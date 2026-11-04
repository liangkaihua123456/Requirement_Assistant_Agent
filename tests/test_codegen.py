from __future__ import annotations

import json

import pytest


def _design() -> dict:
    return {
        "architecture_overview": "分层单体",
        "architecture_style": "monolith",
        "services": [{"name": "order-service", "responsibility": "订单"}],
        "api_endpoints": [
            {
                "method": "GET",
                "path": "/api/v1/orders/{id}",
                "description": "查询订单详情",
                "request_body": "",
                "response_body": "{ id, status, total }",
                "auth_required": True,
                "related_features": ["订单管理"],
            },
            {
                "method": "POST",
                "path": "/api/v1/orders/{id}/cancel",
                "description": "取消订单",
                "request_body": "{ reason }",
                "response_body": "{ id, status }",
                "auth_required": True,
                "related_features": ["订单管理"],
            },
        ],
        "db_schema": {
            "database_type": "PostgreSQL",
            "tables": [
                {
                    "table_name": "orders",
                    "description": "订单表",
                    "columns": [
                        {"name": "id", "type": "bigint", "description": "主键"},
                        {"name": "status", "type": "varchar(32)", "description": "状态"},
                        {"name": "total_amount", "type": "numeric(10,2)", "description": "金额"},
                        {"name": "created_at", "type": "timestamp", "description": "创建时间"},
                    ],
                    "indexes": ["UNIQUE KEY uk_order_no (status)", "KEY idx_created (created_at)"],
                    "related_features": ["订单管理"],
                }
            ],
            "relationships": ["orders 1:N order_item"],
        },
    }


def test_normalize_language_accepts_aliases():
    from app.tools.codegen import normalize_language

    assert normalize_language("python") == "python"
    assert normalize_language("FastAPI") == "python"
    assert normalize_language("ts") == "node"
    assert normalize_language("spring") == "java"
    assert normalize_language("") == ""
    assert normalize_language("rust") == ""


def test_openapi_contains_paths_and_schemas():
    from app.tools.codegen.openapi import build_openapi

    spec = build_openapi({"product_name": "订单系统"}, _design())

    assert spec["openapi"].startswith("3.0")
    assert "/api/v1/orders/{id}" in spec["paths"]
    assert "get" in spec["paths"]["/api/v1/orders/{id}"]
    assert "orders" in spec["components"]["schemas"]
    params = spec["paths"]["/api/v1/orders/{id}"]["get"]["parameters"]
    assert params[0]["name"] == "id"


def test_ddl_creates_table_indexes_and_comments():
    from app.tools.codegen.ddl import build_ddl

    sql = build_ddl(_design())

    assert "CREATE TABLE IF NOT EXISTS orders" in sql
    assert "status VARCHAR(32)" in sql
    assert "total_amount NUMERIC(10,2)" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uk_order_no ON orders (status);" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_created ON orders (created_at);" in sql
    assert "COMMENT ON TABLE orders" in sql
    assert "-- 关系：orders 1:N order_item" in sql


@pytest.mark.parametrize("language", ["python", "node", "java", "go"])
def test_generate_artifacts_for_each_language(tmp_path, language):
    from app.tools.codegen import generate_artifacts

    manifest = generate_artifacts(
        {"product_name": "订单系统"}, _design(), language, tmp_path / language
    )

    assert manifest["enabled"] is True
    assert manifest["language"] == language
    assert manifest["file_count"] >= 6
    assert manifest["endpoints"] == 2
    assert (tmp_path / language / "openapi.yaml").exists()
    assert (tmp_path / language / "schema.sql").exists()
    assert any(item["kind"] == "frontend" for item in manifest["files"])


def test_generate_artifacts_skips_without_language(tmp_path):
    from app.tools.codegen import generate_artifacts

    manifest = generate_artifacts({}, _design(), "", tmp_path)

    assert manifest["enabled"] is False
    assert manifest["reason"] == "no_language_selected"


def test_python_backend_files_are_valid_syntax(tmp_path):
    import ast

    from app.tools.codegen import generate_artifacts

    generate_artifacts({"product_name": "订单系统"}, _design(), "python", tmp_path)

    for path in (tmp_path / "backend").rglob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"))


def test_frontend_files_contain_module_pages(tmp_path):
    from app.tools.codegen import generate_artifacts

    generate_artifacts({"product_name": "订单系统"}, _design(), "node", tmp_path)

    list_page = tmp_path / "frontend/src/views/OrdersList.vue"
    assert list_page.exists()
    body = list_page.read_text(encoding="utf-8")
    assert "order" in body.lower()
    router = (tmp_path / "frontend/src/router/index.ts").read_text(encoding="utf-8")
    assert "/orders" in router


def test_task_request_accepts_target_language():
    from app.api.routes_task import CreateTaskRequest

    request = CreateTaskRequest(user_input="做一个订单系统", target_language="python")

    assert request.target_language == "python"
