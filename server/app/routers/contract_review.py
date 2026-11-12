from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.core.security import get_current_user
from app.models import User
from app.routers.contracts import get_owned
from app.routers.document_workflow import authorize_ai
from app.routers.documents import get_owned_doc
from app.services import contract_review as review
from app.services.documents import build_native, build_pdf
from app.services.notice_files import MAX_FILE, extract_notice
from app.services.pdf_forms import positioned
from app.services.source_storage import resolve


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
    warning = ''
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
        parts, warning = read_source(data, f'{doc.title}.{extension}')
        source = review.ReviewFile(name=doc.title, parts=parts)
    return {**review.preview(body, source), 'warning': warning}


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
    transmission = review_preview(db, user, contract_id, body)
    authorize_ai(db, user, request, body, transmission, 'contract-clause-review')
    return review.analyze(transmission['payload_preview'])
