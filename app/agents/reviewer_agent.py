"""Reviewer Agent: LLM review plus rule-based API/DB feature coverage checks."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from app.core.config import get_settings
from app.core.llm import get_llm_with_tools, get_structured_llm
from app.core.logger import logger
from app.core.prompts import REVIEWER_SYSTEM_PROMPT, REVIEWER_USER_PROMPT
from app.graph.state import AgentState
from app.memory.short_term import add_entry, format_for_prompt
from app.memory.few_shot import build_few_shot_for_task
from app.schemas.review import ReviewResult, ReviewTargetType
from app.tools.agent_tools import REVIEWER_TOOLS
from app.tools.api_hygiene import audit_api_hygiene
from app.tools.coverage_metrics import coverage_report, normalize_text


def reviewer_node(state: AgentState) -> dict:
    """Review PRD and technical design, then enforce coverage gates."""
    logger.info("Reviewer Agent started", extra={"node": "reviewer"})

    prd_doc = state.get("prd_doc", {})
    technical_design = state.get("technical_design", {})
    clarified_req = state.get("clarified_requirement", {})
    metadata = state.get("metadata", {}) or {}

    memory_hits = []
    memory_context = ""
    if _memory_enabled(metadata):
        memory_context, memory_hits = _run_reviewer_tool_calling(
            prd_doc, technical_design, clarified_req
        )

    structured_llm = get_structured_llm(ReviewResult, role="reviewer")
    task_memory_text = format_for_prompt(
        state.get("task_memory"),
        max_chars=get_settings().short_term_memory_max_chars,
    )
    few_shot_text = build_few_shot_for_task(prd_doc, clarified_req, metadata=metadata)
    previous_issues = (state.get("review_result") or {}).get("issues") or []
    messages = [
        SystemMessage(content=REVIEWER_SYSTEM_PROMPT),
        HumanMessage(
            content=REVIEWER_USER_PROMPT.format(
                prd_doc=json.dumps(prd_doc, ensure_ascii=False, indent=2, sort_keys=True),
                technical_design=json.dumps(
                    _compact_design_for_review(technical_design),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
                clarified_requirement=json.dumps(clarified_req, ensure_ascii=False, indent=2, sort_keys=True),
                extra_context=_build_review_history(previous_issues),
                few_shot_examples=few_shot_text,
                task_memory=task_memory_text,
                memory_context=memory_context,
            )
        ),
    ]

    result: ReviewResult = structured_llm.invoke(messages)
    if result is None:
        logger.warning(
            "Reviewer 首次结构化输出不可解析，以精简契约重试一次",
            extra={"node": "reviewer"},
        )
        result = structured_llm.invoke(
            messages
            + [
                HumanMessage(
                    content=(
                        "上一次输出未能通过校验。请重新输出精简评审：\n"
                        "- 只给 overall_score、五个维度评分、passed、reflow_target、summary。\n"
                        "- issues 最多 5 条，每条 description 一句话、suggestion 一句话。\n"
                        "- 不要输出 Markdown。"
                    )
                )
            ]
        )
    if result is None:
        # A single unparseable review must not discard a complete deliverable.
        logger.error("Reviewer 结构化输出两次不可解析，降级为规则评审", extra={"node": "reviewer"})
        result_dict = _rule_only_review()
    else:
        result_dict = result.model_dump()
    result_dict = _apply_rule_based_adjustment(
        result_dict, prd_doc, technical_design, previous_issues=previous_issues
    )

    reflow_count = int(state.get("reflow_count", 0) or 0)
    reflow_target = _target_value(result_dict.get("reflow_target"))
    if not result_dict.get("passed", False) and reflow_target != "none":
        reflow_count += 1

    logger.info(
        "Reviewer Agent completed",
        extra={
            "node": "reviewer",
            "passed": result_dict.get("passed"),
            "overall_score": result_dict.get("overall_score"),
            "reflow_target": reflow_target,
            "reflow_count": reflow_count,
        },
    )

    passed = result_dict.get("passed", False)
    issues_count = len(result_dict.get("issues") or [])
    high_issues = sum(
        1 for i in (result_dict.get("issues") or [])
        if i.get("severity") in ("high", "critical")
    )
    warnings_list = (
        [f"发现 {high_issues} 个高严重性问题"] if high_issues else []
    )
    if reflow_target != "none" and not passed:
        warnings_list.append(f"建议回流到 {reflow_target}")

    task_mem = add_entry(
        state, "reviewer",
        summary=f"评审{'通过' if passed else '未通过'}，总分={result_dict.get('overall_score')}",
        key_decisions=[
            f"PRD评分={result_dict.get('prd_score')}",
            f"技术评分={result_dict.get('tech_score')}",
            f"回流目标={reflow_target}",
        ],
        metrics={
            "overall_score": result_dict.get("overall_score"),
            "passed": passed,
            "issues_count": issues_count,
            "reflow_count": reflow_count,
        },
        warnings=warnings_list,
    )

    return {
        "review_result": result_dict,
        **task_mem,
        "reflow_count": reflow_count,
        "current_node": "reviewer",
        "memory_hits": memory_hits,
        "metadata": {
            **metadata,
            "review_memory_context_used": bool(memory_context),
            # The rule-conflict re-review was removed: rules already decide the
            # gate, and a second full review doubled reviewer latency.
            "self_refine_reviewer": 0,
        },
        "execution_logs": [
            {
                "node": "reviewer",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "passed": result_dict.get("passed"),
                "overall_score": result_dict.get("overall_score"),
                "reflow_target": reflow_target,
                "memory_hit_count": len(memory_hits),
            }
        ],
    }


def _rule_only_review() -> dict[str, Any]:
    """Neutral review used when the model output cannot be parsed twice."""
    return {
        "overall_score": 6.0,
        "prd_score": 0.0,
        "tech_score": 0.0,
        "issues": [],
        "suggestions": [
            "评审模型多次输出不可解析，已改用覆盖率规则生成结论，请人工复核。"
        ],
        "passed": False,
        "reflow_target": ReviewTargetType.NONE,
        "summary": "规则评审：模型输出不可解析，结论由覆盖率与人工复核决定。",
    }


_RUBRIC_DIMENSIONS = (
    ("completeness_score", 0.30),
    ("consistency_score", 0.25),
    ("feasibility_score", 0.20),
    ("testability_score", 0.15),
    ("security_score", 0.10),
)


def _weighted_overall(review: dict[str, Any]) -> float | None:
    """Weighted score over the dimensions the model actually filled."""
    provided = [
        (float(review.get(name) or 0), weight)
        for name, weight in _RUBRIC_DIMENSIONS
        if float(review.get(name) or 0) > 0
    ]
    if not provided:
        return None
    total_weight = sum(weight for _, weight in provided)
    return round(sum(score * weight for score, weight in provided) / total_weight, 2)


def _build_review_history(previous_issues: list[dict[str, Any]]) -> str:
    """Prompt block asking the model to re-check last round's issues."""
    if not previous_issues:
        return ""
    lines = [
        f"{index}. [{issue.get('severity', '?')}] {issue.get('description', '')}"
        for index, issue in enumerate(previous_issues[:8], start=1)
    ]
    return (
        "## 上一轮评审问题复核\n\n"
        "请逐条核对当前 PRD 与技术设计，判断以下问题是否已经解决：\n\n"
        + "\n".join(lines)
        + "\n\n输出要求：\n"
        '- 在 issue_reviews 中逐条给出 {"description": 原文, "resolved": true/false}。\n'
        "- 已解决的问题不要再次写入 issues。\n"
        "- issues 只保留仍未解决的历史问题与新发现的问题。\n"
    )


