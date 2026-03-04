from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from passlib.context import CryptContext

from app.core.config import settings


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
MAX_BCRYPT_PASSWORD_BYTES = 72


def _normalize_password_for_bcrypt(password: str) -> str:
    # bcrypt only accepts up to 72 bytes. For longer secrets, hash first to a fixed-length value.
    password_bytes = password.encode("utf-8")
    if len(password_bytes) <= MAX_BCRYPT_PASSWORD_BYTES:
        return password
    return f"sha256${hashlib.sha256(password_bytes).hexdigest()}"


def get_password_hash(password: str) -> str:
    return pwd_context.hash(_normalize_password_for_bcrypt(password))


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(_normalize_password_for_bcrypt(password), password_hash)


def create_access_token(user_id: int, username: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "username": username,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_expire_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(session_id: UUID, user_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "sid": str(session_id),
        "type": "refresh",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=settings.refresh_token_expire_days)).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
