"""用量表读写与聚合。

统计只认 ``llm_usage`` 这一张表：一次调用一行，失败节点的调用同样在表里，
所以页面上的总数能直接和供应商账单对齐。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import get_settings
from app.core.logger import logger
from app.core.usage import UsageRecord, estimate_cost, is_peak_hour
from app.storage.usage_writer import delete_by_source, insert_rows

ROLE_LABELS = {
    "planner": "需求分析",
    "solution": "方案设计",
    "engineer": "工程实现",
    "reviewer": "智能评审",
    "repairer": "自动修复",
    "evaluator": "方案评估",
    "dialogue": "对话",
    "normalizer": "输入规范化",
    "vision": "图片识别",
    "default": "默认",
    "unknown": "历史数据",
}


def _db_path() -> str:
    url = get_settings().database_url
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if url.startswith(prefix):
            return url[len(prefix) :]
    return url


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def _parse_dt(text: str | None) -> datetime | None:
    """数据库里存的是 UTC naive 时间，按 UTC 解释。"""
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text).replace(" ", "T"))
    except ValueError:
        return None


def _cutoff(days: int) -> str:
    start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=max(days - 1, 0))
    return start.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")


def aggregate(days: int = 30) -> dict[str, Any]:
    cutoff = _cutoff(days)
    conn = _connect()
    try:
        summary_row = conn.execute(
            """
            SELECT COUNT(*) AS calls,
                   COUNT(DISTINCT NULLIF(task_id, '')) AS requests,
                   COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                   COALESCE(SUM(total_tokens), 0) AS total_tokens,
                   COALESCE(SUM(cached_tokens), 0) AS cached_tokens,
                   COALESCE(SUM(cost_cny), 0) AS cost_cny,
                   COALESCE(SUM(CASE WHEN priced = 1 THEN 1 ELSE 0 END), 0) AS priced_calls,
                   COALESCE(SUM(CASE WHEN peak = 1 THEN 1 ELSE 0 END), 0) AS peak_calls
            FROM llm_usage WHERE created_at >= ?
            """,
            (cutoff,),
        ).fetchone()

        daily = conn.execute(
            """
            SELECT substr(created_at, 1, 10) AS day,
                   COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                   COALESCE(SUM(cached_tokens), 0) AS cached_tokens,
                   COALESCE(SUM(cost_cny), 0) AS cost,
                   COUNT(DISTINCT NULLIF(task_id, '')) AS requests,
                   COUNT(*) AS calls
            FROM llm_usage WHERE created_at >= ?
            GROUP BY day ORDER BY day
            """,
            (cutoff,),
        ).fetchall()

        by_model = _group(conn, "model", cutoff)
        by_role = _group(conn, "role", cutoff)
        by_node = _group(conn, "node", cutoff)
        by_source = _group(conn, "source", cutoff)
        requests = _requests(conn, cutoff)
    finally:
        conn.close()

    prompt_tokens = int(summary_row["prompt_tokens"] or 0)
    cached_tokens = int(summary_row["cached_tokens"] or 0)
    calls = int(summary_row["calls"] or 0)
    priced_calls = int(summary_row["priced_calls"] or 0)

    summary = {
        "requests": int(summary_row["requests"] or 0),
        "calls": calls,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": int(summary_row["completion_tokens"] or 0),
        "total_tokens": int(summary_row["total_tokens"] or 0),
        "cached_tokens": cached_tokens,
        "cache_miss_tokens": max(prompt_tokens - cached_tokens, 0),
        "cache_write_tokens": 0,
        "cost_cny": round(float(summary_row["cost_cny"] or 0), 6),
        "cache_hit_rate": round(cached_tokens / prompt_tokens, 4) if prompt_tokens else 0.0,
        "priced": calls == 0 or priced_calls == calls,
        "peak_calls": int(summary_row["peak_calls"] or 0),
        "off_peak_calls": calls - int(summary_row["peak_calls"] or 0),
        "currency": "CNY",
    }

    for bucket in by_role:
        bucket["label"] = ROLE_LABELS.get(bucket["key"], bucket["key"] or "未标注")
    for bucket in by_source:
        bucket["label"] = {"agent": "智能体", "vision": "图片识别", "backfill": "历史回填"}.get(
            bucket["key"], bucket["key"]
        )
    for bucket in by_node:
        bucket["label"] = bucket["key"] or "未标注"

    return {
        "days": days,
        "summary": summary,
        "series": _fill_series(daily, days),
        "by_model": by_model,
        "by_role": by_role,
        "by_node": by_node,
        "by_source": by_source,
        "requests": requests,
    }


def _group(conn: sqlite3.Connection, field: str, cutoff: str) -> list[dict[str, Any]]:
    if field not in {"model", "role", "node", "source"}:
        return []
    rows = conn.execute(
        f"""
        SELECT {field} AS key,
               COUNT(*) AS calls,
               COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
               COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
               COALESCE(SUM(total_tokens), 0) AS total_tokens,
               COALESCE(SUM(cached_tokens), 0) AS cached_tokens,
               COALESCE(SUM(cost_cny), 0) AS cost_cny
        FROM llm_usage WHERE created_at >= ?
        GROUP BY {field} ORDER BY total_tokens DESC
        """,
        (cutoff,),
    ).fetchall()
    return [
        {
            "key": row["key"] or "",
            "label": row["key"] or "",
            "calls": int(row["calls"] or 0),
            "prompt_tokens": int(row["prompt_tokens"] or 0),
            "completion_tokens": int(row["completion_tokens"] or 0),
            "total_tokens": int(row["total_tokens"] or 0),
            "cached_tokens": int(row["cached_tokens"] or 0),
            "cache_miss_tokens": max(
                int(row["prompt_tokens"] or 0) - int(row["cached_tokens"] or 0), 0
            ),
            "cost_cny": round(float(row["cost_cny"] or 0), 6),
        }
        for row in rows
    ]


def _requests(conn: sqlite3.Connection, cutoff: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT u.task_id,
               MIN(u.created_at) AS created_at,
               COUNT(*) AS calls,
               GROUP_CONCAT(DISTINCT u.model) AS models,
               GROUP_CONCAT(DISTINCT u.source) AS sources,
               COALESCE(SUM(u.prompt_tokens), 0) AS prompt_tokens,
               COALESCE(SUM(u.completion_tokens), 0) AS completion_tokens,
               COALESCE(SUM(u.total_tokens), 0) AS total_tokens,
               COALESCE(SUM(u.cached_tokens), 0) AS cached_tokens,
               COALESCE(SUM(u.cost_cny), 0) AS cost_cny
        FROM llm_usage u
        WHERE u.created_at >= ? AND u.task_id <> ''
        GROUP BY u.task_id ORDER BY created_at DESC LIMIT 200
        """,
        (cutoff,),
    ).fetchall()

    tasks: dict[str, dict[str, Any]] = {}
    try:
        for row in conn.execute(
            "SELECT task_id, user_input, status FROM tasks ORDER BY id DESC LIMIT 2000"
        ):
            tasks[row["task_id"]] = {"user_input": row["user_input"] or "", "status": row["status"] or ""}
    except Exception:
        pass

    result = []
    for row in rows:
        meta = tasks.get(row["task_id"], {})
        result.append(
            {
                "task_id": row["task_id"],
                "created_at": row["created_at"] or "",
                "user_input": (meta.get("user_input") or "")[:80],
                "status": meta.get("status") or "",
                "models": row["models"] or "",
                "sources": row["sources"] or "",
                "calls": int(row["calls"] or 0),
                "prompt_tokens": int(row["prompt_tokens"] or 0),
                "completion_tokens": int(row["completion_tokens"] or 0),
                "total_tokens": int(row["total_tokens"] or 0),
                "cached_tokens": int(row["cached_tokens"] or 0),
                "cost_cny": round(float(row["cost_cny"] or 0), 6),
                "duration_seconds": None,
            }
        )
    return result


