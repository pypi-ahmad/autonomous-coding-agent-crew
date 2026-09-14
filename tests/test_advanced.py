from pathlib import Path
from shutil import which

import pytest

from agent_crew.settings import active_providers
from agent_crew.workspace import (
    append_trace,
    git_commit,
    git_diff,
    git_init,
    parse_coverage,
    read_trace,
    reflection_verdict,
    write_file,
)


def test_parse_coverage_reads_total_line():
    output = "src/app.py     10      2    80%\nTOTAL          10      2    80%\n"
    assert parse_coverage(output) == 80.0


def test_parse_coverage_missing():
    assert parse_coverage("no coverage here") is None


def test_reflection_verdict():
    assert reflection_verdict("OK\nLooks fine.") == "ok"
    assert reflection_verdict("REVISE\nMissing helper.") == "revise"


def test_active_providers_local_only():
    assert active_providers(local_only=True) == ("ollama",)
    assert "openai" in active_providers(local_only=False)


def test_trace_roundtrip(tmp_path: Path):
    append_trace(tmp_path, "coder", "wrote", "pkg/a.py", "pkg/a.py")
    rows = read_trace(tmp_path)
    assert rows[0]["agent"] == "coder"
    assert rows[0]["decision"] == "wrote"


@pytest.mark.skipif(which("git") is None, reason="git not on PATH")
def test_git_init_commit_diff(tmp_path: Path):
    write_file(tmp_path, "a.py", "x = 1\n")
    git_init(tmp_path)
    write_file(tmp_path, "a.py", "x = 2\n")
    git_commit(tmp_path, "feat: bump")
    write_file(tmp_path, "a.py", "x = 3\n")
    diff = git_diff(tmp_path)
    assert "3" in diff
