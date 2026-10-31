"""安全与 JWT 工具。

- 密码哈希（bcrypt）
- access / refresh token 的签发与校验（PyJWT）
- 忘记密码的一次性重置 token 生成与哈希
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.core.config import get_settings

# ---------- 密码 ----------
# bcrypt 仅使用前 72 字节，超出部分需手动截断（bcrypt 5.x 会抛错）
def _pw_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:72]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_pw_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_pw_bytes(password), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ---------- JWT ----------
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _create_token(subject: str, token_type: str, expires_delta: timedelta) -> str:
    settings = get_settings()
    now = _utcnow()
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "jti": secrets.token_hex(16),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: int) -> str:
    settings = get_settings()
    return _create_token(user_id, "access", timedelta(minutes=settings.access_token_expire_minutes))


def create_refresh_token(user_id: int) -> str:
    settings = get_settings()
    return _create_token(user_id, "refresh", timedelta(days=settings.refresh_token_expire_days))


def decode_token(token: str, expected_type: str | None = None) -> dict[str, Any]:
    """解码并校验 token。无效/过期抛 jwt 异常，由调用方处理。"""
    settings = get_settings()
    payload = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )
    if expected_type is not None and payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("token type mismatch")
    return payload


# ---------- 密码重置 token ----------
def generate_reset_token() -> tuple[str, str]:
    """返回 (明文 token, sha256 哈希)。明文发给用户，库里只存哈希。"""
    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode("utf-8")).hexdigest()


def hash_reset_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
