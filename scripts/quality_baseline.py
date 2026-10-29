"""Quality baseline from existing task snapshots.

No LLM calls: it reads `data/tasks.db` and derives the metrics that matter for
delivery quality, so a change can be compared before/after against the same
yardstick.

Usage:
    python scripts/quality_baseline.py
    python scripts/quality_baseline.py --json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "tasks.db"
REPORT_DIR = ROOT / "reports"

STATE_CHANGE_HINTS = (
    "approve",
    "reject",
    "cancel",
    "confirm",
    "refund",
    "renew",
    "return",
    "overdue",
    "expire",
    "submit",
    "withdraw",
    "assign",
    "dispatch",
    "transfer",
    "settle",
    "pay",
    "ship",
    "complete",
    "verify",
    "close",
    "status",
    "checkin",
    "checkout",
)


def load_tasks() -> list[dict]:
    if not DB_PATH.exists():
        return []
    connection = sqlite3.connect(DB_PATH)
    rows = connection.execute(
        "select task_id, status, created_at, state_snapshot from tasks order by created_at"
    ).fetchall()
    connection.close()
    tasks = []
    for task_id, status, created_at, snapshot in rows:
        try:
            state = json.loads(snapshot or "{}")
        except Exception:
            continue
        tasks.append(
            {"task_id": task_id, "status": status, "created_at": str(created_at), "state": state}
        )
    return tasks


def _feature_api_count(feature: dict, endpoints: list[dict]) -> int:
    fid = str(feature.get("feature_id") or "")
    name = str(feature.get("name") or "")
    hits = 0
    for endpoint in endpoints:
        ids = [str(item) for item in (endpoint.get("related_feature_ids") or [])]
        if fid and fid in ids:
            hits += 1
            continue
        text = f"{endpoint.get('path') or ''} {endpoint.get('description') or ''}"
        if name and name in text:
            hits += 1
    return hits


def analyze(task: dict) -> dict:
    state = task["state"]
    prd = state.get("prd_doc") or {}
    design = state.get("technical_design") or {}
    review = state.get("review_result") or {}
    metrics = (state.get("metadata") or {}).get("metrics") or {}
    usage = (metrics.get("token_usage") or {}).get("total") or {}

    features = [item for item in (prd.get("feature_modules") or []) if isinstance(item, dict)]
    endpoints = [item for item in (design.get("api_endpoints") or []) if isinstance(item, dict)]
    tables = [
        item
        for item in ((design.get("db_schema") or {}).get("tables") or [])
        if isinstance(item, dict)
    ]
    issues = review.get("issues") or []
    severity = Counter(str(item.get("severity") or "?") for item in issues)

    per_feature = [_feature_api_count(feature, endpoints) for feature in features]
    methods = Counter(str(item.get("method") or "").upper() for item in endpoints)
    state_changes = sum(
        1
        for item in endpoints
        if any(hint in str(item.get("path") or "").lower() for hint in STATE_CHANGE_HINTS)
    )

    prompt = usage.get("prompt_tokens") or 0
    cached = usage.get("cached_tokens") or 0
    return {
        "task_id": task["task_id"],
        "status": task["status"],
        "created_at": task["created_at"],
        "features": len(features),
        "apis": len(endpoints),
        "tables": len(tables),
        "services": len(design.get("services") or []),
        "api_per_feature_median": statistics.median(per_feature) if per_feature else 0,
        "features_without_api": sum(1 for count in per_feature if count == 0),
        "get_ratio": round(methods.get("GET", 0) / max(len(endpoints), 1), 2),
        "state_change_apis": state_changes,
        "degraded": bool(design.get("_degraded")),
        "score": review.get("overall_score"),
        # Early tasks scored a flat 7.0 before the rubric existed; mixing them
        # into the baseline hides real improvements.
        "has_rubric": review.get("completeness_score") is not None,
        "passed": review.get("passed"),
        "issues": len(issues),
        "high": severity.get("high", 0) + severity.get("critical", 0),
        "medium": severity.get("medium", 0),
        "prompt_tokens": prompt,
        "cached_tokens": cached,
        "cache_rate": round(cached / prompt * 100, 1) if prompt else 0.0,
        "cost_cny": usage.get("cost_cny"),
        "duration_seconds": metrics.get("background_duration_seconds"),
    }


def bucket_of(item: dict) -> str:
    if item["degraded"]:
        return "降级"
    if item["features"] >= 7:
        return "复杂"
    if item["features"] >= 5:
        return "中等"
    return "简单"


def build_report(items: list[dict]) -> str:
    header = (
        "| 任务 | 分档 | 状态 | 评分 | 通过 | high | 中 | 模块 | API | 表 | "
        "每模块API中位 | 无API模块 | GET占比 | 状态流转 | 降级 | 命中率 |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | "
        "--- | --- | --- | --- | --- | --- |\n"
    )
    lines = []
    for item in items:
        lines.append(
            f"| {item['task_id']} | {bucket_of(item)} | {item['status']} | "
            f"{item['score'] if item['score'] is not None else '-'}{'' if item['has_rubric'] else '*'} | "
            f"{'是' if item['passed'] else '否'} | {item['high']} | {item['medium']} | "
            f"{item['features']} | {item['apis']} | {item['tables']} | "
            f"{item['api_per_feature_median']} | {item['features_without_api']} | "
            f"{item['get_ratio']} | {item['state_change_apis']} | "
            f"{'是' if item['degraded'] else '否'} | {item['cache_rate']}% |"
        )
    return header + "\n".join(lines)


def summarize(items: list[dict]) -> dict:
    groups: dict[str, list[dict]] = {}
    for item in items:
        groups.setdefault(bucket_of(item), []).append(item)

    summary: dict[str, dict] = {}
    for name, group in groups.items():
        scores = [
            item["score"]
            for item in group
            if item["has_rubric"] and isinstance(item["score"], (int, float))
        ]
        highs = [item["high"] for item in group]
        summary[name] = {
            "count": len(group),
            "scored": len(scores),
            "score_median": round(statistics.median(scores), 2) if scores else None,
            "score_min": min(scores) if scores else None,
            "high_median": statistics.median(highs) if highs else 0,
            "degraded": sum(1 for item in group if item["degraded"]),
            "zero_api_features": sum(item["features_without_api"] for item in group),
            "cache_rate_median": round(
                statistics.median([item["cache_rate"] for item in group]), 1
            ),
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="print JSON instead of the table")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    items = [analyze(task) for task in load_tasks()]
    total = len(items)
    # Tasks without a PRD never reached the design stage; counting them as
    # "simple / 0 APIs" skews the baseline.
    items = [item for item in items if item["features"] > 0]
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    summary = summarize(items)
    (REPORT_DIR / "quality_baseline.json").write_text(
        json.dumps(
            {"total_tasks": total, "valid_tasks": len(items), "items": items, "summary": summary},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    report = (
        f"共 {total} 个任务，其中 {len(items)} 个进入设计阶段（有 PRD）。\n\n"
        + build_report(items)
        + "\n\n## 分档基线\n\n```json\n"
        + json.dumps(summary, ensure_ascii=False, indent=2)
        + "\n```\n"
    )
    (REPORT_DIR / "quality_baseline.md").write_text(report, encoding="utf-8")

    if args.json:
        print(
            json.dumps(
                {"total_tasks": total, "valid_tasks": len(items), "items": items, "summary": summary},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(report)
    print(f"\n已写入 {REPORT_DIR / 'quality_baseline.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
