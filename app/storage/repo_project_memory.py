"""project_memory 结构化归档 —— 长期记忆的"事实账本"（同步 sqlite3 直写）。

工作流节点是同步函数（跑在 asyncio.to_thread 里），不能 await 异步仓储，
因此与 run_column_migrations 相同，这里用直连 sqlite3 写入本地库；
表结构由 SQLAlchemy 的 ProjectMemoryRecord 在 init_db 时创建。

与 Chroma 的分工：Chroma 负责"语义找得到"（few-shot 召回），这张表负责
"事实查得清"（按项目/类型/分数过滤、审计、重建向量库的数据源）。
memory_key 唯一约束保证任务重跑/巩固写入幂等。
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.core.config import get_settings
from app.core.logger import logger


def _db_path() -> str:
    url = get_settings().database_url
    return url.split("///", 1)[-1]


def save_memory_archive(
    *,
    project_id: str,
    memory_key: str,
    memory_type: str,
    task_id: str,
    domain: str,
    product_name: str,
    overall_score: float | None,
    content: str,
    meta: dict[str, Any] | None = None,
) -> bool:
    """幂等 upsert 一条长期记忆归档。失败返回 False，不抛异常、不阻塞主流程。"""
    sql = """
        INSERT INTO project_memory
            (project_id, memory_key, memory_type, task_id, domain, product_name,
             overall_score, content, meta_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(memory_key) DO UPDATE SET
            content = excluded.content,
            overall_score = excluded.overall_score,
            domain = excluded.domain,
            product_name = excluded.product_name,
            meta_json = excluded.meta_json,
            updated_at = CURRENT_TIMESTAMP
    """
    try:
        with sqlite3.connect(_db_path(), timeout=15) as conn:
            conn.execute(
                sql,
                (
                    project_id, memory_key, memory_type, task_id,
                    domain or "", product_name or "", overall_score,
                    content, json.dumps(meta or {}, ensure_ascii=False),
                ),
            )
            conn.commit()
        return True
    except Exception as exc:  # pragma: no cover - 归档失败不应影响交付
        logger.warning(f"project_memory 归档失败: {exc}", extra={"memory_key": memory_key})
        return False


def list_memory_archive(
    project_id: str = "default",
    memory_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """按项目读取归档（可选类型过滤），供后台分析/重建向量库使用。"""
    sql = (
        "SELECT memory_key, memory_type, task_id, domain, product_name, "
        "overall_score, content, meta_json, created_at FROM project_memory "
        "WHERE project_id = ?"
    )
    params: list[Any] = [project_id]
    if memory_type:
        sql += " AND memory_type = ?"
        params.append(memory_type)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    try:
        with sqlite3.connect(_db_path(), timeout=15) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(sql, params)]
    except Exception as exc:  # pragma: no cover
        logger.warning(f"project_memory 读取失败: {exc}")
        return []
