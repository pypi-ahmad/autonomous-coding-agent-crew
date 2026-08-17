from __future__ import annotations

import json
import re
from pathlib import Path

from agent_crew.logging_setup import get_logger
from agent_crew.settings import RUNS_DIR

TOKEN = re.compile(r"[a-z0-9_]+")
WIN_SCORE_THRESHOLD = 70


def memory_path() -> Path:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    return RUNS_DIR / "memory.jsonl"


def _tokens(text: str) -> set[str]:
    return set(TOKEN.findall(text.lower()))


def remember(record: dict) -> None:
    path = memory_path()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def load_memory() -> list[dict]:
    path = memory_path()
    if not path.is_file():
        return []
    rows: list[dict] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            get_logger().warning("Skipping malformed memory.jsonl line %d", lineno)
    return rows


def recall(task: str, limit: int = 5, kind: str = "") -> list[dict]:
    needles = _tokens(task)
    scored: list[tuple[int, dict]] = []
    for row in load_memory():
        if kind and row.get("kind") != kind:
            continue
        bag = _tokens(
            str(row.get("task", ""))
            + " "
            + str(row.get("lesson", ""))
            + " "
            + str(row.get("pattern", ""))
            + " "
            + str(row.get("failure", ""))
        )
        score = len(needles & bag)
        if score:
            scored.append((score, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [row for _score, row in scored[:limit]]


def format_lessons(rows: list[dict]) -> str:
    if not rows:
        return ""
    lines = ["Past lessons:"]
    lines.extend(
        f"- kind={row.get('kind') or 'lesson'} "
        f"task={row.get('task', '')[:80]} score={row.get('score', '?')} "
        f"lesson={row.get('lesson') or row.get('pattern') or row.get('failure', '')}"
        for row in rows
    )
    return "\n".join(lines)


def remember_outcome(  # noqa: PLR0913
    *,
    task: str,
    score: int,
    tests_passed: bool,
    gates_ok: bool,
    coverage: float,
    stack: str = "",
    failure: str = "",
    lesson: str = "",
) -> str:
    kind = "win" if tests_passed and score >= WIN_SCORE_THRESHOLD else "fail"
    pattern = ""
    if kind == "win":
        pattern = f"gates={gates_ok} stack={stack[:80]} coverage={coverage:.0f}"
    record = {
        "kind": kind,
        "task": task,
        "score": score,
        "lesson": lesson,
        "pattern": pattern,
        "failure": failure if kind == "fail" else "",
        "tests_passed": tests_passed,
        "coverage": coverage,
        "stack": stack,
    }
    remember(record)
    return kind
