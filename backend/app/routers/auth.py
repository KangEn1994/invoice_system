from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_token,
    verify_password,
)
from app.deps import get_current_admin
from app.models import AdminUser, AuthSession
from app.schemas import AdminMeResponse, LoginRequest, LogoutRequest, RefreshRequest, TokenResponse


router = APIRouter(prefix="/auth", tags=["auth"])


def _build_token_response(db: Session, user: AdminUser, session: AuthSession) -> TokenResponse:
    access_token = create_access_token(user_id=user.id, username=user.username)
    refresh_token = create_refresh_token(session_id=session.id, user_id=user.id)

    session.refresh_token_hash = hash_token(refresh_token)
    session.expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    session.last_seen_at = datetime.now(timezone.utc)
    db.add(session)
    db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(AdminUser).where(AdminUser.username == payload.username))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已禁用")

    session = AuthSession(
        id=uuid.uuid4(),
        user_id=user.id,
        refresh_token_hash="",
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    return _build_token_response(db=db, user=user, session=session)


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> TokenResponse:
    try:
        token_payload = decode_token(payload.refresh_token)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="refresh token 无效") from exc

    if token_payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token 类型错误")

    session_id = token_payload.get("sid")
    user_id = token_payload.get("sub")
    if not session_id or not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="refresh token 无效")

    session = db.get(AuthSession, uuid.UUID(session_id))
    if not session or session.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="session 已失效")

    if session.user_id != int(user_id):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="session 不匹配")

    if session.refresh_token_hash != hash_token(payload.refresh_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="refresh token 不匹配")

    if session.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="session 已过期")

    user = db.get(AdminUser, session.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户无效")

    return _build_token_response(db=db, user=user, session=session)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: LogoutRequest, db: Session = Depends(get_db)) -> None:
    try:
        token_payload = decode_token(payload.refresh_token)
        if token_payload.get("type") != "refresh":
            return
        session_id = token_payload.get("sid")
        if not session_id:
            return
        session = db.get(AuthSession, uuid.UUID(session_id))
        if not session:
            return
        session.revoked_at = datetime.now(timezone.utc)
        db.add(session)
        db.commit()
    except Exception:
        return


@router.get("/me", response_model=AdminMeResponse)
def me(current_admin: AdminUser = Depends(get_current_admin)) -> AdminMeResponse:
    return AdminMeResponse(id=current_admin.id, username=current_admin.username, role="admin")
