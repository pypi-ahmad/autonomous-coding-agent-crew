from pathlib import Path

from agent_crew.graph import CrewState, route_after_tester
from agent_crew.logging_setup import configure_logging
from agent_crew.quality import evaluate_quality
from agent_crew.workspace import delete_workspace, reset_all_runs, write_file


def _state(**overrides: object) -> CrewState:
    base: dict[str, object] = {
        "error": "",
        "debug_attempts": 0,
        "max_debug_attempts": 3,
        "gates_ok": False,
        "gate_fail": "",
        "test_rewrites": 0,
        "tests_passed": False,
    }
    base.update(overrides)
    return base  # type: ignore[return-value]


def test_route_after_tester_respects_custom_debug_limit():
    assert route_after_tester(_state(debug_attempts=1, max_debug_attempts=2)) == "debugger"
    assert route_after_tester(_state(debug_attempts=2, max_debug_attempts=2)) == "documenter"


def test_route_after_tester_falls_back_to_default_when_unset():
    state = _state(debug_attempts=2)
    del state["max_debug_attempts"]  # type: ignore[misc]
    assert route_after_tester(state) == "debugger"


def test_evaluate_quality_respects_custom_coverage_floor(tmp_path: Path):
    write_file(tmp_path, "pkg.py", "def add(a, b):\n    return a + b\n")
    strict = evaluate_quality(tmp_path, tests_ok=True, coverage=60.0, min_coverage=90.0)
    lenient = evaluate_quality(tmp_path, tests_ok=True, coverage=60.0, min_coverage=50.0)
    assert not strict.coverage_ok
    assert lenient.coverage_ok
    assert "min 90%" in strict.report
    assert "min 50%" in lenient.report


def test_configure_logging_is_idempotent_and_creates_file():
    logger = configure_logging()
    handlers_before = len(logger.handlers)
    logger2 = configure_logging()
    assert logger is logger2
    assert len(logger2.handlers) == handlers_before
    logger.warning("test log line")
    assert logger.handlers[0].baseFilename  # type: ignore[attr-defined]


def test_delete_workspace_removes_directory(tmp_path: Path):
    target = tmp_path / "run1"
    target.mkdir()
    (target / "a.txt").write_text("x", encoding="utf-8")
    delete_workspace(target)
    assert not target.exists()


def test_reset_all_runs_removes_dirs_but_keeps_log(tmp_path: Path):
    (tmp_path / "run1").mkdir()
    (tmp_path / "run2").mkdir()
    (tmp_path / "agent-crew.log").write_text("log", encoding="utf-8")
    removed = reset_all_runs(tmp_path)
    assert removed == 2
    assert not (tmp_path / "run1").exists()
    assert not (tmp_path / "run2").exists()
    assert (tmp_path / "agent-crew.log").exists()


def test_reset_all_runs_missing_dir_returns_zero(tmp_path: Path):
    assert reset_all_runs(tmp_path / "nope") == 0
