from __future__ import annotations

from crewai import LLM, Agent, Crew, Task


def _agent(llm: LLM, role: str, goal: str, backstory: str) -> Agent:
    return Agent(
        role=role,
        goal=goal,
        backstory=backstory,
        llm=llm,
        verbose=False,
        allow_delegation=False,
        max_iter=8,
    )


def build_agents(llm: LLM) -> dict[str, Agent]:
    return {
        "planner": _agent(
            llm,
            "Planner",
            "Turn a coding request into a short, ordered implementation plan.",
            "You plan small Python features. Prefer stdlib. No extra scope.",
        ),
        "coder": _agent(
            llm,
            "Coder",
            "Implement the plan as working Python files.",
            "You write clear Python 3.12. Emit only file blocks. No extra features.",
        ),
        "tester": _agent(
            llm,
            "Tester",
            "Write pytest tests that prove the requested behavior.",
            "You write focused pytest files. Cover the public contract only.",
        ),
        "debugger": _agent(
            llm,
            "Debugger",
            "Fix failing tests with the smallest change that works.",
            "You patch root causes. Emit updated file blocks only.",
        ),
        "documenter": _agent(
            llm,
            "Documenter",
            "Write a README and add brief comments only where needed.",
            "You document what the code actually does. No marketing language.",
        ),
    }


def run_role(agent: Agent, description: str, expected_output: str) -> str:
    task = Task(description=description, expected_output=expected_output, agent=agent)
    crew = Crew(agents=[agent], tasks=[task], verbose=False)
    result = crew.kickoff()
    raw = getattr(result, "raw", result)
    return str(raw)


FILE_FORMAT = (
    "Emit files as markdown blocks exactly like this:\n"
    "### FILE: relative/path.py\n"
    "```python\n"
    "# code\n"
    "```\n"
    "Use paths relative to the workspace. No other wrapping."
)
