from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from io import BytesIO
from pathlib import Path

from agent_crew.policy import get_policy
from agent_crew.settings import RUNS_DIR

FILE_BLOCK = re.compile(
    r"### FILE:\s*([^\n]+)\n```(?:[a-zA-Z0-9_+-]+)?\n(.*?)```",
    re.DOTALL,
)
SKIP_DIR = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".git",
    ".vendor",
    "node_modules",
}
SKIP_COPY = {".venv", "__pycache__", ".git", ".ruff_cache", ".pytest_cache", "node_modules"}
SANDBOX_TIMEOUT = 15


def is_test_path(relative: str) -> bool:
    name = Path(relative).name
    return name.startswith("test_") or name.endswith(
        ("_test.py", ".test.js", ".spec.js", ".test.ts", ".spec.ts")
    )


def safe_file(workspace: Path, relative: str) -> Path:
    cleaned = relative.strip().replace("\\", "/").lstrip("/")
    dest = (workspace / cleaned).resolve()
    if not dest.is_relative_to(workspace.resolve()):
        raise ValueError(f"Refused path outside workspace: {relative}")
    return dest


def list_files(workspace: Path) -> list[str]:
    root = workspace.resolve()
    names: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIR for part in path.parts):
            continue
        if path.suffix == ".pyc":
            continue
        names.append(path.relative_to(root).as_posix())
    return names


def read_file(workspace: Path, relative: str) -> str:
    return safe_file(workspace, relative).read_text(encoding="utf-8")


