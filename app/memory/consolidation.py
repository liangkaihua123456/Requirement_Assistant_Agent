"""Memory Consolidation & Conflict Detection.

Consolidation: Periodically (every N tasks) reviews recent memories, merging
similar patterns, abstracting principles, and resolving contradictions.

Conflict Detection: Before writing new memory, checks for contradictions
with existing similar memories to prevent conflicting knowledge accumulation.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import get_settings
from app.core.llm import get_llm
from app.core.logger import logger
from app.storage.memory_chroma import get_memory_store

# ── Consolidation prompt ──────────────────────────────────────

CONSOLIDATION_SYSTEM = """你是一个记忆巩固代理人。你管理一个软件工程知识库，存储着过往项目的架构案例、设计模式和评审发现。

你的任务：审查以下记忆列表，执行 4 种操作：

1. **合并 (Merge)**：如果多条记忆描述了相同或高度相似的模式/教训，合并为一条更通用的记忆。合并后的内容应比原始更抽象，覆盖所有原始案例的要点。
2. **抽象原则 (Abstract)**：如果多条记忆揭示了一个可复用的通用原则，提取为一条新的 architecture_principle。原则必须**具体、可操作**，不能是空洞的废话。
3. **解决冲突 (Resolve)**：如果两条记忆相互矛盾（例如一条推荐技术 A，另一条明确反对技术 A），判断哪条更正确。标注为 keep_a / keep_b / keep_both（如果两者在不同场景下都对）。
4. **标记过时 (Obsolete)**：如果某条记忆已经被更新的实践取代，标记为过时。

规则：
- 不要合并来自不同领域 (domain) 的记忆，除非模式确实跨领域通用（如"幂等设计"）
- 不确定时保留两条，不要强行合并
- 合并后内容用中文，长度控制在 400 字以内
- 只输出合法 JSON，不要加 markdown 代码块标记

输出 JSON：
{
  "merged": [
    {"source_ids": ["id1", "id2"], "content": "合并后的内容...", "memory_type": "architecture_pattern", "tags": "tag1,tag2", "reason": "合并理由"}
  ],
  "new_principles": [
    {"content": "原则内容...", "tags": "...", "reason": "提取理由"}
  ],
  "conflicts": [
    {"id_a": "...", "id_b": "...", "description": "矛盾描述", "resolution": "keep_a|keep_b|keep_both", "reason": "裁决理由"}
  ],
  "obsolete": [
    {"id": "...", "reason": "过时理由"}
  ]
}"""

# ── Conflict detection prompt ─────────────────────────────────

CONFLICT_DETECTION_PROMPT = """比较以下新经验与已存储的记忆，判断它们之间的关系：

新经验：
{new_content}

已存储记忆（相似度最高的）：
{existing_content}

判断关系（三选一）：
- confirms：新经验与已有记忆一致，无需操作
- contradicts：新经验在具体技术点上与已有记忆**矛盾**
- supersedes：新经验提供了更完整/更优的版本，可以取代旧记忆

