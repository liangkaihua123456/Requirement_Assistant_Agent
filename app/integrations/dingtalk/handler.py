"""钉钉机器人消息处理：建任务、查状态、提交澄清/审批。"""

from __future__ import annotations

import httpx
import dingtalk_stream
from dingtalk_stream import AckMessage

from app.core.logger import logger
from app.integrations.dingtalk import service
from app.integrations.dingtalk.client import post_text
from app.integrations.dingtalk.render import (
    parse_approval,
    render_task_summary,
)
from app.storage import dingtalk as dingtalk_repo

STATUS_WORDS = {"状态", "status"}


class DingTalkHandler(dingtalk_stream.ChatbotHandler):
    """把钉钉群消息翻译成任务操作。"""

    def __init__(self, http: httpx.AsyncClient):
        super().__init__()
        self.http = http

    async def process(self, callback: dingtalk_stream.CallbackMessage):
        msg = dingtalk_stream.ChatbotMessage.from_dict(callback.data)
        msg_id = msg.message_id or ""
        conversation_id = msg.conversation_id or msg.sender_staff_id or ""
        if not msg_id or not conversation_id:
            return AckMessage.STATUS_OK, "OK"

        # 钉钉可能重推；msg_id 是全局唯一键，先原子占用
        if not await dingtalk_repo.claim_message(msg_id, conversation_id):
            logger.info("DingTalk duplicate msg_id skipped", extra={"node": "dingtalk"})
            return AckMessage.STATUS_OK, "OK"

        text = (msg.text.content if msg.text else "").strip()
        sender = msg.sender_staff_id or ""
        webhook = msg.session_webhook or ""

        async with service.conversation_lock(conversation_id):
            binding = await dingtalk_repo.get_active_binding(conversation_id)
            if binding and webhook:
                await dingtalk_repo.update_binding(
                    binding["task_id"], session_webhook=webhook
                )
                binding["session_webhook"] = webhook

            pending = binding if binding and binding.get("pending_kind") else None

            if pending and text not in STATUS_WORDS:
                reply = await self._handle_pending(pending, text, sender, webhook)
            elif text in STATUS_WORDS:
                reply = await self._render_status(conversation_id, binding, pending)
            elif binding:
                reply = f"当前会话任务 {binding['task_id']} 仍在执行，请等待完成"
            elif not text:
                reply = "请描述你的需求"
            else:
                task_id, error = await service.create_task_from_dingtalk(
                    conversation_id=conversation_id,
                    text=text,
                    requester_staff_id=sender,
                    session_webhook=webhook,
                )
                if task_id:
                    reply = f"已受理：{task_id}"
                elif error == "busy":
                    reply = "当前会话已有进行中的任务，请等待完成"
                else:
                    reply = "创建任务失败，请稍后再试"

        logger.info(
            "DingTalk message handled",
            extra={
                "node": "dingtalk",
                "conversation_id": conversation_id,
                "task_id": (binding or {}).get("task_id", ""),
            },
        )

        if webhook:
            try:
                await post_text(self.http, webhook, reply, sender)
            except Exception as exc:
                logger.warning(f"DingTalk reply failed: {exc}", extra={"node": "dingtalk"})

        return AckMessage.STATUS_OK, "OK"

    async def _render_status(
        self,
        conversation_id: str,
        binding: dict | None,
        pending: dict | None,
    ) -> str:
        target = binding or await dingtalk_repo.get_latest_binding(conversation_id)
        if not target:
            return "当前会话没有任务"

        task = await service.get_task(target["task_id"])
        if task is None:
            return "任务记录不存在"
        reply = render_task_summary(task)
        if pending:
            reply += "\n等待你回复澄清/审批内容"
        return reply

    async def _handle_pending(
        self,
        pending: dict,
        text: str,
        sender: str,
        webhook: str,
    ) -> str:
        requester = pending.get("requester_staff_id", "")
        if requester and sender != requester:
            return "只有任务发起人可以回复这个任务"

        kind = pending.get("pending_kind")
        task_id = pending["task_id"]
        approved: bool | None
        feedback: str

        if kind == "clarification":
            if not text:
                return "请直接回复补充内容"
            approved, feedback = None, text
        elif kind == "approval":
            approved, feedback = parse_approval(text)
            if approved is None:
                return "请回复「通过」，或「驳回 <原因>」"
        else:
            return "当前任务等待人工处理，但无法识别类型"

        try:
            ok, reason = await service.submit_feedback(task_id, approved, feedback)
        except Exception as exc:
            logger.error(f"DingTalk feedback failed: {exc}", extra={"node": "dingtalk"})
            return "提交失败，请稍后再试"

        if ok:
            await dingtalk_repo.update_binding(
                task_id,
                session_webhook=webhook,
                last_notified_status="queued",
                active=1,
            )
            return "已提交，任务继续执行"

        if reason == "not_waiting":
            await dingtalk_repo.clear_pending(task_id)
            return "这个任务已经不在等待状态了"
        if reason == "missing_checkpoint":
            await dingtalk_repo.clear_pending(task_id)
            return "任务 checkpoint 丢失，无法恢复"
        return "任务不存在或已被删除"
