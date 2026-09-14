from pathlib import Path

from agent_crew.collab import (
    apply_resolved,
    complexity_of,
    detect_conflicts,
    format_votes,
    parse_vote,
    resolve_writes,
    select_coders,
    tally_votes,
)
from agent_crew.graph import resume_phase, route_after_reviewer
from agent_crew.policy import Policy, set_policy
from agent_crew.settings import MAX_REVIEW_ATTEMPTS
from agent_crew.workspace import file_block_paths


def test_select_coders_simple():
    assert select_coders("add two integers") == ("coder",)
    assert complexity_of("add two integers") == "simple"


def test_select_coders_fullstack_and_db():
    roles = select_coders(
        "Build a fullstack dashboard with auth and payments",
        framework="fastapi",
        database="sqlite",
        fullstack=True,
    )
    assert "backend" in roles
    assert "frontend" in roles
    assert "database" in roles
    assert (
        complexity_of(
            "Build a fullstack dashboard with auth and payments",
            fullstack=True,
            database="sqlite",
        )
        == "complex"
    )


def test_votes_and_tally():
    assert parse_vote("APPROVE\nLooks fine") == "approve"
    assert parse_vote("REVISE\nSplit the API") == "revise"
    votes = {"reviewer": "revise", "tester": "approve", "backend": "revise"}
    assert tally_votes(votes) == "revise"
    assert tally_votes({"a": "approve", "b": "revise"}) == "approve"
    assert "revise" in format_votes(votes)


def test_conflicts_and_priority(tmp_path: Path):
    outputs = {
        "backend": "### FILE: src/db.py\n```\nbackend\n```\n",
        "database": "### FILE: src/db.py\n```\ndatabase\n```\n",
        "tester": "### FILE: test_db.py\n```\nassert True\n```\n",
    }
    owned = {role: file_block_paths(text) for role, text in outputs.items()}
    hits = detect_conflicts(owned)
    assert any("src/db.py" in row for row in hits)
    claimed, conflicts = resolve_writes(outputs)
    assert conflicts
    assert claimed["src/db.py"][0] == "database"
    assert claimed["src/db.py"][1].strip() == "database"
    assert "test_db.py" in claimed
    set_policy(Policy())
    written = apply_resolved(tmp_path, claimed)
    assert "src/db.py" in written
    assert (tmp_path / "src/db.py").read_text(encoding="utf-8").strip() == "database"


def test_route_after_reviewer():
    assert route_after_reviewer({"error": "x"}) == "next"  # type: ignore[arg-type]
    revise = {"review_verdict": "revise", "review_attempts": 0}
    assert route_after_reviewer(revise) == "coder"  # type: ignore[arg-type]
    done = {"review_verdict": "revise", "review_attempts": MAX_REVIEW_ATTEMPTS}
    assert route_after_reviewer(done) == "next"  # type: ignore[arg-type]
    assert route_after_reviewer({"review_verdict": "ok"}) == "next"  # type: ignore[arg-type]


def test_resume_includes_reviewer():
    assert resume_phase("reviewer") == "review"
    assert resume_phase("coder") == "review"
