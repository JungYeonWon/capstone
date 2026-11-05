"""Propose -> review -> create a private reusable work plan and editable draft."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user, throttle
from app.models import AuditLog, Document, Template, User
from app.routers.contracts import get_owned
from app.routers.templates import visible_templates
from app.services import custom_plans as plans
from app.services.documents import to_out
from app.services.library import metadata, recommendation, scope

router=APIRouter(prefix='/contracts',tags=['custom-plans'])


class ProposeIn(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    request: str=Field(min_length=5,max_length=2000)
    document_type: plans.DocumentType = 'free'
    title: str=Field(default='',max_length=100)
    purpose: str=Field(default='',max_length=1000)
    project_code: str=Field(default='',max_length=80)
    use_ai: bool=False
    consent_digest: str=Field(default='',max_length=64)


class CreateIn(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    request: str=Field(min_length=5,max_length=2000)
    title: str=Field(default='',max_length=100)
    purpose: str=Field(default='',max_length=1000)
    layout: plans.PlanLayout
    acknowledge_unofficial: bool=False


def matches(db,user,contract,project_code,doc_type='work_plan',title=''):
    result=[]
    types={'work_plan':{'과업수행계획서','수행계획서','사업수행계획서','작업계획서'},
           'proposal':{'제안서','사업제안서'},'report':{'보고서','완료보고서','결과보고서'},'pledge':{'확약서','보안확약서','비밀유지확약서'}}
    for template in visible_templates(db,user):
        if scope(template)=='organization' and template.status=='ready':
            document_type = str(metadata(template).get('document_type', '')).replace(' ', '')
            if document_type not in (types.get(doc_type) or {title.replace(' ','')}):
                continue
            match=recommendation(template,contract.client_name,project_code)
            if match:
                result.append({'id':template.id,'name':template.name,'reason':match[1],
                               'project_code':metadata(template).get('project_code','')})
    return result


@router.post('/{contract_id}/custom-plan/transmission')
def transmission(contract_id:int,body:ProposeIn,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    get_owned(db,user,contract_id)
    return plans.transfer(body.request,body.document_type,body.title,body.purpose)


@router.post('/{contract_id}/custom-plan/propose')
def propose(contract_id:int,body:ProposeIn,request:Request,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    contract=get_owned(db,user,contract_id)
    if body.use_ai:
        if not settings.ai_enabled:
            raise HTTPException(503,'외부 AI가 연결되어 있지 않습니다. 로컬 구성 제안을 사용하세요.')
        if body.consent_digest!=plans.transfer(body.request,body.document_type,body.title,body.purpose)['consent_digest']:
            raise HTTPException(400,'전송할 내용을 확인하고 외부 AI 사용에 동의하세요.')
        throttle(db,request,'custom-plan-ai',str(user.id))
        db.add(AuditLog(user_id=user.id,action='ai_send',detail='맞춤 양식 구성: 동의한 마스킹 제목·목적·요청과 해당 구성 정보만 전송. 회사·계약·인감 제외.'))
        db.commit()
    layout,mode=plans.propose(body.request,body.use_ai,body.document_type,body.title,body.purpose)
    return {'layout':layout.model_dump(),'mode':mode,'matches':matches(db,user,contract,body.project_code,body.document_type,layout.title),
            'warning':'AI 구성을 검증하지 못해 직접 편집할 기본 구성으로 대체했습니다.' if mode=='rule_fallback' else ''}


@router.post('/{contract_id}/custom-plan')
def create(contract_id:int,body:CreateIn,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    contract=get_owned(db,user,contract_id)
    if not body.acknowledge_unofficial:
        raise HTTPException(400,'발주처 지정 서식이 아닌 검토용 초안임을 확인하세요.')
    count=db.scalar(select(func.count()).select_from(Template).where(Template.owner_id==user.id,Template.kind=='custom'))
    if count>=50:
        raise HTTPException(413,'맞춤 양식은 계정당 50개까지 저장할 수 있습니다.')
    context='\n'.join(value for value in (f'문서 제목: {body.layout.title}',f'작성 목적: {body.purpose}' if body.purpose else '',body.request) if value)
    label=body.layout.title if body.layout.document_type=='free' else plans.DOCUMENT_TYPES[body.layout.document_type]
    template=Template(kind='custom',owner_id=user.id,name=body.layout.title,category='맞춤 서류',
                      description=f'사용자가 구성을 확인한 {label} 초안 · 발주처 지정 서식 아님',
                      aliases=[label],definition=plans.definition(body.layout,context,'user_reviewed'),
                      fields=[{'label':s.label,'field_key':s.key,'method':'user','location':{}} for s in body.layout.sections],
                      status='ready')
    db.add(template);db.flush()
    doc=Document(contract_id=contract.id,template_id=template.id,title=body.layout.title,
                 values=plans.values(template,user.company,contract),status='draft')
    db.add(doc);db.flush()
    db.add(AuditLog(user_id=user.id,action='custom_plan_create',detail=f'contract:{contract.id}; template:{template.id}; document:{doc.id}'))
    db.commit()
    return {'document':to_out(doc),'template_id':template.id}
