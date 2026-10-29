"""Model routing and token usage accounting."""

from __future__ import annotations

from types import SimpleNamespace

from app.core.config import RoleOverride, get_settings
from app.core.model_router import resolve_profile
from app.core.usage import UsageAccumulator, UsageRecord, _extract_usage


def test_role_without_override_inherits_global(monkeypatch):
    settings = get_settings()
    overrides = dict(settings.role_overrides)
    overrides["solution"] = RoleOverride()
    monkeypatch.setattr(settings, "role_overrides", overrides)
    monkeypatch.setattr("app.core.model_router.get_overrides", lambda: overrides)

    profile = resolve_profile("solution")

    assert profile.is_override is False
    assert profile.model == settings.openai_model_name
    assert profile.api_base == settings.openai_api_base


def test_role_override_uses_own_provider(monkeypatch):
    settings = get_settings()
    overrides = dict(settings.role_overrides)
    overrides["planner"] = RoleOverride(
        model="gpt-6.1-sol",
        api_base="https://relay.example.com/v1",
        api_key="relay-key",
        max_tokens=32000,
    )
    monkeypatch.setattr(settings, "role_overrides", overrides)
    monkeypatch.setattr(settings, "model_routing_enabled", True)
    monkeypatch.setattr("app.core.model_router.get_overrides", lambda: overrides)

    profile = resolve_profile("planner")

    assert profile.is_override is True
    assert profile.role == "planner"
    assert profile.model == "gpt-6.1-sol"
    assert profile.api_base == "https://relay.example.com/v1"
    assert profile.api_key == "relay-key"
    assert profile.max_tokens == 32000


def test_override_carries_reasoning_effort(monkeypatch):
    settings = get_settings()
    overrides = dict(settings.role_overrides)
    overrides["planner"] = RoleOverride(model="gpt-6.1-sol", reasoning_effort="high")
    monkeypatch.setattr(settings, "role_overrides", overrides)
    monkeypatch.setattr(settings, "model_routing_enabled", True)
    monkeypatch.setattr("app.core.model_router.get_overrides", lambda: overrides)

    assert resolve_profile("planner").reasoning_effort == "high"


def test_override_ignored_when_routing_disabled(monkeypatch):
    settings = get_settings()
    overrides = dict(settings.role_overrides)
    overrides["planner"] = RoleOverride(model="gpt-6.1-sol")
    monkeypatch.setattr(settings, "role_overrides", overrides)
    monkeypatch.setattr(settings, "model_routing_enabled", False)

    profile = resolve_profile("planner")

    assert profile.is_override is False
    assert profile.model == settings.openai_model_name


def test_usage_summary_aggregates_and_estimates_cost(monkeypatch):
    from app.core.config import DEFAULT_MODEL_PRICING

    monkeypatch.setattr("app.core.usage.get_pricing", lambda: DEFAULT_MODEL_PRICING)
    # 固定为高峰价，避免测试结果随运行时刻（高峰/空闲）变化
    monkeypatch.setattr("app.core.usage.is_peak_hour", lambda moment=None: True)
    accumulator = UsageAccumulator()
    accumulator.add(
        UsageRecord(
            role="engineer",
            model="deepseek-flash",
            prompt_tokens=1_000_000,
            completion_tokens=1_000_000,
            total_tokens=2_000_000,
            cached_tokens=0,
        )
    )
    accumulator.add(
        UsageRecord(
            role="planner",
            model="gpt-6.1-sol",
            prompt_tokens=1_000_000,
            completion_tokens=1_000_000,
            total_tokens=2_000_000,
            cached_tokens=0,
        )
    )

    summary = accumulator.summary()

    assert summary["total"]["total_tokens"] == 4_000_000
    assert summary["total"]["calls"] == 2
    assert summary["by_role"]["engineer"]["total_tokens"] == 2_000_000
    assert summary["by_model"]["gpt-6.1-sol"]["calls"] == 1
    # DeepSeek 高峰: 2 + 8 = 10 CNY; GPT: (2 + 10) USD * 7.1 = 85.2 CNY
    assert summary["priced"] is True
    assert summary["cost_cny"] == 95.2


def test_usage_with_cached_tokens_uses_cache_price(monkeypatch):
    from app.core.config import DEFAULT_MODEL_PRICING

    monkeypatch.setattr("app.core.usage.get_pricing", lambda: DEFAULT_MODEL_PRICING)
    monkeypatch.setattr("app.core.usage.is_peak_hour", lambda moment=None: True)
    accumulator = UsageAccumulator()
    accumulator.add(
        UsageRecord(
            role="engineer",
            model="deepseek-flash",
            prompt_tokens=1_000_000,
            completion_tokens=0,
            total_tokens=1_000_000,
            cached_tokens=1_000_000,
        )
    )

    summary = accumulator.summary()

    # 高峰命中价 0.04 元 / 百万 tokens
    assert summary["cost_cny"] == 0.04


def test_unknown_model_marks_cost_unpriced():
    accumulator = UsageAccumulator()
    accumulator.add(
        UsageRecord(
            role="reviewer",
            model="unknown-model",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )
    )

    summary = accumulator.summary()

    assert summary["priced"] is False
    assert summary["cost_cny"] == 0.0


def test_extract_usage_from_generation_metadata():
    message = SimpleNamespace(
        response_metadata={
            "token_usage": {
                "prompt_tokens": 120,
                "completion_tokens": 30,
                "total_tokens": 150,
                "prompt_tokens_details": {"cached_tokens": 40},
            }
        }
    )
    response = SimpleNamespace(llm_output={}, generations=[[SimpleNamespace(message=message)]])

    usage = _extract_usage(response)

    assert usage is not None
    assert usage["prompt_tokens"] == 120
    assert usage["prompt_tokens_details"]["cached_tokens"] == 40
