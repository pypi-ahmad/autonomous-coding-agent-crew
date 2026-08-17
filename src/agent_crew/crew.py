from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from crewai import LLM, Agent, Crew, Task

from agent_crew.tools import make_fs_tools, make_read_tools

if TYPE_CHECKING:
    from crewai.tools import BaseTool


def _agent(
    llm: LLM,
    role: str,
    goal: str,
    backstory: str,
    tools: list[BaseTool] | None = None,
) -> Agent:
    return Agent(
        role=role,
        goal=goal,
        backstory=backstory,
        llm=llm,
        tools=tools or [],
        verbose=False,
        allow_delegation=False,
        max_iter=8,
    )


def build_agents(llm: LLM, workspace: Path | None = None) -> dict[str, Agent]:
    impl = make_fs_tools(workspace, protect_tests=True) if workspace is not None else []
    tests = make_fs_tools(workspace, protect_tests=False) if workspace is not None else []
    return {
        "planner": _agent(
            llm,
            "Planner",
            "Break a request into sub-tasks, an implementation order, risks, and edge cases.",
            "You plan work for the detected stack (Python and/or JavaScript). "
            "Greenfield gets a full TREE. Existing trees get a smallest-diff feature add. "
            "Honor framework and database practices. Prefer stdlib. No extra scope.",
        ),
        "coder": _agent(
            llm,
            "Coder",
            "Implement the approved plan as working files for the detected stack.",
            "You write clear Python 3.12 and/or JavaScript. Use file tools, search, rename, "
            "or ### FILE blocks. On existing trees, change only what the plan names. "
            "Do not write test files.",
            impl,
        ),
        "backend": _agent(
            llm,
            "Backend coder",
            "Implement server, API, and service files only.",
            "You own backend paths. Do not write frontend or tests. Match the plan TREE.",
            impl,
        ),
        "frontend": _agent(
            llm,
            "Frontend coder",
            "Implement UI and client files only.",
            "You own frontend paths. Do not write backend services or tests. Match the plan TREE.",
            impl,
        ),
        "database": _agent(
            llm,
            "Database coder",
            "Implement schema and data-access files only.",
            "You own db modules and schema. Parameterized queries. Do not write UI or tests.",
            impl,
        ),
        "reviewer": _agent(
            llm,
            "Reviewer",
            "Check architecture, coupling, and quality before tests.",
            "You do not write files. First line OK or REVISE. Name concrete risks.",
            make_read_tools(workspace) if workspace is not None else [],
        ),
        "tester": _agent(
            llm,
            "Tester",
            "Write unit, integration, and edge tests that prove the requested behavior.",
            "Python: pytest. JavaScript: node:test (*.test.js). "
            "Always add test_*.py (unit), test_edge_*.py, and test_integration_*.py "
            "when more than one module exists. Optional test_perf_*.py. "
            "Do not delete existing tests. Raise coverage on the public API.",
            tests,
        ),
        "debugger": _agent(
            llm,
            "Debugger",
            "Fix failing tests and quality gates with the smallest change that works.",
            "You read stack frames, QUALITY.md, and blamed files. Patch root causes. "
            "Clear lint, types, security, and perf gates. Use run_terminal with "
            "'git log' or 'git diff' if you need to see what the last coder pass "
            "actually changed. Temporary prints are allowed; remove them. Do not weaken tests.",
            impl,
        ),
        "documenter": _agent(
            llm,
            "Documenter",
            "Write a README and add brief comments only where needed.",
            "You document what the code actually does. No marketing language.",
            tests,
        ),
    }


def run_role(agent: Agent, description: str, expected_output: str) -> str:
    task = Task(description=description, expected_output=expected_output, agent=agent)
    crew = Crew(agents=[agent], tasks=[task], verbose=False)
    result = crew.kickoff()
    raw = getattr(result, "raw", result)
    return str(raw)


FILE_FORMAT = (
    "Emit the project for the detected stack. Full-stack uses backend/ and frontend/.\n"
    "Python tests: test_*.py unit, test_edge_*.py, test_integration_*.py, "
    "optional test_perf_*.py.\n"
    "JS tests: *.test.js (node --test, CommonJS).\n"
    "### FILE: relative/path\n"
    "```\n"
    "# code\n"
    "```\n"
    "Use paths relative to the workspace. Multiple files are required. "
    "Tools: list_files, read_file, write_file, create_file, run_python, "
    "search_code, search_semantic, rename_symbol, analyze_project, detect_stack, "
    "run_quality, run_terminal (python, pytest, pip, ruff, ty, node, git)."
)
