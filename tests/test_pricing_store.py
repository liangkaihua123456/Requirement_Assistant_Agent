"""Price table, peak/off-peak billing, and manual override precedence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.usage import UsageRecord, estimate_cost, is_peak_hour

BJ = timezone(timedelta(hours=8))


def test_builtin_deepseek_prices_are_cny_peak_rates():
    """官方价目表以人民币列出高峰单价，空闲时段为半价。"""
    from app.core.config import DEFAULT_MODEL_PRICING

    flash = DEFAULT_MODEL_PRICING["deepseek-flash"]
    assert flash.currency == "CNY"
    assert (flash.input, flash.cached_input, flash.output) == (2.0, 0.04, 8.0)

    pro = DEFAULT_MODEL_PRICING["deepseek-v4-pro"]
    assert pro.currency == "CNY"
    assert (pro.input, pro.cached_input, pro.output) == (9.0, 0.30, 27.0)


def test_peak_windows_use_beijing_time():
    # 2026-10-23 是周五
    assert is_peak_hour(datetime(2026, 10, 23, 8, 59, tzinfo=BJ)) is False
    assert is_peak_hour(datetime(2026, 10, 23, 9, 0, tzinfo=BJ)) is True
    assert is_peak_hour(datetime(2026, 10, 23, 11, 59, tzinfo=BJ)) is True
    assert is_peak_hour(datetime(2026, 10, 23, 12, 0, tzinfo=BJ)) is False
    assert is_peak_hour(datetime(2026, 10, 23, 14, 0, tzinfo=BJ)) is True
    assert is_peak_hour(datetime(2026, 10, 23, 17, 59, tzinfo=BJ)) is True
    assert is_peak_hour(datetime(2026, 10, 23, 18, 0, tzinfo=BJ)) is False
    # 周六全天空闲
    assert is_peak_hour(datetime(2026, 10, 24, 10, 0, tzinfo=BJ)) is False


def test_peak_cost_is_double_off_peak(tmp_path, monkeypatch):
    from app.core import pricing_store

    monkeypatch.setattr(pricing_store, "_FILE", tmp_path / "pricing.json")
    monkeypatch.setattr(pricing_store, "_cache", None)

    def cost_at(moment: datetime) -> float:
        record = UsageRecord(
            role="",
            model="deepseek-flash",
            prompt_tokens=1_000_000,
            completion_tokens=0,
            total_tokens=1_000_000,
            cached_tokens=0,
            at=moment,
        )
        amount, known = estimate_cost(record)
        assert known
        return amount

    assert cost_at(datetime(2026, 10, 23, 10, 0, tzinfo=BJ)) == pytest.approx(2.0)
    assert cost_at(datetime(2026, 10, 23, 21, 0, tzinfo=BJ)) == pytest.approx(1.0)

    # 输出价同样分时
    output_peak = UsageRecord(
        role="", model="deepseek-flash", prompt_tokens=0, completion_tokens=1_000_000,
        total_tokens=1_000_000, cached_tokens=0,
        at=datetime(2026, 10, 23, 10, 0, tzinfo=BJ),
    )
    assert estimate_cost(output_peak)[0] == pytest.approx(8.0)


def test_cached_input_uses_cache_rate(tmp_path, monkeypatch):
    from app.core import pricing_store

    monkeypatch.setattr(pricing_store, "_FILE", tmp_path / "pricing.json")
    monkeypatch.setattr(pricing_store, "_cache", None)

    record = UsageRecord(
        role="", model="deepseek-flash", prompt_tokens=1_000_000, completion_tokens=0,
        total_tokens=1_000_000, cached_tokens=1_000_000,
        at=datetime(2026, 10, 23, 10, 0, tzinfo=BJ),
    )
    assert estimate_cost(record)[0] == pytest.approx(0.04)


def test_parse_litellm_converts_per_token_to_per_million():
    from app.core.pricing_sync import parse_litellm_prices

    data = {
        "gpt-6.1-sol": {
            "input_cost_per_token": 0.000002,
            "output_cost_per_token": 0.00001,
            "cache_read_input_token_cost": 0.0000001,
        }
    }

    prices = parse_litellm_prices(data)

    assert prices["gpt-6.1-sol"]["input"] == 2.0
    assert prices["gpt-6.1-sol"]["output"] == 10.0
    assert prices["gpt-6.1-sol"]["cached_input"] == 0.1


def test_litellm_falls_back_to_mirror(monkeypatch):
    """GitHub raw 被重置连接时应自动换 CDN，而不是整次同步失败。"""
    from app.core import pricing_sync

    calls: list[str] = []

    class FakeResponse:
        def __init__(self, ok: bool):
            self.ok = ok

        def raise_for_status(self):
            if not self.ok:
                raise ConnectionResetError("WinError 10054")

        def json(self):
            return {
                "gpt-6.1-sol": {
                    "input_cost_per_token": 0.000002,
                    "output_cost_per_token": 0.00001,
                }
            }

    def fake_get(url, **kwargs):
        calls.append(url)
        return FakeResponse("jsdelivr" in url)

    monkeypatch.setattr(pricing_sync.httpx, "get", fake_get)

    prices = pricing_sync.fetch_litellm_prices()

    assert len(calls) == 2
    assert "raw.githubusercontent.com" in calls[0]
    assert prices["gpt-6.1-sol"]["input"] == 2.0


def test_litellm_reports_all_sources_failed(monkeypatch):
    from app.core import pricing_sync

    def fake_get(url, **kwargs):
        raise ConnectionResetError("blocked")

    monkeypatch.setattr(pricing_sync.httpx, "get", fake_get)

    with pytest.raises(RuntimeError) as excinfo:
        pricing_sync.fetch_litellm_prices()
    assert "raw.githubusercontent.com" in str(excinfo.value)


def test_sync_does_not_override_manual_price(tmp_path, monkeypatch):
    from app.core import pricing_store

    monkeypatch.setattr(pricing_store, "_FILE", tmp_path / "pricing.json")
    monkeypatch.setattr(pricing_store, "_cache", None)

    pricing_store.save(
        {"deepseek-flash": {"input": 9, "cached_input": 9, "output": 9, "currency": "CNY"}},
        manual=True,
    )
    pricing_store.save(
        {"deepseek-flash": {"input": 1, "cached_input": 1, "output": 1, "currency": "CNY"}},
        manual=False,
    )

    stored = pricing_store.get_models_raw()["deepseek-flash"]
    assert stored["input"] == 9
    assert stored["manual"] is True


def test_legacy_usd_deepseek_entries_are_removed(tmp_path, monkeypatch):
    """早期同步把人民币价标成了 USD，迁移后应回落到内置 CNY 价。"""
    from app.core import pricing_store

    monkeypatch.setattr(pricing_store, "_FILE", tmp_path / "pricing.json")
    monkeypatch.setattr(pricing_store, "_cache", None)

    pricing_store.save(
        {"deepseek-flash": {"input": 0.15, "cached_input": 0.003, "output": 0.6, "currency": "USD"}}
    )
    assert pricing_store.migrate_deepseek_currency() == 1
    assert "deepseek-flash" not in pricing_store.get_models_raw()

    flash = pricing_store.get_pricing()["deepseek-flash"]
    assert flash.currency == "CNY"
    assert flash.input == 2.0
