"""Plan Evaluator Agent — 比较 Planner 产出的主方案与备选策略，选最优。

仅当 settings.plan_variants_enabled=True 且存在 alternatives 时执行比较；
否则透明透传，行为与原有流程一致。
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.llm import get_structured_llm
from app.core.logger import logger
from app.core.prompts import PLAN_EVALUATOR_SYSTEM_PROMPT, PLAN_EVALUATOR_USER_PROMPT
from app.graph.state import AgentState
from app.memory.short_term import add_entry


class _EvaluationResult(BaseModel):
    """LLM 结构化评估输出。"""

    selected_index: int = Field(0, ge=0, le=2, description="选中方案编号: 0=主方案, 1=备选1, 2=备选2")
    selected_goal: str = Field("", description="选中方案的 goal")
    reason: str = Field("", description="选择理由")
    risk_note: str = Field("", description="选中方案的主要风险点")


def plan_evaluator_node(state: AgentState) -> dict:
    """比较 Planner 产出的主方案与备选策略，选择最优方案。

    若 plan_variants_enabled=False 或无 alternatives → 透传，零开销。
    """
    settings = get_settings()
    req = state.get("clarified_requirement") or {}
    user_input = state.get("normalized_input") or state.get("user_input", "")
    alternatives = req.get("alternatives") or []

    # 无备选方案或功能未启用 → 透明透传
    if not settings.plan_variants_enabled or not alternatives:
        logger.info("Plan Evaluator 跳过（无备选方案或功能未启用）", extra={"node": "plan_evaluator"})
        return {
            "current_node": "plan_evaluator",
            "plan_evaluation": {"action": "skipped", "reason": "no_alternatives" if not alternatives else "disabled"},
            "execution_logs": [{
                "node": "plan_evaluator",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "action": "skipped",
            }],
        }

    logger.info(
        f"Plan Evaluator 开始比较 {len(alternatives) + 1} 个方案",
        extra={"node": "plan_evaluator"},
    )

    # 构建备选方案文本
    alt_lines = []
    for i, alt in enumerate(alternatives, 1):
        if not isinstance(alt, dict):
            continue
        alt_lines.append(
            f"### 备选方案 {i}\n"
            f"- 目标：{alt.get('goal', '')}\n"
            f"- 架构暗示：{alt.get('architecture_hint', '')}\n"
            f"- 核心功能：{'；'.join(alt.get('core_features', [])[:5])}\n"
            f"- 权衡说明：{alt.get('tradeoff_note', '')}\n"
        )
    alternatives_text = "\n".join(alt_lines) if alt_lines else "（无备选方案）"

    user_prompt = PLAN_EVALUATOR_USER_PROMPT.format(
        user_input=user_input[:1500],
        main_goal=req.get("goal", ""),
        main_arch=req.get("assumptions", [])[:3] if req.get("assumptions") else "未指定",
        main_features="；".join(req.get("core_features", [])[:5]),
        main_constraints="；".join(req.get("constraints", [])[:5]),
        main_priority=req.get("priority", "medium"),
        alternatives_text=alternatives_text,
    )

    try:
        structured_llm = get_structured_llm(_EvaluationResult, temperature=0.2, role="evaluator")
        result: _EvaluationResult = structured_llm.invoke([
            {"role": "system", "content": PLAN_EVALUATOR_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ])
    except Exception as exc:
        logger.warning(
            "Plan Evaluator LLM 调用失败，保留主方案",
            extra={"node": "plan_evaluator", "error": str(exc)[:200]},
        )
        return {
            "current_node": "plan_evaluator",
            "plan_evaluation": {"action": "kept_main", "reason": "llm_failed"},
            "execution_logs": [{
                "node": "plan_evaluator",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "action": "llm_failed",
                "error": str(exc)[:200],
            }],
        }

    selected_index = result.selected_index
    reason = result.reason
    risk_note = result.risk_note

    # 若选中备选方案，将其提升为主方案
    new_req = deepcopy(req)
    new_req.pop("alternatives", None)

    if selected_index > 0 and selected_index <= len(alternatives):
        alt = alternatives[selected_index - 1]
        if isinstance(alt, dict):
            new_req["goal"] = alt.get("goal", new_req.get("goal", ""))
            alt_features = alt.get("core_features") or []
            if alt_features:
                new_req["core_features"] = alt_features
            # 将原有主方案信息也保留为参考
            new_req["_original_plan"] = {
                "goal": req.get("goal", ""),
                "core_features": req.get("core_features", []),
            }
            logger.info(
                f"Plan Evaluator 选中备选方案 #{selected_index}: {alt.get('goal', '')[:60]}",
                extra={"node": "plan_evaluator"},
            )
    else:
        logger.info(
            f"Plan Evaluator 保留主方案: {reason[:80]}",
            extra={"node": "plan_evaluator"},
        )

    task_mem = add_entry(
        state, "plan_evaluator",
        summary=f"比较 {len(alternatives) + 1} 个方案，选中: {new_req.get('goal', '')[:60]}",
        key_decisions=[reason],
        metrics={"total_variants": len(alternatives) + 1, "selected_index": selected_index},
        warnings=[risk_note] if risk_note else [],
    )

    return {
        "clarified_requirement": new_req,
        "plan_evaluation": {
            "action": "evaluated",
            "total_variants": len(alternatives) + 1,
            "selected_index": selected_index,
            "reason": reason,
            "risk_note": risk_note,
        },
        "current_node": "plan_evaluator",
        **task_mem,
        "execution_logs": [{
            "node": "plan_evaluator",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "evaluated",
            "selected_index": selected_index,
        }],
    }
