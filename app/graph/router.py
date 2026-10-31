"""LangGraph 条件路由逻辑。

负责工作流中各分支条件判断，适配 LangGraph 1.0 API。
路由函数接收 state (TypedDict) 并返回目标节点名称字符串。
"""

from __future__ import annotations

from typing import Literal, Union

from app.core.config import get_settings
from app.graph.state import AgentState


def route_entry(
    state: AgentState,
) -> Literal["input_normalize", "engineer", "repairer", "reviewer", "solution"]:
    """图入口：支持二次优化与失败重试，跳过已经完成的阶段。

    二次优化带原设计时走 repairer；失败重试按失败节点续跑。
    """
    metadata = state.get("metadata") or {}

    if metadata.get("retry"):
        failed = str(metadata.get("failed_node") or "")
        if failed == "reviewer" and state.get("technical_design"):
            return "reviewer"
        if failed in ("engineer", "repairer") or (failed == "reviewer" and not state.get("technical_design")):
            return "repairer" if state.get("technical_design") else "engineer"
        return "input_normalize"

    if metadata.get("reoptimize") and state.get("prd_doc"):
        if state.get("technical_design") and metadata.get("reoptimize_mode", "repair") == "repair":
            return "repairer"
        return "engineer"
    return "input_normalize"


def route_after_planner(
    state: AgentState,
) -> Literal["human_clarification", "solution"]:
    """Planner 之后的路由判断。

    若需要人工澄清 -> human_clarification
    否则 -> solution
    """
    if state.get("needs_human_clarification", False):
        return "human_clarification"
    return "solution"


def route_after_reviewer(
    state: AgentState,
) -> Literal["human_approval", "solution", "engineer", "repairer", "dialogue_reviewer"]:
    """Reviewer 之后的路由判断。

    - 评审通过 -> human_approval
    - Dialogue 模式启用且未通过 -> dialogue_reviewer
    - 回流次数超限 -> human_approval（转交人工决策）
    - PRD 缺失 -> solution
    - 技术设计不完整 -> engineer
    """
    review = state.get("review_result")
    if review is None:
        return "human_approval"

    if review.get("passed", False):
        return "human_approval"

    # Dialogue 模式：评审未通过时进入多轮对话
    if _dialogue_should_continue(state):
        return "dialogue_reviewer"

    # 回流次数超限，转交人工
    reflow_count = state.get("reflow_count", 0)
    max_reflow = state.get("max_reflow_count", 2)
    if reflow_count >= max_reflow:
        return "human_approval"

    reflow_target = review.get("reflow_target", "none")
    if reflow_target == "solution":
        return "solution"
    elif reflow_target == "engineer":
        if _should_repair(state):
            return "repairer"
        return "engineer"

    return "human_approval"


MAX_REPAIR_ATTEMPTS = 2


def _should_repair(state: AgentState) -> bool:
    """Repairer runs before any full engineer rewrite, up to a fixed budget。

    定向修订比整份重写更稳定，因此连续两轮未通过都先尝试 repairer，
    额度用尽后才回退到 engineer。
    """
    settings = get_settings()
    if not settings.repairer_enabled:
        return False
    return int(state.get("repair_count") or 0) < MAX_REPAIR_ATTEMPTS


def route_after_dialogue_reviewer(
    state: AgentState,
) -> Union[Literal["dialogue_engineer", "dialogue_solution", "human_approval"], list[str]]:
    """Dialogue Reviewer 之后的路由：决定谁需要参与对话。

    - 同时有 solution 和 engineer 问题时 -> [dialogue_solution, dialogue_engineer] (并行)
    - 只有 engineer 问题 -> dialogue_engineer
    - 只有 solution 问题 -> dialogue_solution
    - 无目标 -> human_approval
    """
    targets = state.get("dialogue_targets") or []
    if not targets:
        return "human_approval"

    dialogue_round = state.get("dialogue_round", 0)
    max_rounds = get_settings().dialogue_max_rounds
    if dialogue_round > max_rounds:
        return "human_approval"

    if "solution" in targets and "engineer" in targets:
        # LangGraph supports fan-out to parallel nodes via list return
        return ["dialogue_solution", "dialogue_engineer"]
    elif "solution" in targets:
        return "dialogue_solution"
    else:
        return "dialogue_engineer"


def _dialogue_should_continue(state: AgentState) -> bool:
    """Check if dialogue mode is active and has remaining rounds."""
    settings = get_settings()
    if not settings.dialogue_enabled:
        return False
    dialogue_round = state.get("dialogue_round", 0)
    return dialogue_round < settings.dialogue_max_rounds


def route_after_human_approval(
    state: AgentState,
) -> Literal["package_output", "solution", "repairer"]:
    """人工审批之后的路由。

    - 批准 -> package_output
    - 驳回且有技术设计 -> repairer（定向修订，PRD 不变）
    - 驳回且无设计 -> solution（重做）
    """
    if state.get("human_approved", False):
        return "package_output"
    if state.get("technical_design"):
        return "repairer"
    return "solution"
