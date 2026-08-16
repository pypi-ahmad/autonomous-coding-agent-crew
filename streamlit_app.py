from __future__ import annotations

from pathlib import Path

import streamlit as st

from agent_crew.graph import resume_phase, run_autonomous, run_plan, stream_code, stream_verify
from agent_crew.llm import models_for, validate_selection
from agent_crew.memory import format_lessons, recall, remember
from agent_crew.policy import Policy
from agent_crew.settings import MAX_GOAL_CYCLES, active_providers
from agent_crew.templates import DATABASE_NAMES, TEMPLATE_NAMES
from agent_crew.workspace import (
    file_tree,
    list_files,
    list_runs,
    load_run,
    parse_pytest_counts,
    read_file,
    read_trace,
    render_history,
    render_report,
    zip_workspace,
)

LANG = {
    ".py": "python",
    ".md": "markdown",
    ".toml": "toml",
    ".json": "json",
    ".txt": "text",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".prisma": "text",
}

st.set_page_config(page_title="Agent crew", page_icon=":material/terminal:", layout="wide")
st.session_state.setdefault("result", None)
st.session_state.setdefault("error", None)
st.session_state.setdefault("phase", "input")
st.session_state.setdefault("draft", None)

st.title("Autonomous coding agent crew")
st.caption("Phase 9. Parallel specialists, reviewer, votes, conflict merge.")


@st.cache_data(ttl="30s", max_entries=8)
def cached_models(provider: str) -> list[str]:
    return models_for(provider)


def policy_from_ui() -> Policy:
    locked = tuple(
        part.strip() for part in str(st.session_state.get("locked", "")).split(",") if part.strip()
    )
    return Policy(
        dry_run=bool(st.session_state.get("dry_run", False)),
        allow_write=bool(st.session_state.get("allow_write", True)),
        allow_terminal=bool(st.session_state.get("allow_terminal", True)),
        allow_pip=bool(st.session_state.get("allow_pip", True)),
        locked=locked,
    )


def pump(events: object, status: object, live_file: object) -> dict:
    merged = st.session_state.draft
    for node, _update, merged in events:
        agent = merged.get("current_agent") or node
        current = merged.get("current_file") or "—"
        live_file.caption(f"Current: {agent} · {current}")
        if merged.get("log"):
            status.write(merged["log"][-1])
        st.session_state.draft = merged
    return merged


def show_feed(result: dict) -> None:
    for line in result.get("log") or []:
        agent = "crew"
        for name in ("planner", "coder", "tester", "debugger", "documenter", "evaluate"):
            if name in line.lower():
                agent = name
                break
        st.chat_message(agent).write(line)


def show_tree(workspace: Path) -> None:
    tree = file_tree(workspace)
    st.code(tree, language="text")
    names = list_files(workspace)
    if not names:
        st.caption("Workspace empty.")
        return
    pick = st.selectbox("Open file", names, key=f"tree_{workspace.name}")
    suffix = Path(pick).suffix.lower()
    st.code(read_file(workspace, pick), language=LANG.get(suffix, "text"))


