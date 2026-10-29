"""Incremental design patching.

The engineer used to regenerate the whole technical design whenever coverage
was short of the threshold. That cost a full 8k-token completion per round.
This module adds only the missing endpoints and tables, then merges them into
the existing design, so a gap costs a small completion instead of a rewrite.

Both the engineer node and the repairer node use this path.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.core.llm import get_structured_llm
from app.core.logger import logger
from app.tools.coverage_metrics import collect_feature_terms, normalize_text

PATCH_SYSTEM_PROMPT = """你是一名精准修复工程师。现有技术设计未完全覆盖 PRD 功能模块。

任务：只生成缺失部分的 API 端点和数据库表，已有设计不做改动。

要求：
- 每个缺失模块生成 1-2 个语义明确的 API 端点，路径包含业务关键词（如 /orders/refund），不要使用 /feature-modules/* 之类的占位路径。
- 每个缺失模块生成 1 张语义明确的表，表名包含业务关键词（如 refund_records）。
- API 必须填写 related_feature_ids，值与给定 feature_id 完全一致；同时填写 related_features（模块名称）。
- 表必须填写 related_feature_ids 与 related_features。
- API 包含 method / path / description / request_body / response_body / auth_required。
- 表包含 table_name / description / columns（id、业务字段、status、created_at 等）/ indexes。
- 不要重复已有端点路径或已有表名。

只输出 JSON：
{
  "api_endpoints": [{...}],
  "db_tables": [{...}]
}"""


class DesignPatch(BaseModel):
    """仅包含缺失的 API 端点和 DB 表。"""

    api_endpoints: list[dict] = Field(default_factory=list)
    db_tables: list[dict] = Field(default_factory=list)


REFINE_SYSTEM_PROMPT = """你是技术设计修订工程师。现有设计存在评审指出的问题，请在其基础上修订。

要求：
- 只修改与问题相关的字段，其余内容原样保留，不要重写整个设计。
- 必须逐条解决所有列出的问题，尤其是 high 与 critical。
- 修复后不得引入新的不一致（如状态枚举、路径命名）。
- 不要输出解释，只输出完整的技术设计 JSON。

只输出 JSON。"""


def refine_design(
    prd_doc: dict[str, Any],
    design: dict[str, Any],
    issues: list[dict[str, Any]],
    human_feedback: str = "",
    role: str = "engineer",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Revise an existing design against review issues, keeping the rest intact."""
    if not issues and not human_feedback.strip():
        return design, {"attempted": False, "repaired": 0}

    issue_lines = []
    for issue in issues[:12]:
        issue_lines.append(
            f"- [{issue.get('severity', '?')}] {issue.get('description', '')}"
            f" 建议：{issue.get('suggestion', '')}"
        )

    prompt = (
        f"## PRD 功能模块（用于核对一致性）\n"
        f"{json.dumps((prd_doc.get('feature_modules') or [])[:12], ensure_ascii=False, sort_keys=True)}\n\n"
        f"## 必须修复的问题\n" + ("\n".join(issue_lines) or "无") + "\n\n"
        f"## 用户驳回意见\n{human_feedback or '无'}\n\n"
        f"## 现有技术设计\n{json.dumps(design, ensure_ascii=False, sort_keys=True)}\n\n"
        "请在现有设计基础上修订，输出完整的技术设计 JSON。"
    )

    try:
        from app.schemas.design import TechnicalDesign

        result = get_structured_llm(TechnicalDesign, temperature=0.2, role=role).invoke(
            [
                SystemMessage(content=REFINE_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]
        )
    except Exception as exc:
        logger.warning(f"Design refinement failed, keeping original: {str(exc)[:200]}")
        return design, {"attempted": True, "error": str(exc)[:200]}

    if result is None:
        return design, {"attempted": True, "error": "unparseable output"}

    refined = result.model_dump()
    logger.info(
        "Design refined against review issues "
        f"issues={len(issues)} api_before={len(design.get('api_endpoints') or [])} "
        f"api_after={len(refined.get('api_endpoints') or [])}"
    )
    return refined, {"attempted": True, "repaired": len(issues)}


def patch_design_gaps(
    prd_doc: dict[str, Any],
    design: dict[str, Any],
    gaps: dict[str, Any],
    extra_hints: str = "",
    temperature: float = 0.2,
    role: str = "engineer",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Patch missing API/DB coverage. Returns (patched_design, stats)."""
    missing_api = list(gaps.get("api") or [])
    missing_db = list(gaps.get("db") or [])
    if not missing_api and not missing_db:
        return design, {"attempted": False, "api": 0, "db": 0}

    modules = _modules_for(prd_doc, missing_api + missing_db)
    prompt = (
        f"## 功能模块定义\n{json.dumps(modules, ensure_ascii=False, indent=2, sort_keys=True)}\n\n"
        f"## 缺失 API 覆盖的功能模块\n{', '.join(missing_api) or '无'}\n\n"
        f"## 缺失 DB 覆盖的功能模块\n{', '.join(missing_db) or '无'}\n\n"
        f"## 已有设计摘要（勿重复）\n{summarize_design(design)}\n\n"
        f"## 评审意见\n{extra_hints or '无'}\n\n"
        "请生成缺失的 API 端点和 DB 表（只输出 JSON）。"
    )

    try:
        result: DesignPatch = get_structured_llm(
            DesignPatch, temperature=temperature, role=role
        ).invoke(
            [
                SystemMessage(content=PATCH_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]
        )
    except Exception as exc:
        logger.warning(
            f"Design patch failed, keeping original design: {exc}",
            extra={"missing_api": len(missing_api), "missing_db": len(missing_db)},
        )
        return design, {"attempted": True, "api": 0, "db": 0, "error": str(exc)[:200]}

    patch = result.model_dump() if result is not None else {}
    patched, stats = merge_patch(design, patch)
    logger.info(
        "Design patch applied "
        f"requested_api={len(missing_api)} requested_db={len(missing_db)} "
        f"added_api={stats['api']} added_db={stats['db']}"
    )
    return patched, {"attempted": True, **stats}


def merge_patch(design: dict[str, Any], patch: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    """Merge patch entries into a copy of the design, skipping duplicates."""
    patched = deepcopy(design or {})
    patched.setdefault("api_endpoints", [])
    patched.setdefault("db_schema", {})
    patched["db_schema"].setdefault("tables", [])
    patched["db_schema"].setdefault("database_type", "PostgreSQL")
    patched["db_schema"].setdefault("relationships", [])

    added_api = _append_unique(
        patched["api_endpoints"],
        patch.get("api_endpoints") or [],
        key=lambda item: (
            str(item.get("method") or "").upper(),
            normalize_text(str(item.get("path") or "")),
        ),
    )
    added_db = _append_unique(
        patched["db_schema"]["tables"],
        patch.get("db_tables") or [],
        key=lambda item: normalize_text(str(item.get("table_name") or "")),
    )
    return patched, {"api": added_api, "db": added_db}


def summarize_design(design: dict[str, Any]) -> str:
    """Compact existing-design summary for the patch prompt."""
    api_paths = [str(e.get("path") or "") for e in (design.get("api_endpoints") or [])[:20]]
    tables = [
        str(t.get("table_name") or "")
        for t in ((design.get("db_schema") or {}).get("tables") or [])[:20]
    ]
    services = [str(s.get("name") or "") for s in (design.get("services") or [])[:8]]
    return (
        f"API: {', '.join(p for p in api_paths if p) or '无'}\n"
        f"DB 表: {', '.join(t for t in tables if t) or '无'}\n"
        f"服务: {', '.join(s for s in services if s) or '无'}\n"
        f"架构风格: {design.get('architecture_style') or '未指定'}"
    )


def _append_unique(existing: list[dict], incoming: list[dict], key) -> int:
    seen = {key(item) for item in existing if isinstance(item, dict)}
    added = 0
    for item in incoming:
        if not isinstance(item, dict):
            continue
        item_key = key(item)
        if isinstance(item_key, tuple):
            if not any(item_key):
                continue
        elif not item_key:
            continue
        if item_key in seen:
            continue
        existing.append(item)
        seen.add(item_key)
        added += 1
    return added


def _modules_for(prd_doc: dict[str, Any], missing_names: list[str]) -> list[dict[str, Any]]:
    """Return PRD modules (with resolved feature_id) for the missing names."""
    wanted = {str(name) for name in missing_names}
    id_by_name = {item["name"]: item["id"] for item in collect_feature_terms(prd_doc)}
    modules = []
    for module in prd_doc.get("feature_modules") or []:
        if not isinstance(module, dict):
            continue
        name = str(module.get("name") or "")
        if name not in wanted:
            continue
        modules.append(
            {
                "feature_id": id_by_name.get(name, ""),
                "name": name,
                "description": module.get("description", ""),
                "priority": module.get("priority", ""),
                "sub_features": (module.get("sub_features") or [])[:6],
                "acceptance_criteria": (module.get("acceptance_criteria") or [])[:4],
            }
        )
    return modules
