from __future__ import annotations

import io

import pytest


def _docx_bytes() -> bytes:
    from docx import Document

    document = Document()
    document.add_heading("点单系统需求", level=1)
    document.add_paragraph("支持扫码点单，微信支付与退款。")
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "角色"
    table.rows[0].cells[1].text = "顾客"
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_extract_docx_paragraphs_and_tables():
    from app.tools.doc_extract import extract_document

    result = extract_document("req.docx", _docx_bytes())

    assert result["ok"] is True
    assert result["kind"] == "docx"
    assert "扫码点单" in result["text"]
    assert "顾客" in result["text"]
    assert result["chars"] > 0


def test_extract_pdf_without_text_layer_warns():
    from pypdf import PdfWriter

    from app.tools.doc_extract import extract_document

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)

    result = extract_document("scan.pdf", buffer.getvalue())

    assert result["kind"] == "pdf"
    assert result["pages"] == 1
    assert result["text"] == ""
    assert result["warnings"]


def test_reject_legacy_doc():
    from app.tools.doc_extract import DocumentError, extract_document

    with pytest.raises(DocumentError) as excinfo:
        extract_document("old.doc", b"legacy")

    assert excinfo.value.code == "legacy_doc"


def test_reject_unsupported_type():
    from app.tools.doc_extract import DocumentError, extract_document

    with pytest.raises(DocumentError) as excinfo:
        extract_document("notes.txt", b"hello")

    assert excinfo.value.code == "unsupported_type"


def test_corrupted_docx_reports_decode_failure():
    from app.tools.doc_extract import DocumentError, extract_document

    with pytest.raises(DocumentError) as excinfo:
        extract_document("broken.docx", b"not a zip")

    assert excinfo.value.code == "decode_failed"


def test_document_route_registered():
    from app.main import app

    paths = [route.path for route in app.routes]

    assert "/extract/document" in paths
