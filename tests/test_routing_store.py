"""Persistence of role routing configured from the settings page."""

from __future__ import annotations

from app.core import routing_store


def _reset(tmp_path, monkeypatch):
    monkeypatch.setattr(routing_store, "_FILE", tmp_path / "model_routing.json")
    monkeypatch.setattr(routing_store, "_cache", None)


def test_saved_override_wins_over_env(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)

    routing_store.save_overrides(
        {
            "planner": {
                "model": "ui-model",
                "api_base": "https://ui.example.com/v1",
                "api_key": "ui-key",
                "max_tokens": 4096,
                "reasoning_effort": "low",
            }
        }
    )

    from app.core.model_router import resolve_profile

    profile = resolve_profile("planner")
    assert profile.model == "ui-model"
    assert profile.api_base == "https://ui.example.com/v1"
    assert profile.api_key == "ui-key"
    assert profile.max_tokens == 4096
    assert profile.reasoning_effort == "low"
    assert profile.is_override is True


def test_empty_api_key_keeps_previous_value(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)

    routing_store.save_overrides({"engineer": {"model": "m1", "api_key": "secret-1"}})
    routing_store.save_overrides({"engineer": {"model": "m1", "api_key": ""}})

    assert routing_store.stored_overrides()["engineer"]["api_key"] == "secret-1"


def test_clearing_model_falls_back_to_global(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)

    routing_store.save_overrides({"reviewer": {"model": "custom"}})
    routing_store.save_overrides({"reviewer": {"model": ""}})

    from app.core.model_router import resolve_profile

    profile = resolve_profile("reviewer")
    assert profile.is_override is False


def test_mask_key_hides_middle():
    assert routing_store.mask_key("sk-1234567890abcdef") == "sk-1******cdef"
    assert routing_store.mask_key("short") == "*****"
    assert routing_store.mask_key("") == ""
