"""Usage statistics endpoint.

Sums come from ``llm_usage`` — one row per model call — so failed tasks and
image extraction are counted the same way as successful agent steps.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query

from app.storage import repo_usage

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/usage")
async def get_usage_stats(days: int = Query(30, ge=1, le=365)):
    # 成本仍按行记录（成本上限需要），但界面只展示 token 维度，不再下发单价表。
    return await asyncio.to_thread(repo_usage.aggregate, days)


@router.post("/usage/backfill")
async def backfill_usage():
    """把历史任务快照补进用量表，可重复执行。"""
    rows = await asyncio.to_thread(repo_usage.backfill_from_tasks)
    return {"rows": rows}


@router.post("/usage/recost")
async def recost_usage():
    """按当前单价重算用量表里的成本。"""
    return await asyncio.to_thread(repo_usage.recost_all)
