"""后台轮询任务状态，把 waiting/completed/error 推回钉钉。"""

from __future__ import annotations

import asyncio

import httpx

from app.core.config import get_settings
from app.core.logger import logger
from app.integrations.dingtalk import service
from app.integrations.dingtalk.client import post_text
from app.integrations.dingtalk.render import (
    classify_waiting,
    render_task_status,
    render_waiting,
)
from app.storage import dingtalk as dingtalk_repo


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

                    # 人工已通过 REST 或其他途径处理过，pending 需要清掉
                    if binding.get("pending_kind") and status != "waiting_human":
                        await dingtalk_repo.clear_pending(task_id)
                        binding["pending_kind"] = ""

                    if status == "waiting_human":
                        if binding.get("pending_kind"):
                            continue  # 已经发过问题，等用户回复
                        kind, payload = classify_waiting(task.get("state_snapshot") or {})
                        await dingtalk_repo.set_pending(
                            task_id, kind, payload, webhook
                        )
                        if webhook:
                            try:
                                await post_text(
                                    http,
                                    webhook,
                                    render_waiting(task_id, kind, payload),
                                    binding.get("requester_staff_id"),
                                )
                            except Exception:
                                # 发送失败就清掉 pending，下一轮重试，避免永久卡住
                                await dingtalk_repo.clear_pending(task_id)
                                raise
                        else:
                            logger.warning(
                                "DingTalk binding has no sessionWebhook",
                                extra={"node": "dingtalk", "task_id": task_id},
                            )
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
