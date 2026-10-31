"""Aggregate token usage for the statistics page.

Input is the per-task usage snapshots stored in ``metadata.metrics.token_usage``.
Output covers the overview cards, the daily trend series, and the model/role
breakdowns, all derived from the same records so totals never disagree.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.usage import UsageRecord, estimate_cost

ROLE_LABELS = {
    "planner": "需求分析",
    "solution": "方案设计",
    "engineer": "工程实现",
    "reviewer": "智能评审",
    "repairer": "自动修复",
    "evaluator": "方案评估",
    "dialogue": "对话",
    "normalizer": "输入规范化",
    "default": "默认",
}

_TOKEN_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens", "calls")


def build_usage_stats(records: list[dict[str, Any]], days: int = 30) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "requests": 0,
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cached_tokens": 0,
        "cost_cny": 0.0,
        "cache_hit_rate": 0.0,
        "priced": True,
    }
    daily: dict[str, dict[str, Any]] = {}
    by_model: dict[str, dict[str, Any]] = {}
    by_role: dict[str, dict[str, Any]] = {}
    requests: list[dict[str, Any]] = []

    for record in records:
        usage = record.get("usage") or {}
        total = usage.get("total") or {}
        prompt_tokens = int(total.get("prompt_tokens") or 0)
        completion_tokens = int(total.get("completion_tokens") or 0)
        total_tokens = int(total.get("total_tokens") or 0)
        cached_tokens = int(total.get("cached_tokens") or 0)
        cost = float(usage.get("cost_cny") or 0)
        calls = int(total.get("calls") or 0)

        summary["requests"] += 1
        summary["calls"] += calls
        summary["prompt_tokens"] += prompt_tokens
        summary["completion_tokens"] += completion_tokens
        summary["total_tokens"] += total_tokens
        summary["cached_tokens"] += cached_tokens
        summary["cost_cny"] += cost
        summary["priced"] = bool(summary["priced"]) and bool(usage.get("priced", True))

        day = str(record.get("created_at") or "")[:10]
        bucket = daily.setdefault(day, {"input": 0, "output": 0, "cached": 0, "cost": 0.0, "requests": 0})
        bucket["input"] += prompt_tokens
        bucket["output"] += completion_tokens
        bucket["cached"] += cached_tokens
        bucket["cost"] += cost
        bucket["requests"] += 1

        for model, item in (usage.get("by_model") or {}).items():
            target = _accumulate(
                by_model,
                model,
                item,
                fallback_cost=_model_cost(model, item, _parse_moment(record.get("created_at"))),
            )
            target["label"] = model
        for role, item in (usage.get("by_role") or {}).items():
            target = _accumulate(by_role, role, item, fallback_cost=_shared_cost(usage, item))
            target["label"] = ROLE_LABELS.get(role, role)

        requests.append(
            {
                "task_id": record.get("task_id", ""),
                "created_at": record.get("created_at", ""),
                "user_input": record.get("user_input", ""),
                "status": record.get("status", ""),
                "models": ", ".join((usage.get("by_model") or {}).keys()),
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "cached_tokens": cached_tokens,
                "cost_cny": round(cost, 6),
                "duration_seconds": record.get("duration_seconds"),
            }
        )

    summary["cache_hit_rate"] = (
        round(summary["cached_tokens"] / summary["prompt_tokens"], 4)
        if summary["prompt_tokens"]
        else 0.0
    )
    summary["cost_cny"] = round(summary["cost_cny"], 6)

    return {
        "days": days,
        "summary": summary,
        "series": _fill_series(daily, days),
        "by_model": sorted(by_model.values(), key=lambda item: -item["total_tokens"]),
        "by_role": sorted(by_role.values(), key=lambda item: -item["total_tokens"]),
        "requests": requests[:100],
    }


def _parse_moment(text: Any) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text).replace(" ", "T"))
    except ValueError:
        return None


def _model_cost(model: str, item: dict[str, Any], at: datetime | None = None) -> float:
    """Recompute a model bucket's cost from its tokens when the snapshot lacks it."""
    if float(item.get("cost_cny") or 0) > 0:
        return 0.0
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
    return amount if known else 0.0


def _shared_cost(usage: dict[str, Any], item: dict[str, Any]) -> float:
    """Allocate a task's cost to one bucket when the bucket has no cost field.

    Snapshots written before per-bucket cost tracking only carry the task total,
    so the share is derived from token volume. Buckets that already record a
    cost keep their own value.
    """
    if float(item.get("cost_cny") or 0) > 0:
        return 0.0
    buckets = list((usage.get("by_model") or {}).values())
    total_tokens = sum(int((bucket or {}).get("total_tokens") or 0) for bucket in buckets) or 1
    share = int(item.get("total_tokens") or 0) / total_tokens
    return float(usage.get("cost_cny") or 0) * share


def _accumulate(
    bucket: dict[str, dict[str, Any]],
    key: str,
    item: dict[str, Any],
    fallback_cost: float = 0.0,
) -> dict[str, Any]:
    target = bucket.setdefault(
        key,
        {
            "key": key,
            "label": key,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cached_tokens": 0,
            "calls": 0,
            "cost_cny": 0.0,
        },
    )
    for field in _TOKEN_FIELDS:
        target[field] += int(item.get(field) or 0)
    cost = float(item.get("cost_cny") or 0)
    if cost == 0 and fallback_cost:
        cost = fallback_cost
    target["cost_cny"] = round(target["cost_cny"] + cost, 6)
    return target


def _fill_series(daily: dict[str, dict[str, Any]], days: int) -> list[dict[str, Any]]:
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=max(days - 1, 0))
    series = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        key = day.isoformat()
        item = daily.get(key) or {}
        series.append(
            {
                "date": key,
                "input": int(item.get("input") or 0),
                "output": int(item.get("output") or 0),
                "cached": int(item.get("cached") or 0),
                "cost": round(float(item.get("cost") or 0), 6),
                "requests": int(item.get("requests") or 0),
            }
        )
    return series
