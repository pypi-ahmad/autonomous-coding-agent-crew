from __future__ import annotations

import time
from collections.abc import Callable

from agent_crew.crew import run_role

COVER_HIGH = 80
COVER_MID = 50

FALLBACK_PLAN = (
    "## Sub-tasks\n1. Implement the request in Python 3.12.\n"
    "## Implementation order\n1. Write modules.\n2. Write tests.\n"
    "## Risks\nPlanner failed; using fallback plan.\n"
    "## Edge cases\nEmpty input, invalid types.\n"
)


def run_role_retry(
    agent: object,
    description: str,
    expected_output: str,
    *,
    attempts: int = 3,
    sleeper: Callable[[float], None] = time.sleep,
) -> str:
    last: Exception | None = None
    wait = 0.5
    for _ in range(attempts):
        try:
            return run_role(agent, description, expected_output)  # type: ignore[arg-type]
        except Exception as exc:
            last = exc
            sleeper(wait)
            wait *= 2
    if last is None:
        raise RuntimeError("retry loop empty")
    raise last


def safe_role(
    agent: object,
    description: str,
    expected_output: str,
    fallback: str,
    *,
    sleeper: Callable[[float], None] = time.sleep,
) -> tuple[str, str]:
    try:
        return run_role_retry(agent, description, expected_output, sleeper=sleeper), ""
    except Exception as exc:
        return fallback, str(exc)


def heuristic_score(
    *,
    tests_passed: bool,
    coverage: float,
    error: str,
    mutant_killed: bool,
) -> int:
    score = 0
    if tests_passed:
        score += 40
    if coverage >= COVER_HIGH:
        score += 30
    elif coverage >= COVER_MID:
        score += 15
    if not error:
        score += 20
    if mutant_killed:
        score += 10
    return score


def score_suggestions(*, tests_passed: bool, coverage: float, error: str) -> list[str]:
    tips: list[str] = []
    if not tests_passed:
        tips.append("Get pytest green before adding features.")
    if coverage < COVER_HIGH:
        tips.append("Raise coverage on the public API.")
    if error:
        tips.append(f"Clear the run error: {error[:120]}")
    if not tips:
        tips.append("Split a hard function and add one edge-case test.")
    return tips[:3]
