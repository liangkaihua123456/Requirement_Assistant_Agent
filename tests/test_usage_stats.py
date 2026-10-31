"""Aggregation for the usage statistics page."""

from __future__ import annotations

from datetime import datetime, timezone

from app.tools.usage_stats import build_usage_stats


def _record() -> dict:
    return {
        "task_id": "task-a",
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "completed",
        "user_input": "示例需求",
        "duration_seconds": 60.0,
        "usage": {
            "total": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
                "cached_tokens": 20,
                "calls": 2,
            },
            "by_model": {
                "deepseek-flash": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150,
                    "cached_tokens": 20,
                    "calls": 2,
                }
            },
            "by_role": {
                "engineer": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150,
                    "cached_tokens": 20,
                    "calls": 2,
                }
            },
            "cost_cny": 0.01,
            "priced": True,
        },
    }


def test_summary_and_series_length():
    stats = build_usage_stats([_record()], days=7)

    assert stats["summary"]["requests"] == 1
    assert stats["summary"]["total_tokens"] == 150
    assert stats["summary"]["calls"] == 2
    assert stats["summary"]["cache_hit_rate"] == 0.2
    assert len(stats["series"]) == 7
    assert stats["series"][-1]["date"] == datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert stats["series"][-1]["input"] == 100


def test_model_cost_is_recomputed_when_bucket_lacks_cost(monkeypatch):
    from app.core.config import DEFAULT_MODEL_PRICING

    monkeypatch.setattr("app.core.usage.get_pricing", lambda: DEFAULT_MODEL_PRICING)
    monkeypatch.setattr("app.core.usage.is_peak_hour", lambda moment=None: True)
    stats = build_usage_stats([_record()], days=7)
    model = stats["by_model"][0]

    # 高峰价：80 未命中 * 2 + 20 命中 * 0.04 + 50 输出 * 8 = 0.000561 元
    assert model["key"] == "deepseek-flash"
    assert model["cost_cny"] == 0.000561


def test_role_cost_is_allocated_from_task_total():
    stats = build_usage_stats([_record()], days=7)
    role = stats["by_role"][0]

    assert role["label"] == "工程实现"
    assert role["cost_cny"] == 0.01


def test_empty_records_return_zeroed_summary():
    stats = build_usage_stats([], days=7)

    assert stats["summary"]["total_tokens"] == 0
    assert stats["summary"]["cost_cny"] == 0.0
    assert stats["by_model"] == []
    assert len(stats["series"]) == 7
