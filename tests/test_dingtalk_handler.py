"""DingTalk handler 测试：临时 DB + MockTransport，不连钉钉。"""

from __future__ import annotations

import json

import httpx
import pytest

from app.integrations.dingtalk import service
from app.integrations.dingtalk.handler import DingTalkHandler
from app.storage import dingtalk as dingtalk_repo
from app.storage import repo_task


class FakeCallback:
    def __init__(self, msg_id: str, text: str, sender: str = "u1") -> None:
        self.data = {
            "msgtype": "text",
            "text": {"content": text},
            "msgId": msg_id,
            "conversationId": "c1",
            "senderStaffId": sender,
            "sessionWebhook": "https://example.invalid/hook",
        }


@pytest.mark.asyncio
async def test_handler_create_and_status(temp_db, monkeypatch) -> None:
    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(service, "enqueue_start", noop)
    monkeypatch.setattr(service, "enqueue_resume", noop)

    sent: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        bot = DingTalkHandler(http)

        await bot.process(FakeCallback("m1", "做个待办应用"))
        assert "已受理" in sent[-1]["text"]["content"]

        binding = await dingtalk_repo.get_active_binding("c1")
        assert binding is not None
        task = await repo_task.get_task(binding["task_id"])
        assert task is not None
        assert task["status"] == "queued"

        await bot.process(FakeCallback("m2", "状态"))
        assert "状态：queued" in sent[-1]["text"]["content"]

        # 同一个 msgId 重推不再处理
        await bot.process(FakeCallback("m1", "做个待办应用"))
        assert len(sent) == 2


@pytest.mark.asyncio
async def test_handler_feedback_and_auth(temp_db, monkeypatch) -> None:
    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(service, "enqueue_start", noop)
    monkeypatch.setattr(service, "enqueue_resume", noop)
    monkeypatch.setattr(service, "has_checkpoint", lambda task_id: True)

    sent: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        bot = DingTalkHandler(http)
        await bot.process(FakeCallback("m1", "做个待办应用"))

        binding = await dingtalk_repo.get_active_binding("c1")
        task_id = binding["task_id"]
        await repo_task.update_task(
            task_id,
            status="waiting_human",
            current_node="human_approval",
            state_snapshot={"review_result": {"passed": False, "overall_score": 7.5}},
        )
        await dingtalk_repo.set_pending(
            task_id, "approval", {"overall_score": 7.5}, "https://example.invalid/hook"
        )

        # 非发起人不能审批
        await bot.process(FakeCallback("m2", "通过", sender="u2"))
        assert "只有任务发起人" in sent[-1]["text"]["content"]

        # 发起人可以审批
        await bot.process(FakeCallback("m3", "通过", sender="u1"))
        assert "已提交" in sent[-1]["text"]["content"]
        task = await repo_task.get_task(task_id)
        assert task["status"] == "queued"
        binding = await dingtalk_repo.get_active_binding("c1")
        assert binding["pending_kind"] == ""
