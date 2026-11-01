"""机器人1/2 配置与发送回退逻辑的轻量测试。"""

from __future__ import annotations

import pytest

from app.core.config import get_settings


def test_robot_roles_from_env(monkeypatch) -> None:
    monkeypatch.setenv("DINGTALK_ROBOT1_APP_KEY", "ding-robot1")
    monkeypatch.setenv("DINGTALK_ROBOT1_APP_SECRET", "secret1")
    monkeypatch.setenv("DINGTALK_ROBOT2_APP_KEY", "ding-robot2")
    monkeypatch.setenv("DINGTALK_ROBOT2_APP_SECRET", "secret2")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.dingtalk_robot1_configured is True
    assert settings.dingtalk_robot2_configured is True
    assert settings.dingtalk_robot1_robot_code == "ding-robot1"
    assert settings.dingtalk_robot2_app_key == "ding-robot2"
    get_settings.cache_clear()


def test_robot2_falls_back_to_legacy_env(monkeypatch) -> None:
    monkeypatch.delenv("DINGTALK_ROBOT2_APP_KEY", raising=False)
    monkeypatch.delenv("DINGTALK_ROBOT2_APP_SECRET", raising=False)
    monkeypatch.setenv("DINGTALK_APP_KEY", "legacy-key")
    monkeypatch.setenv("DINGTALK_APP_SECRET", "legacy-secret")
    monkeypatch.delenv("DINGTALK_ROBOT1_APP_KEY", raising=False)
    monkeypatch.delenv("DINGTALK_ROBOT1_APP_SECRET", raising=False)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.dingtalk_robot2_configured is True
    assert settings.dingtalk_robot2_app_key == "legacy-key"
    assert settings.dingtalk_robot1_configured is False
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_send_robot1_question_noop_when_missing(monkeypatch) -> None:
    import httpx

    from app.integrations.dingtalk.client import send_robot1_question

    monkeypatch.delenv("DINGTALK_ROBOT1_APP_KEY", raising=False)
    monkeypatch.delenv("DINGTALK_ROBOT1_APP_SECRET", raising=False)
    get_settings.cache_clear()
    async with httpx.AsyncClient() as http:
        assert (
            await send_robot1_question(
                http,
                open_conversation_id="cid123",
                content="hello",
            )
            is False
        )
    get_settings.cache_clear()
