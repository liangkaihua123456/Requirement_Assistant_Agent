"""发送钉钉文本消息的小封装（sessionWebhook）。"""

from __future__ import annotations

import httpx


async def post_text(
    http: httpx.AsyncClient,
    session_webhook: str,
    content: str,
    staff_id: str | None = None,
) -> None:
    """向钉钉消息自带的 sessionWebhook 回复文本。

    请求体格式见:
    https://open.dingtalk.com/document/orgapp/robots-send-group-messages
    """
    payload: dict = {
        "msgtype": "text",
        "text": {"content": content},
    }
    if staff_id:
        payload["at"] = {"atUserIds": [staff_id]}

    response = await http.post(session_webhook, json=payload)
    response.raise_for_status()
