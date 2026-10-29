"""Model routing settings API.

Lets an operator set model, endpoint, key, max tokens, and reasoning effort per
role from the UI. Values persist to ``data/model_routing.json`` and take effect
without restarting the process.
"""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core import pricing_sync
from app.core.config import ROLE_NAMES, get_settings
from app.core.llm import get_llm, reload_clients
from app.core.model_router import resolve_profile
from app.core.pricing_store import get_meta, get_models_raw, get_pricing, save as save_pricing
from app.core.routing_store import get_overrides, mask_key, save_overrides
from app.tools.cost_recalc import recalc_all_costs

router = APIRouter(prefix="/settings", tags=["settings"])

ROLE_LABELS = {
    "planner": "需求分析",
    "solution": "方案设计",
    "engineer": "工程实现",
    "reviewer": "智能评审",
    "repairer": "自动修复",
    "evaluator": "方案评估",
    "dialogue": "多智能体对话",
    "normalizer": "输入规范化",
    "vision": "图片识别（多模态）",
}


class RoleConfigInput(BaseModel):
    role: str
    model: str = ""
    api_base: str = ""
    api_key: str = ""
    max_tokens: int = 0
    reasoning_effort: str = ""


class RoutingUpdate(BaseModel):
    roles: list[RoleConfigInput] = Field(default_factory=list)


class RoutingTestInput(BaseModel):
    role: str


class ModelPriceInput(BaseModel):
    model: str
    input: float = 0
    cached_input: float = 0
    output: float = 0
    currency: str = "USD"


class PricingUpdate(BaseModel):
    models: list[ModelPriceInput] = Field(default_factory=list)


@router.get("/routing")
async def get_routing_config():
    settings = get_settings()
    overrides = get_overrides()
    rows = []
    for role in ROLE_NAMES:
        profile = resolve_profile(role)
        override = overrides.get(role)
        rows.append(
            {
                "role": role,
                "label": ROLE_LABELS.get(role, role),
                "model": override.model if override else "",
                "api_base": override.api_base if override else "",
                "api_key_masked": mask_key(profile.api_key),
                "api_key_set": bool(profile.api_key),
                "max_tokens": override.max_tokens if override else 0,
                "reasoning_effort": override.reasoning_effort if override else "",
                "effective_model": profile.model,
                "effective_api_base": profile.api_base,
                "is_override": profile.is_override,
            }
        )

    return {
        "routing_enabled": settings.model_routing_enabled,
        "fallback_enabled": settings.model_routing_fallback_enabled,
        "global": {
            "model": settings.openai_model_name,
            "api_base": settings.openai_api_base,
            "max_tokens": settings.openai_max_tokens,
        },
        "roles": rows,
    }


@router.put("/routing")
async def update_routing_config(body: RoutingUpdate):
    payload = {
        item.role: {
            "model": item.model,
            "api_base": item.api_base,
            "api_key": item.api_key,
            "max_tokens": item.max_tokens,
            "reasoning_effort": item.reasoning_effort,
        }
        for item in body.roles
        if item.role in ROLE_NAMES
    }
    save_overrides(payload)
    reload_clients()
    return {"status": "saved", "roles": len(payload)}


@router.post("/routing/test")
async def test_routing_connection(body: RoutingTestInput):
    role = body.role.strip()
    if role not in ROLE_NAMES:
        return {"ok": False, "error": "unknown role"}
    result = _probe_role(role)
    result.pop("role", None)
    return result


CORE_ROLES = ("planner", "solution", "engineer", "reviewer")


@router.post("/preflight")
async def preflight_check():
    """提交任务前检查核心角色是否可用，提前暴露密钥、余额与网络问题。"""
    results = []
    for role in CORE_ROLES:
        results.append(await asyncio.to_thread(_probe_role, role))
    failed = [item for item in results if not item["ok"]]
    return {
        "ok": not failed,
        "results": results,
        "failed_roles": [item["role"] for item in failed],
    }


def _probe_role(role: str) -> dict:
    profile = resolve_profile(role)
    started = time.perf_counter()
    try:
        reply = get_llm(0.0, role=role).invoke([{"role": "user", "content": "回复 ok"}])
        return {
            "role": role,
            "ok": True,
            "model": profile.model,
            "elapsed_seconds": round(time.perf_counter() - started, 2),
            "reply": str(getattr(reply, "content", ""))[:40],
        }
    except Exception as exc:
        return {
            "role": role,
            "ok": False,
            "model": profile.model,
            "elapsed_seconds": round(time.perf_counter() - started, 2),
            "error": str(exc)[:300],
        }


@router.get("/pricing")
async def get_pricing_config():
    pricing = get_pricing()
    raw = get_models_raw()
    models = []
    for name, price in sorted(pricing.items()):
        models.append(
            {
                "model": name,
                "input": price.input,
                "cached_input": price.cached_input,
                "output": price.output,
                "currency": price.currency,
                "manual": bool((raw.get(name) or {}).get("manual")),
            }
        )
    return {
        "models": models,
        "meta": get_meta(),
        "usd_to_cny_rate": get_settings().usd_to_cny_rate,
    }


@router.put("/pricing")
async def update_pricing_config(body: PricingUpdate):
    payload = {
        item.model.strip(): {
            "input": item.input,
            "cached_input": item.cached_input,
            "output": item.output,
            "currency": item.currency,
        }
        for item in body.models
        if item.model.strip()
    }
    save_pricing(payload, manual=True)
    return {"status": "saved", "models": len(payload)}


@router.post("/pricing/sync")
async def sync_pricing():
    """Fetch official prices now instead of waiting for the daily refresh."""
    return await asyncio.to_thread(pricing_sync.sync_all)


@router.post("/pricing/recalc")
async def recalc_pricing():
    """Recompute every task's cost with the current price table."""
    return await recalc_all_costs()
