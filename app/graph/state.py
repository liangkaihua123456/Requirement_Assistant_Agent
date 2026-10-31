"""LangGraph 共享状态定义。

状态字段按"业务产物"组织，而非绑定到单一 Agent，
以便后续插入新 Agent、并行分支或更多审批点时不需要整体推翻。

LangGraph 1.0 要求 State 使用 TypedDict + Annotated reducer。
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


def _replace(existing: Any, new: Any) -> Any:
    """替换策略：直接用新值覆盖旧值。"""
    return new


def _append_list(existing: list, new: list) -> list:
    """追加策略：将新列表追加到旧列表。"""
    return existing + new


class AgentState(TypedDict, total=False):
    """工作流共享状态。

    所有节点通过读写此状态进行数据传递。
    LangGraph 使用 Annotated 类型来决定字段的合并策略。
    """

    # ── 用户输入 ──────────────────────────────────────────────
    user_input: Annotated[str, _replace]
    normalized_input: Annotated[str, _replace]

    # ── 业务产物（以 dict 存储，便于 JSON 序列化）──────────────
    clarified_requirement: Annotated[dict, _replace]
    prd_doc: Annotated[dict, _replace]
    technical_design: Annotated[dict, _replace]
    code_scaffold: Annotated[dict, _replace]
    review_result: Annotated[dict, _replace]

    # ── 人工交互 ──────────────────────────────────────────────
    human_feedback: Annotated[str, _replace]
    needs_human_clarification: Annotated[bool, _replace]
    human_clarification_confirmed: Annotated[bool, _replace]
    human_approved: Annotated[bool, _replace]

    # ── 流程控制 ──────────────────────────────────────────────
    current_node: Annotated[str, _replace]
    next_action: Annotated[str, _replace]
    reflow_count: Annotated[int, _replace]
    max_reflow_count: Annotated[int, _replace]
    error_message: Annotated[str, _replace]

    # ── 短期记忆（任务内上下文）────────────────────────────────
    task_memory: Annotated[list[dict], _append_list]

    # ── Dialogue（多轮对话）────────────────────────────────────
    dialogue_round: Annotated[int, _replace]
    dialogue_active: Annotated[bool, _replace]
    dialogue_history: Annotated[list[dict], _append_list]
    dialogue_targets: Annotated[list[str], _replace]
    dialogue_questions: Annotated[list[dict], _replace]

    # ── Repairer ───────────────────────────────────────────────
    repair_attempted: Annotated[bool, _replace]
    repair_count: Annotated[int, _replace]

    # ── Plan-Verify ────────────────────────────────────────────
    plan_evaluation: Annotated[dict, _replace]

    # ── 预留扩展 ──────────────────────────────────────────────
    memory_hits: Annotated[list[dict], _append_list]
    execution_logs: Annotated[list[dict], _append_list]
    metadata: Annotated[dict, _replace]
    task_id: Annotated[str, _replace]
