"""机器人2：调用模型生成澄清/审批建议，并纠正明显错误。

建议不会自动提交，必须由发起人确认（或自行修改后提交）。
"""

from __future__ import annotations

import json
import re
from typing import Any

from json_repair import repair_json
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm import get_llm
from app.core.logger import logger

_SYSTEM = """你是钉钉群里的「机器人2」协作助手。
「机器人1」已经向用户提出了澄清问题或评审确认请求。
你的职责：
1. 根据原始需求与当前任务上下文，给出可直接采用的回复草稿；
2. 纠正需求理解或表述中的明显矛盾、遗漏与错误；
3. 不要编造用户未提及且无法合理推断的硬性约束。

必须只输出一个 JSON 对象，字段：
- draft: string，可直接作为用户回复提交的正文
- rationale: string，简要说明补充点与纠错点（一两句）
"""


def _task_context(task: dict[str, Any]) -> str:
    snapshot = task.get("state_snapshot") or {}
    clarified = snapshot.get("clarified_requirement") or {}
    review = snapshot.get("review_result") or {}
    parts = [
        f"原始需求：{task.get('user_input') or snapshot.get('user_input') or ''}",
        f"当前节点：{task.get('current_node') or ''}",
    ]
    if clarified:
        parts.append(
            "已澄清摘要："
            + json.dumps(clarified, ensure_ascii=False)[:2500]
        )
    if review:
        parts.append(
            "评审结果：" + json.dumps(review, ensure_ascii=False)[:2500]
        )
    return "\n".join(parts)


def _build_user_prompt(kind: str, payload: Any, task: dict[str, Any]) -> str:
    context = _task_context(task)
    if kind == "clarification":
        questions = payload if isinstance(payload, list) else [str(payload)]
        numbered = "\n".join(
            f"{index}. {question}" for index, question in enumerate(questions, 1)
        )
        return (
            f"{context}\n\n"
            f"机器人1提出的澄清问题：\n{numbered}\n\n"
            "请生成补充回复草稿：逐条回答上述问题；"
            "对需求中含糊或错误处给出合理纠正；"
            "draft 应为用户可直接发送的完整文本。"
        )

    review = payload if isinstance(payload, dict) else {}
    return (
        f"{context}\n\n"
        f"机器人1的评审确认请求，评审摘要：\n"
        f"{json.dumps(review, ensure_ascii=False)[:2500]}\n\n"
        "请生成审批建议草稿：draft 第一行必须是「通过」或「驳回 <原因>」；"
        "若建议驳回，原因要具体可执行；若建议通过，可简短说明理由。"
    )


def _parse_assist_json(content: str) -> tuple[str, str]:
    text = (content or "").strip()
    if not text:
        return "", ""

    candidate = text
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fenced:
        candidate = fenced.group(1).strip()

    try:
        repaired = repair_json(candidate)
        data = json.loads(repaired) if isinstance(repaired, str) else repaired
    except Exception:
        return text, ""

    if not isinstance(data, dict):
        return text, ""
    draft = str(data.get("draft") or "").strip()
    rationale = str(data.get("rationale") or "").strip()
    return draft, rationale


async def generate_assist_draft(
    kind: str,
    payload: Any,
    task: dict[str, Any],
) -> tuple[str, str]:
    """返回 (draft, rationale)；失败时返回空字符串。"""
    if kind not in {"clarification", "approval"}:
        return "", ""

    try:
        llm = get_llm(temperature=0.2)
        response = await llm.ainvoke(
            [
                SystemMessage(content=_SYSTEM),
                HumanMessage(content=_build_user_prompt(kind, payload, task)),
            ]
        )
        draft, rationale = _parse_assist_json(
            getattr(response, "content", "") or ""
        )
        if kind == "approval" and draft:
            first = draft.splitlines()[0].strip()
            if not (
                first in {"通过", "批准", "同意"}
                or first.startswith(("驳回", "拒绝", "不通过"))
            ):
                # 模型未按格式输出时，兜底包一层，避免确认后无法解析
                draft = f"驳回 {draft}" if "驳回" in draft else f"通过\n{draft}"
        return draft, rationale
    except Exception as exc:
        logger.warning(
            f"DingTalk assist draft failed: {exc}",
            extra={"node": "dingtalk", "task_id": task.get("task_id", "")},
        )
        return "", ""


async def correct_human_reply(
    kind: str,
    payload: Any,
    task: dict[str, Any],
    human_text: str,
) -> tuple[str, str]:
    """纠正人工回复中的明显错误，返回 (corrected, rationale)。

    若无需纠正，corrected 应尽量保持原意；调用方可比较文本决定是否再确认。
    """
    text = (human_text or "").strip()
    if not text or kind != "clarification":
        return text, ""

    prompt = (
        f"{_task_context(task)}\n\n"
        f"机器人1的问题：\n{json.dumps(payload, ensure_ascii=False)[:1500]}\n\n"
        f"用户刚回复：\n{text}\n\n"
        "请在保留用户意图的前提下，纠正明显错误、补全遗漏、理顺表述；"
        "不要改变用户明确给出的事实。draft 为纠正后的完整回复。"
    )
    try:
        llm = get_llm(temperature=0.1)
        response = await llm.ainvoke(
            [
                SystemMessage(content=_SYSTEM),
                HumanMessage(content=prompt),
            ]
        )
        draft, rationale = _parse_assist_json(
            getattr(response, "content", "") or ""
        )
        return (draft or text), rationale
    except Exception as exc:
        logger.warning(
            f"DingTalk assist correct failed: {exc}",
            extra={"node": "dingtalk", "task_id": task.get("task_id", "")},
        )
        return text, ""
