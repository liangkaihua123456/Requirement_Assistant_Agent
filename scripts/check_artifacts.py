"""Validate generated code artifacts.

Reads recent tasks that requested code output, regenerates their artifacts into
a temporary directory and checks them against real validators:

  - OpenAPI 3.0 structure (openapi-spec-validator)
  - PostgreSQL DDL syntax (sqlglot)
  - Python syntax (ast)
  - duplicated module prefixes in routes
  - required files present and non-empty

Exit code 1 when any problem is found, so it can gate a commit.
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
import re
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

# sqlglot warns about partial-index predicates it cannot model; those are not
# syntax errors, so keep the output clean.
logging.getLogger("sqlglot").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "data" / "tasks.db"

REQUIRED = {
    "python": ["backend/app/main.py", "backend/requirements.txt"],
    "node": ["backend/src/main.ts", "backend/package.json"],
    "java": ["backend/src/main/java/com/example/demo/DemoApplication.java", "backend/pom.xml"],
    "go": ["backend/main.go", "backend/go.mod"],
}

_DUPLICATE_PATTERNS = (
    # /api/api/ or /api/v1/api/
    re.compile(r"/api(?:/v\d+)?/api\b", re.IGNORECASE),
    # /api/v1/orders/api/orders — the module is mounted twice
    re.compile(r"/api(?:/v\d+)?/([A-Za-z0-9_-]+)/api(?:/v\d+)?/\1\b", re.IGNORECASE),
)


def _load_tasks(limit: int, task_id: str | None) -> list[tuple[str, dict, dict, str]]:
    if not DB_PATH.exists():
        return []
    connection = sqlite3.connect(DB_PATH)
    if task_id:
        rows = connection.execute(
            "select task_id, state_snapshot from tasks where task_id = ?", (task_id,)
        ).fetchall()
    else:
        rows = connection.execute(
            "select task_id, state_snapshot from tasks "
            "where state_snapshot like '%\"target_language\"%' "
            "order by created_at desc limit ?",
            (limit * 4,),
        ).fetchall()
    connection.close()

    picked: list[tuple[str, dict, dict, str]] = []
    for row_id, snapshot in rows:
        try:
            state = json.loads(snapshot or "{}")
        except Exception:
            continue
        language = str(state.get("target_language") or "").strip().lower()
        design = state.get("technical_design") or {}
        if not language or not (design.get("api_endpoints") or design.get("db_schema")):
            continue
        picked.append((row_id, state.get("prd_doc") or {}, design, language))
        if len(picked) >= limit:
            break
    return picked


_NEST_CONTROLLER = re.compile(r"@Controller\(['\"]([^'\"]+)['\"]\)")
_NEST_METHOD = re.compile(r"@(?:Get|Post|Put|Patch|Delete)\(['\"]([^'\"]*)['\"]\)")


def _check_duplicate_prefix(root: Path) -> list[str]:
    problems: list[str] = []
    for path in (root / "backend").rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".ts", ".java", ".go"}:
            continue
        body = path.read_text(encoding="utf-8", errors="ignore")

        for pattern in _DUPLICATE_PATTERNS:
            match = pattern.search(body)
            if match:
                problems.append(
                    f"{path.relative_to(root)}: 路径前缀重复（{match.group(0)}）"
                )
                break
        else:
            # NestJS mounts controller + method path together, so both starting
            # with /api means the prefix is applied twice.
            controllers = _NEST_CONTROLLER.findall(body)
            methods = _NEST_METHOD.findall(body)
            if any(item.lstrip("/").startswith("api") for item in controllers) and any(
                item.lstrip("/").startswith("api") for item in methods
            ):
                problems.append(
                    f"{path.relative_to(root)}: 路径前缀重复（@Controller 与 @Get 都带 api 前缀）"
                )
    return problems


def validate_one(
    task_id: str,
    prd: dict[str, Any],
    design: dict[str, Any],
    language: str,
    *,
    strict: bool,
) -> list[str]:
    from app.tools.codegen import generate_artifacts

    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        manifest = generate_artifacts(prd, design, language, root)
        if not manifest.get("enabled"):
            return [f"{task_id}: 产物未生成（{manifest.get('reason')}）"]

        spec_path = root / "openapi.json"
        if spec_path.exists():
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
            try:
                from openapi_spec_validator import validate

                validate(spec)
            except ImportError:
                if strict:
                    problems.append(f"{task_id}: 缺少 openapi-spec-validator，无法校验规范")
            except Exception as exc:
                problems.append(f"{task_id}: OpenAPI 不合法 — {str(exc).splitlines()[0][:160]}")

        sql_path = root / "schema.sql"
        if sql_path.exists():
            try:
                import sqlglot

                sqlglot.parse(sql_path.read_text(encoding="utf-8"), read="postgres")
            except ImportError:
                if strict:
                    problems.append(f"{task_id}: 缺少 sqlglot，无法校验 SQL")
            except Exception as exc:
                problems.append(f"{task_id}: SQL 解析失败 — {str(exc).splitlines()[0][:160]}")

        for path in (root / "backend").rglob("*.py"):
            try:
                ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError as exc:
                problems.append(f"{task_id}: {path.relative_to(root)} 语法错误 — {exc}")

        for relative in REQUIRED.get(language, []):
            target = root / relative
            if not target.exists():
                problems.append(f"{task_id}: 缺少必需文件 {relative}")
            elif target.stat().st_size == 0:
                problems.append(f"{task_id}: 必需文件为空 {relative}")

        problems.extend(f"{task_id}: {item}" for item in _check_duplicate_prefix(root))

    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5, help="recent tasks to validate")
    parser.add_argument("--task", default="", help="validate one task id")
    parser.add_argument("--strict", action="store_true", help="missing validator is a failure")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    tasks = _load_tasks(args.limit, args.task or None)
    if not tasks:
        print("没有找到带代码产物的任务，跳过规范校验")
        return 0

    all_problems: list[str] = []
    for task_id, prd, design, language in tasks:
        problems = validate_one(task_id, prd, design, language, strict=args.strict)
        all_problems.extend(problems)
        if not args.quiet:
            status = "OK" if not problems else f"{len(problems)} 个问题"
            print(f"  {task_id} [{language:6}] {status}")

    if all_problems:
        print("\n规范校验失败：")
        for item in all_problems:
            print(f"  - {item}")
        return 1

    print(f"\n规范校验通过（{len(tasks)} 个任务）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
