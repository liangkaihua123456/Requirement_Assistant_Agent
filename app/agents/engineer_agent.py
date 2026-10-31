"""Engineer Agent —— 生成技术设计、DB Schema、API 与代码骨架。

基于 PRD 文档和需求澄清结果，产出完整的技术设计方案。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from app.core.llm import get_llm_with_tools, get_structured_llm
from app.core.logger import logger
from app.core.config import get_settings
from app.core.prompts import ENGINEER_SYSTEM_PROMPT, ENGINEER_USER_PROMPT
from app.graph.state import AgentState
from app.memory.short_term import add_entry, format_for_prompt
from app.memory.few_shot import build_few_shot_for_task
from app.schemas.design import TechnicalDesign
from app.tools.agent_tools import ENGINEER_PREP_TOOLS
from app.storage.repo_memory import search_memory_sync
from app.tools.coverage_metrics import (
    report_coverage_gaps,
    score_api_feature_coverage,
    score_db_feature_coverage,
    score_prd_tech_coverage,
)
from app.tools.design_patch import patch_design_gaps


def engineer_node(state: AgentState) -> dict:
    """Engineer 节点：基于 PRD 生成技术设计方案。"""
    logger.info("Engineer Agent 开始执行", extra={"node": "engineer"})

    prd_doc = state.get("prd_doc", {})
    clarified_req = state.get("clarified_requirement", {})
    review_result = state.get("review_result")
    human_feedback = state.get("human_feedback", "")
    metadata = state.get("metadata", {}) or {}

    extra_context = ""
    if human_feedback:
        extra_context += f"用户驳回意见（必须优先解决）：\n{human_feedback}\n\n"

    if review_result:
        # Inject review issues even when the review passed: a rejection keeps
        # the old verdict, and those issues are exactly what must be fixed.
        issues = [
            i for i in review_result.get("issues", [])
            if i.get("target") == "engineer"
        ]
        suggestions = review_result.get("suggestions", []) if not review_result.get("passed") else []
        if issues or suggestions:
            extra_context += "上一轮评审指出的问题（必须逐条解决，不得遗漏）：\n"
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

    structured_llm = get_structured_llm(TechnicalDesign, role="engineer")

    task_memory_text = format_for_prompt(
        state.get("task_memory"),
        max_chars=get_settings().short_term_memory_max_chars,
    )

    few_shot_text = build_few_shot_for_task(prd_doc, clarified_req, metadata=metadata)

    messages = [
        SystemMessage(content=ENGINEER_SYSTEM_PROMPT),
        HumanMessage(
            content=ENGINEER_USER_PROMPT.format(
                prd_doc=json.dumps(prd_doc, ensure_ascii=False, indent=2, sort_keys=True),
                clarified_requirement=json.dumps(clarified_req, ensure_ascii=False, indent=2, sort_keys=True),
                extra_context=extra_context,
                few_shot_examples=few_shot_text,
                task_memory=task_memory_text,
                memory_context=memory_context,
            )
        ),
    ]

    # 一次全量生成 + 最多两轮增量补丁。
    # 旧实现覆盖率不达标就整份重生成（最多 3 轮 × 8k token），是单任务最大耗时项；
    # 现在只补缺失的 API/表，单轮补丁的输出量约为全量的 1/5。
    _MAX_PATCH_ROUNDS = 2
    result: TechnicalDesign = structured_llm.invoke(messages)
    if result is None:
        # A long design is the one place where the single-shot output limit is
        # routinely hit. Retry once with a smaller contract instead of failing
        # the whole task after the continuation rounds are exhausted.
        logger.warning(
            "Engineer 首次结构化输出不可解析，以精简契约重试一次",
            extra={"node": "engineer"},
        )
        result = structured_llm.invoke(
            messages
            + [
                HumanMessage(
                    content=(
                        "上一次输出未能通过校验，可能因为内容过长被截断。请重新输出精简版本：\n"
                        "- 只包含 architecture_overview、architecture_style、services、db_schema、api_endpoints。\n"
                        "- 省略 tech_risks 与 code_scaffold。\n"
                        "- 每个功能模块最多 1 个 API 端点、1 张表，每张表 columns 不超过 6 个。\n"
                        "- 所有数组字段必须是数组，字符串字段必须是字符串；不要嵌套对象代替字符串。"
                    )
                )
            ]
        )
    degraded = False
    if result is None:
        logger.error(
            "Engineer structured_llm returned None after continuation; "
            "falling back to a PRD-derived skeleton design",
            extra={"node": "engineer"},
        )
        result_dict: dict = _fallback_design(prd_doc)
        degraded = True
    else:
        result_dict = result.model_dump()

    gaps = report_coverage_gaps(prd_doc, result_dict)
    patch_rounds = 0
    patch_log: list[dict] = []
    while (gaps["api"] or gaps["db"]) and patch_rounds < _MAX_PATCH_ROUNDS:
        patched, stats = patch_design_gaps(
            prd_doc, result_dict, gaps, extra_hints=extra_context
        )
        patch_rounds += 1
        patch_log.append(stats)
        logger.info(
            f"Engineer 增量补丁第 {patch_rounds} 轮",
            extra={
                "node": "engineer",
                "added_api": stats.get("api", 0),
                "added_db": stats.get("db", 0),
                "missing_api": len(gaps["api"]),
                "missing_db": len(gaps["db"]),
            },
        )
        if not stats.get("api") and not stats.get("db"):
            break  # 补丁未产出新条目，继续重试没有意义
        result_dict = patched
        gaps = report_coverage_gaps(prd_doc, result_dict)

    react_iterations = 1 + patch_rounds
    raw_prd_tech_coverage = score_prd_tech_coverage(prd_doc, result_dict)
    raw_api_coverage = score_api_feature_coverage(prd_doc, result_dict)
    raw_db_coverage = score_db_feature_coverage(prd_doc, result_dict)
    coverage_repair = {
        "api": [name for name in gaps["api"]],
        "db": [name for name in gaps["db"]],
        "patched_api": sum(int(item.get("api") or 0) for item in patch_log),
        "patched_db": sum(int(item.get("db") or 0) for item in patch_log),
    }
    code_scaffold = result_dict.get("code_scaffold") or {}
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
    if coverage_repair["api"]:
        warnings_list.append(f"{len(coverage_repair['api'])} 个模块仍缺 API 映射")
    if coverage_repair["db"]:
        warnings_list.append(f"{len(coverage_repair['db'])} 个模块仍缺 DB 映射")
    if coverage_repair["patched_api"] or coverage_repair["patched_db"]:
        warnings_list.append(
            f"增量补丁新增 {coverage_repair['patched_api']} 个 API、{coverage_repair['patched_db']} 张表"
        )

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
        "technical_design": {**result_dict, "_degraded": degraded},
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
            "patch_rounds": patch_rounds,
            "raw_prd_tech_coverage_rate": raw_prd_tech_coverage,
            "raw_api_feature_coverage_rate": raw_api_coverage,
            "raw_db_feature_coverage_rate": raw_db_coverage,
            "coverage_repair_applied": bool(patch_log),
            "coverage_repair": coverage_repair,
            "self_refine_engineer": 0,
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
    llm_with_tools = get_llm_with_tools(ENGINEER_PREP_TOOLS, role="engineer")

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


def _fallback_design(prd_doc: dict) -> dict:
    """模型解析彻底失败时的最小可用设计。

    按 PRD 功能模块生成服务、接口与数据表，保证 API/DB 覆盖率不为零，
    让评审与交付流程可以继续，而不是把整个任务判死。
    """
    features = prd_doc.get("feature_modules") or []
    modules: list[tuple[str, str]] = []
    for index, feature in enumerate(features[:12]):
        if not isinstance(feature, dict):
            continue
        fid = str(feature.get("feature_id") or f"feature_{index + 1}")
        name = str(feature.get("name") or fid)
        modules.append((fid, name))

    if not modules:
        modules = [("core", "核心业务")]

    services = [
        {
            "name": f"{fid}-service",
            "responsibility": f"承载「{name}」的业务逻辑",
            "tech_stack": ["FastAPI"],
        }
        for fid, name in modules
    ]

    tables = []
    endpoints = []
    for fid, name in modules:
        table_name = re.sub(r"[^a-z0-9_]", "_", fid.lower()).strip("_") or "records"
        tables.append(
            {
                "table_name": table_name,
                "description": f"{name}数据表",
                "columns": [
                    {"name": "id", "type": "uuid", "nullable": False, "description": "主键"},
                    {
                        "name": "created_at",
                        "type": "timestamp",
                        "nullable": False,
                        "description": "创建时间",
                    },
                ],
                "indexes": [],
                "related_features": [name],
                "related_feature_ids": [fid],
            }
        )
        endpoints.append(
            {
                "method": "POST",
                "path": f"/{table_name}",
                "description": f"创建{name}记录",
                "request_body": "JSON 对象，字段随业务定义",
                "response_body": "JSON 对象，返回创建结果",
                "auth_required": True,
                "related_features": [name],
                "related_feature_ids": [fid],
            }
        )

    return {
        "architecture_overview": "模型输出解析失败后的降级设计：按 PRD 功能模块生成最小可用的服务、接口与数据表。",
        "architecture_style": "分层单体",
        "services": services,
        "db_schema": {"database_type": "PostgreSQL", "tables": tables, "relationships": []},
        "api_endpoints": endpoints,
        "tech_risks": [
            {
                "risk": "技术设计由自动降级生成，缺少细节设计",
                "impact": "high",
                "mitigation": "请在任务详情页复核设计，必要时触发二次优化",
            }
        ],
        "code_scaffold": {"directory_structure": [], "key_files": [], "dependencies": []},
    }
