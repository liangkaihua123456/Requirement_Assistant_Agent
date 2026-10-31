"""Round 2 P1 changes: cancel/delete, export, preflight, templates."""

from __future__ import annotations

import pytest


def test_round2_routes_registered():
    from app.main import app

    paths = [route.path for route in app.routes]

    assert "/tasks/{task_id}/cancel" in paths
    assert "/tasks/{task_id}/export/zip" in paths
    assert "/tasks/{task_id}/export/docx" in paths
    assert "/tasks/cleanup" in paths
    assert "/templates" in paths
    assert "/settings/preflight" in paths
    # 成本上限已取消，接口不应再注册
    assert "/settings/budget" not in paths


def test_cancellation_flag_lifecycle():
    from app.core.cancellation import clear_cancel, is_cancelled, request_cancel

    request_cancel("t1")
    assert is_cancelled("t1")
    clear_cancel("t1")
    assert not is_cancelled("t1")


def test_cancelled_task_stops_at_node_boundary():
    from app.core.cancellation import TaskCancelled, clear_cancel, request_cancel
    from app.core.observability import trace_node

    @trace_node("noop")
    def node(state):
        return {}

    request_cancel("t2")
    with pytest.raises(TaskCancelled):
        node({"task_id": "t2"})
    clear_cancel("t2")
    assert isinstance(node({"task_id": "t2"}), dict)


def test_review_design_is_compacted():
    import json

    from app.agents.reviewer_agent import _compact_design_for_review

    design = {
        "architecture_overview": "x" * 900,
        "architecture_style": "单体",
        "services": [
            {"name": "svc", "responsibility": "r" * 200, "tech_stack": ["FastAPI"]}
        ],
        "api_endpoints": [
            {
                "method": "POST",
                "path": "/a",
                "description": "d" * 300,
                "request_body": "y" * 2000,
                "response_body": "z" * 2000,
                "related_feature_ids": ["f1"],
            }
        ],
        "db_schema": {
            "database_type": "PostgreSQL",
            "tables": [
                {
                    "table_name": "t",
                    "description": "d" * 200,
                    "columns": [{"name": "id", "type": "uuid", "description": "pk"}],
                    "related_feature_ids": ["f1"],
                }
            ],
        },
        "tech_risks": [{"risk": "r" * 300, "impact": "high"}],
        "code_scaffold": {"key_files": [{"path": "a.py", "skeleton": "s" * 5000}]},
    }

    compact = _compact_design_for_review(design)

    assert "code_scaffold" not in compact
    assert len(compact["api_endpoints"][0]["request_body"]) <= 121
    assert compact["api_endpoints"][0]["request_body"].endswith("…")
    assert compact["api_endpoints"][0]["related_feature_ids"] == ["f1"]
    assert compact["db_schema"]["tables"][0]["related_feature_ids"] == ["f1"]
    assert len(compact["architecture_overview"]) <= 501
    assert len(json.dumps(compact, ensure_ascii=False)) < len(
        json.dumps(design, ensure_ascii=False)
    ) * 0.4


def test_api_hygiene_flags_duplicate_action():
    from app.tools.api_hygiene import audit_api_hygiene

    design = {
        "api_endpoints": [
            {"method": "POST", "path": "/api/v1/orders/cancel"},
            {"method": "POST", "path": "/api/v1/orders/{id}/cancel"},
        ]
    }

    issues = audit_api_hygiene(design)

    assert any(item["severity"] == "high" for item in issues)
    assert "cancel" in issues[0]["description"]


def test_api_hygiene_accepts_clean_design():
    from app.tools.api_hygiene import audit_api_hygiene

    design = {
        "api_endpoints": [
            {"method": "GET", "path": "/api/orders"},
            {"method": "GET", "path": "/api/orders/{id}"},
            {"method": "GET", "path": "/api/orders/export"},
            {"method": "GET", "path": "/api/orders/my"},
            {"method": "POST", "path": "/api/orders"},
            {"method": "POST", "path": "/api/orders/{id}/cancel"},
        ]
    }

    assert audit_api_hygiene(design) == []


def test_design_delta_merges_incrementally():
    from app.agents.dialogue_agent import DesignDelta, _apply_design_delta

    design = {
        "architecture_overview": "分层",
        "api_endpoints": [{"method": "POST", "path": "/orders", "description": "创建订单"}],
        "db_schema": {
            "database_type": "PostgreSQL",
            "tables": [{"table_name": "orders", "description": "订单"}],
        },
    }
    delta = DesignDelta(
        answers=["增加幂等键"],
        api_updates=[
            {"method": "POST", "path": "/orders", "description": "创建订单（含幂等键）"},
            {"method": "GET", "path": "/orders/{id}", "description": "查询订单"},
        ],
        db_updates=[{"table_name": "orders", "description": "订单表（含状态机）"}],
        architecture_note="增加幂等层",
    )

    merged, stats = _apply_design_delta(design, delta)

    assert len(merged["api_endpoints"]) == 2
    assert "幂等键" in merged["api_endpoints"][0]["description"]
    assert stats["api_updated"] == 1 and stats["api_added"] == 1
    assert stats["db_updated"] == 1
    assert "状态机" in merged["db_schema"]["tables"][0]["description"]
    assert "幂等层" in merged["architecture_overview"]
    # Original design must not be mutated.
    assert design["api_endpoints"][0]["description"] == "创建订单"


def test_export_docx_and_zip(tmp_path, monkeypatch):
    from app.tools import export_tool

    class _Settings:
        output_dir = tmp_path

    monkeypatch.setattr(export_tool, "get_settings", lambda: _Settings())

    state = {
        "prd_doc": {
            "overview": "示例产品",
            "features": [
                {"name": "下单", "description": "用户下单", "priority": "high"},
            ],
        },
        "technical_design": {
            "architecture_overview": "分层单体",
            "architecture_style": "单体",
            "api_endpoints": [
                {"method": "POST", "path": "/orders", "description": "创建订单"},
            ],
            "db_schema": {"tables": [{"table_name": "orders", "description": "订单表"}]},
        },
        "review_result": {
            "overall_score": 8.2,
            "passed": True,
            "issues": [{"severity": "low", "description": "示例问题"}],
        },
    }

    docx_path = export_tool.export_docx(state, "task-x")
    zip_path = export_tool.export_bundle_zip("task-x")

    assert docx_path.exists() and docx_path.suffix == ".docx"
    assert docx_path.stat().st_size > 0
    assert zip_path.exists() and zip_path.suffix == ".zip"
    assert zip_path.stat().st_size > 0
