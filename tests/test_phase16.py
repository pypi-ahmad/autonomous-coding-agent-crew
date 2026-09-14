import sys
import time
from pathlib import Path

from agent_crew.llm import make_llm
from agent_crew.memory import load_memory, memory_path, remember
from agent_crew.workspace import _write_raw, run_subprocess


def test_run_subprocess_normal_execution(tmp_path: Path):
    ok, out = run_subprocess([sys.executable, "-c", "print('hi')"], cwd=tmp_path, timeout=10)
    assert ok
    assert "hi" in out


def test_run_subprocess_nonzero_exit(tmp_path: Path):
    ok, _out = run_subprocess(
        [sys.executable, "-c", "raise SystemExit(1)"], cwd=tmp_path, timeout=10
    )
    assert not ok


def test_run_subprocess_times_out_and_kills_tree(tmp_path: Path):
    start = time.monotonic()
    ok, out = run_subprocess(
        [sys.executable, "-c", "import time; time.sleep(30)"], cwd=tmp_path, timeout=1
    )
    elapsed = time.monotonic() - start
    assert not ok
    assert "timeout" in out.lower()
    assert elapsed < 10  # the wait is bounded even though the sleep was 30s


def test_run_subprocess_missing_executable(tmp_path: Path):
    ok, out = run_subprocess(["this-binary-does-not-exist-xyz"], cwd=tmp_path, timeout=5)
    assert not ok
    assert out


def test_write_raw_is_atomic_and_leaves_no_tmp_files(tmp_path: Path):
    _write_raw(tmp_path, "run.json", '{"a": 1}')
    assert (tmp_path / "run.json").read_text(encoding="utf-8") == '{"a": 1}'
    leftovers = list(tmp_path.glob(".*.tmp"))
    assert leftovers == []


def test_load_memory_skips_malformed_lines(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("agent_crew.memory.RUNS_DIR", tmp_path)
    path = memory_path()
    path.write_text(
        '{"kind": "win", "task": "a"}\nnot valid json\n{"kind": "fail", "task": "b"}\n',
        encoding="utf-8",
    )
    rows = load_memory()
    assert len(rows) == 2
    assert rows[0]["task"] == "a"
    assert rows[1]["task"] == "b"


def test_remember_then_load_roundtrip(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("agent_crew.memory.RUNS_DIR", tmp_path)
    remember({"kind": "win", "task": "demo"})
    rows = load_memory()
    assert rows[0]["task"] == "demo"


def test_make_llm_sets_a_timeout(monkeypatch):
    # openai/google/agnes validate against a static model list (no network
    # call, unlike ollama), so a fake key is enough to exercise this path.
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    llm = make_llm("openai", "gpt-5.6-luna")
    assert llm.timeout is not None
    assert llm.timeout > 0
