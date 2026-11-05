import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user, throttle
from app.models import AuditLog, Contract, Document, Template, User, WorkspaceState
from app.routers.contracts import get_owned
from app.routers.documents import get_owned_doc
from app.routers.templates import get_visible, to_out, visible_templates
from app.services import custom_plans as plans, document_workflow as flow

router=APIRouter(tags=['document-workflow'])


def custom_doc(db,user,document_id):
    doc=get_owned_doc(db,user,document_id)
    if doc.template.kind!='custom': raise HTTPException(400,'맞춤 서류에서 사용할 수 있습니다.')
    return doc


def authorize_ai(db,user,request,body,preview,purpose):
    if not body.use_ai:return
    if not settings.ai_enabled:raise HTTPException(503,'외부 AI가 연결되지 않았습니다. 로컬 제안을 사용할 수 있습니다.')
    if body.consent_digest!=preview['consent_digest']:raise HTTPException(400,'변경된 전송 내용을 다시 확인하고 동의하세요.')
    throttle(db,request,purpose,str(user.id))
    db.add(AuditLog(user_id=user.id,action='ai_send',detail=purpose+': 사용자가 확인한 마스킹 전송 내용만 사용'))
    db.commit()


@router.post('/documents/{document_id}/draft/preview')
def draft_preview(document_id:int,body:flow.DraftIn,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    doc=custom_doc(db,user,document_id)
    return {**flow.transfer(flow.draft_context(doc,user.company,body)),
            'questions':flow.questions(doc,{**doc.values,**body.values,**body.answers})}


@router.post('/documents/{document_id}/draft/suggest')
def draft_suggest(document_id:int,body:flow.DraftIn,request:Request,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    doc=custom_doc(db,user,document_id)
    preview=flow.transfer(flow.draft_context(doc,user.company,body))
    authorize_ai(db,user,request,body,preview,'document-body-ai')
    return flow.suggest_body(doc,user.company,body)


Slot = Annotated[str,Field(pattern=r'^(builder|notice|document_[1-9][0-9]*|answers_[1-9][0-9]*)$',max_length=40)]


class StateIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    payload: dict = Field(default_factory=dict)
    revision: int = Field(ge=0)


def slot_check(db,user,contract_id,slot):
    get_owned(db,user,contract_id)
    if slot.startswith(('document_','answers_')):
        doc=get_owned_doc(db,user,int(slot.split('_')[1]))
        if doc.contract_id!=contract_id:raise HTTPException(404,'계약에 속한 서류가 아닙니다.')


@router.get('/contracts/{contract_id}/workspace/{slot}')
def get_state(contract_id:int,slot:Slot,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    slot_check(db,user,contract_id,slot)
    row=db.get(WorkspaceState,(contract_id,slot))
    return {'payload':row.payload if row else {},'revision':row.revision if row else 0,'updated_at':row.updated_at if row else None}


@router.put('/contracts/{contract_id}/workspace/{slot}')
def put_state(contract_id:int,slot:Slot,body:StateIn,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    slot_check(db,user,contract_id,slot)
    # Notices retain both the current and applied source plus bounded evidence.
    limit=320000 if slot=='notice' else 160000
    if len(json.dumps(body.payload,ensure_ascii=False).encode())>limit:raise HTTPException(413,'임시 저장 용량을 초과했습니다.')
    if slot=='notice' and body.payload:
        try: state=flow.NoticeState.model_validate(body.payload)
        except ValueError:raise HTTPException(422,'체크리스트 형식을 확인하세요.') from None
        if len({i.id for i in state.items})!=len(state.items):raise HTTPException(422,'체크리스트 항목 ID가 중복되었습니다.')
        for item in state.items:
            if item.document_id:
                doc=get_owned_doc(db,user,item.document_id)
                if doc.contract_id!=contract_id:raise HTTPException(404,'다른 계약의 서류입니다.')
        body.payload=state.model_dump()
    if slot.startswith('document_') and body.payload:
        values=body.payload.get('values')
        if not isinstance(values,dict) or any(not isinstance(v,str) or len(v)>10000 for v in values.values()):
            raise HTTPException(422,'서류 임시 저장값을 확인하세요.')
        doc=get_owned_doc(db,user,int(slot.split('_')[1]))
        from app.services.documents import template_keys
        if set(values)-set(template_keys(doc.template)):raise HTTPException(422,'허용되지 않은 항목입니다.')
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    insert=pg_insert if db.bind.dialect.name=='postgresql' else sqlite_insert
    db.execute(insert(WorkspaceState).values(contract_id=contract_id,slot=slot,payload={},revision=0,updated_at=datetime.utcnow()).on_conflict_do_nothing())
    revision=db.scalar(update(WorkspaceState).where(WorkspaceState.contract_id==contract_id,WorkspaceState.slot==slot,WorkspaceState.revision==body.revision).values(payload=body.payload,revision=body.revision+1,updated_at=datetime.utcnow()).returning(WorkspaceState.revision))
    if revision is None:
        db.rollback();raise HTTPException(409,'다른 창에서 변경되었습니다. 새로 불러와 내용을 확인하세요.')
    db.commit()
    return {'revision':revision}


@router.post('/contracts/{contract_id}/notice/preview')
def notice_preview(contract_id:int,body:flow.NoticeIn,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    get_owned(db,user,contract_id)
    return flow.transfer({'notice':body.text})


@router.get('/contracts/{contract_id}/notice/templates')
def notice_templates(contract_id:int,title:Annotated[str,Field(min_length=1,max_length=100)],
                     project_code:Annotated[str,Field(max_length=100)]='',user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    from app.services.library import recommendation
    from app.services.notice_analysis import canonical, compact
    contract=get_owned(db,user,contract_id)
    matches=[]
    for template in visible_templates(db,user):
        rank=recommendation(template,contract.client_name,project_code)
        if template.status!='ready' or rank is None:continue
        names=[template.name,*(template.aliases or []),template.definition.get('library',{}).get('document_type','')]
        if any(compact(canonical(title))==compact(canonical(name)) for name in names if name):
            matches.append((rank[0],template.id,{'template':to_out(template),'reason':rank[1]}))
    return [row[2] for row in sorted(matches,key=lambda row:row[:2])[:10]]


@router.post('/contracts/{contract_id}/notice/analyze')
def notice_analyze(contract_id:int,body:flow.NoticeIn,request:Request,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    get_owned(db,user,contract_id)
    authorize_ai(db,user,request,body,flow.transfer({'notice':body.text}),'notice-ai')
    return flow.notice_items(body.text,body.use_ai)


@router.post('/contracts/{contract_id}/notice/extract')
async def notice_extract(contract_id:int,file:UploadFile=File(...),user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    get_owned(db,user,contract_id)
    data=await file.read(3*1024*1024+1)
    from starlette.concurrency import run_in_threadpool
    from app.services.notice_files import extract_notice
    return await run_in_threadpool(extract_notice,data,file.filename or '')



class VersionIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    layout: plans.PlanLayout
    note: str = Field(default='',max_length=300)


def own_template(db,user,template_id):
    template=get_visible(db,user,template_id)
    if template.kind!='custom' or template.owner_id!=user.id:raise HTTPException(404,'내 맞춤 양식이 아닙니다.')
    return template


@router.get('/templates/{template_id}/versions')
def versions(template_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    template=own_template(db,user,template_id)
    root=template.definition['custom_plan'].get('root_id',template.id)
    rows=db.scalars(select(Template).where(Template.owner_id==user.id,Template.kind=='custom').order_by(Template.id.desc())).all()
    return [to_out(t) for t in rows if t.definition['custom_plan'].get('root_id',t.id)==root]


@router.post('/templates/{template_id}/versions')
def new_version(template_id:int,body:VersionIn,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    db.scalar(select(User).where(User.id==user.id).with_for_update())
    template=own_template(db,user,template_id)
    rows=db.scalars(select(Template).where(Template.owner_id==user.id,Template.kind=='custom')).all()
    if len(rows)>=50:raise HTTPException(413,'맞춤 양식은 계정당 50개까지 저장할 수 있습니다.')
    old=template.definition['custom_plan']; root=old.get('root_id',template.id)
    number=1+max(t.definition['custom_plan'].get('version',1) for t in rows if t.definition['custom_plan'].get('root_id',t.id)==root)
    definition=plans.definition(body.layout,old.get('request',''),'user_reviewed')
    definition['custom_plan'].update(root_id=root,parent_id=template.id,version=number,version_note=body.note)
    copy=Template(kind='custom',owner_id=user.id,name=body.layout.title,category=template.category,
                  description=f'개인 양식 버전 {number} · 기존 서류는 이전 버전 유지',aliases=list(template.aliases or []),definition=definition,
                  fields=[{'label':s.label,'field_key':s.key,'method':'user','location':{}} for s in body.layout.sections],status='ready')
    db.add(copy);db.flush()
    db.add(AuditLog(user_id=user.id,action='template_version',detail=f'template:{copy.id}; parent:{template.id}; version:{number}'))
    db.commit();return to_out(copy)
