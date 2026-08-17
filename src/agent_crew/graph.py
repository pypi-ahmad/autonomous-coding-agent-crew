from __future__ import annotations

from collections.abc import Iterator
from contextlib import suppress
from pathlib import Path
from typing import Literal, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from agent_crew.autonomy import install_deps, parse_subtasks, remaining_subtasks, write_health
from agent_crew.codeintel import analyze_project, blamed_snapshot, parse_traceback
from agent_crew.collab import (
    SCOPE,
    apply_resolved,
    complexity_of,
    format_inbox,
    format_votes,
    make_inbox,
    parse_vote,
    resolve_writes,
    run_parallel,
    select_coders,
    tally_votes,
    write_conflicts,
)
from agent_crew.crew import FILE_FORMAT, build_agents
from agent_crew.llm import make_llm
from agent_crew.memory import format_lessons, recall, remember_outcome
from agent_crew.policy import Policy, policy_from_state, set_policy
from agent_crew.quality import evaluate_quality, format_levels, write_quality
from agent_crew.reliability import (
    FALLBACK_PLAN,
    heuristic_score,
    run_role_retry,
    safe_role,
    score_suggestions,
)
from agent_crew.settings import (
    MAX_DEBUG_ATTEMPTS,
    MAX_GOAL_CYCLES,
    MAX_REVIEW_ATTEMPTS,
    MAX_TEST_REWRITES,
    MIN_COVERAGE,
    MIN_LOOP_SCORE,
    RUNS_DIR,
)
from agent_crew.stack import apply_hint, detect_stack, format_stack, practices_for
from agent_crew.templates import apply_database, apply_template
from agent_crew.workspace import (
    append_crew_log,
    append_trace,
    apply_files,
    copy_project,
    git_commit,
    git_diff,
    git_init,
    git_rollback,
    git_savepoint,
    has_tests,
    list_files,
    parse_coverage,
    probe_one_mutation,
    reflection_verdict,
    run_python,
    run_tests,
    save_run,
    snapshot,
    write_file,
    write_history,
    write_report,
    write_repro,
)


class CrewState(TypedDict):
    task: str
    provider: str
    model: str
    workspace: str
    plan: str
    plan_approved: bool
    code: str
    tests: str
    test_output: str
    tests_passed: bool
    debug_attempts: int
    docs: str
    log: list[str]
    current_agent: str
    current_file: str
    error: str
    feedback: str
    coverage: float
    diff: str
    reflection: str
    analysis: str
    checkpoint: str
    score: int
    evaluation: str
    template: str
    dry_run: bool
    allow_write: bool
    allow_terminal: bool
    allow_pip: bool
    locked: str
    stack: str
    language: str
    framework: str
    database: str
    fullstack: bool
    practices: str
    gates_ok: bool
    gate_fail: str
    quality: str
    test_rewrites: int
    test_levels: str
    roster: str
    votes: str
    conflicts: str
    review: str
    review_verdict: str
    review_attempts: int
    inbox: str
    complexity: str
    autonomous: bool
    goal_cycles: int
    max_goal_cycles: int
    subtasks: str
    deps: str
    rollback: str
    health: str


def route_after_tester(state: CrewState) -> Literal["debugger", "documenter", "tester"]:
    if state.get("error"):
        return "documenter"
    if "gates_ok" not in state:
        done = state["tests_passed"] or state["debug_attempts"] >= MAX_DEBUG_ATTEMPTS
        return "documenter" if done else "debugger"
    if state["gates_ok"] or state.get("debug_attempts", 0) >= MAX_DEBUG_ATTEMPTS:
        return "documenter"
    fail = state.get("gate_fail") or ""
    rewrites = int(state.get("test_rewrites") or 0)
    if fail in {"coverage", "missing_tests"} and rewrites < MAX_TEST_REWRITES:
        return "tester"
    return "debugger"


def route_after_evaluate(state: CrewState) -> Literal["planner", "done"]:
    if not state.get("autonomous"):
        return "done"
    score = int(state.get("score") or 0)
    if state.get("gates_ok") and score >= int(MIN_LOOP_SCORE):
        return "done"
    if int(state.get("goal_cycles") or 0) >= int(state.get("max_goal_cycles") or MAX_GOAL_CYCLES):
        return "done"
    return "planner"


