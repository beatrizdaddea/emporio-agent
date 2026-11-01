"""Offline tests for the deterministic return-window decision."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from emporio.tools import CatalogStore, check_return_eligibility, load_store

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
REFERENCE = date(2026, 3, 23)


@pytest.fixture(scope="module")
def store() -> CatalogStore:
    return load_store(DATA_DIR)


def _decide(store: CatalogStore, order_id: int, reason: str, ref: date = REFERENCE):
    result = check_return_eligibility(store, order_id=order_id, reason=reason, reference_date=ref)
    assert result["found"] is True
    return result["decision"]


def test_order_7_regret_is_expired_with_proxy_basis(store: CatalogStore) -> None:
    decision = _decide(store, 7, "regret")

    assert decision["eligible"] is False
    assert decision["blocker"] == "window_expired"
    assert decision["rule_section"] == "4.1"
    assert decision["window_days"] == 7
    assert decision["basis"] == "estimated_delivery"
    assert decision["basis_date"] == "2026-02-17"
    assert decision["days_elapsed"] == 34
    assert decision["reference_date"] == "2026-03-23"
    assert decision["source"]["file"].endswith("orders.csv")
    json.dumps(decision)


def test_order_7_defect_uses_purchase_date(store: CatalogStore) -> None:
    decision = _decide(store, 7, "defect")

    assert decision["eligible"] is False
    assert decision["blocker"] == "window_expired"
    assert decision["rule_section"] == "4.2"
    assert decision["window_days"] == 30
    assert decision["basis"] == "order_date"
    assert decision["basis_date"] == "2026-02-03"
    assert decision["days_elapsed"] == 48


@pytest.mark.parametrize(
    ("order_id", "blocker"),
    [(8, "not_delivered"), (9, "not_delivered"), (13, "not_delivered"), (17, "cancelled")],
)
def test_undelivered_or_cancelled_orders_are_blocked(
    store: CatalogStore, order_id: int, blocker: str
) -> None:
    for reason in ("regret", "defect"):
        decision = _decide(store, order_id, reason)
        assert decision["eligible"] is False
        assert decision["blocker"] == blocker
        assert decision["days_elapsed"] is None


def test_window_boundaries_are_inclusive_and_use_given_reference_date(
    store: CatalogStore,
) -> None:
    assert _decide(store, 7, "regret", date(2026, 2, 24))["eligible"] is True  # day 7
    assert _decide(store, 7, "regret", date(2026, 2, 25))["blocker"] == "window_expired"  # day 8
    assert _decide(store, 7, "defect", date(2026, 3, 5))["eligible"] is True  # day 30
    assert _decide(store, 7, "defect", date(2026, 3, 6))["blocker"] == "window_expired"  # day 31
    assert _decide(store, 7, "regret", date(2026, 2, 17))["days_elapsed"] == 0


def test_decision_lists_what_was_not_checked(store: CatalogStore) -> None:
    not_checked = " ".join(_decide(store, 7, "regret")["not_checked"])

    assert "online purchases" in not_checked
    assert "packaging" in not_checked
    assert "proxy" in not_checked


def test_unknown_order_returns_not_found(store: CatalogStore) -> None:
    result = check_return_eligibility(
        store, order_id=9999, reason="regret", reference_date=REFERENCE
    )

    assert result["found"] is False
    assert result["decision"] is None
    assert result["error"]["code"] == "not_found"


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"order_id": 0, "reason": "regret"}, "order_id"),
        ({"order_id": True, "reason": "regret"}, "order_id"),
        ({"order_id": "7", "reason": "regret"}, "order_id"),
        ({"order_id": 7, "reason": "exchange"}, "reason"),
        ({"order_id": 7, "reason": "regret", "reference_date": "2026-03-23"}, "reference_date"),
    ],
)
def test_invalid_arguments_return_structured_error(
    store: CatalogStore, kwargs: dict, field: str
) -> None:
    kwargs.setdefault("reference_date", REFERENCE)
    result = check_return_eligibility(store, **kwargs)

    assert result["error"]["code"] == "invalid_argument"
    assert result["error"]["field"] == field
