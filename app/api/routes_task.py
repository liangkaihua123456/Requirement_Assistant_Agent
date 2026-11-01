"""FastAPI task routes with async queue and checkpoint-aware resume."""

from __future__ import annotations

import shutil
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.api.deps import get_current_user
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


def _ensure_owner(task: dict | None, user_id: int) -> dict:
    if task is None or task.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


class CreateTaskRequest(BaseModel):
    user_input: str = Field(..., min_length=1, description="User requirement")
    project: str | None = Field(None, max_length=64, description="所属项目，长期记忆按项目隔离，默认 default")


class ReoptimizeRequest(BaseModel):
    reoptimize_requirement: str | None = Field(
        None, max_length=4000, description="本次要调整/新增的需求描述；留空则沿用既有行为直接重跑工程与评审"
    )
    keep_baseline: bool = Field(True, description="True=原需求与变更描述共同生效；False=以新描述为准（原文仅作来源记录）")


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
    source_task_id: str | None = None
    project_history: str | None = None


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
    project_id = (req.project or "default").strip() or "default"
    task_id = await repo_task.create_task(req.user_input, user_id=current_user["id"], project_id=project_id)
    initial_state = {
        "user_input": req.user_input,
        "task_id": task_id,
        "project_id": project_id,
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
async def get_task_stats(current_user: dict = Depends(get_current_user)):
    """按状态聚合任务数，避免列表页截断导致统计失真。"""
    counts = await repo_task.count_tasks_by_status(user_id=current_user["id"])
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
    current_user: dict = Depends(get_current_user),
):
    """服务端分页列表，支持状态过滤与关键词搜索。"""
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    return await repo_task.list_tasks_page(limit=limit, offset=offset, status=status, q=q, user_id=current_user["id"])


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
        source_task_id=(state_snapshot.get("metadata") or {}).get("source_task_id"),
        project_history=(state_snapshot.get("metadata") or {}).get("project_history"),
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


async def _build_iteration_history(project_id: str, source_task_id: str, max_chars: int = 1600) -> str:
    """组装项目回溯卡：迭代链（最多回溯源 3 级）+ 各轮澄清/审批问答 + 历史案例。

    用途：迭代任务的 agent 与用户都能看到"之前做过什么、问过什么"，
    回答类变更描述（如"我之前弄过什么东西"）不再石沉大海。
    """
    lines: list[str] = []
    chain: list[str] = []
    cur: str | None = source_task_id
    for _ in range(4):
        if not cur:
            break
        t = await repo_task.get_task(cur)
        if t is None:
            break
        chain.append(cur)
        cur = ((t.get("state_snapshot") or {}).get("metadata") or {}).get("source_task_id")

    for tid in chain:
        t = await repo_task.get_task(tid)
        if t is None:
            continue
        snap = t.get("state_snapshot") or {}
        meta = snap.get("metadata") or {}
        ui = t.get("user_input") or ""
        brief_part = ""
        for marker in ("【本次变更】", "【本次需求变更"):
            if marker in ui:
                brief_part = ui.split(marker, 1)[1].split("【项目历史", 1)[0][:100].strip()
                break
        rv = snap.get("review_result") or {}
        verdict = "通过" if rv.get("passed") else ("未通过" if rv else "无评审")
        lines.append(f"· 任务 {tid}｜状态 {t.get('status')}｜评审 {verdict}({rv.get('overall_score', '-')})"
                     + (f"｜变更: {brief_part}" if brief_part else ""))
        for q in list((snap.get("clarified_requirement") or {}).get("open_questions") or [])[:3]:
            qs = str(q).strip().replace("\n", " ")[:90]
            if qs:
                lines.append(f"    [问] {qs}")
        for f in await repo_task.list_feedbacks(tid, limit=4):
            q = (f.get("content") or "").strip().replace("\n", " ")[:110]
            if q:
                lines.append(f"    [{f.get('feedback_type') or f.get('node') or 'clarify'}] {q}")

    from app.storage.repo_project_memory import list_memory_archive
    for r in list_memory_archive(project_id=project_id, memory_type="case", limit=5)[:5]:
        if r.get("task_id") in chain:
            continue
        lines.append(f"· 项目历史案例：{r.get('product_name') or r.get('memory_key')}（评分 {r.get('overall_score')}）")

    text = "\n".join(lines)
    return text[:max_chars] if text else ""


