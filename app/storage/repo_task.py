"""任务存储仓库 —— 封装任务 CRUD 操作。"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import select, update

from app.storage.db import TaskRecord, FeedbackRecord, get_db_session


async def create_task(user_input: str, user_id: int | None = None) -> str:
    """创建新任务，返回 task_id。"""
    task_id = str(uuid.uuid4())[:8]
    async with get_db_session() as session:
        record = TaskRecord(
            task_id=task_id,
            user_input=user_input,
            user_id=user_id,
            status="created",
        )
        session.add(record)
        await session.commit()
    return task_id


async def get_task(task_id: str) -> dict | None:
    """根据 task_id 查询任务。"""
    async with get_db_session() as session:
        stmt = select(TaskRecord).where(TaskRecord.task_id == task_id)
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return {
            "task_id": record.task_id,
            "user_id": record.user_id,
            "user_input": record.user_input,
            "status": record.status,
            "current_node": record.current_node,
            "state_snapshot": json.loads(record.state_snapshot or "{}"),
            "result": json.loads(record.result or "{}"),
            "reflow_count": record.reflow_count,
            "created_at": str(record.created_at),
            "updated_at": str(record.updated_at),
        }


async def update_task(task_id: str, **kwargs) -> None:
    """更新任务字段。"""
    async with get_db_session() as session:
        # 特殊处理 dict -> json 字段
        for key in ("state_snapshot", "result"):
            if key in kwargs and isinstance(kwargs[key], dict):
                kwargs[key] = json.dumps(kwargs[key], ensure_ascii=False)
        stmt = update(TaskRecord).where(TaskRecord.task_id == task_id).values(**kwargs)
        await session.execute(stmt)
        await session.commit()


async def save_feedback(task_id: str, content: str, node: str = "", feedback_type: str = "general") -> None:
    """保存人工反馈记录。"""
    async with get_db_session() as session:
        record = FeedbackRecord(
            task_id=task_id,
            node=node,
            feedback_type=feedback_type,
            content=content,
        )
        session.add(record)
        await session.commit()


async def list_tasks(limit: int = 50, offset: int = 0, user_id: int | None = None) -> list[dict]:
    """列出任务（分页，可按用户隔离）。"""
    async with get_db_session() as session:
        stmt = select(TaskRecord)
        if user_id is not None:
            stmt = stmt.where(TaskRecord.user_id == user_id)
        stmt = (
            stmt.order_by(TaskRecord.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await session.execute(stmt)
        records = result.scalars().all()
        return [
            {
                "task_id": r.task_id,
                "user_input": r.user_input[:100],
                "status": r.status,
                "current_node": r.current_node,
                "created_at": str(r.created_at),
            }
            for r in records
        ]


async def list_tasks_by_status(statuses: list[str], limit: int = 200) -> list[dict]:
    """List tasks whose status is in the provided set."""
    if not statuses:
        return []
    async with get_db_session() as session:
        stmt = (
            select(TaskRecord)
            .where(TaskRecord.status.in_(statuses))
            .order_by(TaskRecord.updated_at.asc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        records = result.scalars().all()
        return [
            {
                "task_id": r.task_id,
                "user_input": r.user_input,
                "status": r.status,
                "current_node": r.current_node,
                "state_snapshot": json.loads(r.state_snapshot or "{}"),
                "result": json.loads(r.result or "{}"),
                "reflow_count": r.reflow_count,
                "created_at": str(r.created_at),
                "updated_at": str(r.updated_at),
            }
            for r in records
        ]
