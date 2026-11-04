"""Generate delivery artifacts: OpenAPI spec, DDL, backend and frontend code."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.tools.codegen.backend import LANGUAGE_LABELS, SUPPORTED, build_backend
from app.tools.codegen.ddl import build_ddl
from app.tools.codegen.frontend import build_frontend
from app.tools.codegen.openapi import build_openapi, to_yaml

_KIND_RULES = (
    ("openapi.", "spec"),
    ("schema.sql", "ddl"),
    ("backend/", "backend"),
    ("frontend/", "frontend"),
)


def _kind(path: str) -> str:
    for marker, kind in _KIND_RULES:
        if marker in path:
            return kind
    return "doc"


def normalize_language(value: str | None) -> str:
    text = str(value or "").strip().lower()
    if text in SUPPORTED:
        return text
    # Accept separators and casing: "spring-boot", "Spring Boot", "golang".
    compact = "".join(char for char in text if char.isalnum())
    aliases = {
        "py": "python",
        "fastapi": "python",
        "ts": "node",
        "typescript": "node",
        "nestjs": "node",
        "nodejs": "node",
        "spring": "java",
        "springboot": "java",
        "golang": "go",
        "gin": "go",
    }
    return aliases.get(compact, "")


def generate_artifacts(
    prd_doc: dict[str, Any],
    design: dict[str, Any],
    language: str | None,
    output_dir: Path,
) -> dict[str, Any]:
    """Write artifacts under output_dir and return a manifest for the UI."""
    lang = normalize_language(language)
    if not lang:
        return {"enabled": False, "reason": "no_language_selected"}
    if not (design.get("api_endpoints") or design.get("db_schema")):
        return {"enabled": False, "reason": "design_incomplete"}

    files: dict[str, str] = {}
    openapi_doc = build_openapi(prd_doc, design)
    files["openapi.yaml"] = to_yaml(openapi_doc)
    files["openapi.json"] = json.dumps(openapi_doc, ensure_ascii=False, indent=2)
    files["schema.sql"] = build_ddl(design)
    files.update(build_backend(design, prd_doc, lang))
    files.update(build_frontend(design))

    written: list[dict[str, Any]] = []
    for relative, content in files.items():
        target = output_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        data = content if isinstance(content, str) else str(content)
        target.write_text(data, encoding="utf-8")
        written.append(
            {
                "path": relative,
                "kind": _kind(relative),
                "bytes": len(data.encode("utf-8")),
            }
        )

    written.sort(key=lambda item: (item["kind"], item["path"]))
    counts: dict[str, int] = {}
    for item in written:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1

    return {
        "enabled": True,
        "language": lang,
        "language_label": LANGUAGE_LABELS.get(lang, lang),
        "file_count": len(written),
        "files": written,
        "counts": counts,
        "endpoints": len(openapi_doc.get("paths") or {}),
        "tables": len((openapi_doc.get("components") or {}).get("schemas") or {}),
    }
