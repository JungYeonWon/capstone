import json
import logging
import os
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import Base, get_db
from app.core.encryption import cipher
from app.core.security import hash_password
from app.models import User, Company, Contract, Document, Template, WorkspaceState
from app.services import ai_workflows as flow, custom_plans
from main import app
from tests.auth_helpers import PASSWORD, auth_headers

logging.getLogger('httpx2').setLevel(logging.WARNING)
HASH = hash_password(PASSWORD)


def fake_result(mode, sources):
    first = next(s for s in sources if s['kind'] == 'input')
    evidence = [{'source_id': first['source_id'], 'quote': first['text']}]
    category = {'change': 'scope_additional', 'requirements': 'feature', 'meeting': 'discussion'}[mode]
    kinds = {'change': ['change_agreement', 'followup_email'], 'requirements': ['scope', 'estimate'],
             'meeting': ['meeting_minutes', 'followup_email']}[mode]
    return {'summary': '입력 자료의 확인 사항을 정리했습니다.', 'items': [{
        'category': category, 'title': '확인 사항', 'detail': '범위와 조건은 상대방과 확인해야 합니다.',
        'basis': 'source', 'owner': '', 'due': '', 'evidence': evidence}],
        'questions': [{'question': '검수 기준은 무엇인가요?', 'reason': '확인할 기준이 필요합니다.'}],
        'drafts': [{'kind': kind, 'title': kind + ' 검토 초안', 'sections': [{'label': '확인 사항', 'text': '[확인 필요] 조건을 협의합니다.'}]} for kind in kinds]}


def provider_result(mode, sources):
    result = fake_result(mode, sources)
    result['drafts'] = {draft['kind']: {'title': draft['title'], 'sections': draft['sections']} for draft in result['drafts']}
    if mode == 'meeting': result['drafts']['change_agreement'] = None
    return result


class AIWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'DATA_ENCRYPTION_KEYS': Fernet.generate_key().decode(), 'DATA_ENCRYPTION_KEY_FILE': ''})
        self.env.start(); cipher.cache_clear()
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine); self.db = Session(self.engine)
        self.users = [User(email=f'ai-flow-{i}@example.invalid', password_hash=HASH) for i in (1, 2)]
        self.db.add_all(self.users); self.db.flush()
        self.db.add_all([Company(user_id=u.id, company_name='가상업체', account_number='BANK-SECRET', seal_image='SEAL-SECRET') for u in self.users])
        self.contract = Contract(user_id=self.users[0].id, contract_title='가상 예약 프로젝트', description='환자 예약 화면과 관리자 일정 화면을 개발합니다.')
        self.other = Contract(user_id=self.users[1].id, contract_title='다른 사용자 계약')
        self.db.add_all([self.contract, self.other]); self.db.commit()
        self.headers = [auth_headers(self.db, u.id) for u in self.users]
        def db_override():
            try: yield self.db
            finally: self.db.rollback()
        app.dependency_overrides[get_db] = db_override
        self.client = TestClient(app)
        self.base = f'/api/v1/contracts/{self.contract.id}/ai-workflows'
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.client.close(); app.dependency_overrides.clear(); self.db.close(); self.engine.dispose(); self.env.stop(); cipher.cache_clear()

    def post(self, path, body, user=0): return self.client.post(self.base + path, headers=self.headers[user], json=body)
    def body(self): return {'text': '관리자 통계 화면에 월별 엑셀 다운로드도 추가해주세요.', 'include_contract': True}
    def mock_ai(self, system, payload, **kwargs):
        data = json.loads(payload)
        return provider_result(data['task'], data['sources'])
    def run_ai(self, mode, body=None):
        body = body or self.body()
        with patch.object(settings, 'OPENAI_API_KEY', 'test-only'), patch('app.services.ai._chat_json', side_effect=self.mock_ai) as mock:
            preview = self.post(f'/{mode}/preview', body)
            self.assertEqual(preview.status_code, 200, preview.text)
            result = self.post(f'/{mode}/analyze', {**body, 'consent_digest': preview.json()['consent_digest']})
        self.assertEqual(result.status_code, 200, result.text)
        return preview.json(), result.json(), mock

    def test_all_three_workflows_send_exact_masked_consent_payload(self):
        for mode in ('change', 'requirements', 'meeting'):
            with self.subTest(mode=mode):
                preview, result, mock = self.run_ai(mode)
                self.assertEqual(mock.call_args.args[1], preview['payload_preview'])
                self.assertNotIn('BANK-SECRET', preview['payload_preview'])
                self.assertNotIn('SEAL-SECRET', preview['payload_preview'])
                self.assertEqual(result['consent_digest'], preview['consent_digest'])
                self.assertGreaterEqual(len(result['result']['drafts']), 2)
        self.assertEqual(self.db.scalars(select(Document)).all(), [])

    def test_scope_claim_without_contract_citation_is_downgraded(self):
        _, result, _ = self.run_ai('change')
        self.assertEqual(result['result']['items'][0]['category'], 'scope_unclear')

    def test_change_impact_proposal_still_requires_request_evidence(self):
        sources = [{'source_id': 1, 'kind': 'input', 'text': '통계 기능을 추가할지 협의해 주세요.'}]
        result = flow.WorkflowResult.model_validate(fake_result('change', sources))
        item = result.items[0]; item.category = 'cost'; item.basis = 'proposal'
        flow.validate_result('change', result, sources)
        item.evidence = []
        with self.assertRaises(ValueError): flow.validate_result('change', result, sources)

    def test_provider_schema_requires_evidence_for_change_and_meeting_items(self):
        sources = [{'source_id': 1, 'kind': 'input', 'text': '추가 통계 화면에 대해 협의합니다.'}]
        for mode in ('change', 'meeting'):
            response = provider_result(mode, sources)
            response['items'][0]['evidence'] = []
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                flow.RESPONSES[mode].model_validate(response)

    def test_changed_request_and_changed_reference_require_fresh_consent(self):
        with patch.object(settings, 'OPENAI_API_KEY', 'test-only'), patch('app.services.ai._chat_json') as mock:
            body = self.body(); preview = self.post('/change/preview', body).json()
            response = self.post('/change/analyze', {**body, 'text': '대시보드 전체를 추가해 주세요.', 'consent_digest': preview['consent_digest']})
            self.assertEqual(response.status_code, 400)
            self.contract.description = '변경된 기존 과업입니다.'; self.db.commit()
            self.assertEqual(self.post('/change/analyze', {**body, 'consent_digest': preview['consent_digest']}).status_code, 400)
            mock.assert_not_called()

    def test_change_requires_baseline_and_all_inputs_are_bounded(self):
        self.assertEqual(self.post('/change/preview', {'text': self.body()['text']}).status_code, 422)
        self.assertEqual(self.post('/meeting/preview', {'text': '짧음'}).status_code, 422)
        self.assertEqual(self.post('/requirements/preview', {'text': 'a' * 20001}).status_code, 422)
        body = {'text': 'a' * 20000, 'files': [{'name': '별첨', 'parts': [{'text': 'b' * 15000}], 'kind': 'reference'}]}
        self.assertEqual(self.post('/requirements/preview', body).status_code, 413)
        self.assertEqual(self.post('/unknown/preview', self.body()).status_code, 422)

    def test_followup_answers_are_in_next_exact_payload(self):
        body = {'text': '병원 예약 사이트와 관리자 일정을 만들고 싶습니다.', 'answers': [{'question': '검수 기준은 무엇인가요?', 'text': '동시 예약 중복 방지가 필요합니다.'}]}
        preview, _, mock = self.run_ai('requirements', body)
        self.assertIn('동시 예약 중복 방지', mock.call_args.args[1])
        self.assertEqual(json.loads(preview['payload_preview'])['sources'][-1]['kind'], 'answer')
        self.assertEqual(self.run_ai('requirements', body)[1]['result']['questions'], [])

    def test_omitted_specification_sections_remain_visible_as_unknowns(self):
        _, output, _ = self.run_ai('requirements')
        scope = next(d for d in output['result']['drafts'] if d['kind'] == 'scope')
        for label in ('산출물', '검수 기준', '제외 범위', '일정'):
            section = next(s for s in scope['sections'] if s['label'] == label)
            self.assertIn('[확인 필요]', section['text'])

    def test_minute_sections_do_not_merge_discussion_into_agreements(self):
        _, output, _ = self.run_ai('meeting')
        minutes = next(d for d in output['result']['drafts'] if d['kind'] == 'meeting_minutes')
        self.assertEqual([s['label'] for s in minutes['sections'][:4]], ['합의 후보', '논의 사항', '미결 사항', '후속 업무'])
        self.assertIn('[확인 필요]', minutes['sections'][0]['text'])

    def test_invalid_citation_or_wrong_draft_fails_instead_of_becoming_a_document(self):
        for broken in ('quote', 'kind', 'empty'):
            def bad_ai(system, payload, **kwargs):
                data = json.loads(payload); result = provider_result(data['task'], data['sources'])
                if broken == 'quote': result['items'][0]['evidence'][0]['quote'] = '없는 원문을 만들어낸 문장입니다.'
                if broken == 'kind': result['drafts']['scope'] = result['drafts'].pop('followup_email')
                if broken == 'empty': return None
                return result
            with patch.object(settings, 'OPENAI_API_KEY', 'test-only'), patch('app.services.ai._chat_json', side_effect=bad_ai):
                body = self.body(); preview = self.post('/meeting/preview', body).json()
                self.assertEqual(self.post('/meeting/analyze', {**body, 'consent_digest': preview['consent_digest']}).status_code, 502)
        self.assertEqual(self.db.scalars(select(Document)).all(), [])

    def test_meeting_cannot_use_contract_as_meeting_evidence_or_invent_task_owner(self):
        sources = [{'source_id': 1, 'kind': 'input', 'text': '김담당이 금요일까지 질문 목록을 보냅니다.'}]
        result = flow.WorkflowResult.model_validate(fake_result('meeting', sources))
        item = result.items[0]; item.category = 'task'; item.owner = '없는 담당자'; item.due = '2027-01-01'
        flow.validate_result('meeting', result, sources)
        self.assertEqual((item.owner, item.due), ('', ''))
        item.owner = '김담당'; item.due = '금요일'; flow.validate_result('meeting', result, sources)
        self.assertEqual((item.owner, item.due), ('김담당', '금요일'))
        sources[0]['kind'] = 'reference'
        with self.assertRaises(ValueError): flow.validate_result('meeting', result, sources)

    def test_saved_sessions_are_encrypted_separate_and_revision_protected(self):
        _, output, _ = self.run_ai('requirements')
        payload = {'input': self.body(), 'output': output, 'estimate_lines': [], 'output_stale': False}
        path = self.base + '/requirements/session'
        saved = self.client.put(path, headers=self.headers[0], json={'payload': payload, 'revision': 0})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(self.client.get(path, headers=self.headers[0]).json()['payload']['output'], output)
        self.assertEqual(self.client.put(path, headers=self.headers[0], json={'payload': payload, 'revision': 0}).status_code, 409)
        self.assertIsNone(self.client.get(self.base + '/meeting/session', headers=self.headers[0]).json()['payload'])
        raw = self.db.execute(text('SELECT payload FROM workspace_states')).all()
        self.assertNotIn(self.body()['text'], str(raw)); self.assertIn('_cdoc_encrypted_v1', str(raw))

    def test_files_can_supply_input_and_reference_without_external_send(self):
        response = self.client.post(self.base + '/extract', headers=self.headers[0], files={'file': ('회의.txt', '교육을 온라인으로 진행할지 다음 회의에서 정합니다.'.encode(), 'text/plain')})
        self.assertEqual(response.status_code, 200, response.text)
        file = {**response.json(), 'kind': 'input'}
        with patch('app.services.ai._chat_json') as mock:
            preview = self.post('/meeting/preview', {'files': [file]})
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertEqual(json.loads(preview.json()['payload_preview'])['sources'][0]['kind'], 'input')
            mock.assert_not_called()

    def test_other_users_and_csrf_cannot_access_any_workflow(self):
        for mode in ('change', 'requirements', 'meeting'):
            self.assertEqual(self.post(f'/{mode}/preview', self.body(), 1).status_code, 404)
            self.assertEqual(self.post(f'/{mode}/analyze', self.body(), 1).status_code, 404)
            path = self.base + f'/{mode}/session'
            self.assertEqual(self.client.get(path, headers=self.headers[1]).status_code, 404)
            self.assertEqual(self.client.put(path, headers=self.headers[1], json={'payload': {'input': self.body()}, 'revision': 0}).status_code, 404)
        draft = {'kind': 'scope', 'title': '검토 초안', 'sections': [{'label': '범위', 'text': '[확인 필요]'}]}
        self.assertEqual(self.post('/requirements/documents', {'draft': draft, 'acknowledge_draft': True}, 1).status_code, 404)
        self.assertEqual(self.client.post(self.base + '/meeting/preview', headers={'Cookie': self.headers[0]['Cookie']}, json=self.body()).status_code, 403)

    def test_another_contracts_document_is_rejected(self):
        layout = custom_plans.local_layout('가상 요청', 'free', '타인 계약 문서')
        template = Template(kind='custom', owner_id=self.users[1].id, name=layout.title, definition=custom_plans.definition(layout, '', 'user_reviewed'), fields=[])
        self.db.add(template); self.db.flush()
        document = Document(contract_id=self.other.id, template_id=template.id, title=layout.title, values={})
        self.db.add(document); self.db.commit()
        self.assertEqual(self.post('/change/preview', {**self.body(), 'document_id': document.id}).status_code, 404)

    def test_explicit_conversion_creates_editable_draft_without_changing_contract(self):
        for mode in ('change', 'requirements', 'meeting'):
            _, output, _ = self.run_ai(mode)
            draft = output['result']['drafts'][0]
            self.assertEqual(self.post(f'/{mode}/documents', {'draft': draft}).status_code, 400)
            response = self.post(f'/{mode}/documents', {'draft': draft, 'acknowledge_draft': True})
            self.assertEqual(response.status_code, 200, response.text)
            doc = self.db.get(Document, response.json()['document']['id'])
            self.assertEqual(doc.status, 'draft'); self.assertEqual(doc.template.kind, 'custom')
            self.assertIn('[검토용 초안]', doc.values['custom_1'])
            self.assertTrue(response.json()['document']['requires_seal_approval'])
            self.assertEqual(self.client.get(f'/api/v1/documents/{doc.id}/preview', headers=self.headers[0]).status_code, 200)
        self.assertEqual(self.contract.description, '환자 예약 화면과 관리자 일정 화면을 개발합니다.')

    def test_estimate_totals_use_input_decimals_and_are_in_saved_document(self):
        lines = [{'label': '기능 개발', 'quantity': '1.25', 'unit': '일', 'unit_price': '123.45'}, {'label': '점검', 'quantity': '0.5', 'unit': '일', 'unit_price': '0.01'}]
        result = flow.estimate([flow.EstimateLine.model_validate(line) for line in lines])
        self.assertEqual(result, {'amounts': ['154.31', '0.01'], 'total': '154.32'})
        draft = {'kind': 'estimate', 'title': '가상 견적', 'sections': [{'label': '산정 전제', 'text': '[협의 필요] 작업 범위 확인'}]}
        self.assertEqual(self.post('/requirements/documents', {'draft': draft, 'acknowledge_draft': True}).status_code, 422)
        response = self.post('/requirements/documents', {'draft': draft, 'acknowledge_draft': True, 'estimate_lines': lines})
        self.assertEqual(response.status_code, 200, response.text)
        values = response.json()['document']['values']
        self.assertIn('합계: 154.32원', values['custom_2'])
        self.assertIn('부가세·할인 미적용', values['custom_2'])
        self.assertEqual(self.post('/requirements/documents', {'draft': draft, 'acknowledge_draft': True, 'estimate_lines': [{**lines[0], 'quantity': '-1'}]}).status_code, 422)
        self.assertEqual(self.post('/requirements/documents', {'draft': draft, 'acknowledge_draft': True, 'estimate_lines': [{**lines[0], 'unit_price': '100000001'}]}).status_code, 422)