def route_after_reviewer(state: CrewState) -> Literal["coder", "next"]:
    if state.get("error"):
        return "next"
    verdict = state.get("review_verdict") or ""
    attempts = int(state.get("review_attempts") or 0)
    if verdict == "revise" and attempts < MAX_REVIEW_ATTEMPTS:
        return "coder"
    return "next"


def _append(
    state: CrewState,
    line: str,
    agent: str = "",
    file: str = "",
    decision: str = "",
) -> dict:
    workspace = Path(state["workspace"])
    stamp = line if not file else f"{line} [{file}]"
    with suppress(OSError):
        append_crew_log(workspace, stamp)
        append_trace(workspace, agent or "crew", decision or line, line, file)
    return {
        "log": [*state["log"], stamp],
        "current_agent": agent,
        "current_file": file,
    }


def _agents(state: CrewState) -> dict:
    return build_agents(make_llm(state["provider"], state["model"]), Path(state["workspace"]))


def _tree(workspace: Path) -> str:
    names = list_files(workspace)
    return "\n".join(names) if names else "(empty)"


def _notes(state: CrewState) -> str:
    text = (state.get("feedback") or "").strip()
    return f"\nUser feedback:\n{text}\n" if text else ""


def _stack_prompt(state: CrewState) -> str:
    stack = state.get("stack") or ""
    practices = state.get("practices") or ""
    if not stack and not practices:
        return ""
    return f"\nStack:\n{stack}\n{practices}\n"


def _context(state: CrewState) -> str:
    return f"{_notes(state)}{_stack_prompt(state)}{format_inbox(state)}"


def _roster_for(state: CrewState) -> tuple[str, ...]:
    return select_coders(
        state["task"],
        framework=str(state.get("framework") or "unknown"),
        database=str(state.get("database") or "none"),
        fullstack=bool(state.get("fullstack")),
    )


def _bind(state: CrewState) -> None:
    set_policy(policy_from_state(state))


def _collect_votes(state: CrewState, plan: str, roster: tuple[str, ...]) -> dict[str, str]:
    agents = _agents(state)
    voters = ["reviewer", "tester"]
    lead = roster[0] if roster else "coder"
    if lead not in voters:
        voters.append(lead)
    prompt = f"Vote on this plan. First line APPROVE or REVISE.\n\n{plan}\n{_context(state)}"
    votes: dict[str, str] = {}
    for name in voters:
        if name not in agents:
            continue
        ballot, _fail = safe_role(
            agents[name],
            prompt,
            "APPROVE or REVISE, then one sentence.",
            "APPROVE",
        )
        votes[name] = parse_vote(ballot)
    return votes


def planner_node(state: CrewState) -> dict:
    _bind(state)
    workspace = Path(state["workspace"])
    existing = _tree(workspace)
    analysis = analyze_project(workspace) if existing != "(empty)" else ""
    if existing == "(empty)":
        scope = (
            "This may be a high-level goal. Infer stack, TREE, and a complete sub-task list. "
            "Generate a full project from scratch. Start with a ### TREE block. "
            "Full-stack means backend + frontend."
        )
    else:
        scope = (
            "This may be a high-level goal on an existing tree. "
            "Plan the smallest feature add. Do not rewrite unrelated files.\n"
            f"Current tree:\n{existing}\n\nCode map:\n{analysis}"
        )
    leftover = remaining_subtasks(state.get("plan") or "", [])
    if leftover and int(state.get("goal_cycles") or 0) > 0:
        scope += "\nContinue with remaining sub-tasks:\n- " + "\n- ".join(leftover[:8])
    try:
        lessons = format_lessons(recall(state["task"]))
        text, fail = safe_role(
            _agents(state)["planner"],
            (
                f"User request:\n{state['task']}\n{_notes(state)}{_stack_prompt(state)}\n"
                f"{scope}\n{lessons}\n"
                "Required sections:\n"
                "## Sub-tasks\n## Implementation order\n## Risks\n## Edge cases\n"
                "Reuse past lessons. Avoid known mistakes. Follow stack practices."
            ),
            "Sub-tasks, order, risks, edge cases, and a file tree.",
            FALLBACK_PLAN,
        )
        roster = _roster_for(state)
        level = complexity_of(
            state["task"],
            fullstack=bool(state.get("fullstack")),
            database=str(state.get("database") or "none"),
        )
        votes = _collect_votes(state, text, roster)
        if tally_votes(votes) == "revise":
            text, _again = safe_role(
                _agents(state)["planner"],
                (
                    f"Votes:\n{format_votes(votes)}\nRevise the plan. Keep TREE and sections.\n"
                    f"Original:\n{text}"
                ),
                "Revised plan.",
                text,
            )
        extra = _append(
            state,
            "Planner finished" + (" (fallback)" if fail else "") + f" roster={','.join(roster)}",
            "planner",
            decision="plan",
        )
        return {
            "plan": text,
            "analysis": analysis,
            "roster": ",".join(roster),
            "complexity": level,
            "subtasks": " | ".join(parse_subtasks(text)),
            "votes": format_votes(votes),
            "inbox": make_inbox(
                agent="planner",
                files=[],
                note="plan ready",
                extra=format_votes(votes),
            ),
            "error": "",
            **extra,
        }
    except Exception as exc:
        extra = _append(state, f"Planner error: {exc}", "planner", decision="error")
        return {"error": str(exc), **extra}


