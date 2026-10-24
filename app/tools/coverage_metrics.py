"""Feature traceability scoring for PRD -> technical design.

Matching is graded instead of boolean:

* ``1.0``  the artifact lists the PRD ``feature_id`` in ``related_feature_ids``
* ``0.8``  the artifact lists the exact feature name in ``related_features``
* ``0.5``  a feature term appears somewhere in the artifact text
* ``0.0``  no trace

The previous version fabricated placeholder endpoints and tables to push the
score to 1.0. That produced deliverables full of ``/feature-modules/*/actions``
stubs and hid real gaps. Missing coverage is now reported and patched
explicitly by the engineer instead of being papered over.
"""

from __future__ import annotations

import json
import re
from typing import Any

MATCH_ID = 1.0
MATCH_NAME = 0.8
MATCH_TERM = 0.5


def score_prd_tech_coverage(
    prd: dict[str, Any] | None,
    design: dict[str, Any] | None,
) -> float:
    """Estimate whether technical design covers PRD feature modules."""
    return coverage_report(prd, design)["prd_tech"]["score"]


def score_api_feature_coverage(
    prd: dict[str, Any] | None,
    design: dict[str, Any] | None,
) -> float:
    """Estimate whether PRD feature modules are represented in API design."""
    return coverage_report(prd, design)["api"]["score"]


def score_db_feature_coverage(
    prd: dict[str, Any] | None,
    design: dict[str, Any] | None,
) -> float:
    """Estimate whether PRD feature modules are represented in DB schema."""
    return coverage_report(prd, design)["db"]["score"]


def coverage_report(
    prd: dict[str, Any] | None,
    design: dict[str, Any] | None,
) -> dict[str, Any]:
    """Per-feature traceability detail for API, DB, and the whole design."""
    features = collect_feature_terms(prd or {})
    design = design or {}
    endpoints = [item for item in (design.get("api_endpoints") or []) if isinstance(item, dict)]
    tables = [
        item
        for item in ((design.get("db_schema") or {}).get("tables") or [])
        if isinstance(item, dict)
    ]

    api = _score_bucket(features, endpoints, _text_of(endpoints))
    db = _score_bucket(features, tables, _text_of(tables))
    prd_tech = _score_bucket(features, None, normalize_text(json.dumps(design, ensure_ascii=False)))
    return {"api": api, "db": db, "prd_tech": prd_tech, "feature_count": len(features)}


def missing_feature_mappings(
    prd: dict[str, Any] | None,
    design: dict[str, Any] | None,
) -> dict[str, list[str]]:
    """Return feature module names with no API and/or DB representation."""
    report = coverage_report(prd, design)
    return {
        "api": report["api"]["missing"],
        "db": report["db"]["missing"],
    }


def report_coverage_gaps(
    prd: dict[str, Any] | None,
    design: dict[str, Any] | None,
) -> dict[str, Any]:
    """Structured gap report used by the engineer patch loop and reviewer."""
    report = coverage_report(prd, design)
    return {
        "api": report["api"]["missing"],
        "db": report["db"]["missing"],
        "api_score": report["api"]["score"],
        "db_score": report["db"]["score"],
        "prd_tech_score": report["prd_tech"]["score"],
        "feature_count": report["feature_count"],
        "details": report,
    }


def _score_bucket(
    features: list[dict[str, Any]],
    items: list[dict[str, Any]] | None,
    text: str,
) -> dict[str, Any]:
    if not features:
        return {"score": 0.0, "matched": [], "missing": []}

    matched: list[dict[str, Any]] = []
    missing: list[str] = []
    total = 0.0
    for feature in features:
        weight = _match_feature(feature, items, text)
        total += weight
        if weight > 0:
            matched.append({"id": feature["id"], "name": feature["name"], "weight": weight})
        else:
            missing.append(feature["name"])
    return {
        "score": round(total / len(features), 4),
        "matched": matched,
        "missing": missing,
    }


def _match_feature(
    feature: dict[str, Any],
    items: list[dict[str, Any]] | None,
    text: str,
) -> float:
    if items:
        return match_items(feature, items)[0]
    if terms_match(feature["terms"], text):
        return MATCH_TERM
    return 0.0


def match_items(
    feature: dict[str, Any],
    items: list[dict[str, Any]] | None,
) -> tuple[float, list[dict[str, Any]]]:
    """Return the best match weight and every artifact carrying the feature."""
    if not items:
        return 0.0, []

    feature_id = normalize_text(feature["id"])
    if feature_id:
        hits = [
            item
            for item in items
            if feature_id
            in {
                normalize_text(str(value))
                for value in (item.get("related_feature_ids") or [])
                if str(value).strip()
            }
        ]
        if hits:
            return MATCH_ID, hits

    feature_name = normalize_text(feature["name"])
    if feature_name:
        hits = [
            item
            for item in items
            if feature_name
            in {
                normalize_text(str(value))
                for value in (item.get("related_features") or [])
                if str(value).strip()
            }
        ]
        if hits:
            return MATCH_NAME, hits

    hits = [
        item
        for item in items
        if terms_match(feature["terms"], normalize_text(json.dumps(item, ensure_ascii=False)))
    ]
    if hits:
        return MATCH_TERM, hits
    return 0.0, []


def _text_of(items: list[dict[str, Any]]) -> str:
    return normalize_text(json.dumps(items, ensure_ascii=False))


def collect_feature_terms(prd: dict[str, Any]) -> list[dict[str, Any]]:
    features = []
    for index, module in enumerate(prd.get("feature_modules") or [], start=1):
        if not isinstance(module, dict):
            continue
        name = str(module.get("name") or f"feature_{index}").strip()
        feature_id = str(module.get("feature_id") or "").strip() or slugify(name, index)
        terms = []
        if module.get("name"):
            terms.append(str(module["name"]))
        if module.get("description"):
            terms.append(str(module["description"]))
        terms.extend(str(item) for item in module.get("sub_features") or [] if item)
        terms.extend(str(item) for item in module.get("acceptance_criteria") or [] if item)
        compact_terms = [term for term in terms if normalize_text(term)]
        if compact_terms:
            features.append({"id": feature_id, "name": name, "terms": compact_terms})
    return features


def terms_match(terms: list[str], text: str) -> bool:
    return any(term_appears(term, text) for term in terms)


def term_appears(term: str, text: str) -> bool:
    normalized = normalize_text(term)
    if not normalized:
        return False
    if normalized in text:
        return True
    tokens = [token for token in re.split(r"\s+", normalized) if len(token) >= 3]
    return bool(tokens) and any(token in text for token in tokens)


def normalize_text(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[_\-_/|:;,.!?()\[\]{}\"']", " ", value)
    value = re.sub(r"[，。！？、；：）（【】《》“”‘’]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def slugify(value: str, index: int) -> str:
    slug = normalize_text(value)
    slug = re.sub(r"[^0-9a-zA-Z]+", "_", slug).strip("_")
    return slug[:48] or f"feature_{index:02d}"
