# Reference

Dictionary-style reference for `agent-crew`. For the narrative system design, see [ARCHITECTURE.md](ARCHITECTURE.md). For task-oriented recipes, see [HOW_TO.md](HOW_TO.md).

## CLI & run commands

| Command | Does |
| --- | --- |
| `run.cmd` | Windows: creates `.env` from `.env.example` if missing, `uv sync --all-groups`, launches Streamlit headless |
| `./run.sh` | Linux/macOS: same as `run.cmd` |
| `uv run streamlit run streamlit_app.py` | Launch the dashboard directly |
| `uv run agent-crew` | Same app, via the `agent-crew` console script (`src/agent_crew/__init__.py:main`) |
| `uv run pytest` | Run the test suite (coverage on by default, see `pyproject.toml`) |
| `uv run ruff format .` / `uv run ruff check .` | Format / lint |
| `uv run ty check src/` | Type-check |
| `uv run pip-audit .` | Dependency vulnerability scan |
| `make dev` / `make lint` / `make format` / `make test` / `make build` / `make audit` / `make hooks` / `make hooks-install` | Same, via `Makefile` |

## Environment variables

From `.env.example`, loaded by `settings.py` via `python-dotenv`:

| Variable | Provider | Required |
| --- | --- | --- |
| `OPENAI_API_KEY` | OpenAI (or an OpenAI-compatible proxy) | Yes, to use OpenAI |
| `OPENAI_BASE_URL` | OpenAI | Optional, for a custom/proxy endpoint |
| `AGNES_API_KEY` | Agnes AI | Yes, to use Agnes AI |
| `GOOGLE_API_KEY` | Google Gemini | Yes, to use Google |
| `OLLAMA_HOST` | Ollama | Optional, default `http://127.0.0.1:11434` |

## Providers & models

`settings.py`, resolved by `llm.py::make_llm`:

| Provider | Models | Notes |
| --- | --- | --- |
| `ollama` | Live from `GET {OLLAMA_HOST}/api/tags` | No hardcoded list; empty if Ollama isn't running |
| `openai` | `gpt-5.6-luna`, `gpt-5.6-terra` | `reasoning_effort="medium"` always set |
| `agnes` | `agnes-2.5-flash` | OpenAI-compatible wire format at `https://apihub.agnes-ai.com/v1` |
| `google` | `gemini-3.5-flash-lite`, `gemini-3.7-flash` | Routed via `gemini/<model>` |

## Per-run configurable limits

Two of the settings constants below are also per-run overrides, threaded through `initial_state()` / `run_plan()` / `run_autonomous()` as `max_debug_attempts` and `min_coverage`, and exposed in the UI's sidebar **Configuration** expander. `route_after_tester`, `tester_node`, and `quality.py::evaluate_quality` all read `state.get(...)`, falling back to the `settings.py` constant when unset. The rest (`MAX_TEST_REWRITES`, `MAX_REVIEW_ATTEMPTS`, `PERF_BUDGET_S`) are fixed, not exposed as UI overrides.

## Settings constants (`settings.py`)

| Constant | Value | Governs |
| --- | --- | --- |
| `MAX_DEBUG_ATTEMPTS` | 3 | Tester→Debugger loop bound (`route_after_tester`) |
| `MAX_TEST_REWRITES` | 2 | Tester rewrites itself if coverage/levels are missing |
| `MAX_REVIEW_ATTEMPTS` | 1 | Reviewer's revise-loop bound on the coder |
| `MAX_GOAL_CYCLES` | 2 | Default autonomous re-planning budget (overridable per run) |
| `MIN_COVERAGE` | 70.0 | Coverage-floor quality gate |
| `MIN_LOOP_SCORE` | 50 | Score an autonomous run needs to stop early |
| `PERF_BUDGET_S` | 2.0 | Perf-probe quality gate budget |
| `LLM_TIMEOUT_S` | 300 | Per-call timeout on every `LLM(...)` (all four providers) — an LLM call used to have none at all |

## Agent roles (`crew.py::build_agents`)

