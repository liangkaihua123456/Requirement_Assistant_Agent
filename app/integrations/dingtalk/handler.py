"""钉钉机器人消息处理：建任务、查状态、提交澄清/审批，并解析 PDF 附件。

机器人1提出等待确认的问题；机器人2可自动生成补充/纠错建议，
但仍需发起人确认后才会提交。两个机器人都可接收 @ 消息并建任务。

注意：钉钉官方限制——群聊 @ 机器人通常收不到独立发送的文件消息。
因此支持：
1) 单聊直接发 PDF；
2) 消息中的 PDF 链接；
3) 会话缓存的近期文档；
4) 可选 arXiv 回退检索。
"""

from __future__ import annotations

import re
from typing import Any

import httpx
import dingtalk_stream
from dingtalk_stream import AckMessage

from app.core.config import get_settings
from app.core.logger import logger
from app.integrations.dingtalk import service
from app.integrations.dingtalk.assist import correct_human_reply
from app.integrations.dingtalk.client import post_text
from app.integrations.dingtalk.documents import (
    compose_user_input,
    extract_pdf_names,
    extract_urls,
    find_docs_for_query,
    load_docs,
    looks_like_document_question,
    save_doc,
)
from app.integrations.dingtalk.files import (
    fetch_arxiv_pdf_by_query,
    ingest_dingtalk_file,
    ingest_url_pdf,
    parse_inbound_files,
)
from app.integrations.dingtalk.group_files import (
    fetch_group_file_text,
    permission_hint_from_error,
)
from app.integrations.dingtalk.pending_payload import (
    unwrap_pending_payload,
    with_assist_draft,
)
from app.integrations.dingtalk.render import (
    parse_approval,
    parse_confirm_or_modify,
    render_assist_correction,
    render_task_summary,
)
from app.storage import dingtalk as dingtalk_repo

STATUS_WORDS = {"状态", "status"}
_AT_PREFIX = re.compile(r"^(?:@\S+\s*)+")


def _normalize_text(value: str) -> str:
    return "".join((value or "").split()).lower()


def _clean_user_text(value: str) -> str:
    """去掉开头的 @机器人 提及，避免写入任务原文。"""
    return _AT_PREFIX.sub("", (value or "").strip()).strip()


