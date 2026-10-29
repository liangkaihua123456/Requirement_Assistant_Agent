"""DingTalk 消息到任务队列的业务桥接。"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.config import get_settings
from app.core.observability import merge_task_metric
from app.core.task_queue import enqueue_resume, enqueue_start
from app.graph.checkpoints import has_checkpoint
from app.storage import dingtalk as dingtalk_repo
from app.storage import repo_task

# 同一会话串行处理；多进程时还有 DB 的部分唯一索引兜底。
_locks: dict[str, asyncio.Lock] = {}


def conversation_lock(conversation_id: str) -> asyncio.Lock:
    lock = _locks.get(conversation_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[conversation_id] = lock
    return lock


async def create_task_from_dingtalk(
    conversation_id: str,
    text: str,
    requester_staff_id: str,
    session_webhook: str,
) -> tuple[str | None, str]:
    """创建任务并绑定会话。

    调用方（handler）已经持有会话锁；这里不要重复加锁，否则会死锁。
    多进程场景由 dingtalk_bindings 的部分唯一索引兜底。

    返回 (task_id, error)：error 为空表示成功；"busy" 表示当前会话已有任务。
    """
    if await dingtalk_repo.get_active_binding(conversation_id):
        return None, "busy"

    task_id = await repo_task.create_task(text)
    binding_ok = await dingtalk_repo.create_binding(
        conversation_id=conversation_id,
        task_id=task_id,
        requester_staff_id=requester_staff_id,
        session_webhook=session_webhook,
    )
    if not binding_ok:
        await repo_task.update_task(
            task_id,
            status="error",
            state_snapshot={
                "task_id": task_id,
                "error_message": "该会话已有进行中的任务",
            },
        )
        return None, "busy"

    initial_state: dict[str, Any] = {
        "user_input": text,
        "task_id": task_id,
        "max_reflow_count": get_settings().max_reflow_count,
        "metadata": {
            "task_id": task_id,
            "metrics": {
                "api_timeout": False,
                "background_task_success": None,
            },
        },
    }
    initial_state = merge_task_metric(initial_state, api_timeout=False)
    await repo_task.update_task(
        task_id,
        status="queued",
        current_node="queued",
        state_snapshot=initial_state,
    )
    await enqueue_start(task_id, initial_state)
    return task_id, ""


async def submit_feedback(
    task_id: str,
    approved: bool | None,
    feedback: str,
) -> tuple[bool, str]:
    """复刻 REST 的 feedback 校验与 resume 逻辑。"""
    task = await repo_task.get_task(task_id)
    if task is None:
        return False, "not_found"
    if task["status"] != "waiting_human":
        return False, "not_waiting"
    if not has_checkpoint(task_id):
        return False, "missing_checkpoint"

    await repo_task.save_feedback(
        task_id,
        content=feedback,
        node=task["current_node"],
        feedback_type="approval" if approved is not None else "clarification",
    )
    resume_data: Any = (
        {"approved": approved, "feedback": feedback}
        if approved is not None
        else feedback
    )
    state_snapshot = merge_task_metric(
        task.get("state_snapshot") or {},
        resume_requested=True,
        resume_success=None,
    )
    await repo_task.update_task(
        task_id,
        status="queued",
        current_node="queued",
        state_snapshot=state_snapshot,
    )
    await dingtalk_repo.clear_pending(task_id)
    await enqueue_resume(task_id, resume_data)
    return True, "queued"


async def get_task(task_id: str) -> dict[str, Any] | None:
    return await repo_task.get_task(task_id)


async def get_active_binding(conversation_id: str) -> dict[str, Any] | None:
    return await dingtalk_repo.get_active_binding(conversation_id)
