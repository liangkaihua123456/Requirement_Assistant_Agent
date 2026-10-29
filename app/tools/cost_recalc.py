"""Recompute historical task costs with the current price table.

Token counts never change; only the monetary value is recalculated. Model costs
come from the current price table, role costs are allocated by token share so
both dimensions still sum to the task total.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.logger import logger
from app.core.usage import UsageRecord, estimate_cost
from app.storage import repo_task


def _parse_moment(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace(" ", "T"))
    except ValueError:
        return None


def recalculate_usage(usage: dict[str, Any], at=None) -> dict[str, Any] | None:
    by_model = usage.get("by_model") or {}
    if not by_model:
        return None

    total_cost = 0.0
    priced = True
    token_total = 0
    new_by_model: dict[str, dict] = {}

    for model, item in by_model.items():
        item = item or {}
        record = UsageRecord(
            role="",
            model=model,
            prompt_tokens=int(item.get("prompt_tokens") or 0),
            completion_tokens=int(item.get("completion_tokens") or 0),
            total_tokens=int(item.get("total_tokens") or 0),
            cached_tokens=int(item.get("cached_tokens") or 0),
            at=at,
        )
        amount, known = estimate_cost(record)
        priced = priced and known
        total_cost += amount
        token_total += record.total_tokens
        new_by_model[model] = {**item, "cost_cny": round(amount, 6)}

    new_by_role: dict[str, dict] = {}
    for role, item in (usage.get("by_role") or {}).items():
        item = item or {}
        share = int(item.get("total_tokens") or 0) / token_total if token_total else 0
        new_by_role[role] = {**item, "cost_cny": round(total_cost * share, 6)}

    return {
        "total": dict(usage.get("total") or {}),
        "by_role": new_by_role,
        "by_model": new_by_model,
        "cost_cny": round(total_cost, 6),
        "priced": priced,
    }


async def recalc_all_costs() -> dict[str, Any]:
    tasks = await repo_task.list_all_snapshots()
    updated = 0
    skipped = 0
    old_total = 0.0
    new_total = 0.0

    for task in tasks:
        snapshot = task["state_snapshot"]
        metadata = snapshot.get("metadata") or {}
        metrics = metadata.get("metrics") or {}
        usage = metrics.get("token_usage")
        at = _parse_moment(task.get("created_at"))

        if not isinstance(usage, dict) or not usage:
            skipped += 1
            continue

        recomputed = recalculate_usage(usage, at=at)
        if recomputed is None:
            skipped += 1
            continue

        old_total += float(usage.get("cost_cny") or 0)
        new_total += float(recomputed.get("cost_cny") or 0)

        usage["cost_cny"] = recomputed["cost_cny"]
        usage["priced"] = recomputed["priced"]
        usage["by_model"] = recomputed["by_model"]
        usage["by_role"] = recomputed["by_role"]
        metrics["token_usage"] = usage

        per_node = metrics.get("token_usage_by_node")
        if isinstance(per_node, dict):
            for node, node_usage in list(per_node.items()):
                if not isinstance(node_usage, dict) or not node_usage:
                    continue
                node_recomputed = recalculate_usage(node_usage)
                if node_recomputed is None:
                    continue
                node_usage["cost_cny"] = node_recomputed["cost_cny"]
                node_usage["by_model"] = node_recomputed["by_model"]
                node_usage["by_role"] = node_recomputed["by_role"]
                node_usage["priced"] = node_recomputed["priced"]
                per_node[node] = node_usage
            metrics["token_usage_by_node"] = per_node

        snapshot.setdefault("metadata", {})["metrics"] = metrics
        await repo_task.update_task(task["task_id"], state_snapshot=snapshot)
        updated += 1

    # 统计页以 llm_usage 为准，快照重算后必须同步重算用量表，否则两个数字会打架。
    usage_rows = 0
    try:
        from app.storage import repo_usage

        usage_rows = int(repo_usage.recost_all().get("updated") or 0)
    except Exception as exc:
        logger.warning(f"Usage table recost failed: {str(exc)[:160]}")

    logger.info(
        f"Cost recalculation finished: updated={updated} skipped={skipped} usage_rows={usage_rows}"
    )
    return {
        "tasks": len(tasks),
        "updated": updated,
        "skipped": skipped,
        "usage_rows": usage_rows,
        "old_cost_cny": round(old_total, 6),
        "new_cost_cny": round(new_total, 6),
    }
