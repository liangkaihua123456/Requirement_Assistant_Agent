"""Persist per-role model routing set from the settings page.

`.env` stays the deployment-level default. Values saved from the UI live in
``data/model_routing.json`` and take precedence, so an operator can change a
role's provider without restarting the process (the LLM client cache is cleared
after each save).
"""

from __future__ import annotations

import json
import threading

from app.core.config import BASE_DIR, ROLE_NAMES, RoleOverride, get_settings

_LOCK = threading.Lock()
_FILE = BASE_DIR / "data" / "model_routing.json"
_cache: dict[str, dict] | None = None


def _read_file() -> dict[str, dict]:
    global _cache
    if _cache is not None:
        return _cache
    if _FILE.exists():
        try:
            parsed = json.loads(_FILE.read_text(encoding="utf-8"))
            _cache = {
                key: value
                for key, value in parsed.items()
                if isinstance(value, dict) and key in ROLE_NAMES
            }
        except (json.JSONDecodeError, OSError):
            _cache = {}
    else:
        _cache = {}
    return _cache


def stored_overrides() -> dict[str, dict]:
    """Raw saved entries (may contain plaintext keys; never return to clients)."""
    return dict(_read_file())


def get_overrides() -> dict[str, RoleOverride]:
    """Effective overrides: saved values win over environment values."""
    settings = get_settings()
    merged: dict[str, RoleOverride] = {}
    for role in ROLE_NAMES:
        env_value = settings.role_overrides.get(role)
        if env_value is not None:
            merged[role] = env_value.model_copy()

    for role, raw in _read_file().items():
        merged[role] = RoleOverride(
            model=str(raw.get("model") or ""),
            api_base=str(raw.get("api_base") or ""),
            api_key=str(raw.get("api_key") or ""),
            max_tokens=int(raw.get("max_tokens") or 0),
            reasoning_effort=str(raw.get("reasoning_effort") or ""),
        )
    return merged


def save_overrides(payload: dict[str, dict]) -> None:
    """Merge and persist; an empty api_key keeps the previously stored one."""
    global _cache
    with _LOCK:
        data = dict(_read_file())
        for role, item in payload.items():
            if role not in ROLE_NAMES:
                continue
            previous = data.get(role) or {}
            entry = {
                "model": str(item.get("model") or "").strip(),
                "api_base": str(item.get("api_base") or "").strip(),
                "max_tokens": max(0, int(item.get("max_tokens") or 0)),
                "reasoning_effort": str(item.get("reasoning_effort") or "").strip(),
            }
            key = str(item.get("api_key") or "").strip()
            entry["api_key"] = key or str(previous.get("api_key") or "")
            data[role] = entry

        _FILE.parent.mkdir(parents=True, exist_ok=True)
        _FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        _cache = data


def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}{'*' * 6}{key[-4:]}"
