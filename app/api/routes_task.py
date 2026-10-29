"""FastAPI task routes with async queue and checkpoint-aware resume."""

from __future__ import annotations

import shutil
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.core.cancellation import request_cancel
from app.core.config import get_settings
from app.core.logger import logger
from app.core.observability import extract_metrics, merge_task_metric
from app.core.task_queue import enqueue_resume, enqueue_start, make_config
from app.graph.builder import get_graph
from app.graph.checkpoints import get_checkpoint_path, get_checkpointer, has_checkpoint
from app.storage import repo_task
from app.tools.export_tool import export_bundle_zip, export_deliverable, export_docx
from app.tools.traceability import build_traceability

router = APIRouter(prefix="/tasks", tags=["tasks"])


class CreateTaskRequest(BaseModel):
    user_input: str = Field(..., min_length=1, description="User requirement")


class CreateTaskResponse(BaseModel):
    task_id: str
    status: str
    message: str
    task_submit_latency_ms: float | None = None


class FeedbackRequest(BaseModel):
    feedback: str = Field("", description="Human feedback")
    approved: bool | None = Field(None, description="Approval decision")


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    current_node: str
    reflow_count: int
    interrupt_info: dict | list | str | None = None
    clarified_requirement: dict | None = None
    user_input: str = ""
    review_result: dict | None = None
    prd_doc: dict | None = None
    technical_design: dict | None = None
    metrics: dict | None = None
    error_message: str | None = None


@router.get("")
async def list_tasks_endpoint(limit: int = 50, offset: int = 0):
    return await repo_task.list_tasks(limit=limit, offset=offset)


@router.post("", response_model=CreateTaskResponse)
async def create_task(req: CreateTaskRequest):
    """Create a task quickly and run the graph in the background."""
    started = time.perf_counter()
    task_id = await repo_task.create_task(req.user_input)
    initial_state = {
        "user_input": req.user_input,
        "task_id": task_id,
        "max_reflow_count": 2,
        "metadata": {
            "task_id": task_id,
            "metrics": {
                "api_timeout": False,
                "background_task_success": None,
            },
        },
    }
    initial_state = merge_task_metric(
        initial_state,
        api_timeout=False,
    )
    await repo_task.update_task(
        task_id,
        status="queued",
        current_node="queued",
        state_snapshot=initial_state,
    )
    await enqueue_start(task_id, initial_state)
    submit_latency_ms = round((time.perf_counter() - started) * 1000, 3)
    initial_state = merge_task_metric(
        initial_state,
        task_submit_latency_ms=submit_latency_ms,
    )
    await repo_task.update_task(task_id, state_snapshot=initial_state)
    logger.info("Task queued", extra={"task_id": task_id, "latency_ms": submit_latency_ms})
    return CreateTaskResponse(
        task_id=task_id,
        status="queued",
        message="Task created and queued for background execution.",
        task_submit_latency_ms=submit_latency_ms,
    )


@router.get("/stats")
async def get_task_stats():
    """按状态聚合任务数，避免列表页截断导致统计失真。"""
    counts = await repo_task.count_tasks_by_status()
    return {
        "total": sum(counts.values()),
        "by_status": counts,
        "completed": counts.get("completed", 0),
        "running": counts.get("running", 0),
        "queued": counts.get("queued", 0),
        "waiting_human": counts.get("waiting_human", 0),
        "error": counts.get("error", 0),
    }


@router.get("/page")
async def list_tasks_page(
    limit: int = 20,
    offset: int = 0,
    status: str | None = None,
    q: str | None = None,
):
    """服务端分页列表，支持状态过滤与关键词搜索。"""
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    return await repo_task.list_tasks_page(limit=limit, offset=offset, status=status, q=q)


@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    task = await repo_task.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    state_snapshot = task.get("state_snapshot") or {}
    interrupt_info = state_snapshot.get("interrupt_info")
    checkpoint_seen = False
    try:
        graph_state = get_graph().get_state(make_config(task_id))
        checkpoint_seen = _has_materialized_graph_state(graph_state) or has_checkpoint(task_id)
        values = graph_state.values if hasattr(graph_state, "values") else {}
        if isinstance(values, dict) and values.get("__interrupt__"):
            interrupt_info = values["__interrupt__"]
    except Exception as exc:
        logger.warning(f"Could not read graph checkpoint for task {task_id}: {exc}")

    if task["status"] in {"waiting_human", "running", "queued"}:
        state_snapshot = merge_task_metric(
            state_snapshot,
            checkpoint_recovered=checkpoint_seen,
            state_persistence_coverage=1.0 if state_snapshot else 0.0,
        )
        await repo_task.update_task(task_id, state_snapshot=state_snapshot)

    return TaskStatusResponse(
        task_id=task["task_id"],
        status=task["status"],
        current_node=task["current_node"],
        reflow_count=task["reflow_count"],
        interrupt_info=interrupt_info,
        clarified_requirement=state_snapshot.get("clarified_requirement"),
        user_input=task.get("user_input", ""),
        review_result=state_snapshot.get("review_result"),
        prd_doc=state_snapshot.get("prd_doc"),
        technical_design=state_snapshot.get("technical_design"),
        metrics=extract_metrics(state_snapshot),
        error_message=_error_message(state_snapshot),
    )


