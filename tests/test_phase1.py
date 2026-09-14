from pathlib import Path

import pytest

from agent_crew.graph import route_after_tester
from agent_crew.settings import MAX_DEBUG_ATTEMPTS
from agent_crew.workspace import apply_files, run_tests, safe_file


def test_route_after_tester_pass_goes_to_documenter():
    state = {
        "tests_passed": True,
        "debug_attempts": 0,
    }
    assert route_after_tester(state) == "documenter"  # type: ignore[arg-type]


def test_route_after_tester_fail_retries_then_stops():
    failing = {"tests_passed": False, "debug_attempts": 0}
    assert route_after_tester(failing) == "debugger"  # type: ignore[arg-type]
    exhausted = {"tests_passed": False, "debug_attempts": MAX_DEBUG_ATTEMPTS}
    assert route_after_tester(exhausted) == "documenter"  # type: ignore[arg-type]


def test_apply_files_and_pytest(tmp_path: Path):
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
    written = apply_files(tmp_path, text)
    assert written == ["add.py", "test_add.py"]
    passed, output = run_tests(tmp_path)
    assert passed, output


def test_safe_file_rejects_escape(tmp_path: Path):
    with pytest.raises(ValueError, match="Refused path"):
        safe_file(tmp_path, "../secret.txt")
