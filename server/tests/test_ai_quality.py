import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from app.services import ai_workflows as flow
from app.services.contract_review import analyze
from tests.test_ai_workflows import provider_result


def source(text, sid=1, kind='input', **extra):
    return {'source_id': sid, 'file_id': sid, 'name': f'가상{sid}.txt', 'page': sid, 'kind': kind, 'text': text, **extra}


def finding(quote, **extra):
    return {'category': '손해배상·위약금', 'title': '배상 범위 확인', 'impact': '배상 범위 확인이 필요합니다.',
        'question': '책임 한도를 확인할 수 있을까요?', 'evidence': [{'source_id': 1, 'quote': quote}], **extra}


class ContractContextTests(unittest.TestCase):
    def run_review(self, sources, findings, addressed=None):
        with patch('app.services.ai._chat_json', return_value={'findings': findings, 'addressed': addressed or []}):
            return analyze(json.dumps({'role': '수행사', 'sources': sources}, ensure_ascii=False))

    def test_adjacent_qualification_is_cited_and_unqualified_claim_is_marked_uncertain(self):
        original = '수행사는 간접손해를 포함하여 손해배상 책임을 부담합니다.'
        limit = '다만 손해배상 총액은 계약금액의 100%를 상한으로 합니다.'
        result = self.run_review([source(original+'\n'+limit)], [finding(original)])
        item = result['findings'][0]
        self.assertEqual(item['assessment'], 'uncertain')
        self.assertEqual(item['context_evidence'][0]['quote'], limit)

    def test_ai_can_explain_remaining_burden_with_a_verified_annex(self):
        original = '손해배상은 별첨 조건을 포함해 간접손해에 대해 부담합니다.'
        limit = '손해배상 총액은 계약금액의 100%를 상한으로 합니다.'
        result = self.run_review([source(original), source(limit, 2)], [finding(original,
            context_evidence=[{'source_id': 2, 'quote': limit}], context_note='상한은 있으나 간접손해 포함 범위를 확인하세요.', priority='high')])
        item = result['findings'][0]
        self.assertEqual(item['context_evidence'][0]['source_id'], 2)
        self.assertEqual(item['context_note'], '상한은 있으나 간접손해 포함 범위를 확인하세요.')
        self.assertEqual(item['priority'], 'high')

    def test_other_obligations_cap_does_not_become_a_damages_qualification(self):
        original = '수행사는 간접손해를 포함하여 손해배상 책임을 부담합니다.'
        result = self.run_review([source(original+'\n개발 기간은 30일로 정합니다.')], [finding(original)])
        self.assertEqual(result['findings'][0]['context_evidence'], [])

    def test_addressed_issue_suppresses_rule_rediscovery_only_with_two_verified_quotes(self):
        original = '수행사는 간접손해를 포함하여 손해배상 책임을 부담합니다.'
        limit = '다만 간접손해는 배상 범위에서 제외하며 배상 한도는 계약금액으로 합니다.'
        item = {'category': '손해배상·위약금', 'original': {'source_id': 1, 'quote': original},
            'qualification': {'source_id': 1, 'quote': limit}, 'reason': '예외 조항과 한도를 함께 확인했습니다.'}
        result = self.run_review([source(original+'\n'+limit)], [], [item])
        self.assertEqual(result['findings'], [])
        self.assertEqual(len(result['addressed']), 1)
        item['qualification']['quote'] = '실제 자료에는 없는 한도와 면책 문장입니다.'
        result = self.run_review([source(original)], [], [item])
        self.assertEqual(result['addressed'], [])
        self.assertEqual(result['findings'][0]['method'], 'rule')

    def test_invalid_context_quote_rejects_the_finding(self):
        original = '수행사는 간접손해를 포함하여 손해배상 책임을 부담합니다.'
        result = self.run_review([source(original)], [finding(original, context_evidence=[{'source_id': 9, 'quote': '가짜 예외 조항입니다.'}])])
        self.assertEqual(result['excluded'], 1)
        self.assertTrue(all(item['method'] == 'rule' for item in result['findings']))

    def test_duplicate_citations_merge_questions_and_high_priority_moves_first(self):
        first = '수행사는 손해배상 책임의 한도를 별도로 협의합니다.'
        second = '수행사는 운영 중 손해배상 범위를 추가 협의합니다.'
        rows = [finding(first, priority='low'), finding(first, question='간접손해 포함 여부를 확인할 수 있을까요?'),
            finding(second, evidence=[{'source_id': 2, 'quote': second}], priority='high')]
        result = self.run_review([source(first), source(second, 2)], rows)
        self.assertEqual(result['deduplicated'], 1)
        self.assertEqual(result['findings'][0]['priority'], 'high')
        self.assertIn('간접손해 포함', result['findings'][1]['question'])
        self.assertIn('책임 한도', result['findings'][1]['question'])


