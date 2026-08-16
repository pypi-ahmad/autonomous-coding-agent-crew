from pathlib import Path

import pytest

from agent_crew.codeintel import (
    analyze_project,
    blamed_files,
    parse_traceback,
    rename_symbol,
    search_code,
    search_semantic,
)
from agent_crew.shell import build_command
from agent_crew.workspace import write_file


def test_analyze_project_lists_defs(tmp_path: Path):
    write_file(
        tmp_path,
        "pkg/mod.py",
        "import os\n\nclass Box:\n    pass\n\ndef add(a, b):\n    return a + b\n",
    )
    report = analyze_project(tmp_path)
    assert "Box" in report
    assert "add" in report
    assert "os" in report


def test_search_keyword_and_semantic(tmp_path: Path):
    write_file(tmp_path, "a.py", "def invoice_total():\n    return 1\n")
    write_file(tmp_path, "b.py", "def greet():\n    return 'hi'\n")
    assert "invoice_total" in search_code(tmp_path, "invoice_")
    ranked = search_semantic(tmp_path, "invoice total")
    assert "a.py" in ranked
    assert ranked.splitlines()[0].endswith("a.py")


def test_rename_symbol_across_files(tmp_path: Path):
    write_file(tmp_path, "a.py", "def add(a, b):\n    return a + b\n")
    write_file(tmp_path, "b.py", "from a import add\n\nprint(add(1, 2))\n")
    changed = rename_symbol(tmp_path, "add", "plus")
    assert "a.py" in changed
    assert "b.py" in changed
    assert "def plus" in (tmp_path / "a.py").read_text(encoding="utf-8")
    assert "plus(1, 2)" in (tmp_path / "b.py").read_text(encoding="utf-8")


def test_parse_traceback_and_blame(tmp_path: Path):
    write_file(tmp_path, "app.py", "x = 1\n")
    output = 'File "app.py", line 3, in test\nAssertionError\n'
    assert parse_traceback(output) == [("app.py", 3)]
    assert blamed_files(tmp_path, output) == ["app.py"]


def test_terminal_allowlist(tmp_path: Path):
    write_file(tmp_path, "ok.py", "print(1)\n")
    argv = build_command(tmp_path, "python ok.py")
    assert argv[-1] == "ok.py"
    pip = build_command(tmp_path, "pip install hexample")
    assert "--target" in pip
    assert "hexample" in pip
    with pytest.raises(ValueError, match="Refused"):
        build_command(tmp_path, "rm -rf /")
    with pytest.raises(ValueError, match="unsafe"):
        build_command(tmp_path, "pip install foo; rm -rf /")
    with pytest.raises(ValueError, match="Refused"):
        build_command(tmp_path, "curl https://evil.test")
