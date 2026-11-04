from __future__ import annotations

import pytest


def _minimal_design() -> dict:
    return {
        "api_endpoints": [
            {
                "method": "GET",
                "path": "/api/v1/orders/{orderId}/items/{itemId}",
                "description": "查询订单条目",
                "request_body": "",
                "response_body": "{ id, qty }",
                "auth_required": False,
                "related_features": [],
            }
        ],
        "db_schema": {
            "tables": [
                {
                    "table_name": "Order Item",
                    "description": "订单条目",
                    "columns": [
                        {"name": "id", "type": "bigint"},
                        {"name": "geometry_data", "type": "geometry"},
                        {"name": "2fa_flag", "type": "boolean"},
                    ],
                    "indexes": [
                        {"columns": ["id", "geometry_data"], "unique": True, "name": "uk_item"},
                        "KEY idx_flag (2fa_flag)",
                    ],
                },
                {
                    "table_name": "123abc",
                    "columns": [{"name": "id", "type": "int"}],
                },
            ],
            "relationships": [],
        },
    }


def test_empty_design_is_rejected(tmp_path):
    from app.tools.codegen import generate_artifacts

    manifest = generate_artifacts({}, {}, "python", tmp_path)

    assert manifest["enabled"] is False
    assert manifest["reason"] == "design_incomplete"


def test_api_only_design_generates_without_tables(tmp_path):
    from app.tools.codegen import generate_artifacts

    design = {"api_endpoints": [{"method": "GET", "path": "/ping", "description": "健康检查"}]}
    manifest = generate_artifacts({}, design, "go", tmp_path)

    assert manifest["enabled"] is True
    assert manifest["tables"] == 0
    assert manifest["endpoints"] == 1


def test_table_only_design_generates_without_endpoints(tmp_path):
    from app.tools.codegen import generate_artifacts

    design = {
        "db_schema": {
            "tables": [
                {"table_name": "logs", "columns": [{"name": "id", "type": "bigint"}]}
            ]
        }
    }
    manifest = generate_artifacts({}, design, "java", tmp_path)

    assert manifest["enabled"] is True
    assert manifest["endpoints"] == 0
    assert manifest["tables"] == 1


def test_identifiers_are_sanitized():
    from app.tools.codegen.ddl import build_ddl

    sql = build_ddl(_minimal_design())

    assert "CREATE TABLE IF NOT EXISTS order_item" in sql
    assert "CREATE TABLE IF NOT EXISTS t_123abc" in sql
    # Unknown type falls back to TEXT.
    assert "geometry_data TEXT" in sql
    # Column starting with a digit gets a safe prefix in both column and index.
    assert "t_2fa_flag BOOLEAN" in sql


def test_index_variants_are_parsed():
    from app.tools.codegen.ddl import build_ddl

    sql = build_ddl(_minimal_design())

    assert "CREATE UNIQUE INDEX IF NOT EXISTS uk_item ON order_item (id, geometry_data);" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_flag ON order_item (t_2fa_flag);" in sql


def test_multi_param_path_generates_all_parameters():
    from app.tools.codegen.openapi import build_openapi

    spec = build_openapi({}, _minimal_design())
    params = spec["paths"]["/api/v1/orders/{orderId}/items/{itemId}"]["get"]["parameters"]

    assert [item["name"] for item in params] == ["orderId", "itemId"]
    assert all(item["required"] for item in params)


def test_missing_related_features_falls_back_to_path_tag():
    from app.tools.codegen.openapi import build_openapi

    spec = build_openapi({}, _minimal_design())
    operation = spec["paths"]["/api/v1/orders/{orderId}/items/{itemId}"]["get"]

    assert operation["tags"] == ["orders"]
    assert "security" not in operation


def test_long_description_is_truncated():
    from app.tools.codegen.openapi import build_openapi

    design = {
        "api_endpoints": [
            {
                "method": "POST",
                "path": "/api/v1/notes",
                "description": "说明" * 400,
                "request_body": "{ content }",
                "response_body": "{ id }",
                "auth_required": True,
            }
        ]
    }
    spec = build_openapi({}, design)
    operation = spec["paths"]["/api/v1/notes"]["post"]

    assert len(operation["responses"]["200"]["description"]) <= 300
    assert operation["requestBody"]["content"]["application/json"]["schema"]["description"]
    assert operation["security"] == [{"bearerAuth": []}]


@pytest.mark.parametrize(
    "path,module,expected",
    [
        ("/api/v1/books", "books", ""),
        ("/api/books/{id}", "books", "/{id}"),
        ("/books/{id}/cancel", "books", "/{id}/cancel"),
        ("/api/v1/orders/{id}", "orders", "/{id}"),
        ("/api/v1/auth/wx-login", "auth", "/wx-login"),
        ("/v2/books", "books", ""),
    ],
)
def test_relative_path_strips_prefixes(path, module, expected):
    from app.tools.codegen.backend import relative_path

    assert relative_path(path, module) == expected


@pytest.mark.parametrize("language", ["python", "node", "java", "go"])
def test_module_prefix_is_not_duplicated(tmp_path, language):
    from app.tools.codegen import generate_artifacts

    design = {
        "api_endpoints": [
            {"method": "GET", "path": "/api/books", "description": "列表"},
            {"method": "GET", "path": "/api/books/{id}", "description": "详情"},
        ]
    }
    generate_artifacts({}, design, language, tmp_path)

    paths = {
        "python": "backend/app/routes/books.py",
        "node": "backend/src/books/books.controller.ts",
        "java": "backend/src/main/java/com/example/demo/controller/BooksController.java",
        "go": "backend/handlers/books.go",
    }
    body = (tmp_path / paths[language]).read_text(encoding="utf-8")

    assert "api/books/api/books" not in body
    assert "/api/books" not in body or language == "java"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("PYTHON", "python"),
        (" Node ", "node"),
        ("GoLang", "go"),
        ("spring-boot", "java"),
        ("", ""),
        ("rust", ""),
        (None, ""),
    ],
)
def test_language_aliases(value, expected):
    from app.tools.codegen import normalize_language

    assert normalize_language(value) == expected
