"""Runtime settings persisted outside .env.

Only values an operator changes while the service is running belong here.
Static configuration stays in app.core.config.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_PATH = Path(__file__).resolve().parents[2] / "data" / "app_settings.json"

DEFAULTS: dict[str, Any] = {}


def _read() -> dict[str, Any]:
    if not _PATH.exists():
        return {}
    try:
        return json.loads(_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write(data: dict[str, Any]) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_setting(key: str) -> Any:
    with _LOCK:
        data = _read()
    return data.get(key, DEFAULTS.get(key))


def set_setting(key: str, value: Any) -> None:
    with _LOCK:
        data = _read()
        data[key] = value
        _write(data)
