"""任务存储仓库 —— 封装任务 CRUD 操作。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, delete, func, or_, select, update

from app.storage.db import TaskRecord, FeedbackRecord, get_db_session


async def create_task(user_input: str) -> str:
    """创建新任务，返回 task_id。"""
    task_id = str(uuid.uuid4())[:8]
    async with get_db_session() as session:
        record = TaskRecord(
            task_id=task_id,
            user_input=user_input,
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


async def list_tasks(limit: int = 50, offset: int = 0) -> list[dict]:
    """列出任务（分页），附带列表页需要的质量与耗时指标。"""
    async with get_db_session() as session:
        stmt = (
            select(TaskRecord)
            .order_by(TaskRecord.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await session.execute(stmt)
        records = result.scalars().all()
        return [_task_summary(r) for r in records]


async def count_tasks_by_status() -> dict[str, int]:
    """按状态统计任务数，供仪表盘使用。"""
    async with get_db_session() as session:
        rows = (
            await session.execute(
                select(TaskRecord.status, func.count()).group_by(TaskRecord.status)
            )
        ).all()
    return {str(status): int(count) for status, count in rows}


async def list_tasks_page(
    limit: int = 20,
    offset: int = 0,
    status: str | None = None,
    q: str | None = None,
) -> dict:
    """服务端分页，支持状态过滤与关键词搜索，返回当前页与总数。"""
    async with get_db_session() as session:
        conditions = []
        if status and status != "all":
            conditions.append(TaskRecord.status == status)
        if q:
            like = f"%{q}%"
            conditions.append(
                or_(TaskRecord.task_id.like(like), TaskRecord.user_input.like(like))
            )
        condition = and_(*conditions) if conditions else None

        total_stmt = select(func.count()).select_from(TaskRecord)
        if condition is not None:
            total_stmt = total_stmt.where(condition)
        total = int((await session.execute(total_stmt)).scalar_one())

        stmt = (
            select(TaskRecord)
            .order_by(TaskRecord.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        if condition is not None:
            stmt = stmt.where(condition)
        records = (await session.execute(stmt)).scalars().all()

    return {"items": [_task_summary(record) for record in records], "total": total}


async def delete_task(task_id: str) -> bool:
    """删除任务记录，返回是否命中。"""
    async with get_db_session() as session:
        result = await session.execute(
            delete(TaskRecord).where(TaskRecord.task_id == task_id)
        )
        await session.commit()
    return bool(result.rowcount)


async def list_expired_tasks(
    cutoff: datetime, statuses: list[str], limit: int = 200
) -> list[str]:
    """列出早于 cutoff 且处于终态的任务 ID，用于归档清理。"""
    async with get_db_session() as session:
        stmt = (
            select(TaskRecord.task_id)
            .where(
                TaskRecord.created_at < cutoff,
                TaskRecord.status.in_(statuses),
            )
            .order_by(TaskRecord.created_at.asc())
            .limit(limit)
        )
        rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


async def delete_tasks(task_ids: list[str]) -> int:
    """批量删除任务记录。"""
    if not task_ids:
        return 0
    async with get_db_session() as session:
        result = await session.execute(
            delete(TaskRecord).where(TaskRecord.task_id.in_(task_ids))
        )
        await session.commit()
    return int(result.rowcount or 0)


async def list_usage_records(days: int = 30, limit: int = 500) -> list[dict]:
    """按时间窗口读取任务的 token 用量，供统计页聚合。"""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    async with get_db_session() as session:
        stmt = (
            select(TaskRecord)
            .where(TaskRecord.created_at >= cutoff)
            .order_by(TaskRecord.created_at.desc())
            .limit(limit)
        )
        records = (await session.execute(stmt)).scalars().all()

    result = []
    for record in records:
        snapshot = json.loads(record.state_snapshot or "{}")
        metrics = ((snapshot.get("metadata") or {}).get("metrics") or {})
        usage = metrics.get("token_usage") or {}
        if not usage:
            continue
        result.append(
            {
                "task_id": record.task_id,
                "created_at": record.created_at.isoformat() if record.created_at else "",
                "status": record.status,
                "user_input": (record.user_input or "")[:80],
                "usage": usage,
                "duration_seconds": metrics.get("background_duration_seconds"),
            }
        )
    return result


async def list_all_snapshots(limit: int = 2000) -> list[dict]:
    """返回任务的完整快照，用于批量重算成本。"""
    async with get_db_session() as session:
        stmt = (
            select(TaskRecord.task_id, TaskRecord.state_snapshot, TaskRecord.created_at)
            .order_by(TaskRecord.created_at.desc())
            .limit(limit)
        )
        rows = (await session.execute(stmt)).all()
    return [
        {
            "task_id": row[0],
            "state_snapshot": json.loads(row[1] or "{}"),
            # 重算成本时要按任务发生时刻判断高峰/空闲
            "created_at": row[2].isoformat() if row[2] else "",
        }
        for row in rows
    ]


def _task_summary(record: TaskRecord) -> dict:
    snapshot = json.loads(record.state_snapshot or "{}")
    metadata = snapshot.get("metadata") or {}
    metrics = metadata.get("metrics") or {}
    review = snapshot.get("review_result") or {}
    usage = metrics.get("token_usage") or {}
    total_usage = usage.get("total") or {}
    return {
        "task_id": record.task_id,
        "user_input": record.user_input[:100],
        "status": record.status,
        "current_node": record.current_node,
        "created_at": str(record.created_at),
        "overall_score": review.get("overall_score"),
        "review_passed": review.get("passed"),
        "duration_seconds": metrics.get("background_duration_seconds"),
        "llm_calls": metrics.get("llm_call_count"),
        "api_coverage": metadata.get("raw_api_feature_coverage_rate"),
        "db_coverage": metadata.get("raw_db_feature_coverage_rate"),
        "reflow_count": record.reflow_count,
        "total_tokens": total_usage.get("total_tokens"),
        "cost_cny": usage.get("cost_cny"),
    }


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
