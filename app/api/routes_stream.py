"""SSE 流式输出路由 —— GET /tasks/{task_id}/stream

从后台 worker 的 per-task 进度队列读取事件并推送给客户端，
不重复执行图，彻底避免与 worker 的竞争。

事件格式（JSON）：
  {"type": "node_start",  "node": "engineer"}
  {"type": "token",       "node": "engineer", "content": "..."}
  {"type": "node_end",    "node": "engineer"}
  {"type": "interrupt",   "node": "human_clarification", "data": {...}}
  {"type": "done",        "status": "completed" | "waiting_human"}
  {"type": "error",       "message": "..."}
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncGenerator

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from app.core.logger import logger
from app.core.task_queue import get_or_create_progress_queue, _PROGRESS_SENTINEL
from app.storage import repo_task

router = APIRouter(prefix="/tasks", tags=["tasks-stream"])


@router.get("/{task_id}/stream")
async def stream_task(task_id: str):
    """以 SSE 方式实时推送任务执行进度。

    - 任务必须已存在（先调用 POST /tasks 创建）
    - 任务处于 queued/running 时订阅，事件由后台 worker 推送
    - 任务已 completed/waiting_human/error 时直接返回当前状态
    - 客户端断开连接后自动停止推送
    """
    task = await repo_task.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    return EventSourceResponse(
        _event_generator(task_id, task),
        media_type="text/event-stream",
    )


async def _event_generator(
    task_id: str, task: dict[str, Any]
) -> AsyncGenerator[dict, None]:
    status = task.get("status", "")

    # 已终态：直接推送当前状态后关闭
    if status in {"completed", "waiting_human", "error"}:
        yield _sse({"type": "done", "status": status})
        return

    # 注册进度队列（worker 会往里写事件）
    # 注意：必须在 worker 执行前注册，否则 worker 完成后队列已被清理
    # 若订阅时任务已变为终态（worker 刚好在这一刻完成），重新检查一次
    progress_q = get_or_create_progress_queue(task_id)

    # 二次检查：防止在 get_or_create 和 worker 完成之间的竞态
    from app.storage import repo_task as _repo
    fresh_task = await _repo.get_task(task_id)
    fresh_status = (fresh_task or {}).get("status", "")
    if fresh_status in {"completed", "waiting_human", "error"}:
        yield _sse({"type": "done", "status": fresh_status})
        return

    try:
        while True:
            try:
                event = await asyncio.wait_for(progress_q.get(), timeout=5.0)
            except asyncio.TimeoutError:
                # 短心跳：前端可借此轮询 current_node，长 LLM 调用时进度条不会假死在「排队中」
                yield _sse({"type": "heartbeat"})
                continue

            if event is _PROGRESS_SENTINEL:
                break

            yield _sse(event)

            # done/error 事件后关闭
            if isinstance(event, dict) and event.get("type") in {"done", "error"}:
                break

    except asyncio.CancelledError:
        logger.info(f"SSE client disconnected for task {task_id}")


def _sse(data: Any) -> dict:
    return {"data": json.dumps(data, ensure_ascii=False)}
