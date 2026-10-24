"""Lightweight task and node observability helpers."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from langgraph.errors import GraphInterrupt

from app.core.cancellation import TaskCancelled, is_cancelled
from app.core.logger import logger
from app.core.usage import start_tracking, stop_tracking


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def trace_node(node_name: str, llm_calls: int = 0):
    """Wrap a LangGraph node and append runtime metrics to its output.

    ``llm_calls`` is only a fallback for calls that bypass the LLM factory.
    Normal calls are counted from recorded token usage, so nodes without an LLM
    call no longer inflate the counter.
    """

    def decorator(func: Callable[[dict], dict]):
        def wrapper(state: dict) -> dict:
            task_id = str(state.get("task_id") or "")
            if task_id and is_cancelled(task_id):
                raise TaskCancelled(task_id)

            started = time.perf_counter()
            usage_token = start_tracking(task_id=task_id, node=node_name)
            try:
                result = func(state)
            except GraphInterrupt:
                raise
            except TaskCancelled:
                raise
            except Exception:
                duration = time.perf_counter() - started
                _record_error(state, node_name, duration)
                raise
            finally:
                usage = stop_tracking(usage_token)

            duration = time.perf_counter() - started
            if not isinstance(result, dict):
                return result

            metadata = dict(state.get("metadata") or {})
            metadata.update(result.get("metadata") or {})
            metrics = dict(metadata.get("metrics") or {})
            node_latencies = list(metrics.get("node_latencies") or [])
            node_latencies.append({"node": node_name, "duration_seconds": round(duration, 4)})
            metrics["node_latencies"] = node_latencies
            metrics["node_latency_seconds"] = round(
                sum(item["duration_seconds"] for item in node_latencies) / len(node_latencies),
                4,
            )
            previous_calls = int(metrics.get("llm_call_count") or 0)
            metrics.setdefault("node_error_count", 0)

            if usage:
                usage_summary = usage.summary()
                per_node = dict(metrics.get("token_usage_by_node") or {})
                per_node[node_name] = usage_summary
                metrics["token_usage_by_node"] = per_node
                metrics["token_usage"] = _merge_usage(metrics.get("token_usage"), usage_summary)
                # Actual call count beats the static per-node hint.
                metrics["llm_call_count"] = previous_calls + len(usage.records)
            else:
                metrics["llm_call_count"] = previous_calls + llm_calls

            metadata["metrics"] = metrics

            logs = list(result.get("execution_logs") or [])
            logs.append(
                {
                    "node": node_name,
                    "timestamp": utc_now_iso(),
                    "duration_seconds": round(duration, 4),
                    "event": "node_completed",
                }
            )
            result["metadata"] = metadata
            result["execution_logs"] = logs
            return result

        return wrapper

    return decorator


def merge_task_metric(state_snapshot: dict[str, Any] | None, **metrics: Any) -> dict[str, Any]:
    state = dict(state_snapshot or {})
    metadata = dict(state.get("metadata") or {})
    current = dict(metadata.get("metrics") or {})
    current.update({key: value for key, value in metrics.items() if value is not None})
    metadata["metrics"] = current
    state["metadata"] = metadata
    return state


def extract_metrics(state_snapshot: dict[str, Any] | None) -> dict[str, Any]:
    return dict(((state_snapshot or {}).get("metadata") or {}).get("metrics") or {})


def _record_error(state: dict, node_name: str, duration: float) -> None:
    metadata = dict(state.get("metadata") or {})
    metrics = dict(metadata.get("metrics") or {})
    metrics["node_error_count"] = int(metrics.get("node_error_count") or 0) + 1
    metadata["metrics"] = metrics
    logger.error(
        "Node execution failed",
        extra={
            "node": node_name,
            "duration_seconds": round(duration, 4),
            "task_id": state.get("task_id", ""),
        },
    )


_USAGE_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens", "calls")


def _merge_usage(existing: dict[str, Any] | None, incoming: dict[str, Any]) -> dict[str, Any]:
    """Accumulate a node's usage into the task-level totals."""
    if not existing:
        return incoming
    return {
        "total": _sum_bucket(existing.get("total"), incoming.get("total")),
        "by_role": _merge_buckets(existing.get("by_role"), incoming.get("by_role")),
        "by_model": _merge_buckets(existing.get("by_model"), incoming.get("by_model")),
        "cost_cny": round(
            float(existing.get("cost_cny") or 0) + float(incoming.get("cost_cny") or 0), 6
        ),
        "priced": bool(existing.get("priced", True)) and bool(incoming.get("priced", True)),
    }


def _sum_bucket(a: dict[str, Any] | None, b: dict[str, Any] | None) -> dict[str, int]:
    left, right = a or {}, b or {}
    return {
        field: int(left.get(field) or 0) + int(right.get(field) or 0)
        for field in _USAGE_FIELDS
    }


def _merge_buckets(
    a: dict[str, dict[str, Any]] | None,
    b: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, int]]:
    merged: dict[str, dict[str, int]] = {}
    for source in (a or {}, b or {}):
        for key, value in source.items():
            bucket = merged.setdefault(key, {field: 0 for field in _USAGE_FIELDS})
            bucket.setdefault("cost_cny", 0.0)
            for field in _USAGE_FIELDS:
                bucket[field] += int((value or {}).get(field) or 0)
            bucket["cost_cny"] = round(
                float(bucket.get("cost_cny") or 0) + float((value or {}).get("cost_cny") or 0),
                6,
            )
    return merged
