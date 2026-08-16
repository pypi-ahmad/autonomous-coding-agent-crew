from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

FILE_BLOCK = re.compile(
    r"### FILE:\s*([^\n]+)\n```(?:[a-zA-Z0-9_+-]+)?\n(.*?)```",
    re.DOTALL,
)


def safe_file(workspace: Path, relative: str) -> Path:
    cleaned = relative.strip().replace("\\", "/").lstrip("/")
    dest = (workspace / cleaned).resolve()
    if not dest.is_relative_to(workspace.resolve()):
        raise ValueError(f"Refused path outside workspace: {relative}")
    return dest


def apply_files(workspace: Path, text: str) -> list[str]:
    written: list[str] = []
    for relative, body in FILE_BLOCK.findall(text):
        path = safe_file(workspace, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        written.append(path.relative_to(workspace).as_posix())
    return written


def snapshot(workspace: Path) -> str:
    chunks: list[str] = []
    for path in sorted(workspace.rglob("*")):
        if path.is_file():
            rel = path.relative_to(workspace).as_posix()
            chunks.append(f"### FILE: {rel}\n```\n{path.read_text(encoding='utf-8')}\n```")
    return "\n\n".join(chunks)


def run_tests(workspace: Path) -> tuple[bool, str]:
    tests = [
        path
        for path in workspace.rglob("*.py")
        if path.name.startswith("test_") or path.name.endswith("_test.py")
    ]
    if not tests:
        return False, "No test_*.py files written."
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=short"],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode == 0, output[-8000:]
