"""ChromaDB-backed local memory for cases, reviews, and architecture patterns."""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.logger import logger


class DashScopeEmbeddingFunction:
    """Semantic embedding via DashScope text-embedding-v3 with hash fallback.

    The embedding endpoint is frequently unavailable when the chat provider is
    OpenAI-compatible but does not serve embeddings. A failed request must not
    cost a network timeout on every agent call, so the first failure locks the
    function into the local hash implementation for the process lifetime.
    """

    def __init__(self, model: str = "text-embedding-v3", dimensions: int = 1024) -> None:
        self.model = model
        self.dimensions = dimensions
        self._hash_fallback: HashEmbeddingFunction | None = None
        self._disabled = False
        self._lock = threading.Lock()

    def __call__(self, input: list[str]) -> list[list[float]]:
        if self._disabled:
            return self._hash_embed(input)
        try:
            settings = get_settings()
            if not settings.openai_api_key:
                raise RuntimeError("OPENAI_API_KEY is empty, skipping remote embeddings")
            import openai

            client = openai.OpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_api_base,
                timeout=3.0,
                max_retries=0,
            )
            response = client.embeddings.create(model=self.model, input=input)
            embeddings = sorted(response.data, key=lambda e: e.index)
            return [e.embedding for e in embeddings]
        except Exception as exc:
            with self._lock:
                already_disabled = self._disabled
                self._disabled = True
            if not already_disabled:
                logger.warning(
                    f"Embedding endpoint unavailable, falling back to local hash for this process: {exc}"
                )
            return self._hash_embed(input)

    def _hash_embed(self, texts: list[str]) -> list[list[float]]:
        if self._hash_fallback is None:
            self._hash_fallback = HashEmbeddingFunction(self.dimensions)
        return self._hash_fallback(texts)


class HashEmbeddingFunction:
    """Deterministic local embedding function, avoiding external model downloads."""

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions

    def __call__(self, input: list[str]) -> list[list[float]]:  # Chroma embedding protocol
        return [self._embed(text) for text in input]

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = _tokenize(text)
        if not tokens:
            tokens = [text.strip().lower() or "empty"]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            for offset in range(0, len(digest), 4):
                bucket = int.from_bytes(digest[offset : offset + 4], "little") % self.dimensions
                sign = 1.0 if digest[offset] % 2 == 0 else -1.0
                vector[bucket] += sign
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


@dataclass(frozen=True)
class MemorySearchResult:
    content: str
    metadata: dict[str, Any]
    score: float
    source: str

    def model_dump(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "metadata": self.metadata,
            "score": self.score,
            "source": self.source,
        }


