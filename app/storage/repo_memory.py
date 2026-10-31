"""Repository memory API backed by local ChromaDB with graceful fallback."""

from __future__ import annotations

from typing import Any

from app.core.logger import logger
from app.storage.memory_chroma import get_memory_store


def search_memory_sync(
    query: str,
    top_k: int = 3,
    memory_types: list[str] | None = None,
    project_id: str = "default",
) -> list[dict[str, Any]]:
    """Search local memory and return content, metadata, score, and source."""
    try:
        results = get_memory_store(project_id).search(
            query=query,
            top_k=top_k,
            memory_types=memory_types,
        )
        logger.info(f"Memory search completed: hits={len(results)} query={query[:80]}")
        return results
    except Exception as exc:  # pragma: no cover - safety net for runtime fallback
        logger.warning(f"Memory search failed, continuing without memory: {exc}")
        return []


async def search_memory(
    query: str,
    top_k: int = 3,
    memory_types: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Async wrapper for memory search."""
    return search_memory_sync(query=query, top_k=top_k, memory_types=memory_types)


def save_memory_sync(
    content: str,
    metadata: dict[str, Any] | None = None,
    memory_id: str | None = None,
    project_id: str = "default",
) -> None:
    """Save a memory item to the project's ChromaDB store when available."""
    if not content.strip():
        return
    try:
        get_memory_store(project_id).save(content=content, metadata=metadata, memory_id=memory_id)
        logger.info(f"Memory save completed: content={content[:80]}")
    except Exception as exc:  # pragma: no cover
        logger.warning(f"Memory save failed, continuing without persistence: {exc}")


async def save_memory(content: str, metadata: dict[str, Any] | None = None) -> None:
    """Async wrapper for memory save."""
    save_memory_sync(content=content, metadata=metadata)
