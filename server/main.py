"""AI 기반 계약·행정서류 자동화 웹 서비스 — API 서버.

실행: uvicorn main:app --reload --port 8000
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.builtin_templates import BUILTIN_TEMPLATES
from app.core.config import settings
from app.core.database import Base, SessionLocal, engine, get_db
from app.core.security import get_current_user
from app.models import AuditLog, Template, User
from app.routers import auth, company, contracts, documents, templates, privacy, custom_plans, account_security, document_workflow
from app.services.source_storage import TemporaryFilesMiddleware, remove

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("app")


def ensure_company_columns():
    """Add optional reusable business/bank fields to an existing database."""
    existing = {column["name"] for column in inspect(engine).get_columns("companies")}
    columns = {
        "business_type": "VARCHAR(100)",
        "business_item": "VARCHAR(100)",
        "bank_name": "VARCHAR(50)",
        "account_number": "VARCHAR(50)",
        "account_holder": "VARCHAR(100)",
    }
    with engine.begin() as connection:
        for name, sql_type in columns.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE companies ADD COLUMN {name} {sql_type} NOT NULL DEFAULT ''"))
        if "seal_image" not in existing:
            connection.execute(text("ALTER TABLE companies ADD COLUMN seal_image TEXT NOT NULL DEFAULT ''"))
        if "seal_size_mm" not in existing:
            connection.execute(text("ALTER TABLE companies ADD COLUMN seal_size_mm FLOAT NOT NULL DEFAULT 20"))


def ensure_contract_columns():
    """Preserve existing contracts; an unknown signing date stays empty."""
    existing = {column["name"] for column in inspect(engine).get_columns("contracts")}
    if "contract_date" not in existing:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE contracts ADD COLUMN contract_date DATE"))


def seed_builtin_templates(db: Session):
    """기본 양식 라이브러리를 DB에 반영 (코드 정의가 정본)."""
    active_keys = {t["key"] for t in BUILTIN_TEMPLATES}
    for t in BUILTIN_TEMPLATES:
        row = db.scalar(select(Template).where(Template.key == t["key"]))
        definition = dict(t["definition"])
        if row is None:
            row = Template(key=t["key"], kind="builtin", owner_id=None)
            db.add(row)
        row.name, row.category, row.description = t["name"], t["category"], t["description"]
        row.aliases, row.definition, row.status = t["aliases"], definition, "ready"
    for row in db.scalars(select(Template).where(Template.kind == "builtin")).all():
        if row.key not in active_keys:
            row.status = "archived"
    db.commit()


def purge_expired_uploads(db: Session) -> int:
    """보관기간이 지난 업로드 원본 파일 삭제 (양식의 매핑 정보는 남겨 재구성 가능)."""
    rows = db.scalars(select(Template).where(Template.kind == "uploaded", Template.expires_at < datetime.utcnow(), Template.source_path.is_not(None))).all()
    for t in rows:
        remove(db, t)
        db.add(AuditLog(user_id=t.owner_id, action="file_purge", detail=f"보관기간 경과로 '{t.name}' 원본 삭제"))
        t.source_path = None
    db.commit()
    return len(rows)


@asynccontextmanager
async def lifespan(_: FastAPI):
    from app.core.encryption import cipher
    cipher()  # Fail closed if encryption keys are missing or invalid.
    if not settings.CLOUD_MODE:
        Base.metadata.create_all(engine)
        ensure_company_columns()
        ensure_contract_columns()
    with SessionLocal() as db:
        if not settings.CLOUD_MODE:
            seed_builtin_templates(db)
        n = purge_expired_uploads(db)
    log.info("AI 모드: %s / 만료 원본 삭제 %d건", "LLM" if settings.ai_enabled else "규칙 기반", n)
    import asyncio
    async def periodic_cleanup():
        while True:
            await asyncio.sleep(3600)
            try:
                def run():
                    with SessionLocal() as session:
                        maintenance(session)
                await asyncio.to_thread(run)
            except Exception:
                log.error("Scheduled cleanup failed; inspect server/database health.")
    task = asyncio.create_task(periodic_cleanup()) if not settings.CLOUD_MODE else None
    try:
        yield
    finally:
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="계약·행정서류 자동화 API", version="0.1.0", lifespan=lifespan)
app.add_middleware(TemporaryFilesMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_credentials=True, allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"], allow_headers=["Content-Type", "X-CSRF-Token", "X-Sensitive-Grant"], expose_headers=["Content-Disposition", "X-Reauthentication-Scope"])

API = "/api/v1"
for r in (auth.router, company.router, contracts.router, documents.router, templates.router, privacy.router, custom_plans.router, account_security.router, document_workflow.router):
    app.include_router(r, prefix=API)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    return response


def maintenance(db):
    from sqlalchemy import delete
    from datetime import timedelta
    from app.models import AuthSession, AuthThrottle, SensitiveGrant, MfaChallenge, MfaCredential, WorkspaceState
    now = datetime.utcnow()
    count = purge_expired_uploads(db)
    db.execute(delete(SensitiveGrant).where(SensitiveGrant.expires_at < now))
    expired = select(AuthSession.token_hash).where(AuthSession.expires_at < now)
    db.execute(delete(SensitiveGrant).where(SensitiveGrant.session_hash.in_(expired)))
    db.execute(delete(AuthSession).where(AuthSession.expires_at < now))
    db.execute(delete(AuthThrottle).where(AuthThrottle.window_start < now - timedelta(days=1)))
    db.execute(delete(MfaChallenge).where(MfaChallenge.expires_at < now))
    db.execute(delete(MfaCredential).where(MfaCredential.enabled == 0, MfaCredential.pending_expires < now))
    db.execute(delete(WorkspaceState).where(WorkspaceState.slot!='notice',WorkspaceState.updated_at < now-timedelta(days=30)))
    # Crash recovery: only generated temp files in the upload root, never originals in user folders.
    for path in settings.UPLOAD_DIR.glob("tmp*"):
        import time
        if path.is_file() and path.stat().st_mtime < time.time() - 3600:
            path.unlink(missing_ok=True)
    db.commit()
    return count


@app.get(f"{API}/internal/maintenance")
def scheduled_maintenance(request: Request, db: Session = Depends(get_db)):
    import hmac
    import os
    from fastapi import HTTPException
    secret = os.getenv("CRON_SECRET", "")
    if len(secret) < 32 or not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + secret):
        raise HTTPException(401, "인증이 필요합니다.")
    return {"purged": maintenance(db)}


@app.get(f"{API}/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "ai_mode": "llm" if settings.ai_enabled else "rule", "mail_mode": "smtp" if settings.SMTP_HOST else "mock", "cloud_mode": settings.CLOUD_MODE,
            "limits": {"upload_mb": settings.MAX_UPLOAD_MB, "hwp_conversion": not settings.CLOUD_MODE, "uploaded_hangul_pdf": not settings.CLOUD_MODE}}


@app.get(f"{API}/audit-logs")
def audit_logs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """내 민감정보 처리 이력 (AI 전송·메일·파일 삭제)."""
    rows = db.scalars(select(AuditLog).where(AuditLog.user_id == user.id).order_by(AuditLog.id.desc()).limit(100)).all()
    return [{"id": r.id, "action": r.action, "detail": r.detail, "created_at": r.created_at} for r in rows]
