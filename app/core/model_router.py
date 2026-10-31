"""Role-based model routing.

Each agent role can point at a different model, provider endpoint, and key.
Empty overrides inherit the global LLM settings, so existing deployments keep
working without any new configuration.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import DEFAULT_MODEL_PRICING, ROLE_NAMES, get_settings
from app.core.routing_store import get_overrides

DEFAULT_ROLE = "default"


@dataclass(frozen=True)
class ModelProfile:
    role: str
    model: str
    api_base: str
    api_key: str
    max_tokens: int
    is_override: bool = False
    reasoning_effort: str = ""


def resolve_profile(role: str = DEFAULT_ROLE) -> ModelProfile:
    """Resolve the effective model profile for a role."""
    settings = get_settings()
    overrides = get_overrides() if settings.model_routing_enabled else {}
    override = overrides.get(role)

    if override and override.model.strip():
        return ModelProfile(
            role=role,
            model=override.model.strip(),
            api_base=(override.api_base or settings.openai_api_base).strip(),
            api_key=(override.api_key or settings.openai_api_key).strip(),
            max_tokens=override.max_tokens or settings.openai_max_tokens,
            is_override=True,
            reasoning_effort=override.reasoning_effort.strip(),
        )

    return ModelProfile(
        # Keep the calling role as the usage label even when it inherits the
        # global model, so per-role token accounting stays meaningful.
        role=role,
        model=settings.openai_model_name,
        api_base=settings.openai_api_base,
        api_key=settings.openai_api_key,
        max_tokens=settings.openai_max_tokens,
        is_override=False,
    )


def routing_summary() -> dict[str, dict[str, str | int | bool]]:
    """Effective routing per role, for logs and diagnostics."""
    settings = get_settings()
    summary: dict[str, dict[str, str | int | bool]] = {}
    for role in (DEFAULT_ROLE, *ROLE_NAMES):
        profile = resolve_profile(role)
        summary[role] = {
            "model": profile.model,
            "api_base": profile.api_base,
            "max_tokens": profile.max_tokens,
            "override": profile.is_override,
            "reasoning_effort": profile.reasoning_effort or "-",
        }
    summary["_meta"] = {
        "routing_enabled": settings.model_routing_enabled,
        "fallback_enabled": settings.model_routing_fallback_enabled,
        "priced_models": ",".join(sorted(set(settings.model_pricing) | set(DEFAULT_MODEL_PRICING))),
    }
    return summary