def coder_node(state: CrewState) -> dict:
    _bind(state)
    workspace = Path(state["workspace"])
    with suppress(OSError, FileNotFoundError):
        git_init(workspace)
    try:
        roster = _roster_for(state)
        if state.get("roster"):
            roster = tuple(part for part in state["roster"].split(",") if part)
        roles = list(roster)
        if "tester" not in roles:
            roles.append("tester")
        agents = _agents(state)
        review_note = ""
        review_attempts = int(state.get("review_attempts") or 0)
        if (state.get("review_verdict") or "") == "revise":
            review_note = f"\nReviewer asked for changes:\n{state.get('review') or ''}\n"
            review_attempts += 1
        jobs: dict[str, tuple[str, str]] = {}
        for role in roles:
            if role not in agents:
                continue
            jobs[role] = (
                (
                    f"Approved plan:\n{state['plan']}\n\nRequest:\n{state['task']}\n"
                    f"{_context(state)}{review_note}\nFiles now:\n{_tree(workspace)}\n\n"
                    f"{SCOPE.get(role, SCOPE['coder'])}\n"
                    "Use search_code / search_semantic / rename_symbol on existing trees. "
                    f"{FILE_FORMAT}"
                ),
                "### FILE blocks for your owned paths.",
            )
        outputs = run_parallel(state, agents, jobs)
        claimed, conflicts = resolve_writes(outputs)
        written = apply_resolved(workspace, claimed)
        with suppress(OSError, ValueError):
            write_conflicts(workspace, conflicts)
        pkgs, dep_note = install_deps(workspace)
        deps = ", ".join(pkgs) if pkgs else dep_note
        impl_text = "\n\n".join(text for role, text in outputs.items() if role != "tester" and text)
        test_text = outputs.get("tester") or state.get("tests") or ""
        diff = ""
        with suppress(OSError, FileNotFoundError):
            diff = git_diff(workspace)
        commit_message = "feat: parallel coder pass"
        if diff.strip():
            summary, fail = safe_role(
                agents.get("documenter") or next(iter(agents.values())),
                "Write ONE line, conventional-commit style (feat:/fix:/refactor:/test:/chore:), "
                f"summarizing this diff. No body, no quotes, under 72 chars.\n\n{diff[:4000]}",
                "One line, e.g. 'feat: add health endpoint'.",
                commit_message,
            )
            if not fail:
                commit_message = summary.strip().splitlines()[0][:120] or commit_message
        with suppress(OSError, FileNotFoundError):
            git_commit(workspace, commit_message)
        extra = _append(
            state,
            (
                f"Build roster={','.join(roles)} wrote={', '.join(written) or 'none'}"
                + (f" conflicts={len(conflicts)}" if conflicts else "")
            ),
            "coder",
            written[-1] if written else "",
            "build",
        )
        return {
            "code": impl_text,
            "tests": test_text,
            "reflection": "",
            "diff": diff,
            "roster": ",".join(roster),
            "conflicts": "; ".join(conflicts),
            "review_attempts": review_attempts,
            "inbox": make_inbox(
                agent="coder",
                files=written,
                note="parallel build done",
                extra="; ".join(conflicts),
            ),
            "deps": deps,
            "error": "",
            **extra,
        }
    except Exception as exc:
        extra = _append(state, f"Coder error: {exc}", "coder", decision="error")
        return {"error": str(exc), **extra}


