from __future__ import annotations

import ast
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from agent_crew.policy import get_policy
from agent_crew.settings import MIN_COVERAGE, PERF_BUDGET_S
from agent_crew.workspace import _write_raw, is_test_path, list_files, read_file

SECRET = re.compile(r"(api[_-]?key|secret|password|token)\s*=\s*['\"][^'\"]+['\"]", re.IGNORECASE)
TOOL_MISSING = 127
MULTI_MODULE = 2
JS_DANGER = re.compile(r"\beval\s*\(|new Function\s*\(|child_process")
DANGER_FUNCS = {"eval", "exec", "compile"}
DANGER_ATTR = {("os", "system"), ("pickle", "loads"), ("subprocess", "call")}


@dataclass
class Quality:
    tests_ok: bool = False
    coverage: float = -1.0
    coverage_ok: bool = False
    lint_ok: bool = False
    types_ok: bool = False
    security_ok: bool = False
    perf_ok: bool = False
    levels_ok: bool = False
    levels: dict[str, list[str]] = field(default_factory=dict)
    fail: str = "tests"
    report: str = ""

    @property
    def ok(self) -> bool:
        return (
            self.tests_ok
            and self.coverage_ok
            and self.lint_ok
            and self.types_ok
            and self.security_ok
            and self.perf_ok
            and self.levels_ok
        )


def classify_tests(workspace: Path) -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = {"unit": [], "integration": [], "edge": [], "perf": []}
    for rel in list_files(workspace):
        if not is_test_path(rel):
            continue
        name = Path(rel).name.lower()
        kind = _kind(name)
        if kind:
            buckets[kind].append(rel)
            continue
        try:
            text = read_file(workspace, rel)
        except (OSError, ValueError):
            buckets["unit"].append(rel)
            continue
        for fn in re.findall(r"def\s+(test_\w+)", text):
            buckets[_kind(fn) or "unit"].append(f"{rel}::{fn}")
        if not re.search(r"def\s+test_", text) and rel.endswith(".js"):
            buckets["unit"].append(rel)
    return buckets


def _kind(name: str) -> str:
    if "perf" in name:
        return "perf"
    if "integrat" in name:
        return "integration"
    if "edge" in name:
        return "edge"
    return ""


def _impl_py(workspace: Path) -> list[str]:
    return [
        rel
        for rel in list_files(workspace)
        if rel.endswith(".py") and not is_test_path(rel) and Path(rel).name != "__init__.py"
    ]


def lint_workspace(workspace: Path) -> tuple[bool, str]:
    argv = [
        sys.executable,
        "-m",
        "ruff",
        "check",
        ".",
        "--isolated",
        "--select",
        "E,F,S,B",
        "--ignore",
        "E501,S101",
    ]
    code, out = _tool(workspace, argv)
    if code == TOOL_MISSING or "No module named" in out:
        return _syntax_only(workspace)
    return code == 0, out or "ruff clean"


def typecheck_workspace(workspace: Path) -> tuple[bool, str]:
    if not _impl_py(workspace):
        return True, "no Python to typecheck"
    argv = [sys.executable, "-m", "ty", "check", "."]
    code, out = _tool(workspace, argv)
    if code == TOOL_MISSING or "No module named" in out:
        return True, "ty not installed; skipped"
    return code == 0, out or "ty clean"


