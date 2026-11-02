"""Streamlit UI/UX for interactive dialogue and technical assessment evidence capture."""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from emporio.agent import build_agent, build_chat_model, run_turn
from emporio.config import Settings, load_settings
from emporio.history import Session
from emporio.retrieval import POLICY_FILE, PolicyExtractionError, PolicyIndex, load_policy
from emporio.tools import CatalogStore, SourceDataError, load_store
from emporio.ui_helpers import (
    FREE_OPENROUTER_MODELS,
    LOCAL_DETERMINISTIC_MODEL_ID,
    PRESET_SCENARIOS,
    LocalDeterministicChatModel,
    TurnEvidence,
    export_evidence_json,
    export_evidence_markdown,
    get_preset_by_id,
    summarize_session_usage,
)

MODE_LIVE_WITH_FALLBACK = "OpenRouter (:free) + Auto-Fallback on 429"
MODE_LIVE_STRICT = "OpenRouter (:free) Strict (No Fallback)"
MODE_LOCAL_DETERMINISTIC = "Local Deterministic Agent (100% Offline)"


def _init_data_and_settings() -> tuple[Settings, CatalogStore, PolicyIndex]:
    """Load configuration, catalog store, and policy index once."""
    settings = load_settings(require_api_key=False)
    store = load_store(settings.data_dir)
    index = load_policy(settings.data_dir / POLICY_FILE)
    return settings, store, index


def _build_live_agent(
    settings: Settings,
    store: CatalogStore,
    index: PolicyIndex,
    *,
    model_id: str,
    allow_provider_fallbacks: bool,
) -> Any:
    """Build the LangGraph agent backed by the selected OpenRouter `:free` model."""
    updated = replace(settings, openrouter_model=model_id)
    chat_model = build_chat_model(updated, allow_provider_fallbacks=allow_provider_fallbacks)
    return build_agent(chat_model, store, index, updated.reference_date)


def _build_local_agent(
    settings: Settings,
    store: CatalogStore,
    index: PolicyIndex,
) -> Any:
    """Build the LangGraph agent backed by the deterministic offline tool-calling model."""
    return build_agent(LocalDeterministicChatModel(), store, index, settings.reference_date)


def _execute_user_turn(
    st: Any,
    settings: Settings,
    store: CatalogStore,
    index: PolicyIndex,
    prompt_text: str,
    *,
    execution_mode: str,
    selected_model_id: str,
    allow_provider_fallbacks: bool,
    scenario_id: str | None = None,
) -> None:
    """Run one turn and append its evidence to session state."""
    session: Session = st.session_state["emporio_session"]
    turns: list[TurnEvidence] = st.session_state["emporio_turns"]

    started = time.perf_counter()
    model_used = selected_model_id

    if execution_mode == MODE_LOCAL_DETERMINISTIC or not settings.openrouter_api_key:
        local_agent = _build_local_agent(settings, store, index)
        result = run_turn(local_agent, session, prompt_text)
        model_used = LOCAL_DETERMINISTIC_MODEL_ID
    else:
        live_agent = _build_live_agent(
            settings,
            store,
            index,
            model_id=selected_model_id,
            allow_provider_fallbacks=allow_provider_fallbacks,
        )
        result = run_turn(live_agent, session, prompt_text)
        if (
            execution_mode == MODE_LIVE_WITH_FALLBACK
            and result.error in {"rate_limited", "unreachable", "provider_error"}
        ):
            local_agent = _build_local_agent(settings, store, index)
            result = run_turn(local_agent, session, prompt_text)
            model_used = f"{LOCAL_DETERMINISTIC_MODEL_ID} (fallback from {selected_model_id})"

    elapsed_ms = (time.perf_counter() - started) * 1000.0

    session.record("user", prompt_text)
    session.record("assistant", result.reply)

    evidence = TurnEvidence.from_turn_result(
        turn_index=len(turns) + 1,
        user_prompt=prompt_text,
        result=result,
        latency_ms=elapsed_ms,
        scenario_id=scenario_id,
        model_used=model_used,
    )
    turns.append(evidence)


