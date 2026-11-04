"""PDF / Word text extraction for requirement intake.

Runs in-process, no external binary. Scanned PDFs without a text layer will
yield empty text, which is reported as a warning instead of an error so the
caller can fall back to asking the user for a text description.
"""

from __future__ import annotations

import io
import time
from typing import Any

MAX_CHARS = 200_000


class DocumentError(ValueError):
    """A document that cannot be turned into text, with a stable code."""

    def __init__(self, message: str, code: str = "invalid_document") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _normalize(text: str) -> str:
    raw = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in raw.split("\n")]
    output: list[str] = []
    blank = 0
    for line in lines:
        if line:
            blank = 0
            output.append(line)
            continue
        blank += 1
        if blank <= 1:
            output.append("")
    return "\n".join(output).strip()


def extract_pdf(data: bytes) -> dict[str, Any]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise DocumentError("服务器缺少 pypdf，无法解析 PDF", "missing_dependency") from exc

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:
        raise DocumentError(f"PDF 解析失败：{exc}", "decode_failed") from exc

    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            raise DocumentError("PDF 已加密，请先解除密码再上传", "encrypted") from exc

    pages: list[str] = []
    failed = 0
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            failed += 1
            pages.append("")

    return {
        "text": _normalize("\n\n".join(pages)),
        "pages": len(reader.pages),
        "failed_pages": failed,
        "kind": "pdf",
    }


def extract_docx(data: bytes) -> dict[str, Any]:
    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise DocumentError("服务器缺少 python-docx，无法解析 Word", "missing_dependency") from exc

    try:
        document = Document(io.BytesIO(data))
    except Exception as exc:
        raise DocumentError(f"Word 解析失败：{exc}", "decode_failed") from exc

    blocks = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                blocks.append(" | ".join(cells))

    return {
        "text": _normalize("\n".join(blocks)),
        "pages": 0,
        "failed_pages": 0,
        "kind": "docx",
    }


def extract_document(filename: str, data: bytes) -> dict[str, Any]:
    """Dispatch by extension and normalize the result payload."""
    started = time.perf_counter()
    name = (filename or "").lower()

    if name.endswith(".pdf"):
        result = extract_pdf(data)
    elif name.endswith(".docx"):
        result = extract_docx(data)
    elif name.endswith(".doc"):
        raise DocumentError("暂不支持 .doc 格式，请另存为 .docx 后上传", "legacy_doc")
    else:
        raise DocumentError("仅支持 .pdf 与 .docx 文件", "unsupported_type")

    text = str(result.get("text") or "")
    warnings: list[str] = []
    if not text:
        warnings.append("未提取到文本，可能是扫描件或纯图片文档，建议改用文字描述")
    elif len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
        warnings.append(f"内容超过 {MAX_CHARS} 字，已截断")
    if result.get("failed_pages"):
        warnings.append(f"{result['failed_pages']} 页解析失败，内容可能不完整")

    return {
        "ok": True,
        "kind": result["kind"],
        "filename": filename or "",
        "text": text,
        "chars": len(text),
        "pages": result.get("pages", 0),
        "warnings": warnings,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
    }