Every role is a CrewAI `Agent` sharing one `LLM`; `impl` tools can write files, `tests`-scoped tools can write test files, `reviewer` gets read-only tools.

| Role | Job | Tools |
| --- | --- | --- |
| `planner` | Sub-tasks, order, risks, edge cases | none (text only) |
| `coder` | Implement the approved plan | fs (impl) |
| `backend` | Server/API/service files only | fs (impl) |
| `frontend` | UI/client files only | fs (impl) |
| `database` | Schema and data-access files only | fs (impl) |
| `reviewer` | Architecture/coupling pass before tests; first line OK/REVISE | fs (read-only) |
| `tester` | Unit/integration/edge (+optional perf) tests | fs (tests) |
| `debugger` | Fix failing tests/gates with the smallest change | fs (impl) |
| `documenter` | Write the generated project's README + brief comments | fs (tests-scoped) |

## `CrewState` fields (`graph.py`)

The `TypedDict` threaded through every LangGraph node, grouped by concern:

| Group | Fields |
| --- | --- |
| Run identity | `task`, `provider`, `model`, `workspace`, `template`, `feedback` |
| Plan/code/test | `plan`, `plan_approved`, `code`, `tests`, `test_output`, `tests_passed`, `debug_attempts`, `test_rewrites`, `test_levels` |
| Docs & eval | `docs`, `score`, `evaluation`, `reflection`, `health` |
| Quality gates | `coverage`, `gates_ok`, `gate_fail`, `quality` |
| Stack detection | `stack`, `language`, `framework`, `database`, `fullstack`, `practices`, `complexity` |
| Collaboration | `roster`, `votes`, `conflicts`, `review`, `review_verdict`, `review_attempts`, `inbox` |
| Autonomy | `autonomous`, `goal_cycles`, `max_goal_cycles`, `subtasks`, `deps`, `rollback` |
| Permissions | `dry_run`, `allow_write`, `allow_terminal`, `allow_pip`, `locked` |
| Bookkeeping | `log`, `current_agent`, `current_file`, `error`, `diff`, `analysis`, `checkpoint` |

## Graph entrypoints (`graph.py`)

| Function | Runs | Stops for approval? |
| --- | --- | --- |
| `run_plan(...)` | `planner` only | Returns after planning; caller shows the plan |
| `stream_code(state)` | `coder` → `reviewer` (with revise loop) | Caller reviews the diff after |
| `stream_verify(state)` | `tester` → `debugger`/`documenter` → `evaluate` | Runs to completion |
| `stream_build(state)` | `stream_code` then `stream_verify` | Runs to completion |
| `run_build(state)` | Same as `stream_build`, non-streaming | Runs to completion |
| `run_autonomous(...)` / `stream_auto(state)` | Full loop: `planner→coder→reviewer→tester→debugger→documenter→evaluate`, looping back to `planner` per `route_after_evaluate` | No pauses — set `autonomous=True` internally |
| `run_crew(...)` | `run_plan` then `run_build` | No pauses |
| `resume_phase(checkpoint)` | — | Maps a saved `checkpoint` node name to a UI phase (`"plan"`/`"review"`/`"done"`) |

## Templates (`templates.py::TEMPLATES`)

`apply_template(workspace, name)` writes only files that don't already exist.

| Name | Scaffolds |
| --- | --- |
| `blank` | Nothing |
| `library` | `src/pkg/{__init__,core}.py`, `tests/test_core.py` |
| `cli` | `src/app/{__init__,__main__}.py`, `tests/test_main.py` |
| `fastapi` | `src/api/{__init__,main}.py`, `tests/test_health.py` |
| `flask` | `src/app.py`, `tests/test_health.py` |
| `django` | `app/{views,models,urls}.py`, `tests/test_views.py` |
| `streamlit` | `app.py`, `tests/test_app.py` |
| `datascience` | `src/analysis.py`, `tests/test_analysis.py` |
| `express` | `src/health.js`, `src/health.test.js`, `package.json` |
| `react` | `frontend/src/{lib.js,lib.test.js,App.jsx}`, `package.json` |
| `nextjs` | `app/page.js`, `lib/{health.js,health.test.js}`, `package.json` |
| `fullstack` | `backend/{__init__,main}.py`, `tests/test_health.py`, `frontend/src/{lib.js,lib.test.js}`, `package.json` |

