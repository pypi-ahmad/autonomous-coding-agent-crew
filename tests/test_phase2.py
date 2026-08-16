from pathlib import Path

import pytest

from agent_crew.graph import route_after_tester
from agent_crew.tools import make_fs_tools
from agent_crew.workspace import (
    create_file,
    has_tests,
    list_files,
    read_file,
    run_python,
    safe_file,
    write_file,
)


def test_create_read_write_list(tmp_path: Path):
    create_file(tmp_path, "pkg/util.py", "X = 1\n")
    write_file(tmp_path, "pkg/util.py", "X = 2\n")
    write_file(tmp_path, "README.md", "hi\n")
    assert read_file(tmp_path, "pkg/util.py") == "X = 2\n"
    assert list_files(tmp_path) == ["pkg/util.py", "README.md"]


def test_create_file_refuses_overwrite(tmp_path: Path):
    create_file(tmp_path, "a.py", "1")
    with pytest.raises(FileExistsError):
        create_file(tmp_path, "a.py", "2")


def test_fs_tools_refuse_escape(tmp_path: Path):
    with pytest.raises(ValueError, match="Refused path"):
        write_file(tmp_path, "../x.py", "no")
    with pytest.raises(ValueError, match="Refused path"):
        read_file(tmp_path, "../x.py")


def test_run_python_sandbox(tmp_path: Path):
    write_file(tmp_path, "ok.py", "print(2 + 2)\n")
    ok, out = run_python(tmp_path, "ok.py")
    assert ok, out
    assert "4" in out


def test_run_python_rejects_non_python(tmp_path: Path):
    write_file(tmp_path, "notes.md", "x")
    with pytest.raises(ValueError, match="\\.py"):
        run_python(tmp_path, "notes.md")


def test_run_python_timeout(tmp_path: Path):
    write_file(tmp_path, "slow.py", "import time\ntime.sleep(30)\n")
    ok, out = run_python(tmp_path, "slow.py", timeout=1)
    assert not ok
    assert "timeout" in out.lower()


def test_has_tests_detects_pytest_files(tmp_path: Path):
    write_file(tmp_path, "app.py", "x = 1\n")
    assert not has_tests(tmp_path)
    write_file(tmp_path, "test_app.py", "def test_x():\n    assert True\n")
    assert has_tests(tmp_path)


def test_route_after_tester_still_caps_retries():
    fail = {"tests_passed": False, "debug_attempts": 0, "error": ""}
    ok = {"tests_passed": True, "debug_attempts": 0, "error": ""}
    assert route_after_tester(fail) == "debugger"  # type: ignore[arg-type]
    assert route_after_tester(ok) == "documenter"  # type: ignore[arg-type]


def test_safe_file_still_jails(tmp_path: Path):
    dest = safe_file(tmp_path, "pkg/a.py")
    assert dest.is_relative_to(tmp_path.resolve())


def test_crewai_fs_tools_roundtrip(tmp_path: Path):
    tools = {tool.name: tool for tool in make_fs_tools(tmp_path)}
    tools["create_file"].run(path="pkg/a.py", content="print(1)\n")
    tools["write_file"].run(path="pkg/a.py", content="print(2)\n")
    assert "print(2)" in tools["read_file"].run(path="pkg/a.py")
    assert "pkg/a.py" in tools["list_files"].run()
    ok_text = tools["run_python"].run(path="pkg/a.py")
    assert "ok" in ok_text
    assert "2" in ok_text
