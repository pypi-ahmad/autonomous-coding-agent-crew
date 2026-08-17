# How to use agent-crew

Everything here assumes you're running the Streamlit dashboard. For a dictionary of every field/function, see [REFERENCE.md](REFERENCE.md). For system design, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Part A — Your first run (tutorial)

1. **Install.** You need [uv](https://docs.astral.sh/uv/) and Python 3.12.

   ```bash
   git clone https://github.com/pypi-ahmad/autonomous-coding-agent-crew.git
   cd autonomous-coding-agent-crew
   ```

2. **Launch.** On Windows, double-click `run.cmd`; on Linux/macOS, run `./run.sh` — either creates `.env` from `.env.example` if missing, runs `uv sync --all-groups`, and starts the app. Or, on any OS, run it directly:

   ```bash
   uv sync --all-groups
   uv run streamlit run streamlit_app.py
   ```

3. **Pick a provider and model.** In the sidebar, toggle **Fully local (Ollama only)** if you don't want to touch API keys — Ollama's model list is read live from your local daemon. Otherwise pick OpenAI, Agnes AI, or Google and pick a model from the dropdown.

   > [!TIP]
   > No API key, no cost: install [Ollama](https://ollama.com/), `ollama pull <model>`, leave `.env` empty, and toggle "Fully local".

4. **Describe the task.** In the main form, type a coding task — a specific ask ("add a function that...") or a high-level goal ("build a todo API"). Optionally pick a **Stack template** and **Database**, or point **Existing project folder** at a folder on disk to work on it instead of starting blank. Click **Plan**.

5. **Approve the plan.** Read the planner's output. Add feedback in the text box if you want changes, then click **Approve plan** (or **Reject plan** to go back and retype the task).

6. **Review the diff.** Once the coder (and reviewer) finish, you land on a git diff of what changed. Add feedback if you want another pass, then click **Resume tests** — or **Stop here** to end the run as-is.

7. **Read the result.** The dashboard shows test/coverage/score/gate status, an activity feed, an execution timeline, a file tree with a syntax-highlighted viewer, the diff, and tabs for tests/report/history/plan/docs. Download the project as a zip, or the `REPORT.md`/`HISTORY.md`.

## Part B — Recipes

### Scaffold a project from a template

Pick one of the 12 templates in **Stack template** (`blank`, `library`, `cli`, `fastapi`, `flask`, `django`, `streamlit`, `datascience`, `express`, `react`, `nextjs`, `fullstack`), then either:

- Click **Start from template** for an instant, no-LLM scaffold — the files land in a fresh `runs/<id>/` and you're dropped straight on the results dashboard to browse/download them.
- Or type a task and click **Plan** as usual, if you want the crew to build on top of the scaffold.

The template only writes files that don't already exist, so it's safe to combine with an existing folder, and agents can freely edit/replace any scaffolded file afterward (nothing is template-locked unless you lock it yourself, see below). Full file list per template: [REFERENCE.md → Templates](REFERENCE.md#templates-templatespytemplates).

### Add a database overlay

Pick one of `sqlite`, `sqlalchemy`, `postgres`, `prisma` in the **Database** dropdown alongside a template. It scaffolds a `db.py` (or `prisma/schema.prisma` + `src/db.js`) and a matching test — see [REFERENCE.md → Database overlays](REFERENCE.md#database-overlays-templatespydatabases).

### Work on an existing project instead of starting blank

Fill in **Existing project folder** with an absolute path before clicking **Plan**. It's copied into `runs/<id>/`, skipping `.venv` and `.git`. The planner detects the stack and proposes a smallest-diff feature add instead of a full tree.

### Preview without changing anything (dry-run)

Toggle **Dry-run** in the sidebar before approving the plan. Every write, terminal command, and pip install returns a plan string instead of executing — safe to see what would happen first.

### Stop agents from touching specific files

In **Locked files**, enter comma-separated globs (e.g. `README.md, tests/*, *.toml`). Any write matching a locked path or filename is refused, on top of the path jail that already blocks writes outside the job workspace.

### Turn on autonomous mode

Toggle **Autonomous (no pauses)** in the sidebar's Autonomy section before submitting the task. Instead of pausing for plan approval and diff review, the crew runs planner → coder → reviewer → tester → debugger → documenter → evaluate on a loop, re-planning with any leftover sub-tasks until the score/gates pass or the **Goal cycle budget** (default 2, max 20) is used up. Good for a well-scoped goal you're willing to let run unattended; bad if you want to steer mid-run — for that, leave autonomous mode off.

While it's running, a **Stop** button ends the loop cleanly after the current step and takes you straight to the results dashboard with whatever's done so far — nothing is lost, the workspace and its `run.json` checkpoint are on disk either way.

### Track token usage

Every LLM call's token usage is tallied automatically — no setup needed. Watch it live under the current-step caption while a run streams, or check the **Tokens** metric on the results dashboard once it's done. This works for every provider, including Ollama; there's no dollar-cost estimate since this project doesn't ship pricing tables for its models.

### Read what agents ran in the terminal

Every `run_terminal` call an agent makes (pip installs, pytest, git, node) is logged to a **Terminal** tab on the results dashboard, in the order it happened — separate from the Tests tab, which only shows the tester's own pytest output.

### Resume a run after closing the app, or recover from a refresh

On the input screen, pick a run from **Resume checkpoint** and click **Load checkpoint**. It reads `runs/<id>/run.json` and drops you back into the plan/review/done phase the run last checkpointed at.

A browser refresh recovers automatically instead: the current run's id lives in the page URL (`?run=<id>`), so reloading the page re-opens the same run at its last checkpoint without you picking anything. An autonomous run's *loop* can't resume mid-stream after a refresh (the in-flight generator is gone), but nothing is lost — you land on the last checkpoint and can continue manually from there, same as any other run.

### Use past-run lessons

No action needed — every run's outcome is scored, classified win/fail, and appended to `runs/memory.jsonl` by `remember_outcome`. On your next task, matching lessons show up under the sidebar's **Memory** expander and are spliced into the planner's prompt automatically ("Reuse past lessons. Avoid known mistakes.").

### Manage permissions

In the sidebar's **Permissions** section: **Allow writes** gates file writes, **Allow terminal** gates any shell command, **Allow pip** gates `pip install` specifically. Turn any off before approving a plan to run with that capability disabled for the rest of the job.

### Tune safety limits per run

Open the sidebar's **Configuration** expander before submitting a task. **Max debug attempts** overrides how many tester-fail → debugger loops a run gets before it fails closed and rolls back (default 3). **Coverage floor %** overrides the quality gate's minimum coverage (default 70%) — lower it for a quick prototype, raise it for something you want held to a stricter bar.

### Clean up a run, or reset everything

On the results dashboard, **Clean project** deletes that run's workspace from disk — click it once to arm, then **Confirm delete?** (or **Cancel**). In the sidebar's **Environment** expander, **Reset environment** does the same for every run under `runs/`, including saved memory — same arm/confirm flow. Both keep the rotating `agent-crew.log`.

### If a run seems stuck

Every LLM call has a 5-minute timeout (`LLM_TIMEOUT_S` in `settings.py`) — if a provider stalls or Ollama hangs, the current step fails and the retry/fallback logic in `safe_role` takes over instead of the whole run hanging forever. Terminal commands, tests, and git calls are bounded too, and a timeout kills the whole process tree (not just the direct process), so a stuck `pip install` build or test worker can't linger in the background.

### Where to look when something goes wrong

Every run's own artifacts (`crew.log`, `terminal.log`, `trace.jsonl`, `run.json`) live in that run's `runs/<id>/` folder. For app-wide issues — a retry that fell back, an exception in the LangGraph pipeline itself — check `runs/agent-crew.log`, a rotating log (2MB × 3 backups) that persists across runs and is explicitly kept by both Clean project and Reset environment.

### Export the finished project

Use the **Download zip** / **Download report** / **Download history** buttons on the results dashboard. The zip contains the whole workspace, including `HEALTH.md`, `QUALITY.md`, and `EVAL.md` if the run produced them.
