from pathlib import Path
from shutil import which

import pytest

from agent_crew.shell import build_command
from agent_crew.workspace import git_commit, git_diff, git_init, write_file


@pytest.mark.skipif(which("git") is None, reason="git not on PATH")
def test_diff_captured_before_commit_is_not_empty(tmp_path: Path):
    write_file(tmp_path, "a.py", "x = 1\n")
    git_init(tmp_path)
    write_file(tmp_path, "a.py", "x = 2\n")

    before_commit = git_diff(tmp_path)
    git_commit(tmp_path, "feat: bump")
    after_commit = git_diff(tmp_path)

    assert "2" in before_commit
    assert after_commit == ""


def test_shell_allowlists_git_branch(tmp_path: Path):
    argv = build_command(tmp_path, "git branch")
    assert argv[1:] == ["branch"]


def test_shell_still_refuses_git_push():
    with pytest.raises(ValueError, match="not allowlisted"):
        build_command(Path(), "git push")
