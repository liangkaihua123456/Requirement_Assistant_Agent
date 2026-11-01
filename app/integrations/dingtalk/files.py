"""钉钉附件下载、URL 下载、arXiv 回退检索。"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings, get_settings
from app.core.logger import logger
from app.integrations.dingtalk.client import get_access_token
from app.integrations.dingtalk.pdf_text import extract_pdf_text

_ARXIV_ATOM = "{http://www.w3.org/2005/Atom}"


def credentials_for_robot_code(
    robot_code: str,
    settings: Settings | None = None,
) -> tuple[str, str, str]:
    """返回 (app_key, app_secret, robot_code)。"""
    cfg = settings or get_settings()
    code = (robot_code or "").strip()
    candidates = [
        (
            cfg.dingtalk_robot1_app_key,
            cfg.dingtalk_robot1_app_secret,
            cfg.dingtalk_robot1_robot_code,
        ),
        (
            cfg.dingtalk_robot2_app_key,
            cfg.dingtalk_robot2_app_secret,
            cfg.dingtalk_robot2_robot_code,
        ),
    ]
    for app_key, app_secret, own_code in candidates:
        if app_key and app_secret and code and code == own_code:
            return app_key, app_secret, own_code
    # 回退：优先机器人1，再机器人2
    if cfg.dingtalk_robot1_configured:
        return (
            cfg.dingtalk_robot1_app_key,
            cfg.dingtalk_robot1_app_secret,
            cfg.dingtalk_robot1_robot_code,
        )
    return (
        cfg.dingtalk_robot2_app_key,
        cfg.dingtalk_robot2_app_secret,
        cfg.dingtalk_robot2_robot_code,
    )


def parse_inbound_files(raw: dict[str, Any]) -> list[dict[str, str]]:
    """从原始回调中提取可下载附件。"""
    files: list[dict[str, str]] = []
    msgtype = raw.get("msgtype") or ""
    if msgtype == "file":
        content = raw.get("content") or {}
        code = content.get("downloadCode") or ""
        name = content.get("fileName") or "attachment.bin"
        if code:
            files.append({"download_code": code, "filename": name})
        return files

    if msgtype == "picture":
        content = raw.get("content") or {}
        code = content.get("downloadCode") or ""
        if code:
            files.append({"download_code": code, "filename": "image.jpg"})
        return files

    if msgtype == "richText":
        content = raw.get("content") or {}
        items = content.get("richText") or []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            code = item.get("downloadCode") or ""
            if not code:
                continue
            name = item.get("fileName") or f"richtext-{index}.bin"
            files.append({"download_code": code, "filename": name})
    return files


async def resolve_message_file_url(
    http: httpx.AsyncClient,
    *,
    download_code: str,
    robot_code: str,
    settings: Settings | None = None,
) -> str:
    app_key, app_secret, resolved_code = credentials_for_robot_code(
        robot_code, settings
    )
    if not app_key or not app_secret or not resolved_code:
        raise RuntimeError("missing robot credentials for file download")
    token = await get_access_token(http, app_key, app_secret)
    response = await http.post(
        "https://api.dingtalk.com/v1.0/robot/messageFiles/download",
        headers={"x-acs-dingtalk-access-token": token},
        json={"downloadCode": download_code, "robotCode": resolved_code},
    )
    if response.status_code >= 400:
        logger.error(
            f"DingTalk messageFiles/download failed: {response.status_code} {response.text}",
            extra={"node": "dingtalk"},
        )
    response.raise_for_status()
    body = response.json()
    url = body.get("downloadUrl") or ""
    if not url:
        raise RuntimeError(f"empty downloadUrl: {body}")
    return url


async def download_bytes(http: httpx.AsyncClient, url: str) -> bytes:
    response = await http.get(url, follow_redirects=True)
    response.raise_for_status()
    return response.content


async def ingest_dingtalk_file(
    http: httpx.AsyncClient,
    *,
    download_code: str,
    filename: str,
    robot_code: str,
    settings: Settings | None = None,
) -> tuple[str, str]:
    """下载钉钉附件并提取文本。返回 (filename, text)。"""
    cfg = settings or get_settings()
    url = await resolve_message_file_url(
        http,
        download_code=download_code,
        robot_code=robot_code,
        settings=cfg,
    )
    data = await download_bytes(http, url)
    if filename.lower().endswith(".pdf") or data[:4] == b"%PDF":
        text = extract_pdf_text(data, max_chars=cfg.dingtalk_doc_max_chars)
        return filename, text
    # 非 PDF：尽量按 utf-8 文本处理
    try:
        text = data.decode("utf-8", errors="ignore")[: cfg.dingtalk_doc_max_chars]
    except Exception:
        text = ""
    return filename, text


async def ingest_url_pdf(
    http: httpx.AsyncClient,
    url: str,
    settings: Settings | None = None,
) -> tuple[str, str]:
    cfg = settings or get_settings()
    data = await download_bytes(http, url)
    name = url.rstrip("/").split("/")[-1] or "download.pdf"
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"
    if data[:4] != b"%PDF" and not url.lower().endswith(".pdf"):
        raise RuntimeError("url does not look like a PDF")
    text = extract_pdf_text(data, max_chars=cfg.dingtalk_doc_max_chars)
    return name, text


def _arxiv_query_from_text(text: str) -> str:
    names = re.findall(r"([A-Za-z][\w.+\-]{2,})\.pdf", text or "", flags=re.I)
    if names:
        return names[0]
    # 去掉中文提示词，保留可能的英文题名片段
    cleaned = re.sub(r"[\u4e00-\u9fff]+", " ", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:120]


async def fetch_arxiv_pdf_by_query(
    http: httpx.AsyncClient,
    query: str,
    settings: Settings | None = None,
) -> tuple[str, str] | None:
    """按论文名/关键词检索 arXiv 并下载首个 PDF。"""
    cfg = settings or get_settings()
    if not cfg.dingtalk_doc_arxiv_fallback:
        return None
    q = _arxiv_query_from_text(query)
    if len(q) < 3:
        return None
    api = (
        "https://export.arxiv.org/api/query?"
        f"search_query=all:{quote(q)}&start=0&max_results=3"
    )
    try:
        response = await http.get(api, timeout=20.0, follow_redirects=True)
        response.raise_for_status()
        root = ET.fromstring(response.text)
    except Exception as exc:
        logger.warning(f"arXiv search failed: {exc}", extra={"node": "dingtalk"})
        return None

    for entry in root.findall(f"{_ARXIV_ATOM}entry"):
        title = (entry.findtext(f"{_ARXIV_ATOM}title") or "").strip()
        pdf_url = ""
        for link in entry.findall(f"{_ARXIV_ATOM}link"):
            if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
                pdf_url = link.attrib.get("href") or ""
                break
        if not pdf_url:
            entry_id = (entry.findtext(f"{_ARXIV_ATOM}id") or "").strip()
            if "arxiv.org/abs/" in entry_id:
                pdf_url = entry_id.replace("/abs/", "/pdf/") + ".pdf"
        if not pdf_url:
            continue
        try:
            data = await download_bytes(http, pdf_url)
            text = extract_pdf_text(data, max_chars=cfg.dingtalk_doc_max_chars)
            if len(text) < 200:
                continue
            filename = f"{(title or q).splitlines()[0][:80].strip()}.pdf"
            filename = re.sub(r'[\\/:*?"<>|]+', "_", filename)
            return filename, text
        except Exception as exc:
            logger.warning(
                f"arXiv pdf download failed: {exc}", extra={"node": "dingtalk"}
            )
            continue
    return None
