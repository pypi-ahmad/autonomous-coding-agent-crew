from pathlib import Path

from agent_crew.graph import CrewState, initial_state, route_after_evaluate
from agent_crew.policy import Policy


def test_initial_state_autonomous_defaults(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("agent_crew.graph.RUNS_DIR", tmp_path)
    state = initial_state("demo", "ollama", "unused", policy=Policy())
    assert state["autonomous"] is False
    assert state["goal_cycles"] == 0
    assert state["max_goal_cycles"] == 2


def test_initial_state_autonomous_override(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("agent_crew.graph.RUNS_DIR", tmp_path)
    state = initial_state(
        "demo", "ollama", "unused", policy=Policy(), autonomous=True, max_goal_cycles=5
    )
    assert state["autonomous"] is True
    assert state["max_goal_cycles"] == 5


def _state(**overrides: object) -> CrewState:
    base: dict[str, object] = {
        "autonomous": True,
        "score": 0,
        "gates_ok": False,
        "goal_cycles": 0,
        "max_goal_cycles": 2,
    }
    base.update(overrides)
    return base  # type: ignore[return-value]


def test_route_after_evaluate_not_autonomous_stops():
    assert route_after_evaluate(_state(autonomous=False)) == "done"


def test_route_after_evaluate_loops_until_budget():
    assert route_after_evaluate(_state(goal_cycles=0, max_goal_cycles=2)) == "planner"
    assert route_after_evaluate(_state(goal_cycles=2, max_goal_cycles=2)) == "done"


def test_route_after_evaluate_stops_on_passing_score():
    assert route_after_evaluate(_state(gates_ok=True, score=90)) == "done"
