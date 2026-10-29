"""LLM 模型接入层 —— 统一管理 ChatOpenAI 实例。

适配 langchain-openai >= 1.1。
单次输出达到上限时，在同一段对话里续写并拼接，直到得到完整结构化结果。
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
from json_repair import repair_json
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.core.logger import logger
from app.core.model_router import ModelProfile, resolve_profile
from app.core.usage import TokenUsageCallback


def _provider_extra_body(api_base: str, model_name: str) -> dict | None:
    """Provider-specific switches required for forced tool calling.

    DeepSeek V4.x runs in thinking mode by default and rejects ``tool_choice``
    while thinking is on, which breaks every structured output call. DashScope
    Qwen3/GLM-5 need their own flag.
    """
    base_url = api_base.lower()
    model = model_name.lower()
    if "deepseek" in base_url and model.startswith(("deepseek-flash", "deepseek-v4")):
        return {"thinking": {"type": "disabled"}}
    if "dashscope" in base_url and model.startswith(("qwen3", "glm-5")):
        return {"enable_thinking": False}
    return None


def _build_llm(profile: ModelProfile, temperature: float) -> ChatOpenAI:
    settings = get_settings()
    extra: dict = {}
    if profile.reasoning_effort:
        extra["reasoning_effort"] = profile.reasoning_effort
    kwargs: dict = {
        "model": profile.model,
        "api_key": profile.api_key,
        "base_url": profile.api_base,
        "temperature": temperature,
        "max_tokens": profile.max_tokens,
        "timeout": settings.openai_timeout_seconds,
        "max_retries": 2,
        "extra_body": _provider_extra_body(profile.api_base, profile.model),
        "callbacks": [TokenUsageCallback(profile.role, profile.model)],
    }
    if os.getenv("LLM_PAYLOAD_LOG") == "1":
        kwargs["http_client"] = httpx.Client(
            timeout=settings.openai_timeout_seconds,
            event_hooks={"request": [_log_request_payload]},
        )
    return ChatOpenAI(**kwargs, **extra)


_PAYLOAD_LOG = Path("data/logs/llm_payload.jsonl")


def _log_request_payload(request: httpx.Request) -> None:
    """Record the observable shape of each LLM request.

    Prompt-cache debugging needs to know whether two requests share a prefix,
    which tools/response_format they carried, and whether the wrapper changed
    anything between calls.
    """
    try:
        data = json.loads(request.content.decode("utf-8", "ignore"))
        messages = data.get("messages") or []
        contents = [str(item.get("content") or "") for item in messages]
        record = {
            "model": data.get("model"),
            "message_count": len(messages),
            "content_lens": [len(text) for text in contents],
            "first_head": contents[0][:120] if contents else "",
            "last_head": contents[-1][:120] if contents else "",
            "tools": [
                (item.get("function") or {}).get("name")
                for item in (data.get("tools") or [])
            ],
            "tool_choice": data.get("tool_choice"),
            "response_format": data.get("response_format"),
            "stream": data.get("stream"),
            "extra_body": data.get("thinking"),
        }
        _PAYLOAD_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _PAYLOAD_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


@lru_cache(maxsize=64)
def _cached_llm(role: str, temperature: float) -> ChatOpenAI:
    return _build_llm(resolve_profile(role), temperature)


def reload_clients() -> None:
    """Drop cached clients so saved routing changes take effect immediately."""
    _cached_llm.cache_clear()


def get_llm(temperature: float = 0.3, role: str = "default") -> ChatOpenAI:
    """获取指定角色的 LLM 实例，角色配置为空时继承全局模型。"""
    return _cached_llm(role, temperature)


def get_creative_llm(role: str = "solution") -> ChatOpenAI:
    """获取用于创意/方案生成的高 temperature LLM。"""
    return get_llm(0.7, role=role)


class _ContinuableStructuredLLM:
    """结构化调用。输出被 token 上限截断时，沿同一段对话续写并拼接。"""

    def __init__(
        self,
        llm: ChatOpenAI,
        schema: type[BaseModel],
        method: str,
        max_continuations: int,
        slim_context: bool = True,
        fallback_llm: ChatOpenAI | None = None,
    ):
        self._llm = llm
        self._schema = schema
        self._method = method
        self._max_continuations = max(0, max_continuations)
        self._slim_context = slim_context
        self._structured = llm.with_structured_output(schema, method=method, include_raw=True)
        self._fallback_llm = fallback_llm
        self._fallback_structured = (
            fallback_llm.with_structured_output(schema, method=method, include_raw=True)
            if fallback_llm is not None
            else None
        )

    def invoke(self, messages: list[BaseMessage] | list[dict], config: Any = None, **kwargs: Any):
        base = list(messages)
        active_llm = self._llm
        structured = self._structured
        try:
            result = structured.invoke(base, config, **kwargs)
        except Exception as exc:
            if self._fallback_structured is None:
                raise
            logger.warning(
                "角色模型调用失败，回退全局模型重试 "
                f"model={getattr(self._llm, 'model_name', '?')} error={str(exc)[:200]}"
            )
            active_llm = self._fallback_llm
            structured = self._fallback_structured
            result = structured.invoke(base, config, **kwargs)

        parsed = result.get("parsed") if isinstance(result, dict) else result
        if parsed is not None:
            return parsed

        raw = result.get("raw") if isinstance(result, dict) else None
        partial = _extract_partial(raw)
        limited = _is_length_limited(raw)
        if not limited:
            return _parse_schema(self._schema, partial)
        if not partial:
            return None

        logger.info(
            "结构化输出达到单次 token 上限，在同一段对话中续写 "
            f"partial_chars={len(partial)} max_rounds={self._max_continuations} "
            f"slim_context={self._slim_context}"
        )
        for round_index in range(1, self._max_continuations + 1):
            problem = _schema_problem(self._schema, partial)
            prompt = _continue_prompt(partial) if limited else _repair_prompt(partial, problem)
            # Round 1 keeps the full partial: the model needs the whole structure.
            # Later rounds only need the tail, and resending a growing transcript
            # is what makes long continuations slow.
            if self._slim_context and round_index > 1:
                context = _slim_excerpt(partial)
            else:
                context = partial
            call_messages = base + [AIMessage(content=context), HumanMessage(content=prompt)]
            response = active_llm.invoke(call_messages, config, **kwargs)
            piece = _message_text(response)
            if not piece.strip():
                logger.warning(f"结构化输出续写第 {round_index} 轮没有返回文本")
                break
            strict_piece = _parse_schema(self._schema, piece, repair=False)
            partial = piece if strict_piece is not None else _join_continuation(partial, piece)
            limited = _is_length_limited(response)
            recovered = strict_piece or _parse_schema(self._schema, partial, repair=not limited)
            logger.info(
                "结构化输出续写完成 "
                f"round={round_index} finish={_finish_reason(response)} chars={len(partial)} "
                f"parsed={recovered is not None} problem={problem[:180]}"
            )
            if recovered is not None:
                return recovered
        return _parse_schema(self._schema, partial)


def _slim_excerpt(partial: str, limit: int = 2000) -> str:
    if len(partial) <= limit:
        return partial
    return "[前文已省略，以下是已生成内容的结尾]\n" + partial[-limit:]


def get_structured_llm(
    schema,
    *,
    temperature: float = 0.3,
    method: str | None = None,
    role: str = "default",
):
    """获取可续写的结构化 LLM。

    按角色选择模型；角色模型调用失败时自动回退全局模型重试一次。
    """
    settings = get_settings()
    structured_method = method or settings.structured_output_method
    profile = resolve_profile(role)

    fallback_llm = None
    if profile.is_override and settings.model_routing_fallback_enabled:
        fallback_llm = _cached_llm("default", temperature)

    return _ContinuableStructuredLLM(
        _cached_llm(profile.role, temperature),
        schema,
        structured_method,
        settings.structured_output_max_continuations,
        slim_context=settings.continuation_slim_context_enabled,
        fallback_llm=fallback_llm,
    )


def _finish_reason(message: Any) -> str:
    metadata = getattr(message, "response_metadata", None) or {}
    return str(metadata.get("finish_reason") or metadata.get("stop_reason") or "")


def _is_length_limited(message: Any) -> bool:
    return _finish_reason(message) in {"length", "max_tokens"}


def _message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for block in content:
            if isinstance(block, str):
                chunks.append(block)
            elif isinstance(block, dict):
                chunks.append(str(block.get("text") or block.get("content") or ""))
        return "".join(chunks)
    return str(content or "")


def _extract_partial(message: Any) -> str:
    if message is None:
        return ""
    candidates: list[str] = []
    for tool_call in getattr(message, "invalid_tool_calls", None) or []:
        args = tool_call.get("args") if isinstance(tool_call, dict) else ""
        if isinstance(args, str) and args.strip():
            candidates.append(args)
    for tool_call in getattr(message, "tool_calls", None) or []:
        args = tool_call.get("args") if isinstance(tool_call, dict) else None
        if isinstance(args, dict) and args:
            candidates.append(json.dumps(args, ensure_ascii=False))
        elif isinstance(args, str) and args.strip():
            candidates.append(args)
    text = _message_text(message).strip()
    if text:
        candidates.append(text)
    return max(candidates, key=len) if candidates else ""


def _strip_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
    return re.sub(r"\s*```$", "", stripped)


def _join_continuation(existing: str, addition: str) -> str:
    addition = _strip_fence(addition)
    if not addition:
        return existing
    if len(addition) > len(existing) and existing[:80] and addition.startswith(existing[:80]):
        return addition
    tail = existing[-80:]
    tail_at = addition.find(tail) if tail else -1
    if tail_at >= 0:
        return existing + addition[tail_at + len(tail):]
    overlap_limit = min(len(existing), len(addition), 400)
    for size in range(overlap_limit, 12, -1):
        if existing.endswith(addition[:size]):
            return existing + addition[size:]
    return existing + addition


def _continue_prompt(partial: str) -> str:
    tail = partial[-160:]
    return (
        "上一条输出因为单次 token 上限被截断，请在当前对话里从截断处继续。"
        "只补写缺失的后半段，不要重复已经输出的内容，不要重新开始 JSON，"
        "不要解释，也不要使用 Markdown 代码块。"
        f"截断处最后的内容是：{tail}"
    )


def _repair_prompt(partial: str, problem: str) -> str:
    tail = partial[-200:]
    return (
        "同一段对话里的 JSON 还不能通过校验。"
        f"错误：{problem[:800]}。"
        "请只补写或替换出错位置之后的内容，不要重复已经正确的前半段，"
        "不要解释，也不要使用 Markdown 代码块。"
        f"当前文本结尾是：{tail}"
    )


def _candidate_object(text: str, *, repair: bool = True) -> Any:
    stripped = _strip_fence(text)
    start = stripped.find("{")
    if start < 0:
        return None
    fragment = stripped[start:]
    end = fragment.rfind("}")
    candidates = [fragment if end < 0 else fragment[: end + 1]]
    if end >= 0 and end + 1 < len(fragment):
        candidates.append(fragment)
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            data = repair_json(candidate, return_objects=True) if repair else None
        if isinstance(data, dict):
            return data
    return None


def _parse_schema(schema: type[BaseModel], text: str, *, repair: bool = True):
    data = _candidate_object(text, repair=repair)
    if not isinstance(data, dict):
        return None
    try:
        return schema.model_validate(data)
    except ValidationError:
        return None


def _schema_problem(schema: type[BaseModel], text: str) -> str:
    data = _candidate_object(text, repair=True)
    if not isinstance(data, dict):
        return "拼接结果不是合法 JSON 对象"
    try:
        schema.model_validate(data)
    except ValidationError as exc:
        return str(exc)
    return ""


def get_llm_with_tools(tools: list, *, temperature: float = 0.3, role: str = "default") -> ChatOpenAI:
    """获取绑定工具的 LLM 实例，供 tool calling 循环使用。

    qwen-max 通过 DashScope OpenAI 兼容接口支持 function calling，
    格式与 OpenAI 一致，bind_tools() 可直接使用。
    每次调用返回新的绑定实例（bind_tools 不可缓存，因为 tools 列表可变），
    但底层 ChatOpenAI 实例复用 _cached_llm()。
    """
    return get_llm(temperature, role=role).bind_tools(tools)
