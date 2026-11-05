from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String, Text, LargeBinary
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.encryption import EncryptedText, EncryptedJSON, EncryptedBytes


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(50), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    company: Mapped["Company | None"] = relationship(back_populates="user", uselist=False)


class Company(Base):
    """사용자 회사 기본정보 — 한 번 입력 후 모든 서류에 재사용 (최소 수집)."""

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    company_name: Mapped[str] = mapped_column(EncryptedText, default="")
    representative: Mapped[str] = mapped_column(EncryptedText, default="")
    business_number: Mapped[str] = mapped_column(EncryptedText, default="")
    address: Mapped[str] = mapped_column(EncryptedText, default="")
    phone: Mapped[str] = mapped_column(EncryptedText, default="")
    email: Mapped[str] = mapped_column(EncryptedText, default="")
    manager_name: Mapped[str] = mapped_column(EncryptedText, default="")
    business_type: Mapped[str] = mapped_column(EncryptedText, default="")
    business_item: Mapped[str] = mapped_column(EncryptedText, default="")
    bank_name: Mapped[str] = mapped_column(EncryptedText, default="")
    account_number: Mapped[str] = mapped_column(EncryptedText, default="")
    account_holder: Mapped[str] = mapped_column(EncryptedText, default="")
    seal_image: Mapped[str] = mapped_column(EncryptedText, default="")  # Normalized PNG data URI, owner-only.
    seal_size_mm: Mapped[float] = mapped_column(Float, default=20)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="company")


class Contract(Base):
    __tablename__ = "contracts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    contract_title: Mapped[str] = mapped_column(EncryptedText)
    client_name: Mapped[str] = mapped_column(EncryptedText, default="")  # 발주처
    amount: Mapped[int] = mapped_column(Integer, default=0)  # 계약금액(부가세 포함, 원)
    contract_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str] = mapped_column(EncryptedText, default="")  # 업무내용
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    documents: Mapped[list["Document"]] = relationship(back_populates="contract", cascade="all, delete-orphan")
    workspace_states: Mapped[list["WorkspaceState"]] = relationship(cascade="all, delete-orphan")
    user: Mapped[User] = relationship()


class Template(Base):
    """서류 양식. builtin=서비스 기본 양식(owner 없음), uploaded=기업 자체 양식."""

    __tablename__ = "templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(20), default="builtin")  # builtin | uploaded
    key: Mapped[str | None] = mapped_column(String(50), nullable=True, unique=True)  # builtin 식별자
    name: Mapped[str] = mapped_column(EncryptedText)
    category: Mapped[str] = mapped_column(String(50), default="기타")
    description: Mapped[str] = mapped_column(EncryptedText, default="")
    aliases: Mapped[list] = mapped_column(EncryptedJSON, default=list)
    # builtin: 렌더링 정의(title/table/body...) / uploaded: 파일 형식 정보
    definition: Mapped[dict] = mapped_column(EncryptedJSON, default=dict)
    # [{label, field_key, location, confidence}]
    fields: Mapped[list] = mapped_column(EncryptedJSON, default=list)
    source_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(10), nullable=True)  # docx | pdf | hwp | hwpx
    status: Mapped[str] = mapped_column(String(20), default="ready")  # analyzing | ready
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Document(Base):
    """계약에 대해 특정 양식으로 작성한 서류 인스턴스."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id"), index=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("templates.id"))
    title: Mapped[str] = mapped_column(EncryptedText)
    values: Mapped[dict] = mapped_column(EncryptedJSON, default=dict)  # field_key -> 값 (사용자 수정 반영)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | reviewed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    contract: Mapped[Contract] = relationship(back_populates="documents")
    template: Mapped[Template] = relationship()


class AuditLog(Base):
    """민감정보 처리 이력 (AI 전송·파일 삭제 등)."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(50))
    detail: Mapped[str] = mapped_column(EncryptedText, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TemplateFavorite(Base):
    __tablename__ = "template_favorites"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("templates.id"), primary_key=True)


class StoredFile(Base):
    """Private small-file persistence for the free cloud deployment."""
    __tablename__ = "stored_files"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    data: Mapped[bytes] = mapped_column(EncryptedBytes)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class LibraryAdmin(Base):
    """Explicit reviewed user IDs; registering a matching email grants no role."""
    __tablename__ = "library_admins"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)


class AuthThrottle(Base):
    __tablename__ = "auth_throttles"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class SensitiveGrant(Base):
    __tablename__ = "sensitive_grants"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_hash: Mapped[str] = mapped_column(ForeignKey("auth_sessions.token_hash", ondelete="CASCADE"), index=True)
    scope: Mapped[str] = mapped_column(String(100))
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class MfaCredential(Base):
    __tablename__ = "mfa_credentials"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    secret: Mapped[str] = mapped_column(EncryptedText)
    enabled: Mapped[int] = mapped_column(Integer, default=0)
    last_step: Mapped[int] = mapped_column(Integer, default=-1)
    pending_session: Mapped[str] = mapped_column(String(64))
    pending_expires: Mapped[datetime] = mapped_column(DateTime)


class MfaRecovery(Base):
    __tablename__ = "mfa_recovery"
    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)


class MfaChallenge(Base):
    __tablename__ = "mfa_challenges"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class WorkspaceState(Base):
    __tablename__ = 'workspace_states'
    contract_id: Mapped[int] = mapped_column(ForeignKey('contracts.id', ondelete='CASCADE'), primary_key=True)
    slot: Mapped[str] = mapped_column(String(40), primary_key=True)
    payload: Mapped[dict] = mapped_column(EncryptedJSON, default=dict)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
