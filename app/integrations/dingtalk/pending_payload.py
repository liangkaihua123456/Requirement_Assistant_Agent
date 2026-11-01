"""waiting_human 的 pending_payload 结构与兼容读写。

规范结构::

    {
      "data": <原问题列表或评审摘要>,
      "assist_draft": "<机器人2建议回复>",
      "assist_rationale": "<补充/纠错说明>"
    }

旧数据可能仍是裸 list / dict，读取时自动兼容。
"""

from __future__ import annotations

from typing import Any


def wrap_pending_payload(
    data: Any,
    assist_draft: str = "",
    assist_rationale: str = "",
) -> dict[str, Any]:
    return {
        "data": data,
        "assist_draft": (assist_draft or "").strip(),
        "assist_rationale": (assist_rationale or "").strip(),
    }


def unwrap_pending_payload(raw: Any) -> tuple[Any, str, str]:
    """返回 (data, assist_draft, assist_rationale)。"""
    if isinstance(raw, dict) and "data" in raw:
        return (
            raw.get("data"),
            str(raw.get("assist_draft") or "").strip(),
            str(raw.get("assist_rationale") or "").strip(),
        )
    return raw, "", ""


def with_assist_draft(
    raw: Any,
    assist_draft: str,
    assist_rationale: str = "",
) -> dict[str, Any]:
    data, _, _ = unwrap_pending_payload(raw)
    return wrap_pending_payload(data, assist_draft, assist_rationale)
