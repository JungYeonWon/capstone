import re
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import (SESSION_COOKIE, check_origin, create_access_token, csrf_token,
                               digest, get_current_user, hash_password, set_session_cookie,
                               throttle, verify_password, lock_account)
from app.models import AuditLog, AuthSession, Company, Contract, Document, SensitiveGrant, User, MfaCredential, MfaChallenge
from app.schemas import LoginIn, RegisterIn, UserOut

router = APIRouter(prefix='/auth', tags=['auth'])
_DUMMY_HASH = hash_password('dummy-password-never-used-for-login')


def issue(db, response, request, user):
    old = request.cookies.get(SESSION_COOKIE)
    if old:
        key = digest(old)
        db.execute(delete(SensitiveGrant).where(SensitiveGrant.session_hash == key))
        db.execute(delete(AuthSession).where(AuthSession.token_hash == key))
    token = create_access_token(user.id, db)
    db.add(AuditLog(user_id=user.id, action='login', detail='새 로그인 세션 생성'))
    db.commit()
    set_session_cookie(response, token)
    return {'user': UserOut.model_validate(user), 'csrf_token': csrf_token(token)}


@router.post('/register')
def register(body: RegisterIn, response: Response, request: Request, db: Session = Depends(get_db)):
    check_origin(request)
    email = body.email.strip().lower()
    throttle(db, request, 'register', email)
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, '이미 가입된 이메일입니다.')
    user = User(email=email, password_hash=hash_password(body.password), name=body.name)
    db.add(user); db.flush()
    db.add(Company(user_id=user.id))
    return issue(db, response, request, user)


@router.post('/login')
def login(body: LoginIn, response: Response, request: Request, db: Session = Depends(get_db)):
    check_origin(request)
    email = body.email.strip().lower()
    throttle(db, request, 'login', email)
    user = db.scalar(select(User).where(User.email == email).with_for_update().execution_options(populate_existing=True))
    valid = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not valid:
        db.add(AuditLog(user_id=user.id if user else None, action='login_failed', detail='로그인 인증 실패'))
        db.commit()
        raise HTTPException(401, '이메일 또는 비밀번호가 올바르지 않습니다.')
    credential = db.get(MfaCredential, user.id)
    if credential and credential.enabled:
        raw = secrets.token_urlsafe(32)
        db.execute(delete(MfaChallenge).where(MfaChallenge.expires_at <= datetime.utcnow()))
        db.add(MfaChallenge(token_hash=digest(raw), user_id=user.id,
                            expires_at=datetime.utcnow() + timedelta(minutes=5)))
        db.commit()
        response.headers['Cache-Control'] = 'no-store'
        return {'mfa_required': True, 'challenge': raw}
    return issue(db, response, request, user)


@router.get('/me', response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.get('/csrf')
def csrf(request: Request, user: User = Depends(get_current_user)):
    return {'csrf_token': csrf_token(request.cookies[SESSION_COOKIE])}


@router.get('/sessions')
def sessions(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.expires_at > datetime.utcnow())).all()
    return [{"created_at": row.created_at, "expires_at": row.expires_at,
             "current": row.token_hash == request.state.auth_session.token_hash} for row in rows]


def revoke(db, request, user, all_devices=False):
    query = select(AuthSession.token_hash).where(AuthSession.user_id == user.id)
    if not all_devices:
        query = query.where(AuthSession.token_hash == request.state.auth_session.token_hash)
    keys = list(db.scalars(query))
    db.execute(delete(SensitiveGrant).where(SensitiveGrant.session_hash.in_(keys)))
    db.execute(delete(AuthSession).where(AuthSession.token_hash.in_(keys)))
    if all_devices:
        db.execute(delete(MfaChallenge).where(MfaChallenge.user_id == user.id))
    db.add(AuditLog(user_id=user.id, action='logout_all' if all_devices else 'logout', detail='로그인 세션 폐기'))
    db.commit()


@router.post('/logout')
def logout(request: Request, response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    revoke(db, request, user)
    response.delete_cookie(SESSION_COOKIE, path='/', secure=SESSION_COOKIE.startswith('__Host-'), httponly=True, samesite='strict')
    return {'ok': True}


@router.post('/logout-all')
def logout_all(request: Request, response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lock_account(db, request, user)
    revoke(db, request, user, True)
    response.delete_cookie(SESSION_COOKIE, path='/', secure=SESSION_COOKIE.startswith('__Host-'), httponly=True, samesite='strict')
    return {'ok': True}


class ReauthenticateIn(BaseModel):
    password: str = Field(max_length=100)
    scope: str = Field(max_length=100)
    code: str = Field(default='', max_length=40)


@router.post('/reauthenticate')
def reauthenticate(body: ReauthenticateIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    throttle(db, request, 'reauth', str(user.id))
    lock_account(db, request, user)
    if not verify_password(body.password, user.password_hash):
        db.add(AuditLog(user_id=user.id, action='reauth_failed', detail='민감 작업 재인증 실패')); db.commit()
        raise HTTPException(403, '비밀번호를 확인하세요.')
    credential = db.get(MfaCredential, user.id)
    if credential and credential.enabled:
        from app.core.mfa import verify_factor
        verify_factor(db, credential, body.code)
    valid = body.scope in {'seal:read', 'seal:manage', 'data:delete'}
    match = re.fullmatch(r'(document|contract):(\d+):(download|export|mail)', body.scope)
    if match:
        kind, id_, action = match.groups()
        obj = db.get(Document if kind == 'document' else Contract, int(id_))
        owner = obj.contract.user_id if obj and kind == 'document' else obj.user_id if obj else None
        valid = owner == user.id and action in ({'download'} if kind == 'document' else {'export', 'mail'})
    seal_match = re.fullmatch(r'document:(\d+):seal:([0-9a-f]{64})', body.scope)
    if seal_match:
        from app.services.documents import custom_seal_version
        doc_id, version = seal_match.groups()
        doc = db.get(Document, int(doc_id))
        if doc and doc.contract.user_id == user.id:
            if custom_seal_version(doc, user.company) != version:
                raise HTTPException(409, '문서나 인감이 변경되었습니다. 미리보기를 다시 열어 확인하세요.')
            valid = True
    if not valid:
        raise HTTPException(404, '허용되지 않은 작업입니다.')
    raw = secrets.token_urlsafe(32)
    db.add(SensitiveGrant(token_hash=digest(raw), session_hash=request.state.auth_session.token_hash,
                          scope=body.scope, expires_at=datetime.utcnow() + timedelta(minutes=2)))
    db.add(AuditLog(user_id=user.id, action='reauth', detail=body.scope)); db.commit()
    return {'grant': raw}
