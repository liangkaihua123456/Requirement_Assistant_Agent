"""文档缓存与 PDF 文本拼接测试。"""

from __future__ import annotations

from app.integrations.dingtalk.documents import (
    compose_user_input,
    extract_pdf_names,
    find_docs_for_query,
    looks_like_document_question,
    save_doc,
)
from app.integrations.dingtalk.files import parse_inbound_files
from app.integrations.dingtalk.pdf_text import extract_pdf_text


def test_extract_pdf_names_and_question_detect() -> None:
    text = "@机器人1号 上面的ConsRoute.pdf文档解释一下此论文主要做什么"
    assert "ConsRoute.pdf" in extract_pdf_names(text)
    assert looks_like_document_question(text) is True


def test_save_and_find_docs(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.integrations.dingtalk.documents.BASE_DIR", tmp_path
    )
    save_doc("cid-1", filename="ConsRoute.pdf", text="hello paper", source="test")
    docs = find_docs_for_query(
        "cid-1", "上面的ConsRoute.pdf文档解释一下此论文主要做什么"
    )
    assert len(docs) == 1
    assert docs[0]["filename"] == "ConsRoute.pdf"
    composed = compose_user_input("解释论文", docs)
    assert "hello paper" in composed
    assert "ConsRoute.pdf" in composed


def test_parse_inbound_files() -> None:
    files = parse_inbound_files(
        {
            "msgtype": "file",
            "content": {
                "downloadCode": "abc",
                "fileName": "ConsRoute.pdf",
            },
        }
    )
    assert files == [{"download_code": "abc", "filename": "ConsRoute.pdf"}]


def test_extract_pdf_text_roundtrip() -> None:
    # 最小合法 PDF
    from pypdf import PdfWriter
    import io

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    # blank page may extract empty; just ensure no crash
    text = extract_pdf_text(buf.getvalue(), max_chars=1000)
    assert isinstance(text, str)
