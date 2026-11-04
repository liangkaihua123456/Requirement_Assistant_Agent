"""Pre-commit gate: tests + artifact validation (+ optional frontend build).

Usage:
    python scripts/precommit.py            # tests + artifacts
    python scripts/precommit.py --full     # also build the frontend
    python scripts/precommit.py --hook     # quieter output for git hooks
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend-vue"


def _npm() -> str:
    return "npm.cmd" if os.name == "nt" else "npm"


def resolve_python() -> str:
    """Pick the interpreter that has pytest and the validators installed.

    Git hooks usually run with the system interpreter, which lacks project
    dependencies, so an explicit marker wins over sys.executable.
    """
    candidates: list[str] = []
    env_value = os.getenv("PROJECT_PYTHON", "").strip()
    if env_value:
        candidates.append(env_value)

    marker = ROOT / ".project-python"
    if marker.exists():
        value = marker.read_text(encoding="utf-8").strip()
        if value:
            candidates.append(value)

    candidates.extend(
        [
            str(ROOT / ".venv" / "Scripts" / "python.exe"),
            str(ROOT / "venv" / "Scripts" / "python.exe"),
            str(ROOT / ".venv" / "bin" / "python"),
        ]
    )

    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return sys.executable


def _run(label: str, command: list[str], cwd: Path) -> tuple[bool, float, str]:
    started = time.perf_counter()
    result = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    elapsed = time.perf_counter() - started
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode == 0, elapsed, output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="also build the frontend")
    parser.add_argument("--hook", action="store_true", help="compact output for git hooks")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    python = resolve_python()
    if not args.hook:
        print(f"[precommit] 解释器：{python}")

    steps: list[tuple[str, list[str], Path]] = [
        ("后端测试", [python, "-m", "pytest", "tests", "-q"], ROOT),
        (
            "产物规范校验",
            [
                python,
                "scripts/check_artifacts.py",
                "--limit",
                "5",
                "--strict",
                "--quiet",
            ],
            ROOT,
        ),
    ]
    if args.full and FRONTEND.exists():
        steps.append(("前端构建", [_npm(), "run", "build"], FRONTEND))

    failures: list[str] = []
    for label, command, cwd in steps:
        if not args.hook:
            print(f"[precommit] {label} ...", flush=True)
        ok, elapsed, output = _run(label, command, cwd)
        if ok:
            if not args.hook:
                print(f"[precommit] {label} 通过（{elapsed:.1f}s）")
            continue
        failures.append(label)
        print(f"[precommit] {label} 失败（{elapsed:.1f}s）")
        tail = "\n".join(output.strip().splitlines()[-25:])
        if tail:
            print(tail)

    if failures:
        print(f"\n[precommit] 未通过：{'、'.join(failures)}")
        print("[precommit] 修复后再提交；紧急情况可用 git commit --no-verify 跳过")
        return 1

    print("\n[precommit] 全部检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
