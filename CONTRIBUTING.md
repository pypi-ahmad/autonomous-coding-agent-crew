# Contributing

Thanks for looking at Autonomous Coding Agent Crew. Bug reports, feature ideas, and pull requests are all welcome — this is a free, community-driven, local-first project.

## Report a bug

Open an [issue](.github/ISSUE_TEMPLATE/bug_report.md) with: steps to reproduce, expected vs. actual behavior, your OS (Windows/Linux), the provider/model you used, and any relevant log output from `runs/<id>/`.

## Suggest a feature

Open a [feature request](.github/ISSUE_TEMPLATE/feature_request.md) describing the problem it solves, not just the feature itself.

## Development setup

Needs [uv](https://docs.astral.sh/uv/) and Python 3.12.

```bash
git clone https://github.com/pypi-ahmad/autonomous-coding-agent-crew.git
cd autonomous-coding-agent-crew
uv sync --all-groups
copy .env.example .env   # Windows; cp on Linux
```

Run the app:

```bash
uv run streamlit run streamlit_app.py
```

Before opening a PR:

```bash
uv run ruff format .
uv run ruff check .
uv run ty check src/
uv run pytest
```

Or `make lint test` (see `Makefile`).

## Code style

- Formatting/linting: `ruff` (config in `pyproject.toml`, `select = ["ALL"]` with explicit ignores).
- Types: `ty`.
- Tests: `pytest`, under `tests/`. New behavior gets a test.
- Keep changes scoped — one concern per PR.

## Pull requests

Use the [PR template](.github/PULL_REQUEST_TEMPLATE.md). Link the issue it closes, if any. CI (`.github/workflows/ci.yml`) runs format, lint, types, tests, and `pip-audit` — keep it green.

## Project layout

See the module table in [README.md](README.md#how-it-works) and [ARCHITECTURE.md](ARCHITECTURE.md) for how the pieces fit together.
