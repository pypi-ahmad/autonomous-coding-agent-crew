from pathlib import Path
from shutil import which

import pytest

from agent_crew.graph import initial_state
from agent_crew.policy import Policy, set_policy
from agent_crew.shell import build_command
from agent_crew.stack import Stack, apply_hint, detect_stack, practices_for
from agent_crew.templates import apply_database, apply_template
from agent_crew.workspace import (
    has_tests,
    is_test_path,
    run_tests,
    write_file,
)


@pytest.fixture(autouse=True)
def _reset_policy():
    set_policy(Policy())
    yield
    set_policy(Policy())


def test_detect_fastapi(tmp_path: Path):
    write_file(
        tmp_path,
        "src/api/main.py",
        "from fastapi import FastAPI\napp = FastAPI()\n",
    )
    stack = detect_stack(tmp_path)
    assert stack.language == "python"
    assert stack.framework == "fastapi"
    assert "Pydantic" in practices_for(stack)


def test_detect_react_and_fullstack(tmp_path: Path):
    write_file(
        tmp_path, "package.json", '{"dependencies": {"react": "19.0.0", "react-dom": "19"}}\n'
    )
    write_file(tmp_path, "frontend/src/App.jsx", "export default function App() { return null }\n")
    write_file(tmp_path, "backend/main.py", "from fastapi import FastAPI\napp = FastAPI()\n")
    stack = detect_stack(tmp_path)
    assert stack.language == "mixed"
    assert stack.framework in {"react", "fastapi"}
    assert stack.fullstack


def test_detect_go_stays_go(tmp_path: Path):
    write_file(tmp_path, "go.mod", "module example.com/app\n")
    stack = detect_stack(tmp_path)
    assert stack.language == "go"
    assert "Keep Go" in practices_for(stack)


def test_apply_hint_template():
    hinted = apply_hint(Stack(), "fullstack", "sqlite")
    assert hinted.language == "mixed"
    assert hinted.framework == "fullstack"
    assert hinted.database == "sqlite"
    assert hinted.fullstack


def test_flask_and_sqlite_scaffold(tmp_path: Path):
    assert "src/app.py" in apply_template(tmp_path, "flask")
    db_root = tmp_path / "dbonly"
    db_root.mkdir()
    assert "db.py" in apply_database(db_root, "sqlite")
    passed, output = run_tests(db_root)
    assert passed, output


def test_js_test_paths_and_has_tests(tmp_path: Path):
    write_file(tmp_path, "src/health.test.js", "test('x', () => {})\n")
    assert is_test_path("src/health.test.js")
    assert has_tests(tmp_path)


def test_node_allowlist(tmp_path: Path):
    write_file(tmp_path, "ok.js", "console.log(1)\n")
    argv = build_command(tmp_path, "node ok.js")
    assert argv[-1] == "ok.js"
    argv = build_command(tmp_path, "node --test ok.js")
    assert "--test" in argv
    with pytest.raises(ValueError, match="allowlisted"):
        build_command(tmp_path, "npm install evil")


@pytest.mark.skipif(which("node") is None, reason="node not on PATH")
def test_node_test_runner(tmp_path: Path):
    apply_template(tmp_path, "express")
    passed, output = run_tests(tmp_path)
    assert passed, output


def test_initial_state_fullstack(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("agent_crew.graph.RUNS_DIR", tmp_path)
    state = initial_state(
        "demo",
        "ollama",
        "unused",
        template="fullstack",
        database="sqlite",
        policy=Policy(),
    )
    root = Path(state["workspace"])
    assert (root / "backend/main.py").is_file()
    assert (root / "frontend/src/lib.js").is_file()
    assert (root / "db.py").is_file()
    assert state["language"] == "mixed"
    assert state["fullstack"]
    assert state["database"] == "sqlite"
    assert "FastAPI" in state["practices"] or "fullstack" in state["stack"]


def test_prisma_overlay(tmp_path: Path):
    written = apply_database(tmp_path, "prisma")
    assert "prisma/schema.prisma" in written
    assert "model Item" in (tmp_path / "prisma/schema.prisma").read_text(encoding="utf-8")
