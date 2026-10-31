"""FastAPI task routes with async queue and checkpoint-aware resume."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from pydantic import BaseModel, Field

from app.core.logger import logger
from app.core.observability import extract_metrics, merge_task_metric
from app.core.task_queue import enqueue_resume, enqueue_start, make_config
from app.graph.builder import get_graph
from app.graph.checkpoints import has_checkpoint
from app.storage import repo_task
from app.tools.export_tool import export_deliverable

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _ensure_owner(task: dict | None, user_id: int) -> dict:
    if task is None or task.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


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
async def list_tasks_endpoint(
    limit: int = 50,
    offset: int = 0,
    current_user: dict = Depends(get_current_user),
):
    return await repo_task.list_tasks(limit=limit, offset=offset, user_id=current_user["id"])


@router.post("", response_model=CreateTaskResponse)
async def create_task(req: CreateTaskRequest, current_user: dict = Depends(get_current_user)):
    """Create a task quickly and run the graph in the background."""
    started = time.perf_counter()
    task_id = await repo_task.create_task(req.user_input, user_id=current_user["id"])
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


@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str, current_user: dict = Depends(get_current_user)):
    task = _ensure_owner(await repo_task.get_task(task_id), current_user["id"])

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
async def submit_feedback(task_id: str, req: FeedbackRequest, current_user: dict = Depends(get_current_user)):
    task = _ensure_owner(await repo_task.get_task(task_id), current_user["id"])
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


@router.get("/{task_id}/result")
async def get_task_result(task_id: str, current_user: dict = Depends(get_current_user)):
    task = _ensure_owner(await repo_task.get_task(task_id), current_user["id"])

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
