from pathlib import Path

import pytest

from agent_crew.graph import route_after_tester
from agent_crew.quality import classify_tests, evaluate_quality, security_scan, write_quality
from agent_crew.settings import MAX_DEBUG_ATTEMPTS, MAX_TEST_REWRITES, MIN_COVERAGE
from agent_crew.shell import build_command
from agent_crew.workspace import write_file


def test_route_legacy_still_uses_tests_passed():
    assert route_after_tester({"tests_passed": True, "debug_attempts": 0}) == "documenter"
    assert route_after_tester({"tests_passed": False, "debug_attempts": 0}) == "debugger"


def test_route_gates_ok_to_documenter():
    state = {"gates_ok": True, "tests_passed": True, "debug_attempts": 0, "gate_fail": ""}
    assert route_after_tester(state) == "documenter"  # type: ignore[arg-type]


def test_route_missing_tests_back_to_tester():
    state = {
        "gates_ok": False,
        "tests_passed": True,
        "debug_attempts": 0,
        "gate_fail": "missing_tests",
        "test_rewrites": 0,
    }
    assert route_after_tester(state) == "tester"  # type: ignore[arg-type]
    state["test_rewrites"] = MAX_TEST_REWRITES
    assert route_after_tester(state) == "debugger"  # type: ignore[arg-type]


def test_route_lint_goes_to_debugger():
    state = {
        "gates_ok": False,
        "tests_passed": True,
        "debug_attempts": 0,
        "gate_fail": "lint",
        "test_rewrites": 0,
    }
    assert route_after_tester(state) == "debugger"  # type: ignore[arg-type]


def test_route_gates_exhausted_to_documenter():
    state = {
        "gates_ok": False,
        "tests_passed": False,
        "debug_attempts": MAX_DEBUG_ATTEMPTS,
        "gate_fail": "tests",
    }
    assert route_after_tester(state) == "documenter"  # type: ignore[arg-type]


def test_classify_test_levels(tmp_path: Path):
    write_file(tmp_path, "test_add.py", "def test_add():\n    assert True\n")
    write_file(tmp_path, "test_edge_add.py", "def test_add_empty():\n    assert True\n")
    write_file(tmp_path, "test_integration_api.py", "def test_flow():\n    assert True\n")
    buckets = classify_tests(tmp_path)
    assert buckets["unit"]
    assert buckets["edge"]
    assert buckets["integration"]


def test_security_flags_eval(tmp_path: Path):
    write_file(tmp_path, "evil.py", "def run(x):\n    return eval(x)\n")
    ok, report = security_scan(tmp_path)
    assert not ok
    assert "eval" in report


def test_quality_requires_edge_and_coverage(tmp_path: Path):
    write_file(tmp_path, "add.py", "def add(a, b):\n    return a + b\n")
    write_file(
        tmp_path,
        "test_add.py",
        "from add import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
    )
    q = evaluate_quality(tmp_path, tests_ok=True, coverage=40)
    assert not q.ok
    assert q.fail in {"missing_tests", "coverage"}
    write_file(
        tmp_path,
        "test_edge_add.py",
        "from add import add\n\ndef test_add_zero():\n    assert add(0, 0) == 0\n",
    )
    q2 = evaluate_quality(tmp_path, tests_ok=True, coverage=90)
    assert q2.levels_ok
    assert q2.coverage_ok
    assert q2.coverage >= MIN_COVERAGE
    write_quality(tmp_path, q2)
    assert (tmp_path / "QUALITY.md").is_file()


def test_quality_pass_clean_module(tmp_path: Path):
    write_file(tmp_path, "add.py", "def add(left, right):\n    return left + right\n")
    write_file(
        tmp_path,
        "test_add.py",
        "from add import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
    )
    write_file(
        tmp_path,
        "test_edge_add.py",
        "from add import add\n\ndef test_add_zero():\n    assert add(0, 0) == 0\n",
    )
    q = evaluate_quality(tmp_path, tests_ok=True, coverage=90)
    assert q.ok, q.report
    assert q.fail == ""


def test_ruff_and_ty_allowlisted(tmp_path: Path):
    argv = build_command(tmp_path, "python -m ruff check .")
    assert "ruff" in argv
    argv = build_command(tmp_path, "python -m ty check .")
    assert "ty" in argv
    with pytest.raises(ValueError, match="python is limited"):
        build_command(tmp_path, "python -m ruff format .")