def reviewer_node(state: CrewState) -> dict:
    _bind(state)
    workspace = Path(state["workspace"])
    attempts = int(state.get("review_attempts") or 0)
    try:
        text = run_role_retry(
            _agents(state)["reviewer"],
            (
                f"Review architecture and quality. First line OK or REVISE.\n"
                f"Request:\n{state['task']}\nPlan:\n{state['plan']}\n"
                f"{_context(state)}\nConflicts:\n{state.get('conflicts') or 'none'}\n"
                f"Files:\n{snapshot(workspace)}\n"
                "Check coupling, stack fit, missing modules. Do not write files."
            ),
            "OK or REVISE, then a short architecture review.",
        )
        verdict = reflection_verdict(text)
        extra = _append(
            state,
            f"Reviewer {verdict}",
            "reviewer",
            decision=verdict,
        )
        return {
            "review": text,
            "review_verdict": verdict,
            "review_attempts": attempts,
            "inbox": make_inbox(
                agent="reviewer",
                files=[],
                note=verdict,
                extra=text[:400],
            ),
            "error": "",
            **extra,
        }
    except Exception as exc:
        extra = _append(state, f"Reviewer error: {exc}", "reviewer", decision="error")
        return {"error": str(exc), **extra}


def tester_node(state: CrewState) -> dict:
    _bind(state)
    workspace = Path(state["workspace"])
    text = state["tests"]
    rewrites = int(state.get("test_rewrites") or 0)
    try:
        need_write = (not has_tests(workspace)) or (
            (state.get("gate_fail") or "") in {"coverage", "missing_tests"}
        )
        if need_write:
            text = run_role_retry(
                _agents(state)["tester"],
                (
                    f"Request:\n{state['task']}\n{_context(state)}\n"
                    f"Files:\n{snapshot(workspace)}\n\n"
                    f"Gate: {state.get('gate_fail') or 'first pass'}. "
                    f"Coverage: {state.get('coverage', -1)}. Min {MIN_COVERAGE:.0f}%.\n"
                    "Write unit tests (test_*.py), edge tests (test_edge_*.py), "
                    "and integration tests (test_integration_*.py) if more than one module. "
                    "Optional test_perf_*.py for hot functions. "
                    "Python: pytest. JS: node:test (*.test.js). "
                    f"Do not delete existing tests. {FILE_FORMAT}"
                ),
                "### FILE blocks containing unit, edge, and integration tests.",
            )
            apply_files(workspace, text)
            rewrites += 1
        passed, output = run_tests(workspace)
        coverage = parse_coverage(output)
        cover_note = f" coverage={coverage:.0f}%" if coverage is not None else ""
        if passed:
            mutant, note = probe_one_mutation(workspace)
            if mutant == "survived":
                passed = False
                output = f"{note}\n{output}"
                line = f"Tester green but mutant survived{cover_note}"
            else:
                line = f"Tester passed ({mutant}){cover_note}"
        elif state["debug_attempts"] >= MAX_DEBUG_ATTEMPTS:
            write_repro(workspace, output)
            line = f"Wrote REPRO.md (fail-closed){cover_note}"
        else:
            line = f"Tester failed{cover_note}"
        quality = evaluate_quality(
            workspace,
            tests_ok=passed,
            coverage=coverage if coverage is not None else -1.0,
        )
        with suppress(OSError, ValueError):
            write_quality(workspace, quality)
        rollback = state.get("rollback") or ""
        if quality.ok:
            with suppress(OSError, FileNotFoundError):
                git_savepoint(workspace, "chore: green")
        elif state["debug_attempts"] >= MAX_DEBUG_ATTEMPTS:
            write_repro(workspace, quality.report)
            with suppress(OSError, FileNotFoundError):
                rollback = git_rollback(workspace)
                if rollback and rollback != "no green savepoint":
                    line = f"{line}; {rollback}"
        extra = _append(state, line, "tester", decision=quality.fail or "test")
        return {
            "tests": text,
            "tests_passed": passed,
            "test_output": output,
            "coverage": coverage if coverage is not None else -1.0,
            "gates_ok": quality.ok,
            "gate_fail": quality.fail,
            "quality": quality.report,
            "test_rewrites": rewrites,
            "test_levels": format_levels(quality.levels),
            "rollback": rollback,
            "error": "",
            **extra,
        }
    except Exception as exc:
        extra = _append(state, f"Tester error: {exc}", "tester", decision="error")
        return {"error": str(exc), "tests_passed": False, "gates_ok": False, **extra}


