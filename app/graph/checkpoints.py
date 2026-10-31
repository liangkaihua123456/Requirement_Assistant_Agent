"""LangGraph checkpoint 持久化 —— 官方 SqliteSaver（短期记忆/运行时状态载体）。

每个 super-step 的 state（含 task_memory、各产物每轮版本）由官方 SqliteSaver
增量写入 SQLite：跨线程安全、支持异步路径（aput）、按 thread_id（=task_id）
隔离，任务终态用 delete_thread 回收。

历史说明：v1 自制 PersistentMemorySaver（内存主存 + pickle 全量快照）已废弃。
旧文件 data/checkpoints/langgraph_checkpoints.sqlite 仅作历史留档，v1 时期挂起
（waiting_human）的任务无法在新 checkpointer 上恢复，需重新创建任务。
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from app.core.config import get_settings
from app.core.logger import logger

_checkpointer: SqliteSaver | None = None
_lock = threading.Lock()


def _make_serde():
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    return JsonPlusSerializer().with_msgpack_allowlist(
        [("app.schemas.review", "ReviewTargetType")]
    )


def get_checkpoint_path() -> Path:
    settings = get_settings()
    return settings.checkpoint_dir / "langgraph_checkpoints_v2.sqlite"


def get_checkpointer() -> SqliteSaver:
    """Return the process-wide SqliteSaver (thread-safe, write-through)."""
    global _checkpointer
    if _checkpointer is None:
        with _lock:
            if _checkpointer is None:
                path = get_checkpoint_path()
                path.parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(str(path), check_same_thread=False)
                _checkpointer = SqliteSaver(conn, serde=_make_serde())
                logger.info(f"SqliteSaver checkpointer ready at {path}")
    return _checkpointer


def reset_checkpointer_for_tests() -> None:
    """Drop the cached checkpointer so tests can point at a fresh file."""
    global _checkpointer
    _checkpointer = None


def has_checkpoint(thread_id: str) -> bool:
    try:
        saver = get_checkpointer()
        return saver.get_tuple({"configurable": {"thread_id": thread_id}}) is not None
    except Exception:
        return False
