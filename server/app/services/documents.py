"""서류 인스턴스 관련 공통 로직: 값 자동 채우기, 파일 생성, 응답 변환."""

import re
from pathlib import Path

from sqlalchemy.orm import Session

from app.builtin_templates import template_field_keys
from app.models import AuditLog, Company, Contract, Document, Template
from app.services import ai, renderer
from app.services.pdf_forms import positioned, fill_pdf
from app.services.professional_renderer import render_native
from app.standard_fields import base_values
from app.core.config import settings
from app.services.source_storage import resolve


def template_keys(t: Template) -> list[str]:
    if t.kind in ("builtin", "custom"):
        return template_field_keys(t.definition)
    keys, seen = [], set()
    for f in t.fields:
        k = f.get("field_key")
        if k and k not in seen:
            seen.add(k)
            keys.append(k)
    return keys


def auto_values(db: Session, user_id: int, t: Template, company: Company | None, contract: Contract) -> dict:
    """회사·계약정보 → 이 양식이 쓰는 필드만 골라 값 채우기. AI 문장 필드는 생성."""
    if t.kind == "custom":
        from app.services.custom_plans import values
        return values(t, company, contract)
    base = base_values(company, contract)
    keys = template_keys(t)
    values = {k: base.get(k, "") for k in keys}
    if "attachment_list" in keys:
        values["attachment_list"] = "\n".join(item for section in t.definition.get("sections", [])
                                               if section.get("type") == "attachments"
                                               for item in section.get("items", []))
    if "work_summary" in keys:
        text, used = ai.generate_work_summary(base)
        values["work_summary"] = text
        if used:
            db.add(AuditLog(user_id=user_id, action="ai_generate", detail=f"과업 개요 생성 (계약 {contract.id})"))
    return values


def sync_contract_values(doc: Document, previous: dict, current: dict) -> bool:
    """Refresh contract-derived values while retaining document-specific edits."""
    related = {
        "contract_title", "client_name", "amount", "amount_korean", "supply_amount", "vat",
        "contract_date", "start_date", "end_date", "period", "description", "work_summary",
        "payment_amount", "payment_amount_korean", "usage_purpose", "quote_items",
        "detail_items", "completion_details", "activity_topic", "activity_details",
    }
    values = dict(doc.values or {})
    changed = False
    for key in related.intersection(template_keys(doc.template)):
        if doc.template.kind=='custom' and key=='description' and doc.template.definition['custom_plan']['layout'].get('document_type') in ('report','pledge'):
            continue
        if doc.template.kind == 'custom' and any(section['key'] == key and section['kind'] == 'table' for section in doc.template.definition['custom_plan']['layout']['sections']):
            continue
        existing = values.get(key, "")
        if doc.template.kind == 'custom' and key == 'work_summary':
            if not str(existing or '').strip() or existing == previous.get('description', ''):
                if existing != current.get('description', ''):
                    values[key] = current.get('description', '')
                    changed = True
            continue
        if not str(existing or "").strip() or existing == previous.get(key, ""):
            value = current.get(key, "")
            if existing != value:
                values[key] = value
                changed = True
    if changed:
        doc.values = values
        doc.status = "draft"
    return changed


def build_docx(doc: Document):
    t = doc.template
    if positioned(t):
        from fastapi import HTTPException
        raise HTTPException(400, "원본 PDF 지정 양식은 PDF 형식으로 출력하세요.")
    if t.kind in ("builtin", "custom"):
        return renderer.render_builtin_docx(t.definition, doc.values, seal=document_seal(doc))
    if t.source_type == "docx" and t.source_path:
        path = resolve(t)
        if path and path.exists():
            return renderer.fill_uploaded_docx(path, t.fields, doc.values)
    if t.source_type in ('hwp', 'hwpx'):
        from app.services.hwpx_forms import editable_path, project_docx
        return project_docx(editable_path(t), t.fields, doc.values)
    # PDF 양식 또는 원본이 보관기간 경과로 삭제된 경우 → 항목 기반 재구성
    return renderer.rebuild_from_pdf_fields(t.name, t.fields, doc.values)


def output_format(t: Template) -> str:
    """User-facing native format. Uploaded forms keep their existing DOCX path."""
    if positioned(t):
        return "pdf"
    if t.kind in ("builtin", "custom"):
        return t.definition.get("output_format", "hwpx")
    if t.source_type in ('hwp', 'hwpx'):
        return 'hwpx'
    return "docx"


def build_native(doc: Document) -> tuple[bytes, str, str]:
    """Return bytes, extension, and full media type for the preferred native file."""
    if positioned(doc.template):
        return fill_pdf(doc.template, doc.values), "pdf", "application/pdf"
    if doc.template.kind in ("builtin", "custom") and doc.template.definition.get("sections"):
        return render_native(doc.template.definition, doc.values, seal=document_seal(doc))
    if doc.template.source_type in ('hwp', 'hwpx'):
        from app.services.hwpx_forms import editable_path, fill
        try:
            return fill(editable_path(doc.template), doc.template.fields, doc.values), 'hwpx', 'application/hwp+zip'
        except ValueError as error:
            from fastapi import HTTPException
            raise HTTPException(422, str(error))
    return (
        renderer.docx_bytes(build_docx(doc)),
        "docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


def document_seal(doc: Document):
    from app.core.render_security import seal_authorized
    from app.services.seal import company_seal
    return company_seal(doc.contract.user.company) if doc.contract and seal_authorized.get() else None


def build_pdf(doc: Document) -> bytes:
    if positioned(doc.template):
        return fill_pdf(doc.template, doc.values)
    if doc.template.source_type in ('hwp', 'hwpx'):
        from app.services.hancom import pdf_bytes
        if settings.CLOUD_MODE:
            from fastapi import HTTPException
            raise HTTPException(503, "무료 웹 버전은 업로드 한글 원본의 PDF 미리보기를 지원하지 않습니다. HWPX를 다운로드해 한글에서 확인하세요.")
        return pdf_bytes(build_native(doc)[0])
    return renderer.docx_to_pdf_bytes(build_docx(doc))


def preview_html(doc: Document) -> str:
    if positioned(doc.template):
        from app.services.pdf_forms import preview_html as pdf_preview
        return pdf_preview(build_pdf(doc))
    return renderer.docx_to_html(build_docx(doc))


def review_text(doc: Document) -> str:
    if positioned(doc.template):
        import pymupdf
        with pymupdf.open(stream=build_pdf(doc), filetype="pdf") as pdf:
            return "\n".join(page.get_text() for page in pdf)
    return renderer.docx_to_text(build_docx(doc))


def safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", name).strip("_") or "document"


def to_out(doc: Document) -> dict:
    from app.services.validator import document_keys, has_value

    keys, required = document_keys(doc)
    return {
        "id": doc.id,
        "contract_id": doc.contract_id,
        "template_id": doc.template_id,
        "title": doc.title,
        "values": doc.values,
        "status": doc.status,
        "created_at": doc.created_at,
        "updated_at": doc.updated_at,
        "template_kind": doc.template.kind,
        "output_format": output_format(doc.template),
        "field_keys": keys,
        "missing": [k for k in required if not has_value(doc.template, k, (doc.values or {}).get(k))],
    }