def debugger_node(state: CrewState) -> dict:
    _bind(state)
    workspace = Path(state["workspace"])
    attempt = state["debug_attempts"] + 1
    try:
        frames = parse_traceback(state["test_output"])
        blamed = blamed_snapshot(workspace, state["test_output"])
        frame_txt = "\n".join(f"{path}:{line}" for path, line in frames) or "(no frames)"
        text = run_role_retry(
            _agents(state)["debugger"],
            (
                f"Request:\n{state['task']}\n{_context(state)}\n"
                f"Failed gate: {state.get('gate_fail') or 'tests'}.\n"
                f"Quality:\n{state.get('quality') or '(none)'}\n\n"
                f"Stack frames:\n{frame_txt}\n\n"
                f"Test output:\n{state['test_output']}\n\n"
                f"Blamed files:\n{blamed}\n\n"
                "Fix implementation only. Multi-file patches are allowed. "
                "Clear lint, type, security, and perf findings. "
                "You may add temporary print() in blamed files; remove them before you finish. "
                f"Do not change tests. {FILE_FORMAT}"
            ),
            "Updated ### FILE blocks for blamed implementation files.",
        )
        written = apply_files(workspace, text, protect_tests=True)
        file = written[-1] if written else ""
        smoke = ""
        first_py = next(
            (
                name
                for name in written
                if name.endswith(".py") and not Path(name).name.startswith("test_")
            ),
            "",
        )
        if first_py:
            ok, _out = run_python(workspace, first_py)
            smoke = f" sandbox {'ok' if ok else 'failed'}"
        extra = _append(
            state,
            f"Debugger attempt {attempt}: {', '.join(written) or 'no files'}{smoke}",
            "debugger",
            file,
            decision="fix",
        )
        return {"code": text, "debug_attempts": attempt, "error": "", **extra}
    except Exception as exc:
        extra = _append(state, f"Debugger error: {exc}", "debugger", decision="error")
        return {"debug_attempts": attempt, "error": str(exc), **extra}


def documenter_node(state: CrewState) -> dict:
    _bind(state)
    workspace = Path(state["workspace"])
    cover = state.get("coverage", -1.0)
    cover_txt = f"{cover:.0f}%" if cover is not None and cover >= 0 else "n/a"
    try:
        text = run_role_retry(
            _agents(state)["documenter"],
            (
                f"Request:\n{state['task']}\n{_context(state)}\n"
                f"Files:\n{snapshot(workspace)}\n\n"
                f"Coverage: {cover_txt}. Gates: {state.get('gate_fail') or 'pass'}. "
                f"Error: {state['error'] or 'none'}.\n"
                "Write README.md and add brief comments only where the code is not obvious. "
                f"{FILE_FORMAT}"
            ),
            "### FILE blocks including README.md.",
        )
        apply_files(workspace, text)
        with suppress(OSError, FileNotFoundError):
            git_commit(workspace, "docs: documenter pass")
        extra = _append(state, "Documenter finished", "documenter", "README.md", "docs")
        return {"docs": text, **extra}
    except Exception as exc:
        extra = _append(state, f"Documenter error: {exc}", "documenter", decision="error")
        return {"error": state["error"] or str(exc), **extra}


