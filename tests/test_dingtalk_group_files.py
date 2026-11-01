"""群文件匹配逻辑测试。"""

from __future__ import annotations

from app.integrations.dingtalk.group_files import _match_dentry, permission_hint_from_error


def test_match_dentry_by_name() -> None:
    dentries = [
        {"id": "1", "type": "FILE", "status": "NORMAL", "name": "other.pdf", "extension": "pdf"},
        {
            "id": "2",
            "type": "FILE",
            "status": "NORMAL",
            "name": "ConsRoute.pdf",
            "extension": "pdf",
        },
    ]
    hit = _match_dentry(dentries, wanted_names=["ConsRoute.pdf"])
    assert hit is not None
    assert hit["id"] == "2"


def test_match_latest_pdf_when_no_name() -> None:
    dentries = [
        {"id": "1", "type": "FILE", "status": "NORMAL", "name": "a.pdf", "extension": "pdf"},
        {"id": "2", "type": "FOLDER", "status": "NORMAL", "name": "docs"},
    ]
    hit = _match_dentry(dentries, wanted_names=[])
    assert hit is not None
    assert hit["name"] == "a.pdf"


def test_permission_hint() -> None:
    tip = permission_hint_from_error(RuntimeError("403 Forbidden AccessDenied"))
    assert "群文件空间读权限" in tip
