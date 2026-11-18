from typing import Literal
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.core.security import get_current_user
from app.models import User, ClauseReview, AuditLog
from app.routers.contracts import get_owned
from app.routers.document_workflow import authorize_ai
from app.routers.documents import get_owned_doc
from app.services import contract_review as review
from app.services.documents import build_native, build_pdf
from app.services.notice_files import MAX_FILE, extract_notice
from app.services.pdf_forms import positioned
from app.services.source_storage import resolve
from app.services import review_history as history


router = APIRouter(prefix='/contracts/{contract_id}/clause-review', tags=['contract-review'])


def read_source(data, filename):
    result = extract_notice(data, filename, include_pages=True)
    pages = result.get('page_texts')
    parts = [{'page': index, 'text': text} for index, text in enumerate(pages, 1) if text.strip()] if pages else [
        {'page': None, 'text': result['text']},
    ]
    return parts, result['warning']


def review_preview(db, user, contract_id, body):
    get_owned(db, user, contract_id)
    source = None
    warning = ' '.join(file.warning for file in body.files if file.warning)
    signature=None
    if body.document_id:
        doc = get_owned_doc(db, user, body.document_id)
        if doc.contract_id != contract_id or doc.template.kind not in ('custom', 'uploaded'):
            raise HTTPException(404, '이 계약의 자체 양식 또는 AI 자유 양식을 선택하세요.')
        if doc.template.kind == 'custom':
            data, extension = build_pdf(doc), 'pdf'
        else:
            path = resolve(doc.template)
            if not path or not path.is_file() or (doc.template.source_type == 'pdf' and not positioned(doc.template)):
                raise HTTPException(422, '원본을 바탕으로 저장본을 읽을 수 없습니다. 계약서 최종 파일을 올려주세요.')
            data, extension, _ = build_native(doc)
        parts, document_warning = read_source(data, f'{doc.title}.{extension}')
        warning=' '.join(filter(None,[warning,document_warning]))
        signature=history.document_signature(doc)
        source = review.ReviewFile(name=doc.title, parts=parts)
    return {**review.preview(body, source), 'warning': warning,'document_signature':signature}


@router.post('/extract')
async def extract(contract_id: int, file: UploadFile = File(...),
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    get_owned(db, user, contract_id)
    data = await file.read(MAX_FILE + 1)
    parts, warning = await run_in_threadpool(read_source, data, file.filename or '')
    return {'name': (file.filename or '계약서')[:180], 'parts': parts, 'warning': warning}


@router.post('/preview')
def preview(contract_id: int, body: review.ReviewIn,
            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return review_preview(db, user, contract_id, body)


@router.post('/analyze')
def analyze(contract_id: int, body: review.ReviewIn, request: Request,
            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    contract=get_owned(db,user,contract_id)
    if db.scalar(select(func.count()).select_from(ClauseReview).where(ClauseReview.contract_id==contract_id))>=50:
        raise HTTPException(413,'계약당 검토 이력은 최대 50개입니다. 기존 이력을 정리한 뒤 다시 검토하세요.')
    transmission = review_preview(db, user, contract_id, body)
    authorize_ai(db, user, request, body, transmission, 'contract-clause-review')
    result=review.analyze(transmission['payload_preview'])
    return history.save(db,user,contract,body,transmission,result)


@router.get('/history')
def list_history(contract_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    get_owned(db,user,contract_id)
    rows=db.scalars(select(ClauseReview).where(ClauseReview.contract_id==contract_id).order_by(ClauseReview.id.desc()).limit(50)).all()
    return [history.to_out(row,False) for row in rows]


@router.get('/history/{review_id}')
def get_history(contract_id:int,review_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    row=history.get_owned(db,user,contract_id,review_id)
    return {**history.to_out(row),'document_state':history.document_state(db,row)}


class FollowUp(BaseModel):
    model_config=ConfigDict(extra='forbid')
    status:Literal['pending','asking','resolved']
    note:str=Field(default='',max_length=1000)
    revision:int=Field(ge=0)


@router.put('/history/{review_id}/findings/{index}')
def follow_up(contract_id:int,review_id:int,index:int,body:FollowUp,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    if index<0:raise HTTPException(404,'검토 항목을 찾을 수 없습니다.')
    return history.change_finding(db,user,history.get_owned(db,user,contract_id,review_id),index,body.status,body.note,body.revision)


@router.get('/history/{review_id}/pdf')
def download_report(contract_id:int,review_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    row=history.get_owned(db,user,contract_id,review_id)
    contract=get_owned(db,user,contract_id)
    data=history.report_pdf(row,contract.contract_title,history.document_state(db,row))
    db.add(AuditLog(user_id=user.id,action='review_export',detail=f'검토 이력 {row.id} PDF 다운로드'));db.commit()
    return Response(data,media_type='application/pdf',headers={'Content-Disposition':f'attachment; filename="contract-review-{row.id}.pdf"','Cache-Control':'no-store'})


class CompareIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    after_id:int=Field(gt=0)
    source_map:dict[str,str]=Field(default_factory=dict,max_length=6)


@router.post('/history/{review_id}/compare')
def compare_history(contract_id:int,review_id:int,body:CompareIn,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    before=history.get_owned(db,user,contract_id,review_id)
    after=history.get_owned(db,user,contract_id,body.after_id)
    if before.id==after.id:raise HTTPException(400,'서로 다른 검토 이력을 선택하세요.')
    return history.compare(before.payload,after.payload,body.source_map)


class CompareDraft(review.ReviewIn):
    source_map:dict[str,str]=Field(default_factory=dict,max_length=6)


@router.post('/history/{review_id}/compare-draft')
def compare_draft(contract_id:int,review_id:int,body:CompareDraft,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    before=history.get_owned(db,user,contract_id,review_id)
    transmission=review_preview(db,user,contract_id,body)
    import json
    after=json.loads(transmission['payload_preview']);after['role']=body.role
    return {**history.compare(before.payload,after,body.source_map),
        'after_files':[{'key':g['key'],'name':g['name']} for g in history.file_groups(after['sources']).values()],
        'source_warning':transmission['warning']}


@router.delete('/history/{review_id}')
def delete_history(contract_id:int,review_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    row=history.get_owned(db,user,contract_id,review_id)
    db.delete(row);db.add(AuditLog(user_id=user.id,action='review_delete',detail=f'검토 이력 {review_id} 삭제'));db.commit()
    return {'ok':True}
