"""Regression tests for the performance work (batch A).

Each test pins one removed source of wasted work so a later refactor cannot
silently bring it back.
"""

from __future__ import annotations

import pytest

from app.agents.orchestrator_agent import normalize_input_text
from app.core.config import get_settings
from app.memory import few_shot
from app.storage.memory_chroma import DashScopeEmbeddingFunction


def test_normalize_input_text_cleans_without_changing_content():
    raw = "  做一个\u200b 订单\r\n\r\n\r\n\r\n系统，\t支持  退款  "
    cleaned = normalize_input_text(raw, max_chars=8000)
    assert "\u200b" not in cleaned
    assert "\r" not in cleaned
    assert "订单" in cleaned and "退款" in cleaned
    assert "\n\n\n" not in cleaned


def test_normalize_input_text_truncates_at_limit():
    cleaned = normalize_input_text("需" * 50, max_chars=10)
    assert cleaned.startswith("需" * 10)
    assert cleaned.endswith("[输入已截断]")


def test_few_shot_skips_memory_store_when_disabled(monkeypatch):
    def _fail(*args, **kwargs):
        raise AssertionError("memory store must not be touched when disabled")

    monkeypatch.setattr(few_shot, "search_memory_sync", _fail)
    result = few_shot.build_few_shot_for_task(
        {"feature_modules": [{"name": "订单"}]},
        {"goal": "订单系统"},
        enabled=False,
    )
    assert result == ""


def test_few_shot_respects_task_level_override(monkeypatch):
    monkeypatch.setattr(few_shot, "search_memory_sync", lambda *a, **k: [])
    text = few_shot.build_few_shot_for_task(
        {"feature_modules": [{"name": "订单"}]},
        {"goal": "订单系统"},
        metadata={"memory_enabled": False},
    )
    assert text == ""
    assert few_shot.resolve_memory_enabled({"memory_enabled": True}) is True
    assert few_shot.resolve_memory_enabled({"memory_enabled": False}) is False


def test_embedding_without_api_key_falls_back_to_hash_once(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "openai_api_key", "", raising=False)
    embedder = DashScopeEmbeddingFunction(model="text-embedding-v3", dimensions=64)

    first = embedder("a")
    second = embedder("b")

    assert embedder._disabled is True
    assert len(first) == 1 and len(first[0]) == 64
    assert len(second) == 1 and len(second[0]) == 64


def test_slim_excerpt_keeps_only_tail():
    from app.core.llm import _slim_excerpt

    payload = "a" * 5000
    excerpt = _slim_excerpt(payload, limit=2000)
    assert excerpt.endswith("a" * 2000)
    assert len(excerpt) < 2100
    assert excerpt != payload


@pytest.mark.asyncio
async def test_worker_pool_matches_configured_concurrency():
    import asyncio

    from app.core import task_queue

    task_queue._worker_tasks = []
    task_queue._queue = asyncio.Queue()
    task_queue._stop_event = asyncio.Event()
    task_queue._ensure_worker_pool()
    try:
        assert len(task_queue._worker_tasks) == get_settings().task_worker_concurrency
        assert all(not task.done() for task in task_queue._worker_tasks)
    finally:
        await task_queue.stop_worker()
        task_queue._queue = None
        task_queue._stop_event = None