def show_dashboard(result: dict) -> None:
    workspace = Path(result["workspace"])
    names = list_files(workspace) if workspace.is_dir() else []
    cover = result.get("coverage", -1)
    cover_label = f"{cover:.0f}%" if isinstance(cover, int | float) and cover >= 0 else "n/a"
    counts = parse_pytest_counts(result.get("test_output") or "")
    with st.container(horizontal=True):
        st.metric("Tests", "passed" if result.get("tests_passed") else "failed", border=True)
        st.metric("Coverage", cover_label, border=True)
        score = result.get("score", -1)
        st.metric("Score", f"{score}/100" if score >= 0 else "n/a", border=True)
        st.metric("Gates", "pass" if result.get("gates_ok") else "fail", border=True)
    with st.container(horizontal=True, vertical_alignment="center"):
        st.caption(f"Workspace: `{result['workspace']}`")
        if result.get("template"):
            st.badge(str(result["template"]), icon=":material/folder:", color="blue")
        if result.get("language") and result["language"] != "unknown":
            st.badge(str(result["language"]), icon=":material/code:", color="blue")
        if result.get("framework") and result["framework"] != "unknown":
            st.badge(str(result["framework"]), icon=":material/widgets:", color="green")
        if result.get("database") and result["database"] != "none":
            st.badge(str(result["database"]), icon=":material/database:", color="violet")
        if result.get("fullstack"):
            st.badge("Full-stack", icon=":material/layers:", color="orange")
        if result.get("gates_ok"):
            st.badge("Quality pass", icon=":material/verified:", color="green")
        elif result.get("gate_fail"):
            st.badge(str(result["gate_fail"]), icon=":material/gpp_bad:", color="red")
        if result.get("roster"):
            st.badge(str(result["roster"]), icon=":material/groups:", color="blue")
        if result.get("votes"):
            st.badge("Voted", icon=":material/how_to_vote:", color="violet")
        if result.get("conflicts"):
            st.badge("Conflicts", icon=":material/warning:", color="orange")
        if result.get("review_verdict"):
            st.badge(str(result["review_verdict"]), icon=":material/rate_review:", color="gray")
        if result.get("dry_run"):
            st.badge("Dry-run", icon=":material/science:", color="orange")
        if result.get("locked"):
            st.badge("Locks on", icon=":material/lock:", color="red")
        if not result.get("allow_write", True):
            st.badge("Writes off", icon=":material/edit_off:", color="gray")
        if not result.get("allow_terminal", True):
            st.badge("Terminal off", icon=":material/terminal:", color="gray")
    left, right = st.columns(2)
    with left.container(border=True, height=360):
        st.markdown("**Activity feed**")
        show_feed(result)
    with right.container(border=True, height=360):
        st.markdown("**Execution timeline**")
        trace = read_trace(workspace) if workspace.is_dir() else []
        if trace:
            st.dataframe(trace, hide_index=True, height=280)
        else:
            st.caption("No trace yet.")
    with st.container(horizontal=True):
        try:
            st.download_button(
                "Download zip",
                data=zip_workspace(workspace),
                file_name="crew-project.zip",
                mime="application/zip",
                icon=":material/folder_zip:",
            )
        except OSError:
            st.caption("Zip unavailable.")
        st.download_button(
            "Download report",
            data=render_report(result, files=names, trace=trace if workspace.is_dir() else []),
            file_name="REPORT.md",
            mime="text/markdown",
            icon=":material/description:",
        )
        st.download_button(
            "Download history",
            data=render_history(result, trace=trace if workspace.is_dir() else []),
            file_name="HISTORY.md",
            mime="text/markdown",
            icon=":material/history:",
        )
    tabs = st.tabs(
        [
            ":material/account_tree: Tree",
            ":material/difference: Diff",
            ":material/science: Tests",
            ":material/article: Report",
            ":material/forum: History",
            ":material/edit_note: Plan",
            ":material/menu_book: Docs",
        ],
        on_change="rerun",
    )
    if tabs[0].open:
        with tabs[0]:
            if workspace.is_dir():
                show_tree(workspace)
            else:
                st.caption("Workspace missing.")
    if tabs[1].open:
        with tabs[1]:
            st.code(result.get("diff") or "(no diff)", language="diff")
            if result.get("reflection"):
                st.markdown(result["reflection"])
    if tabs[2].open:
        with tabs[2]:
            with st.container(horizontal=True):
                st.metric("Passed", counts["passed"], border=True)
                st.metric("Failed", counts["failed"], border=True)
                st.metric("Errors", counts["error"], border=True)
            if result.get("test_levels"):
                st.caption(f"Levels: {result['test_levels']}")
            st.code(result.get("test_output") or "(no test output)", language="text")
            if result.get("quality"):
                st.markdown(result["quality"])
    if tabs[3].open:
        with tabs[3]:
            st.markdown(render_report(result, files=names))
    if tabs[4].open:
        with tabs[4]:
            st.markdown(render_history(result))
    if tabs[5].open:
        with tabs[5]:
            if result.get("analysis"):
                with st.expander("Codebase map", icon=":material/hub:"):
                    st.code(result["analysis"], language="markdown")
            st.markdown(result.get("plan") or "_empty_")
    if tabs[6].open:
        with tabs[6]:
            st.markdown(result.get("docs") or "_empty_")
            if result.get("evaluation"):
                st.markdown(result["evaluation"])


