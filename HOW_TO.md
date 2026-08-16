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

### Resume a run after closing the app

On the input screen, pick a run from **Resume checkpoint** and click **Load checkpoint**. It reads `runs/<id>/run.json` and drops you back into the plan/review/done phase the run last checkpointed at.

### Use past-run lessons

No action needed — every run's outcome is scored, classified win/fail, and appended to `runs/memory.jsonl` by `remember_outcome`. On your next task, matching lessons show up under the sidebar's **Memory** expander and are spliced into the planner's prompt automatically ("Reuse past lessons. Avoid known mistakes.").

### Manage permissions

In the sidebar's **Permissions** section: **Allow writes** gates file writes, **Allow terminal** gates any shell command, **Allow pip** gates `pip install` specifically. Turn any off before approving a plan to run with that capability disabled for the rest of the job.

### Export the finished project

Use the **Download zip** / **Download report** / **Download history** buttons on the results dashboard. The zip contains the whole workspace, including `HEALTH.md`, `QUALITY.md`, and `EVAL.md` if the run produced them.
