# Runbook: Autonomous Coding Agent Crew

Operational reference. For system design see [ARCHITECTURE.md](../ARCHITECTURE.md). For first-run setup see [HOW_TO.md](../HOW_TO.md).

## Start

**Windows**

```bat
run.cmd
```

Does: checks for `uv` on `PATH`, copies `.env.example` to `.env` if absent, runs `uv sync --all-groups`, then launches Streamlit on the default port (8501). Press any key when prompted to exit.

**Linux / macOS**

```bash
./run.sh
```

Same steps as `run.cmd`. Requires `chmod +x run.sh` on first use.

**Manual (any OS)**

```bash
uv sync --all-groups
uv run streamlit run streamlit_app.py
```

The app opens at `http://localhost:8501` by default.

## Stop

Press **Ctrl+C** in the terminal where Streamlit is running. Runs in progress are checkpointed to `runs/<id>/run.json` after every LangGraph node, so they can be resumed from the sidebar.

## Logs

| Log | Path | Notes |
| --- | --- | --- |
| App-wide rotating log | `runs/agent-crew.log` | 2 MB per file, 3 backups (`agent-crew.log.1`, `.2`, `.3`). Survives "Reset environment". |
| Per-run decisions | `runs/<id>/crew.log` | One line per agent decision, appended. |
| Terminal commands | `runs/<id>/terminal.log` | Records every `run_terminal` call and its output. |
| Decision trace | `runs/<id>/trace.jsonl` | One JSON object per line: `{agent, decision, file, detail}`. |
| Quality report | `runs/<id>/QUALITY.md` | Written by the tester node after every gate evaluation. |
| Run state | `runs/<id>/run.json` | Full `CrewState` serialised after every node; used for checkpoint resume. |

## Common failures

### "uv is not on PATH"

`uv` is not installed. Install it from [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/) and rerun.

### "Missing environment variable: OPENAI_API_KEY" (or AGNES_API_KEY / GOOGLE_API_KEY)

The `.env` file is missing the key for the selected provider. Either fill it in `.env` or switch to Ollama in the sidebar (no key needed).

### "No Ollama models found. Is Ollama running?"

The Ollama daemon is not running, or `OLLAMA_HOST` is wrong. Start Ollama (`ollama serve`) and ensure it is reachable at the configured host (default `http://127.0.0.1:11434`).

### "Command timeout after 300s"

An LLM call stalled (timeout is `LLM_TIMEOUT_S = 300` in `settings.py`). The `safe_role` wrapper will return the fallback string and log a warning to `runs/agent-crew.log`. The run continues with degraded output for that role.

### "Command timeout after 90s" (in test output)

A pytest or node test suite hung. The whole process tree is killed (including native builds triggered by `pip install`). Check `runs/<id>/terminal.log` for the last command.

### "Command timeout after 120s" (in terminal output)

A `run_terminal` command (e.g. `pip install`) took too long. Same tree-kill applies.

### "git not found"

`git` is not on `PATH`. Git integration (`git_init`, `git_commit`, `git_savepoint`, `git_rollback`) silently degrades: files are still written, but no commits are made and rollback is unavailable.

### "node not found; skipped JS tests"

`node` is not on `PATH`. JavaScript tests are skipped; Python tests still run.

### Checkpoint resume fails / "run.json" errors

If a run was interrupted mid-write, `run.json` may be corrupt. Delete the affected run directory (`runs/<id>/`) and start a new run. The `_write_raw` atomic-write primitive (introduced to prevent this) means it should only happen if the process was hard-killed during the temp-file rename step.

### "pip disabled by policy" / "Writes disabled by policy"

The **Allow pip**, **Allow writes**, or **Allow terminal** toggle is off in the Streamlit sidebar. Enable the relevant permission and retry.

### "No green savepoint" (in rollback output)

No `chore: green` commit exists in the run's git history. Either the run never passed quality gates, or git is unavailable. Files are still in whatever state the last agent left them.

## Reset

| Action | What it does |
| --- | --- |
| **Clean project** (sidebar) | Deletes all `runs/` subdirectories except the rotating log files. |
| **Reset environment** (sidebar) | Runs `uv sync --all-groups` again to rebuild the `.venv`. Does not delete run data. |
| Manual: delete a run | `rm -rf runs/<id>/` (or equivalent). Safe at any time; runs are isolated directories. |

## Environment variables

All variables are read from `.env` at repo root via `python-dotenv`. None are required if using Ollama.

| Variable | Required for | Default |
| --- | --- | --- |
| `OPENAI_API_KEY` | OpenAI provider | (none) |
| `OPENAI_BASE_URL` | OpenAI-compatible endpoint override | (none) |
| `AGNES_API_KEY` | Agnes AI provider | (none) |
| `GOOGLE_API_KEY` | Google provider | (none) |
| `OLLAMA_HOST` | Ollama (non-default host) | `http://127.0.0.1:11434` |

## Ports and external calls

| Destination | When | Notes |
| --- | --- | --- |
| Ollama (`OLLAMA_HOST/api/tags`) | Provider selection, model listing | 3-second timeout; failure returns empty list silently |
| OpenAI / Agnes AI / Google APIs | Any non-Ollama LLM call | Via CrewAI `LLM`; 300-second timeout per call |
| Local `git` | After every coder pass and quality gate | CLI via `subprocess`; not required for basic operation |

No inbound ports beyond Streamlit's own server. No data leaves the machine except LLM API calls.
