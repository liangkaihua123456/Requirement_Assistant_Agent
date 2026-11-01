"""后台轮询任务状态，把 waiting/completed/error 推回钉钉。"""

from __future__ import annotations

import asyncio

import httpx

from app.core.config import get_settings
from app.core.logger import logger
from app.integrations.dingtalk import service
from app.integrations.dingtalk.assist import generate_assist_draft
from app.integrations.dingtalk.client import (
    post_text,
    send_robot1_question,
    send_robot2_assist,
)
from app.integrations.dingtalk.pending_payload import wrap_pending_payload
from app.integrations.dingtalk.render import (
    classify_waiting,
    render_assist_draft,
    render_task_status,
    render_waiting,
)
from app.storage import dingtalk as dingtalk_repo


async def _post_robot1_or_fallback(
    http: httpx.AsyncClient,
    *,
    conversation_id: str,
    webhook: str,
    content: str,
    staff_id: str | None,
    settings,
) -> None:
    """优先以机器人1身份提问；未配置或失败时回退到 sessionWebhook。"""
    if settings.dingtalk_robot1_configured:
        try:
            sent = await send_robot1_question(
                http,
                open_conversation_id=conversation_id,
                content=content,
                settings=settings,
            )
            if sent:
                return
        except Exception as exc:
            logger.warning(
                f"Robot1 OpenAPI send failed, fallback to sessionWebhook: {exc}",
                extra={"node": "dingtalk"},
            )
    if not webhook:
        raise RuntimeError("no robot1 config and no sessionWebhook for fallback")
    await post_text(http, webhook, content, staff_id)


async def _post_robot2_assist_or_fallback(
    http: httpx.AsyncClient,
    *,
    conversation_id: str,
    webhook: str,
    content: str,
    staff_id: str | None,
    settings,
) -> None:
    """优先以机器人2 OpenAPI 发建议；失败则回退 sessionWebhook。"""
    if settings.dingtalk_robot2_configured:
        try:
            sent = await send_robot2_assist(
                http,
                open_conversation_id=conversation_id,
                content=content,
                settings=settings,
            )
            if sent:
                return
        except Exception as exc:
            logger.warning(
                f"Robot2 OpenAPI assist failed, fallback to sessionWebhook: {exc}",
                extra={"node": "dingtalk"},
            )
    if webhook:
        await post_text(http, webhook, content, staff_id)
        return
    raise RuntimeError("robot2 assist send failed and no sessionWebhook")


async def notify_loop(http: httpx.AsyncClient) -> None:
    interval = max(1.0, get_settings().dingtalk_notify_interval_seconds)
    while True:
        try:
            bindings = await dingtalk_repo.list_active_bindings()
        except Exception as exc:
            logger.warning(
                f"DingTalk binding query failed: {exc}", extra={"node": "dingtalk"}
            )
            await asyncio.sleep(interval)
            continue

        for binding in bindings:
            conversation_id = binding["conversation_id"]
            task_id = binding["task_id"]

            async with service.conversation_lock(conversation_id):
                try:
                    task = await service.get_task(task_id)
                    if task is None:
                        await dingtalk_repo.deactivate_binding(task_id, "missing")
                        continue

                    status = task.get("status", "")
                    webhook = binding.get("session_webhook", "")
                    settings = get_settings()

                    # 人工已通过 REST 或其他途径处理过，pending 需要清掉
                    if binding.get("pending_kind") and status != "waiting_human":
                        await dingtalk_repo.clear_pending(task_id)
                        binding["pending_kind"] = ""

                    if status == "waiting_human":
                        if binding.get("pending_kind"):
                            continue  # 已经发过问题，等用户回复
                        kind, payload = classify_waiting(task.get("state_snapshot") or {})

                        assist_draft = ""
                        assist_rationale = ""
                        if settings.dingtalk_assist_enabled and kind in {
                            "clarification",
                            "approval",
                        }:
                            assist_draft, assist_rationale = await generate_assist_draft(
                                kind, payload, task
                            )

                        pending_body = wrap_pending_payload(
                            payload, assist_draft, assist_rationale
                        )
                        await dingtalk_repo.set_pending(
                            task_id, kind, pending_body, webhook
                        )
                        try:
                            # 机器人1：提出问题；机器人2：给出建议（需人工确认）
                            await _post_robot1_or_fallback(
                                http,
                                conversation_id=conversation_id,
                                webhook=webhook,
                                content=render_waiting(task_id, kind, pending_body),
                                staff_id=binding.get("requester_staff_id"),
                                settings=settings,
                            )
                            if assist_draft:
                                await _post_robot2_assist_or_fallback(
                                    http,
                                    conversation_id=conversation_id,
                                    webhook=webhook,
                                    content=render_assist_draft(
                                        task_id,
                                        kind,
                                        assist_draft,
                                        assist_rationale,
                                    ),
                                    staff_id=binding.get("requester_staff_id"),
                                    settings=settings,
                                )
                        except Exception:
                            # 发送失败就清掉 pending，下一轮重试，避免永久卡住
                            await dingtalk_repo.clear_pending(task_id)
                            raise
                        continue

                    if status in {"completed", "error"}:
                        if binding.get("last_notified_status") != status:
                            if webhook:
                                await post_text(
                                    http,
                                    webhook,
                                    render_task_status(task),
                                    binding.get("requester_staff_id"),
                                )
                            await dingtalk_repo.deactivate_binding(task_id, status)
                        continue

                except Exception as exc:
                    logger.warning(
                        f"DingTalk notify failed: {exc}",
                        extra={"node": "dingtalk", "task_id": task_id},
                    )

        await asyncio.sleep(interval)