def evaluate_node(state: CrewState) -> dict:
    _bind(state)
    workspace = Path(state["workspace"])
    mutant_killed = any("killed" in line.lower() for line in state["log"])
    score = heuristic_score(
        tests_passed=state["tests_passed"],
        coverage=state.get("coverage", -1.0),
        error=state.get("error") or "",
        mutant_killed=mutant_killed,
    )
    tips = score_suggestions(
        tests_passed=state["tests_passed"],
        coverage=state.get("coverage", -1.0),
        error=state.get("error") or "",
    )
    review, _fail = safe_role(
        _agents(state)["documenter"],
        (
            f"Score this result. Quality, readability, test coverage. "
            f"Tests passed={state['tests_passed']} coverage={state.get('coverage', -1)}. "
            f"Suggest 3 improvements.\nFiles:\n{_tree(workspace)}"
        ),
        "Short scores and three suggestions.",
        "",
    )
    body = f"# Score {score}/100\n\n" + "\n".join(f"- {tip}" for tip in tips)
    if state.get("quality"):
        body += "\n\n" + str(state["quality"])
    if review:
        body += "\n\n## Model review\n" + review
    cycles = int(state.get("goal_cycles") or 0)
    if state.get("autonomous") and not (state.get("gates_ok") and score >= MIN_LOOP_SCORE):
        cycles += 1
    kind = "fail"
    with suppress(OSError, ValueError):
        write_file(workspace, "EVAL.md", body + "\n")
        kind = remember_outcome(
            task=state["task"],
            score=score,
            tests_passed=state["tests_passed"],
            gates_ok=bool(state.get("gates_ok")),
            coverage=float(state.get("coverage") or -1),
            stack=str(state.get("stack") or ""),
            failure=str(state.get("gate_fail") or ""),
            lesson=tips[0],
        )
    extra = _append(state, f"Eval score {score}/100 {kind}", "evaluate", "EVAL.md", "score")
    snapshot_state = {**state, "score": score, "evaluation": body, "goal_cycles": cycles}
    health = ""
    with suppress(OSError, ValueError):
        write_report(workspace, snapshot_state)
        write_history(workspace, snapshot_state)
        health = write_health(workspace, snapshot_state)
    leftover = remaining_subtasks(state.get("plan") or "", [])
    inbox = make_inbox(
        agent="evaluate",
        files=[health] if health else [],
        note=f"{kind} score={score}",
        extra="next: " + (leftover[0] if leftover else "done"),
    )
    return {
        "score": score,
        "evaluation": body,
        "goal_cycles": cycles,
        "health": health,
        "inbox": inbox,
        **extra,
    }


def build_plan_graph() -> object:
    graph = StateGraph(CrewState)
    graph.add_node("planner", planner_node)
    graph.add_edge(START, "planner")
    graph.add_edge("planner", END)
    return graph.compile()


def build_code_graph() -> object:
    graph = StateGraph(CrewState)
    graph.add_node("coder", coder_node)
    graph.add_node("reviewer", reviewer_node)
    graph.add_edge(START, "coder")
    graph.add_edge("coder", "reviewer")
    graph.add_conditional_edges(
        "reviewer",
        route_after_reviewer,
        {"coder": "coder", "next": END},
    )
    return graph.compile()


def build_verify_graph() -> object:
    graph = StateGraph(CrewState)
    graph.add_node("tester", tester_node)
    graph.add_node("debugger", debugger_node)
    graph.add_node("documenter", documenter_node)
    graph.add_node("evaluate", evaluate_node)
    graph.add_edge(START, "tester")
    graph.add_conditional_edges(
        "tester",
        route_after_tester,
        {"debugger": "debugger", "documenter": "documenter", "tester": "tester"},
    )
    graph.add_edge("debugger", "tester")
    graph.add_edge("documenter", "evaluate")
    graph.add_edge("evaluate", END)
    return graph.compile()


def build_exec_graph() -> object:
    graph = StateGraph(CrewState)
    graph.add_node("coder", coder_node)
    graph.add_node("reviewer", reviewer_node)
    graph.add_node("tester", tester_node)
    graph.add_node("debugger", debugger_node)
    graph.add_node("documenter", documenter_node)
    graph.add_node("evaluate", evaluate_node)
    graph.add_edge(START, "coder")
    graph.add_edge("coder", "reviewer")
    graph.add_conditional_edges(
        "reviewer",
        route_after_reviewer,
        {"coder": "coder", "next": "tester"},
    )
    graph.add_conditional_edges(
        "tester",
        route_after_tester,
        {"debugger": "debugger", "documenter": "documenter", "tester": "tester"},
    )
    graph.add_edge("debugger", "tester")
    graph.add_edge("documenter", "evaluate")
    graph.add_edge("evaluate", END)
    return graph.compile()


