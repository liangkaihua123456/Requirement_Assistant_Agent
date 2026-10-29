"""DingTalk 消息渲染与人工反馈解析。"""

from __future__ import annotations

from typing import Any

APPROVE_WORDS = {"通过", "批准", "同意", "approve", "approved", "yes", "是"}
REJECT_PREFIXES = ("驳回", "拒绝", "不通过")


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
    if value in APPROVE_WORDS:
        return True, ""
    for prefix in REJECT_PREFIXES:
        if value.startswith(prefix):
            return False, value[len(prefix):].strip()
    return None, ""


def render_waiting(task_id: str, kind: str, payload: Any) -> str:
    if kind == "clarification":
        lines = [f"任务 {task_id} 需要补充信息："]
        for index, question in enumerate(payload or [], 1):
            lines.append(f"{index}. {question}")
        lines.append("\n直接回复补充内容即可（仅发起人可回复）。")
        return "\n".join(lines)

    if kind == "approval":
        review = payload if isinstance(payload, dict) else {}
        score = review.get("overall_score", "?")
        summary = review.get("summary", "")
        return (
            f"任务 {task_id} 评审完成（{score}/10）。\n"
            f"{summary}\n"
            "回复「通过」，或「驳回 <原因>」。"
        )

    return f"任务 {task_id} 等待人工处理。"


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
