"""Fetch official model prices.

Sources:

* DeepSeek — **not synced**. Its public page lists CNY with peak/off-peak tiers,
  and parsing it as USD produced prices that were wrong by a factor tied to the
  exchange rate and the time-of-day multiplier. The official list price is
  therefore built in (``DEFAULT_MODEL_PRICING``, peak rates in CNY) and can be
  edited by hand on the pricing page.
* OpenAI — the LiteLLM community price table, because openai.com blocks
  non-browser clients with 403. Values are USD per 1M tokens.

A failed source keeps the previous values and records the error instead of
zeroing prices.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.logger import logger
from app.core.pricing_store import get_meta, save

LITELLM_SOURCES = (
    # GitHub raw 在部分网络环境会被重置连接（WinError 10054），CDN 通常可达
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json",
    "https://cdn.jsdelivr.net/gh/BerriAI/litellm@main/model_prices_and_context_window.json",
    "https://fastly.jsdelivr.net/gh/BerriAI/litellm@main/model_prices_and_context_window.json",
)
SOURCE_TIMEOUT_SECONDS = 15
USER_AGENT = "Mozilla/5.0 (compatible; RequirementAgent/1.0)"

LITELLM_MODELS = ("gpt-6.1-sol",)

SYNC_INTERVAL_HOURS = 24


def needs_sync() -> bool:
    synced_at = str(get_meta().get("synced_at") or "")
    if not synced_at:
        return True
    try:
        last = datetime.fromisoformat(synced_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    age_hours = (datetime.now(timezone.utc) - last).total_seconds() / 3600
    return age_hours >= SYNC_INTERVAL_HOURS


def sync_all() -> dict[str, Any]:
    """Refresh the models that have a machine-readable source."""
    prices: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    try:
        prices.update(fetch_litellm_prices())
    except Exception as exc:
        errors.append(f"litellm: {str(exc)[:200]}")

    meta = {
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "source": "litellm (deepseek: built-in CNY peak rates)",
        "errors": errors,
        "updated_models": sorted(prices),
    }
    if prices:
        save(prices, meta=meta)
    else:
        save({}, meta=meta)

    if errors:
        # OpenAI 系拉取失败不影响 DeepSeek 内置价，提示里要说清楚，免得被当成整体故障
        logger.warning(f"Price sync completed with errors: {errors}")
    else:
        logger.info(f"Price sync completed: {sorted(prices)}")
    return {"prices": prices, "meta": meta}


def fetch_litellm_prices() -> dict[str, dict[str, Any]]:
    """按顺序尝试多个镜像，全部失败才报错。"""
    failures: list[str] = []
    for url in LITELLM_SOURCES:
        host = url.split("//", 1)[-1].split("/", 1)[0]
        try:
            response = httpx.get(
                url,
                timeout=SOURCE_TIMEOUT_SECONDS,
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT},
            )
            response.raise_for_status()
            return parse_litellm_prices(response.json())
        except Exception as exc:
            failures.append(f"{host}: {type(exc).__name__}")
    raise RuntimeError(" | ".join(failures))


def parse_litellm_prices(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for model in LITELLM_MODELS:
        entry = data.get(model)
        if not isinstance(entry, dict):
            continue
        input_cost = entry.get("input_cost_per_token")
        output_cost = entry.get("output_cost_per_token")
        if input_cost is None or output_cost is None:
            continue
        result[model] = {
            "input": round(float(input_cost) * 1_000_000, 6),
            "output": round(float(output_cost) * 1_000_000, 6),
            "cached_input": round(float(entry.get("cache_read_input_token_cost") or 0) * 1_000_000, 6),
            "currency": "USD",
        }
    if not result:
        raise ValueError("no matching models in price table")
    return result
