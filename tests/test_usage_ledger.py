"""用量账本测试：调用级落库、聚合口径、回填幂等。"""

from __future__ import annotations

import sqlite3

import pytest

from app.core.config import get_settings
from app.storage import repo_usage, usage_writer

SCHEMA = """
CREATE TABLE llm_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id VARCHAR(64) NOT NULL DEFAULT '',
    node VARCHAR(64) DEFAULT '',
    role VARCHAR(32) DEFAULT '',
    model VARCHAR(80) DEFAULT '',
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    cached_tokens INTEGER DEFAULT 0,
    cost_cny FLOAT DEFAULT 0,
    priced BOOLEAN DEFAULT 0,
    peak BOOLEAN DEFAULT 1,
    source VARCHAR(16) DEFAULT 'agent',
    created_at DATETIME
);
CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id VARCHAR(64),
    user_input TEXT,
    status VARCHAR(32),
    state_snapshot TEXT,
    created_at DATETIME
);
"""


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "ledger.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    monkeypatch.setattr(
        get_settings(), "database_url", f"sqlite+aiosqlite:///{path.as_posix()}", raising=False
    )
    return path


def test_aggregate_sums_calls_and_cache_miss(ledger):
    usage_writer.insert_usage(
        task_id="t1", node="planner", role="planner", model="deepseek-flash",
        prompt_tokens=1000, completion_tokens=200, total_tokens=1200,
        cached_tokens=400, cost_cny=0.5, priced=True, source="agent",
    )
    usage_writer.insert_usage(
        task_id="t1", node="engineer", role="engineer", model="deepseek-flash",
        prompt_tokens=3000, completion_tokens=800, total_tokens=3800,
        cached_tokens=1800, cost_cny=1.2, priced=True, source="agent",
    )
    usage_writer.insert_usage(
        task_id="", node="image_extract", role="vision", model="deepseek-flash",
        prompt_tokens=500, completion_tokens=100, total_tokens=600,
        cached_tokens=0, cost_cny=0.2, priced=True, source="vision",
    )

    data = repo_usage.aggregate(days=30)
    summary = data["summary"]

    assert summary["calls"] == 3
    assert summary["requests"] == 1  # 图片识别没有 task_id，不计入任务数
    assert summary["prompt_tokens"] == 4500
    assert summary["completion_tokens"] == 1100
    assert summary["total_tokens"] == 5600
    assert summary["cached_tokens"] == 2200
    assert summary["cache_miss_tokens"] == 2300
    assert summary["cost_cny"] == pytest.approx(1.9)
    assert summary["cache_hit_rate"] == pytest.approx(0.4889, abs=1e-4)

    sources = {row["key"]: row for row in data["by_source"]}
    assert sources["agent"]["calls"] == 2
    assert sources["vision"]["calls"] == 1

    models = {row["key"]: row for row in data["by_model"]}
    assert models["deepseek-flash"]["total_tokens"] == 5600


def test_failed_task_calls_are_still_counted(ledger):
    """失败节点只写调用记录、不写任务快照，也必须出现在统计里。"""
    usage_writer.insert_usage(
        task_id="boom", node="reviewer", role="reviewer", model="deepseek-flash",
        prompt_tokens=800, completion_tokens=40, total_tokens=840,
        cached_tokens=0, cost_cny=0.1, priced=True, source="agent",
    )
    data = repo_usage.aggregate(days=30)
    assert data["summary"]["calls"] == 1
    assert data["summary"]["total_tokens"] == 840
    assert data["by_node"][0]["key"] == "reviewer"


def test_backfill_is_idempotent(ledger, monkeypatch):
    conn = sqlite3.connect(ledger)
    snapshot = (
        '{"metadata": {"metrics": {"token_usage": {"total": {"prompt_tokens": 100, '
        '"completion_tokens": 50, "total_tokens": 150, "cached_tokens": 20, "calls": 1}, '
        '"cost_cny": 0.3, "priced": true, "by_model": {"deepseek-flash": '
        '{"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150, '
        '"cached_tokens": 20, "calls": 1, "cost_cny": 0.3}}}}}}'
    )
    conn.execute(
        "INSERT INTO tasks (task_id, user_input, status, state_snapshot, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("old-task", "历史需求", "completed", snapshot, "2026-10-20T10:00:00"),
    )
    conn.commit()
    conn.close()

    first = repo_usage.backfill_from_tasks()
    second = repo_usage.backfill_from_tasks()
    assert first == 1
    assert second == 1  # 先删后插，不会翻倍

    data = repo_usage.aggregate(days=30)
    assert data["summary"]["total_tokens"] == 150
    assert data["summary"]["calls"] == 1
    # 快照记的是旧价 0.3，回填必须按当前价目表重算，否则每次重启都会覆盖「重算历史成本」的结果。
    # 2026-10-20T10:00Z = 北京 18:00，属空闲时段，按半价。
    assert data["summary"]["cost_cny"] == pytest.approx(0.00028, abs=1e-6)


def test_backfill_skips_tasks_with_live_records(ledger):
    conn = sqlite3.connect(ledger)
    conn.execute(
        "INSERT INTO tasks (task_id, user_input, status, state_snapshot, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("live-task", "已采集", "completed", '{"metadata":{"metrics":{"token_usage":{}}}}', "2026-10-21T10:00:00"),
    )
    conn.commit()
    conn.close()
    usage_writer.insert_usage(
        task_id="live-task", node="planner", role="planner", model="deepseek-flash",
        prompt_tokens=10, completion_tokens=5, total_tokens=15, cached_tokens=0,
        cost_cny=0.01, priced=True, source="agent",
    )
    assert repo_usage.backfill_from_tasks() == 0
    data = repo_usage.aggregate(days=30)
    assert data["summary"]["calls"] == 1
    assert data["by_source"][0]["key"] == "agent"
