import json
import logging
import os
import unittest
from unittest.mock import patch

import pymupdf
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import Base, get_db
from app.core.encryption import cipher
from app.core.security import hash_password
from app.models import User, Contract, Company, ClauseReview
from main import app
from tests.auth_helpers import PASSWORD, auth_headers, approve

HASH=hash_password(PASSWORD)
logging.getLogger('httpx2').setLevel(logging.WARNING)
PAYMENT='검수 완료 후 잔금을 지급하며 검수 기한은 별도로 정하지 않습니다.'
SUPPORT='계약 종료 후 유지보수는 기간과 횟수 제한 없이 무상으로 제공합니다.'
SOURCE=PAYMENT+'\n'+SUPPORT


class ReviewHistoryTests(unittest.TestCase):
    def test_rule_candidates_survive_save_reload_and_pdf_export(self):
        body=self.body('계약은 별도 통지가 없으면 자동 갱신됩니다.')
        with patch.object(settings,'OPENAI_API_KEY','test-only'),patch('app.services.ai._chat_json',return_value={'findings':[]}):
            preview=self.post('/preview',body).json()
            response=self.post('/analyze',{**body,'consent_digest':preview['consent_digest']})
        self.assertEqual(response.status_code,200,response.text)
        saved=response.json()
        self.assertEqual(saved['review_version'],2)
        self.assertEqual(saved['findings'][0]['method'],'rule')
        loaded=self.get(f"/history/{saved['id']}").json()
        self.assertEqual(loaded['findings'],saved['findings'])
        report=self.get(f"/history/{saved['id']}/pdf")
        with pymupdf.open(stream=report.content,filetype='pdf') as pdf:
            text=''.join(page.get_text() for page in pdf)
        self.assertIn('규칙 기반 확인 후보',text)

    def setUp(self):
        self.env=patch.dict(os.environ,{'DATA_ENCRYPTION_KEYS':Fernet.generate_key().decode(),'DATA_ENCRYPTION_KEY_FILE':''})
        self.env.start();cipher.cache_clear()
        self.engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
        Base.metadata.create_all(self.engine);self.db=Session(self.engine)
        self.users=[User(email=f'review-{i}@example.invalid',password_hash=HASH) for i in (1,2)]
        self.db.add_all(self.users);self.db.flush()
        self.db.add_all([Company(user_id=u.id,company_name='가상 회사') for u in self.users])
        self.contract=Contract(user_id=self.users[0].id,contract_title='가상 계약')
        self.db.add(self.contract);self.db.commit()
        self.headers=[auth_headers(self.db,u.id) for u in self.users]
        app.dependency_overrides[get_db]=lambda:self.db
        self.client=TestClient(app);self.base=f'/api/v1/contracts/{self.contract.id}/clause-review'
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.client.close();app.dependency_overrides.clear();self.db.close();self.engine.dispose();self.env.stop();cipher.cache_clear()

    def post(self,path,body,index=0):return self.client.post(self.base+path,headers=self.headers[index],json=body)
    def get(self,path,index=0):return self.client.get(self.base+path,headers=self.headers[index])
    def body(self,source=SOURCE,name='계약서.txt',role='supplier'):
        return {'role':role,'files':[{'name':name,'parts':[{'page':1,'text':source}]}]}

    def create(self,source=SOURCE,name='계약서.txt',role='supplier'):
        body=self.body(source,name,role)
        quotes=[q for q in (PAYMENT,SUPPORT) if q in source]
        if not quotes:quotes=[source]
        fake={'findings':[{'category':'검수·대금 지급','title':f'확인 항목 {i+1}',
            'impact':'기준과 기간을 확인해야 합니다.','question':f'질문 {i+1}: 구체적인 기한을 정할 수 있을까요?',
            'evidence':[{'source_id':1,'quote':quote}]} for i,quote in enumerate(quotes)]}
        with patch.object(settings,'OPENAI_API_KEY','test-only'),patch('app.services.ai._chat_json',return_value=fake):
            preview=self.post('/preview',body).json()
            response=self.post('/analyze',{**body,'consent_digest':preview['consent_digest']})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def test_success_is_encrypted_saved_retrievable_and_old_records_are_immutable(self):
        first=self.create();second=self.create()
        self.assertNotEqual(first['id'],second['id'])
        listed=self.get('/history').json()
        self.assertEqual([r['id'] for r in listed],[second['id'],first['id']])
        self.assertEqual(self.get(f"/history/{first['id']}").json()['findings'],first['findings'])
        raw=self.db.execute(text('SELECT payload FROM clause_reviews')).all()
        self.assertNotIn(PAYMENT,str(raw));self.assertIn('_cdoc_encrypted_v1',str(raw))
        self.assertEqual(first['findings'][0]['status'],'pending')

    def test_note_status_and_revision_conflict(self):
        saved=self.create();path=f"/history/{saved['id']}/findings/0"
        change={'status':'asking','note':'담당자에게 검수 기한 질문 전달','revision':0}
        result=self.client.put(self.base+path,headers=self.headers[0],json=change)
        self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json()['revision'],1)
        self.assertEqual(result.json()['findings'][0]['note'],change['note'])
        stale=self.client.put(self.base+path,headers=self.headers[0],json={**change,'note':'stale overwrite'})
        self.assertEqual(stale.status_code,409)
        self.assertEqual(self.get(f"/history/{saved['id']}").json()['findings'][0]['note'],change['note'])
        invalid=self.client.put(self.base+path,headers=self.headers[0],json={**change,'revision':1,'status':'approved'})
        self.assertEqual(invalid.status_code,422)
        too_long=self.client.put(self.base+path,headers=self.headers[0],json={**change,'revision':1,'note':'가'*1001})
        self.assertEqual(too_long.status_code,422)

    def test_all_routes_are_contract_owner_only_and_writes_require_csrf(self):
        a=self.create();b=self.create();rid=a['id']
        for path in ['/history',f'/history/{rid}',f'/history/{rid}/pdf']:
            self.assertEqual(self.get(path,1).status_code,404,path)
        for path,body in [(f'/history/{rid}/compare',{'after_id':b['id']}),(f'/history/{rid}/compare-draft',self.body())]:
            self.assertEqual(self.post(path,body,1).status_code,404)
        change={'status':'resolved','note':'확인','revision':0}
        self.assertEqual(self.client.put(self.base+f'/history/{rid}/findings/0',headers=self.headers[1],json=change).status_code,404)
        self.assertEqual(self.client.delete(self.base+f'/history/{rid}',headers=self.headers[1]).status_code,404)
        no_csrf={k:v for k,v in self.headers[0].items() if k.lower()!='x-csrf-token'}
        self.assertEqual(self.client.put(self.base+f'/history/{rid}/findings/0',headers=no_csrf,json=change).status_code,403)

    def test_comparison_of_modified_and_unchanged_evidence_never_marks_resolved(self):
        before=self.create()
        source='검수 요청 후 10일 이내 검수하고 검수 완료 후 7일 이내 잔금을 지급합니다.\n'+SUPPORT
        after=self.create(source,name='계약서-v2.txt')
        with patch('app.services.ai._chat_json') as ai:
            result=self.post(f"/history/{before['id']}/compare",{'after_id':after['id']})
            ai.assert_not_called()
        self.assertEqual(result.status_code,200,result.text)
        items=result.json()['items'];self.assertFalse(items[0]['unchanged']);self.assertTrue(items[1]['unchanged'])
        self.assertIn('7일',items[0]['evidence'][0]['after'])
        self.assertIn('10일',items[0]['evidence'][0]['after'])
        self.assertTrue(all(f['status']=='pending' for f in self.get(f"/history/{after['id']}").json()['findings']))

    def test_draft_comparison_is_local_and_unmatched_files_are_explicit(self):
        before=self.create()
        body=self.body(SOURCE,name='수정본.txt')
        body['files'].append({'name':'새로운별첨.txt','parts':[{'text':'별첨에는 별도의 납품 기한을 정합니다.'}]})
        with patch('app.services.ai._chat_json') as ai:
            result=self.post(f"/history/{before['id']}/compare-draft",body)
            ai.assert_not_called()
        self.assertEqual(len(result.json()['unmatched_before']),1)
        mapped=self.post(f"/history/{before['id']}/compare-draft",{**body,'source_map':{'1':'1'}})
        self.assertTrue(all(i['unchanged'] for i in mapped.json()['items']))
        self.assertEqual(mapped.json()['additional_after'][0]['name'],'새로운별첨.txt')
        self.assertEqual(self.post(f"/history/{before['id']}/compare-draft",{**body,'role':'client'}).status_code,400)
        self.assertEqual(self.db.query(ClauseReview).count(),1)

    def test_pdf_is_real_korean_pdf_with_status_notes_and_no_executable_markup(self):
        saved=self.create();rid=saved['id']
        self.client.put(self.base+f'/history/{rid}/findings/0',headers=self.headers[0],json={'status':'asking','note':'<script>가상 메모</script>','revision':0})
        response=self.get(f'/history/{rid}/pdf')
        self.assertEqual(response.status_code,200,response.text if response.status_code!=200 else '')
        self.assertTrue(response.content.startswith(b'%PDF-'));self.assertEqual(response.headers['cache-control'],'no-store')
        with pymupdf.open(stream=response.content,filetype='pdf') as pdf:
            contents=''.join(page.get_text() for page in pdf)
            self.assertIn('계약서 검토 보고서',contents);self.assertIn('상대방 문의 중',contents);self.assertIn('가상 메모',contents)

    def test_contract_and_privacy_deletion_remove_saved_reviews(self):
        self.create()
        response=self.client.delete(f'/api/v1/contracts/{self.contract.id}',headers=self.headers[0])
        self.assertEqual(response.status_code,200);self.assertEqual(self.db.query(ClauseReview).count(),0)
        self.contract=Contract(user_id=self.users[0].id,contract_title='다른 가상 계약');self.db.add(self.contract);self.db.commit()
        self.base=f'/api/v1/contracts/{self.contract.id}/clause-review';self.create()
        headers=approve(self.client,self.headers[0],'data:delete')
        self.assertEqual(self.client.delete('/api/v1/privacy/data',headers=headers).status_code,200)
        self.assertEqual(self.db.query(ClauseReview).count(),0)

    def test_failed_ai_call_never_creates_a_history_record(self):
        body=self.body()
        with patch.object(settings,'OPENAI_API_KEY','test-only'),patch('app.services.ai._chat_json',return_value=None):
            preview=self.post('/preview',body).json()
            self.assertEqual(self.post('/analyze',{**body,'consent_digest':preview['consent_digest']}).status_code,502)
        self.assertEqual(self.db.query(ClauseReview).count(),0)

    def test_own_delete_and_limit_do_not_trigger_paid_requests(self):
        saved=self.create();other=self.create()
        self.assertEqual(self.client.delete(self.base+f"/history/{saved['id']}",headers=self.headers[0]).status_code,200)
        self.assertEqual(self.get(f"/history/{saved['id']}").status_code,404)
        row=self.db.get(ClauseReview,other['id'])
        for _ in range(49):self.db.add(ClauseReview(contract_id=self.contract.id,payload=dict(row.payload)))
        self.db.commit()
        with patch('app.services.ai._chat_json') as ai:
            result=self.post('/analyze',self.body());ai.assert_not_called()
        self.assertEqual(result.status_code,413)
        self.assertEqual(len(self.get('/history').json()),50)
