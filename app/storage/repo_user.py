"""用户存储仓库 —— 封装用户与密码重置 token 的 CRUD。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.core.security import hash_password, hash_reset_token, verify_password
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


# ---------- 演示账号 ----------
DEMO_USERNAME = "admin"
DEMO_PASSWORD = "admin"  # 仅演示用途，写死为 admin/admin


async def ensure_demo_admin() -> dict:
    """确保演示账号 admin/admin 可用（写死演示密码）。

    - 无 admin 用户 → 创建；
    - 已存在但密码不是 admin → 重置为 admin（演示语义，保证 demo 永远进得来）。
    仅供本地演示；生产部署请设置 DEMO_ADMIN_ENABLED=false 关闭。
    """
    existing = await get_by_username(DEMO_USERNAME)
    if existing is None:
        return await create_user(DEMO_USERNAME, hash_password(DEMO_PASSWORD), email=None)
    if not verify_password(DEMO_PASSWORD, existing["password_hash"]):
        await update_password(existing["id"], hash_password(DEMO_PASSWORD))
    return existing


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
