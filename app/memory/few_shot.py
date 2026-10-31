"""Dynamic Few-shot — retrieve successful historical cases from ChromaDB
and format them as structured input→output examples for prompt injection.

Unlike the existing tool-calling-based `{memory_context}` (LLM optionally
searches), this module does **systematic** retrieval — every agent prep
phase calls it, ensuring few-shot examples are always present.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.storage.repo_memory import search_memory_sync


def resolve_memory_enabled(metadata: dict | None = None) -> bool:
    """Single source of truth for the memory switch.

    A per-task ``metadata.memory_enabled`` value overrides the global setting
    so a task can opt in or out without restarting the process.
    """
    if metadata and "memory_enabled" in metadata:
        return bool(metadata.get("memory_enabled"))
    return bool(get_settings().memory_enabled)


def retrieve_few_shot_examples(
    query: str,
    top_k: int | None = None,
    memory_types: list[str] | None = None,
    enabled: bool | None = None,
) -> list[dict]:
    """Retrieve high-quality cases from ChromaDB for few-shot use.

    Only returns cases with overall_score >= few_shot_min_score (default 7.0).
    Over-fetches by 3x to allow for quality filtering down to top_k.

    When memory is disabled this returns immediately: building a few-shot
    block used to open a Chroma client and seed it on every agent call even
    with MEMORY_ENABLED=false.
    """
    settings = get_settings()
    if enabled is None:
        enabled = settings.memory_enabled
    if not enabled:
        return []

    top_k = top_k if top_k is not None else settings.few_shot_top_k
    memory_types = memory_types or ["case"]

    hits = search_memory_sync(
        query=query,
        top_k=max(1, top_k * 3),
        memory_types=memory_types,
    )

    min_score = settings.few_shot_min_score
    filtered = [
        h
        for h in hits
        if float((h.get("metadata") or {}).get("overall_score") or 0) >= min_score
    ]
    return filtered[:top_k]


def format_few_shot(
    cases: list[dict],
    max_chars: int | None = None,
) -> str:
    """Format retrieved cases as few-shot examples for prompt injection.

    Each case is rendered as:
    ### 案例 N：{product_name}（评分 {score}/10）
    **需求场景**：...
    **技术方案要点**：...

    Returns empty string for empty cases list.
    """
    if not cases:
        return ""

    settings = get_settings()
    max_chars = max_chars if max_chars is not None else settings.few_shot_max_chars

    lines = [
        "## 历史成功案例（供参考，请模仿其结构深度和追溯粒度）",
        "",
    ]

    for i, case in enumerate(cases, 1):
        meta = case.get("metadata") or {}
        content = case.get("content") or ""
        product_name = meta.get("product_name") or f"案例{i}"
        domain = meta.get("domain") or ""
        score = meta.get("overall_score") or "?"

        domain_tag = f" [{domain}]" if domain else ""
        lines.append(f"### 案例 {i}：{product_name}{domain_tag}（评分 {score}/10）")
        lines.append("")

        # Parse the structured content from ChromaDB case summary
        _render_case_body(lines, content)

        lines.append("")

    result = "\n".join(lines)
    if len(result) > max_chars:
        result = result[: max_chars - 50].rstrip() + "\n...[few-shot 示例已截断]"
    return result


def _render_case_body(lines: list[str], content: str) -> None:
    """Render a single case's content into the lines list."""
    # ChromaDB case content is stored as structured lines like:
    #   产品：XXX
    #   领域：XXX
    #   目标：XXX
    #   核心功能：...
    #   API 端点数：N，示例：...
    #   DB 表数：N，示例：...
    #   评审评分：N
    # Parse out the useful parts and present them as few-shot sections.
    fields: dict[str, str] = {}
    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue
        if "：" in line:
            key, _, value = line.partition("：")
            fields[key.strip()] = value.strip()

    # Build requirements description
    req_parts = []
    if fields.get("目标"):
        req_parts.append(fields["目标"])
    if fields.get("核心功能"):
        req_parts.append(f"核心功能：{fields['核心功能']}")

    if req_parts:
        lines.append(f"**需求场景**：{'；'.join(req_parts)}")

    # Build technical solution description
    tech_parts = []
    if fields.get("API 端点数"):
        api_val = fields["API 端点数"]
        lines.append(f"- API：{api_val}")
    if fields.get("DB 表数"):
        db_val = fields["DB 表数"]
        lines.append(f"- DB：{db_val}")

    if not any(k in fields for k in ("API 端点数", "DB 表数")):
        # Fallback: show raw content compactly
        compact = content.replace("\n", "；")
        lines.append(f"**方案摘要**：{compact[:300]}")


def build_few_shot_for_task(
    prd_doc: dict,
    clarified_req: dict | None = None,
    top_k: int | None = None,
    max_chars: int | None = None,
    metadata: dict | None = None,
    enabled: bool | None = None,
) -> str:
    """One-stop: build few-shot text from task context.

    Constructs a search query from PRD features + goal, retrieves
    best-matching historical cases, and formats them for prompt injection.

    Returns an empty string without touching the memory store when the
    memory switch is off.
    """
    if enabled is None:
        enabled = resolve_memory_enabled(metadata)
    if not enabled:
        return ""

    query = _build_search_query(prd_doc, clarified_req or {})
    if not query.strip():
        return ""

    settings = get_settings()
    top_k = top_k if top_k is not None else settings.few_shot_top_k
    max_chars = max_chars if max_chars is not None else settings.few_shot_max_chars

    cases = retrieve_few_shot_examples(query, top_k=top_k, enabled=True)
    return format_few_shot(cases, max_chars=max_chars)


def _build_search_query(prd_doc: dict, clarified_req: dict) -> str:
    """Build a search query from PRD document and clarified requirement fields."""
    parts: list[str] = []

    goal = prd_doc.get("product_goal") or clarified_req.get("goal") or ""
    if goal:
        parts.append(str(goal)[:200])

    product_name = prd_doc.get("product_name") or clarified_req.get("product_name") or ""
    if product_name:
        parts.append(str(product_name)[:100])

    # PRD uses feature_modules (list of dict), clarified_req uses core_features (list of str)
    features = prd_doc.get("feature_modules") or clarified_req.get("core_features") or []
    feature_names = []
    for f in features:
        if isinstance(f, dict):
            feature_names.append(str(f.get("name", "")))
        elif isinstance(f, str):
            feature_names.append(f)
    if feature_names:
        parts.append(" ".join(feature_names[:5]))

    domain = prd_doc.get("domain") or clarified_req.get("domain") or ""
    if domain:
        parts.append(str(domain)[:50])

    return " ".join(parts)
