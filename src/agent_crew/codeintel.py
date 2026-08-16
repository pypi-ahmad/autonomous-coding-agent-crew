from __future__ import annotations

import ast
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from functools import lru_cache
from pathlib import Path

from agent_crew.stack import detect_stack, format_stack
from agent_crew.workspace import list_files, read_file, snapshot, write_file

MANIFESTS = {
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "go.mod",
    "pom.xml",
}
JS_FN = re.compile(r"(?:function\s+|const\s+|exports\.|module\.exports\.)([A-Za-z_][A-Za-z0-9_]*)")
TEXT_SUFFIX = (
    ".py",
    ".md",
    ".toml",
    ".txt",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".json",
    ".prisma",
)
CODE_SUFFIX = (".py", ".js", ".jsx", ".ts", ".tsx")

TRACE_FILE = re.compile(r'File "([^"]+)", line (\d+)')
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]+")
SEARCH_CAP = 50
SERIAL_ANALYZE = 2


def _file_stamp(workspace: Path) -> tuple[tuple[str, int], ...]:
    root = workspace.resolve()
    return tuple((rel, (root / rel).stat().st_mtime_ns) for rel in list_files(workspace))


def _summarize_js(workspace: Path, rel: str) -> str:
    try:
        text = read_file(workspace, rel)
    except (OSError, ValueError):
        return f"## {rel}\n(unreadable)"
    funcs = sorted(set(JS_FN.findall(text)))
    return f"## {rel}\nfunctions: {', '.join(funcs) or '—'}"


def _summarize_file(workspace: Path, rel: str) -> str:
    base = Path(rel).name
    if base in MANIFESTS or rel.endswith(".prisma"):
        return f"## {rel}\n{read_file(workspace, rel)[:2000]}"
    if rel.endswith((".js", ".jsx", ".ts", ".tsx")):
        return _summarize_js(workspace, rel)
    if not rel.endswith(".py"):
        return ""
    try:
        tree = ast.parse(read_file(workspace, rel))
    except (SyntaxError, OSError):
        return f"## {rel}\n(unreadable)"
    imports: list[str] = []
    funcs: list[str] = []
    classes: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
        elif isinstance(node, ast.FunctionDef):
            funcs.append(node.name)
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
    return (
        f"## {rel}\nimports: {', '.join(sorted(set(imports))) or '—'}\n"
        f"classes: {', '.join(classes) or '—'}\n"
        f"functions: {', '.join(funcs) or '—'}"
    )


@lru_cache(maxsize=32)
def _analyze_cached(root: str, stamp: tuple[tuple[str, int], ...]) -> str:
    workspace = Path(root)
    rels = [
        rel
        for rel, _ns in stamp
        if (rel.endswith(CODE_SUFFIX) or Path(rel).name in MANIFESTS or rel.endswith(".prisma"))
    ]
    if len(rels) <= SERIAL_ANALYZE:
        chunks = [_summarize_file(workspace, rel) for rel in rels]
    else:
        with ThreadPoolExecutor(max_workers=min(8, len(rels))) as pool:
            chunks = list(pool.map(lambda rel: _summarize_file(workspace, rel), rels))
    chunks = [chunk for chunk in chunks if chunk]
    return "\n\n".join(chunks) if chunks else "(empty project)"


def analyze_project(workspace: Path) -> str:
    root = workspace.resolve()
    body = _analyze_cached(str(root), _file_stamp(root))
    header = format_stack(detect_stack(workspace))
    return f"{header}\n\n{body}"


def search_code(workspace: Path, pattern: str) -> str:
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"Bad pattern: {exc}") from exc
    hits: list[str] = []
    for rel in list_files(workspace):
        if not rel.endswith(TEXT_SUFFIX):
            continue
        try:
            text = read_file(workspace, rel)
        except OSError:
            continue
        for index, line in enumerate(text.splitlines(), start=1):
            if rx.search(line):
                hits.append(f"{rel}:{index}:{line.strip()}")
                if len(hits) >= SEARCH_CAP:
                    return "\n".join(hits)
    return "\n".join(hits) if hits else "(no matches)"


def _tokens(text: str) -> list[str]:
    parts: list[str] = []
    for token in TOKEN.findall(text):
        lower = token.lower()
        parts.append(lower)
        parts.extend(piece for piece in lower.split("_") if piece)
    return parts


def search_semantic(workspace: Path, query: str) -> str:
    needles = set(_tokens(query))
    if not needles:
        return "(empty query)"
    scored: list[tuple[int, str]] = []
    for rel in list_files(workspace):
        if not rel.endswith(CODE_SUFFIX):
            continue
        try:
            text = read_file(workspace, rel)
        except OSError:
            continue
        bag = Counter(_tokens(text))
        score = sum(bag[token] for token in needles)
        if score:
            scored.append((score, rel))
    scored.sort(reverse=True)
    if not scored:
        return "(no semantic hits)"
    return "\n".join(f"{score} {rel}" for score, rel in scored[:8])


def rename_symbol(workspace: Path, old: str, new: str) -> str:
    if not IDENT.match(old) or not IDENT.match(new):
        raise ValueError("rename_symbol needs Python identifiers")
    rx = re.compile(rf"\b{re.escape(old)}\b")
    changed: list[str] = []
    for rel in list_files(workspace):
        if not rel.endswith(CODE_SUFFIX):
            continue
        text = read_file(workspace, rel)
        updated = rx.sub(new, text)
        if updated != text:
            write_file(workspace, rel, updated)
            changed.append(rel)
    return ", ".join(changed) if changed else "(no replacements)"


def parse_traceback(output: str) -> list[tuple[str, int]]:
    return [
        (match.group(1).replace("\\", "/"), int(match.group(2)))
        for match in TRACE_FILE.finditer(output)
    ]


def blamed_files(workspace: Path, output: str) -> list[str]:
    root = workspace.resolve()
    names: list[str] = []
    known = list_files(workspace)
    for raw, _line in parse_traceback(output):
        path = Path(raw)
        rel = ""
        if path.is_absolute():
            with suppress(ValueError):
                rel = path.resolve().relative_to(root).as_posix()
        if not rel:
            rel = next((found for found in known if found.endswith(path.name)), "")
        if rel and rel not in names:
            names.append(rel)
    return names


def blamed_snapshot(workspace: Path, output: str) -> str:
    names = blamed_files(workspace, output)
    if not names:
        return snapshot(workspace)
    return snapshot(workspace, only=names)
