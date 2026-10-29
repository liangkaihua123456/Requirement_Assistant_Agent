"""DingTalk bindings and message-id dedup storage."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

from app.storage.db import (
    DingTalkBinding,
    DingTalkMessage,
    get_db_session,
)


def _binding_dict(row: DingTalkBinding) -> dict[str, Any]:
    raw_payload = getattr(row, "pending_payload", "") or ""
    payload: Any = {}
    if raw_payload:
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError:
            payload = {}
    return {
        "id": row.id,
        "conversation_id": row.conversation_id,
        "task_id": row.task_id,
        "requester_staff_id": row.requester_staff_id or "",
        "active": bool(row.active),
        "pending_kind": row.pending_kind or "",
        "pending_payload": payload,
        "session_webhook": row.session_webhook or "",
        "last_notified_status": row.last_notified_status or "",
    }


async def claim_message(msg_id: str, conversation_id: str) -> bool:
    """原子地占用一个 msgId；返回 False 表示重复消息。"""
    stmt = (
        sqlite_insert(DingTalkMessage)
        .values(msg_id=msg_id, conversation_id=conversation_id)
        .on_conflict_do_nothing(index_elements=["msg_id"])
    )
    async with get_db_session() as session:
        result = await session.execute(stmt)
        await session.commit()
        return (getattr(result, "rowcount", 0) or 0) == 1


async def get_active_binding(conversation_id: str) -> dict[str, Any] | None:
    async with get_db_session() as session:
        stmt = (
            select(DingTalkBinding)
            .where(
                DingTalkBinding.conversation_id == conversation_id,
                DingTalkBinding.active == 1,
            )
            .order_by(DingTalkBinding.id.desc())
        )
        row = (await session.execute(stmt)).scalars().first()
        return _binding_dict(row) if row else None


async def get_binding(task_id: str) -> dict[str, Any] | None:
    async with get_db_session() as session:
        stmt = select(DingTalkBinding).where(DingTalkBinding.task_id == task_id)
        row = (await session.execute(stmt)).scalars().first()
        return _binding_dict(row) if row else None


async def get_latest_binding(conversation_id: str) -> dict[str, Any] | None:
    async with get_db_session() as session:
        stmt = (
            select(DingTalkBinding)
            .where(DingTalkBinding.conversation_id == conversation_id)
            .order_by(DingTalkBinding.id.desc())
        )
        row = (await session.execute(stmt)).scalars().first()
        return _binding_dict(row) if row else None


async def create_binding(
    conversation_id: str,
    task_id: str,
    requester_staff_id: str,
    session_webhook: str,
) -> bool:
    """创建 active 绑定；同一会话已有 active 绑定时返回 False。"""
    async with get_db_session() as session:
        session.add(
            DingTalkBinding(
                conversation_id=conversation_id,
                task_id=task_id,
                requester_staff_id=requester_staff_id,
                active=1,
                session_webhook=session_webhook,
                last_notified_status="queued",
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return False
        return True


async def update_binding(task_id: str, **kwargs: Any) -> None:
    if "pending_payload" in kwargs and not isinstance(kwargs["pending_payload"], str):
        kwargs["pending_payload"] = json.dumps(
            kwargs["pending_payload"], ensure_ascii=False
        )
    if not kwargs:
        return
    async with get_db_session() as session:
        await session.execute(
            update(DingTalkBinding)
            .where(DingTalkBinding.task_id == task_id)
            .values(**kwargs)
        )
        await session.commit()


async def set_pending(
    task_id: str,
    kind: str,
    payload: Any,
    session_webhook: str,
) -> None:
    await update_binding(
        task_id,
        pending_kind=kind,
        pending_payload=payload,
        session_webhook=session_webhook,
        last_notified_status="waiting_human",
    )


async def clear_pending(task_id: str, session_webhook: str = "") -> None:
    values: dict[str, Any] = {
        "pending_kind": "",
        "pending_payload": "",
        "last_notified_status": "queued",
        "active": 1,
    }
    if session_webhook:
        values["session_webhook"] = session_webhook
    await update_binding(task_id, **values)


async def deactivate_binding(task_id: str, status: str) -> None:
    await update_binding(task_id, active=0, last_notified_status=status)


async def list_active_bindings(limit: int = 200) -> list[dict[str, Any]]:
    async with get_db_session() as session:
        stmt = (
            select(DingTalkBinding)
            .where(DingTalkBinding.active == 1)
            .order_by(DingTalkBinding.id.asc())
            .limit(limit)
        )
        rows = (await session.execute(stmt)).scalars().all()
        return [_binding_dict(row) for row in rows]
