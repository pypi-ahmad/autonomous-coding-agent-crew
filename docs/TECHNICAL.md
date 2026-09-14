# Technical reference: Autonomous Coding Agent Crew

Stack decisions and invariants. For the full system design and C4 diagrams see [ARCHITECTURE.md](../ARCHITECTURE.md). For the API/module dictionary see [REFERENCE.md](../REFERENCE.md).

## Stack

| Component | Version | Role |
| --- | --- | --- |
| Python | 3.12 (pinned in `.python-version`) | Runtime |
| uv | ≥0.11.29 (build backend) | Package manager, lockfile, venv |
| CrewAI | ≥0.80 | One agent + one task per role call |
| LangGraph | ≥0.4 | Control-flow state machine; owns routing and the debug loop |
| Streamlit | ≥1.57 | UI and session state |
| python-dotenv | ≥1.2.2 | `.env` loading at import time (`settings.py`) |
| Ruff | ≥0.16.3 (dev) | Lint and format; `select = ["ALL"]` with explicit ignores |
| ty | ≥0.0.72 (dev) | Type checking; lenient on CrewAI/LangGraph stub gaps |
| pytest + pytest-cov | ≥9.1.1 / ≥7.1.0 (dev) | Test runner with branch coverage |
| pip-audit | ≥2.9.0 (dev) | Advisory vulnerability scan |

No Docker, no database server, no message broker. Every feature added since the initial release is first-party code in `src/agent_crew/`; the runtime dependency list has not grown.

## Key invariants

### All file writes are atomic

Every path that writes a project file or `run.json` goes through `workspace._write_raw`. It writes to a `tempfile.mkstemp` file in the same directory then calls `Path.replace()`, which is atomic on both Windows (same volume) and POSIX. A crash or concurrent write to the same path leaves the previous version intact rather than a truncated file.

Any new code that writes to the workspace must go through `write_file` or `_write_raw`, not a bare `open()` call.

### All subprocess calls kill the whole process tree on timeout

`workspace.run_subprocess` is the single subprocess entry point. On timeout it calls `_kill_tree`, which uses `taskkill /F /T /PID` on Windows and `os.killpg(SIGKILL)` on POSIX. The child is launched with `CREATE_NEW_PROCESS_GROUP` (Windows) or `start_new_session=True` (POSIX) so the group/session can be targeted. Without this, a `pip install` that triggers a native compile step would survive a plain `proc.kill()`.

### Policy is a ContextVar

`policy.Policy` is stored in a `ContextVar`. `graph.py` calls `set_policy(policy_from_state(state))` at the start of every node (`_bind`). `collab.run_parallel` uses `copy_context()` before submitting each thread so the policy propagates to parallel roles correctly.

### Token usage is a ContextVar

`crew._USAGE` accumulates `total_tokens`/`prompt_tokens`/`completion_tokens`/`successful_requests` across all role calls in a run. It is reset once per run via `reset_usage()` in `initial_state`. Parallel roles in `collab.run_parallel` share the same context copy and therefore the same accumulator.

### Quality gates run in fixed priority order

`quality.evaluate_quality` checks: tests → missing test levels → coverage floor → lint → types → security → perf. The first failing check sets `Quality.fail` and stops the sequence. `route_after_tester` reads `gate_fail` to decide the next node; the debugger is given the specific gate that failed.

The coverage floor (`min_coverage`, default 70.0) is per-run overridable via `CrewState["min_coverage"]`.

### Rollback requires a prior green savepoint

`workspace.git_rollback` finds the most recent commit whose message contains `"chore: green"` and runs `git reset --hard` to it. If no such commit exists (the run never passed all gates), it returns `"no green savepoint"` and leaves files as they are.

### `apply_files` trusts the LLM output path

`workspace.apply_files` writes every `### FILE: <path>` block it finds in an LLM response. Path traversal is blocked by `safe_file` (resolves and checks `is_relative_to`), but the file content is written verbatim. The `protect_tests=True` flag prevents overwriting test files; implementors should pass it for all non-tester roles.

### `analyze_project` result is LRU-cached by file mtime

`codeintel._analyze_cached` is decorated with `@lru_cache(maxsize=32)` keyed on `(workspace_root, tuple_of_(rel, mtime_ns))`. The cache is invalidated when any file's mtime changes. It is valid within a single Python process lifetime only; a restart clears it.

### Memory is append-only JSONL; malformed lines are skipped

`memory.remember` appends one JSON object per outcome to `runs/memory.jsonl`. `load_memory` reads the file line by line, skipping (and logging) any line that fails `json.loads`. A single corrupt line does not break future recall. The file is never compacted or truncated by first-party code.

### The shell allowlist is enforced before subprocess execution

`shell.build_command` parses the command with `shlex.split`, rejects shell metacharacters (`; | & \` $ < > \n`), and maps the head token to a specific `sys.executable`/binary. Anything not on the allowlist raises `ValueError`. `run_terminal` calls `build_command` before `run_subprocess`.

## Error handling