class DingTalkHandler(dingtalk_stream.ChatbotHandler):
    """把钉钉群消息翻译成任务操作。"""

    def __init__(self, http: httpx.AsyncClient, robot_role: str = "robot2"):
        super().__init__()
        self.http = http
        self.robot_role = robot_role

    async def process(self, callback: dingtalk_stream.CallbackMessage):
        raw = callback.data if isinstance(callback.data, dict) else {}
        msg = dingtalk_stream.ChatbotMessage.from_dict(raw)
        msg_id = msg.message_id or raw.get("msgId") or ""
        conversation_id = (
            msg.conversation_id or raw.get("conversationId") or msg.sender_staff_id or ""
        )
        raw_text = ""
        if msg.text and msg.text.content:
            raw_text = msg.text.content.strip()
        elif msg.message_type == "richText" and msg.rich_text_content:
            raw_text = " ".join(msg.get_text_list() or []).strip()
        logger.info(
            f"DingTalk inbound via {self.robot_role}: "
            f"msg_id={msg_id} type={raw.get('msgtype')} "
            f"conversation_id={conversation_id} text={raw_text[:80]}",
            extra={"node": "dingtalk"},
        )
        if not msg_id or not conversation_id:
            return AckMessage.STATUS_OK, "OK"

        # 钉钉可能重推；msg_id 是全局唯一键，先原子占用
        if not await dingtalk_repo.claim_message(msg_id, conversation_id):
            logger.info("DingTalk duplicate msg_id skipped", extra={"node": "dingtalk"})
            return AckMessage.STATUS_OK, "OK"

        text = _clean_user_text(raw_text)
        sender = msg.sender_staff_id or raw.get("senderStaffId") or ""
        webhook = msg.session_webhook or raw.get("sessionWebhook") or ""
        robot_code = msg.robot_code or raw.get("robotCode") or ""

        async with service.conversation_lock(conversation_id):
            # 先消化本条消息里的附件/链接
            ingested, ingest_notes = await self._ingest_attachments(
                conversation_id=conversation_id,
                raw=raw,
                text=text,
                robot_code=robot_code,
            )

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
            elif not text and ingested:
                names = "、".join(d["filename"] for d in ingested)
                reply = (
                    f"已接收并解析文档：{names}。请继续提问，例如："
                    f"「解释一下这篇论文主要做什么」"
                )
            elif not text:
                reply = "请描述你的需求；若要解读 PDF，请先单聊发送文件或附上 PDF 链接"
            else:
                reply = await self._create_task_with_docs(
                    conversation_id=conversation_id,
                    text=text,
                    sender=sender,
                    webhook=webhook,
                    robot_code=robot_code,
                    ingest_notes=ingest_notes,
                )

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

    async def _ingest_attachments(
        self,
        *,
        conversation_id: str,
        raw: dict[str, Any],
        text: str,
        robot_code: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        settings = get_settings()
        ingested: list[dict[str, Any]] = []
        notes: list[str] = []

        for item in parse_inbound_files(raw):
            try:
                filename, body = await ingest_dingtalk_file(
                    self.http,
                    download_code=item["download_code"],
                    filename=item["filename"],
                    robot_code=robot_code,
                    settings=settings,
                )
                if body:
                    doc = save_doc(
                        conversation_id,
                        filename=filename,
                        text=body,
                        source="dingtalk_file",
                    )
                    ingested.append(doc)
                    notes.append(f"已解析钉钉附件《{filename}》（{doc['chars']} 字）")
                else:
                    notes.append(f"附件《{filename}》未能提取到文本")
            except Exception as exc:
                logger.warning(
                    f"DingTalk file ingest failed: {exc}", extra={"node": "dingtalk"}
                )
                notes.append(f"附件下载/解析失败：{exc}")

        for url in extract_urls(text):
            if ".pdf" not in url.lower() and "arxiv.org" not in url.lower():
                continue
            try:
                filename, body = await ingest_url_pdf(self.http, url, settings=settings)
                if body:
                    doc = save_doc(
                        conversation_id,
                        filename=filename,
                        text=body,
                        source=f"url:{url}",
                    )
                    ingested.append(doc)
                    notes.append(f"已解析链接 PDF《{filename}》（{doc['chars']} 字）")
            except Exception as exc:
                logger.warning(
                    f"URL pdf ingest failed: {exc}", extra={"node": "dingtalk"}
                )
                notes.append(f"链接 PDF 解析失败：{url}")

        return ingested, notes

    async def _resolve_docs_for_question(
        self,
        conversation_id: str,
        text: str,
        *,
        webhook: str = "",
        sender: str = "",
        robot_code: str = "",
    ) -> tuple[list[dict[str, Any]], list[str]]:
        settings = get_settings()
        notes: list[str] = []
        docs = find_docs_for_query(conversation_id, text)
        if docs:
            return docs, notes

        if not looks_like_document_question(text):
            return [], notes

        # 1) 优先读钉钉群文件（群里先发文件再 @ 提问的标准场景）
        if settings.dingtalk_group_file_enabled and sender:
            if webhook:
                try:
                    await post_text(
                        self.http,
                        webhook,
                        "正在从本群「群文件」查找并解析文档，请稍候…",
                        sender,
                    )
                except Exception:
                    pass
            try:
                fetched = await fetch_group_file_text(
                    self.http,
                    open_conversation_id=conversation_id,
                    operator_userid=sender,
                    wanted_names=extract_pdf_names(text),
                    robot_code=robot_code,
                    settings=settings,
                )
            except Exception as exc:
                fetched = None
                hint = permission_hint_from_error(exc)
                notes.append(hint)
                logger.warning(
                    f"group file fetch failed: {exc}", extra={"node": "dingtalk"}
                )
            if fetched:
                filename, body = fetched
                doc = save_doc(
                    conversation_id,
                    filename=filename,
                    text=body,
                    source="dingtalk_group_file",
                )
                notes.append(f"已从群文件读取并解析《{filename}》（{doc['chars']} 字）")
                return [doc], notes

        # 2) 可选：公开论文 arXiv 回退
        if settings.dingtalk_doc_arxiv_fallback:
            if webhook:
                try:
                    await post_text(
                        self.http,
                        webhook,
                        "群文件暂未命中，正在尝试公开论文源检索，请稍候…",
                        sender,
                    )
                except Exception:
                    pass
            try:
                fetched = await fetch_arxiv_pdf_by_query(
                    self.http, text, settings=settings
                )
            except Exception as exc:
                fetched = None
                logger.warning(f"arXiv fallback error: {exc}", extra={"node": "dingtalk"})
            if fetched:
                filename, body = fetched
                doc = save_doc(
                    conversation_id,
                    filename=filename,
                    text=body,
                    source="arxiv",
                )
                notes.append(f"已从 arXiv 检索并解析《{filename}》")
                return [doc], notes
        return [], notes

    async def _create_task_with_docs(
        self,
        *,
        conversation_id: str,
        text: str,
        sender: str,
        webhook: str,
        robot_code: str,
        ingest_notes: list[str],
    ) -> str:
        docs, resolve_notes = await self._resolve_docs_for_question(
            conversation_id,
            text,
            webhook=webhook,
            sender=sender,
            robot_code=robot_code,
        )
        notes = ingest_notes + resolve_notes

        if looks_like_document_question(text) and not docs:
            names = "、".join(extract_pdf_names(text)) or "PDF"
            cached = load_docs(conversation_id)
            tip_lines = [
                "我还没有拿到可阅读的论文正文，因此不能只凭文件名作答。",
                f"你提到了：{names}",
            ]
            tip_lines.extend(notes[:2])
            tip_lines.extend(
                [
                    "请检查：",
                    "1) 文件是否已出现在本群「群文件」中；",
                    "2) 机器人应用是否已开通群文件/企业存储读与下载权限并发布；",
                    "3) 或改为单聊发送 PDF / 粘贴 PDF 链接后重试。",
                ]
            )
            if cached:
                tip_lines.append(
                    f"（当前会话缓存文档 {len(cached)} 份，但未匹配到本次提问）"
                )
            return "\n".join(tip_lines)

        user_input = compose_user_input(text, docs) if docs else text
        task_id, error = await service.create_task_from_dingtalk(
            conversation_id=conversation_id,
            text=user_input,
            requester_staff_id=sender,
            session_webhook=webhook,
        )
        if task_id:
            prefix = "；".join(notes[:2])
            if docs:
                return (
                    (prefix + "。\n" if prefix else "")
                    + f"已基于文档正文受理：{task_id}"
                )
            return f"已受理：{task_id}"
        if error == "busy":
            return "当前会话已有进行中的任务，请等待完成"
        return "创建任务失败，请稍后再试"

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
            _, draft, _ = unwrap_pending_payload(pending.get("pending_payload"))
            reply += "\n等待你回复澄清/审批内容"
            if draft:
                reply += "\n机器人2已给出建议，可回复「确认」采用"
        docs = load_docs(conversation_id)
        if docs:
            reply += f"\n会话已缓存文档：{'、'.join(d.get('filename','') for d in docs[:3])}"
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
        raw_payload = pending.get("pending_payload")
        data, assist_draft, _ = unwrap_pending_payload(raw_payload)

        if kind not in {"clarification", "approval"}:
            return "当前任务等待人工处理，但无法识别类型"

        action, modify_content = parse_confirm_or_modify(text)
        if action == "confirm":
            if not assist_draft:
                return "当前没有待确认的机器人2建议，请直接回复内容"
            return await self._submit_feedback(
                pending, kind, assist_draft, webhook
            )
        if action == "modify":
            if not modify_content:
                return "请在「修改」后写上要提交的内容"
            return await self._submit_feedback(
                pending, kind, modify_content, webhook
            )

        if kind == "clarification":
            if not text:
                return "请直接回复补充内容"
            settings = get_settings()
            if settings.dingtalk_assist_enabled and settings.dingtalk_assist_correct_reply:
                task = await service.get_task(task_id)
                if task is not None:
                    corrected, rationale = await correct_human_reply(
                        kind, data, task, text
                    )
                    if corrected and _normalize_text(corrected) != _normalize_text(text):
                        await dingtalk_repo.update_binding(
                            task_id,
                            pending_payload=with_assist_draft(
                                raw_payload, corrected, rationale
                            ),
                            session_webhook=webhook,
                        )
                        return render_assist_correction(task_id, corrected, rationale)
            return await self._submit_feedback(pending, kind, text, webhook)

        approved, feedback = parse_approval(text)
        if approved is None:
            return (
                "请回复「通过」或「驳回 <原因>」；"
                "若采用机器人2建议，回复「确认」或「修改 <内容>」"
            )
        return await self._submit_feedback(
            pending,
            kind,
            text if approved is False else (feedback and f"通过\n{feedback}" or "通过"),
            webhook,
            approved=approved,
            feedback=feedback,
        )

    async def _submit_feedback(
        self,
        pending: dict,
        kind: str,
        text: str,
        webhook: str,
        approved: bool | None = None,
        feedback: str | None = None,
    ) -> str:
        task_id = pending["task_id"]
        if kind == "clarification":
            submit_approved, submit_feedback = None, text
        elif approved is not None:
            submit_approved, submit_feedback = approved, feedback or ""
        else:
            submit_approved, submit_feedback = parse_approval(text)
            if submit_approved is None:
                return "建议内容无法识别为「通过」或「驳回 <原因>」，请「修改」后再确认"

        try:
            ok, reason = await service.submit_feedback(
                task_id, submit_approved, submit_feedback
            )
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
