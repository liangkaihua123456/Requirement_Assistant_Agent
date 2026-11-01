"""钉钉消息发送：sessionWebhook 回复 + 机器人1 OpenAPI 主动群发。"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.logger import logger

_TOKEN_CACHE: dict[str, Any] = {"key": "", "token": "", "expire_at": 0.0}


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


async def get_access_token(
    http: httpx.AsyncClient,
    app_key: str,
    app_secret: str,
) -> str:
    """获取企业内部应用 access_token（带进程内缓存）。"""
    cache_key = f"{app_key}:{app_secret}"
    now = time.time()
    if (
        _TOKEN_CACHE.get("key") == cache_key
        and _TOKEN_CACHE.get("token")
        and float(_TOKEN_CACHE.get("expire_at") or 0) > now + 60
    ):
        return str(_TOKEN_CACHE["token"])

    response = await http.post(
        "https://api.dingtalk.com/v1.0/oauth2/accessToken",
        json={"appKey": app_key, "appSecret": app_secret},
    )
    response.raise_for_status()
    body = response.json()
    token = body.get("accessToken") or body.get("access_token") or ""
    if not token:
        raise RuntimeError(f"DingTalk accessToken empty: {body}")
    expire_in = int(body.get("expireIn") or body.get("expires_in") or 7200)
    _TOKEN_CACHE.update(
        {"key": cache_key, "token": token, "expire_at": now + expire_in}
    )
    return token


async def send_group_text_as_robot(
    http: httpx.AsyncClient,
    *,
    app_key: str,
    app_secret: str,
    robot_code: str,
    open_conversation_id: str,
    content: str,
) -> None:
    """以指定企业机器人为身份，向群聊主动发送文本。"""
    if not open_conversation_id:
        raise ValueError("open_conversation_id is required")
    if not robot_code:
        raise ValueError("robot_code is required")

    token = await get_access_token(http, app_key, app_secret)
    payload = {
        "msgKey": "sampleText",
        "msgParam": json.dumps({"content": content}, ensure_ascii=False),
        "openConversationId": open_conversation_id,
        "robotCode": robot_code,
    }
    response = await http.post(
        "https://api.dingtalk.com/v1.0/robot/groupMessages/send",
        headers={"x-acs-dingtalk-access-token": token},
        json=payload,
    )
    if response.status_code >= 400:
        logger.error(
            f"DingTalk groupMessages/send failed: {response.status_code} {response.text}",
            extra={"node": "dingtalk"},
        )
    response.raise_for_status()


async def send_robot1_question(
    http: httpx.AsyncClient,
    *,
    open_conversation_id: str,
    content: str,
    settings: Settings | None = None,
) -> bool:
    """用机器人1发提问；未配置时返回 False。"""
    cfg = settings or get_settings()
    if not cfg.dingtalk_robot1_configured:
        return False
    await send_group_text_as_robot(
        http,
        app_key=cfg.dingtalk_robot1_app_key,
        app_secret=cfg.dingtalk_robot1_app_secret,
        robot_code=cfg.dingtalk_robot1_robot_code,
        open_conversation_id=open_conversation_id,
        content=content,
    )
    return True


async def send_robot2_assist(
    http: httpx.AsyncClient,
    *,
    open_conversation_id: str,
    content: str,
    settings: Settings | None = None,
) -> bool:
    """用机器人2发建议；未配置时返回 False。"""
    cfg = settings or get_settings()
    if not cfg.dingtalk_robot2_configured:
        return False
    await send_group_text_as_robot(
        http,
        app_key=cfg.dingtalk_robot2_app_key,
        app_secret=cfg.dingtalk_robot2_app_secret,
        robot_code=cfg.dingtalk_robot2_robot_code,
        open_conversation_id=open_conversation_id,
        content=content,
    )
    return True