def render_app() -> None:
    """Render the Streamlit interface."""
    import streamlit as st

    st.set_page_config(
        page_title="Empório da Música — Support Agent Evidence UI",
        page_icon="🎸",
        layout="wide",
    )

    try:
        if "emporio_base" not in st.session_state:
            st.session_state["emporio_base"] = _init_data_and_settings()
        settings, store, index = st.session_state["emporio_base"]
    except (ValueError, OSError, SourceDataError, PolicyExtractionError) as exc:
        st.error(f"**Startup / Configuration Error:** {exc}")
        return

    if "emporio_session" not in st.session_state:
        st.session_state["emporio_session"] = Session()
    if "emporio_turns" not in st.session_state:
        st.session_state["emporio_turns"] = []

    session: Session = st.session_state["emporio_session"]
    turns: list[TurnEvidence] = st.session_state["emporio_turns"]

    # --------------------------------------------------------- Sidebar Controls
    with st.sidebar:
        st.header("⚙️ Session & Model")
        if st.button("🔄 Reset / New Session", use_container_width=True):
            st.session_state["emporio_session"] = Session()
            st.session_state["emporio_turns"] = []
            st.rerun()

        execution_mode = st.selectbox(
            "Execution Mode:",
            options=[
                MODE_LIVE_WITH_FALLBACK,
                MODE_LOCAL_DETERMINISTIC,
                MODE_LIVE_STRICT,
            ],
            help=(
                "Choose whether to call OpenRouter's free models with automatic local fallback "
                "when rate-limited (HTTP 429), run 100% offline with the deterministic LangGraph "
                "agent, or run strict live OpenRouter calls."
            ),
        )

        model_choices = list(FREE_OPENROUTER_MODELS)
        if settings.openrouter_model not in model_choices:
            model_choices.insert(0, settings.openrouter_model)

        selected_model_id = st.selectbox(
            "OpenRouter `:free` Model:",
            options=model_choices,
            index=0,
            disabled=(execution_mode == MODE_LOCAL_DETERMINISTIC),
            help="Select any explicit `:free` model or `openrouter/free` auto-router.",
        )

        allow_provider_fallbacks = st.checkbox(
            "Allow OpenRouter free sub-provider fallback (`allow_fallbacks: True`)",
            value=True,
            disabled=(execution_mode == MODE_LOCAL_DETERMINISTIC),
            help="Lets OpenRouter route to another free upstream provider when one returns 429.",
        )

        st.divider()
        st.subheader("🧪 Preset Assessment Scenarios")
        scenario_options = {p.scenario_id: p.title for p in PRESET_SCENARIOS}
        selected_id = st.selectbox(
            "Select an assessment scenario:",
            options=list(scenario_options.keys()),
            format_func=lambda sid: scenario_options[sid],
        )
        selected_preset = get_preset_by_id(selected_id)
        if selected_preset is not None:
            st.caption(f"**Requirements:** `{selected_preset.requirements}`")
            st.caption(f"**Expected evidence:** `{selected_preset.expected_evidence}`")
            edited_preset_prompt = st.text_area(
                "Scenario prompt (editable before sending):",
                value=selected_preset.prompt,
                height=95,
                key=f"preset_box_{selected_preset.scenario_id}",
            )
            if st.button(
                "▶️ Run Scenario Prompt",
                type="primary",
                use_container_width=True,
            ):
                with st.spinner("Running agent turn..."):
                    _execute_user_turn(
                        st,
                        settings,
                        store,
                        index,
                        edited_preset_prompt,
                        execution_mode=execution_mode,
                        selected_model_id=selected_model_id,
                        allow_provider_fallbacks=allow_provider_fallbacks,
                        scenario_id=selected_preset.scenario_id,
                    )
                st.rerun()

        st.divider()
        st.subheader("📥 Export Transcript Evidence")
        displayed_model = (
            LOCAL_DETERMINISTIC_MODEL_ID
            if execution_mode == MODE_LOCAL_DETERMINISTIC
            else selected_model_id
        )
        md_payload = export_evidence_markdown(
            thread_id=session.thread_id,
            model=displayed_model,
            reference_date=settings.reference_date,
            turns=turns,
        )
        json_payload = export_evidence_json(
            thread_id=session.thread_id,
            model=displayed_model,
            reference_date=settings.reference_date,
            turns=turns,
        )
        st.download_button(
            label="📄 Download Transcript (.md)",
            data=md_payload,
            file_name=f"dialogue-evidence-{session.thread_id[:8]}.md",
            mime="text/markdown",
            use_container_width=True,
        )
        st.download_button(
            label="🧾 Download Transcript (.json)",
            data=json_payload,
            file_name=f"dialogue-evidence-{session.thread_id[:8]}.json",
            mime="application/json",
            use_container_width=True,
        )

    # --------------------------------------------------------- Top Audit Bar
    usage_totals = summarize_session_usage(turns)
    error_count = sum(1 for t in turns if t.error is not None)

    st.markdown("### 🎸 Empório da Música — Support Agent (Assessment Evidence UI)")
    col_model, col_date, col_thread, col_turns, col_tokens, col_status = st.columns(
        [2.4, 1.3, 1.8, 0.9, 1.3, 1.3]
    )
    col_model.metric("Active Model", displayed_model)
    col_date.metric("Reference Date", settings.reference_date.isoformat())
    col_thread.metric("Session Thread ID", session.thread_id[:12] + "…")
    col_turns.metric("Turns", str(len(turns)))
    col_tokens.metric("Total Tokens", str(usage_totals["total_tokens"]))
    status_label = "READY" if not turns else ("ERROR" if error_count else "OK")
    col_status.metric("Session Status", status_label)

    st.caption(
        f"**Mode:** `{execution_mode}` | "
        f"**Free Sub-Provider Fallback:** `{allow_provider_fallbacks}` | "
        f"**Full Thread ID:** `{session.thread_id}` | "
        f"**Data Dir:** `{settings.data_dir.name}/`"
    )
    st.divider()

    # --------------------------------------------------------- Main Chat Area
    if not turns:
        st.info(
            "No messages in this session yet. Choose a **Preset Assessment Scenario** in the "
            "sidebar or type a customer question below."
        )

    for turn in turns:
        with st.chat_message("user"):
            if turn.scenario_id:
                st.caption(f"Scenario: `{turn.scenario_id}` • Turn #{turn.turn_index}")
            else:
                st.caption(f"Turn #{turn.turn_index}")
            st.markdown(turn.user_prompt)

        with st.chat_message("assistant"):
            st.markdown(turn.reply)
            with st.expander("Technical evidence", expanded=False):
                st.caption(
                    f"Model: `{turn.model_used or displayed_model}` | "
                    f"Latency: `{turn.latency_ms:.1f} ms` | "
                    f"Tokens: `{turn.usage.get('total_tokens', 0) if turn.usage else 0}`"
                )
                if turn.error:
                    st.error(f"Turn error: `{turn.error}`")
                if turn.trace:
                    for trace_entry in turn.trace:
                        st.code(trace_entry, language=None)
                else:
                    st.caption("No tools invoked.")

    user_input = st.chat_input(
        "Ask about products, promotions, orders, return deadlines, or store policies..."
    )
    if user_input:
        with st.spinner("Running agent turn..."):
            _execute_user_turn(
                st,
                settings,
                store,
                index,
                user_input,
                execution_mode=execution_mode,
                selected_model_id=selected_model_id,
                allow_provider_fallbacks=allow_provider_fallbacks,
            )
        st.rerun()


def main(argv: list[str] | None = None) -> int:
    """CLI launcher for `uv run emporio-ui`."""
    script_path = str(Path(__file__).resolve())
    cmd = [sys.executable, "-m", "streamlit", "run", script_path]
    if argv:
        cmd.extend(argv)
    return subprocess.call(cmd)


if __name__ == "__main__":
    render_app()
