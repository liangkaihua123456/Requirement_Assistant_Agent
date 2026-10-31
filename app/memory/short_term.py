"""Short-term memory for within-task context retention.

Each agent node writes a structured entry after completing its work.
Subsequent nodes (especially on reflow) read the memory to understand
prior decisions, metrics, and issues without re-inspecting full artifacts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def add_entry(
    state: dict[str, Any],
    node: str,
    summary: str,
    key_decisions: list[str] | None = None,
    metrics: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Build a task_memory append entry for the state update dict.

    Automatically computes iteration by counting how many times this node
    has already appeared in task_memory (0-based: first run = iteration 0,
    first reflow = iteration 1, etc.).
    """
    existing = state.get("task_memory") or []
    same_node_count = sum(1 for e in existing if e.get("node") == node)
    entry = {
        "node": node,
        "iteration": same_node_count,
        "summary": summary.strip(),
        "key_decisions": list(key_decisions or []),
        "metrics": dict(metrics or {}),
        "warnings": list(warnings or []),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return {"task_memory": [entry]}


def format_for_prompt(
    task_memory: list[dict[str, Any]] | None,
    max_chars: int = 1200,
    max_tokens: int | None = None,
) -> str:
    """Format task_memory entries as a compact prompt block.

    - 渲染顺序为「最新在前」；超出 max_chars 时从头截断，即优先保留最新记忆
      （reflow 最依赖上一轮评审意见，旧实现会把最新条目截掉，已修复）。
    - Duplicate entries for the same node+iteration are kept only once (last wins).
    - When max_tokens is provided, uses token-aware truncation; otherwise falls back
      to character-based truncation with max_chars.
    - Returns empty string when task_memory is None or empty.
    """
    if not task_memory:
        return ""

    seen: set[tuple[str, int]] = set()
    deduped: list[dict[str, Any]] = []
    for entry in reversed(task_memory):
        key = (entry.get("node", ""), entry.get("iteration", 0))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    # 保持 newest-first：截断时保留头部 = 保留最新记忆

    if not deduped:
        return ""

    lines = ["## 任务执行记录（短期记忆）"]

    for i, entry in enumerate(deduped, 1):
        node = entry.get("node", "unknown")
        iteration = entry.get("iteration", 0)
        summary = entry.get("summary", "")
        decisions = entry.get("key_decisions") or []
        metrics = entry.get("metrics") or {}
        warns = entry.get("warnings") or []

        iter_tag = f" [Reflow #{iteration}]" if iteration > 0 else ""
        lines.append(f"{i}. [{node}]{iter_tag} {summary}")

        if decisions:
            lines.append(f"   关键决策：{'；'.join(decisions[:5])}")
        if metrics:
            kv = ", ".join(f"{k}={v}" for k, v in metrics.items())
            lines.append(f"   指标：{kv}")
        if warns:
            lines.append(f"   注意：{'；'.join(warns[:3])}")

    result = "\n".join(lines)

    if max_tokens is not None:
        from app.memory.context_compression import adaptive_truncate

        if estimate_tokens(result) > max_tokens:
            result = adaptive_truncate(result, max_tokens)
    elif len(result) > max_chars:
        result = result[: max_chars - 50].rstrip() + "\n...[短期记忆已截断]"

    return result


def estimate_tokens(text: str) -> int:
    """Re-exported from context_compression for convenience."""
    from app.memory.context_compression import estimate_tokens as _est

    return _est(text)


def format_reflow_context(
    task_memory: list[dict[str, Any]] | None,
    current_node: str,
    max_chars: int = 800,
) -> str:
    """Build reflow-specific context for an agent about to re-execute.

    Extracts:
    - The most recent entry for current_node (what it did last time)
    - The most recent reviewer entry (why it was rejected, if applicable)
    """
    if not task_memory:
        return ""

    last_own = None
    last_review = None
    for entry in reversed(task_memory):
        if last_own is None and entry.get("node") == current_node:
            last_own = entry
        if last_review is None and entry.get("node") == "reviewer":
            last_review = entry
        if last_own is not None and last_review is not None:
            break

    parts: list[str] = []
    if last_review:
        parts.append(
            f"上一轮评审结果：{last_review.get('summary', '')}\n"
            f"评分={last_review.get('metrics', {}).get('overall_score', '?')} "
            f"通过={last_review.get('metrics', {}).get('passed', '?')}"
        )
        if last_review.get("warnings"):
            parts.append("评审发现的问题：")
            for w in last_review["warnings"][:5]:
                parts.append(f"  - {w}")

    if last_own:
        parts.append(
            f"你上次产出：{last_own.get('summary', '')}\n"
            f"关键决策：{'；'.join(last_own.get('key_decisions', [])[:5]) or '无'}"
        )

    result = "\n".join(parts)
    if len(result) > max_chars:
        result = result[: max_chars - 30].rstrip() + "\n...[reflow上下文已截断]"
    return result
