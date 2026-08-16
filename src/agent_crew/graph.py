from __future__ import annotations

from pathlib import Path
from typing import Literal, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from agent_crew.crew import FILE_FORMAT, build_agents, run_role
from agent_crew.llm import make_llm
from agent_crew.settings import MAX_DEBUG_ATTEMPTS, RUNS_DIR
from agent_crew.workspace import apply_files, run_tests, snapshot


class CrewState(TypedDict):
    task: str
    provider: str
    model: str
    workspace: str
    plan: str
    code: str
    tests: str
    test_output: str
    tests_passed: bool
    debug_attempts: int
    docs: str
    log: list[str]


def route_after_tester(state: CrewState) -> Literal["debugger", "documenter"]:
    if state["tests_passed"]:
        return "documenter"
    if state["debug_attempts"] >= MAX_DEBUG_ATTEMPTS:
        return "documenter"
    return "debugger"


def _append(state: CrewState, line: str) -> list[str]:
    return [*state["log"], line]


def _agents(state: CrewState) -> dict:
    return build_agents(make_llm(state["provider"], state["model"]))


def planner_node(state: CrewState) -> dict:
    text = run_role(
        _agents(state)["planner"],
        (
            f"User request:\n{state['task']}\n\n"
            "Write a numbered implementation plan. Python 3.12, stdlib first."
        ),
        "A short numbered plan.",
    )
    return {"plan": text, "log": _append(state, "Planner finished")}


def coder_node(state: CrewState) -> dict:
    text = run_role(
        _agents(state)["coder"],
        (
            f"Request:\n{state['task']}\n\nPlan:\n{state['plan']}\n\n"
            f"Write the implementation. {FILE_FORMAT}"
        ),
        "One or more ### FILE blocks with Python source.",
    )
    written = apply_files(Path(state["workspace"]), text)
    return {
        "code": text,
        "log": _append(state, f"Coder wrote: {', '.join(written) or 'no files'}"),
    }


def tester_node(state: CrewState) -> dict:
    workspace = Path(state["workspace"])
    text = run_role(
        _agents(state)["tester"],
        (
            f"Request:\n{state['task']}\n\nCurrent files:\n{snapshot(workspace)}\n\n"
            f"Write pytest tests. {FILE_FORMAT}"
        ),
        "### FILE blocks containing pytest tests.",
    )
    apply_files(workspace, text)
    passed, output = run_tests(workspace)
    status = "passed" if passed else "failed"
    return {
        "tests": text,
        "tests_passed": passed,
        "test_output": output,
        "log": _append(state, f"Tester {status}"),
    }


def debugger_node(state: CrewState) -> dict:
    workspace = Path(state["workspace"])
    text = run_role(
        _agents(state)["debugger"],
        (
            f"Request:\n{state['task']}\n\nTest output:\n{state['test_output']}\n\n"
            f"Current files:\n{snapshot(workspace)}\n\n"
            f"Fix the failures. {FILE_FORMAT}"
        ),
        "Updated ### FILE blocks.",
    )
    written = apply_files(workspace, text)
    return {
        "code": text,
        "debug_attempts": state["debug_attempts"] + 1,
        "log": _append(
            state,
            f"Debugger attempt {state['debug_attempts'] + 1}: {', '.join(written) or 'no files'}",
        ),
    }


def documenter_node(state: CrewState) -> dict:
    workspace = Path(state["workspace"])
    text = run_role(
        _agents(state)["documenter"],
        (
            f"Request:\n{state['task']}\n\nFiles:\n{snapshot(workspace)}\n\n"
            "Write README.md and add brief comments only where the code is not obvious. "
            f"{FILE_FORMAT}"
        ),
        "### FILE blocks including README.md and any commented source.",
    )
    apply_files(workspace, text)
    return {"docs": text, "log": _append(state, "Documenter finished")}


def build_graph() -> object:
    graph = StateGraph(CrewState)
    graph.add_node("planner", planner_node)
    graph.add_node("coder", coder_node)
    graph.add_node("tester", tester_node)
    graph.add_node("debugger", debugger_node)
    graph.add_node("documenter", documenter_node)
    graph.add_edge(START, "planner")
    graph.add_edge("planner", "coder")
    graph.add_edge("coder", "tester")
    graph.add_conditional_edges(
        "tester",
        route_after_tester,
        {"debugger": "debugger", "documenter": "documenter"},
    )
    graph.add_edge("debugger", "tester")
    graph.add_edge("documenter", END)
    return graph.compile()


def run_crew(task: str, provider: str, model: str) -> CrewState:
    workspace = RUNS_DIR / uuid4().hex[:8]
    workspace.mkdir(parents=True, exist_ok=True)
    initial: CrewState = {
        "task": task,
        "provider": provider,
        "model": model,
        "workspace": str(workspace),
        "plan": "",
        "code": "",
        "tests": "",
        "test_output": "",
        "tests_passed": False,
        "debug_attempts": 0,
        "docs": "",
        "log": [],
    }
    return build_graph().invoke(initial)  # type: ignore[return-value]