def _fill_series(rows: list[sqlite3.Row], days: int) -> list[dict[str, Any]]:
    by_day = {row["day"]: row for row in rows}
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=max(days - 1, 0))
    series = []
    for offset in range(days):
        key = (start + timedelta(days=offset)).isoformat()
        row = by_day.get(key)
        prompt = int(row["prompt_tokens"] or 0) if row else 0
        cached = int(row["cached_tokens"] or 0) if row else 0
        series.append(
            {
                "date": key,
                "input": prompt,
                "cache_miss": max(prompt - cached, 0),
                "output": int(row["completion_tokens"] or 0) if row else 0,
                "cached": cached,
                "cost": round(float(row["cost"] or 0), 6) if row else 0.0,
                "requests": int(row["requests"] or 0) if row else 0,
                "calls": int(row["calls"] or 0) if row else 0,
            }
        )
    return series


def price_snapshot() -> list[dict[str, Any]]:
    """当前计价单价，页面上直接展示，避免"数字对不上却看不出用的什么价"。"""
    from app.core.pricing_store import get_pricing

    pricing = get_pricing()
    return [
        {
            "model": name,
            "input": price.input,
            "cached_input": price.cached_input,
            "output": price.output,
            "currency": price.currency,
        }
        for name, price in sorted(pricing.items())
    ]