with st.sidebar:
    st.subheader("Model")
    local_only = st.toggle("Fully local (Ollama only)", key="local_only")
    providers = active_providers(local_only=local_only)
    provider = st.segmented_control(
        "Provider",
        list(providers),
        default=providers[0],
        required=True,
        width="stretch",
        key=f"provider_{int(local_only)}",
    )
    if not provider or provider not in providers:
        provider = providers[0]
    available = cached_models(provider)
    if not available:
        st.error("No models for this provider. Start Ollama or check the provider list.")
        model = ""
    else:
        model = st.selectbox("Model", available, key="model")
    st.caption("OpenAI uses medium reasoning effort. Keys come from `.env`.")
    st.subheader("Permissions")
    st.toggle("Dry-run", key="dry_run", help="Plan and preview. No agent writes or commands.")
    st.toggle("Allow writes", value=True, key="allow_write")
    st.toggle("Allow terminal", value=True, key="allow_terminal")
    st.toggle("Allow pip", value=True, key="allow_pip")
    st.text_input(
        "Locked files",
        key="locked",
        placeholder="README.md, tests/*, *.toml",
        help="Comma-separated globs. Agents cannot overwrite matches.",
    )
    st.subheader("Autonomy")
    autonomous_mode = st.toggle(
        "Autonomous (no pauses)",
        key="autonomous_mode",
        help="Skip plan/review approval. Loop planner -> code -> tests -> eval until the "
        "goal is met or the cycle budget runs out.",
    )
    goal_cycles_budget = st.number_input(
        "Goal cycle budget",
        min_value=1,
        max_value=20,
        value=MAX_GOAL_CYCLES,
        key="goal_cycles_budget",
        disabled=not autonomous_mode,
        help="Max planner re-loops before an autonomous run stops itself.",
    )
    live_fb = st.text_area("Feedback for next step", key="live_feedback")
    lessons = format_lessons(
        recall(st.session_state.draft["task"] if st.session_state.draft else "")
    )
    if lessons:
        with st.expander("Memory", icon=":material/bookmark:"):
            st.caption(lessons)

if st.session_state.phase == "input":
    saved = list_runs()
    if saved:
        labels = [path.parent.name for path in saved]
        pick = st.selectbox("Resume checkpoint", ["(new run)", *labels])
        if pick != "(new run)" and st.button("Load checkpoint", icon=":material/history:"):
            loaded = load_run(saved[labels.index(pick)].parent)
            st.session_state.draft = loaded
            st.session_state.result = (
                loaded if resume_phase(str(loaded.get("checkpoint", ""))) == "done" else None
            )
            st.session_state.phase = resume_phase(str(loaded.get("checkpoint", "")))
            st.rerun()
    with st.container(horizontal=True):
        st.selectbox("Stack template", list(TEMPLATE_NAMES), key="template")
        st.selectbox("Database", list(DATABASE_NAMES), key="database")
    st.caption("Existing folder is auto-detected. Template scaffolds missing files only.")
    with st.form("task_form"):
        task = st.text_area(
            "Coding task",
            placeholder="Example: generate a Python package that adds two integers and tests it.",
            height=160,
        )
        project_dir = st.text_input(
            "Existing project folder (optional)",
            placeholder=r"D:\code\my-lib",
            help="Copied into runs/<id>. Skips .venv and .git. Empty = template or blank.",
        )
        submitted = st.form_submit_button(
            "Plan",
            type="primary",
            icon=":material/edit_note:",
        )
    if submitted:
        st.session_state.error = None
        st.session_state.result = None
        if not task.strip():
            st.session_state.error = "Enter a coding task."
        elif not model:
            st.session_state.error = "Pick a model first."
        else:
            try:
                validate_selection(provider, model)
                folder = project_dir.strip() or None
                if autonomous_mode:
                    live_file = st.empty()
                    status = st.status("Autonomous run working", expanded=True)
                    events = run_autonomous(
                        task.strip(),
                        provider,
                        model,
                        folder,
                        template=str(st.session_state.get("template") or "blank"),
                        database=str(st.session_state.get("database") or "none"),
                        policy=policy_from_ui(),
                        max_goal_cycles=int(goal_cycles_budget),
                    )
                    merged = pump(events, status, live_file)
                    st.session_state.draft = merged
                    st.session_state.result = merged
                    st.session_state.error = merged.get("error") or None
                    st.session_state.phase = "done"
                    status.update(
                        label="Autonomous run failed"
                        if merged.get("error")
                        else "Autonomous run done",
                        state="error" if merged.get("error") else "complete",
                    )
                    st.rerun()
                else:
                    with st.spinner("Planner working"):
                        draft = run_plan(
                            task.strip(),
                            provider,
                            model,
                            folder,
                            template=str(st.session_state.get("template") or "blank"),
                            database=str(st.session_state.get("database") or "none"),
                            policy=policy_from_ui(),
                        )
                    if draft["error"]:
                        st.session_state.error = draft["error"]
                        st.session_state.draft = draft
                    else:
                        st.session_state.draft = draft
                        st.session_state.phase = "plan"
                        st.rerun()
            except Exception as exc:
                st.session_state.error = str(exc)