def build_auto_graph() -> object:
    graph = StateGraph(CrewState)
    graph.add_node("planner", planner_node)
    graph.add_node("coder", coder_node)
    graph.add_node("reviewer", reviewer_node)
    graph.add_node("tester", tester_node)
    graph.add_node("debugger", debugger_node)
    graph.add_node("documenter", documenter_node)
    graph.add_node("evaluate", evaluate_node)
    graph.add_edge(START, "coder")
    graph.add_edge("coder", "reviewer")
    graph.add_conditional_edges(
        "reviewer",
        route_after_reviewer,
        {"coder": "coder", "next": "tester"},
    )
    graph.add_conditional_edges(
        "tester",
        route_after_tester,
        {"debugger": "debugger", "documenter": "documenter", "tester": "tester"},
    )
    graph.add_edge("debugger", "tester")
    graph.add_edge("documenter", "evaluate")
    graph.add_conditional_edges(
        "evaluate",
        route_after_evaluate,
        {"planner": "planner", "done": END},
    )
    graph.add_edge("planner", "coder")
    return graph.compile()


def build_graph() -> object:
    graph = StateGraph(CrewState)
    graph.add_node("planner", planner_node)
    graph.add_node("coder", coder_node)
    graph.add_node("reviewer", reviewer_node)
    graph.add_node("tester", tester_node)
    graph.add_node("debugger", debugger_node)
    graph.add_node("documenter", documenter_node)
    graph.add_node("evaluate", evaluate_node)
    graph.add_edge(START, "planner")
    graph.add_edge("planner", "coder")
    graph.add_edge("coder", "reviewer")
    graph.add_conditional_edges(
        "reviewer",
        route_after_reviewer,
        {"coder": "coder", "next": "tester"},
    )
    graph.add_conditional_edges(
        "tester",
        route_after_tester,
        {"debugger": "debugger", "documenter": "documenter", "tester": "tester"},
    )
    graph.add_edge("debugger", "tester")
    graph.add_edge("documenter", "evaluate")
    graph.add_edge("evaluate", END)
    return graph.compile()


def initial_state(
    task: str,
    provider: str,
    model: str,
    project_dir: str | None = None,
    feedback: str = "",
    *,
    template: str = "blank",
    database: str = "none",
    policy: Policy | None = None,
    autonomous: bool = False,
    max_goal_cycles: int = MAX_GOAL_CYCLES,
) -> CrewState:
    workspace = RUNS_DIR / uuid4().hex[:8]
    workspace.mkdir(parents=True, exist_ok=True)
    if project_dir:
        src = Path(project_dir).expanduser().resolve()
        if not src.is_dir():
            raise ValueError(f"Not a directory: {project_dir}")
        copy_project(src, workspace)
    if template and template not in {"blank", "auto"}:
        apply_template(workspace, template)
    if database and database != "none":
        apply_database(workspace, database)
    found = apply_hint(detect_stack(workspace), template, database)
    pol = policy or Policy()
    set_policy(pol)
    return {
        "task": task,
        "provider": provider,
        "model": model,
        "workspace": str(workspace),
        "plan": "",
        "plan_approved": False,
        "code": "",
        "tests": "",
        "test_output": "",
        "tests_passed": False,
        "debug_attempts": 0,
        "docs": "",
        "log": [],
        "current_agent": "",
        "current_file": "",
        "error": "",
        "feedback": feedback,
        "coverage": -1.0,
        "diff": "",
        "reflection": "",
        "analysis": "",
        "checkpoint": "",
        "score": -1,
        "evaluation": "",
        "template": template or "blank",
        "dry_run": pol.dry_run,
        "allow_write": pol.allow_write,
        "allow_terminal": pol.allow_terminal,
        "allow_pip": pol.allow_pip,
        "locked": ",".join(pol.locked),
        "stack": format_stack(found),
        "language": found.language,
        "framework": found.framework,
        "database": found.database,
        "fullstack": found.fullstack,
        "practices": practices_for(found),
        "gates_ok": False,
        "gate_fail": "",
        "quality": "",
        "test_rewrites": 0,
        "test_levels": "",
        "roster": "",
        "votes": "",
        "conflicts": "",
        "review": "",
        "review_verdict": "",
        "review_attempts": 0,
        "inbox": "",
        "complexity": "",
        "autonomous": autonomous,
        "goal_cycles": 0,
        "max_goal_cycles": max_goal_cycles,
        "subtasks": "",
        "deps": "",
        "rollback": "",
        "health": "",
    }