def backfill_from_tasks() -> int:
    """把历史任务快照里的用量补进新表，只补没有调用级记录的任务。

    幂等：先清掉上次回填的行；已有 agent 记录的任务跳过，避免新旧账重复。
    """
    delete_by_source("backfill")
    conn = _connect()
    rows: list[dict[str, Any]] = []
    try:
        covered = {
            row["task_id"]
            for row in conn.execute(
                "SELECT DISTINCT task_id FROM llm_usage WHERE source <> 'backfill'"
            )
        }
        tasks = conn.execute(
            "SELECT task_id, created_at, state_snapshot FROM tasks ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    for task in tasks:
        task_id = task["task_id"]
        if task_id in covered:
            continue
        try:
            import json

            snapshot = json.loads(task["state_snapshot"] or "{}")
            usage = ((snapshot.get("metadata") or {}).get("metrics") or {}).get("token_usage") or {}
        except Exception:
            continue
        if not usage:
            continue

        created_at = str(task["created_at"] or "")
        # 历史数据没有逐次调用时间，用任务创建时刻近似判断高峰/空闲。
        moment = _parse_dt(created_at)
        peak = is_peak_hour(moment)

        def cost_of(model: str, item: dict[str, Any]) -> tuple[float, bool]:
            """按当前价目表重算，而不是照抄快照里的旧金额。

            照抄会让每次重启的回填覆盖掉「重算历史成本」的结果。
            """
            record = UsageRecord(
                role="",
                model=model,
                prompt_tokens=int(item.get("prompt_tokens") or 0),
                completion_tokens=int(item.get("completion_tokens") or 0),
                total_tokens=int(item.get("total_tokens") or 0),
                cached_tokens=int(item.get("cached_tokens") or 0),
                at=moment,
            )
            return estimate_cost(record)

        by_model = usage.get("by_model") or {}
        if by_model:
            for model, item in by_model.items():
                amount, known = cost_of(model, item)
                rows.append(
                    {
                        "task_id": task_id,
                        "node": "",
                        "role": "unknown",
                        "model": model,
                        "prompt_tokens": int(item.get("prompt_tokens") or 0),
                        "completion_tokens": int(item.get("completion_tokens") or 0),
                        "total_tokens": int(item.get("total_tokens") or 0),
                        "cached_tokens": int(item.get("cached_tokens") or 0),
                        "cost_cny": amount,
                        "priced": known,
                        "peak": peak,
                        "source": "backfill",
                        "created_at": created_at,
                    }
                )
        else:
            total = usage.get("total") or {}
            amount, known = cost_of("", total)
            rows.append(
                {
                    "task_id": task_id,
                    "node": "",
                    "role": "unknown",
                    "model": "",
                    "prompt_tokens": int(total.get("prompt_tokens") or 0),
                    "completion_tokens": int(total.get("completion_tokens") or 0),
                    "total_tokens": int(total.get("total_tokens") or 0),
                    "cached_tokens": int(total.get("cached_tokens") or 0),
                    "cost_cny": amount,
                    "priced": known,
                    "peak": peak,
                    "source": "backfill",
                    "created_at": created_at,
                }
            )

    if not rows:
        return 0
    written = insert_rows(rows)
    logger.info(f"Usage backfill finished: {written} rows from {len(rows)} candidates")
    return written


def recost_all() -> dict[str, Any]:
    """按当前单价与每条记录的发生时刻重算成本，同时刷新高峰标记。"""
    conn = _connect()
    updated = 0
    try:
        rows = conn.execute(
            "SELECT id, model, prompt_tokens, completion_tokens, total_tokens, "
            "cached_tokens, created_at FROM llm_usage"
        ).fetchall()
        payload = []
        for row in rows:
            moment = _parse_dt(row["created_at"])
            record = UsageRecord(
                role="",
                model=row["model"] or "",
                prompt_tokens=int(row["prompt_tokens"] or 0),
                completion_tokens=int(row["completion_tokens"] or 0),
                total_tokens=int(row["total_tokens"] or 0),
                cached_tokens=int(row["cached_tokens"] or 0),
                at=moment,
            )
            amount, known = estimate_cost(record)
            payload.append(
                (
                    round(amount, 8),
                    1 if known else 0,
                    1 if is_peak_hour(moment) else 0,
                    row["id"],
                )
            )
        if payload:
            with conn:
                conn.executemany(
                    "UPDATE llm_usage SET cost_cny = ?, priced = ?, peak = ? WHERE id = ?",
                    payload,
                )
            updated = len(payload)
    finally:
        conn.close()
    return {"updated": updated}