@router.post("/{task_id}/reoptimize")
async def reoptimize_task(
    task_id: str,
    req: ReoptimizeRequest | None = None,
    current_user: dict = Depends(get_current_user),
):
    """二次优化：默认基于已有 PRD 重跑工程与评审（repair/rebuild）。

    携带 reoptimize_requirement 时视为"重新讲需求"：强制 rebuild，从规划起
    按新描述重做 PRD、方案设计与工程实现；旧任务及其产物保持不变，仅作引用。
    """
    original = _ensure_owner(await repo_task.get_task(task_id), current_user["id"])
    if original is None:
        raise HTTPException(status_code=404, detail="Task not found")

    snapshot = original.get("state_snapshot") or {}
    prd_doc = snapshot.get("prd_doc") or {}
    review = snapshot.get("review_result") or {}
    brief = ((req.reoptimize_requirement if req else None) or "").strip()
    project_id = original.get("project_id") or "default"

    if not prd_doc:
        raise HTTPException(status_code=400, detail="任务尚未产出 PRD，无法二次优化")
    if review.get("passed") and not brief:
        raise HTTPException(
            status_code=400,
            detail="任务已通过评审，无需二次优化；如有需求变更请填写变更描述后再迭代",
        )

    design = snapshot.get("technical_design") or {}
    if brief:
        mode = "rebuild"
        keep_baseline = bool(req.keep_baseline)
        user_input = (
            f"{original['user_input']}\n\n【本次变更】\n{brief}"
            if keep_baseline
            else f"【本次需求变更，以此为准（迭代自任务 {task_id}）】\n{brief}"
        )
    else:
        mode = "repair" if design else "rebuild"
        user_input = original["user_input"]

    history = await _build_iteration_history(project_id, task_id) if brief else ""
    if history:
        # 让迭代任务"看得见自己之前做过/问过什么"：历史卡进 user_input（agent 可读）
        # 与 metadata（前端可直接展示为产物）
        user_input += f"\n\n【项目历史 · 回溯背景，非新需求】\n{history}"

    new_task_id = await repo_task.create_task(
        user_input, user_id=current_user["id"], project_id=project_id
    )

    initial_state = {
        "user_input": user_input,
        "task_id": new_task_id,
        "project_id": project_id,
        "max_reflow_count": get_settings().max_reflow_count,
        "reflow_count": 0,
        "repair_count": 0,
        "metadata": {
            "reoptimize": True,
            "reoptimize_mode": mode,
            "source_task_id": task_id,
            "task_id": new_task_id,
            "has_requirement_brief": bool(brief),
            "project_history": history or None,
        },
    }
    if brief:
        # 带需求变更：不投喂旧 PRD/澄清结论，让 planner→solution→engineer 全链路
        # 按新描述重做；旧产物通过 source_task_id 可查
        initial_state["metadata"]["reference_prd"] = {
            "product_name": prd_doc.get("product_name") or "",
            "domain": prd_doc.get("domain") or "",
        }
    else:
        initial_state["prd_doc"] = prd_doc
        initial_state["clarified_requirement"] = snapshot.get("clarified_requirement") or {}
    if mode == "repair":
        initial_state["technical_design"] = design

    await repo_task.update_task(new_task_id, state_snapshot=initial_state)
    await enqueue_start(new_task_id, initial_state)
    logger.info(
        f"Reoptimize task {new_task_id} created from {task_id} "
        f"(mode={mode}, brief={'yes' if brief else 'no'})"
    )
    return {
        "task_id": new_task_id,
        "source_task_id": task_id,
        "mode": mode,
        "brief_applied": bool(brief),
        "status": "queued",
    }


@router.post("/{task_id}/retry")
async def retry_task(task_id: str, current_user: dict = Depends(get_current_user)):
    """从失败节点继续执行，不新建任务。"""
    task = _ensure_owner(await repo_task.get_task(task_id), current_user["id"])
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
async def cleanup_tasks(days: int = 30, dry_run: bool = True, limit: int = 200, current_user: dict = Depends(get_current_user)):
    """清理 N 天前的终态任务（记录 + checkpoint + 导出目录）。

    默认 dry_run，只返回候选数量与样例，避免误删。
    """
    if days < 1:
        raise HTTPException(status_code=400, detail="days 至少为 1")

    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    task_ids = await repo_task.list_expired_tasks(
        cutoff, ["completed", "error", "cancelled"], limit, user_id=current_user["id"]
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
async def cancel_task(task_id: str, current_user: dict = Depends(get_current_user)):
    """请求取消任务：排队中直接终止，执行中在当前节点结束后终止。"""
    task = _ensure_owner(await repo_task.get_task(task_id), current_user["id"])
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
async def delete_task(task_id: str, current_user: dict = Depends(get_current_user)):
    """删除任务记录、checkpoint 与导出目录。"""
    task = _ensure_owner(await repo_task.get_task(task_id), current_user["id"])
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
async def export_task_zip(task_id: str, current_user: dict = Depends(get_current_user)):
    task = _ensure_owner(await repo_task.get_task(task_id), current_user["id"])
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
async def export_task_docx(task_id: str, current_user: dict = Depends(get_current_user)):
    task = _ensure_owner(await repo_task.get_task(task_id), current_user["id"])
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
async def get_task_traceability(task_id: str, current_user: dict = Depends(get_current_user)):
    """Feature-to-artifact matrix for the task detail page."""
    task = _ensure_owner(await repo_task.get_task(task_id), current_user["id"])
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
