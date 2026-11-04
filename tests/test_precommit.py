from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _clean_design() -> dict:
    return {
        "api_endpoints": [
            {"method": "GET", "path": "/api/v1/orders/{id}", "description": "详情"},
            {"method": "POST", "path": "/api/v1/orders", "description": "创建"},
        ],
        "db_schema": {
            "tables": [
                {
                    "table_name": "orders",
                    "columns": [{"name": "id", "type": "bigint"}],
                }
            ]
        },
    }


def test_duplicate_prefix_detector_hits(tmp_path):
    from scripts.check_artifacts import _check_duplicate_prefix

    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / "controller.ts").write_text(
        "@Controller('api/v1/orders')\n@Get('/api/v1/orders')\n", encoding="utf-8"
    )

    problems = _check_duplicate_prefix(tmp_path)

    assert problems
    assert "路径前缀重复" in problems[0]


def test_duplicate_prefix_detector_ignores_clean_tree(tmp_path):
    from scripts.check_artifacts import _check_duplicate_prefix

    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / "main.py").write_text(
        'router = APIRouter(prefix="/orders")\n', encoding="utf-8"
    )

    assert _check_duplicate_prefix(tmp_path) == []


def test_duplicate_prefix_detector_reads_nested_files(tmp_path):
    from scripts.check_artifacts import _check_duplicate_prefix

    nested = tmp_path / "backend" / "src" / "orders"
    nested.mkdir(parents=True)
    (nested / "orders.controller.ts").write_text(
        "// /api/v1/orders/api/orders\n", encoding="utf-8"
    )

    assert _check_duplicate_prefix(tmp_path)


def test_validate_one_accepts_clean_design():
    from scripts.check_artifacts import validate_one

    assert validate_one("t1", {}, _clean_design(), "python", strict=True) == []


def test_validate_one_reports_missing_artifacts():
    from scripts.check_artifacts import validate_one

    problems = validate_one("t2", {}, {}, "python", strict=True)

    assert problems
    assert "产物未生成" in problems[0]


def test_validate_one_detects_broken_python(tmp_path, monkeypatch):
    import scripts.check_artifacts as checker

    def fake_generate(prd, design, language, output_dir):
        backend = Path(output_dir) / "backend"
        backend.mkdir(parents=True, exist_ok=True)
        (backend / "main.py").write_text("def broken(:\n", encoding="utf-8")
        (Path(output_dir) / "openapi.json").write_text(
            '{"openapi": "3.0.3", "info": {"title": "x", "version": "1"}, '
            '"paths": {}}',
            encoding="utf-8",
        )
        return {"enabled": True, "language": language, "files": []}

    monkeypatch.setattr("app.tools.codegen.generate_artifacts", fake_generate)

    problems = checker.validate_one("t3", {}, _clean_design(), "python", strict=False)

    assert any("语法错误" in item for item in problems)


def test_validate_one_detects_invalid_openapi(monkeypatch):
    import scripts.check_artifacts as checker

    def fake_generate(prd, design, language, output_dir):
        out = Path(output_dir)
        (out / "backend").mkdir(parents=True, exist_ok=True)
        (out / "backend" / "main.py").write_text("x = 1\n", encoding="utf-8")
        (out / "openapi.json").write_text(
            '{"openapi": "3.0.3", "paths": {"a": {"b": {}}}}', encoding="utf-8"
        )
        return {"enabled": True, "language": language, "files": []}

    monkeypatch.setattr("app.tools.codegen.generate_artifacts", fake_generate)

    problems = checker.validate_one("t4", {}, _clean_design(), "python", strict=False)

    assert any("OpenAPI 不合法" in item for item in problems)


def test_resolve_python_prefers_marker(tmp_path, monkeypatch):
    import scripts.precommit as precommit

    marker = tmp_path / ".project-python"
    marker.write_text(sys.executable, encoding="utf-8")

    monkeypatch.setattr(precommit, "ROOT", tmp_path)
    monkeypatch.delenv("PROJECT_PYTHON", raising=False)

    assert precommit.resolve_python() == sys.executable


def test_resolve_python_prefers_env(tmp_path, monkeypatch):
    import scripts.precommit as precommit

    monkeypatch.setattr(precommit, "ROOT", tmp_path)
    monkeypatch.setenv("PROJECT_PYTHON", sys.executable)

    assert precommit.resolve_python() == sys.executable


def test_resolve_python_falls_back_to_sys_executable(tmp_path, monkeypatch):
    import scripts.precommit as precommit

    monkeypatch.setattr(precommit, "ROOT", tmp_path)
    monkeypatch.delenv("PROJECT_PYTHON", raising=False)

    assert precommit.resolve_python() == sys.executable