def _write_raw(workspace: Path, relative: str, content: str) -> str:
    path = safe_file(workspace, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path.relative_to(workspace.resolve()).as_posix()


def write_file(
    workspace: Path,
    relative: str,
    content: str,
    *,
    protect_tests: bool = False,
) -> str:
    policy = get_policy()
    if not policy.allow_write:
        raise ValueError("Writes disabled by policy")
    if policy.is_locked(relative):
        raise ValueError(f"Locked path: {relative}")
    if protect_tests and is_test_path(relative):
        raise ValueError(f"Refused test path: {relative}")
    path = safe_file(workspace, relative)
    rel = path.relative_to(workspace.resolve()).as_posix()
    if policy.dry_run:
        return rel
    return _write_raw(workspace, relative, content)


def create_file(
    workspace: Path,
    relative: str,
    content: str,
    *,
    protect_tests: bool = False,
) -> str:
    path = safe_file(workspace, relative)
    if path.exists():
        raise FileExistsError(f"Already exists: {relative}")
    return write_file(workspace, relative, content, protect_tests=protect_tests)


def has_tests(workspace: Path) -> bool:
    return any(is_test_path(rel) for rel in list_files(workspace))


def _js_test_files(workspace: Path) -> list[str]:
    return [
        rel
        for rel in list_files(workspace)
        if rel.endswith((".test.js", ".spec.js", ".test.ts", ".spec.ts"))
    ]


def _py_test_files(workspace: Path) -> list[str]:
    return [
        rel
        for rel in list_files(workspace)
        if Path(rel).name.startswith("test_") or Path(rel).name.endswith("_test.py")
    ]


def file_block_paths(text: str) -> list[str]:
    return [relative.strip() for relative, _body in FILE_BLOCK.findall(text)]


def file_blocks(text: str) -> list[tuple[str, str]]:
    return [(relative.strip(), body) for relative, body in FILE_BLOCK.findall(text)]


def apply_files(workspace: Path, text: str, *, protect_tests: bool = False) -> list[str]:
    written: list[str] = []
    policy = get_policy()
    for relative, body in FILE_BLOCK.findall(text):
        rel = relative.strip()
        if protect_tests and is_test_path(rel):
            continue
        if policy.is_locked(rel):
            continue
        written.append(write_file(workspace, rel, body))
    return written


def snapshot(workspace: Path, only: list[str] | None = None, limit: int = 40) -> str:
    names = only if only is not None else list_files(workspace)
    return "\n\n".join(
        f"### FILE: {rel}\n```\n{read_file(workspace, rel)}\n```" for rel in names[:limit]
    )


def _sandbox_env(workspace: Path | None = None) -> dict[str, str]:
    keep = ("PATH", "SYSTEMROOT", "PATHEXT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE")
    env = {key: os.environ[key] for key in keep if key in os.environ}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if workspace is not None:
        vendor = workspace / ".vendor"
        if vendor.is_dir():
            env["PYTHONPATH"] = str(vendor)
    return env


def run_python(workspace: Path, relative: str, timeout: int = SANDBOX_TIMEOUT) -> tuple[bool, str]:
    policy = get_policy()
    if not policy.allow_terminal:
        return False, "Terminal disabled by policy"
    if policy.dry_run:
        return False, f"dry-run: python {relative}"
    path = safe_file(workspace, relative)
    if path.suffix != ".py":
        raise ValueError("Sandbox runs .py files only")
    if not path.is_file():
        raise FileNotFoundError(relative)
    rel = path.relative_to(workspace.resolve()).as_posix()
    # ponytail: cwd jail + stripped env + timeout. No OS container.
    try:
        proc = subprocess.run(  # noqa: S603
            [sys.executable, rel],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=_sandbox_env(workspace),
        )
    except subprocess.TimeoutExpired:
        return False, f"Sandbox timeout after {timeout}s"
    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode == 0, output[-8000:]


def parse_coverage(output: str) -> float | None:
    match = re.search(r"^TOTAL\s+.*?(\d+)%\s*$", output, re.MULTILINE)
    if not match:
        return None
    return float(match.group(1))


def reflection_verdict(text: str) -> str:
    first = text.strip().splitlines()[0].upper() if text.strip() else ""
    if first.startswith("REVISE"):
        return "revise"
    return "ok"


def parse_pytest_counts(output: str) -> dict[str, int]:
    counts = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
    for key in counts:
        match = re.search(rf"(\d+)\s+{key}", output)
        if match:
            counts[key] = int(match.group(1))
    return counts


def file_tree(workspace: Path) -> str:
    names = list_files(workspace)
    if not names:
        return "(empty)"
    return "\n".join("  " * (rel.count("/")) + rel.rsplit("/", 1)[-1] for rel in names)


def render_report(
    state: dict,
    files: list[str] | None = None,
    trace: list[dict] | None = None,
) -> str:
    workspace = Path(state["workspace"]) if state.get("workspace") else None
    names = files if files is not None else (list_files(workspace) if workspace else [])
    events = trace if trace is not None else (read_trace(workspace) if workspace else [])
    cover = state.get("coverage", -1)
    cover_txt = f"{cover:.0f}%" if isinstance(cover, int | float) and cover >= 0 else "n/a"
    lines = [
        "# Project report",
        "",
        f"- Task: {state.get('task', '')}",
        f"- Template: {state.get('template', 'blank')}",
        f"- Stack: {state.get('stack', '')}",
        f"- Tests: {'passed' if state.get('tests_passed') else 'failed'}",
        f"- Gates: {'pass' if state.get('gates_ok') else state.get('gate_fail') or 'fail'}",
        f"- Roster: {state.get('roster', '')}",
        f"- Votes: {state.get('votes', '')}",
        f"- Conflicts: {state.get('conflicts') or 'none'}",
        f"- Coverage: {cover_txt}",
        f"- Score: {state.get('score', 'n/a')}",
        f"- Dry-run: {state.get('dry_run', False)}",
        "",
        "## Files",
    ]
    lines.extend(f"- `{name}`" for name in names)
    if not names:
        lines.append("- (none)")
    lines.extend(["", "## Decisions"])
    if events:
        lines.extend(
            f"- {row.get('agent', '?')}: {row.get('decision', '')} — {row.get('detail', '')}"
            for row in events
        )
    else:
        lines.extend(f"- {line}" for line in state.get("log") or ["(none)"])
    plan = (state.get("plan") or "").strip()
    if plan:
        lines.extend(["", "## Plan", plan])
    evaluation = (state.get("evaluation") or "").strip()
    if evaluation:
        lines.extend(["", "## Evaluation", evaluation])
    return "\n".join(lines) + "\n"


def render_history(state: dict, trace: list[dict] | None = None) -> str:
    workspace = Path(state["workspace"]) if state.get("workspace") else None
    events = trace if trace is not None else (read_trace(workspace) if workspace else [])
    lines = [
        "# Conversation history",
        "",
        f"Task: {state.get('task', '')}",
        "",
        "## Feedback",
        (state.get("feedback") or "(none)").strip(),
        "",
        "## Log",
    ]
    lines.extend(f"- {line}" for line in state.get("log") or ["(none)"])
    if events:
        lines.extend(["", "## Trace"])
        lines.extend(
            f"- {row.get('agent', '?')} · {row.get('decision', '')} · "
            f"{row.get('file') or '—'} — {row.get('detail', '')}"
            for row in events
        )
    plan = (state.get("plan") or "").strip()
    if plan:
        lines.extend(["", "## Plan", plan])
    return "\n".join(lines) + "\n"


def write_report(workspace: Path, state: dict) -> str:
    return _write_raw(workspace, "REPORT.md", render_report({**state, "workspace": str(workspace)}))


def write_history(workspace: Path, state: dict) -> str:
    return _write_raw(
        workspace, "HISTORY.md", render_history({**state, "workspace": str(workspace)})
    )


def run_tests(workspace: Path) -> tuple[bool, str]:
    policy = get_policy()
    if not policy.allow_terminal:
        return False, "Terminal disabled by policy"
    if policy.dry_run:
        return False, "dry-run: tests not executed"
    py_tests = _py_test_files(workspace)
    js_tests = _js_test_files(workspace)
    if not py_tests and not js_tests:
        return False, "No tests written."
    chunks: list[str] = []
    passed = True
    if py_tests:
        ok, out = _run_pytest(workspace)
        passed = passed and ok
        chunks.append(out)
    if js_tests:
        ok, out = _run_node_tests(workspace, js_tests)
        passed = passed and ok
        chunks.append(out)
    return passed, "\n".join(chunks)[-8000:]


def _run_pytest(workspace: Path) -> tuple[bool, str]:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--tb=short",
            "--cov=.",
            "--cov-report=term-missing",
        ],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
        env=_sandbox_env(workspace),
    )
    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode == 0, output[-8000:]


