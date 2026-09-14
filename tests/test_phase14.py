from dataclasses import dataclass
from pathlib import Path

from agent_crew.crew import _add_usage, get_usage, reset_usage
from agent_crew.workspace import append_terminal_log, read_terminal_log


@dataclass
class _FakeUsage:
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    successful_requests: int


def test_usage_tracker_accumulates_across_calls():
    reset_usage()
    assert get_usage() == {
        "total_tokens": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "successful_requests": 0,
    }
    _add_usage(
        _FakeUsage(total_tokens=10, prompt_tokens=7, completion_tokens=3, successful_requests=1)
    )
    _add_usage(
        _FakeUsage(total_tokens=5, prompt_tokens=4, completion_tokens=1, successful_requests=1)
    )
    usage = get_usage()
    assert usage["total_tokens"] == 15
    assert usage["prompt_tokens"] == 11
    assert usage["completion_tokens"] == 4
    assert usage["successful_requests"] == 2


def test_usage_tracker_ignores_missing_usage():
    reset_usage()
    _add_usage(None)
    assert get_usage()["total_tokens"] == 0


def test_terminal_log_roundtrip(tmp_path: Path):
    assert read_terminal_log(tmp_path) == ""
    append_terminal_log(tmp_path, "pytest -q", ok=True, output="2 passed")
    append_terminal_log(tmp_path, "pip install foo", ok=False, output="no matching distribution")
    log = read_terminal_log(tmp_path)
    assert "$ pytest -q" in log
    assert "[ok]" in log
    assert "$ pip install foo" in log
    assert "[failed]" in log
    assert "no matching distribution" in log
