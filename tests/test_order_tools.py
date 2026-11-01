"""Offline tests for exact, read-only order status lookup."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

from emporio.tools import (
    ORDERS_FILE,
    CatalogStore,
    DataIntegrityError,
    DataSchemaError,
    get_order_status,
    load_store,
)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture(scope="module")
def store() -> CatalogStore:
    return load_store(DATA_DIR)


def _copied_data_dir(tmp_path: Path, name: str) -> Path:
    fixture_dir = tmp_path / name
    shutil.copytree(DATA_DIR, fixture_dir)
    return fixture_dir


def test_known_order_returns_exact_source_values_and_evidence(store: CatalogStore) -> None:
    result = get_order_status(store, order_id=8)

    assert result["found"] is True
    assert result["error"] is None
    order = result["order"]
    assert order is not None
    assert order == {
        "order_id": 8,
        "order_date": "2026-02-15",
        "status": "shipped",
        "total_brl": "349.90",
        "currency": "BRL",
        "payment_method": "debit",
        "tracking_code": "BRJL5544332BR",
        "estimated_delivery": "2026-02-28",
        "notes_pt": None,
        "items": [
            {
                "product_id": 120,
                "product_name": "Kala KA-C Concert Mogno",
                "quantity": 1,
                "source": {
                    "file": "desafio_tecnico_ai_eng - order_items.csv",
                    "row": 9,
                },
                "product_source": {
                    "file": "desafio_tecnico_ai_eng - products.csv",
                    "row": 41,
                },
            }
        ],
        "source": {"file": ORDERS_FILE, "row": 9},
    }
    json.dumps(result, ensure_ascii=False)


@pytest.mark.parametrize(
    ("order_id", "expected_products"),
    [
        (15, [82, 106]),
        (20, [107, 84]),
    ],
)
def test_multi_item_orders_preserve_source_line_order(
    store: CatalogStore,
    order_id: int,
    expected_products: list[int],
) -> None:
    result = get_order_status(store, order_id=order_id)

    assert result["order"] is not None
    assert [item["product_id"] for item in result["order"]["items"]] == expected_products


def test_missing_optional_order_fields_remain_null(store: CatalogStore) -> None:
    result = get_order_status(store, order_id=9)

    assert result["order"] is not None
    assert result["order"]["status"] == "confirmed"
    assert result["order"]["tracking_code"] is None
    assert result["order"]["estimated_delivery"] is None
    assert result["order"]["notes_pt"] is None


def test_cancelled_order_note_is_preserved_as_source_data(store: CatalogStore) -> None:
    result = get_order_status(store, order_id=17)

    assert result["order"] is not None
    assert result["order"]["status"] == "cancelled"
    assert result["order"]["notes_pt"] == (
        "Pedido cancelado pelo cliente antes do processamento"
    )


def test_unknown_order_returns_unambiguous_not_found(store: CatalogStore) -> None:
    result = get_order_status(store, order_id=999)

    assert result == {
        "found": False,
        "order": None,
        "evidence": {"source_file": ORDERS_FILE},
        "error": {
            "code": "not_found",
            "field": "order_id",
            "message": "No order found for order_id 999.",
        },
    }


@pytest.mark.parametrize("order_id", [True, 0, -1, "8", 8.0, None])
def test_malformed_order_id_returns_structured_error(
    store: CatalogStore,
    order_id: object,
) -> None:
    result = get_order_status(store, order_id=order_id)  # type: ignore[arg-type]

    assert result["error"] == {
        "code": "invalid_argument",
        "field": "order_id",
        "message": "must be a positive integer",
    }


def test_order_output_never_exposes_customer_identity(store: CatalogStore) -> None:
    forbidden = {"customer_id", "name", "email", "phone", "city"}

    for order_id in store.orders:
        result = get_order_status(store, order_id=order_id)
        serialized = json.dumps(result, ensure_ascii=False)
        assert all(f'"{field}"' not in serialized for field in forbidden)


def test_load_store_rejects_duplicate_order_identifiers(tmp_path: Path) -> None:
    fixture_dir = _copied_data_dir(tmp_path, "duplicate-order")
    orders_path = fixture_dir / ORDERS_FILE
    with orders_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    rows.append(rows[1])
    with orders_path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows(rows)

    with pytest.raises(DataIntegrityError, match=r"Duplicate order_id '1'.*rows 2 and 22"):
        load_store(fixture_dir)


def test_load_store_rejects_missing_required_order_column(tmp_path: Path) -> None:
    fixture_dir = _copied_data_dir(tmp_path, "missing-status-column")
    orders_path = fixture_dir / ORDERS_FILE
    with orders_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    status_index = rows[0].index("status")
    without_status = [row[:status_index] + row[status_index + 1 :] for row in rows]
    with orders_path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows(without_status)

    with pytest.raises(DataSchemaError, match="Unexpected columns"):
        load_store(fixture_dir)
