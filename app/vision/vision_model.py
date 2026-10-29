"""多模态模型通道：把图片直接交给视觉模型，一次调用拿到结构化需求。

走 OpenAI 兼容的 ``/chat/completions``，因此 DashScope（qwen-vl-max）、
智谱（glm-4v）、火山方舟（doubao-vision）、DeepSeek（deepseek-flash）等只要能
接收 ``image_url`` 就能接入。``vision`` 角色留空时继承全局模型——只要该模型
支持图片输入即可生效；不支持时调用会失败，编排层自动降级到本地 OCR。
"""

from __future__ import annotations

import json
import re

import httpx
from json_repair import repair_json

from app.core.config import get_settings
from app.core.logger import logger
from app.core.model_router import resolve_profile

PROMPT = """你是需求提取助手。用户上传的图片可能是需求文档截图、聊天记录、手写笔记或原型草图。

请完成两件事：
1. 尽可能完整地转录图片中的文字，保持原有顺序和换行，不要臆造内容；
2. 在此基础上整理出可用于软件需求分析的结构化信息。若图片内容与软件需求无关，按实际内容填写 goal，features 留空数组。

只输出一个 JSON 对象，不要 Markdown 代码块，不要解释：
{
  "title": "需求标题，不超过 20 字",
  "goal": "产品目标，一到两句话",
  "features": ["核心功能，一行一条"],
  "constraints": ["技术栈、合规、预算、时间等约束，没有则为空数组"],
  "audience": "目标用户，没有则空字符串",
  "raw_text": "图片中的完整文字"
}"""


class VisionUnavailable(Exception):
    """视觉通道未配置或不可用。"""


class VisionCallFailed(Exception):
    """已配置但调用失败（网络、鉴权、限流、返回不可解析）。"""


def is_configured() -> bool:
    """vision 角色解析出模型与密钥即可用，显式配置与继承全局同等对待。

    早期版本要求 ``is_override`` 才算启用，理由是担心继承到纯文本模型。但
    DeepSeek 的 ``deepseek-flash`` 已经支持图片输入，继承本应生效；把"继承"
    一律判为未配置会白白绕过可用的视觉通道。真的不支持时，调用会返回 4xx，
    编排层自动降级到本地 OCR，代价只有一次快速失败。
    """
    try:
        profile = resolve_profile("vision")
    except Exception:
        return False
    return bool(profile.model.strip() and profile.api_key.strip())


def _endpoint(api_base: str) -> str:
    base = api_base.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _extract_json(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end <= start:
        raise VisionCallFailed("模型未返回 JSON")
    fragment = stripped[start : end + 1]
    try:
        data = json.loads(fragment)
    except json.JSONDecodeError:
        data = repair_json(fragment, return_objects=True)
    if not isinstance(data, dict):
        raise VisionCallFailed("模型返回的结构无法解析")
    return data


async def analyze(prepared) -> dict:
    """调用视觉模型。失败抛异常，由编排层决定是否降级。"""
    if not is_configured():
        raise VisionUnavailable("未配置视觉模型")

    settings = get_settings()
    profile = resolve_profile("vision")
    payload = {
        "model": profile.model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": prepared.data_url}},
                ],
            }
        ],
        "temperature": 0.1,
        "max_tokens": min(profile.max_tokens or 2048, 4096),
    }
    headers = {
        "Authorization": f"Bearer {profile.api_key}",
        "Content-Type": "application/json",
    }

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=settings.vision_timeout_seconds) as client:
                response = await client.post(
                    _endpoint(profile.api_base), json=payload, headers=headers
                )
            if response.status_code >= 500 or response.status_code == 429:
                last_error = VisionCallFailed(f"HTTP {response.status_code}")
                if attempt == 0:
                    continue
                raise last_error
            if response.status_code >= 400:
                raise VisionCallFailed(f"HTTP {response.status_code}: {response.text[:200]}")
            data = response.json()
            break
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = VisionCallFailed(f"网络异常: {type(exc).__name__}")
            if attempt == 0:
                continue
            raise last_error
    else:  # pragma: no cover - 循环必然 break 或 raise
        raise last_error or VisionCallFailed("调用失败")

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise VisionCallFailed("响应缺少 choices 内容")
    if isinstance(content, list):
        content = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))

    result = _extract_json(str(content))
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    result["_usage"] = {
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
        "cached_tokens": int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0),
    }
    logger.info(
        "Vision channel ok",
        extra={"model": profile.model, "chars": len(str(content))},
    )
    return result
