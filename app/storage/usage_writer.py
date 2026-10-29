"""调用级用量落库。

写在 LLM 回调里，只做一次 INSERT，失败也只记日志——记账不能反过来拖垮任务。
用同步 sqlite3 而不是异步 Session：回调本身是同步的，而单条 INSERT 在 SQLite
上只有百微秒级开销，为此绕到线程池反而更慢。
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Iterable

from app.core.config import get_settings
from app.core.logger import logger

_LOCK = threading.Lock()
_warned = False

_INSERT = """
INSERT INTO llm_usage (
    task_id, node, role, model, prompt_tokens, completion_tokens,
    total_tokens, cached_tokens, cost_cny, priced, peak, source, created_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _db_path() -> str:
    """把 SQLAlchemy URL 还原成 sqlite 文件路径，行为与引擎保持一致。"""
    url = get_settings().database_url
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if url.startswith(prefix):
            return url[len(prefix) :]
    return url


def _connect() -> sqlite3.Connection | None:
    try:
        conn = sqlite3.connect(_db_path(), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn
    except Exception:
        return None


def insert_usage(
    *,
    task_id: str,
    node: str = "",
    role: str = "",
    model: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    cached_tokens: int = 0,
    cost_cny: float = 0.0,
    priced: bool = False,
    peak: bool = True,
    source: str = "agent",
    created_at: str | None = None,
) -> None:
    global _warned
    conn = _connect()
    if conn is None:
        if not _warned:
            logger.warning("Usage log skipped: database not reachable")
            _warned = True
        return
    try:
        with _LOCK, conn:
            conn.execute(
                _INSERT,
                (
                    task_id or "",
                    node or "",
                    role or "",
                    model or "",
                    int(prompt_tokens),
                    int(completion_tokens),
                    int(total_tokens or prompt_tokens + completion_tokens),
                    int(cached_tokens),
                    round(float(cost_cny), 8),
                    1 if priced else 0,
                    1 if peak else 0,
                    source,
                    created_at
                    or datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds"),
                ),
            )
    except Exception as exc:
        if not _warned:
            logger.warning(f"Usage log failed: {str(exc)[:160]}")
            _warned = True
    finally:
        try:
            conn.close()
        except Exception:
            pass


def delete_by_source(source: str) -> int:
    conn = _connect()
    if conn is None:
        return 0
    try:
        with _LOCK, conn:
            cursor = conn.execute("DELETE FROM llm_usage WHERE source = ?", (source,))
            return cursor.rowcount or 0
    except Exception:
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


def insert_rows(rows: Iterable[dict[str, Any]]) -> int:
    payload = [
        (
            row.get("task_id") or "",
            row.get("node") or "",
            row.get("role") or "",
            row.get("model") or "",
            int(row.get("prompt_tokens") or 0),
            int(row.get("completion_tokens") or 0),
            int(row.get("total_tokens") or 0),
            int(row.get("cached_tokens") or 0),
            round(float(row.get("cost_cny") or 0), 8),
            1 if row.get("priced") else 0,
            1 if row.get("peak", True) else 0,
            row.get("source") or "backfill",
            row.get("created_at")
            or datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds"),
        )
        for row in rows
    ]
    if not payload:
        return 0
    conn = _connect()
    if conn is None:
        return 0
    try:
        with _LOCK, conn:
            conn.executemany(_INSERT, payload)
        return len(payload)
    except Exception as exc:
        logger.warning(f"Usage backfill failed: {str(exc)[:160]}")
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass
