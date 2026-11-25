"""Owner-scoped workflow sessions and explicit conversion to editable documents."""
import json
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.core.security import get_current_user
from app.models import AuditLog, Document, Template, User, WorkspaceState
from app.routers.contracts import get_owned
from app.routers.contract_review import read_source, review_preview
from app.routers.document_workflow import authorize_ai
from app.services import ai_workflows as flow, custom_plans as plans
from app.services.contract_review import ReviewIn
from app.services.documents import to_out
from app.services.notice_files import MAX_FILE

router = APIRouter(prefix='/contracts/{contract_id}/ai-workflows', tags=['ai-workflows'])


def transmission(db, user, contract_id, mode, body):
    contract = get_owned(db, user, contract_id)
    sources, warning = [], ''
    if body.document_id:
        preview = review_preview(db, user, contract_id, ReviewIn(role=body.role, document_id=body.document_id))
        sources = json.loads(preview['payload_preview'])['sources']
        warning = preview['warning']
    return flow.preview(mode, body, contract, sources, warning)


@router.post('/extract')
async def extract(contract_id: int, file: UploadFile = File(...),
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    get_owned(db, user, contract_id)
    data = await file.read(MAX_FILE + 1)
    parts, warning = await run_in_threadpool(read_source, data, file.filename or '')
    return {'name': (file.filename or '자료')[:180], 'parts': parts, 'warning': warning}


@router.post('/{mode}/preview')
def preview(contract_id: int, mode: flow.Mode, body: flow.WorkflowInput,
            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return transmission(db, user, contract_id, mode, body)


@router.post('/{mode}/analyze')
def analyze(contract_id: int, mode: flow.Mode, body: flow.WorkflowInput, request: Request,
            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    preview = transmission(db, user, contract_id, mode, body)
    # A single shared purpose prevents bypassing the paid-call limit by switching tabs.
    authorize_ai(db, user, request, body, preview, 'contract-workflow-ai')
    return {'result': flow.analyze(mode, preview['payload_preview']), 'sources': json.loads(preview['payload_preview'])['sources'],
            'warning': preview['warning'], 'consent_digest': preview['consent_digest']}


class RunResult(flow.Strict):
    result: flow.WorkflowResult
    sources: list[dict] = Field(max_length=140)
    warning: str = Field(default='', max_length=7000)
    consent_digest: str = Field(max_length=64)


class DraftChange(flow.Strict):
    id: str = Field(min_length=1, max_length=180)
    kind: str = Field(max_length=30)
    type: Literal['title', 'section', 'add_section', 'remove_section', 'add_document', 'remove_document']
    section_id: str = Field(default='', max_length=100)
    before: flow.DraftSection | None = None
    after: flow.DraftSection | None = None
    before_title: str = Field(default='', max_length=100)
    after_title: str = Field(default='', max_length=100)
    document: flow.Draft | None = None
    protected: bool = True


class SessionPayload(flow.Strict):
    input: flow.WorkflowInput
    output: RunResult | None = None
    estimate_lines: list[flow.EstimateLine] = Field(default_factory=list, max_length=30)
    output_stale: bool = False
    draft_baseline: list[flow.Draft] = Field(default_factory=list, max_length=3)
    draft_changes: list[DraftChange] = Field(default_factory=list, max_length=70)


class SessionIn(flow.Strict):
    payload: SessionPayload
    revision: int = Field(ge=0)


@router.get('/{mode}/session')
def get_session(contract_id: int, mode: flow.Mode, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    get_owned(db, user, contract_id)
    row = db.get(WorkspaceState, (contract_id, f'assistant_{mode}'))
    return {'payload': row.payload if row else None, 'revision': row.revision if row else 0}


@router.put('/{mode}/session')
def save_session(contract_id: int, mode: flow.Mode, body: SessionIn,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    get_owned(db, user, contract_id)
    if body.payload.input.document_id:
        from app.routers.documents import get_owned_doc
        document = get_owned_doc(db, user, body.payload.input.document_id)
        if document.contract_id != contract_id: raise HTTPException(404, '다른 계약의 서류입니다.')
    payload = body.payload.model_dump()
    if len(json.dumps(payload, ensure_ascii=False).encode()) > 640000:
        raise HTTPException(413, '저장 용량을 초과했습니다. 입력 자료를 줄여주세요.')
    if body.payload.output:
        try: flow.validate_result(mode, body.payload.output.result, body.payload.output.sources)
        except (ValueError, KeyError, TypeError): raise HTTPException(422, '저장할 분석 결과의 근거를 확인하세요.') from None
        payload = body.payload.model_dump()
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    insert = pg_insert if db.bind.dialect.name == 'postgresql' else sqlite_insert
    slot = f'assistant_{mode}'
    db.execute(insert(WorkspaceState).values(contract_id=contract_id, slot=slot, payload={}, revision=0, updated_at=datetime.utcnow()).on_conflict_do_nothing())
    revision = db.scalar(update(WorkspaceState).where(WorkspaceState.contract_id == contract_id,
        WorkspaceState.slot == slot, WorkspaceState.revision == body.revision)
        .values(payload=payload, revision=body.revision + 1, updated_at=datetime.utcnow()).returning(WorkspaceState.revision))
    if revision is None:
        db.rollback()
        raise HTTPException(409, '다른 창에서 작업을 저장했습니다. 현재 내용을 복사한 뒤 새로 불러오세요.')
    db.commit()
    return {'revision': revision}


class CreateDraft(flow.Strict):
    draft: flow.Draft
    acknowledge_draft: bool = False
    estimate_lines: list[flow.EstimateLine] = Field(default_factory=list, max_length=30)


@router.post('/{mode}/documents')
def create_document(contract_id: int, mode: flow.Mode, body: CreateDraft,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    contract = get_owned(db, user, contract_id)
    if body.draft.kind not in flow.KINDS[mode]: raise HTTPException(422, '이 기능에서 생성할 수 없는 서류 종류입니다.')
    if not body.acknowledge_draft: raise HTTPException(400, '미확정 조건이 있는 검토용 초안임을 확인하세요.')
    if body.estimate_lines and body.draft.kind != 'estimate': raise HTTPException(422, '견적 문서에만 계산 항목을 넣을 수 있습니다.')
    if body.draft.kind == 'estimate' and not body.estimate_lines: raise HTTPException(422, '견적 항목의 단가와 수량을 입력하세요.')
    # Serialize the per-account template limit, as each conversion creates a private layout.
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    if db.scalar(select(func.count()).select_from(Template).where(Template.owner_id == user.id, Template.kind == 'custom')) >= 50:
        raise HTTPException(413, '맞춤 양식은 계정당 50개까지 저장할 수 있습니다.')
    sections = list(body.draft.sections)
    if body.draft.kind == 'estimate':
        amounts = flow.estimate(body.estimate_lines)
        rows = [f'{line.label}: {line.quantity}{line.unit} × {line.unit_price}원 = {amount}원' for line, amount in zip(body.estimate_lines, amounts['amounts'])]
        rows.append(f"합계: {amounts['total']}원 (부가세·할인 미적용, 사용자 입력 기준)")
        sections.append(flow.DraftSection(label='사용자 입력 견적 계산', text='\n'.join(rows)))
    layout = plans.PlanLayout(title=body.draft.title, document_type='free', sections=[
        plans.PlanSection(key=f'custom_{i}', label=s.label) for i, s in enumerate(sections, 1)])
    definition = plans.definition(layout, flow.TITLES[mode], 'user_reviewed')
    definition['custom_plan']['workflow'] = mode
    template = Template(kind='custom', owner_id=user.id, name=layout.title, category='AI 업무 초안',
        description='사용자가 내용을 검토한 업무 초안 · 지정 서식 아님', aliases=[], definition=definition,
        fields=[{'label': s.label, 'field_key': s.key, 'method': 'user', 'location': {}} for s in layout.sections], status='ready')
    db.add(template); db.flush()
    values = plans.values(template, user.company, contract)
    values.update({f'custom_{i}': '[검토용 초안] ' + s.text for i, s in enumerate(sections, 1)})
    document = Document(contract_id=contract.id, template_id=template.id, title=layout.title, values=values, status='draft')
    db.add(document); db.flush()
    db.add(AuditLog(user_id=user.id, action='workflow_document', detail=f'{mode}; contract:{contract.id}; document:{document.id}'))
    db.commit()
    return {'document': to_out(document)}
