from __future__ import annotations

import streamlit as st

from agent_crew.graph import run_crew
from agent_crew.llm import models_for, validate_selection
from agent_crew.settings import PROVIDERS

st.set_page_config(page_title="Agent crew", page_icon=":material/code:", layout="wide")
st.session_state.setdefault("result", None)
st.session_state.setdefault("error", None)

st.title("Autonomous coding agent crew")
st.caption("Phase 1. CrewAI roles. LangGraph flow. Five agents, one debug loop.")


@st.cache_data(ttl="30s", max_entries=8)
def cached_models(provider: str) -> list[str]:
    return models_for(provider)


with st.sidebar:
    st.subheader("Model")
    provider = st.segmented_control(
        "Provider",
        list(PROVIDERS),
        default=PROVIDERS[0],
        required=True,
        width="stretch",
        key="provider",
    )
    available = cached_models(provider)
    if not available:
        st.error("No models for this provider. Start Ollama or check the provider list.")
        model = ""
    else:
        model = st.selectbox("Model", available, key="model")
    st.caption("OpenAI uses medium reasoning effort. Keys come from `.env`.")

with st.form("task_form"):
    task = st.text_area(
        "Coding task",
        placeholder="Example: write a Python function that adds two integers and tests it.",
        height=160,
    )
    submitted = st.form_submit_button(
        "Run crew",
        type="primary",
        icon=":material/play_arrow:",
    )

result_slot = st.container()

if submitted:
    st.session_state.error = None
    if not task.strip():
        st.session_state.error = "Enter a coding task."
    elif not model:
        st.session_state.error = "Pick a model first."
    else:
        try:
            validate_selection(provider, model)
            with result_slot.skeleton():
                st.session_state.result = run_crew(task.strip(), provider, model)
        except Exception as exc:
            st.session_state.error = str(exc)
            st.session_state.result = None

if st.session_state.error:
    result_slot.error(st.session_state.error)

result = st.session_state.result
if result:
    with result_slot.container(border=True):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.success(f"Workspace: {result['workspace']}")
            if result["tests_passed"]:
                st.badge("Tests passed", icon=":material/check:", color="green")
            else:
                st.badge("Tests failed", icon=":material/close:", color="red")
        for line in result["log"]:
            st.caption(line)
        plan, code, tests, docs, raw = st.tabs(["Plan", "Code", "Tests", "Docs", "Test output"])
        plan.markdown(result["plan"] or "_empty_")
        code.code(result["code"] or "", language="markdown")
        tests.code(result["tests"] or "", language="markdown")
        docs.markdown(result["docs"] or "_empty_")
        raw.code(result["test_output"] or "", language="text")
