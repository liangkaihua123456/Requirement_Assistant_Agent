"""LLM 模型接入层 —— 统一管理 ChatOpenAI 实例。

适配 langchain-openai >= 1.1。
单次输出达到上限时，在同一段对话里续写并拼接，直到得到完整结构化结果。
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from json_repair import repair_json
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.core.logger import logger


def _provider_extra_body() -> dict | None:
    """Disable thinking modes that conflict with structured tool_choice."""
    settings = get_settings()
    base_url = settings.openai_api_base.lower()
    model_name = settings.openai_model_name.lower()
    thinking_model_prefixes = ("qwen3", "glm-5")
    if "dashscope" in base_url and model_name.startswith(thinking_model_prefixes):
        return {"enable_thinking": False}
    if "deepseek" in base_url or model_name.startswith("deepseek"):
        return {"thinking": {"type": "disabled"}}
    return None


@lru_cache()
def get_llm(temperature: float = 0.3) -> ChatOpenAI:
    """获取默认 LLM 实例。"""
    settings = get_settings()
    return ChatOpenAI(
        model=settings.openai_model_name,
        api_key=settings.openai_api_key,
        base_url=settings.openai_api_base,
        temperature=temperature,
        max_tokens=settings.openai_max_tokens,
        timeout=settings.openai_timeout_seconds,
        max_retries=2,
        extra_body=_provider_extra_body(),
    )


def get_creative_llm() -> ChatOpenAI:
    """获取用于创意/方案生成的高 temperature LLM。"""
    settings = get_settings()
    return ChatOpenAI(
        model=settings.openai_model_name,
        api_key=settings.openai_api_key,
        base_url=settings.openai_api_base,
        temperature=0.7,
        max_tokens=settings.openai_max_tokens,
        timeout=settings.openai_timeout_seconds,
        max_retries=2,
        extra_body=_provider_extra_body(),
    )


class _ContinuableStructuredLLM:
    """结构化调用。输出被 token 上限截断时，沿同一段对话续写并拼接。"""

    def __init__(self, llm: ChatOpenAI, schema: type[BaseModel], method: str, max_continuations: int):
        self._llm = llm
        self._schema = schema
        self._method = method
        self._max_continuations = max(0, max_continuations)
        self._structured = llm.with_structured_output(schema, method=method, include_raw=True)

    def invoke(self, messages: list[BaseMessage] | list[dict], config: Any = None, **kwargs: Any):
        transcript = list(messages)
        result = self._structured.invoke(transcript, config, **kwargs)
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
            f"partial_chars={len(partial)} max_rounds={self._max_continuations}"
        )
        transcript.append(AIMessage(content=partial))
        repair_attempts = 0
        for round_index in range(1, self._max_continuations + 1):
            problem = _schema_problem(self._schema, partial)
            has_object = isinstance(_candidate_object(partial, repair=True), dict)
            # Valid JSON object that fails schema: at most one repair pass.
            # Further "continuations" usually corrupt the payload further.
            if has_object and not limited:
                if repair_attempts >= 1:
                    logger.info(
                        "结构化输出已是完整 JSON 但 schema 不通过，停止续写 "
                        f"problem={problem[:180]}"
                    )
                    break
                repair_attempts += 1
                prompt = _repair_prompt(partial, problem)
            else:
                prompt = _continue_prompt(partial) if limited else _repair_prompt(partial, problem)
            transcript.append(HumanMessage(content=prompt))
            response = self._llm.invoke(transcript, config, **kwargs)
            piece = _message_text(response)
            if not piece.strip():
                logger.warning(f"结构化输出续写第 {round_index} 轮没有返回文本")
                break
            strict_piece = _parse_schema(self._schema, piece, repair=False)
            if strict_piece is not None:
                return strict_piece
            # If the model rewrote a full JSON object, prefer it over naive concat.
            rewritten = _parse_schema(self._schema, piece, repair=True)
            if rewritten is not None:
                return rewritten
            if isinstance(_candidate_object(piece, repair=True), dict) and len(piece) >= len(partial) * 0.6:
                partial = piece
            else:
                partial = _join_continuation(partial, piece)
            limited = _is_length_limited(response)
            recovered = _parse_schema(self._schema, partial, repair=not limited)
            logger.info(
                "结构化输出续写完成 "
                f"round={round_index} finish={_finish_reason(response)} chars={len(partial)} "
                f"parsed={recovered is not None} problem={problem[:180]}"
            )
            if recovered is not None:
                return recovered
            transcript.append(response)
        return _parse_schema(self._schema, partial)


def get_structured_llm(schema, *, temperature: float = 0.3, method: str | None = None):
    """获取可续写的结构化 LLM。

    返回值与原先一样，是 Pydantic 模型实例。单次输出被截断时，
    会把已生成内容放回同一段对话并继续补写。
    """
    settings = get_settings()
    structured_method = method or settings.structured_output_method
    return _ContinuableStructuredLLM(
        get_llm(temperature),
        schema,
        structured_method,
        settings.structured_output_max_continuations,
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
    except ValidationError as exc:
        # One more pass after json-repair may still leave mild type drift;
        # let schema field validators coerce common list/object mismatches.
        try:
            repaired = repair_json(json.dumps(data, ensure_ascii=False), return_objects=True)
            if isinstance(repaired, dict):
                return schema.model_validate(repaired)
        except ValidationError as exc2:
            logger.info(f"结构化输出 schema 校验失败: {str(exc2)[:240]}")
            return None
        except Exception:
            logger.info(f"结构化输出 schema 校验失败: {str(exc)[:240]}")
            return None
        logger.info(f"结构化输出 schema 校验失败: {str(exc)[:240]}")
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


def get_llm_with_tools(tools: list, *, temperature: float = 0.3) -> ChatOpenAI:
    """获取绑定工具的 LLM 实例，供 tool calling 循环使用。

    qwen-max 通过 DashScope OpenAI 兼容接口支持 function calling，
    格式与 OpenAI 一致，bind_tools() 可直接使用。
    每次调用返回新的绑定实例（bind_tools 不可缓存，因为 tools 列表可变），
    但底层 ChatOpenAI 实例复用 get_llm() 的 lru_cache。
    """
    return get_llm(temperature).bind_tools(tools)
