"""Shared test fixtures."""

from __future__ import annotations

import pytest_asyncio

from app.core.config import get_settings
from app.storage import db as db_module


@pytest_asyncio.fixture
async def temp_db(tmp_path, monkeypatch):
    """用临时 SQLite，避免测试污染 data/tasks.db。"""
    monkeypatch.setenv(
        "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    )
    get_settings.cache_clear()
    db_module._engine = None
    db_module._session_factory = None
    await db_module.init_db()
    try:
        yield
    finally:
        if db_module._engine is not None:
            await db_module._engine.dispose()
        db_module._engine = None
        db_module._session_factory = None
        get_settings.cache_clear()
