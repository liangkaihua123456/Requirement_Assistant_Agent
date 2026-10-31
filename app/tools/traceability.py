"""Build the feature traceability matrix returned to the UI.

Rows are PRD feature modules; columns are service, API, table, and acceptance
criteria. The weight column reuses the same matcher as the review gate so the
matrix and the review can never disagree.
"""

from __future__ import annotations

import json
from typing import Any

from app.tools.coverage_metrics import (
    MATCH_TERM,
    collect_feature_terms,
    coverage_report,
    match_items,
    normalize_text,
    terms_match,
)


def build_traceability(
    prd: dict[str, Any] | None,
    design: dict[str, Any] | None,
) -> dict[str, Any]:
    prd = prd or {}
    design = design or {}
    features = collect_feature_terms(prd)
    endpoints = [item for item in (design.get("api_endpoints") or []) if isinstance(item, dict)]
    tables = [
        item
        for item in ((design.get("db_schema") or {}).get("tables") or [])
        if isinstance(item, dict)
    ]
    services = [item for item in (design.get("services") or []) if isinstance(item, dict)]
    modules = [item for item in (prd.get("feature_modules") or []) if isinstance(item, dict)]
    by_id = {str(item.get("feature_id") or ""): item for item in modules}
    by_name = {str(item.get("name") or ""): item for item in modules}

    rows = []
    for feature in features:
        api_weight, api_items = match_items(feature, endpoints)
        db_weight, db_items = match_items(feature, tables)
        service_hits = [
            service
            for service in services
            if terms_match(
                feature["terms"], normalize_text(json.dumps(service, ensure_ascii=False))
            )
        ]
        module = by_id.get(feature["id"]) or by_name.get(feature["name"]) or {}
        rows.append(
            {
                "feature_id": feature["id"],
                "name": feature["name"],
                "priority": str(module.get("priority") or ""),
                "acceptance_criteria": [
                    str(item) for item in (module.get("acceptance_criteria") or [])
                ],
                "service": {
                    "weight": MATCH_TERM if service_hits else 0.0,
                    "items": [_service_row(item) for item in service_hits],
                },
                "api": {"weight": api_weight, "items": [_api_row(item) for item in api_items]},
                "db": {"weight": db_weight, "items": [_table_row(item) for item in db_items]},
            }
        )

    report = coverage_report(prd, design)
    return {
        "features": rows,
        "summary": {
            "feature_count": report["feature_count"],
            "api_score": report["api"]["score"],
            "db_score": report["db"]["score"],
            "prd_tech_score": report["prd_tech"]["score"],
            "missing_api": report["api"]["missing"],
            "missing_db": report["db"]["missing"],
        },
    }


def _api_row(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "method": str(item.get("method") or "").upper(),
        "path": str(item.get("path") or ""),
        "description": str(item.get("description") or ""),
        "related_feature_ids": [str(value) for value in (item.get("related_feature_ids") or [])],
    }


def _table_row(item: dict[str, Any]) -> dict[str, Any]:
    columns = item.get("columns") or []
    return {
        "table_name": str(item.get("table_name") or ""),
        "description": str(item.get("description") or ""),
        "column_count": len(columns) if isinstance(columns, list) else 0,
        "related_feature_ids": [str(value) for value in (item.get("related_feature_ids") or [])],
    }


def _service_row(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(item.get("name") or ""),
        "responsibility": str(item.get("responsibility") or ""),
    }
