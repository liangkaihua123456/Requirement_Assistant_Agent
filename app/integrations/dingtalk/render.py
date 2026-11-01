"""DingTalk 消息渲染与人工反馈解析。"""

from __future__ import annotations

from typing import Any

from app.integrations.dingtalk.pending_payload import unwrap_pending_payload

APPROVE_WORDS = {"通过", "批准", "同意", "approve", "approved", "yes", "是"}
REJECT_PREFIXES = ("驳回", "拒绝", "不通过")
CONFIRM_WORDS = {"确认", "采用", "同意建议", "用建议", "confirm", "ok"}
MODIFY_PREFIXES = ("修改", "更正", "改为")


def classify_waiting(snapshot: dict[str, Any]) -> tuple[str, Any]:
    """判断 waiting_human 是澄清还是审批，返回 (kind, payload)。

    后端当前把 LangGraph Interrupt 序列化成了 repr 字符串，
    所以优先使用结构化的 review_result / open_questions。
    """
    review = snapshot.get("review_result") or {}
    if review and ("passed" in review or "overall_score" in review):
        return "approval", review

    questions = (snapshot.get("clarified_requirement") or {}).get("open_questions") or []
    if questions:
        return "clarification", questions

    interrupt = str(snapshot.get("interrupt_info") or "")
    if "'type': 'approval'" in interrupt or '"type": "approval"' in interrupt:
        return "approval", review
    if "'type': 'clarification'" in interrupt or '"type": "clarification"' in interrupt:
        return "clarification", questions

    return "unknown", None


def parse_approval(text: str) -> tuple[bool | None, str]:
    """返回 (approved, feedback)；None 表示无法识别。"""
    value = text.strip()
    # 允许「通过\n理由」这类多行建议草稿
    first = value.splitlines()[0].strip() if value else ""
    if first in APPROVE_WORDS or value in APPROVE_WORDS:
        feedback = "\n".join(value.splitlines()[1:]).strip() if first in APPROVE_WORDS else ""
        return True, feedback
    for prefix in REJECT_PREFIXES:
        if first.startswith(prefix) or value.startswith(prefix):
            source = first if first.startswith(prefix) else value
            return False, source[len(prefix):].strip()
    return None, ""


def parse_confirm_or_modify(text: str) -> tuple[str | None, str]:
    """解析机器人2建议的确认/修改指令。

    返回 (action, content)：
    - ("confirm", "") 采用当前建议
    - ("modify", content) 用修改后的内容提交
    - (None, "") 未识别
    """
    value = text.strip()
    if not value:
        return None, ""
    if value.lower() in CONFIRM_WORDS or value in CONFIRM_WORDS:
        return "confirm", ""
    for prefix in MODIFY_PREFIXES:
        if value.startswith(prefix):
            return "modify", value[len(prefix):].strip()
    return None, ""


def pending_question_payload(raw: Any) -> Any:
    """从 pending_payload 取出机器人1的问题/评审数据。"""
    data, _, _ = unwrap_pending_payload(raw)
    return data


def render_waiting(task_id: str, kind: str, payload: Any) -> str:
    data = pending_question_payload(payload)
    if kind == "clarification":
        lines = [f"【机器人1】任务 {task_id} 需要补充信息："]
        for index, question in enumerate(data or [], 1):
            lines.append(f"{index}. {question}")
        lines.append(
            "\n可直接回复补充内容；若已有机器人2建议，也可回复「确认」采用，"
            "或「修改 <内容>」（仅发起人可回复）。"
        )
        return "\n".join(lines)

    if kind == "approval":
        review = data if isinstance(data, dict) else {}
        score = review.get("overall_score", "?")
        summary = review.get("summary", "")
        return (
            f"【机器人1】任务 {task_id} 评审完成（{score}/10）。\n"
            f"{summary}\n"
            "回复「通过」或「驳回 <原因>」；"
            "若已有机器人2建议，也可回复「确认」采用，或「修改 <内容>」。"
        )

    return f"任务 {task_id} 等待人工处理。"


def render_assist_draft(
    task_id: str,
    kind: str,
    draft: str,
    rationale: str = "",
) -> str:
    title = "澄清建议" if kind == "clarification" else "审批建议"
    lines = [
        f"【机器人2】任务 {task_id} 的{title}（需人工确认后才会提交）：",
        draft.strip(),
    ]
    if rationale.strip():
        lines.append(f"\n说明：{rationale.strip()}")
    lines.append(
        "\n回复「确认」采用上述建议；「修改 <内容>」按你的版本提交；"
        "也可直接按原方式回复。"
    )
    return "\n".join(lines)


def render_assist_correction(task_id: str, draft: str, rationale: str = "") -> str:
    lines = [
        f"【机器人2】已对你的回复做了纠错/补全（任务 {task_id}），请确认：",
        draft.strip(),
    ]
    if rationale.strip():
        lines.append(f"\n说明：{rationale.strip()}")
    lines.append(
        "\n回复「确认」提交纠正后的版本；「修改 <内容>」用你的最终版本；"
        "继续直接发送文本将再次尝试纠错。"
    )
    return "\n".join(lines)


def render_task_status(task: dict[str, Any]) -> str:
    task_id = task.get("task_id", "")
    status = task.get("status", "")
    snapshot = task.get("state_snapshot") or {}

    if status == "completed":
        product = (snapshot.get("prd_doc") or {}).get("product_name")
        return f"任务 {task_id} 已完成" + (f"：{product}" if product else "")
    if status == "error":
        message = (snapshot.get("error_message") or "未知错误").strip()
        return f"任务 {task_id} 失败：{message}"
    return f"任务 {task_id} 状态：{status}"


def render_task_summary(task: dict[str, Any]) -> str:
    snapshot = task.get("state_snapshot") or {}
    review = snapshot.get("review_result") or {}
    parts = [f"任务 {task.get('task_id', '')} 状态：{task.get('status', '')}"]
    if review:
        parts.append(f"评审得分：{review.get('overall_score', '?')}/10")
    return "\n".join(parts)
