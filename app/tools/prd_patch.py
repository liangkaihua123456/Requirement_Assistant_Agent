"""PRD quality gate.

The solution agent used to hand its first output straight to the engineer, so a
PRD without acceptance criteria, user flows, or measurable non-functional
requirements only surfaced later as a review failure and a full reflow.

This module audits the PRD structure and fills only the missing parts with one
targeted completion instead of regenerating the whole document.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.core.llm import get_structured_llm
from app.core.logger import logger
from app.tools.coverage_metrics import slugify

MIN_FEATURES = 3
MIN_USER_STORIES = 3
MIN_NON_FUNCTIONAL = 3

PRD_PATCH_SYSTEM_PROMPT = """你是一名资深产品经理，正在补齐一份 PRD 的缺失部分。

只输出缺失内容，不要重写已有内容：
- feature_acceptance：为指定功能模块补充可验证的验收标准（每条能被测试用例直接判定，包含触发条件与预期结果）。
- user_flows：补充核心流程的步骤（name + steps）。
- non_functional_requirements：补充性能、安全、可用性等非功能需求，metric 必须是量化指标。

只输出 JSON：
{
  "feature_acceptance": [{"feature_id": "", "name": "", "acceptance_criteria": ["..."]}],
  "user_flows": [{"name": "", "steps": ["..."]}],
  "non_functional_requirements": [{"category": "", "description": "", "metric": ""}]
}"""


class FeatureAcceptance(BaseModel):
    feature_id: str = Field("", description="对应功能模块的 feature_id")
    name: str = Field(..., description="功能模块名称")
    acceptance_criteria: list[str] = Field(default_factory=list)


class PRDPatch(BaseModel):
    feature_acceptance: list[FeatureAcceptance] = Field(default_factory=list)
    user_flows: list[dict] = Field(default_factory=list)
    non_functional_requirements: list[dict] = Field(default_factory=list)


def audit_prd(prd: dict[str, Any]) -> list[str]:
    """Return structural gaps. Empty list means the PRD may proceed."""
    gaps: list[str] = []
    features = [item for item in (prd.get("feature_modules") or []) if isinstance(item, dict)]
    if len(features) < MIN_FEATURES:
        gaps.append(f"功能模块少于 {MIN_FEATURES} 个（当前 {len(features)}）")
    missing_acceptance = [
        str(item.get("name") or "") for item in features if not (item.get("acceptance_criteria") or [])
    ]
    if missing_acceptance:
        gaps.append("以下功能模块缺少验收标准：" + ", ".join(missing_acceptance))
    if len(prd.get("user_stories") or []) < MIN_USER_STORIES:
        gaps.append(f"用户故事少于 {MIN_USER_STORIES} 条")
    if not prd.get("user_flows"):
        gaps.append("缺少用户流程")
    if len(prd.get("non_functional_requirements") or []) < MIN_NON_FUNCTIONAL:
        gaps.append(f"非功能性需求少于 {MIN_NON_FUNCTIONAL} 条")
    return gaps


def ensure_prd_quality(
    prd: dict[str, Any],
    clarified_req: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fill structural gaps with one targeted completion. Returns (prd, audit)."""
    normalized = with_feature_ids(prd)
    gaps = audit_prd(normalized)
    if not gaps:
        return normalized, {"gaps": [], "patched": False, "remaining": []}

    features = [
        {
            "feature_id": item.get("feature_id", ""),
            "name": item.get("name", ""),
            "description": item.get("description", ""),
            "sub_features": (item.get("sub_features") or [])[:6],
            "acceptance_criteria": item.get("acceptance_criteria") or [],
        }
        for item in (normalized.get("feature_modules") or [])
        if isinstance(item, dict)
    ]
    prompt = (
        f"## 产品\n{normalized.get('product_name', '')}\n{normalized.get('positioning', '')}\n\n"
        f"## 需求目标\n{(clarified_req or {}).get('goal', '')}\n\n"
        f"## 已存在的内容\n"
        f"- 功能模块数：{len(features)}\n"
        f"- 用户故事数：{len(normalized.get('user_stories') or [])}\n"
        f"- 用户流程数：{len(normalized.get('user_flows') or [])}\n"
        f"- 非功能需求数：{len(normalized.get('non_functional_requirements') or [])}\n\n"
        f"## 功能模块\n{json.dumps(features, ensure_ascii=False, indent=2, sort_keys=True)}\n\n"
        f"## 需要补齐的缺口\n" + "\n".join(f"- {gap}" for gap in gaps) + "\n\n"
        "请只补充缺失内容。"
    )

    try:
        patch: PRDPatch = get_structured_llm(PRDPatch, temperature=0.4, role="solution").invoke(
            [
                SystemMessage(content=PRD_PATCH_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]
        )
    except Exception as exc:
        logger.warning(f"PRD gap patch failed, keeping original PRD: {exc}")
        return normalized, {"gaps": gaps, "patched": False, "remaining": gaps, "error": str(exc)[:200]}

    merged = merge_prd_patch(normalized, patch.model_dump() if patch else {})
    merged = with_feature_ids(merged)
    remaining = audit_prd(merged)
    logger.info(
        f"PRD gap patch applied gaps={len(gaps)} remaining={len(remaining)}"
    )
    return merged, {"gaps": gaps, "patched": True, "remaining": remaining}


def with_feature_ids(prd: dict[str, Any]) -> dict[str, Any]:
    """Ensure every feature module has a stable id for cross-document tracing."""
    normalized = deepcopy(prd or {})
    modules = normalized.get("feature_modules") or []
    used: set[str] = set()
    for index, module in enumerate(modules, start=1):
        if not isinstance(module, dict):
            continue
        name = str(module.get("name") or f"feature_{index}")
        feature_id = str(module.get("feature_id") or "").strip()
        if not feature_id:
            feature_id = slugify(name, index)
        if feature_id in used:
            feature_id = f"{feature_id}_{index}"
        used.add(feature_id)
        module["feature_id"] = feature_id
    return normalized


def merge_prd_patch(prd: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(prd or {})
    modules = [item for item in (merged.get("feature_modules") or []) if isinstance(item, dict)]
    by_id = {str(item.get("feature_id") or ""): item for item in modules}
    by_name = {str(item.get("name") or ""): item for item in modules}

    for item in patch.get("feature_acceptance") or []:
        if not isinstance(item, dict):
            continue
        target = by_id.get(str(item.get("feature_id") or "")) or by_name.get(
            str(item.get("name") or "")
        )
        criteria = [str(value) for value in (item.get("acceptance_criteria") or []) if str(value).strip()]
        if target is not None and criteria and not (target.get("acceptance_criteria") or []):
            target["acceptance_criteria"] = criteria

    if not merged.get("user_flows"):
        flows = [item for item in (patch.get("user_flows") or []) if isinstance(item, dict)]
        if flows:
            merged["user_flows"] = flows

    existing_nfr = list(merged.get("non_functional_requirements") or [])
    if len(existing_nfr) < MIN_NON_FUNCTIONAL:
        extra = [
            item
            for item in (patch.get("non_functional_requirements") or [])
            if isinstance(item, dict)
        ]
        merged["non_functional_requirements"] = existing_nfr + extra

    return merged
