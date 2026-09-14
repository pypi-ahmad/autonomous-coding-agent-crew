from pathlib import Path

from agent_crew.memory import format_lessons, recall, remember
from agent_crew.reliability import heuristic_score, run_role_retry, score_suggestions
from agent_crew.workspace import list_runs, load_run, save_run, write_file


def test_heuristic_score_and_tips():
    score = heuristic_score(tests_passed=True, coverage=90, error="", mutant_killed=True)
    assert score == 100
    tips = score_suggestions(tests_passed=False, coverage=10, error="boom")
    assert len(tips) == 3


def test_run_role_retry_recovers(monkeypatch):
    calls = {"n": 0}

    def flaky(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("temp")
        return "ok"

    monkeypatch.setattr("agent_crew.reliability.run_role", flaky)
    assert run_role_retry(None, "d", "e", sleeper=lambda _delay: None) == "ok"  # type: ignore[arg-type]
    assert calls["n"] == 3


def test_memory_recall(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("agent_crew.memory.memory_path", lambda: tmp_path / "memory.jsonl")
    remember({"task": "add integers package", "lesson": "lock tests first", "score": 80})
    remember({"task": "unrelated weather bot", "lesson": "timeouts", "score": 20})
    hits = recall("add two integers")
    assert hits
    assert "lock tests" in hits[0]["lesson"]
    text = format_lessons(hits)
    assert "Past lessons" in text


def test_checkpoint_roundtrip(tmp_path: Path):
    write_file(tmp_path, "a.py", "x = 1\n")
    save_run(tmp_path, {"checkpoint": "coder", "task": "demo"})
    loaded = load_run(tmp_path)
    assert loaded["checkpoint"] == "coder"
    runs = list_runs(tmp_path.parent)
    assert any(path.parent == tmp_path for path in runs)
