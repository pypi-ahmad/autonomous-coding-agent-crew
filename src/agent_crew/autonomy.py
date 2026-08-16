from __future__ import annotations

import ast
import re
from pathlib import Path

from agent_crew.policy import get_policy
from agent_crew.settings import MIN_COVERAGE
from agent_crew.shell import run_terminal
from agent_crew.workspace import _write_raw, is_test_path, list_files, read_file

STDLIB = {
    "abc",
    "ast",
    "asyncio",
    "collections",
    "contextlib",
    "copy",
    "csv",
    "dataclasses",
    "datetime",
    "enum",
    "functools",
    "hashlib",
    "http",
    "io",
    "itertools",
    "json",
    "logging",
    "math",
    "os",
    "pathlib",
    "re",
    "shutil",
    "sqlite3",
    "string",
    "subprocess",
    "sys",
    "tempfile",
    "threading",
    "time",
    "typing",
    "unittest",
    "uuid",
    "warnings",
    "zipfile",
}

IMPORT_TO_PIP = {
    "fastapi": "fastapi",
    "flask": "flask",
    "django": "django",
    "sqlalchemy": "sqlalchemy",
    "pydantic": "pydantic",
    "httpx": "httpx",
    "requests": "requests",
    "numpy": "numpy",
    "pandas": "pandas",
    "streamlit": "streamlit",
    "dotenv": "python-dotenv",
    "yaml": "pyyaml",
    "PIL": "pillow",
    "sklearn": "scikit-learn",
    "jose": "python-jose",
    "passlib": "passlib",
    "uvicorn": "uvicorn",
}

SUBTASK = re.compile(r"^\s*(?:\d+[.)]|[-*])\s+(.+)$")


def parse_subtasks(plan: str) -> list[str]:
    lines = plan.splitlines()
    in_block = False
    found: list[str] = []
    for line in lines:
        heading = line.strip().lower()
        if heading.startswith("##"):
            in_block = "sub-task" in heading or "subtask" in heading
            continue
        if not in_block:
            continue
        match = SUBTASK.match(line)
        if match:
            found.append(match.group(1).strip())
    return found


def remaining_subtasks(plan: str, done: list[str]) -> list[str]:
    skip = {item.lower() for item in done}
    return [item for item in parse_subtasks(plan) if item.lower() not in skip]


def discover_imports(workspace: Path) -> list[str]:
    names: set[str] = set()
    for rel in list_files(workspace):
        if not rel.endswith(".py") or is_test_path(rel):
            continue
        try:
            tree = ast.parse(read_file(workspace, rel))
        except (OSError, SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".", 1)[0])
    return sorted(names)


def needed_packages(imports: list[str]) -> list[str]:
    pkgs: list[str] = []
    for name in imports:
        if name in STDLIB or name.startswith("_"):
            continue
        pkg = IMPORT_TO_PIP.get(name)
        if pkg and pkg not in pkgs:
            pkgs.append(pkg)
    return pkgs


def install_deps(workspace: Path) -> tuple[list[str], str]:
    policy = get_policy()
    pkgs = needed_packages(discover_imports(workspace))
    if not pkgs:
        return [], "no third-party imports"
    if not policy.allow_pip or not policy.allow_terminal:
        return pkgs, "pip disabled by policy"
    if policy.dry_run:
        return pkgs, "dry-run: " + ", ".join(pkgs)
    notes: list[str] = []
    for pkg in pkgs:
        ok, out = run_terminal(workspace, f"pip install {pkg}")
        notes.append(f"{pkg}: {'ok' if ok else out[:200]}")
    req = workspace / "requirements.txt"
    prior = req.read_text(encoding="utf-8").splitlines() if req.is_file() else []
    merged = list(dict.fromkeys([*prior, *pkgs]))
    _write_raw(workspace, "requirements.txt", "\n".join(merged) + "\n")
    return pkgs, "; ".join(notes)


def render_health(state: dict, files: list[str] | None = None) -> str:
    cover = state.get("coverage", -1)
    cover_txt = f"{cover:.0f}%" if isinstance(cover, int | float) and cover >= 0 else "n/a"
    names = files if files is not None else []
    lines = [
        "# Project health report",
        "",
        f"- Goal: {state.get('task', '')}",
        f"- Autonomous: {state.get('autonomous', False)}",
        f"- Cycles: {state.get('goal_cycles', 0)}",
        f"- Stack: {state.get('stack', '')}",
        f"- Tests: {'passed' if state.get('tests_passed') else 'failed'}",
        f"- Coverage: {cover_txt} (min {MIN_COVERAGE:.0f}%)",
        f"- Gates: {'pass' if state.get('gates_ok') else state.get('gate_fail') or 'fail'}",
        f"- Score: {state.get('score', 'n/a')}",
        f"- Deps: {state.get('deps') or 'none'}",
        f"- Rollback: {state.get('rollback') or 'none'}",
        f"- Roster: {state.get('roster', '')}",
        f"- Subtasks: {state.get('subtasks') or '—'}",
        "",
        "## Files",
    ]
    lines.extend(f"- `{name}`" for name in names[:40])
    if not names:
        lines.append("- (none)")
    quality = (state.get("quality") or "").strip()
    if quality:
        lines.extend(["", quality])
    return "\n".join(lines) + "\n"


def write_health(workspace: Path, state: dict) -> str:
    names = list_files(workspace)
    return _write_raw(
        workspace,
        "HEALTH.md",
        render_health({**state, "workspace": str(workspace)}, files=names),
    )
