"""从钉钉群文件空间读取近期上传的文件。

群聊里单独发送的文件不会进入机器人回调，但通常会进入群文件空间。
流程：
1) openConversationId -> spaceId
2) 列出 dentries，按文件名/最近 PDF 匹配
3) 获取下载信息并拉取正文
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings, get_settings
from app.core.logger import logger
from app.integrations.dingtalk.client import get_access_token
from app.integrations.dingtalk.files import credentials_for_robot_code
from app.integrations.dingtalk.pdf_text import extract_pdf_text


async def userid_to_unionid(
    http: httpx.AsyncClient,
    *,
    access_token: str,
    userid: str,
) -> str:
    """用旧版通讯录接口把 userId 换成 unionId。"""
    response = await http.post(
        f"https://oapi.dingtalk.com/topapi/v2/user/get?access_token={quote(access_token)}",
        json={"userid": userid},
    )
    response.raise_for_status()
    body = response.json()
    if body.get("errcode") not in (0, "0", None):
        # 某些成功响应只有 result
        if not body.get("result"):
            raise RuntimeError(f"userid_to_unionid failed: {body}")
    result = body.get("result") or {}
    union_id = result.get("unionid") or result.get("unionId") or ""
    if not union_id:
        raise RuntimeError(f"unionId missing in user detail: {body}")
    return union_id


async def get_oauth_access_token_legacy(
    http: httpx.AsyncClient,
    app_key: str,
    app_secret: str,
) -> str:
    """旧版 gettoken，兼容 topapi 通讯录。"""
    response = await http.get(
        "https://oapi.dingtalk.com/gettoken",
        params={"appkey": app_key, "appsecret": app_secret},
    )
    response.raise_for_status()
    body = response.json()
    token = body.get("access_token") or ""
    if not token:
        raise RuntimeError(f"legacy gettoken failed: {body}")
    return token


async def query_group_space_id(
    http: httpx.AsyncClient,
    *,
    access_token: str,
    open_conversation_id: str,
    union_id: str,
) -> str:
    response = await http.post(
        "https://api.dingtalk.com/v1.0/convFile/conversations/spaces/query",
        params={"unionId": union_id},
        headers={"x-acs-dingtalk-access-token": access_token},
        json={"openConversationId": open_conversation_id},
    )
    if response.status_code >= 400:
        logger.error(
            f"query group space failed: {response.status_code} {response.text}",
            extra={"node": "dingtalk"},
        )
    response.raise_for_status()
    body = response.json()
    space_id = ((body.get("space") or {}).get("spaceId")) or ""
    if not space_id:
        raise RuntimeError(f"group spaceId empty: {body}")
    return space_id


async def list_space_dentries(
    http: httpx.AsyncClient,
    *,
    access_token: str,
    space_id: str,
    union_id: str,
    parent_id: str = "0",
    max_results: int = 50,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    next_token = ""
    while True:
        params: dict[str, Any] = {
            "parentId": parent_id,
            "unionId": union_id,
            "maxResults": max_results,
            "orderBy": "MODIFIED_TIME",
            "order": "DESC",
        }
        if next_token:
            params["nextToken"] = next_token
        response = await http.get(
            f"https://api.dingtalk.com/v1.0/storage/spaces/{space_id}/dentries",
            params=params,
            headers={"x-acs-dingtalk-access-token": access_token},
        )
        if response.status_code >= 400:
            logger.error(
                f"list dentries failed: {response.status_code} {response.text}",
                extra={"node": "dingtalk"},
            )
        response.raise_for_status()
        body = response.json()
        batch = body.get("dentries") or []
        items.extend(batch)
        next_token = body.get("nextToken") or ""
        if not next_token or not batch:
            break
        if len(items) >= 100:
            break
    return items


async def get_dentry_download(
    http: httpx.AsyncClient,
    *,
    access_token: str,
    space_id: str,
    dentry_id: str,
    union_id: str,
) -> tuple[str, dict[str, str]]:
    response = await http.post(
        f"https://api.dingtalk.com/v1.0/storage/spaces/{space_id}/dentries/"
        f"{dentry_id}/downloadInfos/query",
        params={"unionId": union_id},
        headers={"x-acs-dingtalk-access-token": access_token},
        json={},
    )
    if response.status_code >= 400:
        logger.error(
            f"downloadInfos query failed: {response.status_code} {response.text}",
            extra={"node": "dingtalk"},
        )
    response.raise_for_status()
    body = response.json()
    info = body.get("headerSignatureInfo") or body
    urls = info.get("resourceUrls") or []
    headers = info.get("headers") or {}
    if not urls:
        raise RuntimeError(f"no resourceUrls in download info: {body}")
    return urls[0], {str(k): str(v) for k, v in headers.items()}


def _match_dentry(
    dentries: list[dict[str, Any]],
    *,
    wanted_names: list[str],
) -> dict[str, Any] | None:
    files = [
        d
        for d in dentries
        if (d.get("type") or "").upper() == "FILE"
        and (d.get("status") or "NORMAL").upper() == "NORMAL"
    ]
    if not files:
        return None

    lowered = [n.lower() for n in wanted_names if n]
    if lowered:
        for d in files:
            name = (d.get("name") or "").lower()
            if name in lowered or any(n in name for n in lowered):
                return d

    # “上面的/此论文”：取最近修改的 PDF
    pdfs = [
        d
        for d in files
        if (d.get("extension") or "").lower() == "pdf"
        or (d.get("name") or "").lower().endswith(".pdf")
    ]
    return pdfs[0] if pdfs else None


async def fetch_group_file_text(
    http: httpx.AsyncClient,
    *,
    open_conversation_id: str,
    operator_userid: str,
    wanted_names: list[str] | None = None,
    robot_code: str = "",
    settings: Settings | None = None,
) -> tuple[str, str] | None:
    """从群文件空间找到匹配 PDF 并提取文本。返回 (filename, text)。"""
    cfg = settings or get_settings()
    if not open_conversation_id or not operator_userid:
        return None

    app_key, app_secret, _ = credentials_for_robot_code(robot_code, cfg)
    if not app_key or not app_secret:
        return None

    # 新版 token 用于 storage/convFile；旧版 token 用于 userid->unionId
    new_token = await get_access_token(http, app_key, app_secret)
    try:
        legacy_token = await get_oauth_access_token_legacy(http, app_key, app_secret)
        union_id = await userid_to_unionid(
            http, access_token=legacy_token, userid=operator_userid
        )
    except Exception as exc:
        logger.warning(
            f"resolve unionId failed: {exc}", extra={"node": "dingtalk"}
        )
        # 允许直接配置 unionId
        union_id = (cfg.dingtalk_operator_union_id or "").strip()
        if not union_id:
            raise

    space_id = await query_group_space_id(
        http,
        access_token=new_token,
        open_conversation_id=open_conversation_id,
        union_id=union_id,
    )
    dentries = await list_space_dentries(
        http,
        access_token=new_token,
        space_id=space_id,
        union_id=union_id,
        parent_id="0",
    )
    # 再扫一层一级子目录，兼容“群文件/文件夹”
    folders = [
        d for d in dentries if (d.get("type") or "").upper() == "FOLDER"
    ][:5]
    for folder in folders:
        try:
            child = await list_space_dentries(
                http,
                access_token=new_token,
                space_id=space_id,
                union_id=union_id,
                parent_id=str(folder.get("id") or ""),
            )
            dentries.extend(child)
        except Exception as exc:
            logger.warning(
                f"list subfolder failed: {exc}", extra={"node": "dingtalk"}
            )

    target = _match_dentry(dentries, wanted_names=wanted_names or [])
    if not target:
        logger.info(
            "group file not matched",
            extra={"node": "dingtalk"},
        )
        return None

    url, headers = await get_dentry_download(
        http,
        access_token=new_token,
        space_id=space_id,
        dentry_id=str(target.get("id") or ""),
        union_id=union_id,
    )
    response = await http.get(url, headers=headers, follow_redirects=True)
    response.raise_for_status()
    data = response.content
    filename = target.get("name") or "group-file.pdf"
    if not filename.lower().endswith(".pdf") and data[:4] == b"%PDF":
        filename = f"{filename}.pdf"
    text = extract_pdf_text(data, max_chars=cfg.dingtalk_doc_max_chars)
    if len(text) < 50:
        return None
    return filename, text


def permission_hint_from_error(exc: Exception) -> str:
    msg = str(exc)
    if re.search(r"403|Forbidden|AccessDenied|权限", msg, re.I):
        return (
            "读取群文件失败：应用可能未开通权限。"
            "请在钉钉开放平台为机器人应用开通："
            "「群文件空间读权限」「企业存储文件读权限」"
            "「企业存储文件下载信息读权限」「通讯录个人信息读权限」，"
            "并确保应用已发布且机器人在群内。"
        )
    return f"读取群文件失败：{msg}"
