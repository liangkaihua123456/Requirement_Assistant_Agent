"""会话级文档缓存：保存近期解析过的 PDF 正文，供后续提问引用。"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from app.core.config import BASE_DIR, get_settings

_PDF_NAME_RE = re.compile(r"([A-Za-z0-9][\w.+\-]{0,120}\.pdf)", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


def _store_dir() -> Path:
    path = BASE_DIR / "data" / "dingtalk_docs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)[:120] or "unknown"


def _doc_path(conversation_id: str) -> Path:
    return _store_dir() / f"{_safe_key(conversation_id)}.json"


def load_docs(conversation_id: str) -> list[dict[str, Any]]:
    path = _doc_path(conversation_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    docs = data.get("docs") if isinstance(data, dict) else None
    return docs if isinstance(docs, list) else []


def save_doc(
    conversation_id: str,
    *,
    filename: str,
    text: str,
    source: str,
) -> dict[str, Any]:
    docs = load_docs(conversation_id)
    item = {
        "filename": filename,
        "text": text,
        "source": source,
        "saved_at": int(time.time()),
        "chars": len(text or ""),
    }
    # 同名覆盖
    docs = [d for d in docs if (d.get("filename") or "").lower() != filename.lower()]
    docs.insert(0, item)
    docs = docs[:8]
    _doc_path(conversation_id).write_text(
        json.dumps({"docs": docs}, ensure_ascii=False),
        encoding="utf-8",
    )
    return item


def find_docs_for_query(
    conversation_id: str,
    query: str,
) -> list[dict[str, Any]]:
    docs = load_docs(conversation_id)
    if not docs:
        return []
    names = [m.group(1).lower() for m in _PDF_NAME_RE.finditer(query or "")]
    if names:
        matched = [
            d
            for d in docs
            if (d.get("filename") or "").lower() in names
            or any(n in (d.get("filename") or "").lower() for n in names)
        ]
        if matched:
            return matched
    # 提到「上面的/该论文/此论文」时回退最近一份
    markers = ("上面的", "上述", "该论文", "此论文", "这篇论文", "这个pdf", "这个 PDF", "附件")
    if any(m in (query or "") for m in markers) or ".pdf" in (query or "").lower():
        return docs[:1]
    return []


def extract_pdf_names(text: str) -> list[str]:
    return [m.group(1) for m in _PDF_NAME_RE.finditer(text or "")]


def extract_urls(text: str) -> list[str]:
    return _URL_RE.findall(text or "")


def compose_user_input(question: str, docs: list[dict[str, Any]]) -> str:
    settings = get_settings()
    max_chars = max(2000, settings.dingtalk_doc_max_chars)
    parts = [question.strip()]
    budget = max_chars
    for doc in docs:
        text = (doc.get("text") or "").strip()
        if not text:
            continue
        filename = doc.get("filename") or "document.pdf"
        source = doc.get("source") or ""
        header = f"\n\n===== 附件《{filename}》正文"
        if source:
            header += f"（来源：{source}）"
        header += " =====\n"
        body = text if len(text) <= budget else text[:budget]
        parts.append(header + body)
        budget -= len(body)
        if budget <= 0:
            break
    return "\n".join(parts).strip()


def looks_like_document_question(text: str) -> bool:
    value = text or ""
    if extract_pdf_names(value):
        return True
    keywords = ("论文", "pdf", "PDF", "文档", "解读", "解释一下", "主要做什么", "摘要")
    return any(k in value for k in keywords)
