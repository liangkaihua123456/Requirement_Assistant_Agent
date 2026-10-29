"""Deterministic checks on the API surface.

The generation side is told to keep one canonical path per action and to
aggregate reads by resource. This module enforces the same rules on the review
side, so a design that ignores them is flagged even when the model reviewer
misses it.
"""

from __future__ import annotations

import re
from typing import Any

_PARAM = re.compile(r"\{[^}]+\}")
_VERSION = re.compile(r"^v\d+$")

# Reads that are legitimately separate from list/detail: exports, personal
# views, searches and dashboards. They must not count towards read sprawl.
_READ_VIEWS = {
    "export",
    "export-csv",
    "my",
    "me",
    "search",
    "stats",
    "summary",
    "trend",
    "pending",
    "queue",
    "alerts",
    "history",
    "options",
    "lookup",
    "overdue",
}


def _segments(path: str) -> list[str]:
    return [item for item in str(path or "").split("/") if item]


def _meaningful(path: str) -> list[str]:
    return [
        item
        for item in _segments(path)
        if item != "api" and not _VERSION.match(item)
    ]


def _resource_key(path: str) -> str:
    parts = _meaningful(path)
    return parts[0].lower() if parts else ""


def _action_of(path: str) -> str:
    parts = _meaningful(path)
    if not parts:
        return ""
    last = parts[-1]
    if last.startswith("{"):
        return ""
    return last.lower()


def audit_api_hygiene(design: dict[str, Any]) -> list[dict[str, Any]]:
    """Return issues for duplicate action paths and read-endpoint sprawl."""
    endpoints = [
        item for item in (design.get("api_endpoints") or []) if isinstance(item, dict)
    ]
    issues: list[dict[str, Any]] = []

    # 1) The same action must not be reachable through two different paths.
    buckets: dict[tuple[str, str], set[str]] = {}
    for endpoint in endpoints:
        path = str(endpoint.get("path") or "")
        action = _action_of(path)
        if not action:
            continue
        key = (_resource_key(path), action)
        buckets.setdefault(key, set()).add(_PARAM.sub("{id}", path))

    for (resource, action), paths in buckets.items():
        if len(paths) < 2:
            continue
        preview = "、".join(sorted(paths)[:3])
        issues.append(
            {
                "category": "一致性",
                "severity": "high",
                "description": (
                    f"动作 {action} 在 {resource} 下存在多个路径：{preview}，"
                    "同一业务动作应只有一个规范路径"
                ),
                "suggestion": "保留一个规范路径，其余合并或删除，避免调用方择路困难",
                "target": "engineer",
                "origin": "new",
            }
        )

    # 2) Reads should be aggregated: list + detail, not one endpoint per view.
    reads: dict[str, list[str]] = {}
    for endpoint in endpoints:
        if str(endpoint.get("method") or "").upper() != "GET":
            continue
        path = str(endpoint.get("path") or "")
        if _action_of(path) in _READ_VIEWS:
            continue
        reads.setdefault(_resource_key(path), []).append(path)

    for resource, paths in reads.items():
        if len(paths) <= 4:
            continue
        preview = "、".join(sorted(set(paths))[:3])
        issues.append(
            {
                "category": "一致性",
                "severity": "medium",
                "description": (
                    f"{resource} 下有 {len(paths)} 个 GET 端点：{preview} 等，"
                    "读接口应按资源聚合为列表 + 详情，筛选交给查询参数"
                ),
                "suggestion": "合并为列表与详情两个端点，其余视图用查询参数或前端组合表达",
                "target": "engineer",
                "origin": "new",
            }
        )

    return issues
