from __future__ import annotations

from pathlib import Path

from agent_crew.workspace import _write_raw

TEMPLATES: dict[str, dict[str, str]] = {
    "blank": {},
    "library": {
        "src/pkg/__init__.py": '"""Package."""\n\nfrom pkg.core import add\n\n__all__ = ["add"]\n',
        "src/pkg/core.py": "def add(left: int, right: int) -> int:\n    return left + right\n",
        "tests/test_core.py": (
            "from pkg.core import add\n\n\ndef test_add() -> None:\n    assert add(2, 3) == 5\n"
        ),
        "README.md": "# Library\n\nPython package stub.\n",
    },
    "cli": {
        "src/app/__init__.py": "",
        "src/app/__main__.py": (
            "from __future__ import annotations\n\nimport argparse\n\n"
            "def main() -> None:\n"
            "    parser = argparse.ArgumentParser()\n"
            '    parser.add_argument("name", nargs="?", default="world")\n'
            "    args = parser.parse_args()\n"
            '    print(f"hello {args.name}")\n\n'
            'if __name__ == "__main__":\n    main()\n'
        ),
        "tests/test_main.py": (
            "from app.__main__ import main\n\n\ndef test_main() -> None:\n    main()\n"
        ),
        "README.md": "# CLI\n\n`python -m app`\n",
    },
    "fastapi": {
        "src/api/__init__.py": "",
        "src/api/main.py": (
            "from fastapi import FastAPI\n\napp = FastAPI()\n\n"
            '@app.get("/health")\ndef health() -> dict[str, str]:\n    return {"status": "ok"}\n'
        ),
        "tests/test_health.py": (
            "from api.main import health\n\n\ndef test_health() -> None:\n"
            '    assert health()["status"] == "ok"\n'
        ),
        "README.md": "# FastAPI\n\nHealth stub. Install fastapi to serve.\n",
    },
    "streamlit": {
        "app.py": ('import streamlit as st\n\nst.title("Demo")\nst.write("Replace this stub.")\n'),
        "tests/test_app.py": "def test_placeholder() -> None:\n    assert True\n",
        "README.md": "# Streamlit app\n\n`streamlit run app.py`\n",
    },
    "datascience": {
        "src/analysis.py": (
            "from __future__ import annotations\n\n"
            "def mean(values: list[float]) -> float:\n"
            "    return sum(values) / len(values)\n"
        ),
        "tests/test_analysis.py": (
            "from analysis import mean\n\ndef test_mean() -> None:\n    assert mean([2, 4]) == 3\n"
        ),
        "README.md": "# Data science stub\n\nPure-Python analysis helpers.\n",
    },
    "flask": {
        "src/app.py": (
            "from __future__ import annotations\n\n"
            "def create_app():\n"
            "    routes = {'/health': health}\n"
            "    return routes\n\n"
            "def health() -> dict[str, str]:\n"
            '    return {"status": "ok"}\n'
        ),
        "tests/test_health.py": (
            "from app import health\n\n\ndef test_health() -> None:\n"
            '    assert health()["status"] == "ok"\n'
        ),
        "README.md": "# Flask-shaped stub\n\nSwap create_app for flask.Flask when serving.\n",
    },
    "django": {
        "app/views.py": ('def health() -> dict[str, str]:\n    return {"status": "ok"}\n'),
        "app/models.py": (
            "class Item:\n    def __init__(self, name: str) -> None:\n        self.name = name\n"
        ),
        "app/urls.py": 'urlpatterns = [("/health", "views.health")]\n',
        "tests/test_views.py": (
            "from app.views import health\n\n\ndef test_health() -> None:\n"
            '    assert health()["status"] == "ok"\n'
        ),
        "README.md": "# Django-shaped stub\n\nUrls/views/models layout. Install Django to serve.\n",
    },
    "express": {
        "src/health.js": (
            'function health() {\n  return { status: "ok" };\n}\nmodule.exports = { health };\n'
        ),
        "src/health.test.js": (
            'const test = require("node:test");\n'
            'const assert = require("node:assert/strict");\n'
            'const { health } = require("./health");\n'
            'test("health", () => {\n  assert.equal(health().status, "ok");\n});\n'
        ),
        "package.json": '{\n  "name": "express-stub",\n  "private": true\n}\n',
        "README.md": "# Express-shaped stub\n\n`node --test`. Wire express() to serve health().\n",
    },
    "react": {
        "frontend/src/lib.js": (
            "function add(left, right) {\n  return left + right;\n}\nmodule.exports = { add };\n"
        ),
        "frontend/src/lib.test.js": (
            'const test = require("node:test");\n'
            'const assert = require("node:assert/strict");\n'
            'const { add } = require("./lib");\n'
            'test("add", () => {\n  assert.equal(add(2, 3), 5);\n});\n'
        ),
        "frontend/src/App.jsx": (
            "export default function App() {\n  return <main>Replace this stub.</main>;\n}\n"
        ),
        "package.json": '{\n  "name": "react-stub",\n  "private": true\n}\n',
        "README.md": "# React stub\n\nUI in App.jsx. Logic + node:test in lib.js.\n",
    },
    "nextjs": {
        "app/page.js": (
            "export default function Page() {\n  return <main>Replace this stub.</main>;\n}\n"
        ),
        "lib/health.js": (
            'function health() {\n  return { status: "ok" };\n}\nmodule.exports = { health };\n'
        ),
        "lib/health.test.js": (
            'const test = require("node:test");\n'
            'const assert = require("node:assert/strict");\n'
            'const { health } = require("./health");\n'
            'test("health", () => {\n  assert.equal(health().status, "ok");\n});\n'
        ),
        "package.json": (
            '{\n  "name": "next-stub",\n  "private": true,\n'
            '  "dependencies": {"next": "15.0.0"}\n}\n'
        ),
        "README.md": "# Next.js stub\n\nApp router page + lib tests via `node --test`.\n",
    },
    "fullstack": {
        "backend/__init__.py": "",
        "backend/main.py": ('def health() -> dict[str, str]:\n    return {"status": "ok"}\n'),
        "tests/test_health.py": (
            "from backend.main import health\n\n\ndef test_health() -> None:\n"
            '    assert health()["status"] == "ok"\n'
        ),
        "frontend/src/lib.js": (
            'function apiBase() {\n  return "http://127.0.0.1:8000";\n}\n'
            "module.exports = { apiBase };\n"
        ),
        "frontend/src/lib.test.js": (
            'const test = require("node:test");\n'
            'const assert = require("node:assert/strict");\n'
            'const { apiBase } = require("./lib");\n'
            'test("apiBase", () => {\n  assert.ok(apiBase().startsWith("http"));\n});\n'
        ),
        "package.json": '{\n  "name": "fullstack-stub",\n  "private": true\n}\n',
        "README.md": "# Full-stack stub\n\nFastAPI-shaped backend + JS frontend.\n",
    },
}

