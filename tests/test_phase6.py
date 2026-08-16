from pathlib import Path

import pytest

from agent_crew.codeintel import analyze_project
from agent_crew.graph import initial_state
from agent_crew.policy import Policy, get_policy, policy_from_state, set_policy
from agent_crew.shell import run_terminal
from agent_crew.templates import apply_template
from agent_crew.workspace import (
    apply_files,
    file_tree,
    parse_pytest_counts,
    render_history,
    render_report,
    write_file,
    write_history,
    write_report,
)


@pytest.fixture(autouse=True)
def _reset_policy():
    set_policy(Policy())
    yield
    set_policy(Policy())


def test_dry_run_skips_disk(tmp_path: Path):
    set_policy(Policy(dry_run=True))
    write_file(tmp_path, "a.py", "x = 1\n")
    assert not (tmp_path / "a.py").exists()


def test_writes_disabled(tmp_path: Path):
    set_policy(Policy(allow_write=False))
    with pytest.raises(ValueError, match="Writes disabled"):
        write_file(tmp_path, "a.py", "x")


def test_locked_glob_and_apply_skip(tmp_path: Path):
    set_policy(Policy(locked=("README.md", "secret.py")))
    with pytest.raises(ValueError, match="Locked"):
        write_file(tmp_path, "README.md", "no")
    text = """
### FILE: secret.py
```python
x = 1
```

### FILE: ok.py
```python
y = 2
```
"""
    written = apply_files(tmp_path, text)
    assert written == ["ok.py"]
    assert (tmp_path / "ok.py").is_file()
    assert not (tmp_path / "secret.py").exists()


def test_locked_basename_glob():
    policy = Policy(locked=("*.toml",))
    assert policy.is_locked("pyproject.toml")
    assert policy.is_locked("src/pkg/pyproject.toml")
    assert not policy.is_locked("src/pkg/core.py")


def test_terminal_policy(tmp_path: Path):
    write_file(tmp_path, "ok.py", "print(1)\n")
    set_policy(Policy(dry_run=True))
    ok, out = run_terminal(tmp_path, "python ok.py")
    assert ok
    assert "dry-run" in out
    set_policy(Policy(allow_terminal=False))
    with pytest.raises(ValueError, match="Terminal disabled"):
        run_terminal(tmp_path, "python ok.py")
    set_policy(Policy(allow_pip=False))
    with pytest.raises(ValueError, match="pip disabled"):
        run_terminal(tmp_path, "pip install hexample")


def test_apply_template_skips_existing(tmp_path: Path):
    write_file(tmp_path, "README.md", "keep\n")
    written = apply_template(tmp_path, "cli")
    assert "src/app/__main__.py" in written
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "keep\n"
    assert apply_template(tmp_path, "unknown") == []


def test_initial_state_template(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("agent_crew.graph.RUNS_DIR", tmp_path)
    state = initial_state("demo", "ollama", "unused", template="library", policy=Policy())
    root = Path(state["workspace"])
    assert (root / "src/pkg/core.py").is_file()
    assert state["template"] == "library"
    assert get_policy().allow_write


def test_report_and_history(tmp_path: Path):
    write_file(tmp_path, "a.py", "x = 1\n")
    state = {
        "task": "add integers",
        "workspace": str(tmp_path),
        "template": "library",
        "tests_passed": True,
        "coverage": 80,
        "score": 70,
        "log": ["Coder wrote a.py"],
        "plan": "Write add()",
        "evaluation": "ok",
        "feedback": "keep tests",
    }
    report = render_report(state)
    assert "add integers" in report
    assert "library" in report
    hist = render_history(state)
    assert "keep tests" in hist
    write_report(tmp_path, state)
    write_history(tmp_path, state)
    assert (tmp_path / "REPORT.md").is_file()
    assert (tmp_path / "HISTORY.md").is_file()
    assert "a.py" in file_tree(tmp_path)


def test_parse_pytest_counts():
    output = "3 passed, 1 failed, 2 error, 1 skipped in 0.1s"
    counts = parse_pytest_counts(output)
    assert counts["passed"] == 3
    assert counts["failed"] == 1
    assert counts["error"] == 2
    assert counts["skipped"] == 1


def test_analyze_cache_invalidates(tmp_path: Path):
    write_file(tmp_path, "a.py", "def add(a, b):\n    return a + b\n")
    first = analyze_project(tmp_path)
    assert first == analyze_project(tmp_path)
    write_file(tmp_path, "b.py", "def sub(a, b):\n    return a - b\n")
    second = analyze_project(tmp_path)
    assert "sub" in second
    assert first != second


def test_policy_from_state_defaults():
    pol = policy_from_state({"dry_run": True, "locked": "a.py, b.py"})
    assert pol.dry_run
    assert pol.allow_write
    assert pol.is_locked("a.py")
    assert pol.is_locked("b.py")
