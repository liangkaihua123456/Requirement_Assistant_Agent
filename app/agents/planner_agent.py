"""Planner Agent —— 需求澄清、任务拆解、识别缺失信息。

适配 langchain >= 1.2 / langchain-openai >= 1.1 的 with_structured_output API。
节点函数接收 AgentState (TypedDict) 并返回 dict 更新。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm import get_structured_llm
from app.core.logger import logger
from app.core.prompts import PLANNER_SYSTEM_PROMPT, PLANNER_USER_PROMPT
from app.graph.state import AgentState
from app.memory.short_term import add_entry
from app.schemas.requirement import ClarifiedRequirement


def planner_node(state: AgentState) -> dict:
    """Planner 节点：分析用户需求并输出结构化的需求澄清结果。"""
    logger.info("Planner Agent 开始执行", extra={"node": "planner"})

    user_input = state.get("normalized_input") or state.get("user_input", "")
    human_feedback = state.get("human_feedback", "")

    extra_context = ""
    if human_feedback:
        extra_context = f"用户补充说明：\n{human_feedback}"

    # 使用 with_structured_output 绑定 Pydantic Schema
    structured_llm = get_structured_llm(ClarifiedRequirement, role="planner")

    messages = [
        SystemMessage(content=PLANNER_SYSTEM_PROMPT),
        HumanMessage(
            content=PLANNER_USER_PROMPT.format(
                user_input=user_input,
                extra_context=extra_context,
            )
        ),
    ]

    result: ClarifiedRequirement = structured_llm.invoke(messages)
    if result is None:
        raise RuntimeError("需求分析节点未返回可解析结果")
    result_dict = result.model_dump()

    # 不再直接采信模型自填的 needs_clarification：模型倾向保守地列问题，
    # 导致每次任务都打断一次。只有缺少目标或核心功能不足时才真正阻断。
    needs_clarification = _resolve_clarification_need(
        result,
        user_input,
        already_confirmed=bool(state.get("human_clarification_confirmed", False)),
    )

    logger.info(
        "Planner Agent 执行完成",
        extra={
            "node": "planner",
            "needs_clarification": needs_clarification,
            "open_questions_count": len(result.open_questions),
        },
    )

    core_features = result_dict.get("core_features") or []
    feature_names = [f for f in (core_features[:5]) if isinstance(f, str)]
    feature_names += [
        f.get("name", "") for f in core_features[:5] if isinstance(f, dict)
    ]

    decisions = [f"优先级={result_dict.get('priority', 'medium')}"]
    if result_dict.get("assumptions"):
        decisions.append(f"假设={', '.join(str(a)[:50] for a in result_dict['assumptions'][:3])}")

    metrics = {
        "open_questions": len(result.open_questions),
        "core_features": len(core_features),
        "needs_clarification": needs_clarification,
    }

    task_mem = add_entry(
        state, "planner",
        summary=f"识别了 {len(core_features)} 个核心功能{'，需人工澄清' if needs_clarification else ''}",
        key_decisions=decisions,
        metrics=metrics,
        warnings=(
            [f"待澄清问题：{', '.join(str(q)[:80] for q in result.open_questions[:4])}"]
            if needs_clarification and result.open_questions else []
        ),
    )

    return {
        "clarified_requirement": result_dict,
        "needs_human_clarification": needs_clarification,
        "current_node": "planner",
        **task_mem,
        "execution_logs": [
            {
                "node": "planner",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "needs_clarification": needs_clarification,
            }
        ],
    }


def _resolve_clarification_need(
    result: ClarifiedRequirement,
    user_input: str,
    *,
    already_confirmed: bool,
) -> bool:
    """Only block on information that cannot be inferred.

    The model marks ``needs_clarification`` conservatively, so a task used to
    stop for questions even when the input already stated the goal and the core
    features. Blocking is now limited to a missing goal or too few features.
    """
    if already_confirmed:
        return False
    if not result.needs_clarification:
        return False

    goal = (result.goal or "").strip()
    features = [str(item).strip() for item in (result.core_features or []) if str(item).strip()]
    if not goal or len(features) < 3:
        return True

    # A detailed brief already states goal, features, and constraints; the
    # remaining questions can be handled as assumptions instead of blocking.
    return len(user_input.strip()) < 80
