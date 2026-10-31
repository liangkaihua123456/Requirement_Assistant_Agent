"""用户存储仓库 —— 封装用户与密码重置 token 的 CRUD。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.core.security import hash_reset_token
from app.storage.db import PasswordResetTokenRecord, UserRecord, get_db_session


def _to_dict(record: UserRecord) -> dict:
    return {
        "id": record.id,
        "username": record.username,
        "email": record.email,
        "password_hash": record.password_hash,
        "is_active": bool(record.is_active),
        "created_at": str(record.created_at) if record.created_at else None,
    }


async def get_by_id(user_id: int) -> dict | None:
    async with get_db_session() as session:
        record = await session.get(UserRecord, user_id)
        return _to_dict(record) if record else None


async def get_by_username(username: str) -> dict | None:
    async with get_db_session() as session:
        result = await session.execute(
            select(UserRecord).where(UserRecord.username == username)
        )
        record = result.scalar_one_or_none()
        return _to_dict(record) if record else None


async def get_by_email(email: str) -> dict | None:
    async with get_db_session() as session:
        result = await session.execute(
            select(UserRecord).where(UserRecord.email == email)
        )
        record = result.scalar_one_or_none()
        return _to_dict(record) if record else None


async def create_user(username: str, password_hash: str, email: str | None = None) -> dict:
    async with get_db_session() as session:
        record = UserRecord(
            username=username,
            email=email,
            password_hash=password_hash,
            is_active=1,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return _to_dict(record)


async def update_password(user_id: int, password_hash: str) -> None:
    async with get_db_session() as session:
        record = await session.get(UserRecord, user_id)
        if record is not None:
            record.password_hash = password_hash
            await session.commit()


# ---------- 密码重置 token ----------
async def save_reset_token(user_id: int, token_hash: str, expires_at: datetime) -> None:
    async with get_db_session() as session:
        session.add(
            PasswordResetTokenRecord(
                user_id=user_id,
                token_hash=token_hash,
                expires_at=expires_at,
                used=0,
            )
        )
        await session.commit()


async def consume_reset_token(raw_token: str) -> dict | None:
    """校验并标记 token 为已使用；有效返回 {user_id,...}，否则 None。"""
    token_hash = hash_reset_token(raw_token)
    async with get_db_session() as session:
        result = await session.execute(
            select(PasswordResetTokenRecord).where(
                PasswordResetTokenRecord.token_hash == token_hash,
                PasswordResetTokenRecord.used == 0,
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        now = datetime.now(timezone.utc)
        expires = record.expires_at
        if expires and expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires is not None and expires < now:
            return None
        record.used = 1
        await session.commit()
        return {"user_id": record.user_id}