def _run_node_tests(workspace: Path, files: list[str]) -> tuple[bool, str]:
    node = shutil.which("node")
    if not node:
        return False, "node not found; skipped JS tests"
    argv = [node, "--test"]
    for rel in files[:20]:
        safe_file(workspace, rel)
        argv.append(rel)
    try:
        proc = subprocess.run(  # noqa: S603
            argv,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
            env=_sandbox_env(workspace),
        )
    except subprocess.TimeoutExpired:
        return False, "node --test timeout after 90s"
    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode == 0, output[-8000:]


def append_crew_log(workspace: Path, line: str) -> None:
    log_path = workspace / "crew.log"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip() + "\n")


def copy_project(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)

    def _ignore(_directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name in SKIP_COPY}

    shutil.copytree(src, dest, dirs_exist_ok=True, ignore=_ignore)


class _OneFlip(ast.NodeTransformer):
    def __init__(self) -> None:
        self.flipped = False

    def visit_If(self, node: ast.If) -> ast.AST:
        if self.flipped or isinstance(node.test, ast.Constant):
            return self.generic_visit(node)
        node.test = ast.UnaryOp(op=ast.Not(), operand=node.test)
        self.flipped = True
        return node

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        if self.flipped:
            return node
        if isinstance(node.op, ast.Add):
            node.op = ast.Sub()
            self.flipped = True
        elif isinstance(node.op, ast.Sub):
            node.op = ast.Add()
            self.flipped = True
        return node

    def visit_Return(self, node: ast.Return) -> ast.AST:
        if self.flipped or node.value is None:
            return node
        self.flipped = True
        return ast.Return(value=None)


def probe_one_mutation(workspace: Path) -> tuple[str, str]:
    policy = get_policy()
    if policy.dry_run or not policy.allow_write or not policy.allow_terminal:
        if policy.dry_run:
            reason = "dry-run: mutation probe skipped"
        elif not policy.allow_write:
            reason = "Writes disabled"
        else:
            reason = "Terminal disabled"
        return "skipped", reason
    targets = [
        rel
        for rel in list_files(workspace)
        if rel.endswith(".py") and not is_test_path(rel) and not policy.is_locked(rel)
    ]
    if not targets:
        return "skipped", "No implementation file to mutate."
    rel = targets[0]
    path = safe_file(workspace, rel)
    original = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(original)
    except SyntaxError as exc:
        return "skipped", f"Could not parse {rel}: {exc}"
    flipper = _OneFlip()
    new_tree = flipper.visit(tree)
    if not flipper.flipped:
        return "skipped", f"No flippable statement in {rel}."
    ast.fix_missing_locations(new_tree)
    path.write_text(ast.unparse(new_tree) + "\n", encoding="utf-8")
    try:
        passed, output = run_tests(workspace)
    finally:
        path.write_text(original, encoding="utf-8")
    if passed:
        return "survived", f"Mutant survived in {rel}. Tests do not pin behavior.\n{output}"
    return "killed", f"Mutant killed in {rel}."


