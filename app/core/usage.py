"""Token usage tracking and cost estimation.

Every ``ChatOpenAI`` instance created by the LLM factory carries a callback that
records token usage into a context-local accumulator **and** writes one row per
call to ``llm_usage``. ``trace_node`` opens and closes that accumulator around
each graph node, so per-node, per-role, and per-model totals are produced
without touching agent code.

Writing to the table matters more than the accumulator: node output only reaches
the database when the graph step succeeds. A node that raises after spending
200k tokens would otherwise leave no trace, and the usage page would silently
under-report real spending.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from app.core.config import get_settings
from app.core.pricing_store import get_pricing
from app.storage.usage_writer import insert_usage

# 北京时间高峰时段：工作日 9:00-12:00、14:00-18:00。其余（含周末、法定节假日）为空闲。
PEAK_RANGES = ((9, 12), (14, 18))


@dataclass
class UsageRecord:
    role: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cached_tokens: int = 0
    # 调用发生的时刻，用于判断高峰/空闲；为空时按当前时间处理。
    at: datetime | None = None


def normalize_moment(moment: datetime | None) -> datetime:
    if moment is None:
        return datetime.now(timezone.utc)
    if moment.tzinfo is None:
        # 数据库写的是 UTC naive，统一按 UTC 解释
        return moment.replace(tzinfo=timezone.utc)
    return moment


def is_peak_hour(moment: datetime | None = None) -> bool:
    """是否处于 DeepSeek 高峰计费时段。"""
    settings = get_settings()
    local = normalize_moment(moment).astimezone(
        timezone(timedelta(hours=settings.peak_timezone_offset))
    )
    if local.weekday() >= 5:
        return False
    return any(start <= local.hour < end for start, end in PEAK_RANGES)


def price_factor(moment: datetime | None, currency: str) -> float:
    """时段系数。美元计价的模型没有分时价，恒为 1。"""
    if currency.upper() == "USD":
        return 1.0
    return 1.0 if is_peak_hour(moment) else get_settings().off_peak_ratio


def estimate_cost(record: UsageRecord) -> tuple[float, bool]:
    """Return (cost in CNY, whether the model has a configured price)."""
    settings = get_settings()
    price = get_pricing().get(record.model)
    if price is None:
        return 0.0, False

    cached = min(max(record.cached_tokens, 0), record.prompt_tokens)
    uncached = max(record.prompt_tokens - cached, 0)
    factor = price_factor(record.at, price.currency)
    amount = (
        uncached * price.input
        + cached * price.cached_input
        + record.completion_tokens * price.output
    ) / 1_000_000 * factor

    if price.currency.upper() == "USD":
        amount *= settings.usd_to_cny_rate
    return amount, True


class UsageAccumulator:
    """Collects token usage for one node execution."""

    def __init__(self) -> None:
        self.records: list[UsageRecord] = []

    def add(self, record: UsageRecord) -> None:
        self.records.append(record)

    def __bool__(self) -> bool:
        return bool(self.records)

    def summary(self) -> dict[str, Any]:
        if not self.records:
            return {}

        total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cached_tokens": 0}
        by_role: dict[str, dict[str, Any]] = {}
        by_model: dict[str, dict[str, Any]] = {}
        cost_cny = 0.0
        priced = True

        for record in self.records:
            for key in total:
                total[key] += getattr(record, key)

            amount, known = estimate_cost(record)
            cost_cny += amount
            priced = priced and known

            for bucket, key in ((by_role, record.role), (by_model, record.model)):
                item = bucket.setdefault(
                    key,
                    {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                        "cached_tokens": 0,
                        "calls": 0,
                        "cost_cny": 0.0,
                    },
                )
                item["prompt_tokens"] += record.prompt_tokens
                item["completion_tokens"] += record.completion_tokens
                item["total_tokens"] += record.total_tokens
                item["cached_tokens"] += record.cached_tokens
                item["calls"] += 1
                item["cost_cny"] = round(item["cost_cny"] + amount, 6)

        return {
            "total": {**total, "calls": len(self.records)},
            "by_role": by_role,
            "by_model": by_model,
            "cost_cny": round(cost_cny, 6),
            "priced": priced,
        }


@dataclass
class UsageContext:
    """一次节点执行的记账上下文：累计器 + 归属信息。"""

    accumulator: "UsageAccumulator"
    task_id: str = ""
    node: str = ""


_current: ContextVar[UsageContext | None] = ContextVar("token_usage", default=None)


def current_usage() -> UsageAccumulator | None:
    context = _current.get()
    return context.accumulator if context else None


def current_context() -> UsageContext | None:
    return _current.get()


def start_tracking(task_id: str = "", node: str = "") -> Token:
    return _current.set(UsageContext(UsageAccumulator(), task_id=task_id, node=node))


def stop_tracking(token: Token) -> UsageAccumulator | None:
    context = _current.get()
    _current.reset(token)
    return context.accumulator if context else None


def _extract_usage(response: Any) -> dict[str, Any] | None:
    llm_output = getattr(response, "llm_output", None) or {}
    usage = llm_output.get("token_usage") or llm_output.get("usage")
    if isinstance(usage, dict) and usage:
        return usage

    for generation_list in getattr(response, "generations", []) or []:
        for generation in generation_list:
            message = getattr(generation, "message", None)
            metadata = getattr(message, "response_metadata", None) or {}
            usage = metadata.get("token_usage") or metadata.get("usage")
            if isinstance(usage, dict) and usage:
                return usage
    return None


class TokenUsageCallback(BaseCallbackHandler):
    """Records usage of one LLM instance into the current accumulator."""

    def __init__(self, role: str, model: str) -> None:
        self.role = role
        self.model = model

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        context = current_context()
        if context is None:
            return
        usage = _extract_usage(response)
        if usage is None:
            return

        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or prompt_tokens + completion_tokens)
        details = usage.get("prompt_tokens_details") or {}
        cached_tokens = int(
            details.get("cached_tokens") or usage.get("prompt_cache_hit_tokens") or 0
        )

        record = UsageRecord(
            role=self.role,
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cached_tokens=cached_tokens,
            at=datetime.now(timezone.utc),
        )
        context.accumulator.add(record)

        amount, known = estimate_cost(record)
        insert_usage(
            task_id=context.task_id,
            node=context.node,
            role=self.role,
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cached_tokens=cached_tokens,
            cost_cny=amount,
            priced=known,
            peak=is_peak_hour(record.at),
            source="agent",
        )
