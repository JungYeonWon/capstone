"""End-to-end custom-plan routes, privacy boundaries and native rendering."""
import io
import json
import logging
import unittest
from datetime import date
from unittest.mock import patch
from zipfile import ZipFile

import pymupdf
from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import Base,get_db
from app.core.security import hash_password
from app.models import Company,Contract,Document,Template,User,LibraryAdmin,AuditLog
from app.services import custom_plans
from app.services.seal import normalize_seal
from main import app
from tests.auth_helpers import PASSWORD,auth_headers,approve

_HASH=hash_password(PASSWORD)
logging.getLogger('httpx2').setLevel(logging.WARNING)


class CustomPlanTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db=Session(self.engine)
        self.users=[User(email=f'custom-{i}@example.invalid',password_hash=_HASH) for i in (1,2)]
        self.db.add_all(self.users);self.db.flush()
        self.db.add_all([Company(user_id=u.id,company_name=f'비공개업체-{u.id}',representative='가상대표',address='가상주소') for u in self.users])
        self.contract=Contract(user_id=self.users[0].id,contract_title='비공개계약명',client_name='가상발주처',description='확인된 계약 업무내용',start_date=date(2026,11,1),end_date=date(2026,11,30))
        self.db.add(self.contract);self.db.commit()
        self.headers=[auth_headers(self.db,u.id) for u in self.users]
        app.dependency_overrides[get_db]=lambda:self.db
        self.client=TestClient(app)
        self.request='참여인력표와 주간 추진 일정, 산출물 목록이 있는 과업수행계획서를 만들어줘'
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.client.close();app.dependency_overrides.clear();self.db.close();self.engine.dispose()

    @property
    def base(self):return f'/api/v1/contracts/{self.contract.id}/custom-plan'

    def layout(self):
        response=self.client.post(self.base+'/propose',headers=self.headers[0],json={'document_type':'work_plan','request':self.request})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()['layout']

    def create(self,layout=None):
        response=self.client.post(self.base,headers=self.headers[0],json={'request':self.request,'layout':layout or self.layout(),'acknowledge_unofficial':True})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def test_local_proposal_makes_real_tables_without_external_ai_or_persistence(self):
        with patch.object(settings,'OPENAI_API_KEY','test-only'),patch('app.services.ai._chat_json') as ai:
            layout=self.layout();ai.assert_not_called()
        sections={s['key']:s for s in layout['sections']}
        self.assertEqual(sections['work_schedule']['kind'],'table')
        self.assertEqual(sections['staff_plan']['columns'],['성명/직위','역할','담당 업무'])
        self.assertEqual(self.db.query(Template).count(),0)
        self.assertEqual(self.db.query(Document).count(),0)

    def test_create_requires_explicit_unofficial_acknowledgement(self):
        response=self.client.post(self.base,headers=self.headers[0],json={'request':self.request,'layout':self.layout()})
        self.assertEqual(response.status_code,400)
        self.assertEqual(self.db.query(Template).count(),0)

    def test_other_accounts_and_anonymous_cannot_propose_or_create(self):
        layout=self.layout()
        for suffix,payload in [('/propose',{'request':self.request}),('/transmission',{'request':self.request}),('',{'request':self.request,'layout':layout,'acknowledge_unofficial':True})]:
            self.assertEqual(self.client.post(self.base+suffix,headers=self.headers[1],json=payload).status_code,404)
            self.assertEqual(self.client.post(self.base+suffix,json=payload).status_code,401)

    def test_layout_validation_blocks_arbitrary_renderer_types_and_field_keys(self):
        original=self.layout()
        for mutate in ('type','key','duplicate','missing','columns','extra'):
            layout=json.loads(json.dumps(original))
            if mutate=='type':layout['sections'][0]['kind']='raw_html'
            if mutate=='key':layout['sections'][0]['key']='account_number'
            if mutate=='duplicate':layout['sections'].append(layout['sections'][0])
            if mutate=='missing':layout['sections']=layout['sections'][2:]
            if mutate=='columns':layout['sections'][4]['columns']=['only-one']
            if mutate=='extra':layout['source_path']='/etc/passwd'
            response=self.client.post(self.base,headers=self.headers[0],json={'request':self.request,'layout':layout,'acknowledge_unofficial':True})
            self.assertEqual(response.status_code,422,mutate)

    def test_external_ai_requires_exact_preview_and_receives_no_company_or_contract(self):
        request=self.request+' 연락은 fictional@example.invalid 로 해줘'
        with patch.object(settings,'OPENAI_API_KEY','test-only'),patch('app.services.ai._chat_json',return_value=custom_plans.local_layout(request).model_dump()) as ai:
            preview=self.client.post(self.base+'/transmission',headers=self.headers[0],json={'document_type':'work_plan','request':request}).json()
            self.assertNotIn('fictional@example.invalid',preview['payload_preview'])
            self.assertNotIn('비공개업체',preview['payload_preview']);self.assertNotIn('비공개계약명',preview['payload_preview'])
            self.assertEqual(self.client.post(self.base+'/propose',headers=self.headers[0],json={'document_type':'work_plan','request':request,'use_ai':True}).status_code,400)
            ai.assert_not_called()
            response=self.client.post(self.base+'/propose',headers=self.headers[0],json={'document_type':'work_plan','request':request,'use_ai':True,'consent_digest':preview['consent_digest']})
            self.assertEqual(response.status_code,200);self.assertEqual(response.json()['mode'],'ai')
            self.assertEqual(ai.call_args.args[1],preview['payload_preview'])
            self.assertEqual(self.client.post(self.base+'/propose',headers=self.headers[0],json={'document_type':'work_plan','request':request+'変更','use_ai':True,'consent_digest':preview['consent_digest']}).status_code,400)

    def test_invalid_ai_layout_falls_back_without_executing_renderer_instructions(self):
        with patch.object(settings,'OPENAI_API_KEY','test-only'),patch('app.services.ai._chat_json',return_value={'sections':[{'kind':'raw_html','html':'<script>attack()</script>'}]}):
            preview=custom_plans.transfer(self.request)
            response=self.client.post(self.base+'/propose',headers=self.headers[0],json={'document_type':'work_plan','request':self.request,'use_ai':True,'consent_digest':preview['consent_digest']})
            self.assertEqual(response.status_code,200);self.assertEqual(response.json()['mode'],'rule_fallback')
            self.assertNotIn('<script>',str(response.json()['layout']))

    def test_only_relevant_matching_designated_work_plans_are_recommended(self):
        def template(name,doc_type,code='',owner=None,scope='organization'):
            return Template(name=name,kind='uploaded',owner_id=owner,status='ready',definition={'library':{'scope':scope,'organization':'가상발주처','document_type':doc_type,'project_code':code}})
        candidates=[template('해당사업 계획서','과업수행계획서','BID-1'),template('다른사업 계획서','과업수행계획서','BID-2'),template('사용인감계','사용인감계'),template('타인 비공개 계획서','과업수행계획서',owner=self.users[1].id,scope='private')]
        self.db.add_all(candidates);self.db.commit()
        response=self.client.post(self.base+'/propose',headers=self.headers[0],json={'document_type':'work_plan','request':self.request,'project_code':'BID-1'})
        self.assertEqual([row['name'] for row in response.json()['matches']],['해당사업 계획서'])
        self.assertEqual(self.client.post(self.base+'/propose',headers=self.headers[0],json={'document_type':'work_plan','request':self.request}).json()['matches'],[])

    def test_created_layout_private_encrypted_and_unknown_staff_dates_remain_empty(self):
        result=self.create();doc=result['document']
        self.assertEqual(doc['template_kind'],'custom');self.assertIn('company_name',doc['field_keys'])
        self.assertEqual(doc['values']['description'],'확인된 계약 업무내용')
        self.assertEqual(doc['values']['staff_plan'],'');self.assertEqual(doc['values']['work_schedule'],'')
        self.assertIn('staff_plan',doc['missing'])
        raw=self.db.execute(text('SELECT definition FROM templates WHERE id=:id'),{'id':result['template_id']}).scalar()
        self.assertNotIn(self.request,str(raw))
        self.db.add(LibraryAdmin(user_id=self.users[1].id));self.db.commit()
        self.assertEqual(self.client.get(f"/api/v1/templates/{result['template_id']}",headers=self.headers[1]).status_code,404)
        self.assertEqual(self.client.get(f"/api/v1/documents/{doc['id']}/download?format=native",headers=self.headers[1]).status_code,404)

    def test_edited_layout_and_table_values_survive_hwpx_pdf_preview_and_zip(self):
        layout=self.layout();layout['title']='요청한 주간 업무계획'
        layout['sections'][4]['label']='담당 인력표'
        layout['sections'].append({'key':'custom_1','label':'추가 확인사항','kind':'text','columns':[],'required':False})
        result=self.create(layout);id_=result['document']['id']
        response=self.client.put(f'/api/v1/documents/{id_}',headers=self.headers[0],json={'values':{'staff_plan':'가상담당 | 총괄 | 요구사항 확인','work_schedule':'직접 입력한 기간 | 요구사항 협의 | 가상담당','custom_1':'사용자 확인 문구'}})
        self.assertEqual(response.status_code,200)
        native=self.client.get(f'/api/v1/documents/{id_}/download?format=native',headers=self.headers[0])
        self.assertEqual(native.status_code,200,native.text[:100] if native.status_code!=200 else '')
        with ZipFile(io.BytesIO(native.content)) as archive:
            xml=archive.read('Contents/section0.xml').decode()
            self.assertIn('담당 인력표',xml);self.assertIn('사용자 확인 문구',xml);self.assertIn('가상담당',xml)
        for fmt in ('pdf','docx'):
            response=self.client.get(f'/api/v1/documents/{id_}/download?format={fmt}',headers=self.headers[0])
            self.assertEqual(response.status_code,200,response.text[:100] if response.status_code!=200 else '')
            if fmt=='pdf':
                with pymupdf.open(stream=response.content,filetype='pdf') as pdf:
                    self.assertIn('담당 인력표',''.join(page.get_text() for page in pdf))
        self.assertEqual(self.client.get(f'/api/v1/documents/{id_}/preview-pages',headers=self.headers[0]).status_code,200)
        self.assertEqual(self.client.get(f'/api/v1/contracts/{self.contract.id}/export',headers=self.headers[0]).status_code,200)
        self.assertEqual(self.client.get(f"/api/v1/templates/{result['template_id']}/sample-file",headers=self.headers[0]).status_code,200)
        self.assertEqual(self.client.get(f"/api/v1/templates/{result['template_id']}/review-preview-pages",headers=self.headers[0]).status_code,200)

    def test_saved_template_reuses_new_contract_without_copying_prior_document_content_or_ai(self):
        result=self.create();id_=result['document']['id']
        self.client.put(f'/api/v1/documents/{id_}',headers=self.headers[0],json={'values':{'staff_plan':'이전 계약 개인 정보'}})
        other=Contract(user_id=self.users[0].id,contract_title='다음 계약',description='다음 계약 업무')
        self.db.add(other);self.db.commit()
        with patch.object(settings,'OPENAI_API_KEY','test-only'),patch('app.services.ai._chat_json') as ai:
            response=self.client.post(f'/api/v1/contracts/{other.id}/documents',headers=self.headers[0],json={'template_id':result['template_id']})
            self.assertEqual(response.status_code,200);ai.assert_not_called()
        values=response.json()['values']
        self.assertEqual(values['contract_title'],'다음 계약');self.assertEqual(values['work_summary'],'다음 계약 업무')
        self.assertEqual(values['staff_plan'],'')

    def test_invalid_table_rows_are_rejected_and_blank_delimiters_remain_missing(self):
        result=self.create();id_=result['document']['id']
        for value in ('only one cell','\n'.join(['a|b|c']*51)):
            self.client.put(f'/api/v1/documents/{id_}',headers=self.headers[0],json={'values':{'staff_plan':value}})
            self.assertEqual(self.client.get(f'/api/v1/documents/{id_}/download?format=native',headers=self.headers[0]).status_code,422)
        response=self.client.put(f'/api/v1/documents/{id_}',headers=self.headers[0],json={'values':{'staff_plan':' | | '}})
        self.assertIn('staff_plan',response.json()['missing'])

    def test_custom_document_seal_requires_reauthentication_and_templates_are_immutable(self):
        result=self.create();id_=result['document']['id'];tid=result['template_id']
        image=io.BytesIO();Image.new('RGBA',(60,60),(180,0,0,100)).save(image,format='PNG')
        self.users[0].company.seal_image=normalize_seal(image.getvalue());self.db.commit()
        self.assertEqual(self.client.get(f'/api/v1/documents/{id_}/download?format=native',headers=self.headers[0]).status_code,403)
        grant=approve(self.client,self.headers[0],f'document:{id_}:download')
        response=self.client.get(f'/api/v1/documents/{id_}/download?format=native',headers=grant)
        self.assertEqual(response.status_code,200)
        with ZipFile(io.BytesIO(response.content)) as archive:self.assertIn('BinData/companySeal.png',archive.namelist())
        self.assertEqual(self.client.put(f'/api/v1/templates/{tid}/mapping',headers=self.headers[0],json={'fields':[]}).status_code,400)
        self.assertEqual(self.client.delete(f'/api/v1/templates/{tid}',headers=self.headers[0]).status_code,409)
        self.assertEqual(self.client.delete(f'/api/v1/documents/{id_}',headers=self.headers[0]).status_code,200)
        self.assertEqual(self.client.delete(f'/api/v1/templates/{tid}',headers=self.headers[0]).status_code,200)

    def test_contract_sync_does_not_put_plaintext_into_reviewed_tables(self):
        layout=self.layout()
        layout['sections'][0]['kind']='table';layout['sections'][0]['columns']=['항목','내용']
        result=self.create(layout)
        response=self.client.put(f'/api/v1/contracts/{self.contract.id}',headers=self.headers[0],json={'contract_title':'수정 계약','description':'변경된 업무'})
        self.assertEqual(response.status_code,200)
        doc=self.client.get(f"/api/v1/documents/{result['document']['id']}",headers=self.headers[0]).json()
        self.assertEqual(doc['values']['work_summary'],'')
        self.assertEqual(doc['values']['contract_title'],'수정 계약')

    def test_free_layout_uses_arbitrary_title_sections_and_tables_with_bound_consent(self):
        body={'title':'행사 안전관리계획서','purpose':'발주처에 안전 대응 절차 설명',
              'request':'위험요소별 대응표와 비상 연락망을 포함해 주세요.'}
        layout={'title':body['title'],'document_type':'free','sections':[
            {'key':'custom_1','label':'위험요소별 대응','kind':'table','columns':['위험요소','대응 방안'],'required':True},
            {'key':'custom_2','label':'비상 연락망','kind':'table','columns':['역할','연락처'],'required':False},
            {'key':'custom_3','label':'현장 대응 절차','kind':'text','columns':[],'required':True}]}
        with patch.object(settings,'OPENAI_API_KEY','test-only'),patch('app.services.ai._chat_json',return_value=layout) as ai:
            preview=self.client.post(self.base+'/transmission',headers=self.headers[0],json=body).json()
            self.assertIn(body['title'],preview['payload_preview'])
            self.assertIn(body['purpose'],preview['payload_preview'])
            for field in ('title','purpose','request'):
                changed={**body,field:body[field]+' 수정','use_ai':True,'consent_digest':preview['consent_digest']}
                self.assertEqual(self.client.post(self.base+'/propose',headers=self.headers[0],json=changed).status_code,400)
            ai.assert_not_called()
            response=self.client.post(self.base+'/propose',headers=self.headers[0],json={**body,'use_ai':True,'consent_digest':preview['consent_digest']})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['mode'],'ai')
            self.assertEqual(ai.call_args.args[1],preview['payload_preview'])
        created=self.client.post(self.base,headers=self.headers[0],json={**body,'layout':response.json()['layout'],'acknowledge_unofficial':True})
        self.assertEqual(created.status_code,200,created.text)
        doc=created.json()['document']; id_=doc['id']
        self.assertNotIn('work_summary',doc['field_keys'])
        self.assertEqual(doc['values']['custom_1'],'')
        self.assertEqual(doc['values']['custom_3'],'')
        with patch.object(settings,'OPENAI_API_KEY','test-only'),patch('app.services.ai._chat_json',return_value={'values':[{'key':'custom_3','text':'안내 담당자가 현장 상황을 확인합니다.'}]}) as ai:
            path=f'/api/v1/documents/{id_}/draft'
            preview=self.client.post(path+'/preview',headers=self.headers[0],json={}).json()
            context=json.loads(preview['payload_preview'])
            self.assertEqual(context['title'],body['title'])
            self.assertIn(body['purpose'],context['request'])
            suggestion=self.client.post(path+'/suggest',headers=self.headers[0],json={'use_ai':True,'consent_digest':preview['consent_digest']})
            self.assertEqual(suggestion.status_code,200,suggestion.text)
            self.assertEqual(suggestion.json()['mode'],'ai')
            self.assertIn('custom_3',suggestion.json()['values'])
            self.assertEqual(ai.call_args.args[1],preview['payload_preview'])
        self.client.put(f'/api/v1/contracts/{self.contract.id}',headers=self.headers[0],json={'description':'계약 범위 변경'})
        self.assertEqual(self.client.get(f'/api/v1/documents/{id_}',headers=self.headers[0]).json()['values']['custom_3'],'')
        self.client.put(f'/api/v1/documents/{id_}',headers=self.headers[0],json={'values':{'custom_1':'혼잡 | 동선 분리','custom_3':'현장 담당자에게 상황 전달'}})
        for route in ('download?format=native','download?format=pdf','preview-pages'):
            result=self.client.get(f'/api/v1/documents/{id_}/{route}',headers=self.headers[0])
            self.assertEqual(result.status_code,200,route)
        version=self.client.post(f"/api/v1/templates/{doc['template_id']}/versions",headers=self.headers[0],json={'layout':{**layout,'sections':layout['sections'][:1]},'note':'대응표만 남김'})
        self.assertEqual(version.status_code,200,version.text)

    def test_free_manual_skeleton_and_invalid_ai_fallback_are_not_legacy_forms(self):
        body={'title':'장비 반출 확인서','purpose':'장비 반출 내용을 기록','request':'장비 목록과 반출 확인 사항을 구성해 주세요.'}
        response=self.client.post(self.base+'/propose',headers=self.headers[0],json=body)
        self.assertEqual(response.status_code,200,response.text)
        layout=response.json()['layout']
        self.assertEqual(layout['document_type'],'free')
        self.assertEqual(layout['title'],body['title'])
        self.assertTrue(all(s['key'].startswith('custom_') for s in layout['sections']))
        for invalid in ({**layout,'sections':[]},{**layout,'sections':[layout['sections'][0]]*2},
                        {**layout,'sections':[{**layout['sections'][0],'key':'description'}]}):
            result=self.client.post(self.base,headers=self.headers[0],json={**body,'layout':invalid,'acknowledge_unofficial':True})
            self.assertEqual(result.status_code,422,result.text)
        with patch.object(settings,'OPENAI_API_KEY','test-only'),patch('app.services.ai._chat_json',return_value=custom_plans.local_layout('기존 계획').model_dump()):
            preview=self.client.post(self.base+'/transmission',headers=self.headers[0],json=body).json()
            response=self.client.post(self.base+'/propose',headers=self.headers[0],json={**body,'use_ai':True,'consent_digest':preview['consent_digest']})
            self.assertEqual(response.json()['mode'],'rule_fallback')
            self.assertEqual(response.json()['layout']['document_type'],'free')


if __name__=='__main__':unittest.main()
