"""PostgreSQL DDL generation from a technical design."""

from __future__ import annotations

import re
from typing import Any

_IDENT = re.compile(r"[^0-9a-zA-Z_]")
_INDEX_PATTERN = re.compile(
    r"^\s*(UNIQUE\s+)?(?:KEY|INDEX)\s+([A-Za-z0-9_]+)?\s*\(([^)]*)\)\s*$",
    re.IGNORECASE,
)


def _ident(raw: str, fallback: str = "unnamed") -> str:
    name = _IDENT.sub("_", str(raw or "").strip())
    if not name:
        name = fallback
    if name[0].isdigit():
        name = f"t_{name}"
    return name.lower()


def _sql_type(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return "TEXT"
    lowered = text.lower()
    if "uuid" in lowered:
        return "UUID"
    if "jsonb" in lowered:
        return "JSONB"
    if "json" in lowered:
        return "JSON"
    if "bool" in lowered:
        return "BOOLEAN"
    if "bigserial" in lowered or "bigint" in lowered:
        return "BIGINT"
    if "serial" in lowered or "int" in lowered:
        return "INTEGER"
    if "numeric" in lowered or "decimal" in lowered:
        return re.sub(r"\s+", "", text).upper()
    if "double" in lowered:
        return "DOUBLE PRECISION"
    if "float" in lowered or "real" in lowered:
        return "REAL"
    if "timestamp" in lowered:
        return "TIMESTAMPTZ"
    if "datetime" in lowered:
        return "TIMESTAMP"
    if "date" in lowered:
        return "DATE"
    if "time" in lowered:
        return "TIME"
    if "text" in lowered or "clob" in lowered:
        return "TEXT"
    if "varchar" in lowered or "char" in lowered:
        return re.sub(r"\s+", "", text).upper()
    return "TEXT"


def _column_line(column: dict[str, Any], index: int) -> tuple[str, bool]:
    name = _ident(column.get("name") or f"col_{index + 1}")
    sql_type = _sql_type(column.get("type"))
    parts = [name, sql_type]
    if name == "id" or "primary" in str(column.get("type") or "").lower():
        parts.append("PRIMARY KEY")
    elif "not null" in str(column.get("type") or "").lower():
        parts.append("NOT NULL")
    return "    " + " ".join(parts), name


def build_ddl(design: dict[str, Any]) -> str:
    """Return a complete PostgreSQL script with tables, indexes and comments."""
    schema = design.get("db_schema") or {}
    tables = [item for item in (schema.get("tables") or []) if isinstance(item, dict)]
    database_type = str(schema.get("database_type") or "PostgreSQL")

    lines: list[str] = [
        "-- 由需求交付系统自动生成",
        f"-- 目标数据库：{database_type}",
        "",
    ]

    column_index: dict[str, set[str]] = {}

    for table in tables:
        raw_name = str(table.get("table_name") or "")
        if not raw_name:
            continue
        name = _ident(raw_name)
        columns = [item for item in (table.get("columns") or []) if isinstance(item, dict)]
        if not columns:
            lines.append(f"CREATE TABLE IF NOT EXISTS {name} (")
            lines.append("    id BIGSERIAL PRIMARY KEY")
            lines.append(");")
            lines.append("")
            continue

        rendered: list[str] = []
        column_index[name] = set()
        for index, column in enumerate(columns):
            line, column_name = _column_line(column, index)
            rendered.append(line)
            column_index[name].add(column_name)

        lines.append(f"CREATE TABLE IF NOT EXISTS {name} (")
        lines.append(",\n".join(rendered))
        lines.append(");")

        comment = str(table.get("description") or "").strip()
        if comment:
            lines.append(f"COMMENT ON TABLE {name} IS '{_escape(comment[:300])}';")
        for index, column in enumerate(columns):
            text = str(column.get("description") or "").strip()
            if text:
                column_name = _ident(column.get("name") or f"col_{index + 1}")
                lines.append(
                    f"COMMENT ON COLUMN {name}.{column_name} IS '{_escape(text[:200])}';"
                )

        for index in table.get("indexes") or []:
            index_name = _index_name(name, index)
            if index_name:
                lines.append(index_name)

        lines.append("")

    relationships = schema.get("relationships") or []
    for relationship in relationships:
        if isinstance(relationship, dict):
            statement = _foreign_key(relationship, column_index)
            if statement:
                lines.append(statement)
        elif str(relationship).strip():
            # Designs usually describe relationships in prose; keep them as
            # comments rather than guessing column names.
            lines.append(f"-- 关系：{_escape(str(relationship).strip()[:200])}")

    if relationships:
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def _index_name(table: str, index: Any) -> str | None:
    if isinstance(index, dict):
        columns = index.get("columns") or index.get("fields") or []
        if isinstance(columns, str):
            columns = [columns]
        unique = bool(index.get("unique"))
        name = str(index.get("name") or "").strip()
    elif isinstance(index, (list, tuple)):
        columns = list(index)
        unique = False
        name = ""
    else:
        raw = str(index or "").strip()
        # Some designs carry a full CREATE INDEX statement; pass it through.
        if raw.upper().startswith("CREATE ") and "INDEX" in raw[:40].upper():
            statement = raw.rstrip(";").strip()
            if "IF NOT EXISTS" not in statement.upper():
                statement = re.sub(
                    r"\s+INDEX\s+", " INDEX IF NOT EXISTS ", statement, count=1, flags=re.I
                )
            return statement + ";"

        match = _INDEX_PATTERN.match(raw)
        if match:
            unique = bool(match.group(1))
            name = (match.group(2) or "").strip()
            columns = [part.strip() for part in match.group(3).split(",") if part.strip()]
        else:
            # Handle "INDEX(a, b DESC)" and plain "a, b" forms.
            stripped = re.sub(r"^(UNIQUE\s+)?(KEY|INDEX)\s*", "", raw, flags=re.I)
            stripped = stripped.strip().rstrip(")").lstrip("(")
            columns = [part.strip() for part in stripped.split(",") if part.strip()]
            unique = "unique" in raw.lower()
            name = ""

    clean = [_ident(str(item).split()[0]) for item in columns if str(item).strip()]
    if not clean:
        return None

    if not name or _IDENT.search(name):
        name = ("ux" if unique else "ix") + "_" + table + "_" + "_".join(clean)
    else:
        name = name.lower()

    keyword = "UNIQUE INDEX" if unique else "INDEX"
    return (
        f"CREATE {keyword} IF NOT EXISTS {name} "
        f"ON {table} ({', '.join(clean)});"
    )


def _foreign_key(relationship: dict[str, Any], columns: dict[str, set[str]]) -> str | None:
    from_table = _ident(relationship.get("from_table") or relationship.get("table") or "")
    from_column = _ident(relationship.get("from_column") or relationship.get("column") or "")
    to_table = _ident(relationship.get("to_table") or relationship.get("references") or "")
    to_column = _ident(relationship.get("to_column") or "id")
    if not from_table or not from_column or not to_table:
        return None
    if from_table not in columns or from_column not in columns.get(from_table, set()):
        return None
    constraint = f"fk_{from_table}_{from_column}"
    return (
        f"ALTER TABLE {from_table}\n"
        f"    ADD CONSTRAINT {constraint} FOREIGN KEY ({from_column}) "
        f"REFERENCES {to_table} ({to_column}) ON DELETE SET NULL;"
    )


def _escape(text: str) -> str:
    return text.replace("'", "''").replace("\n", " ")
