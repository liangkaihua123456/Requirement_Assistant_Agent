"""同步更新任务进度（供 LangGraph 节点线程使用）。

节点跑在 ``asyncio.to_thread`` 里，不能直接 ``await`` 异步 Session。
这里用与 ``usage_writer`` 相同的同步 sqlite3 路径，只更新
``current_node`` / ``updated_at``，让详情页在长调用期间不再卡在「排队中」。
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone

from app.core.config import get_settings
from app.core.logger import logger

_LOCK = threading.Lock()
_warned = False

_UPDATE_NODE = """
UPDATE tasks
SET current_node = ?, updated_at = ?
WHERE task_id = ? AND status IN ('queued', 'running')
"""


def _db_path() -> str:
    url = get_settings().database_url
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if url.startswith(prefix):
            return url[len(prefix) :]
    return url


def mark_current_node(task_id: str, node: str) -> None:
    """Best-effort：节点开始时写回 current_node。失败不抛，以免拖垮工作流。"""
    global _warned
    if not task_id or not node:
        return
    try:
        conn = sqlite3.connect(_db_path(), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
    except Exception:
        if not _warned:
            logger.warning("Progress update skipped: database not reachable")
            _warned = True
        return
    try:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
        with _LOCK, conn:
            conn.execute(_UPDATE_NODE, (node, now, task_id))
    except Exception as exc:
        logger.warning(f"Progress update failed: {str(exc)[:160]}")
    finally:
        conn.close()
