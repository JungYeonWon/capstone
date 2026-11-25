from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from pydantic import HttpUrl


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- auth
class RegisterIn(BaseModel):
    email: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=6, max_length=100)
    name: str = ""


class LoginIn(BaseModel):
    email: str
    password: str


class UserOut(ORM):
    id: int
    email: str
    name: str


# ---------- company
class CompanyIn(BaseModel):
    company_name: str = ""
    representative: str = ""
    business_number: str = ""
    address: str = ""
    phone: str = ""
    email: str = ""
    manager_name: str = ""
    business_type: str = ""
    business_item: str = ""
    bank_name: str = ""
    account_number: str = ""
    account_holder: str = ""


class CompanyOut(CompanyIn, ORM):
    id: int
    updated_at: datetime
    seal_image: str = ""
    seal_size_mm: float = 20
    has_seal: bool = False


class SealSizeIn(BaseModel):
    size_mm: float = Field(ge=10, le=30)


# ---------- contract
class ContractIn(BaseModel):
    contract_title: str = Field(min_length=1, max_length=200)
    client_name: str = ""
    amount: int = Field(default=0, ge=0)
    contract_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None
    description: str = ""


class ContractOut(ContractIn, ORM):
    id: int
    created_at: datetime
    document_count: int = 0


# ---------- template
class TemplateField(BaseModel):
    label: str
    field_key: str | None = None
    confidence: float = 0
    method: str = "rule"
    context: str = ""
    location: dict = {}


class TemplateOut(ORM):
    id: int
    kind: str
    name: str
    category: str
    description: str
    aliases: list = []
    fields: list[TemplateField] = []
    field_keys: list[str] = []
    source_type: str | None = None
    output_format: str = "docx"
    status: str
    expires_at: datetime | None = None
    created_at: datetime


class TemplateMappingIn(BaseModel):
    name: str | None = None
    category: str | None = None
    fields: list[TemplateField]


class TemplateRenameIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)


class FavoriteIn(BaseModel):
    favorite: bool


class LibraryMetadataIn(BaseModel):
    scope: Literal["private", "organization"] = "private"
    organization: str = Field(default="", max_length=100)
    document_type: str = Field(default="", max_length=100)
    source_url: HttpUrl | None = None
    source_date: date | None = None
    version: str = Field(default="", max_length=100)
    project_code: str = Field(default="", max_length=100)
    usage_terms: str = Field(default="", max_length=1000)
    review_note: str = Field(default="", max_length=1000)


class LibraryPublishIn(BaseModel):
    mapping_checked: bool
    output_checked: bool
    rights_checked: bool


class SearchResult(BaseModel):
    template: TemplateOut
    score: float
    ai: bool = False


# ---------- document
class DocumentCreate(BaseModel):
    template_id: int
    project_code: str = ""


class DocumentUpdate(BaseModel):
    values: dict[str, str]
    expected_updated_at: datetime | None = None


class DocumentOut(ORM):
    id: int
    contract_id: int
    template_id: int
    title: str
    values: dict
    status: str
    created_at: datetime
    updated_at: datetime
    template_kind: str = ""
    output_format: str = "docx"
    field_keys: list[str] = []
    missing: list[str] = []


class MailIn(BaseModel):
    to: str
    subject: str = ""
    body: str = ""
    document_ids: list[int]
    format: str = "native"  # native | pdf | both
