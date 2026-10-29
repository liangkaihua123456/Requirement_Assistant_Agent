"""Turn provider/runtime exceptions into actionable error kinds."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorInfo:
    kind: str
    title: str
    action: str


def classify_error(exc: Exception) -> ErrorInfo:
    text = str(exc)
    lower = text.lower()
    status = getattr(exc, "status_code", None)

    if status == 402 or "insufficient balance" in lower or "insufficient_quota" in lower:
        return ErrorInfo(
            kind="billing",
            title="模型账户余额不足",
            action="请为该供应商账户充值后点击「重试任务」继续",
        )
    if status == 401 or "invalid api key" in lower or "unauthorized" in lower:
        return ErrorInfo(
            kind="auth",
            title="API 密钥无效",
            action="请在「模型配置」中检查对应角色的密钥后重试",
        )
    if status == 429 or "rate limit" in lower or "too many requests" in lower:
        return ErrorInfo(
            kind="rate_limit",
            title="请求频率受限",
            action="等待几分钟后点击「重试任务」",
        )
    if "timeout" in lower or "timed out" in lower:
        return ErrorInfo(
            kind="timeout",
            title="模型响应超时",
            action="可降低该角色的 max_tokens 或稍后重试",
        )
    if "connection" in lower or "connect" in lower or "network" in lower:
        return ErrorInfo(
            kind="network",
            title="无法连接模型服务",
            action="检查网络与 API Base 配置后重试",
        )
    return ErrorInfo(
        kind="unknown",
        title="任务执行失败",
        action="可点击「重试任务」从失败节点继续",
    )
