"""机器人2 建议草稿与确认指令的纯函数/轻量测试。"""

from __future__ import annotations

from app.integrations.dingtalk.assist import _parse_assist_json
from app.integrations.dingtalk.pending_payload import (
    unwrap_pending_payload,
    with_assist_draft,
    wrap_pending_payload,
)
from app.integrations.dingtalk.render import (
    parse_approval,
    parse_confirm_or_modify,
    render_assist_draft,
    render_waiting,
)


def test_pending_payload_roundtrip() -> None:
    wrapped = wrap_pending_payload(["目标平台？"], "Web 端", "补全了平台")
    data, draft, rationale = unwrap_pending_payload(wrapped)
    assert data == ["目标平台？"]
    assert draft == "Web 端"
    assert rationale == "补全了平台"

    legacy_data, legacy_draft, _ = unwrap_pending_payload(["旧问题"])
    assert legacy_data == ["旧问题"]
    assert legacy_draft == ""

    updated = with_assist_draft(wrapped, "移动端", "改为移动端")
    assert updated["assist_draft"] == "移动端"


def test_parse_confirm_or_modify() -> None:
    assert parse_confirm_or_modify("确认") == ("confirm", "")
    assert parse_confirm_or_modify("采用") == ("confirm", "")
    assert parse_confirm_or_modify("修改 只要 Web") == ("modify", "只要 Web")
    assert parse_confirm_or_modify("随便说说") == (None, "")


def test_parse_approval_multiline_draft() -> None:
    assert parse_approval("通过\n方案完整") == (True, "方案完整")
    assert parse_approval("驳回 接口不足") == (False, "接口不足")


def test_render_assist_and_waiting() -> None:
    body = wrap_pending_payload(["目标平台？"], "Web 与移动端", "补全平台")
    waiting = render_waiting("t1", "clarification", body)
    assert "【机器人1】" in waiting
    assert "1. 目标平台？" in waiting
    assert "确认" in waiting

    assist = render_assist_draft("t1", "clarification", "Web 与移动端", "补全平台")
    assert "【机器人2】" in assist
    assert "Web 与移动端" in assist
    assert "人工确认" in assist


def test_parse_assist_json() -> None:
    draft, rationale = _parse_assist_json(
        '{"draft":"通过","rationale":"分数达标"}'
    )
    assert draft == "通过"
    assert rationale == "分数达标"

    draft, rationale = _parse_assist_json(
        "```json\n{\"draft\":\"驳回 缺表结构\",\"rationale\":\"补约束\"}\n```"
    )
    assert draft.startswith("驳回")
    assert "补约束" in rationale
