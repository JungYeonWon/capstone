import io
import zipfile
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_sensitive
from app.models import AuditLog, Contract, Document, User
from app.routers.company import get_or_create_company
from app.routers.templates import get_visible
from app.schemas import ContractIn, DocumentCreate, MailIn
from app.services import ai, renderer
from app.services.documents import auto_values, build_native, build_pdf, review_text, safe_filename, sync_contract_values, to_out
from app.services.mailer import send_mail
from app.services.library import recommendation, scope
from app.services.validator import validate
from app.standard_fields import base_values

router = APIRouter(prefix="/contracts", tags=["contracts"])


def get_owned(db: Session, user: User, contract_id: int) -> Contract:
    """접근 통제: 본인 계약만 조회 가능 (3주차 보안 ④)."""
    c = db.scalar(select(Contract).where(Contract.id == contract_id, Contract.user_id == user.id))
    if not c:
        raise HTTPException(404, "계약을 찾을 수 없습니다.")
    return c


def contract_out(c: Contract, count: int | None = None) -> dict:
    return {
        "id": c.id, "contract_title": c.contract_title, "client_name": c.client_name, "amount": c.amount,
        "contract_date": c.contract_date, "start_date": c.start_date, "end_date": c.end_date, "description": c.description,
        "created_at": c.created_at, "document_count": len(c.documents) if count is None else count,
    }


@router.get("")
def list_contracts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(
        select(Contract, func.count(Document.id))
        .outerjoin(Document, Document.contract_id == Contract.id)
        .where(Contract.user_id == user.id)
        .group_by(Contract.id)
        .order_by(Contract.created_at.desc())
    ).all()
    return [contract_out(c, n) for c, n in rows]


@router.post("")
def create_contract(body: ContractIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.start_date and body.end_date and body.start_date > body.end_date:
        raise HTTPException(400, "착수일이 완료일보다 늦을 수 없습니다.")
    c = Contract(user_id=user.id, **body.model_dump())
    db.add(c)
    db.commit()
    return contract_out(c, 0)


@router.get("/{contract_id}")
def get_contract(contract_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return contract_out(get_owned(db, user, contract_id))


@router.put("/{contract_id}")
def update_contract(contract_id: int, body: ContractIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = get_owned(db, user, contract_id)
    if body.start_date and body.end_date and body.start_date > body.end_date:
        raise HTTPException(400, "착수일이 완료일보다 늦을 수 없습니다.")
    company = user.company
    previous = base_values(company, c)
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    current = base_values(company, c)
    for document in c.documents:
        sync_contract_values(document, previous, current)
    db.commit()
    return contract_out(c)


@router.delete("/{contract_id}")
def delete_contract(contract_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(get_owned(db, user, contract_id))
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- 서류
@router.get("/{contract_id}/documents")
def list_documents(contract_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = get_owned(db, user, contract_id)
    return [to_out(d) for d in sorted(c.documents, key=lambda d: d.id)]


@router.post("/{contract_id}/documents")
def create_document(contract_id: int, body: DocumentCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """양식 선택 → 회사·계약정보 자동 적용 → 서류 생성 (CASE 1·2 공통)."""
    c = get_owned(db, user, contract_id)
    t = get_visible(db, user, body.template_id)
    if t.status != "ready":
        raise HTTPException(400, "양식 항목 매핑을 먼저 확인·저장해 주세요.")
    if scope(t) == "organization" and recommendation(t, c.client_name, body.project_code) is None:
        raise HTTPException(400, "발주처 또는 공고번호가 다른 지정 양식입니다. 공통 양식을 선택하세요.")
    company = get_or_create_company(db, user)
    doc = Document(contract_id=c.id, template_id=t.id, title=t.name, values=auto_values(db, user.id, t, company, c))
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return to_out(doc)


@router.post("/{contract_id}/validate")
def validate_contract(contract_id: int, with_ai: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """AI 검토(누락·오류·서류 간 불일치). 규칙 검증 + (선택) LLM 문장 검토."""
    c = get_owned(db, user, contract_id)
    docs = sorted(c.documents, key=lambda d: d.id)
    master = base_values(get_or_create_company(db, user), c)
    result = validate(docs, master)
    from app.models import WorkspaceState
    from app.services.document_workflow import NoticeState
    checklist=db.get(WorkspaceState,(c.id,'notice'))
    if checklist and checklist.payload:
        state=NoticeState.model_validate(checklist.payload)
        for item in state.items:
            linked=next((d for d in docs if d.id==item.document_id),None)
            if not item.done or (item.document_id and not linked):
                result['issues'].append({'severity':'error' if item.required else 'warning','type':'체크리스트 미완료',
                    'field_key':None,'field_label':None,'message':f"제출서류 '{item.title}'의 준비 여부를 확인하세요.",
                    'document_ids':[linked.id] if linked else [],'document_titles':[linked.title] if linked else []})
    pending=db.scalars(select(WorkspaceState).where(WorkspaceState.contract_id==c.id,WorkspaceState.slot.like('document_%'))).all()
    for state in pending:
        if state.payload.get('values'):
            linked=next((d for d in docs if state.slot==f'document_{d.id}'),None)
            if linked and state.payload['values']!=linked.values:
                result['issues'].append({'severity':'warning','type':'임시 저장 미반영','field_key':None,'field_label':None,
                    'message':'편집기의 임시 저장 내용이 출력 문서에 아직 반영되지 않았습니다. 편집 화면에서 저장하세요.',
                    'document_ids':[linked.id],'document_titles':[linked.title]})
    errors=sum(i['severity']=='error' for i in result['issues'])
    result['summary'].update(errors=errors,warnings=len(result['issues'])-errors,passed=errors==0)
    outstanding={'검토 필요 문구','표 빈칸','임시 저장 미반영','체크리스트 미완료'}
    result['summary']['ready_for_submission']=bool(docs) and errors==0 and not any(i['type'] in outstanding for i in result['issues'])
    result["ai_comments"] = []
    if with_ai:
        for d in docs:
            comments = ai.review_text(d.title, review_text(d))
            if comments:
                result["ai_comments"].append({"document_id": d.id, "title": d.title, "comments": comments})
        db.add(AuditLog(user_id=user.id, action="ai_send", detail=f"문장 검토 {len(docs)}건 (계약 {c.id}, 마스킹 후 전송)"))
    for d in docs:
        has_error = any(d.id in i["document_ids"] and (i["severity"] == "error" or i['type'] in outstanding) for i in result["issues"])
        d.status = "draft" if has_error else "reviewed"
    db.commit()
    return result


def _render_files(docs: list[Document], fmt: str) -> list[tuple[str, bytes, str]]:
    files = []
    for i, d in enumerate(docs, 1):
        name = f"{i:02d}_{safe_filename(d.title)}"
        if fmt in ("native", "both", "docx"):
            data, ext, media = build_native(d)
            files.append((f"{name}.{ext}", data, media.split("/", 1)[1]))
        if fmt == "pdf" or (fmt == "both" and not any(n == f"{name}.pdf" for n, _, _ in files)):
            files.append((f"{name}.pdf", build_pdf(d), "pdf"))
    return files


@router.get("/{contract_id}/export")
def export_zip(contract_id: int, request: Request, format: str = "native", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = get_owned(db, user, contract_id)
    docs = sorted(c.documents, key=lambda d: d.id)
    if not docs:
        raise HTTPException(400, "작성된 서류가 없습니다.")
    if user.company and user.company.seal_image and any(d.template.kind in ("builtin", "custom") for d in docs):
        require_sensitive(request, db, user, f"contract:{c.id}:export")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data, _ in _render_files(docs, format):
            z.writestr(name, data)
    buf.seek(0)
    db.add(AuditLog(user_id=user.id, action="document_export", detail=f"contract:{c.id}")); db.commit()
    fname = quote(f"{safe_filename(c.contract_title)}_제출서류.zip")
    return StreamingResponse(buf, media_type="application/zip", headers={"Content-Disposition": f"attachment; filename*=UTF-8''{fname}"})


@router.post("/{contract_id}/mail")
def mail_documents(contract_id: int, body: MailIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = get_owned(db, user, contract_id)
    docs = [d for d in sorted(c.documents, key=lambda d: d.id) if d.id in set(body.document_ids)]
    if not docs:
        raise HTTPException(400, "보낼 서류를 선택하세요.")
    if user.company and user.company.seal_image and any(d.template.kind in ("builtin", "custom") for d in docs):
        require_sensitive(request, db, user, f"contract:{c.id}:mail")
    company = get_or_create_company(db, user)
    subject = body.subject or f"[{company.company_name or '제출'}] {c.contract_title} 관련 서류 제출"
    text = body.body or f"안녕하세요. {c.contract_title} 관련 서류를 첨부하여 제출합니다.\n\n첨부: " + ", ".join(d.title for d in docs)
    result = send_mail(body.to, subject, text, _render_files(docs, body.format))
    db.add(AuditLog(user_id=user.id, action="mail_send", detail=f"계약 {c.id} 서류 {len(docs)}건 → {body.to} (mock={result['mock']})"))
    db.commit()
    return {**result, "to": body.to, "count": len(docs)}
