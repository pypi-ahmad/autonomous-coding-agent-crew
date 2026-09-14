from pathlib import Path

import pytest

from agent_crew.workspace import (
    apply_files,
    copy_project,
    create_file,
    probe_one_mutation,
    write_file,
    write_repro,
    zip_workspace,
)


def test_apply_files_protect_tests_skips_test_modules(tmp_path: Path):
    text = """
### FILE: add.py
```python
def add(a, b):
    return a + b
```

### FILE: test_add.py
```python
from add import add
def test_add():
    assert add(2, 3) == 5
```
"""
    written = apply_files(tmp_path, text, protect_tests=True)
    assert written == ["add.py"]
    assert not (tmp_path / "test_add.py").exists()


def test_write_file_protect_tests_raises(tmp_path: Path):
    with pytest.raises(ValueError, match="Refused test path"):
        write_file(tmp_path, "test_x.py", "x", protect_tests=True)


def test_mutation_kills_real_assert(tmp_path: Path):
    write_file(
        tmp_path,
        "add.py",
        "def add(a, b):\n    return a + b\n",
    )
    write_file(
        tmp_path,
        "test_add.py",
        "from add import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
    )
    status, note = probe_one_mutation(tmp_path)
    assert status == "killed"
    assert "add.py" in note
    assert "return a + b" in (tmp_path / "add.py").read_text(encoding="utf-8")


def test_mutation_survives_tautology(tmp_path: Path):
    write_file(tmp_path, "add.py", "def add(a, b):\n    return a + b\n")
    write_file(tmp_path, "test_add.py", "def test_ok():\n    assert True\n")
    status, note = probe_one_mutation(tmp_path)
    assert status == "survived"
    assert "survived" in note.lower()


def test_copy_project_skips_venv(tmp_path: Path):
    src = tmp_path / "srcproj"
    src.mkdir()
    (src / "app.py").write_text("x = 1\n", encoding="utf-8")
    (src / ".venv").mkdir()
    (src / ".venv" / "x").write_text("no", encoding="utf-8")
    dest = tmp_path / "dest"
    copy_project(src, dest)
    assert (dest / "app.py").is_file()
    assert not (dest / ".venv").exists()


def test_zip_and_repro(tmp_path: Path):
    create_file(tmp_path, "a.py", "print(1)\n")
    write_repro(tmp_path, "boom")
    blob = zip_workspace(tmp_path)
    assert blob[:2] == b"PK"
    assert (tmp_path / "REPRO.md").is_file()
