"""Unit tests for the Streamlit UI evidence helpers, free-model selector, and offline agent."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from emporio.agent import TurnResult, build_agent, build_chat_model, run_turn
from emporio.config import Settings
from emporio.history import Session
from emporio.llm import is_free_openrouter_model, require_free_model
from emporio.retrieval import POLICY_FILE, load_policy
from emporio.tools import load_store
from emporio.ui_helpers import (
    FREE_OPENROUTER_MODELS,
    PRESET_SCENARIOS,
    LocalDeterministicChatModel,
    TurnEvidence,
    export_evidence_json,
    export_evidence_markdown,
    format_usage_line,
    get_preset_by_id,
    summarize_session_usage,
)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
REFERENCE = date(2026, 3, 23)


def test_preset_scenarios_cover_assessment_flows() -> None:
    scenario_ids = [preset.scenario_id for preset in PRESET_SCENARIOS]
    assert "E01_catalog_filtered" in scenario_ids
    assert "E04_policy_hours" in scenario_ids
    assert "E03_order_status" in scenario_ids
    assert "E05_out_of_scope" in scenario_ids
    assert "E07_return_multi_tool" in scenario_ids
    assert "E06_unknown_entities" in scenario_ids

    found = get_preset_by_id("E01_catalog_filtered")
    assert found is not None
    assert "R$1,000" in found.prompt
    assert get_preset_by_id("non_existent_scenario") is None


def test_free_openrouter_models_and_provider_fallbacks() -> None:
    for model_id in FREE_OPENROUTER_MODELS:
        assert is_free_openrouter_model(model_id)
        require_free_model(model_id)

    settings = Settings(
        openrouter_api_key="sk-or-test-key",
        openrouter_model="openrouter/free",
        openrouter_base_url="https://openrouter.ai/api/v1",
        reference_date=REFERENCE,
        data_dir=DATA_DIR,
    )
    model_with_fallback = build_chat_model(settings, allow_provider_fallbacks=True)
    assert model_with_fallback.extra_body["provider"] == {
        "allow_fallbacks": True,
        "require_parameters": True,
    }


def test_local_deterministic_chat_model_executes_real_tools_for_all_presets() -> None:
    store = load_store(DATA_DIR)
    index = load_policy(DATA_DIR / POLICY_FILE)
    agent = build_agent(LocalDeterministicChatModel(), store, index, REFERENCE)
    session = Session()

    # E01: Catalog search <= R$1,000
    r1 = run_turn(
        agent,
        session,
        "Which acoustic/classical guitars are available for R$1,000 or less?",
    )
    assert r1.error is None
    assert any("call search_products" in t for t in r1.trace)
    assert "products.csv:" in "\n".join(r1.trace)

    # E02: Saturday hours policy
    r2 = run_turn(agent, session, "What time do you open on Saturdays?")
    assert r2.error is None
    assert any("call search_policy" in t for t in r2.trace)
    assert "policy §2" in "\n".join(r2.trace)

    # E03: Order 8 status
    r3 = run_turn(agent, session, "What's the status of order 8?")
    assert r3.error is None
    assert any("call get_order_status" in t for t in r3.trace)
    assert "Order #8" in r3.reply

    # E04: Out-of-scope coding + guitar strings (no tool call)
    r4 = run_turn(
        agent,
        session,
        "Can you write a Python script for me, and do you sell guitar strings?",
    )
    assert r4.error is None
    assert r4.trace == []
    assert "cannot write code" in r4.reply
    assert "guitar strings" in r4.reply

    # E05 (E07_return_multi_tool): Return eligibility + order status + policy for order 7
    r5 = run_turn(
        agent,
        session,
        "I changed my mind about order 7. Can I still return it, and what does the policy say?",
    )
    assert r5.error is None
    assert any("call get_order_status" in t for t in r5.trace)
    assert any("call check_return_eligibility" in t for t in r5.trace)
    assert any("call search_policy" in t for t in r5.trace)
    assert "Order #7" in r5.reply

    # E06: Unknown entities
    r6 = run_turn(
        agent,
        session,
        "Do you have the Gibson Zebra Nonexistent X9, and what is the status of order 9999?",
    )
    assert r6.error is None
    assert any("call get_product" in t for t in r6.trace)
    assert any("call get_order_status" in t for t in r6.trace)
    assert "not found" in r6.reply.lower() or "could not find" in r6.reply.lower()


def test_local_deterministic_model_supports_portuguese_and_language_switches() -> None:
    store = load_store(DATA_DIR)
    index = load_policy(DATA_DIR / POLICY_FILE)
    agent = build_agent(LocalDeterministicChatModel(), store, index, REFERENCE)
    session = Session()

    catalog = run_turn(
        agent,
        session,
        "Quais violões estão disponíveis por até R$ 1.000,00?",
    )
    assert catalog.error is None
    assert any("call search_products" in entry for entry in catalog.trace)
    assert "Estes são os produtos" in catalog.reply
    assert "R$ " in catalog.reply
    assert "products.csv:" in "\n".join(catalog.trace)

    policy = run_turn(agent, session, "Que horas a loja abre no sábado?")
    assert policy.error is None
    assert any("call search_policy" in entry for entry in policy.trace)
    assert "Política da Loja §2" in policy.reply
    assert "Sábado 09:00 às 13:00" in policy.reply

    return_result = run_turn(
        agent,
        session,
        "Mudei de ideia sobre o pedido 7. Ainda posso devolver?",
    )
    assert return_result.error is None
    assert any("call check_return_eligibility" in entry for entry in return_result.trace)
    assert "Elegibilidade de devolução do Pedido #7" in return_result.reply
    assert "Política da Loja §4.1" in return_result.reply
    assert "`34` de uma janela de `7` dias" in return_result.reply
    assert "condição do produto e embalagem original" in return_result.reply

    ambiguous = run_turn(agent, session, "OK")
    assert ambiguous.error is None
    assert "Nenhuma seção" in ambiguous.reply
    assert session.response_language == "pt-BR"

    english = run_turn(agent, session, "What time does the store open on Saturday?")
    assert english.error is None
    assert "Store Policy §2" in english.reply
    assert "Saturday hours: **09:00 to 13:00**" in english.reply
    assert "Original PT-BR evidence" in english.reply
    assert "Sábado 09:00 às 13:00" in english.reply
    assert session.response_language == "en"


def test_local_deterministic_model_matches_ui_evidence_scenarios() -> None:
    store = load_store(DATA_DIR)
    index = load_policy(DATA_DIR / POLICY_FILE)
    agent = build_agent(LocalDeterministicChatModel(), store, index, REFERENCE)
    session = Session()

    portuguese = run_turn(agent, session, "Quais violões vocês têm por até R$ 1.000?")
    assert portuguese.error is None
    trace = "\n".join(portuguese.trace)
    assert '"available_only": true' in trace
    assert '"category": "acoustic_classical_guitars"' in trace
    assert '"max_price_brl": 1000.0' in trace
    assert "Giannini GF-3D Dreadnought Sunburst" not in portuguese.reply
    assert "Shelby SN-7C 7 Cordas Nylon Natural" not in portuguese.reply

    english = run_turn(agent, session, "Which guitars do you have under R$1,000?")
    assert english.error is None
    trace = "\n".join(english.trace)
    assert '"available_only": true' in trace
    assert '"category": "acoustic_classical_guitars"' in trace
    assert '"max_price_brl": 1000.0' in trace
    assert "Tagima Memphis AC-39 Nylon Natural" in english.reply
    assert "R$ 429.90" in english.reply
    assert "Takamine GD20 Dreadnought Natural" not in english.reply

    cheapest = run_turn(agent, session, "Which of those guitars is the cheapest?")
    assert cheapest.error is None
    assert "The cheapest matching product is" in cheapest.reply
    assert "Tagima Memphis AC-39 Nylon Natural" in cheapest.reply
    assert "R$ 429.90" in cheapest.reply

    out_of_scope = run_turn(agent, session, "Qual é a capital da França?")
    assert out_of_scope.error is None
    assert out_of_scope.trace == []
    assert "Posso ajudar apenas" in out_of_scope.reply
    assert "Paris" not in out_of_scope.reply


def test_turn_evidence_and_usage_aggregation() -> None:
    t1 = TurnEvidence.from_turn_result(
        turn_index=1,
        user_prompt="What time do you open on Saturdays?",
        result=TurnResult(
            reply="We open from 9:00 to 14:00 on Saturdays (Policy §2, p. 2).",
            error=None,
            trace=[
                'call search_policy {"query": "Saturday opening hours"}',
                "result search_policy ok sources=[policy §2 p2]",
            ],
            usage={"input_tokens": 120, "output_tokens": 30, "total_tokens": 150},
        ),
        latency_ms=412.67,
        executed_at="2026-03-23T12:00:00+00:00",
        scenario_id="E02_store_policy_hours",
        model_used="openrouter/free",
    )
    t2 = TurnEvidence.from_turn_result(
        turn_index=2,
        user_prompt="Can you write a sorting algorithm?",
        result=TurnResult(
            reply="I can only help with Empório da Música products, orders, and policies.",
            error=None,
            trace=[],
            usage={"input_tokens": 90, "output_tokens": 20, "total_tokens": 110},
        ),
        latency_ms=199.94,
        executed_at="2026-03-23T12:01:00+00:00",
        scenario_id="E04_out_of_scope",
        model_used="openrouter/free",
    )

    assert t1.latency_ms == 412.7
    assert format_usage_line(t1.usage) == "input=120, output=30, total=150"
    assert format_usage_line(None) == "not reported"

    summary = summarize_session_usage([t1, t2])
    assert summary == {
        "input_tokens": 210,
        "output_tokens": 50,
        "total_tokens": 260,
        "turns_with_usage": 2,
    }


def test_export_evidence_markdown_and_json() -> None:
    turn = TurnEvidence.from_turn_result(
        turn_index=1,
        user_prompt="What's the status of order 8?",
        result=TurnResult(
            reply="Order 8 is in transit via Correios.",
            error=None,
            trace=[
                'call get_order_status {"order_id": 8}',
                "result get_order_status ok sources=[orders.csv:9, order_items.csv:11]",
            ],
            usage={"input_tokens": 100, "output_tokens": 25, "total_tokens": 125},
        ),
        latency_ms=350.0,
        executed_at="2026-03-23T15:00:00+00:00",
        scenario_id="E03_order_status",
        model_used="openrouter/free",
    )

    md = export_evidence_markdown(
        thread_id="abc123thread",
        model="openrouter/free",
        reference_date=date(2026, 3, 23),
        turns=[turn],
    )
    assert "# Empório da Música — Dialogue Evidence Transcript" in md
    assert "`abc123thread`" in md
    assert "`openrouter/free`" in md
    assert "`2026-03-23`" in md
    assert "## Turn 1 (E03_order_status)" in md
    assert "orders.csv:9" in md
    assert "PASS (0 runtime errors)" in md

    raw_json = export_evidence_json(
        thread_id="abc123thread",
        model="openrouter/free",
        reference_date=date(2026, 3, 23),
        turns=[turn],
    )
    parsed = json.loads(raw_json)
    assert parsed["thread_id"] == "abc123thread"
    assert parsed["turn_count"] == 1
    assert parsed["turns"][0]["scenario_id"] == "E03_order_status"
    assert parsed["turns"][0]["model_used"] == "openrouter/free"
    assert parsed["turns"][0]["trace"][0] == 'call get_order_status {"order_id": 8}'