TEMPLATE_NAMES = tuple(TEMPLATES)

SQLITE_DB = (
    "from __future__ import annotations\n\n"
    "import sqlite3\nfrom pathlib import Path\n\n"
    'DB_PATH = Path(__file__).resolve().parent / "app.db"\n\n'
    "def connect() -> sqlite3.Connection:\n"
    "    conn = sqlite3.connect(DB_PATH)\n"
    "    conn.execute(\n"
    '        "CREATE TABLE IF NOT EXISTS item '
    '(id INTEGER PRIMARY KEY, name TEXT NOT NULL)"\n'
    "    )\n    conn.commit()\n    return conn\n\n"
    "def add_item(name: str) -> int:\n"
    "    with connect() as conn:\n"
    '        cur = conn.execute("INSERT INTO item(name) VALUES (?)", (name,))\n'
    "        conn.commit()\n        return int(cur.lastrowid or 0)\n"
)

DATABASES: dict[str, dict[str, str]] = {
    "none": {},
    "sqlite": {
        "db.py": SQLITE_DB,
        "tests/test_db.py": (
            "from db import add_item\n\n\ndef test_add_item() -> None:\n"
            '    assert add_item("n") > 0\n'
        ),
    },
    "sqlalchemy": {
        "db.py": (
            "# SQLAlchemy 2.0 shape. Local runs use sqlite3 so tests stay dep-free.\n" + SQLITE_DB
        ),
        "tests/test_db.py": (
            "from db import add_item\n\n\ndef test_add_item() -> None:\n"
            '    assert add_item("n") > 0\n'
        ),
    },
    "postgres": {
        "db.py": (
            "import os\n\n"
            'DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///app.db")\n'
            "# Tests use sqlite3. Point DATABASE_URL at Postgres in prod.\n" + SQLITE_DB
        ),
        "tests/test_db.py": (
            "from db import add_item\n\n\ndef test_add_item() -> None:\n"
            '    assert add_item("n") > 0\n'
        ),
    },
    "prisma": {
        "prisma/schema.prisma": (
            'datasource db {\n  provider = "sqlite"\n  url = "file:./dev.db"\n}\n'
            'generator client {\n  provider = "prisma-client-js"\n}\n'
            "model Item {\n  id   Int    @id @default(autoincrement())\n"
            "  name String\n}\n"
        ),
        "src/db.js": (
            "const items = [];\n"
            "function addItem(name) {\n  const row = { id: items.length + 1, name };\n"
            "  items.push(row);\n  return row;\n}\n"
            "module.exports = { addItem };\n"
        ),
        "src/db.test.js": (
            'const test = require("node:test");\n'
            'const assert = require("node:assert/strict");\n'
            'const { addItem } = require("./db");\n'
            'test("addItem", () => {\n  assert.equal(addItem("n").name, "n");\n});\n'
        ),
    },
}

DATABASE_NAMES = tuple(DATABASES)


def _write_map(workspace: Path, files: dict[str, str]) -> list[str]:
    written: list[str] = []
    for relative, body in files.items():
        dest = workspace / relative
        if dest.exists():
            continue
        written.append(_write_raw(workspace, relative, body))
    return written


def apply_template(workspace: Path, name: str) -> list[str]:
    return _write_map(workspace, TEMPLATES.get(name, {}))


def apply_database(workspace: Path, name: str) -> list[str]:
    return _write_map(workspace, DATABASES.get(name, {}))