class ChromaMemoryStore:
    """Small wrapper around Chroma persistent collections with safe fallback."""

    def __init__(
        self,
        persist_dir: Path | None = None,
        collection_name: str = "multi_agent_memory_semantic",
    ) -> None:
        settings = get_settings()
        self.persist_dir = Path(persist_dir or settings.memory_persist_dir)
        self.collection_name = collection_name
        self.embedding_function = DashScopeEmbeddingFunction(
            model=settings.memory_embedding_model,
            dimensions=settings.memory_embedding_dimensions,
        )
        self._collection = None
        self._fallback_records: list[dict[str, Any]] = []
        self._seeded = False
        self._connect_failed = False
        self._lock = threading.RLock()

    @property
    def available(self) -> bool:
        return self._collection is not None

    def search(
        self,
        query: str,
        top_k: int = 3,
        memory_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        self._ensure_seeded()
        if self._collection is not None:
            try:
                result = self._collection.query(
                    query_texts=[query],
                    n_results=max(1, top_k * 3 if memory_types else top_k),
                    include=["documents", "metadatas", "distances"],
                )
                items = self._format_chroma_results(result)
                if memory_types:
                    items = [
                        item
                        for item in items
                        if (item.get("metadata") or {}).get("memory_type") in memory_types
                    ]
                return items[:top_k]
            except Exception as exc:  # pragma: no cover - defensive fallback
                logger.warning(f"Chroma memory query failed, using fallback: {exc}")
        return self._fallback_search(query, top_k, memory_types)

    def save(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
        memory_id: str | None = None,
    ) -> None:
        metadata = _clean_metadata(metadata or {})
        metadata.setdefault("memory_type", "case")
        metadata.setdefault("source", "runtime")
        record_id = memory_id or str(uuid.uuid4())
        if self._collection is not None or self._connect():
            try:
                self._collection.upsert(
                    ids=[record_id],
                    documents=[content],
                    metadatas=[metadata],
                )
                return
            except Exception as exc:  # pragma: no cover - defensive fallback
                logger.warning(f"Chroma memory save failed, using fallback: {exc}")
        self._fallback_records.append(
            {"id": record_id, "content": content, "metadata": metadata}
        )

    def list_all(
        self,
        domain: str | None = None,
        memory_types: list[str] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List all non-obsolete memories, optionally filtered."""
        self._ensure_seeded()
        items: list[dict[str, Any]] = []

        if self._collection is not None:
            try:
                result = self._collection.get(
                    limit=limit,
                    include=["documents", "metadatas"],
                )
                ids = result.get("ids") or []
                docs = result.get("documents") or []
                metas = result.get("metadatas") or []
                for mem_id, doc, meta in zip(ids, docs, metas):
                    meta = meta or {}
                    if meta.get("obsolete"):
                        continue
                    if domain and meta.get("domain") != domain:
                        continue
                    if memory_types and meta.get("memory_type") not in memory_types:
                        continue
                    items.append({"id": mem_id, "content": doc or "", "metadata": meta})
            except Exception as exc:
                logger.warning(f"Chroma list_all failed: {exc}")
                return items

        for record in self._fallback_records:
            meta = record.get("metadata") or {}
            if meta.get("obsolete"):
                continue
            if domain and meta.get("domain") != domain:
                continue
            if memory_types and meta.get("memory_type") not in memory_types:
                continue
            items.append(record)

        return items[:limit]

    def update_metadata(self, memory_id: str, updates: dict[str, Any]) -> bool:
        """Update metadata for an existing memory item."""
        if self._collection is not None:
            try:
                result = self._collection.get(ids=[memory_id], include=["metadatas"])
                current = (result.get("metadatas") or [None])[0] or {}
                current.update(updates)
                self._collection.update(ids=[memory_id], metadatas=[_clean_metadata(current)])
                return True
            except Exception as exc:
                logger.warning(f"Chroma update_metadata failed: {exc}")

        for record in self._fallback_records:
            if record.get("id") == memory_id:
                meta = record.get("metadata") or {}
                meta.update(updates)
                record["metadata"] = _clean_metadata(meta)
                return True
        return False

    def _ensure_seeded(self) -> None:
        if self._seeded:
            return
        with self._lock:
            if self._seeded:
                return
            self._connect()
            seeded = False
            if self._collection is not None:
                try:
                    seeded = self._collection.count() > 0
                except Exception as exc:  # pragma: no cover
                    logger.warning(f"Chroma memory count failed: {exc}")
            else:
                seeded = bool(self._fallback_records)
            if not seeded:
                for item in seed_memory_items():
                    self.save(
                        item["content"],
                        metadata=item["metadata"],
                        memory_id=item["id"],
                    )
            # Mark as attempted even on failure: retrying the whole seed path on
            # every search is far more expensive than running without memory.
            self._seeded = True

    def _connect(self) -> bool:
        if self._collection is not None:
            return True
        if self._connect_failed:
            return False
        if os.getenv("DISABLE_CHROMA_MEMORY", "").lower() == "true":
            self._connect_failed = True
            return False
        with self._lock:
            if self._collection is not None:
                return True
            if self._connect_failed:
                return False
            try:
                os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
                import chromadb
                from chromadb.config import Settings as ChromaSettings

                self.persist_dir.mkdir(parents=True, exist_ok=True)
                client = chromadb.PersistentClient(
                    path=str(self.persist_dir),
                    settings=ChromaSettings(anonymized_telemetry=False),
                )
                self._collection = client.get_or_create_collection(
                    name=self.collection_name,
                    embedding_function=self.embedding_function,
                    metadata={"description": "Multi-agent delivery memory"},
                )
                return True
            except Exception as exc:
                self._connect_failed = True
                logger.warning(f"Chroma memory unavailable, using in-process fallback: {exc}")
                return False

    def _format_chroma_results(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        items = []
        for doc, metadata, distance in zip(documents, metadatas, distances):
            score = 1.0 / (1.0 + float(distance or 0.0))
            items.append(
                MemorySearchResult(
                    content=doc or "",
                    metadata=dict(metadata or {}),
                    score=round(score, 4),
                    source=str((metadata or {}).get("source") or "chroma"),
                ).model_dump()
            )
        return items

    def _fallback_search(
        self,
        query: str,
        top_k: int,
        memory_types: list[str] | None,
    ) -> list[dict[str, Any]]:
        query_tokens = set(_tokenize(query))
        scored = []
        for record in self._fallback_records:
            metadata = record.get("metadata") or {}
            if memory_types and metadata.get("memory_type") not in memory_types:
                continue
            content = record.get("content") or ""
            tokens = set(_tokenize(content + " " + json.dumps(metadata, ensure_ascii=False)))
            overlap = len(query_tokens & tokens)
            score = overlap / max(1, len(query_tokens))
            scored.append((score, record))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            MemorySearchResult(
                content=record["content"],
                metadata=record["metadata"],
                score=round(score, 4),
                source=str(record["metadata"].get("source") or "fallback"),
            ).model_dump()
            for score, record in scored[:top_k]
            if score > 0 or not query_tokens
        ]


def get_memory_store() -> ChromaMemoryStore:
    global _MEMORY_STORE
    try:
        return _MEMORY_STORE
    except NameError:
        _MEMORY_STORE = ChromaMemoryStore()
        return _MEMORY_STORE


def seed_memory_items() -> list[dict[str, Any]]:
    """Initial patterns used before enough project history exists."""
    return [
        {
            "id": "pattern_flash_sale_inventory",
            "content": (
                "Flash sale and inventory systems should map features to InventoryService, "
                "OrderService, PaymentService, idempotent order APIs, stock reservation tables, "
                "order/payment tables, rate limiting, deduplication keys, and consistency checks."
            ),
            "metadata": {
                "memory_type": "architecture_pattern",
                "domain": "ecommerce",
                "source": "seed",
                "tags": "flash_sale,inventory,payment,idempotency",
            },
        },
        {
            "id": "pattern_rag_ai_search",
            "content": (
                "AI retrieval products need explicit document ingestion APIs, search/query APIs, "
                "embedding jobs, document chunk tables, vector index metadata, query logs, "
                "permission filters, audit trails, and answer quality feedback loops."
            ),
            "metadata": {
                "memory_type": "architecture_pattern",
                "domain": "ai_search",
                "source": "seed",
                "tags": "rag,vector,permission,audit",
            },
        },
        {
            "id": "pattern_health_privacy",
            "content": (
                "Healthcare and privacy-heavy designs should include patient consent APIs, "
                "role based access control, audit log tables, encrypted sensitive columns, "
                "data retention policies, and emergency access review workflows."
            ),
            "metadata": {
                "memory_type": "architecture_pattern",
                "domain": "healthcare",
                "source": "seed",
                "tags": "privacy,rbac,audit,encryption",
            },
        },
        {
            "id": "review_missing_api_db_mapping",
            "content": (
                "Reviewer issue pattern: every PRD feature module must be traceable to at least "
                "one service, one API endpoint, and one database table or column. Generic endpoints "
                "such as /users or /dashboard are insufficient for core feature coverage."
            ),
            "metadata": {
                "memory_type": "review",
                "source": "seed",
                "tags": "coverage,api,db,review",
            },
        },
    ]


def _clean_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    cleaned = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            cleaned[key] = value
        else:
            cleaned[key] = json.dumps(value, ensure_ascii=False)
    return cleaned


def _tokenize(text: str) -> list[str]:
    normalized = text.lower()
    normalized = normalized.replace("_", " ").replace("-", " ").replace("/", " ")
    return [token for token in re_split(normalized) if len(token) >= 2]


def re_split(text: str) -> list[str]:
    import re

    return re.split(r"[^0-9a-zA-Z\u4e00-\u9fff]+", text)
