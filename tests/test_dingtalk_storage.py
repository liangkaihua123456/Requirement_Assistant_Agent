"""DingTalk 存储层测试：临时 SQLite，不碰 data/tasks.db。"""

from __future__ import annotations

import pytest

from app.storage import dingtalk as dingtalk_repo


@pytest.mark.asyncio
async def test_message_dedup(temp_db) -> None:
    assert await dingtalk_repo.claim_message("m1", "c1") is True
    assert await dingtalk_repo.claim_message("m1", "c1") is False
    assert await dingtalk_repo.claim_message("m2", "c1") is True


@pytest.mark.asyncio
async def test_one_active_binding_per_conversation(temp_db) -> None:
    assert await dingtalk_repo.create_binding("c1", "t1", "u1", "https://hook") is True
    assert await dingtalk_repo.create_binding("c1", "t2", "u1", "https://hook") is False

    binding = await dingtalk_repo.get_active_binding("c1")
    assert binding is not None
    assert binding["task_id"] == "t1"

    await dingtalk_repo.set_pending(
        "t1", "clarification", ["目标平台？"], "https://hook"
    )
    binding = await dingtalk_repo.get_active_binding("c1")
    assert binding["pending_kind"] == "clarification"
    assert binding["pending_payload"] == ["目标平台？"]

    await dingtalk_repo.clear_pending("t1", "https://hook2")
    binding = await dingtalk_repo.get_active_binding("c1")
    assert binding["pending_kind"] == ""
    assert binding["session_webhook"] == "https://hook2"

    await dingtalk_repo.deactivate_binding("t1", "completed")
    assert await dingtalk_repo.get_active_binding("c1") is None

    latest = await dingtalk_repo.get_latest_binding("c1")
    assert latest["task_id"] == "t1"
    assert latest["active"] is False

    # active 已释放，同一会话可以绑定新任务
    assert await dingtalk_repo.create_binding("c1", "t3", "u1", "https://hook") is True
