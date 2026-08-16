from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context
from pathlib import Path

from agent_crew.policy import policy_from_state, set_policy
from agent_crew.reliability import run_role_retry
from agent_crew.workspace import (
    _write_raw,
    file_blocks,
    is_test_path,
    write_file,
)

COMPLEX_WORDS = (
    "fullstack",
    "frontend",
    "backend",
    "database",
    "react",
    "next",
    "django",
    "auth",
    "oauth",
    "payment",
    "websocket",
    "graphql",
    "microservice",
)
PRIORITY = {"database": 3, "backend": 2, "coder": 2, "frontend": 1, "tester": 0}
LONG_TASK = 280
COMPLEX_SCORE = 4
SCOPE = {
    "coder": "Implement the full TREE. Do not write tests.",
    "backend": "Backend only: API, services, server modules. No frontend. No tests.",
    "frontend": "Frontend only: UI and client. No backend impl. No tests.",
    "database": "Database only: schema, db module, migrations. No UI. No tests.",
    "tester": "Tests only, from the plan/TREE. Do not write production code.",
}


def complexity_of(task: str, *, fullstack: bool = False, database: str = "none") -> str:
    score = 0
    if fullstack:
        score += 2
    if database and database != "none":
        score += 1
    if len(task) > LONG_TASK:
        score += 1
    lower = task.lower()
    score += min(sum(1 for word in COMPLEX_WORDS if word in lower), 3)
    if score >= COMPLEX_SCORE:
        return "complex"
    if score <= 1:
        return "simple"
    return "standard"


def select_coders(
    task: str,
    *,
    framework: str = "unknown",
    database: str = "none",
    fullstack: bool = False,
) -> tuple[str, ...]:
    level = complexity_of(task, fullstack=fullstack, database=database)
    if level == "simple":
        return ("coder",)
    roles: list[str] = []
    if fullstack or framework in {"react", "nextjs"}:
        roles.extend(["backend", "frontend"])
    elif framework in {"fastapi", "flask", "django", "express"}:
        roles.append("backend")
    else:
        roles.append("coder")
    if database not in {"", "none"} and "coder" in roles:
        roles = ["backend", "database"]
    elif database not in {"", "none"} and "database" not in roles:
        roles.append("database")
    seen: list[str] = []
    for role in roles:
        if role not in seen:
            seen.append(role)
    return tuple(seen or ("coder",))


def parse_vote(text: str) -> str:
    first = text.strip().splitlines()[0].upper() if text.strip() else ""
    if first.startswith("REVISE"):
        return "revise"
    return "approve"


def tally_votes(votes: dict[str, str]) -> str:
    if not votes:
        return "approve"
    revise = sum(1 for vote in votes.values() if vote == "revise")
    return "revise" if revise > len(votes) - revise else "approve"


def format_votes(votes: dict[str, str]) -> str:
    if not votes:
        return ""
    body = ", ".join(f"{name}={vote}" for name, vote in votes.items())
    return f"{tally_votes(votes)} ({body})"


def detect_conflicts(owned: dict[str, list[str]]) -> list[str]:
    claimed: dict[str, list[str]] = {}
    for role, paths in owned.items():
        for path in paths:
            claimed.setdefault(path, []).append(role)
    return [f"{path}: {', '.join(roles)}" for path, roles in claimed.items() if len(roles) > 1]


def resolve_writes(outputs: dict[str, str]) -> tuple[dict[str, tuple[str, str]], list[str]]:
    claimed: dict[str, tuple[str, str]] = {}
    conflicts: list[str] = []
    for role, text in outputs.items():
        for path, body in file_blocks(text):
            if is_test_path(path) and role != "tester":
                continue
            if (not is_test_path(path)) and role == "tester":
                continue
            prior = claimed.get(path)
            if prior and prior[0] != role:
                conflicts.append(f"{path}: {prior[0]} vs {role}")
                if PRIORITY.get(role, 0) <= PRIORITY.get(prior[0], 0):
                    continue
            claimed[path] = (role, body)
    return claimed, conflicts


def apply_resolved(workspace: Path, claimed: dict[str, tuple[str, str]]) -> list[str]:
    written: list[str] = []
    for path, (role, body) in claimed.items():
        written.append(write_file(workspace, path, body, protect_tests=role != "tester"))
    return written


def write_conflicts(workspace: Path, conflicts: list[str]) -> str:
    if not conflicts:
        return ""
    body = "# Conflicts\n\n" + "\n".join(f"- {row}" for row in conflicts) + "\n"
    return _write_raw(workspace, "CONFLICTS.md", body)


def make_inbox(*, agent: str, files: list[str], note: str, extra: str = "") -> str:
    lines = [f"{agent}: {note}"]
    if files:
        lines.append("files: " + ", ".join(files[:16]))
    if extra:
        lines.append(extra)
    return "\n".join(lines)


def format_inbox(state: dict) -> str:
    blob = (state.get("inbox") or "").strip()
    return f"\nHandoff:\n{blob}\n" if blob else ""


def run_parallel(
    state: dict,
    agents: dict,
    jobs: dict[str, tuple[str, str]],
) -> dict[str, str]:
    if not jobs:
        return {}

    def work(role: str, prompt: str, expected: str) -> tuple[str, str]:
        set_policy(policy_from_state(state))
        return role, run_role_retry(agents[role], prompt, expected)

    if len(jobs) == 1:
        role, (prompt, expected) = next(iter(jobs.items()))
        name, text = work(role, prompt, expected)
        return {name: text}

    out: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=min(4, len(jobs))) as pool:
        futs = []
        for role, (prompt, expected) in jobs.items():
            ctx = copy_context()
            futs.append(pool.submit(ctx.run, work, role, prompt, expected))
        for fut in as_completed(futs):
            role, text = fut.result()
            out[role] = text
    return out
