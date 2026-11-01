"""PDF 文本提取。"""

from __future__ import annotations

import io
import re

from pypdf import PdfReader


def extract_pdf_text(data: bytes, max_chars: int = 40000) -> str:
    """从 PDF 字节提取纯文本，截断到 max_chars。"""
    if not data:
        return ""
    reader = PdfReader(io.BytesIO(data))
    chunks: list[str] = []
    total = 0
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        text = _normalize_whitespace(text)
        if not text:
            continue
        remain = max_chars - total
        if remain <= 0:
            break
        if len(text) > remain:
            chunks.append(text[:remain])
            total = max_chars
            break
        chunks.append(text)
        total += len(text)
    return "\n\n".join(chunks).strip()


def _normalize_whitespace(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