def _error_message(state_snapshot: dict) -> str | None:
    message = state_snapshot.get("error_message")
    if not isinstance(message, str):
        return None
    message = message.strip()
    return message or None


def _has_materialized_graph_state(graph_state: Any) -> bool:
    if graph_state is None:
        return False
    values = getattr(graph_state, "values", None)
    tasks = getattr(graph_state, "tasks", None)
    next_nodes = getattr(graph_state, "next", None)
    created_at = getattr(graph_state, "created_at", None)
    return bool(created_at or values or tasks or next_nodes)


@router.post("/{task_id}/feedback")
async def submit_feedback(task_id: str, req: FeedbackRequest):
    task = await repo_task.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] != "waiting_human":
        raise HTTPException(status_code=400, detail="Task is not waiting for human feedback")
    if not has_checkpoint(task_id):
        raise HTTPException(status_code=409, detail="Graph checkpoint is missing for this task")

    await repo_task.save_feedback(
        task_id,
        content=req.feedback,
        node=task["current_node"],
        feedback_type="approval" if req.approved is not None else "clarification",
    )
    resume_data: Any = (
        {"approved": req.approved, "feedback": req.feedback}
        if req.approved is not None
        else req.feedback
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
    await enqueue_resume(task_id, resume_data)
    return {
        "task_id": task_id,
        "status": "queued",
        "current_node": "queued",
        "message": "Feedback accepted and queued for background resume.",
    }


@router.post("/{task_id}/reoptimize")
async def reoptimize_task(task_id: str):
    """基于已有 PRD 重新执行工程与评审，生成一个新任务。"""
    original = await repo_task.get_task(task_id)
    if original is None:
        raise HTTPException(status_code=404, detail="Task not found")

    snapshot = original.get("state_snapshot") or {}
    prd_doc = snapshot.get("prd_doc") or {}
    review = snapshot.get("review_result") or {}

    if not prd_doc:
        raise HTTPException(status_code=400, detail="任务尚未产出 PRD，无法二次优化")
    if review.get("passed"):
        raise HTTPException(status_code=400, detail="任务已通过评审，无需二次优化")

    new_task_id = await repo_task.create_task(original["user_input"])
    design = snapshot.get("technical_design") or {}
    mode = "repair" if design else "rebuild"

    initial_state = {
        "user_input": original["user_input"],
        "task_id": new_task_id,
        "max_reflow_count": get_settings().max_reflow_count,
        "reflow_count": 0,
        "repair_count": 0,
        "prd_doc": prd_doc,
        "clarified_requirement": snapshot.get("clarified_requirement") or {},
        "metadata": {
            "reoptimize": True,
            "reoptimize_mode": mode,
            "source_task_id": task_id,
            "task_id": new_task_id,
        },
    }
    if mode == "repair":
        initial_state["technical_design"] = design

    await repo_task.update_task(new_task_id, state_snapshot=initial_state)
    await enqueue_start(new_task_id, initial_state)
    logger.info(f"Reoptimize task {new_task_id} created from {task_id} (mode={mode})")
    return {"task_id": new_task_id, "source_task_id": task_id, "mode": mode, "status": "queued"}


@router.post("/{task_id}/retry")
async def retry_task(task_id: str):
    """从失败节点继续执行，不新建任务。"""
    task = await repo_task.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] != "error":
        raise HTTPException(status_code=400, detail="只有执行失败的任务可以重试")

    snapshot = dict(task.get("state_snapshot") or {})
    metadata = dict(snapshot.get("metadata") or {})
    failed_node = str(metadata.get("failed_node") or task.get("current_node") or "")
    metadata.update({"retry": True, "failed_node": failed_node})
    metadata.pop("error_kind", None)
    metadata.pop("error_action", None)
    snapshot["metadata"] = metadata
    snapshot["error_message"] = ""

    await repo_task.update_task(task_id, status="queued", state_snapshot=snapshot)
    await enqueue_start(task_id, snapshot)
    logger.info(f"Task {task_id} queued for retry from {failed_node or 'start'}")
    return {"task_id": task_id, "status": "queued", "resume_from": failed_node}