if st.session_state.phase == "plan" and st.session_state.draft:
    st.subheader("Plan")
    if st.session_state.draft.get("stack"):
        st.caption(st.session_state.draft["stack"])
    if st.session_state.draft.get("votes"):
        st.caption(f"Vote: {st.session_state.draft['votes']}")
    if st.session_state.draft.get("roster"):
        st.caption(f"Roster: {st.session_state.draft['roster']}")
    if st.session_state.draft.get("practices"):
        with st.expander("Stack practices", icon=":material/rule:"):
            st.markdown(st.session_state.draft["practices"])
    if st.session_state.draft.get("analysis"):
        with st.expander("Codebase map", icon=":material/hub:"):
            st.code(st.session_state.draft["analysis"], language="markdown")
    st.markdown(st.session_state.draft["plan"] or "_empty_")
    plan_notes = st.text_area("Feedback before coding (optional)", key="plan_notes")
    with st.container(horizontal=True):
        approve = st.button("Approve plan", type="primary", icon=":material/check:")
        reject = st.button("Reject plan", icon=":material/close:")
    if reject:
        st.session_state.phase = "input"
        st.session_state.draft = None
        st.rerun()
    if approve:
        pol = policy_from_ui()
        draft = {
            **st.session_state.draft,
            "feedback": (plan_notes.strip() or live_fb.strip()),
            "dry_run": pol.dry_run,
            "allow_write": pol.allow_write,
            "allow_terminal": pol.allow_terminal,
            "allow_pip": pol.allow_pip,
            "locked": ",".join(pol.locked),
        }
        live_file = st.empty()
        status = st.status("Coder working", expanded=True)
        try:
            merged = pump(stream_code(draft), status, live_file)
            st.session_state.draft = merged
            if merged.get("error"):
                st.session_state.error = merged["error"]
                st.session_state.result = merged
                st.session_state.phase = "done"
                status.update(label="Coder failed", state="error")
            else:
                st.session_state.phase = "review"
                status.update(label="Coder finished — review", state="complete")
            st.rerun()
        except Exception as exc:
            st.session_state.error = str(exc)
            status.update(label="Coder failed", state="error")

if st.session_state.phase == "review" and st.session_state.draft:
    draft = st.session_state.draft
    st.subheader("Code review")
    st.caption("Pause. Read the diff. Add feedback. Resume tests.")
    if draft.get("reflection"):
        st.markdown(draft["reflection"])
    if draft.get("diff"):
        st.code(draft["diff"], language="diff")
    else:
        st.caption("No git diff (git missing or nothing changed).")
    verify_notes = st.text_area("Feedback before tests (optional)", key="verify_notes")
    with st.container(horizontal=True):
        resume = st.button("Resume tests", type="primary", icon=":material/play_arrow:")
        stop = st.button("Stop here", icon=":material/stop:")
    if stop:
        st.session_state.result = draft
        st.session_state.phase = "done"
        st.rerun()
    if resume:
        pol = policy_from_ui()
        draft = {
            **draft,
            "feedback": (verify_notes.strip() or live_fb.strip()),
            "dry_run": pol.dry_run,
            "allow_write": pol.allow_write,
            "allow_terminal": pol.allow_terminal,
            "allow_pip": pol.allow_pip,
            "locked": ",".join(pol.locked),
        }
        live_file = st.empty()
        status = st.status("Tester and debugger", expanded=True)
        try:
            merged = pump(stream_verify(draft), status, live_file)
            st.session_state.draft = merged
            st.session_state.result = merged
            st.session_state.phase = "done"
            if merged.get("error"):
                st.session_state.error = merged["error"]
                status.update(label="Verify failed", state="error")
            else:
                status.update(label="Crew finished", state="complete")
            st.rerun()
        except Exception as exc:
            st.session_state.error = str(exc)
            status.update(label="Verify failed", state="error")

if st.session_state.error:
    st.error(st.session_state.error)

visible = st.session_state.result or (
    st.session_state.draft if st.session_state.phase in {"plan", "review", "done"} else None
)
if visible:
    show_dashboard(visible)

if st.session_state.phase == "done":
    lesson = st.text_input("Record a lesson for later runs")
    if lesson and st.button("Save lesson", icon=":material/bookmark:"):
        remember(
            {
                "task": visible["task"] if visible else "",
                "lesson": lesson,
                "score": visible.get("score", -1) if visible else -1,
            }
        )
        st.caption("Lesson saved.")
    if st.button("New task", icon=":material/add:"):
        st.session_state.phase = "input"
        st.session_state.draft = None
        st.session_state.result = None
        st.session_state.error = None
        st.rerun()
