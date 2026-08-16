from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_crew.workspace import list_files, read_file

SCAN_CAP = 24

MANIFESTS = {
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "go.mod",
    "pom.xml",
    "manage.py",
}

PRACTICES: dict[str, str] = {
    "fastapi": (
        "FastAPI: Pydantic models, Depends() for deps, /health, no logic in route bodies, "
        "type every handler."
    ),
    "flask": ("Flask: app factory, blueprints, no global mutable state, return JSON from views."),
    "django": ("Django: keep apps/urls/models. Do not invent a new layout. ORM for data access."),
    "streamlit": (
        "Streamlit: session_state, forms for submit, no custom CSS, do not launch Streamlit."
    ),
    "library": "Library: tiny public API, stdlib first, pytest on the contract.",
    "cli": "CLI: argparse, non-zero exit on error, no extra parser library.",
    "react": "React: function components, lift state, no extra UI kit.",
    "nextjs": "Next.js: app router, server components by default, fetch on the server.",
    "express": "Express: split routers, JSON only, no shelling out.",
    "go": "Go detected. Keep Go. Smallest diff. Do not rewrite in Python.",
    "java": "Java detected. Keep Java. Smallest diff. Do not rewrite in Python.",
}

DB_PRACTICES: dict[str, str] = {
    "sqlite": "SQLite: stdlib sqlite3, parameterized SQL, one db module.",
    "sqlalchemy": "SQLAlchemy: 2.0 Session style, sqlite URL locally, no string-built SQL.",
    "postgres": "PostgreSQL: DATABASE_URL, parameterized SQL, sqlite fallback in tests.",
    "prisma": "Prisma: schema.prisma is source of truth. Do not hand-edit generated client.",
}


@dataclass(frozen=True)
class Stack:
    language: str = "unknown"
    framework: str = "unknown"
    database: str = "none"
    fullstack: bool = False
    evidence: tuple[str, ...] = ()

    def label(self) -> str:
        parts = [self.language, self.framework]
        if self.database != "none":
            parts.append(self.database)
        if self.fullstack:
            parts.append("fullstack")
        return " / ".join(p for p in parts if p and p != "unknown")


def format_stack(stack: Stack) -> str:
    ev = ", ".join(stack.evidence) or "—"
    return (
        f"language={stack.language} framework={stack.framework} "
        f"database={stack.database} fullstack={stack.fullstack} evidence={ev}"
    )


def practices_for(stack: Stack) -> str:
    lines: list[str] = []
    if stack.framework in PRACTICES:
        lines.append(PRACTICES[stack.framework])
    if stack.language in PRACTICES:
        lines.append(PRACTICES[stack.language])
    if stack.database in DB_PRACTICES:
        lines.append(DB_PRACTICES[stack.database])
    if stack.fullstack:
        lines.append("Full-stack: keep backend and frontend separate. Share types via JSON.")
    if stack.language in {"javascript", "mixed"}:
        lines.append("JS tests: node --test with *.test.js (CommonJS). No extra test runner.")
    if stack.language in {"python", "mixed"}:
        lines.append("Python tests: pytest, test_*.py only.")
    return "\n".join(f"- {line}" for line in lines)


def _read(workspace: Path, relative: str, limit: int = 2000) -> str:
    try:
        return read_file(workspace, relative)[:limit]
    except (OSError, ValueError):
        return ""


def detect_stack(workspace: Path) -> Stack:
    names = list_files(workspace)
    name_set = set(names)
    blobs: list[str] = []
    evidence: list[str] = []
    for rel in names:
        base = Path(rel).name
        if base in MANIFESTS or rel.endswith(".prisma"):
            blobs.append(_read(workspace, rel, 4000))
            evidence.append(rel)
        elif rel.endswith((".py", ".js", ".jsx", ".ts", ".tsx")) and len(blobs) < SCAN_CAP:
            blobs.append(_read(workspace, rel, 1200))
    text = "\n".join(blobs).lower()
    joined = "\n".join(names).lower()

    py = any(n.endswith(".py") for n in names) or bool(
        name_set & {"pyproject.toml", "requirements.txt"}
    )
    js = any(n.endswith((".js", ".jsx", ".ts", ".tsx")) for n in names) or "package.json" in joined
    if py and js:
        language = "mixed"
    elif py:
        language = "python"
    elif js:
        language = "javascript"
    elif "go.mod" in name_set:
        language = "go"
        evidence.append("go.mod")
    elif "pom.xml" in name_set or any(n.endswith(".java") for n in names):
        language = "java"
        evidence.append("pom.xml" if "pom.xml" in name_set else "java")
    else:
        language = "unknown"

    framework = _framework(text, joined, name_set)
    frontend = js or "package.json" in joined
    backend = framework in {"fastapi", "flask", "django", "express"} or any(
        token in text for token in ("fastapi", "flask", "django", "express")
    )
    database = _database(text, names)
    return Stack(
        language=language,
        framework=framework,
        database=database,
        fullstack=frontend and backend,
        evidence=tuple(evidence[:8]),
    )


def _framework(text: str, joined: str, name_set: set[str]) -> str:
    checks = (
        ("nextjs", "next.config" in joined or '"next"' in text),
        (
            "react",
            "react" in text and (".jsx" in joined or ".tsx" in joined or "react-dom" in text),
        ),
        ("express", "express" in text),
        ("fastapi", "fastapi" in text),
        ("django", "django" in text or "manage.py" in name_set),
        ("streamlit", "streamlit" in text),
        ("flask", "flask" in text),
    )
    return next((name for name, hit in checks if hit), "unknown")


def _database(text: str, names: list[str]) -> str:
    if "prisma" in text or any(n.endswith(".prisma") for n in names):
        return "prisma"
    if "sqlalchemy" in text:
        return "sqlalchemy"
    if "psycopg" in text or "postgresql" in text:
        return "postgres"
    if "sqlite3" in text or any(n.endswith((".sqlite", ".db")) for n in names):
        return "sqlite"
    return "none"


_HINT_LANG = {
    "library": "python",
    "cli": "python",
    "fastapi": "python",
    "flask": "python",
    "django": "python",
    "streamlit": "python",
    "datascience": "python",
    "express": "javascript",
    "react": "javascript",
    "nextjs": "javascript",
    "fullstack": "mixed",
}

_HINT_FRAMEWORK = {
    "datascience": "library",
    "library": "library",
    "cli": "cli",
}


def apply_hint(stack: Stack, template: str, database: str) -> Stack:
    name = (template or "blank").strip()
    if name in {"blank", "auto", ""}:
        lang, framework, full = stack.language, stack.framework, stack.fullstack
    else:
        lang = _HINT_LANG.get(name, stack.language)
        framework = _HINT_FRAMEWORK.get(name, name)
        full = name == "fullstack" or stack.fullstack
    db = database if database and database != "none" else stack.database
    return Stack(
        language=lang or stack.language,
        framework=framework or stack.framework,
        database=db,
        fullstack=full,
        evidence=stack.evidence,
    )