| Site | Behaviour |
| --- | --- |
| `reliability.run_role_retry` | Retries 3 times with exponential backoff (0.5 s, 1 s, 2 s). Re-raises the last exception on exhaustion. |
| `reliability.safe_role` | Wraps `run_role_retry`; on any exception returns `(fallback_string, error_string)` and logs a warning to `runs/agent-crew.log`. The caller decides whether to treat a non-empty error string as fatal. |
| `graph._stream` | Wraps `graph.stream(...)` in a generator. Any exception from a node sets `state["error"]` and yields it rather than propagating, so a node-level failure degrades to a visible error message in the Streamlit UI instead of crashing the script. |
| `workspace.load_memory` | Skips malformed JSONL lines with a log warning instead of raising. |
| `workspace.reset_all_runs` | Skips files/directories it cannot delete (e.g. a locked log file on Windows) and continues rather than raising. |
| `llm.list_ollama_models` | Catches all network/JSON errors and returns `[]`, so the UI still renders when Ollama is not running. |

## Persistence paths

| Path | Format | Written by | Read by |
| --- | --- | --- | --- |
| `runs/<8-hex>/` | Directory | `initial_state` | all nodes |
| `runs/<id>/run.json` | JSON (`CrewState`) | `_stream` after every node | `workspace.load_run` (checkpoint resume) |
| `runs/<id>/trace.jsonl` | JSONL; one `{agent, decision, file, detail}` per line | `_append` | `workspace.read_trace` |
| `runs/<id>/crew.log` | Plain text, one line per event | `workspace.append_crew_log` | Streamlit UI |
| `runs/<id>/terminal.log` | `$ cmd\n[ok/failed]\noutput\n\n` blocks | `workspace.append_terminal_log` | Streamlit UI |
| `runs/<id>/QUALITY.md` | Markdown | `quality.write_quality` | Streamlit UI |
| `runs/<id>/REPORT.md` | Markdown | `workspace.write_report` | Streamlit export |
| `runs/<id>/HISTORY.md` | Markdown | `workspace.write_history` | Streamlit export |
| `runs/<id>/HEALTH.md` | Markdown | `autonomy.write_health` | Streamlit export |
| `runs/<id>/EVAL.md` | Markdown | `evaluate_node` | Streamlit UI |
| `runs/<id>/CONFLICTS.md` | Markdown | `collab.write_conflicts` | Reference only |
| `runs/<id>/REPRO.md` | Markdown | `workspace.write_repro` | Reference only |
| `runs/<id>/.vendor/` | pip `--target` directory | `shell._pip_command` | `_sandbox_env` (`PYTHONPATH`) |
| `runs/memory.jsonl` | JSONL; one outcome record per line | `memory.remember` | `memory.recall` (planner prompt) |
| `runs/agent-crew.log` | Rotating text log (2 MB × 3) | `logging_setup` | Tail or IDE |
| `.env` | KEY=VALUE | user | `settings.py` via `load_dotenv` at import time |

## Module responsibility map

| Module | Responsible for | Must not |
| --- | --- | --- |
| `settings.py` | Constants and env-var accessors; loaded once at import | Call LLM, write files, import first-party modules |
| `logging_setup.py` | App-wide rotating file handler | Import UI or graph modules |
| `policy.py` | ContextVar-based permission flags; `is_locked` glob matching | Any I/O |
| `llm.py` | Provider-specific `LLM` factory; Ollama model listing | Write files, own process state |
| `workspace.py` | All file I/O, subprocess execution, git CLI, log helpers | Import CrewAI, LangGraph, or Streamlit |
| `shell.py` | Allowlist parser for `run_terminal`; `build_command` | Bypass `safe_file` or `run_subprocess` |
| `tools.py` | CrewAI `BaseTool` wrappers for workspace operations | Contain domain logic |
| `stack.py` | Stack detection and per-framework practices | Write files |
| `templates.py` | Static scaffolding for blank projects | Detect stack or call LLM |
| `memory.py` | Append-only JSONL memory; token-overlap recall | Write to any path other than `runs/memory.jsonl` |
| `quality.py` | Five gate evaluations; `Quality` dataclass; `QUALITY.md` | Launch processes outside `run_subprocess` |
| `reliability.py` | Retry/backoff wrapper; `heuristic_score`; fallback plan | Own retry state between runs |
| `crew.py` | Agent definitions; `run_role`; token-usage ContextVar | Own control flow or file writes |
| `collab.py` | Parallel role execution; vote tallying; conflict resolution | Merge file content |
| `codeintel.py` | AST/regex code analysis; `analyze_project` (LRU-cached); `blamed_snapshot` | Write files |
| `autonomy.py` | Subtask parsing; `install_deps`; `HEALTH.md`; plan-iteration helpers | Make LLM calls |
| `graph.py` | LangGraph builders; `CrewState`; all node functions; `initial_state`; `run_plan`/`run_autonomous` | Import Streamlit |
| `__init__.py` | `main()` entry point; launches Streamlit via subprocess | Contain logic |
