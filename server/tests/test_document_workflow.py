"""Cross-account, consent, persistence, versioning and submission workflow regressions."""
import io
import logging
import os
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch

import pymupdf
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import Base, get_db
from app.core.encryption import cipher
from app.core.security import hash_password
from app.models import Company, Contract, Document, Template, User, WorkspaceState
from app.services import custom_plans
from main import app, maintenance
from tests.auth_helpers import PASSWORD, auth_headers, approve

logging.getLogger('httpx2').setLevel(logging.WARNING)
HASH=hash_password(PASSWORD)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.environment=patch.dict(os.environ,{'DATA_ENCRYPTION_KEYS':Fernet.generate_key().decode(),'DATA_ENCRYPTION_KEY_FILE':''})
        self.environment.start(); cipher.cache_clear()
        self.engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
        Base.metadata.create_all(self.engine); self.db=Session(self.engine)
        self.users=[User(email=f'workflow-{i}@example.invalid',password_hash=HASH) for i in (1,2)]
        self.db.add_all(self.users);self.db.flush()
        self.db.add_all([Company(user_id=u.id,company_name='가상업체',manager_name='가상담당',account_number='BANK-SECRET') for u in self.users])
        self.contract=Contract(user_id=self.users[0].id,contract_title='가상 계약',client_name='가상 기관',description='접근성 점검과 관리자 교육을 수행한다.',start_date=date(2026,11,1),end_date=date(2026,12,1))
        self.db.add(self.contract);self.db.commit()
        self.headers=[auth_headers(self.db,u.id) for u in self.users]
        def db_override():
            try: yield self.db
            finally: self.db.rollback()
        app.dependency_overrides[get_db]=db_override
        self.client=TestClient(app)
        self.base=f'/api/v1/contracts/{self.contract.id}'
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.client.close();app.dependency_overrides.clear();self.db.close();self.engine.dispose()
        self.environment.stop();cipher.cache_clear()

    def post(self,path,body=None,index=0):return self.client.post(path,headers=self.headers[index],json=body)
    def get(self,path,index=0):return self.client.get(path,headers=self.headers[index])
    def put(self,path,body,index=0):return self.client.put(path,headers=self.headers[index],json=body)

    def create(self,kind='work_plan'):
        layout=custom_plans.local_layout('참여인력과 주간 일정이 있는 문서를 만들어줘',kind).model_dump()
        res=self.post(self.base+'/custom-plan',{'request':'검토 가능한 문서를 만들어줘','layout':layout,'acknowledge_unofficial':True})
        self.assertEqual(res.status_code,200,res.text)
        return res.json()['document']

    def test_all_document_types_have_editable_native_and_pdf_outputs(self):
        for kind in custom_plans.DOCUMENT_TYPES:
            doc=self.create(kind)
            template=self.get(f"/api/v1/templates/{doc['template_id']}").json()
            self.assertEqual(template['custom_plan']['layout']['document_type'],kind)
            if kind in ('report','pledge'):
                self.assertEqual(doc['values']['description'],'')
            self.assertEqual(self.get(f"/api/v1/documents/{doc['id']}/download").status_code,200)
            pdf=self.get(f"/api/v1/documents/{doc['id']}/download?format=pdf")
            self.assertTrue(pdf.content.startswith(b'%PDF-'))
        self.assertEqual(self.post(self.base+'/custom-plan/propose',{'request':'문서를 작성해줘','document_type':'arbitrary_html'}).status_code,422)

    def test_private_draft_survives_reload_encrypted_and_rejects_stale_writes(self):
        path=self.base+'/workspace/builder'; payload={'request':'가상 기밀 요청','layout':custom_plans.local_layout('교육 계획').model_dump()}
        self.assertEqual(self.get(path).json()['revision'],0)
        self.assertEqual(self.put(path,{'payload':payload,'revision':0}).json()['revision'],1)
        self.assertEqual(self.get(path).json()['payload'],payload)
        self.assertNotIn('가상 기밀',str(self.db.scalar(text('SELECT payload FROM workspace_states'))))
        self.assertEqual(self.put(path,{'payload':{'request':'다른창'},'revision':0}).status_code,409)
        self.assertEqual(self.get(path).json()['payload'],payload)
        self.assertEqual(self.get(path,1).status_code,404)
        self.assertEqual(self.put(path,{'payload':{},'revision':1},1).status_code,404)
        self.assertEqual(self.client.put(path,headers={'Cookie':self.headers[0]['Cookie']},json={'payload':{},'revision':1}).status_code,403)
        self.assertEqual(self.put(path,{'payload':{'value':'x'*160000},'revision':1}).status_code,413)

    def test_document_drafts_are_scoped_and_not_exported_before_save(self):
        doc=self.create(); path=self.base+f"/workspace/document_{doc['id']}"
        values={**doc['values'],'description':'임시 수정 내용'}
        self.assertEqual(self.put(path,{'payload':{'values':values,'base_updated_at':doc['updated_at']},'revision':0}).status_code,200)
        self.assertNotEqual(self.get(f"/api/v1/documents/{doc['id']}").json()['values']['description'],'임시 수정 내용')
        result=self.post(self.base+'/validate').json()
        self.assertIn('임시 저장 미반영',[i['type'] for i in result['issues']])
        self.assertFalse(result['summary']['ready_for_submission'])
        self.assertEqual(self.put(path,{'payload':{'values':{'seal_image':'injected'}},'revision':1}).status_code,422)
        self.assertEqual(self.get(self.base+'/workspace/document_99999').status_code,404)

    def test_local_draft_questions_answers_and_tables_do_not_fabricate_unknown_facts(self):
        doc=self.create(); path=f"/api/v1/documents/{doc['id']}/draft"
        with patch('app.services.ai._chat_json') as ai:
            preview=self.post(path+'/preview',{}).json()
            self.assertIn('staff_plan',[q['key'] for q in preview['questions']])
            suggestion=self.post(path+'/suggest',{'answers':{'staff_plan':'가상담당 | 책임자 | 점검','work_schedule':'1주 | 점검 준비 | 가상담당'}})
            self.assertEqual(suggestion.status_code,200,suggestion.text)
            ai.assert_not_called()
        self.assertIn('가상담당',suggestion.json()['values']['staff_plan'])
        self.assertNotIn('deliverables',suggestion.json()['values'])
        self.assertEqual(self.get(f"/api/v1/documents/{doc['id']}").json()['values'],doc['values'])
        self.assertEqual(self.post(path+'/suggest',{'answers':{'staff_plan':'가상담당 | too few'}}).status_code,422)
        self.assertEqual(self.post(path+'/suggest',{},index=1).status_code,404)

    def test_body_ai_requires_exact_consent_and_only_proposes_permitted_text(self):
        doc=self.create(); path=f"/api/v1/documents/{doc['id']}/draft"
        body={'answers':{'work_method':'점검 후 교육한다. 이메일 fictional@example.invalid'}}
        with patch.object(settings,'OPENAI_API_KEY','test-only'),patch('app.services.ai._chat_json',return_value={'values':{'work_method':'접근성 점검을 수행하고 관리자 교육을 진행합니다.','seal_image':'attack','staff_plan':'fabricated person'}}) as ai:
            preview=self.post(path+'/preview',body).json()
            self.assertNotIn('BANK-SECRET',preview['payload_preview'])
            self.assertNotIn('fictional@example.invalid',preview['payload_preview'])
            self.assertEqual(self.post(path+'/suggest',{**body,'use_ai':True}).status_code,400)
            ai.assert_not_called()
            result=self.post(path+'/suggest',{**body,'use_ai':True,'consent_digest':preview['consent_digest']})
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(ai.call_args.args[1],preview['payload_preview'])
            self.assertTrue(result.json()['values']['work_method'].startswith('[검토용 제안]'))
            self.assertNotIn('seal_image',result.json()['values']);self.assertNotIn('staff_plan',result.json()['values'])
            self.assertEqual(self.post(path+'/suggest',{'answers':{'work_method':'다른 내용'},'use_ai':True,'consent_digest':preview['consent_digest']}).status_code,400)

    def test_body_ai_failure_is_explicit_and_leaves_document_unchanged(self):
        doc=self.create();path=f"/api/v1/documents/{doc['id']}/draft"
        with patch.object(settings,'OPENAI_API_KEY','test-only'),patch('app.services.ai._chat_json',return_value=None):
            preview=self.post(path+'/preview',{}).json()
            result=self.post(path+'/suggest',{'use_ai':True,'consent_digest':preview['consent_digest']}).json()
            self.assertEqual(result['mode'],'rule_fallback');self.assertTrue(result['warning'])
        self.assertEqual(self.get(f"/api/v1/documents/{doc['id']}").json()['values'],doc['values'])

    def test_body_structured_response_uses_section_keys_and_rejects_other_fields(self):
        from app.services.document_workflow import BodyResponse
        doc=self.create();path=f"/api/v1/documents/{doc['id']}/draft"
        response={'values':[{'key':'work_method','text':'확인된 절차로 점검합니다.'},
                            {'key':'수행 방법','text':'wrong label'},
                            {'key':'staff_plan','text':'fabricated table'},
                            {'key':'seal_image','text':'forbidden'}]}
        with patch.object(settings,'OPENAI_API_KEY','test-only'),patch('app.services.ai._chat_json',return_value=response) as ai:
            preview=self.post(path+'/preview',{}).json()
            result=self.post(path+'/suggest',{'use_ai':True,'consent_digest':preview['consent_digest']}).json()
            self.assertEqual(result['mode'],'ai')
            self.assertIs(ai.call_args.kwargs['response_model'],BodyResponse)
            self.assertEqual(result['values']['work_method'],'[검토용 제안] 확인된 절차로 점검합니다.')
            for key in ('수행 방법','staff_plan','seal_image'):self.assertNotIn(key,result['values'])

    def test_report_results_and_pledge_obligations_stay_blank_without_user_answers(self):
        for kind in ('report','pledge'):
            doc=self.create(kind)
            result=self.post(f"/api/v1/documents/{doc['id']}/draft/suggest",{}).json()
            self.assertNotIn('description',result['values'])
            contract_data={'contract_title':'변경된 가상 계약','client_name':'가상기관','description':'수정된 업무범위','amount':0}
            self.assertEqual(self.put(self.base,contract_data).status_code,200)
            self.assertEqual(self.get(f"/api/v1/documents/{doc['id']}").json()['values']['description'],'')

    def test_notice_rules_manual_attachments_and_checklist_validation(self):
        text_='제출 서류\n1. 착수신고서 제출\n2. 사업자등록증 사본 첨부\n3. 해당 시 사용인감계 제출\n4. 특수장비 검사확인서 첨부'
        with patch('app.services.ai._chat_json') as ai:
            result=self.post(self.base+'/notice/analyze',{'text':text_}).json();ai.assert_not_called()
        self.assertTrue(any(i['title']=='착수계' for i in result['items']))
        self.assertFalse(any(i['title'].replace(' ','')=='제출서류' for i in result['items']))
        self.assertTrue(any(i['title']=='사업자등록증' for i in result['items']))
        self.assertFalse(next(i['required'] for i in result['items'] if i['title']=='사용인감계'))
        self.assertEqual(self.put(self.base+'/workspace/notice',{'payload':{'text':text_,'items':result['items']},'revision':0}).status_code,200)
        validation=self.post(self.base+'/validate').json()
        self.assertIn('체크리스트 미완료',[i['type'] for i in validation['issues']])
        for i in result['items']:i['done']=True
        self.assertEqual(self.put(self.base+'/workspace/notice',{'payload':{'text':text_,'items':result['items']},'revision':1}).status_code,200)
        self.assertNotIn('체크리스트 미완료',[i['type'] for i in self.post(self.base+'/validate').json()['issues']])

    def test_notice_ai_evidence_and_consent_reject_hallucinated_requirements(self):
        text_='제출서류: 착수계\n1. 현장방문계획서 첨부'
        fake={'items':[{'title':'현장방문계획서','evidence':'1. 현장방문계획서 첨부'},{'title':'없는 서류','evidence':'원문에 없는 근거'}]}
        with patch.object(settings,'OPENAI_API_KEY','test-only'),patch('app.services.ai._chat_json',return_value=fake) as ai:
            preview=self.post(self.base+'/notice/preview',{'text':text_}).json()
            self.assertEqual(self.post(self.base+'/notice/analyze',{'text':text_,'use_ai':True}).status_code,400)
            ai.assert_not_called()
            result=self.post(self.base+'/notice/analyze',{'text':text_,'use_ai':True,'consent_digest':preview['consent_digest']}).json()
            self.assertNotIn('없는 서류',str(result))
            self.assertEqual(ai.call_args.args[1],preview['payload_preview'])
            self.assertEqual(self.post(self.base+'/notice/analyze',{'text':text_+' 변경','use_ai':True,'consent_digest':preview['consent_digest']}).status_code,400)

    def test_notice_pdf_extract_rejects_invalid_encrypted_and_oversize_inputs(self):
        path=self.base+'/notice/extract'
        pdf=pymupdf.open();page=pdf.new_page();page.insert_text((72,72),'Required: report attachment.');data=pdf.tobytes();pdf.close()
        result=self.client.post(path,headers=self.headers[0],files={'file':('notice.pdf',data,'application/pdf')})
        self.assertEqual(result.status_code,200,result.text);self.assertIn('report',result.json()['text'])
        self.assertEqual(self.client.post(path,headers=self.headers[0],files={'file':('fake.pdf',b'not a pdf','application/pdf')}).status_code,422)
        self.assertEqual(self.client.post(path,headers=self.headers[0],files={'file':('big.pdf',b'%PDF-'+b'x'*(3*1024*1024),'application/pdf')}).status_code,413)
        self.assertEqual(self.client.post(path,headers=self.headers[1],files={'file':('notice.pdf',data,'application/pdf')}).status_code,404)
        self.assertEqual(self.db.query(WorkspaceState).count(),0)

    def test_versions_are_private_immutable_and_reusable_without_previous_values(self):
        doc=self.create();old=self.db.get(Template,doc['template_id']);original=old.definition.copy()
        layout=custom_plans.PlanLayout.model_validate(old.definition['custom_plan']['layout']);layout.title='새 버전 가상 양식';layout.sections[2].label='수정한 수행 방법'
        path=f'/api/v1/templates/{old.id}/versions'
        result=self.post(path,{'layout':layout.model_dump(),'note':'항목명 수정'})
        self.assertEqual(result.status_code,200,result.text);new=result.json()
        self.assertEqual(new['custom_plan']['version'],2)
        self.assertEqual(self.get(path,1).status_code,404)
        self.assertEqual(self.post(path,{'layout':layout.model_dump()},1).status_code,404)
        self.db.refresh(old);self.assertEqual(old.definition,original)
        self.assertEqual(self.db.get(Document,doc['id']).template_id,old.id)
        self.assertEqual(len(self.get(path).json()),2)
        added=self.post(self.base+'/documents',{'template_id':new['id']})
        self.assertEqual(added.status_code,200,added.text)
        self.assertNotIn('수정한 수행 방법',str(self.get(f"/api/v1/documents/{doc['id']}").json()['values']))

    def test_notice_facts_persist_and_changed_source_requires_reanalysis(self):
        source='제출서류: 착수계\n제출기한: 계약 후 7일 이내\n제출방법: 이메일 접수'
        result=self.post(self.base+'/notice/analyze',{'text':source}).json()
        payload={'text':source,'analyzed_text':source,'items':result['items'],'facts':result['facts']}
        for item in payload['items']:item['done']=True
        self.assertEqual(self.put(self.base+'/workspace/notice',{'payload':payload,'revision':0}).status_code,200)
        self.assertEqual(self.get(self.base+'/workspace/notice').json()['payload']['facts'],result['facts'])
        types=lambda:[i['type'] for i in self.post(self.base+'/validate').json()['issues']]
        self.assertNotIn('안내문 재분석 필요',types())
        payload['text']+='\n추가 안내: 산출내역서 제출'
        self.assertEqual(self.put(self.base+'/workspace/notice',{'payload':payload,'revision':1}).status_code,200)
        self.assertIn('안내문 재분석 필요',types())
        self.assertFalse(self.post(self.base+'/validate').json()['summary']['ready_for_submission'])


    def test_notice_template_matching_is_local_and_issuer_scoped(self):
        template=Template(kind='builtin',name='착수계',aliases=['착수신고서'],definition={},status='ready')
        self.db.add(template)
        other=Template(kind='uploaded',name='착수계',definition={'library':{'scope':'organization','organization':'다른 기관'}},status='ready')
        self.db.add(other);self.db.commit()
        with patch('app.services.ai._chat_json') as ai:
            result=self.get(self.base+'/notice/templates?title=착수신고서')
            ai.assert_not_called()
        self.assertEqual(result.status_code,200,result.text)
        ids=[m['template']['id'] for m in result.json()]
        self.assertIn(template.id,ids);self.assertNotIn(other.id,ids)
        self.assertEqual(self.get(self.base+'/notice/templates?title=착수계',1).status_code,404)

    def test_notice_txt_and_partial_scan_pdf_report_extraction_limits(self):
        path=self.base+'/notice/extract'
        source='제출서류: 착수계\n제출기한: 계약 후 7일 이내'
        result=self.client.post(path,headers=self.headers[0],files={'file':('notice.txt',source.encode('utf-8-sig'),'text/plain')})
        self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json()['text'],source)
        invalid=self.client.post(path,headers=self.headers[0],files={'file':('notice.txt',b'\xff\xfe\x00','text/plain')})
        self.assertEqual(invalid.status_code,422)
        pdf=pymupdf.open();pdf.new_page().insert_text((72,72),'Submission documents: start report');pdf.new_page()
        result=self.client.post(path,headers=self.headers[0],files={'file':('notice.pdf',pdf.tobytes(),'application/pdf')});pdf.close()
        self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json()['pages'],2)
        self.assertIn('2',result.json()['warning'])

    def test_notice_office_uploads_are_private_and_do_not_store_originals(self):
        from tests.test_notice_files import word_notice, hwpx_notice, hwp_notice
        path=self.base+'/notice/extract'
        for name,data in [('notice.docx',word_notice()),('notice.hwpx',hwpx_notice()),('notice.hwp',hwp_notice())]:
            with self.subTest(name=name):
                result=self.client.post(path,headers=self.headers[0],files={'file':(name,data,'application/octet-stream')})
                self.assertEqual(result.status_code,200,result.text)
                self.assertIn('착수신고서',result.json()['text'])
                denied=self.client.post(path,headers=self.headers[1],files={'file':(name,data,'application/octet-stream')})
                self.assertEqual(denied.status_code,404)
        self.assertEqual(self.db.query(WorkspaceState).count(),0)

    def test_submission_detects_review_markers_partial_tables_and_malformed_rows(self):
        doc=self.create();values={'work_method':'[검토용 제안] 확인할 문구','staff_plan':'가상담당 | | 점검'}
        self.put(f"/api/v1/documents/{doc['id']}",{'values':values})
        result=self.post(self.base+'/validate').json();types=[i['type'] for i in result['issues']]
        self.assertIn('검토 필요 문구',types);self.assertIn('표 빈칸',types)
        self.assertFalse(result['summary']['ready_for_submission'])
        self.put(f"/api/v1/documents/{doc['id']}",{'values':{'staff_plan':'too | few'}})
        self.assertIn('표 형식',[i['type'] for i in self.post(self.base+'/validate').json()['issues']])

    def test_contract_and_privacy_deletion_remove_working_copies_and_draft_retention(self):
        self.put(self.base+'/workspace/builder',{'payload':{'request':'가상 기밀'},'revision':0})
        state=self.db.get(WorkspaceState,(self.contract.id,'builder'));state.updated_at=datetime.utcnow()-timedelta(days=31);self.db.commit()
        maintenance(self.db);self.assertIsNone(self.db.get(WorkspaceState,(self.contract.id,'builder')))
        self.put(self.base+'/workspace/builder',{'payload':{'request':'가상 기밀'},'revision':0})
        approved=approve(self.client,self.headers[0],'data:delete')
        result=self.client.delete('/api/v1/privacy/data',headers=approved)
        self.assertEqual(result.status_code,200,result.text);self.assertEqual(self.db.query(WorkspaceState).count(),0)


if __name__=='__main__':unittest.main()
