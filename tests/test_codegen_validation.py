from __future__ import annotations

import json

import pytest

pytest.importorskip("openapi_spec_validator")
pytest.importorskip("sqlglot")


def _design() -> dict:
    return {
        "architecture_overview": "分层单体",
        "api_endpoints": [
            {
                "method": "GET",
                "path": "/api/v1/bookings/{id}",
                "description": "查询预约详情",
                "response_body": "{ id, status }",
                "auth_required": True,
                "related_features": ["预约管理"],
            },
            {
                "method": "POST",
                "path": "/api/v1/bookings/{id}/cancel",
                "description": "取消预约",
                "request_body": "{ reason }",
                "response_body": "{ id, status }",
                "auth_required": True,
                "related_features": ["预约管理"],
            },
            {
                "method": "POST",
                "path": "/api/v1/bookings",
                "description": "创建预约",
                "request_body": "{ session_id, member_id }",
                "response_body": "{ id }",
                "auth_required": True,
                "related_features": ["预约管理"],
            },
        ],
        "db_schema": {
            "database_type": "PostgreSQL",
            "tables": [
                {
                    "table_name": "booking",
                    "description": "预约表",
                    "columns": [
                        {"name": "id", "type": "bigint", "description": "主键"},
                        {"name": "session_id", "type": "bigint", "description": "场次"},
                        {"name": "member_id", "type": "bigint", "description": "会员"},
                        {"name": "status", "type": "varchar(32)", "description": "状态"},
                        {
                            "name": "cancel_reason",
                            "type": "varchar(200)",
                            "description": "取消原因，含 'quote' 与换行\n第二行",
                        },
                        {"name": "created_at", "type": "timestamp", "description": "创建时间"},
                    ],
                    "indexes": [
                        "CREATE UNIQUE INDEX uk_booking_active ON booking(session_id, member_id) WHERE status = 'BOOKED'",
                        "INDEX(member_id, created_at DESC)",
                        "UNIQUE KEY uk_booking_no (status)",
                        {"columns": ["session_id"], "unique": False, "name": "idx_session"},
                    ],
                },
                {
                    "table_name": "member",
                    "columns": [
                        {"name": "id", "type": "bigint"},
                        {"name": "phone", "type": "varchar(20)"},
                    ],
                    "indexes": ["INDEX(phone)"],
                },
            ],
            "relationships": ["member 1:N booking"],
        },
    }


def test_table_without_primary_key_is_valid(tmp_path):
    from openapi_spec_validator import validate

    from app.tools.codegen import generate_artifacts

    design = {
        "api_endpoints": [{"method": "GET", "path": "/api/v1/meta", "description": "元数据"}],
        "db_schema": {
            "tables": [
                {
                    "table_name": "app_meta",
                    "description": "元数据表",
                    "columns": [
                        {"name": "key", "type": "varchar(64)"},
                        {"name": "value", "type": "varchar(255)"},
                    ],
                }
            ]
        },
    }
    generate_artifacts({}, design, "go", tmp_path)
    spec = json.loads((tmp_path / "openapi.json").read_text(encoding="utf-8"))

    validate(spec)
    assert "required" not in spec["components"]["schemas"]["app_meta"]


def test_openapi_document_passes_spec_validation(tmp_path):
    from openapi_spec_validator import validate

    from app.tools.codegen import generate_artifacts

    generate_artifacts({"product_name": "预约系统"}, _design(), "python", tmp_path)
    spec = json.loads((tmp_path / "openapi.json").read_text(encoding="utf-8"))

    validate(spec)
    assert len(spec["paths"]) == 3
    assert "booking" in spec["components"]["schemas"]
    assert "member" in spec["components"]["schemas"]


def test_ddl_parses_as_postgres(tmp_path):
    from sqlglot import parse

    from app.tools.codegen import generate_artifacts

    generate_artifacts({}, _design(), "go", tmp_path)
    sql = (tmp_path / "schema.sql").read_text(encoding="utf-8")

    statements = [item for item in parse(sql, read="postgres") if item]
    assert len(statements) >= 8
    kinds = {statement.key for statement in statements}
    assert "create" in kinds


def test_ddl_quotes_embedded_apostrophes():
    from app.tools.codegen.ddl import build_ddl

    sql = build_ddl(_design())

    assert "'取消原因，含 ''quote'' 与换行 第二行'" in sql


def test_full_create_index_statement_is_passed_through():
    from app.tools.codegen.ddl import build_ddl

    sql = build_ddl(_design())

    assert (
        "CREATE UNIQUE INDEX IF NOT EXISTS uk_booking_active "
        "ON booking(session_id, member_id) WHERE status = 'BOOKED';"
    ) in sql
    # Already-named statements must not get a second IF NOT EXISTS.
    assert sql.upper().count("IF NOT EXISTS UK_BOOKING_ACTIVE".upper()) == 1


def test_index_function_form_is_normalized():
    from app.tools.codegen.ddl import build_ddl

    sql = build_ddl(_design())

    assert "CREATE INDEX IF NOT EXISTS ix_booking_member_id_created_at" in sql
    assert "ON booking (member_id, created_at);" in sql


REQUIRED_FILES = {
    "python": [
        "backend/app/main.py",
        "backend/app/routes/bookings.py",
        "backend/requirements.txt",
        "backend/Dockerfile",
    ],
    "node": [
        "backend/src/main.ts",
        "backend/src/app.module.ts",
        "backend/src/bookings/bookings.controller.ts",
        "backend/package.json",
    ],
    "java": [
        "backend/src/main/java/com/example/demo/DemoApplication.java",
        "backend/src/main/java/com/example/demo/controller/BookingsController.java",
        "backend/pom.xml",
    ],
    "go": ["backend/main.go", "backend/handlers/bookings.go", "backend/go.mod"],
}


@pytest.mark.parametrize("language", sorted(REQUIRED_FILES))
def test_language_outputs_are_non_empty(tmp_path, language):
    from app.tools.codegen import generate_artifacts

    generate_artifacts({"product_name": "预约系统"}, _design(), language, tmp_path)

    for relative in REQUIRED_FILES[language]:
        path = tmp_path / relative
        assert path.exists(), f"{language} missing {relative}"
        assert path.stat().st_size > 0, f"{language} empty {relative}"

    for relative in ("openapi.yaml", "openapi.json", "schema.sql", "frontend/package.json"):
        assert (tmp_path / relative).stat().st_size > 0


def test_all_languages_share_same_spec_and_ddl(tmp_path):
    from app.tools.codegen import generate_artifacts

    payloads = {}
    for language in ("python", "node", "java", "go"):
        generate_artifacts({}, _design(), language, tmp_path / language)
        payloads[language] = (
            (tmp_path / language / "openapi.yaml").read_text(encoding="utf-8"),
            (tmp_path / language / "schema.sql").read_text(encoding="utf-8"),
        )

    base_spec, base_sql = payloads["python"]
    for language, (spec, sql) in payloads.items():
        assert spec == base_spec, f"{language} spec differs"
        assert sql == base_sql, f"{language} ddl differs"