def _merge_previous_issues(
    previous: list[dict[str, Any]],
    current: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Carry over issues the model explicitly marked as unresolved.

    Without an explicit review list the model simply did not perform the check,
    so the current issues are used as-is rather than resurrecting everything.
    """
    if not previous or not reviews:
        return current

    resolved = {
        normalize_text(str(item.get("description") or ""))
        for item in reviews
        if item.get("resolved")
    }
    unresolved = {
        normalize_text(str(item.get("description") or ""))
        for item in reviews
        if not item.get("resolved")
    }
    current_descriptions = {
        normalize_text(str(item.get("description") or "")) for item in current
    }

    merged = [
        {**issue, "origin": str(issue.get("origin") or "new")}
        for issue in current
    ]
    for issue in previous:
        description = normalize_text(str(issue.get("description") or ""))
        if not description or description in resolved or description in current_descriptions:
            continue
        if description not in unresolved:
            continue
        merged.append({**issue, "origin": "carried"})
    return merged


def _apply_rule_based_adjustment(
    review: dict[str, Any],
    prd_doc: dict[str, Any],
    technical_design: dict[str, Any],
    previous_issues: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    report = coverage_report(prd_doc, technical_design)
    api_coverage = report["api"]["score"]
    db_coverage = report["db"]["score"]
    prd_tech_coverage = report["prd_tech"]["score"]
    missing = {"api": report["api"]["missing"], "db": report["db"]["missing"]}
    feature_count = max(1, int(report["feature_count"]))
    has_features = report["feature_count"] > 0

    issues = list(review.get("issues") or [])
    if previous_issues:
        issues = _merge_previous_issues(
            previous_issues, issues, review.get("issue_reviews") or []
        )
    # Deterministic API surface checks run after the model, so duplicate action
    # paths and read sprawl are caught even when the reviewer misses them.
    seen = {str(item.get("description") or "")[:40] for item in issues}
    for extra in audit_api_hygiene(technical_design):
        if str(extra.get("description") or "")[:40] not in seen:
            issues.append(extra)
    suggestions = list(review.get("suggestions") or [])
    severe_mapping_gap = has_features and (api_coverage < 0.5 or db_coverage < 0.5)

    # The model's own total drifts between runs; keep it for comparison and
    # replace it with the rubric-weighted value when the dimensions are present.
    review.setdefault("llm_overall_score", float(review.get("overall_score") or 0))
    review.setdefault("llm_passed", bool(review.get("passed")))
    weighted = _weighted_overall(review)
    if weighted is not None:
        review["overall_score"] = weighted
    overall = float(review.get("overall_score") or 0)

    if missing["api"]:
        issues.append(
            {
                "category": "completeness",
                "severity": "high" if severe_mapping_gap else "medium",
                "description": "PRD feature modules missing API mapping: "
                + ", ".join(missing["api"]),
                "suggestion": "Add domain-specific endpoints whose path or description explicitly covers these feature modules.",
                "target": ReviewTargetType.ENGINEER,
                "origin": "new",
            }
        )
    if missing["db"]:
        issues.append(
            {
                "category": "completeness",
                "severity": "high" if severe_mapping_gap else "medium",
                "description": "PRD feature modules missing DB schema mapping: "
                + ", ".join(missing["db"]),
                "suggestion": "Add tables or columns whose names/descriptions explicitly persist these feature modules.",
                "target": ReviewTargetType.ENGINEER,
                "origin": "new",
            }
        )

    if severe_mapping_gap:
        suggestions.append(
            "Rework the technical design so every PRD feature has traceable service/API/DB coverage."
        )
        review["reflow_target"] = ReviewTargetType.ENGINEER
        review["tech_score"] = min(float(review.get("tech_score") or 0), 6.0)
        review["overall_score"] = min(overall, 6.5)
    elif missing["api"] or missing["db"]:
        missing_ratio = (len(missing["api"]) + len(missing["db"])) / (feature_count * 2)
        coverage_gap = max(1.0 - api_coverage, 1.0 - db_coverage)
        penalty = max(0.5, min(1.8, coverage_gap * 2.0 + missing_ratio))
        # The old code used max(7.0, ...) here, so a penalty could never push a
        # score below 7.0 and gaps had no effect on the outcome.
        review["tech_score"] = max(0.0, round(float(review.get("tech_score") or 0) - penalty, 2))
        review["overall_score"] = max(0.0, round(float(review.get("overall_score") or 0) - penalty, 2))

    critical = any(
        str(issue.get("severity") or "").lower() == "critical" for issue in issues
    )
    high = any(str(issue.get("severity") or "").lower() == "high" for issue in issues)
    rule_passed = (
        float(review.get("overall_score") or 0) >= 7.0
        and not critical
        and not high
        and not severe_mapping_gap
    )
    # A failing review must route somewhere. When the model left the target
    # empty but listed high-severity issues, send the work back to engineering.
    if not rule_passed:
        target_text = str(review.get("reflow_target") or "none").lower()
        if target_text.endswith("none"):
            review["reflow_target"] = ReviewTargetType.ENGINEER

    # The rubric is the single decision source. The model's own verdict was
    # blocking 7.0-point deliverables with no critical issue, which caused two
    # fruitless reflow rounds before every task reached human approval.
    review["passed"] = rule_passed

    review["issues"] = issues
    review["suggestions"] = suggestions
    summary = review.get("summary") or ""
    review["summary"] = (
        f"{summary}\nRule coverage: PRD-Tech={prd_tech_coverage:.2f}, "
        f"API-Feature={api_coverage:.2f}, DB-Feature={db_coverage:.2f}, "
        f"rubric_weighted={review.get('overall_score')}."
    ).strip()
    return review


def _memory_enabled(metadata: dict[str, Any]) -> bool:
    if "memory_enabled" in metadata:
        return bool(metadata.get("memory_enabled"))
    return bool(get_settings().memory_enabled)


def _run_reviewer_tool_calling(
    prd_doc: dict[str, Any],
    technical_design: dict[str, Any],
    clarified_req: dict[str, Any],
) -> tuple[str, list[dict]]:
    """Tool calling 预热阶段：让 Reviewer LLM 主动检索历史评审和架构模式。"""
    tool_map = {t.name: t for t in REVIEWER_TOOLS}
    llm_with_tools = get_llm_with_tools(REVIEWER_TOOLS, role="reviewer")

    feature_names = ", ".join(
        str(m.get("name", "")) for m in (prd_doc.get("feature_modules") or [])
        if isinstance(m, dict)
    )
    prep_prompt = (
        "你是一名技术评审专家，即将评审以下产品的 PRD 和技术设计。\n"
        f"产品目标：{prd_doc.get('product_goal') or clarified_req.get('goal') or ''}\n"
        f"核心功能模块：{feature_names}\n"
        "请先检索相关历史评审记录或架构模式，为本次评审提供参考标准。"
        "如果不需要额外信息，直接回复'无需检索'即可。"
    )
    messages = [HumanMessage(content=prep_prompt)]
    context_parts: list[str] = []

    for _ in range(3):
        response = llm_with_tools.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            break

        for tc in response.tool_calls:
            tool_name = tc["name"]
            tool_id = tc["id"]
            if tool_name not in tool_map:
                result_content = f"未知工具：{tool_name}"
            else:
                try:
                    result_content = tool_map[tool_name].invoke(tc["args"])
                except Exception as exc:
                    result_content = f"工具调用失败：{exc}"

            messages.append(ToolMessage(content=result_content, tool_call_id=tool_id))
            if tool_name == "search_memory" and result_content != "未找到相关记忆。":
                context_parts.append(result_content)

    memory_context = "\n\n".join(context_parts)
    settings = get_settings()
    if len(memory_context) > settings.memory_context_max_chars:
        memory_context = memory_context[: settings.memory_context_max_chars].rstrip() + "\n...[truncated]"
    return memory_context, []


def _target_value(target: Any) -> str:
    return str(getattr(target, "value", target or "none"))


def _clip(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _compact_design_for_review(design: dict) -> dict:
    """Shrink the design payload to what review findings actually cite.

    Request/response bodies, indexes and code scaffold are the bulkiest parts
    and are rarely referenced in review output. Dropping them shortens the
    variable tail, so the stable PRD prefix covers a larger share of the prompt
    and prompt-cache hits rise.
    """
    db_schema = design.get("db_schema") or {}
    tables = []
    for item in db_schema.get("tables") or []:
        if not isinstance(item, dict):
            continue
        tables.append(
            {
                "table_name": item.get("table_name"),
                "description": _clip(item.get("description"), 90),
                "columns": [
                    {"name": col.get("name"), "type": col.get("type")}
                    for col in (item.get("columns") or [])
                    if isinstance(col, dict)
                ],
                "related_feature_ids": item.get("related_feature_ids") or [],
            }
        )

    return {
        "_note": "request_body / response_body 已截断为前 120 字，indexes 与 code_scaffold 已省略",
        "architecture_overview": _clip(design.get("architecture_overview"), 500),
        "architecture_style": design.get("architecture_style") or "",
        "services": [
            {
                "name": item.get("name"),
                "responsibility": _clip(item.get("responsibility"), 80),
            }
            for item in design.get("services") or []
            if isinstance(item, dict)
        ],
        "api_endpoints": [
            {
                "method": item.get("method"),
                "path": item.get("path"),
                "description": _clip(item.get("description"), 110),
                # Reviewers check契约字段; dropping them entirely made the
                # design look untestable, so keep a short excerpt instead.
                "request_body": _clip(item.get("request_body"), 120),
                "response_body": _clip(item.get("response_body"), 120),
                "related_feature_ids": item.get("related_feature_ids") or [],
            }
            for item in design.get("api_endpoints") or []
            if isinstance(item, dict)
        ],
        "db_schema": {
            "database_type": db_schema.get("database_type"),
            "tables": tables,
        },
        "tech_risks": [
            {"risk": _clip(item.get("risk"), 80), "impact": item.get("impact")}
            for item in design.get("tech_risks") or []
            if isinstance(item, dict)
        ],
    }