## Database overlays (`templates.py::DATABASES`)

`apply_database(workspace, name)`, same write-if-missing rule.

| Name | Scaffolds |
| --- | --- |
| `none` | Nothing |
| `sqlite` | `db.py` (sqlite3, `connect`/`add_item`), `tests/test_db.py` |
| `sqlalchemy` | Same `db.py` shape, commented for a real SQLAlchemy swap; tests stay dep-free |
| `postgres` | `db.py` reads `DATABASE_URL` (default sqlite), same test shape |
| `prisma` | `prisma/schema.prisma`, `src/db.js` (in-memory stub), `src/db.test.js` |

## Permissions (`policy.py::Policy`)

Frozen dataclass, set once per run via `set_policy`, read via `get_policy()`:

| Field | Default | Effect |
| --- | --- | --- |
| `dry_run` | `False` | Every mutation point returns a plan string instead of executing |
| `allow_write` | `True` | Gates `apply_files`/`run_python`/file writes |
| `allow_terminal` | `True` | Gates `run_terminal` (shell.py) |
| `allow_pip` | `True` | Gates `pip install` specifically |
| `locked` | `()` | Comma-separated globs; `is_locked()` refuses writes matching path or filename |

## Shell allowlist (`shell.py::build_command`)

Only these command heads are allowed; everything else raises `ValueError`. Unsafe characters (`;|&`$<>` and newline) are refused outright, as are `rm/del/curl/wget/ssh/powershell/cmd/format`.

| Head | Allowed forms |
| --- | --- |
| `python` / `python3` / `py` | a single `.py` file (path-jailed), `-m pytest`, `-m pip install <pkgs>`, `-m ruff check`, `-m ty check` |
| `pip` | `install <pkgs>` only, no flags; installs `--target <workspace>/.vendor` (picked up via `PYTHONPATH`, no venv needed) |
| `git` | `status`, `diff`, `log`, `branch` (read-only passthrough) |
| `pytest` | any args |
| `node` | a single `.js` file, or `--test` |

## Export artifacts

| File | Written by | Contains |
| --- | --- | --- |
| `REPORT.md` | `workspace.py::write_report` | Run summary + file list + trace |
| `HISTORY.md` | `workspace.py::write_history` | Conversation/decision history |
| `HEALTH.md` | `autonomy.py::write_health` | Goal cycles, gates, score, roster, subtasks, deps, rollback state |
| `QUALITY.md` | `quality.py::write_quality` | Gate-by-gate quality report |
| `EVAL.md` | `graph.py::evaluate_node` | Score /100 + suggestions + model review |
| `crew-project.zip` | `workspace.py::zip_workspace` | Whole workspace dir, download button in the UI |
| `requirements.txt` | `autonomy.py::install_deps` | Auto-detected third-party imports, merged in |
| `terminal.log` | `tools.py::RunTerminalTool` (via `workspace.py::append_terminal_log`) | Every agent-run terminal command + result, in order; rendered in the dashboard's Terminal tab |
| `run.json` | `workspace.py::save_run` | Full `CrewState` snapshot after every node; powers checkpoint resume and refresh recovery |

## Token usage (`crew.py`)

`reset_usage()` / `get_usage()` / `_add_usage(usage)` wrap a `ContextVar` (same pattern as `policy.py`'s `Policy`), so usage accumulates across an entire run — including every autonomous re-planning cycle — without threading a new field through `CrewState`. `run_role` calls `_add_usage` with `CrewOutput.token_usage` (a `crewai.types.usage_metrics.UsageMetrics`) after every `crew.kickoff()`. `initial_state()` calls `reset_usage()` once per new run. No dollar-cost estimate is computed — this project doesn't ship a pricing table for its models.

## App-wide logging (`logging_setup.py`)

`configure_logging()` sets up a `RotatingFileHandler` on the `"agent_crew"` logger, writing to `runs/agent-crew.log` (2MB × 3 backups). Idempotent (checks `logger.handlers` before adding another). Called once at Streamlit startup and wired into `_stream()`'s exception handler (`graph.py`) and `safe_role`'s fallback path (`reliability.py`), so pipeline errors and role-call fallbacks are recorded app-wide, not just in a run's own `crew.log`. Survives both `delete_workspace` (single run) and `reset_all_runs` (everything) — the latter explicitly skips any `agent-crew.log*` file rather than trying to delete an open file handle (a `PermissionError` on Windows).

## Process/file hardening (`workspace.py`)

| Function | Does |
| --- | --- |
| `run_subprocess(argv, cwd=, timeout=, env=)` | Shared `subprocess.run`-alike used by every terminal/test/git call site. On timeout, kills the whole process tree — not just the direct child — via `taskkill /F /T` on Windows or `killpg(SIGKILL)` on POSIX (a bare `.kill()` only kills the direct child; a `pip install` triggering a native build, or a test spawning a worker, would otherwise survive) |
| `_write_raw(workspace, relative, content)` | Every file write in the app (generated project files, `run.json`, `REPORT.md`, ...) goes through this. Writes to a unique temp file in the same directory, then `Path.replace()` — atomic on both platforms, so a crash or a concurrent writer to the same path can never leave a truncated/corrupt file |

`memory.py::load_memory` skips (and logs) individually malformed `memory.jsonl` lines instead of raising — one corrupted line no longer breaks every future recall. `streamlit_app.py`'s two `load_run()` call sites (manual "Load checkpoint" and refresh-recovery) both catch `OSError`/`ValueError` instead of crashing the script on a missing/corrupt `run.json`.

## Environment / cleanup (`workspace.py`)

| Function | Does |
| --- | --- |
| `delete_workspace(workspace)` | `shutil.rmtree` on one run's directory |
| `reset_all_runs(root=RUNS_DIR)` | Deletes every entry under `root` except `agent-crew.log*`; returns the count removed |

Both are wired to the dashboard's **Clean project** and the sidebar's **Reset environment**, each behind an arm-then-confirm button pair (not a checkbox bound to `session_state` — Streamlit forbids reassigning a widget-bound key after that widget has rendered in the same script run).

## Module index

| Module | Job |
| --- | --- |
| `src/agent_crew/crew.py` | CrewAI roles and `### FILE:` format |
| `src/agent_crew/graph.py` | LangGraph nodes, routing, entrypoints |
| `src/agent_crew/llm.py` | Provider factory |
| `src/agent_crew/workspace.py` | Apply files, run pytest/node, path jail, git, report/history, zip export |
| `src/agent_crew/policy.py` | Dry-run, permission flags, locked globs |
| `src/agent_crew/shell.py` | Allowlisted sandboxed exec: python/pip/pytest/node/git |
| `src/agent_crew/tools.py` | CrewAI `BaseTool` wrappers over fs/quality/search/terminal |
| `src/agent_crew/templates.py` | Project stubs and database overlays |
| `src/agent_crew/stack.py` | Detect language, framework, database; inject practices |
| `src/agent_crew/quality.py` | Gates, test levels, lint, types, security, perf |
| `src/agent_crew/collab.py` | Roster, votes, parallel run, conflict merge |
| `src/agent_crew/autonomy.py` | Sub-task tracking, missing-dep auto-install, `HEALTH.md` report |
| `src/agent_crew/codeintel.py` | Cached project summary, code/semantic search, symbol rename, traceback blame |
| `src/agent_crew/memory.py` | JSONL memory store: recall past outcomes, record win/fail lessons |
| `src/agent_crew/reliability.py` | Role-call retry/backoff, fallback plan, heuristic scoring |
| `src/agent_crew/logging_setup.py` | App-wide rotating log (`runs/agent-crew.log`) |
| `src/agent_crew/settings.py` | Providers, models, tunable constants |
| `streamlit_app.py` | Dashboard UI |