@router.post("/cleanup")
async def cleanup_tasks(days: int = 30, dry_run: bool = True, limit: int = 200):
    """清理 N 天前的终态任务（记录 + checkpoint + 导出目录）。

    默认 dry_run，只返回候选数量与样例，避免误删。
    """
    if days < 1:
        raise HTTPException(status_code=400, detail="days 至少为 1")

    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    task_ids = await repo_task.list_expired_tasks(
        cutoff, ["completed", "error", "cancelled"], limit
    )
    if dry_run:
        return {
            "dry_run": True,
            "days": days,
            "candidates": len(task_ids),
            "sample": task_ids[:10],
        }

    removed = await repo_task.delete_tasks(task_ids)
    saver = get_checkpointer()
    output_dir = get_settings().output_dir
    for task_id in task_ids:
        try:
            if hasattr(saver, "delete_thread"):
                saver.delete_thread(task_id)
        except Exception as exc:
            logger.warning(f"删除 checkpoint 失败：{exc}", extra={"task_id": task_id})
        shutil.rmtree(output_dir / task_id, ignore_errors=True)
    # Deleting rows does not shrink the SQLite file; reclaim the space.
    try:
        with sqlite3.connect(get_checkpoint_path()) as conn:
            conn.execute("VACUUM")
    except Exception as exc:
        logger.warning(f"checkpoint VACUUM 失败：{exc}")
    logger.info("Task cleanup finished", extra={"deleted": removed, "days": days})
    return {"dry_run": False, "days": days, "deleted": removed}


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: str):
    """请求取消任务：排队中直接终止，执行中在当前节点结束后终止。"""
    task = await repo_task.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    status = task["status"]
    if status not in ("queued", "running", "waiting_human", "cancelling"):
        raise HTTPException(status_code=400, detail="当前状态不可取消")

    if status in ("queued", "waiting_human"):
        request_cancel(task_id)
        await repo_task.update_task(task_id, status="cancelled")
        return {"task_id": task_id, "status": "cancelled"}

    request_cancel(task_id)
    await repo_task.update_task(task_id, status="cancelling")
    return {"task_id": task_id, "status": "cancelling"}


@router.delete("/{task_id}")
async def delete_task(task_id: str):
    """删除任务记录、checkpoint 与导出目录。"""
    task = await repo_task.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] in ("queued", "running", "cancelling"):
        raise HTTPException(status_code=400, detail="请先取消任务再删除")

    await repo_task.delete_task(task_id)
    try:
        saver = get_checkpointer()
        if hasattr(saver, "delete_thread"):
            saver.delete_thread(task_id)
    except Exception as exc:
        logger.warning(f"删除 checkpoint 失败：{exc}", extra={"task_id": task_id})
    shutil.rmtree(get_settings().output_dir / task_id, ignore_errors=True)
    logger.info("Task deleted", extra={"task_id": task_id})
    return {"deleted": task_id}


@router.get("/{task_id}/export/zip")
async def export_task_zip(task_id: str):
    task = await repo_task.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] != "completed" or not task.get("result"):
        raise HTTPException(status_code=400, detail="只有已完成任务可以导出")

    export_deliverable(task["result"], task_id)
    path = export_bundle_zip(task_id)
    return FileResponse(
        path,
        filename=f"{task_id}_deliverables.zip",
        media_type="application/zip",
    )


@router.get("/{task_id}/export/docx")
async def export_task_docx(task_id: str):
    task = await repo_task.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] != "completed" or not task.get("result"):
        raise HTTPException(status_code=400, detail="只有已完成任务可以导出")

    path = export_docx(task["result"], task_id)
    return FileResponse(
        path,
        filename=f"{task_id}_delivery.docx",
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
    )


@router.get("/{task_id}/traceability")
async def get_task_traceability(task_id: str):
    """Feature-to-artifact matrix for the task detail page."""
    task = await repo_task.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    snapshot = task.get("state_snapshot") or {}
    prd_doc = snapshot.get("prd_doc") or {}
    design = snapshot.get("technical_design") or {}
    if not prd_doc or not design:
        raise HTTPException(
            status_code=400,
            detail="Task has no PRD or technical design yet",
        )

    return {"task_id": task_id, **build_traceability(prd_doc, design)}


@router.get("/{task_id}/result")
async def get_task_result(task_id: str):
    task = await repo_task.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    result_data = task.get("result", {})
    if not result_data or task["status"] != "completed":
        raise HTTPException(status_code=400, detail="Task is not completed")

    try:
        exported = export_deliverable(result_data, task_id)
    except Exception as exc:
        logger.error(f"Export failed: {exc}", extra={"task_id": task_id})
        exported = {}

    return {
        "task_id": task_id,
        "deliverable": result_data,
        "exported_files": exported,
    }
