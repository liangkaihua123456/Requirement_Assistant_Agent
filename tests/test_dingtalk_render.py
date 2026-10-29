"""DingTalk 纯函数测试：不依赖数据库和网络。"""

from __future__ import annotations

from app.integrations.dingtalk.render import (
    classify_waiting,
    parse_approval,
    render_task_status,
    render_waiting,
)


def test_classify_clarification() -> None:
    snapshot = {"clarified_requirement": {"open_questions": ["目标平台？"]}}
    kind, payload = classify_waiting(snapshot)
    assert kind == "clarification"
    assert payload == ["目标平台？"]


def test_classify_approval_prefers_review() -> None:
    snapshot = {
        "review_result": {"passed": False, "overall_score": 7.5},
        "clarified_requirement": {"open_questions": ["旧问题"]},
    }
    kind, payload = classify_waiting(snapshot)
    assert kind == "approval"
    assert payload["overall_score"] == 7.5


def test_parse_approval() -> None:
    assert parse_approval("通过") == (True, "")
    assert parse_approval("驳回 接口太少") == (False, "接口太少")
    assert parse_approval("再说吧") == (None, "")


def test_render_waiting_and_status() -> None:
    text = render_waiting("t1", "clarification", ["目标平台？", "要多人吗？"])
    assert "1. 目标平台？" in text
    assert "仅发起人可回复" in text

    status = render_task_status(
        {
            "task_id": "t1",
            "status": "completed",
            "state_snapshot": {"prd_doc": {"product_name": "待办助手"}},
        }
    )
    assert "已完成" in status
    assert "待办助手" in status