只输出 JSON（不要 markdown）：
{{"verdict": "confirms|contradicts|supersedes", "reason": "一句话理由", "conflict_point": "矛盾点（仅 contradicts 时需要）"}}"""


# ── Trigger management ─────────────────────────────────────────

def _counter_path(project_id: str = "default"):
    safe = "".join(ch for ch in (project_id or "default") if ch.isalnum() or ch in "_-")[:48]
    return get_settings().data_dir / f".consolidation_counter_{safe or 'default'}"


def increment_task_counter(project_id: str = "default") -> int:
    path = _counter_path(project_id)
    count = int(path.read_text().strip() or "0") if path.exists() else 0
    count += 1
    path.write_text(str(count))
    return count


def should_consolidate(project_id: str = "default") -> bool:
    settings = get_settings()
    if not settings.memory_consolidation_enabled:
        return False
    path = _counter_path(project_id)
    if not path.exists():
        return False
    count = int(path.read_text().strip() or "0")
    return count >= settings.memory_consolidation_trigger_count


def reset_consolidation_counter(project_id: str = "default") -> None:
    _counter_path(project_id).write_text("0")


# ── Conflict Detection ────────────────────────────────────────

def detect_conflict(new_content: str, new_metadata: dict, project_id: str = "default") -> dict | None:
    """Check new memory against existing memories in the project store before writing.

    Returns a conflict info dict if contradiction/supersede detected,
    or None if the new memory is safe to write as-is.
    """
    settings = get_settings()
    mem_type = new_metadata.get("memory_type", "case")

    existing = get_memory_store(project_id).search(
        query=new_content,
        top_k=3,
        memory_types=[mem_type],
    )

    if not existing:
        return None

    best = existing[0]
    if best.get("score", 0) < settings.memory_conflict_similarity_threshold:
        return None

    prompt = CONFLICT_DETECTION_PROMPT.format(
        new_content=new_content[:1500],
        existing_content=best.get("content", "")[:1500],
    )

    try:
        llm = get_llm(temperature=0.1)
        response = llm.invoke([HumanMessage(content=prompt)])
        result = json.loads(response.content.strip())
    except (json.JSONDecodeError, Exception) as exc:
        logger.warning("Conflict detection LLM call failed", extra={"error": str(exc)[:200]})
        return None

    if result.get("verdict") == "confirms":
        logger.info("Memory conflict detection: confirms existing, skipping write")
        return {"verdict": "confirms", "reason": result.get("reason", "")}

    logger.info(
        "Memory conflict detected",
        extra={"verdict": result.get("verdict"), "score": best.get("score")},
    )
    return {
        "verdict": result.get("verdict"),
        "reason": result.get("reason", ""),
        "conflict_point": result.get("conflict_point", ""),
    }


# ── Memory Consolidation ──────────────────────────────────────

def consolidate_memories(domain: str | None = None, project_id: str = "default") -> dict:
    """Run LLM-driven memory consolidation.

    Fetches non-obsolete memories, asks the LLM to merge/abstract/resolve,
    and applies the plan back to the store.
    """
    store = get_memory_store(project_id)
    settings = get_settings()

    all_memories = store.list_all(domain=domain, limit=50)

    if len(all_memories) < 5:
        return {"status": "skipped", "reason": "too few memories", "count": len(all_memories)}

    # Build compact memory blocks
    blocks = []
    for i, mem in enumerate(all_memories):
        meta = mem.get("metadata") or {}
        blocks.append(
            f"[ID:{mem.get('id', i)}]"
            f"[TYPE:{meta.get('memory_type', '?')}]"
            f"[DOMAIN:{meta.get('domain', '?')}]"
            f"[TAGS:{meta.get('tags', '')}]\n"
            f"{mem.get('content', '')[:500]}"
        )
    memories_text = "\n\n---\n\n".join(blocks)

    max_input = settings.memory_consolidation_max_chars
    if len(memories_text) > max_input:
        memories_text = memories_text[:max_input] + "\n...[截断]"

    try:
        llm = get_llm(temperature=0.2)
        messages = [
            SystemMessage(content=CONSOLIDATION_SYSTEM),
            HumanMessage(content=f"请巩固以下记忆：\n\n{memories_text}"),
        ]
        response = llm.invoke(messages)
        plan = json.loads(response.content.strip())
    except (json.JSONDecodeError, Exception) as exc:
        logger.warning("Consolidation LLM call failed", extra={"error": str(exc)[:300]})
        return {"status": "error", "reason": str(exc)[:200]}

    result = _apply_plan(plan, project_id)
    reset_consolidation_counter(project_id)

    logger.info(
        "Memory consolidation complete",
        extra={
            "merged": result.get("merged_count", 0),
            "principles": result.get("principles_count", 0),
            "conflicts": result.get("conflicts_count", 0),
            "obsolete": result.get("obsolete_count", 0),
        },
    )
    return result


def _apply_plan(plan: dict, project_id: str = "default") -> dict:
    """Execute the consolidation plan: merge, add principles, mark obsolete."""
    store = get_memory_store(project_id)
    result = {"merged_count": 0, "principles_count": 0, "conflicts_count": 0, "obsolete_count": 0}

    default_domain = ""

    # 1. Merge
    for item in plan.get("merged") or []:
        source_ids = item.get("source_ids") or []
        new_content = item.get("content", "")
        if not new_content or len(source_ids) < 2:
            continue
        merged_id = f"consolidated_{source_ids[0]}"
        store.save(
            content=new_content,
            metadata={
                "project_id": project_id,
                "memory_type": item.get("memory_type", "architecture_pattern"),
                "domain": default_domain,
                "source": "consolidation",
                "tags": item.get("tags", ""),
                "consolidation_reason": item.get("reason", "")[:200],
            },
            memory_id=merged_id,
        )
        for sid in source_ids:
            store.update_metadata(sid, {"obsolete": True, "merged_into": merged_id})
        result["merged_count"] += 1

    # 2. New principles
    for item in plan.get("new_principles") or []:
        content = item.get("content", "")
        if not content:
            continue
        store.save(
            content=content,
            metadata={
                "project_id": project_id,
                "memory_type": "architecture_principle",
                "domain": default_domain,
                "source": "consolidation",
                "tags": item.get("tags", ""),
            },
        )
        result["principles_count"] += 1

    # 3. Conflicts
    for item in plan.get("conflicts") or []:
        result["conflicts_count"] += 1
        logger.warning("Memory conflict during consolidation", extra=item)
        resolution = item.get("resolution", "keep_both")
        id_a, id_b = item.get("id_a", ""), item.get("id_b", "")
        reason = item.get("reason", "")[:200]
        if resolution == "keep_a" and id_b:
            store.update_metadata(id_b, {"obsolete": True, "obsolete_reason": reason})
        elif resolution == "keep_b" and id_a:
            store.update_metadata(id_a, {"obsolete": True, "obsolete_reason": reason})

    # 4. Obsolete
    for item in plan.get("obsolete") or []:
        obs_id = item.get("id", "")
        if obs_id:
            store.update_metadata(obs_id, {"obsolete": True, "obsolete_reason": item.get("reason", "")[:200]})
            result["obsolete_count"] += 1

    return result