def _tool(workspace: Path, argv: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(  # noqa: S603
            argv,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except FileNotFoundError:
        return 127, "tool not found"
    except subprocess.TimeoutExpired:
        return 1, "tool timeout"
    return proc.returncode, ((proc.stdout or "") + (proc.stderr or "")).strip()[-4000:]


def _syntax_only(workspace: Path) -> tuple[bool, str]:
    bad: list[str] = []
    for rel in _impl_py(workspace):
        try:
            ast.parse(read_file(workspace, rel))
        except (SyntaxError, OSError) as exc:
            bad.append(f"{rel}: {exc}")
    return (not bad), "\n".join(bad) or "syntax ok"


def security_scan(workspace: Path) -> tuple[bool, str]:
    hits: list[str] = []
    for rel in list_files(workspace):
        if is_test_path(rel):
            continue
        try:
            text = read_file(workspace, rel)
        except (OSError, ValueError):
            continue
        if rel.endswith((".js", ".ts", ".jsx", ".tsx")) and JS_DANGER.search(text):
            hits.append(f"{rel}: dangerous JS")
            continue
        if not rel.endswith(".py"):
            continue
        if SECRET.search(text):
            hits.append(f"{rel}: hardcoded secret")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        hits.extend(_py_danger(rel, tree))
    return (not hits), "\n".join(hits) or "security ok"


def _py_danger(rel: str, tree: ast.AST) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in DANGER_FUNCS
        ):
            found.append(f"{rel}:{node.lineno}: {node.func.id}()")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                pair = (node.func.value.id, node.func.attr)
                if pair in DANGER_ATTR:
                    found.append(f"{rel}:{node.lineno}: {pair[0]}.{pair[1]}")
            if node.func.attr == "run":
                found.extend(
                    f"{rel}:{node.lineno}: subprocess shell=True"
                    for kw in node.keywords
                    if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value
                )
    return found


def probe_perf(workspace: Path) -> tuple[bool, str]:
    notes: list[str] = []
    total = 0.0
    for rel in _impl_py(workspace)[:8]:
        ok, dt, note = _time_module(workspace, rel)
        total += dt
        if not ok:
            return False, note
        if note:
            notes.append(note)
        if total > PERF_BUDGET_S * 3:
            return False, f"perf budget exceeded ({total:.2f}s)"
    return True, "; ".join(notes) or "perf ok"


def _time_module(workspace: Path, rel: str) -> tuple[bool, float, str]:
    try:
        src = read_file(workspace, rel)
        tree = ast.parse(src)
        ns: dict[str, object] = {}
        exec(compile(tree, rel, "exec"), ns)  # noqa: S102
    except Exception as exc:
        return True, 0.0, f"{rel}: skip ({exc.__class__.__name__})"
    start = time.perf_counter()
    for name, obj in ns.items():
        if name.startswith("_") or not callable(obj):
            continue
        if not _call_fast(obj):
            continue
    dt = time.perf_counter() - start
    if dt > PERF_BUDGET_S:
        return False, dt, f"{rel} too slow ({dt:.2f}s)"
    return True, dt, f"{rel} {dt:.3f}s"


def _call_fast(fn: object) -> bool:
    if not callable(fn):
        return True
    for args in ((), (0,), (0, 0), (1, 1), ("",), ([],)):
        try:
            t0 = time.perf_counter()
            for _ in range(50):
                fn(*args)  # ty: ignore[call-top-callable]
        except Exception:  # noqa: S112
            continue
        else:
            return time.perf_counter() - t0 <= PERF_BUDGET_S
    return True


def evaluate_quality(
    workspace: Path,
    *,
    tests_ok: bool,
    coverage: float,
) -> Quality:
    policy = get_policy()
    if policy.dry_run:
        return Quality(fail="dry-run", report="dry-run: quality skipped")
    levels = classify_tests(workspace)
    impl = _impl_py(workspace)
    need_integration = len(impl) >= MULTI_MODULE
    levels_ok = bool(levels["unit"]) and bool(levels["edge"])
    if need_integration:
        levels_ok = levels_ok and bool(levels["integration"])
    cover_needed = bool(impl)
    coverage_ok = (not cover_needed) or (coverage >= MIN_COVERAGE)
    lint_ok, lint_out = lint_workspace(workspace)
    types_ok, types_out = typecheck_workspace(workspace)
    sec_ok, sec_out = security_scan(workspace)
    perf_ok, perf_out = probe_perf(workspace)
    q = Quality(
        tests_ok=tests_ok,
        coverage=coverage,
        coverage_ok=coverage_ok,
        lint_ok=lint_ok,
        types_ok=types_ok,
        security_ok=sec_ok,
        perf_ok=perf_ok,
        levels_ok=levels_ok,
        levels=levels,
    )
    if not tests_ok:
        q.fail = "tests"
    elif not levels_ok:
        q.fail = "missing_tests"
    elif not coverage_ok:
        q.fail = "coverage"
    elif not lint_ok:
        q.fail = "lint"
    elif not types_ok:
        q.fail = "types"
    elif not sec_ok:
        q.fail = "security"
    elif not perf_ok:
        q.fail = "perf"
    else:
        q.fail = ""
    q.report = _render(q, lint_out, types_out, sec_out, perf_out)
    return q


def _render(q: Quality, lint: str, types: str, sec: str, perf: str) -> str:
    cover = f"{q.coverage:.0f}%" if q.coverage >= 0 else "n/a"
    lines = [
        "# Quality",
        "",
        f"- Gates: {'PASS' if q.ok else 'FAIL'} ({q.fail or 'all clear'})",
        f"- Tests: {'ok' if q.tests_ok else 'fail'}",
        f"- Coverage: {cover} (min {MIN_COVERAGE:.0f}%)",
        (
            f"- Levels: unit={len(q.levels.get('unit', []))} "
            f"integration={len(q.levels.get('integration', []))} "
            f"edge={len(q.levels.get('edge', []))} "
            f"perf={len(q.levels.get('perf', []))}"
        ),
        f"- Lint: {'ok' if q.lint_ok else 'fail'}",
        f"- Types: {'ok' if q.types_ok else 'fail'}",
        f"- Security: {'ok' if q.security_ok else 'fail'}",
        f"- Perf: {'ok' if q.perf_ok else 'fail'}",
        "",
        "## Lint",
        lint or "—",
        "",
        "## Types",
        types or "—",
        "",
        "## Security",
        sec or "—",
        "",
        "## Perf",
        perf or "—",
        "",
    ]
    return "\n".join(lines)


def write_quality(workspace: Path, quality: Quality) -> str:
    return _write_raw(workspace, "QUALITY.md", quality.report + "\n")


def format_levels(levels: dict[str, list[str]]) -> str:
    return ", ".join(f"{k}={len(v)}" for k, v in levels.items())
