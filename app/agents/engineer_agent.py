"""Engineer Agent —— 生成技术设计、DB Schema、API 与代码骨架。

基于 PRD 文档和需求澄清结果，产出完整的技术设计方案。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from app.core.llm import get_llm_with_tools, get_structured_llm
from app.core.logger import logger
from app.core.config import get_settings
from app.core.prompts import ENGINEER_SYSTEM_PROMPT, ENGINEER_USER_PROMPT
from app.graph.state import AgentState
from app.memory.short_term import add_entry, format_for_prompt
from app.memory.few_shot import build_few_shot_for_task
from app.memory.self_refine import build_refined_feedback, engineer_self_critique
from app.schemas.design import TechnicalDesign
from app.tools.agent_tools import ENGINEER_PREP_TOOLS
from app.storage.repo_memory import search_memory_sync
from app.tools.coverage_metrics import (
    missing_feature_mappings,
    repair_feature_mappings,
    score_api_feature_coverage,
    score_db_feature_coverage,
    score_prd_tech_coverage,
)


def engineer_node(state: AgentState) -> dict:
    """Engineer 节点：基于 PRD 生成技术设计方案。"""
    logger.info("Engineer Agent 开始执行", extra={"node": "engineer"})

    prd_doc = state.get("prd_doc", {})
    clarified_req = state.get("clarified_requirement", {})
    review_result = state.get("review_result")
    metadata = state.get("metadata", {}) or {}

    extra_context = ""
    if review_result and not review_result.get("passed", False):
        issues = [
            i for i in review_result.get("issues", [])
            if i.get("target") == "engineer"
        ]
        suggestions = review_result.get("suggestions", [])
        if suggestions or issues:
            extra_context += "评审修订建议：\n"
            for s in suggestions:
                extra_context += f"- {s}\n"
            for issue in issues:
                extra_context += f"- [{issue.get('severity')}] {issue.get('description')}: {issue.get('suggestion')}\n"

    # Tool calling 预热阶段：让 LLM 主动决定是否检索 memory，而非每次强制注入
    # memory_enabled 时才启用，否则跳过，memory_context 保持空字符串
    memory_hits: list[dict] = []
    memory_context = ""
    if _memory_enabled(metadata):
        memory_context, memory_hits = _run_tool_calling_phase(
            prd_doc, clarified_req, extra_context
        )

    structured_llm = get_structured_llm(TechnicalDesign)

    task_memory_text = format_for_prompt(
        state.get("task_memory"),
        max_chars=get_settings().short_term_memory_max_chars,
    )

    few_shot_text = build_few_shot_for_task(prd_doc, clarified_req)

    messages = [
        SystemMessage(content=ENGINEER_SYSTEM_PROMPT),
        HumanMessage(
            content=ENGINEER_USER_PROMPT.format(
                prd_doc=json.dumps(prd_doc, ensure_ascii=False, indent=2),
                clarified_requirement=json.dumps(clarified_req, ensure_ascii=False, indent=2),
                extra_context=extra_context,
                few_shot_examples=few_shot_text,
                task_memory=task_memory_text,
                memory_context=memory_context,
            )
        ),
    ]

    # ReAct 循环：最多 3 轮，每轮检查覆盖率，不达标则反馈给 LLM 要求补充
    _COVERAGE_THRESHOLD = 0.8
    _MAX_REACT_ITERATIONS = 3
    result_dict: dict = {}
    react_iterations = 0

    compact_retry_used = False
    for react_iterations in range(1, _MAX_REACT_ITERATIONS + 1):
        result: TechnicalDesign | None = structured_llm.invoke(messages)
        if result is None:
            logger.error("Engineer structured_llm returned None after continuation")
            if not compact_retry_used:
                compact_retry_used = True
                # Start a fresh transcript — appending to the failed long
                # continuation chat usually reproduces the same overflow.
                compact_messages = [
                    SystemMessage(
                        content=(
                            ENGINEER_SYSTEM_PROMPT
                            + "\n\n【强制精简】必须一次输出完整可解析 JSON。"
                            "api≤10、tables≤6、services≤6、key_files≤5；"
                            "skeleton 每项≤8 行；relationships/indexes/dependencies "
                            "一律为字符串数组。"
                        )
                    ),
                    HumanMessage(
                        content=(
                            "上次输出过长或类型不合法。请基于以下材料重新输出精简技术设计 JSON：\n"
                            f"PRD：{json.dumps(prd_doc, ensure_ascii=False)}\n"
                            f"澄清：{json.dumps(clarified_req, ensure_ascii=False)}\n"
                            f"{extra_context}\n"
                            "只输出 JSON，不要 Markdown。"
                        )
                    ),
                ]
                logger.info("Engineer 使用全新精简对话重试结构化输出", extra={"node": "engineer"})
                result = structured_llm.invoke(compact_messages)
            if result is None:
                if react_iterations == 1:
                    raise RuntimeError("工程节点在达到输出上限并续写后，仍没有得到可解析的技术设计")
                break
        result_dict = result.model_dump()

        api_coverage = score_api_feature_coverage(prd_doc, result_dict)
        db_coverage = score_db_feature_coverage(prd_doc, result_dict)

        logger.info(
            f"Engineer ReAct 第 {react_iterations} 轮",
            extra={
                "node": "engineer",
                "api_coverage": round(api_coverage, 3),
                "db_coverage": round(db_coverage, 3),
            },
        )

        if api_coverage >= _COVERAGE_THRESHOLD and db_coverage >= _COVERAGE_THRESHOLD:
            break  # 覆盖率达标，退出循环

        if react_iterations == _MAX_REACT_ITERATIONS:
            break  # 达到上限，不再追加反馈消息

        # 把覆盖率问题反馈给 LLM
        missing = missing_feature_mappings(prd_doc, result_dict)
        coverage_info = (
            f"当前 API 覆盖率 {api_coverage:.0%}，DB 覆盖率 {db_coverage:.0%}，未达到 {_COVERAGE_THRESHOLD:.0%} 要求。"
        )

        # A self-critique adds a second model call. Only use it when the
        # coverage analysis found an actionable API or database gap.
        if get_settings().self_refine_enabled and (missing["api"] or missing["db"]):
            critique = engineer_self_critique(
                design_json=json.dumps(result_dict, ensure_ascii=False),
                prd_json=json.dumps(prd_doc, ensure_ascii=False),
                missing_api=missing["api"],
                missing_db=missing["db"],
                few_shot_text=few_shot_text,
            )
            missing_lines = []
            if missing["api"]:
                missing_lines.append(f"缺少 API 的模块：{', '.join(missing['api'])}")
            if missing["db"]:
                missing_lines.append(f"缺少 DB 表的模块：{', '.join(missing['db'])}")
            feedback = build_refined_feedback(
                self_critique=critique,
                coverage_info=coverage_info,
                missing_modules="\n".join(missing_lines),
            )
        else:
            feedback_lines = [
                coverage_info,
                "请补充以下功能模块的 API 端点和数据库表设计：",
            ]
            if missing["api"]:
                feedback_lines.append(f"缺少 API 的模块：{', '.join(missing['api'])}")
            if missing["db"]:
                feedback_lines.append(f"缺少 DB 表的模块：{', '.join(missing['db'])}")
            feedback_lines.append("请在原有设计基础上补充，保持其他内容不变，重新输出完整的技术设计。")
            feedback = "\n".join(feedback_lines)

        messages.append(HumanMessage(content=feedback))

    raw_prd_tech_coverage = score_prd_tech_coverage(prd_doc, result_dict)
    raw_api_coverage = score_api_feature_coverage(prd_doc, result_dict)
    raw_db_coverage = score_db_feature_coverage(prd_doc, result_dict)
    result_dict, coverage_repair = repair_feature_mappings(prd_doc, result_dict)
    code_scaffold = result_dict.get("code_scaffold", result.code_scaffold.model_dump())
    api_count = len(result_dict.get("api_endpoints") or [])
    table_count = len((result_dict.get("db_schema") or {}).get("tables") or [])

    logger.info(
        "Engineer Agent 执行完成",
        extra={
            "node": "engineer",
            "api_count": api_count,
            "table_count": table_count,
            "react_iterations": react_iterations,
            "coverage_repair_api_count": len(coverage_repair["api"]),
            "coverage_repair_db_count": len(coverage_repair["db"]),
        },
    )

    warnings_list: list[str] = []
    if missing := coverage_repair.get("api") or []:
        warnings_list.append(f"修复了 {len(missing)} 个 API 覆盖率缺口")
    if missing := coverage_repair.get("db") or []:
        warnings_list.append(f"修复了 {len(missing)} 个 DB 覆盖率缺口")
    if react_iterations > 1:
        warnings_list.append(f"经过 {react_iterations} 轮 ReAct 才达标")

    task_mem = add_entry(
        state, "engineer",
        summary=f"设计了 {api_count} 个 API 端点、{table_count} 张 DB 表",
        key_decisions=[
            f"架构风格={result_dict.get('architecture_style', '')}",
            f"服务数={len(result_dict.get('services') or [])}",
        ],
        metrics={
            "api_count": api_count,
            "table_count": table_count,
            "react_iterations": react_iterations,
            "api_coverage": round(raw_api_coverage, 3),
            "db_coverage": round(raw_db_coverage, 3),
        },
        warnings=warnings_list,
    )

    return {
        "technical_design": result_dict,
        **task_mem,
        "code_scaffold": code_scaffold,
        "current_node": "engineer",
        "execution_logs": [
            {
                "node": "engineer",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "api_count": api_count,
                "table_count": table_count,
                "memory_hit_count": len(memory_hits),
                "coverage_repair": coverage_repair,
            }
        ],
        "memory_hits": memory_hits,
        "metadata": {
            **metadata,
            "memory_context_used": bool(memory_context),
            "memory_hit_count": len(memory_hits),
            "react_iterations": react_iterations,
            "raw_prd_tech_coverage_rate": raw_prd_tech_coverage,
            "raw_api_feature_coverage_rate": raw_api_coverage,
            "raw_db_feature_coverage_rate": raw_db_coverage,
            "coverage_repair_applied": bool(coverage_repair["api"] or coverage_repair["db"]),
            "coverage_repair": coverage_repair,
            "self_refine_engineer": int(react_iterations > 1 and get_settings().self_refine_enabled),
            "self_refine_coverage_delta": max(
                (
                    raw_api_coverage - (float(metadata.get("raw_api_feature_coverage_rate") or 0)),
                    raw_db_coverage - (float(metadata.get("raw_db_feature_coverage_rate") or 0)),
                ),
                default=0.0,
            ),
            "retrieved_case_similarity": max(
                [float(item.get("score") or 0) for item in memory_hits],
                default=None,
            ),
        },
    }


def _memory_enabled(metadata: dict) -> bool:
    if "memory_enabled" in metadata:
        return bool(metadata.get("memory_enabled"))
    return bool(get_settings().memory_enabled)


def _run_tool_calling_phase(
    prd_doc: dict,
    clarified_req: dict,
    extra_context: str,
) -> tuple[str, list[dict]]:
    """Tool calling 预热阶段：让 LLM 主动决定调用哪些工具收集上下文。

    返回 (memory_context_str, memory_hits_list)。
    最多执行 5 轮工具调用，防止无限循环。
    """
    tool_map = {t.name: t for t in ENGINEER_PREP_TOOLS}
    llm_with_tools = get_llm_with_tools(ENGINEER_PREP_TOOLS)

    feature_names = ", ".join(
        str(m.get("name", "")) for m in (prd_doc.get("feature_modules") or [])
        if isinstance(m, dict)
    )
    prep_prompt = (
        "你是一名技术架构师，即将为以下需求生成技术设计方案。\n"
        f"产品目标：{prd_doc.get('product_goal') or clarified_req.get('goal') or ''}\n"
        f"核心功能模块：{feature_names}\n"
        "请先使用工具检索相关历史案例或架构模式，为后续设计提供参考。"
        "如果不需要额外信息，直接回复'无需检索'即可。"
    )
    messages = [HumanMessage(content=prep_prompt)]

    all_memory_hits: list[dict] = []
    context_parts: list[str] = []

    for _ in range(5):
        response = llm_with_tools.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            break

        for tc in response.tool_calls:
            tool_name = tc["name"]
            tool_args = tc["args"]
            tool_id = tc["id"]

            if tool_name not in tool_map:
                result_content = f"未知工具：{tool_name}"
            else:
                try:
                    result_content = tool_map[tool_name].invoke(tool_args)
                except Exception as exc:
                    result_content = f"工具调用失败：{exc}"

            messages.append(ToolMessage(content=result_content, tool_call_id=tool_id))

            # 收集 search_memory 的原始 hits，用于 metadata 统计
            if tool_name == "search_memory" and result_content != "未找到相关记忆。":
                context_parts.append(result_content)
                raw_hits = search_memory_sync(
                    tool_args.get("query", ""),
                    top_k=get_settings().memory_top_k,
                    memory_types=[tool_args.get("memory_type", "case")],
                )
                all_memory_hits.extend(raw_hits)

    memory_context = "\n\n".join(context_parts)
    settings = get_settings()
    if len(memory_context) > settings.memory_context_max_chars:
        memory_context = memory_context[: settings.memory_context_max_chars].rstrip() + "\n...[truncated]"

    return memory_context, all_memory_hits
