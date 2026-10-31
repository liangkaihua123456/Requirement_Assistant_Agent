"""Model price storage.

Resolution order: manually edited values in ``data/model_pricing.json`` >
``MODEL_PRICING_JSON`` from the environment > built-in defaults. Sync metadata
(last run, source, errors) lives in the same file.
"""

from __future__ import annotations

import json
import threading
from typing import Any

from app.core.config import BASE_DIR, DEFAULT_MODEL_PRICING, ModelPrice, get_settings

_LOCK = threading.Lock()
_FILE = BASE_DIR / "data" / "model_pricing.json"
_cache: dict[str, Any] | None = None

_PRICE_FIELDS = ("input", "cached_input", "output")


def _read() -> dict[str, Any]:
    global _cache
    if _cache is not None:
        return _cache
    if _FILE.exists():
        try:
            parsed = json.loads(_FILE.read_text(encoding="utf-8"))
            _cache = parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, OSError):
            _cache = {}
    else:
        _cache = {}
    return _cache


def get_pricing() -> dict[str, ModelPrice]:
    pricing = dict(DEFAULT_MODEL_PRICING)
    pricing.update(get_settings().model_pricing)
    for model, raw in (_read().get("models") or {}).items():
        try:
            pricing[model] = ModelPrice(**raw)
        except (TypeError, ValueError):
            continue
    return pricing


def get_models_raw() -> dict[str, dict[str, Any]]:
    return dict(_read().get("models") or {})


def get_meta() -> dict[str, Any]:
    return dict(_read().get("meta") or {})


def save(
    models: dict[str, dict[str, Any]],
    meta: dict[str, Any] | None = None,
    manual: bool = False,
) -> None:
    """Merge prices into the store. Sync never overwrites manual edits."""
    global _cache
    with _LOCK:
        data = json.loads(json.dumps(_read() or {}))
        bucket = data.setdefault("models", {})
        for name, entry in models.items():
            previous = bucket.get(name) or {}
            if not manual and previous.get("manual"):
                continue
            payload = {field: float(entry.get(field) or 0) for field in _PRICE_FIELDS}
            # 人民币价目表必须保留 CNY，否则会被当成美元再乘一次汇率
            payload["currency"] = str(entry.get("currency") or "CNY").upper()
            payload["manual"] = True if manual else bool(previous.get("manual"))
            bucket[name] = payload
        if meta is not None:
            data["meta"] = meta
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        _FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        _cache = data


def migrate_deepseek_currency() -> int:
    """清掉早期自动同步写下的 DeepSeek USD 条目。

    那次同步把人名币数值当成了美元，并按汇率再乘一次，同时丢掉了高峰/空闲
    的区别。内置价目表已经是官方人民币高峰价，删掉这些条目即可回落过去。
    手工改过的条目保留，避免覆盖用户自己的校准结果。
    """
    global _cache
    removed = 0
    with _LOCK:
        data = json.loads(json.dumps(_read() or {}))
        bucket = data.get("models") or {}
        for name in list(bucket):
            entry = bucket.get(name) or {}
            if not str(name).lower().startswith("deepseek"):
                continue
            if str(entry.get("currency", "")).upper() != "USD":
                continue
            if entry.get("manual"):
                continue
            bucket.pop(name)
            removed += 1
        if removed:
            _cache = data
            _FILE.parent.mkdir(parents=True, exist_ok=True)
            _FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return removed