def write_repro(workspace: Path, test_output: str) -> str:
    body = "# Repro\n\nTests still fail after max debug attempts.\n\n```\n"
    body += (test_output or "(no output)") + "\n```\n"
    return write_file(workspace, "REPRO.md", body)


def save_run(workspace: Path, payload: dict) -> str:
    return _write_raw(workspace, "run.json", json.dumps(payload, indent=2) + "\n")


def load_run(workspace: Path) -> dict:
    return json.loads(read_file(workspace, "run.json"))


def list_runs(root: Path | None = None) -> list[Path]:
    base = root if root is not None else RUNS_DIR
    if not base.is_dir():
        return []
    found = list(base.glob("*/run.json"))
    return sorted(found, key=lambda path: path.stat().st_mtime, reverse=True)[:12]


def zip_workspace(workspace: Path) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for rel in list_files(workspace):
            archive.writestr(rel, read_file(workspace, rel))
    return buf.getvalue()


def append_trace(
    workspace: Path,
    agent: str,
    decision: str,
    detail: str = "",
    file: str = "",
) -> None:
    event = {"agent": agent, "decision": decision, "file": file, "detail": detail}
    with (workspace / "trace.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event) + "\n")


def read_trace(workspace: Path) -> list[dict]:
    path = workspace / "trace.jsonl"
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _git(workspace: Path, *args: str) -> tuple[int, str]:
    git = shutil.which("git")
    if not git:
        return 1, "git not found"
    proc = subprocess.run(  # noqa: S603
        [git, *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=_sandbox_env(),
    )
    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode, output[-8000:]


def git_init(workspace: Path) -> str:
    policy = get_policy()
    if policy.dry_run:
        return "dry-run: git init"
    if not policy.allow_terminal:
        return "Terminal disabled"
    code, out = _git(workspace, "init")
    if code != 0:
        return f"git init failed: {out}"
    _git(workspace, "add", "-A")
    code, out = _git(
        workspace,
        "-c",
        "user.email=crew@local",
        "-c",
        "user.name=agent-crew",
        "commit",
        "-m",
        "chore: import workspace",
    )
    return out or "git init"


def git_commit(workspace: Path, message: str) -> str:
    policy = get_policy()
    if policy.dry_run:
        return f"dry-run: git commit {message}"
    if not policy.allow_terminal:
        return "Terminal disabled"
    _git(workspace, "add", "-A")
    code, out = _git(
        workspace,
        "-c",
        "user.email=crew@local",
        "-c",
        "user.name=agent-crew",
        "commit",
        "-m",
        message,
    )
    if code != 0:
        return out or "nothing to commit"
    return out or message


def git_diff(workspace: Path) -> str:
    _code, out = _git(workspace, "diff", "HEAD")
    return out


def git_log(workspace: Path, limit: int = 12) -> str:
    _code, out = _git(workspace, "log", "--oneline", f"-{limit}")
    return out


def git_savepoint(workspace: Path, message: str = "chore: green") -> str:
    return git_commit(workspace, message)


def git_rollback(workspace: Path, needle: str = "chore: green") -> str:
    policy = get_policy()
    if policy.dry_run:
        return "dry-run: git rollback"
    if not policy.allow_terminal:
        return "Terminal disabled"
    log = git_log(workspace)
    if log == "git not found":
        return log
    sha = ""
    for line in log.splitlines():
        if needle in line:
            sha = line.split()[0]
            break
    if not sha:
        return "no green savepoint"
    code, out = _git(workspace, "reset", "--hard", sha)
    if code != 0:
        return out or "rollback failed"
    return f"rolled back to {sha}"
