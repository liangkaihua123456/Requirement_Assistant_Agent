"""OpenAPI 3.0 generation from a technical design.

Deterministic: everything comes from the design document, no model calls. The
request/response bodies in the design are free text, so they are carried as
schema descriptions instead of being parsed into properties.
"""

from __future__ import annotations

import re
from typing import Any

_PARAM = re.compile(r"\{([^}]+)\}")

_HTTP_METHODS = ("get", "post", "put", "patch", "delete")


def _clean_type(raw: str) -> str:
    text = str(raw or "string").strip().lower()
    if not text:
        return "string"
    if text.startswith(("int", "bigint", "smallint", "serial")):
        return "integer"
    if text.startswith(("decimal", "numeric", "float", "double", "real")):
        return "number"
    if text.startswith("bool"):
        return "boolean"
    if text.startswith(("timestamp", "datetime", "date", "time")):
        return "string"
    if text.startswith(("json", "jsonb")):
        return "object"
    if text.startswith(("array", "[]")):
        return "array"
    return "string"


def _format_for(raw: str) -> str | None:
    text = str(raw or "").strip().lower()
    if text.startswith("timestamp") or text.startswith("datetime"):
        return "date-time"
    if text.startswith("date"):
        return "date"
    if text.startswith("uuid"):
        return "uuid"
    return None


def _table_schema(table: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for column in table.get("columns") or []:
        if not isinstance(column, dict):
            continue
        name = str(column.get("name") or "").strip()
        if not name:
            continue
        raw_type = str(column.get("type") or "")
        prop: dict[str, Any] = {"type": _clean_type(raw_type)}
        fmt = _format_for(raw_type)
        if fmt:
            prop["format"] = fmt
        if column.get("description"):
            prop["description"] = str(column["description"])[:200]
        if "primary" in raw_type.lower() or name == "id":
            prop["x-primary-key"] = True
            required.append(name)
        properties[name] = prop

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "x-table": table.get("table_name"),
        "description": str(table.get("description") or "")[:300],
    }
    # OpenAPI 3.0 rejects an empty required array.
    if required:
        schema["required"] = required
    return schema


def _operation(endpoint: dict[str, Any]) -> dict[str, Any]:
    path = str(endpoint.get("path") or "")
    params = [
        {
            "name": name,
            "in": "path",
            "required": True,
            "schema": {"type": "string"},
        }
        for name in _PARAM.findall(path)
    ]

    description_parts = [str(endpoint.get("description") or "").strip()]
    if endpoint.get("auth_required"):
        description_parts.append("需要身份认证。")
    if endpoint.get("related_features"):
        description_parts.append(
            "关联功能："
            + "、".join(str(item) for item in endpoint["related_features"][:5])
        )

    request_text = str(endpoint.get("request_body") or "").strip()
    response_text = str(endpoint.get("response_body") or "").strip()

    operation: dict[str, Any] = {
        "summary": f"{str(endpoint.get('method') or 'GET').upper()} {path}"[:80],
        "description": "\n".join(part for part in description_parts if part),
        "operationId": _operation_id(endpoint),
        "tags": _tags(endpoint, path),
        "parameters": params,
        "responses": {
            "200": {
                "description": response_text[:300] or "成功",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "additionalProperties": True,
                            **({"description": response_text[:300]} if response_text else {}),
                        }
                    }
                },
            }
        },
    }

    method = str(endpoint.get("method") or "GET").upper()
    if method in ("POST", "PUT", "PATCH") or request_text:
        operation["requestBody"] = {
            "required": method in ("POST", "PUT", "PATCH"),
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "additionalProperties": True,
                        **({"description": request_text[:300]} if request_text else {}),
                    }
                }
            },
        }

    if endpoint.get("auth_required"):
        operation["security"] = [{"bearerAuth": []}]

    return operation


def _operation_id(endpoint: dict[str, Any]) -> str:
    method = str(endpoint.get("method") or "get").lower()
    path = str(endpoint.get("path") or "")
    slug = re.sub(r"\{[^}]+\}", "by", path)
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", slug).strip("_")
    return f"{method}_{slug}"[:64] or method


def _tags(endpoint: dict[str, Any], path: str) -> list[str]:
    features = [str(item) for item in (endpoint.get("related_features") or []) if item]
    if features:
        return [features[0][:40]]
    parts = [part for part in path.split("/") if part and part not in ("api", "v1")]
    return [parts[0] if parts else "default"]


def build_openapi(prd_doc: dict[str, Any], design: dict[str, Any]) -> dict[str, Any]:
    """Return an OpenAPI 3.0 document for the design."""
    title = str((prd_doc or {}).get("product_name") or "Generated API").strip()
    positioning = str((prd_doc or {}).get("positioning") or "").strip()

    paths: dict[str, Any] = {}
    for endpoint in design.get("api_endpoints") or []:
        if not isinstance(endpoint, dict):
            continue
        path = str(endpoint.get("path") or "").strip()
        method = str(endpoint.get("method") or "GET").lower()
        if not path or method not in _HTTP_METHODS:
            continue
        paths.setdefault(path, {})[method] = _operation(endpoint)

    schemas: dict[str, Any] = {}
    for table in ((design.get("db_schema") or {}).get("tables") or []):
        if not isinstance(table, dict) or not table.get("table_name"):
            continue
        schemas[str(table["table_name"])] = _table_schema(table)

    document: dict[str, Any] = {
        "openapi": "3.0.3",
        "info": {
            "title": title,
            "version": "1.0.0",
            "description": positioning[:500] or "由需求交付系统自动生成",
        },
        "servers": [{"url": "/", "description": "当前服务"}],
        "tags": _collect_tags(paths),
        "paths": paths,
        "components": {
            "schemas": schemas,
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
            },
        },
    }
    return document


def _collect_tags(paths: dict[str, Any]) -> list[dict[str, str]]:
    seen: list[str] = []
    for operations in paths.values():
        for operation in operations.values():
            for tag in operation.get("tags") or []:
                if tag not in seen:
                    seen.append(tag)
    return [{"name": tag} for tag in seen]


def to_yaml(document: dict[str, Any]) -> str:
    """Minimal YAML writer good enough for the generated document."""
    try:
        import yaml

        return yaml.safe_dump(document, allow_unicode=True, sort_keys=False)
    except Exception:
        import json

        return json.dumps(document, ensure_ascii=False, indent=2)