class RequirementsQualityTests(unittest.TestCase):
    def test_explicit_login_conflict_is_found_even_when_model_misses_it(self):
        sources=[source('로그인은 이메일과 비밀번호만 사용합니다.'),
            source('로그인 방식은 무엇인가요?\n휴대폰 본인 확인만 사용합니다.',2,'answer',topic='login_method')]
        result=self.run_workflow(sources)
        conflict=next(q for q in result['questions'] if q['intent']=='conflict')
        self.assertEqual({c['source_id'] for c in conflict['evidence']},{1,2})
        self.assertEqual(result['items'][0]['confirmation'],'tentative')
        self.assertIn('서로 다른 조건',result['summary'])

    def test_different_roles_and_alternative_methods_are_not_conflicts(self):
        cases=[('관리자는 이메일로 로그인합니다.','환자는 휴대폰으로 로그인합니다.'),
            ('로그인은 이메일 또는 휴대폰을 사용합니다.','휴대폰으로 로그인합니다.'),
            ('로그인은 이메일과 비밀번호를 사용합니다.','휴대폰 본인 확인으로도 로그인할 수 있습니다.')]
        for a,b in cases:
            with self.subTest(a=a):
                result=self.run_workflow([source(a),source('로그인 방식은 무엇인가요?\n'+b,2,'answer',topic='login_method')])
                self.assertFalse(any(q['intent']=='conflict' for q in result['questions']))

    def test_confirmed_decision_resolves_only_quoted_conflict_and_not_new_conditions(self):
        a='로그인은 이메일과 비밀번호만 사용합니다.'
        b='휴대폰 본인 확인만 사용합니다.'
        sources=[source(a),source('로그인 방식은 무엇인가요?\n'+b,2,'answer',topic='login_method'),
            source('로그인 방식을 무엇으로 확정할까요?\n휴대폰 본인 확인으로 확정합니다.',3,'answer',
                topic='login_method',confirmed=True,resolves=[a,b])]
        def edit(result): result['questions']=[{'question':'어느 로그인 방식인가요?','reason':'두 방식이 다릅니다.','topic':'login_method','intent':'conflict',
            'evidence':[{'source_id':1,'quote':a},{'source_id':2,'quote':b}]}]
        result=self.run_workflow(sources,edit)
        self.assertFalse(any(q['intent']=='conflict' for q in result['questions']))
        sources[0]['text']='로그인은 이메일 아이디와 신규 비밀번호만 사용합니다.'
        self.assertTrue(any(q['intent']=='conflict' for q in self.run_workflow(sources)['questions']))
        sources[0]['text']=a;sources[2]['confirmed']=False
        self.assertTrue(any(q['intent']=='conflict' for q in self.run_workflow(sources)['questions']))

    def run_workflow(self, sources, edit=lambda result: None):
        result = provider_result('requirements', sources); edit(result)
        with patch('app.services.ai._chat_json', return_value=result):
            return flow.analyze('requirements', json.dumps({'sources': sources, 'task': 'requirements', 'role': '수행사', 'current_drafts': []}, ensure_ascii=False))

    def test_paraphrased_login_question_is_suppressed_but_security_followup_remains(self):
        sources = [source('사용자가 예약할 수 있는 사이트를 만듭니다.'),
            source('어떤 방식으로 로그인하나요?\n휴대폰 본인 확인을 사용합니다.', 2, 'answer')]
        def edit(result):
            result['questions'] = [{'question': '로그인 방법을 정해 주실 수 있나요?', 'reason': '방식 확인', 'topic': 'login_method'},
                {'question': '로그인 실패 시 보안 잠금 정책은 무엇인가요?', 'reason': '잠금 확인', 'topic': 'login_security'}]
        result = self.run_workflow(sources, edit)
        self.assertEqual([q['topic'] for q in result['questions']], ['login_security'])

    def test_unknown_answers_do_not_silently_remove_needed_questions(self):
        for answer in ('아직 미정입니다.', '모르겠습니다.', '추후 협의 중입니다.'):
            with self.subTest(answer=answer):
                sources = [source('사용자가 예약할 수 있는 사이트를 만듭니다.'), source('로그인 방식은 무엇인가요?\n'+answer, 2, 'answer')]
                def edit(result): result['questions'] = [{'question': '로그인 방식은 무엇인가요?', 'reason': '방식 확인'}]
                self.assertEqual(len(self.run_workflow(sources, edit)['questions']), 1)

    def test_grounded_followup_can_ask_new_detail_on_an_answered_topic(self):
        answer='예약 하루 전까지 취소합니다.'
        sources=[source('사용자가 예약할 수 있는 사이트를 만듭니다.'),
            source('취소 기한은 언제인가요?\n'+answer,2,'answer',topic='cancellation_deadline')]
        def edit(result):result['questions']=[{'question':'하루 전 취소 마감의 기준 시각은 언제인가요?','reason':'기한은 정해졌지만 시각은 미정입니다.',
            'topic':'cancellation_deadline','intent':'followup','evidence':[{'source_id':2,'quote':answer}]}]
        self.assertEqual(self.run_workflow(sources,edit)['questions'][0]['intent'],'followup')

    def test_conflict_question_is_retained_even_for_an_answered_topic(self):
        a = '로그인은 이메일 비밀번호 방식으로 합니다.'
        b = '로그인 방식은 무엇인가요?\n휴대폰 본인 확인으로 로그인합니다.'
        sources = [source(a, confirmed=True), source(b, 2, 'answer', confirmed=True, topic='login_method')]
        def edit(result):
            result['questions'] = [{'question': '로그인은 이메일과 휴대폰 중 무엇으로 확정할까요?', 'reason': '서로 다른 방식입니다.',
                'topic': 'login_method', 'intent': 'conflict', 'evidence': [{'source_id': 1, 'quote': a}, {'source_id': 2, 'quote': '휴대폰 본인 확인으로 로그인합니다.'}]}]
        result = self.run_workflow(sources, edit)
        self.assertEqual(result['questions'][0]['intent'], 'conflict')
        self.assertEqual(result['items'][0]['confirmation'], 'tentative')
        self.assertTrue(result['quality_notes'])

    def test_conflict_requires_real_distinct_quotes(self):
        def edit(result):
            result['questions'] = [{'question': '어느 조건인가요?', 'reason': '충돌입니다.', 'intent': 'conflict', 'evidence': []}]
        with self.assertRaises(HTTPException) as error:
            self.run_workflow([source('사용자가 예약할 수 있는 사이트를 만듭니다.')], edit)
        self.assertEqual(error.exception.status_code, 502)

    def test_confirmation_comes_from_explicit_source_flags_not_ai_claims(self):
        text = '사용자가 예약할 수 있는 사이트를 만듭니다.'
        result = self.run_workflow([source(text, confirmed=False)], lambda r: r['items'][0].update(confirmation='confirmed'))
        self.assertEqual(result['items'][0]['confirmation'], 'tentative')
        result = self.run_workflow([source(text, confirmed=True)])
        self.assertEqual(result['items'][0]['confirmation'], 'confirmed')
        result = self.run_workflow([source(text, confirmed=True)], lambda r: r['items'][0].update(basis='proposal', confirmation='confirmed'))
        self.assertEqual(result['items'][0]['confirmation'], 'proposal')

    def test_vague_acceptance_is_marked_for_measurable_elaboration(self):
        def edit(result): result['drafts']['scope']['sections'] = [{'label': '검수 기준', 'text': '모든 기능이 정상 작동하고 요구사항을 충족해야 합니다.'}]
        result = self.run_workflow([source('사용자가 예약할 수 있는 사이트를 만듭니다.')], edit)
        scope = next(d for d in result['drafts'] if d['kind'] == 'scope')
        text = next(s['text'] for s in scope['sections'] if s['label'] == '검수 기준')
        self.assertIn('[확인 필요]', text); self.assertIn('기대 결과', text)
        self.assertTrue(any(q['topic'] == 'acceptance' for q in result['questions']))