def run_plan(
    task: str,
    provider: str,
    model: str,
    project_dir: str | None = None,
    feedback: str = "",
    *,
    template: str = "blank",
    database: str = "none",
    policy: Policy | None = None,
) -> CrewState:
    return build_plan_graph().invoke(  # type: ignore[return-value]
        initial_state(
            task,
            provider,
            model,
            project_dir,
            feedback,
            template=template,
            database=database,
            policy=policy,
        )
    )


def _stream(graph: object, state: CrewState) -> Iterator[tuple[str, dict, CrewState]]:
    merged: CrewState = state
    try:
        for chunk in graph.stream(state, stream_mode="updates"):  # type: ignore[attr-defined]
            for node, update in chunk.items():
                payload = update if isinstance(update, dict) else {}
                merged = {**merged, **payload, "checkpoint": str(node)}  # type: ignore[misc]
                with suppress(OSError, TypeError, ValueError):
                    save_run(Path(merged["workspace"]), dict(merged))
                yield str(node), payload, merged
    except Exception as exc:
        merged = {**merged, "error": str(exc), "log": [*merged["log"], f"error: {exc}"]}
        yield "error", {"error": str(exc)}, merged
    with suppress(OSError, TypeError, ValueError):
        save_run(Path(merged["workspace"]), dict(merged))


def stream_code(state: CrewState) -> Iterator[tuple[str, dict, CrewState]]:
    approved: CrewState = {**state, "plan_approved": True}
    yield from _stream(build_code_graph(), approved)


def stream_verify(state: CrewState) -> Iterator[tuple[str, dict, CrewState]]:
    yield from _stream(build_verify_graph(), state)


def stream_auto(state: CrewState) -> Iterator[tuple[str, dict, CrewState]]:
    """Run planner->coder->...->evaluate on a loop, no approval pauses."""
    approved: CrewState = {**state, "plan_approved": True, "autonomous": True}
    yield from _stream(build_auto_graph(), approved)


def run_autonomous(
    task: str,
    provider: str,
    model: str,
    project_dir: str | None = None,
    feedback: str = "",
    *,
    template: str = "blank",
    database: str = "none",
    policy: Policy | None = None,
    max_goal_cycles: int = MAX_GOAL_CYCLES,
) -> Iterator[tuple[str, dict, CrewState]]:
    state = initial_state(
        task,
        provider,
        model,
        project_dir,
        feedback,
        template=template,
        database=database,
        policy=policy,
        autonomous=True,
        max_goal_cycles=max_goal_cycles,
    )
    yield from stream_auto(state)


def stream_build(state: CrewState) -> Iterator[tuple[str, dict, CrewState]]:
    merged = state
    for item in stream_code(state):
        yield item
        merged = item[2]
        if merged.get("error"):
            return
    yield from stream_verify(merged)


def run_build(state: CrewState) -> CrewState:
    final: CrewState = {**state, "plan_approved": True}
    for _node, _update, merged in stream_build(state):
        final = merged
    return final


def resume_phase(checkpoint: str) -> str:
    if checkpoint == "planner":
        return "plan"
    if checkpoint in {"coder", "reviewer"}:
        return "review"
    return "done"


def run_crew(
    task: str,
    provider: str,
    model: str,
    project_dir: str | None = None,
    feedback: str = "",
    *,
    template: str = "blank",
    database: str = "none",
    policy: Policy | None = None,
) -> CrewState:
    planned = run_plan(
        task,
        provider,
        model,
        project_dir,
        feedback,
        template=template,
        database=database,
        policy=policy,
    )
    if planned["error"]:
        return planned
    return run_build(planned)
