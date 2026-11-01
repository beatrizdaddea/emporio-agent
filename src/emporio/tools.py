"""Deterministic CSV data loaders, cleaning rules, and catalog/order tools."""

from __future__ import annotations

import csv
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Literal, TypedDict, cast

PRODUCTS_FILE = "desafio_tecnico_ai_eng - products.csv"
CATEGORIES_FILE = "desafio_tecnico_ai_eng - categories.csv"
PROMOTIONS_FILE = "desafio_tecnico_ai_eng - promotions.csv"
ORDERS_FILE = "desafio_tecnico_ai_eng - orders.csv"
ORDER_ITEMS_FILE = "desafio_tecnico_ai_eng - order_items.csv"

EXPECTED_COLUMNS: dict[str, tuple[str, ...]] = {
    CATEGORIES_FILE: ("category_id", "name", "description"),
    PRODUCTS_FILE: (
        "product_id",
        "price_brl",
        "name",
        "category_id",
        "description",
        "stock_quantity",
        "status",
        "specs",
        "created_at",
    ),
    PROMOTIONS_FILE: (
        "promotion_id",
        "product_id",
        "discount_percent",
        "description",
        "is_active",
    ),
    ORDERS_FILE: (
        "order_id",
        "customer_id",
        "order_date",
        "status",
        "total_brl",
        "payment_method",
        "tracking_code",
        "estimated_delivery",
        "notes",
    ),
    ORDER_ITEMS_FILE: ("order_id", "quantity", "product_id"),
}

ProductStatus = Literal["active", "discontinued", "coming_soon"]
OrderStatus = Literal["delivered", "shipped", "confirmed", "pending", "cancelled"]
PaymentMethod = Literal["pix", "debit", "boleto", "credit_3x", "credit_6x", "credit_12x"]
PriceInput = Decimal | int | float | str

CategorySlug = Literal[
    "electric_guitars",
    "bass",
    "drums_percussion",
    "keyboards_pianos",
    "acoustic_classical_guitars",
    "woodwinds",
    "brass",
    "orchestral_strings",
    "ukuleles",
]

CATEGORY_SLUG_TO_ID: dict[CategorySlug, int] = {
    "electric_guitars": 1,
    "bass": 2,
    "drums_percussion": 3,
    "keyboards_pianos": 4,
    "acoustic_classical_guitars": 5,
    "woodwinds": 6,
    "brass": 7,
    "orchestral_strings": 8,
    "ukuleles": 9,
}

CATEGORY_ID_TO_SLUG: dict[int, CategorySlug] = {
    cat_id: slug for slug, cat_id in CATEGORY_SLUG_TO_ID.items()
}


@dataclass(frozen=True)
class Category:
    """Product category from `categories.csv`."""

    category_id: int
    slug: CategorySlug
    name_pt: str
    description_pt: str
    source_row: int


@dataclass(frozen=True)
class Promotion:
    """Product promotion from `promotions.csv`."""

    promotion_id: int
    product_id: int
    discount_percent: int
    description_pt: str
    is_active: bool
    source_row: int


@dataclass(frozen=True)
class ActivePromotion:
    """Calculated active promotion attached to a product."""

    promotion_id: int
    discount_percent: int
    promo_price_brl: Decimal
    label_pt: str
    source_row: int


@dataclass(frozen=True)
class Product:
    """Cleaned product record from `products.csv`."""

    product_id: int
    name: str
    category_id: int
    category_slug: CategorySlug
    price_brl: Decimal
    stock_quantity: int
    status: ProductStatus
    available: bool
    description_pt: str
    specs: dict[str, str]
    created_at: date
    active_promotion: ActivePromotion | None
    source_row: int


@dataclass(frozen=True)
class OrderItem:
    """Line item belonging to an order from `order_items.csv`."""

    order_id: int
    product_id: int
    product_name: str
    quantity: int
    source_row: int


@dataclass(frozen=True)
class Order:
    """Cleaned order record from `orders.csv` (excludes `customer_id` per DEC-3/NFR-04)."""

    order_id: int
    order_date: date
    status: OrderStatus
    total_brl: Decimal
    payment_method: PaymentMethod
    tracking_code: str | None
    estimated_delivery: date | None
    notes_pt: str | None
    items: tuple[OrderItem, ...]
    source_row: int


@dataclass(frozen=True)
class CatalogStore:
    """In-memory read-only store of cleaned operational CSV tables."""

    categories: dict[int, Category]
    products: dict[int, Product]
    promotions: tuple[Promotion, ...]
    orders: dict[int, Order]


class SourceEvidence(TypedDict):
    """CSV location supporting one returned record."""

    file: str
    row: int


class PromotionOutput(TypedDict):
    """JSON-serializable active-promotion contract."""

    discount_percent: int
    price_brl: str
    currency: Literal["BRL"]
    source: SourceEvidence


class ProductSummary(TypedDict):
    """Concise product contract used by filtered searches."""

    product_id: int
    name: str
    category_slug: CategorySlug
    category_name_pt: str
    price_brl: str
    currency: Literal["BRL"]
    stock_quantity: int
    status: ProductStatus
    available: bool
    active_promotion: PromotionOutput | None
    source: SourceEvidence


class ProductDetail(ProductSummary):
    """Exact-lookup contract with the source description and specifications."""

    description_pt: str
    specs: dict[str, str]
    category_source: SourceEvidence


class ProductLookupResult(TypedDict):
    """Exact product lookup result."""

    found: bool
    product: ProductDetail | None
    evidence: dict[str, str]


class OrderItemOutput(TypedDict):
    """JSON-serializable order line backed by order-item and product rows."""

    product_id: int
    product_name: str
    quantity: int
    source: SourceEvidence
    product_source: SourceEvidence


class OrderOutput(TypedDict):
    """Read-only order status contract without customer identifiers."""

    order_id: int
    order_date: str
    status: OrderStatus
    total_brl: str
    currency: Literal["BRL"]
    payment_method: PaymentMethod
    tracking_code: str | None
    estimated_delivery: str | None
    notes_pt: str | None
    items: list[OrderItemOutput]
    source: SourceEvidence


class NotFoundDetail(TypedDict):
    """Structured exact-identifier not-found error."""

    code: Literal["not_found"]
    field: str
    message: str


class OrderLookupResult(TypedDict):
    """Exact order lookup result."""

    found: bool
    order: OrderOutput | None
    evidence: dict[str, str]
    error: NotFoundDetail | None


class ProductSearchResult(TypedDict):
    """Deterministic filtered product search result."""

    count: int
    total_matches: int
    truncated: bool
    filters: dict[str, object]
    products: list[ProductSummary]


class ErrorDetail(TypedDict):
    """Structured tool-input error."""

    code: Literal["invalid_argument", "ambiguous_match"]
    field: str
    message: str


class ToolErrorResult(TypedDict):
    """JSON-serializable invalid-input or ambiguous-match result."""

    error: ErrorDetail


class SourceDataError(ValueError):
    """Base error for malformed or internally inconsistent source CSV data."""


class DataSchemaError(SourceDataError):
    """Raised when a source CSV does not have its inspected schema."""


class DataIntegrityError(SourceDataError):
    """Raised when source identifiers or references are ambiguous."""


def _invalid_argument(field: str, message: str) -> ToolErrorResult:
    return {
        "error": {
            "code": "invalid_argument",
            "field": field,
            "message": message,
        }
    }


def _ambiguous_match(field: str, message: str) -> ToolErrorResult:
    return {
        "error": {
            "code": "ambiguous_match",
            "field": field,
            "message": message,
        }
    }


def _fold_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.strip().casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _parse_price(value: PriceInput, field: str) -> Decimal | ToolErrorResult:
    if isinstance(value, bool):
        return _invalid_argument(field, "must be a non-negative BRL amount")

    amount: Decimal
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, int):
        amount = Decimal(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            return _invalid_argument(field, "must be a finite BRL amount")
        amount = Decimal(str(value))
    elif isinstance(value, str):
        raw = value.strip()
        if raw.startswith("R$"):
            raw = raw[2:].strip()
        if not raw:
            return _invalid_argument(field, "must not be empty")

        if "," in raw:
            if "." in raw:
                if re.fullmatch(r"\d{1,3}(?:\.\d{3})*,\d{1,2}", raw) is None:
                    return _invalid_argument(field, "has an invalid PT-BR currency format")
                raw = raw.replace(".", "").replace(",", ".")
            else:
                if re.fullmatch(r"\d+,\d{1,2}", raw) is None:
                    return _invalid_argument(field, "has an invalid decimal-comma format")
                raw = raw.replace(",", ".")
        elif re.fullmatch(r"\d+(?:\.\d{1,2})?", raw) is None:
            return _invalid_argument(field, "has an invalid decimal format")

        try:
            amount = Decimal(raw)
        except InvalidOperation:
            return _invalid_argument(field, "must be a valid BRL amount")
    else:
        return _invalid_argument(field, "must be a number or currency string")

    if not amount.is_finite():
        return _invalid_argument(field, "must be a finite BRL amount")
    if amount < 0:
        return _invalid_argument(field, "must be non-negative")
    if amount.as_tuple().exponent < -2:
        return _invalid_argument(field, "must have at most two decimal places")
    return amount.quantize(Decimal("0.01"))


def _money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), ".2f")


def _promotion_output(promotion: ActivePromotion | None) -> PromotionOutput | None:
    if promotion is None:
        return None
    return {
        "discount_percent": promotion.discount_percent,
        "price_brl": _money(promotion.promo_price_brl),
        "currency": "BRL",
        "source": {"file": PROMOTIONS_FILE, "row": promotion.source_row},
    }


def _product_summary(store: CatalogStore, product: Product) -> ProductSummary:
    category = store.categories[product.category_id]
    return {
        "product_id": product.product_id,
        "name": product.name,
        "category_slug": product.category_slug,
        "category_name_pt": category.name_pt,
        "price_brl": _money(product.price_brl),
        "currency": "BRL",
        "stock_quantity": product.stock_quantity,
        "status": product.status,
        "available": product.available,
        "active_promotion": _promotion_output(product.active_promotion),
        "source": {"file": PRODUCTS_FILE, "row": product.source_row},
    }


def _product_detail(store: CatalogStore, product: Product) -> ProductDetail:
    category = store.categories[product.category_id]
    return {
        **_product_summary(store, product),
        "description_pt": product.description_pt,
        "specs": dict(product.specs),
        "category_source": {"file": CATEGORIES_FILE, "row": category.source_row},
    }


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"Required CSV file not found: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        actual_columns = tuple(reader.fieldnames or ())
        expected_columns = EXPECTED_COLUMNS[path.name]
        if actual_columns != expected_columns:
            raise DataSchemaError(
                f"Unexpected columns in {path.name}: expected {expected_columns!r}, "
                f"got {actual_columns!r}."
            )
        rows = list(reader)
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise DataSchemaError(f"Malformed row width in {path.name}.")
    return rows


def _ensure_unique(rows: list[dict[str, str]], *, key: str, source_file: str) -> None:
    seen: dict[str, int] = {}
    for source_row, row in enumerate(rows, start=2):
        value = row[key].strip()
        if value in seen:
            raise DataIntegrityError(
                f"Duplicate {key} {value!r} in {source_file} rows "
                f"{seen[value]} and {source_row}."
            )
        seen[value] = source_row


def load_store(data_dir: Path | str) -> CatalogStore:
    """Load, validate, and clean the operational CSV files from `data_dir`.

    Note:
        `customers.csv` is intentionally never read (`DEC-3`, `NFR-04`), and
        `customer_id` on `orders.csv` is discarded before the read-only store is built.
    """
    base = Path(data_dir)

    # 1. Categories
    cat_rows = _read_csv_rows(base / CATEGORIES_FILE)
    _ensure_unique(cat_rows, key="category_id", source_file=CATEGORIES_FILE)
    categories: dict[int, Category] = {}
    for source_row, row in enumerate(cat_rows, start=2):
        cat_id = int(row["category_id"].strip())
        slug = CATEGORY_ID_TO_SLUG[cat_id]
        categories[cat_id] = Category(
            category_id=cat_id,
            slug=slug,
            name_pt=row["name"].strip(),
            description_pt=row["description"].strip(),
            source_row=source_row,
        )

    # 2. Promotions
    promo_rows = _read_csv_rows(base / PROMOTIONS_FILE)
    _ensure_unique(promo_rows, key="promotion_id", source_file=PROMOTIONS_FILE)
    promotions: list[Promotion] = []
    active_promo_by_product: dict[int, Promotion] = {}
    for source_row, row in enumerate(promo_rows, start=2):
        promo = Promotion(
            promotion_id=int(row["promotion_id"].strip()),
            product_id=int(row["product_id"].strip()),
            discount_percent=int(row["discount_percent"].strip()),
            description_pt=row["description"].strip(),
            is_active=row["is_active"].strip() == "1",
            source_row=source_row,
        )
        promotions.append(promo)
        if promo.is_active:
            if promo.product_id in active_promo_by_product:
                previous = active_promo_by_product[promo.product_id]
                raise DataIntegrityError(
                    f"Multiple active promotions for product_id {promo.product_id}: "
                    f"rows {previous.source_row} and {source_row} in {PROMOTIONS_FILE}."
                )
            active_promo_by_product[promo.product_id] = promo

    # 3. Products (sorted ascending by product_id to fix out-of-order row 145)
    prod_rows = _read_csv_rows(base / PRODUCTS_FILE)
    _ensure_unique(prod_rows, key="product_id", source_file=PRODUCTS_FILE)
    parsed_products: list[Product] = []
    for source_row, row in enumerate(prod_rows, start=2):
        prod_id = int(row["product_id"].strip())
        cat_id = int(row["category_id"].strip())
        price_brl = Decimal(row["price_brl"].strip())
        stock_qty = int(row["stock_quantity"].strip())
        raw_status = row["status"].strip()
        if raw_status not in {"active", "discontinued", "coming_soon"}:
            raise ValueError(f"Invalid product status {raw_status!r} on row {source_row}.")
        status = cast(ProductStatus, raw_status)
        raw_specs = json.loads(row["specs"].strip())
        specs = {str(k): str(v) for k, v in raw_specs.items()}

        active_promo_obj: ActivePromotion | None = None
        if prod_id in active_promo_by_product:
            ap = active_promo_by_product[prod_id]
            discounted = (
                price_brl * (Decimal(100) - ap.discount_percent) / Decimal(100)
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            active_promo_obj = ActivePromotion(
                promotion_id=ap.promotion_id,
                discount_percent=ap.discount_percent,
                promo_price_brl=discounted,
                label_pt=ap.description_pt,
                source_row=ap.source_row,
            )

        parsed_products.append(
            Product(
                product_id=prod_id,
                name=row["name"].strip(),
                category_id=cat_id,
                category_slug=CATEGORY_ID_TO_SLUG[cat_id],
                price_brl=price_brl,
                stock_quantity=stock_qty,
                status=status,
                available=(status == "active" and stock_qty > 0),
                description_pt=row["description"].strip(),
                specs=specs,
                created_at=date.fromisoformat(row["created_at"].strip()),
                active_promotion=active_promo_obj,
                source_row=source_row,
            )
        )

    parsed_products.sort(key=lambda p: p.product_id)
    products: dict[int, Product] = {p.product_id: p for p in parsed_products}

    missing_promotion_products = sorted(
        {promotion.product_id for promotion in promotions} - products.keys()
    )
    if missing_promotion_products:
        raise DataIntegrityError(
            f"Unknown promotion product_id values in {PROMOTIONS_FILE}: "
            f"{missing_promotion_products!r}."
        )

    # 4. Order items (grouped by order_id)
    item_rows = _read_csv_rows(base / ORDER_ITEMS_FILE)
    items_by_order: dict[int, list[OrderItem]] = {}
    for source_row, row in enumerate(item_rows, start=2):
        ord_id = int(row["order_id"].strip())
        prod_id = int(row["product_id"].strip())
        qty = int(row["quantity"].strip())
        if prod_id not in products:
            raise DataIntegrityError(
                f"Unknown product_id {prod_id} in {ORDER_ITEMS_FILE} row {source_row}."
            )
        prod_name = products[prod_id].name
        items_by_order.setdefault(ord_id, []).append(
            OrderItem(
                order_id=ord_id,
                product_id=prod_id,
                product_name=prod_name,
                quantity=qty,
                source_row=source_row,
            )
        )

    # 5. Orders (customer_id intentionally ignored)
    order_rows = _read_csv_rows(base / ORDERS_FILE)
    _ensure_unique(order_rows, key="order_id", source_file=ORDERS_FILE)
    orders: dict[int, Order] = {}
    for source_row, row in enumerate(order_rows, start=2):
        ord_id = int(row["order_id"].strip())
        tracking = row["tracking_code"].strip() or None
        est_deliv_raw = row["estimated_delivery"].strip()
        est_deliv = date.fromisoformat(est_deliv_raw) if est_deliv_raw else None
        notes = row["notes"].strip() or None
        raw_order_status = row["status"].strip()
        if raw_order_status not in {
            "delivered",
            "shipped",
            "confirmed",
            "pending",
            "cancelled",
        }:
            raise DataSchemaError(
                f"Invalid order status {raw_order_status!r} in {ORDERS_FILE} row {source_row}."
            )
        order_status = cast(OrderStatus, raw_order_status)
        raw_payment_method = row["payment_method"].strip()
        if raw_payment_method not in {
            "pix",
            "debit",
            "boleto",
            "credit_3x",
            "credit_6x",
            "credit_12x",
        }:
            raise DataSchemaError(
                f"Invalid payment method {raw_payment_method!r} in "
                f"{ORDERS_FILE} row {source_row}."
            )
        payment_method = cast(PaymentMethod, raw_payment_method)

        orders[ord_id] = Order(
            order_id=ord_id,
            order_date=date.fromisoformat(row["order_date"].strip()),
            status=order_status,
            total_brl=Decimal(row["total_brl"].strip()),
            payment_method=payment_method,
            tracking_code=tracking,
            estimated_delivery=est_deliv,
            notes_pt=notes,
            items=tuple(items_by_order.get(ord_id, [])),
            source_row=source_row,
        )

    orphan_order_ids = sorted(set(items_by_order) - orders.keys())
    if orphan_order_ids:
        raise DataIntegrityError(
            f"Unknown order_id values in {ORDER_ITEMS_FILE}: {orphan_order_ids!r}."
        )

    return CatalogStore(
        categories=categories,
        products=products,
        promotions=tuple(promotions),
        orders=orders,
    )


def get_product(
    store: CatalogStore,
    *,
    product_id: int | None = None,
    exact_name: str | None = None,
) -> ProductLookupResult | ToolErrorResult:
    """Return one exact product match with source evidence.

    Exactly one of `product_id` and `exact_name` must be provided. Name matching
    ignores case, accents, and surrounding whitespace, but requires the complete
    product name and never performs fuzzy matching.
    """
    supplied = (product_id is not None) + (exact_name is not None)
    if supplied != 1:
        return _invalid_argument(
            "lookup",
            "provide exactly one of product_id or exact_name",
        )

    product: Product | None
    if product_id is not None:
        if isinstance(product_id, bool) or not isinstance(product_id, int) or product_id <= 0:
            return _invalid_argument("product_id", "must be a positive integer")
        product = store.products.get(product_id)
    else:
        if not isinstance(exact_name, str) or not exact_name.strip():
            return _invalid_argument("exact_name", "must be a non-empty string")
        folded_name = _fold_text(exact_name)
        candidates = [
            candidate
            for candidate in sorted(store.products.values(), key=lambda item: item.product_id)
            if _fold_text(candidate.name) == folded_name
        ]
        if len(candidates) > 1:
            return _ambiguous_match(
                "exact_name",
                f"matches multiple product IDs: {[item.product_id for item in candidates]!r}",
            )
        product = candidates[0] if candidates else None

    if product is None:
        return {
            "found": False,
            "product": None,
            "evidence": {"source_file": PRODUCTS_FILE},
        }
    return {
        "found": True,
        "product": _product_detail(store, product),
        "evidence": {"source_file": PRODUCTS_FILE},
    }


def search_products(
    store: CatalogStore,
    *,
    query: str | None = None,
    category: CategorySlug | None = None,
    min_price_brl: PriceInput | None = None,
    max_price_brl: PriceInput | None = None,
    status: ProductStatus | None = None,
    available_only: bool = False,
    limit: int = 20,
) -> ProductSearchResult | ToolErrorResult:
    """Search product names and deterministic source-backed filters.

    Prices are inclusive. Results are ordered by `product_id`, capped by `limit`,
    and contain concise JSON-serializable summaries rather than raw CSV rows.
    """
    if query is not None and (not isinstance(query, str) or not query.strip()):
        return _invalid_argument("query", "must be a non-empty string when provided")
    if category is not None and category not in CATEGORY_SLUG_TO_ID:
        return _invalid_argument("category", "must be a supported English category slug")
    if status is not None and status not in {"active", "discontinued", "coming_soon"}:
        return _invalid_argument("status", "must be active, discontinued, or coming_soon")
    if not isinstance(available_only, bool):
        return _invalid_argument("available_only", "must be a boolean")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
        return _invalid_argument("limit", "must be an integer between 1 and 20")

    minimum: Decimal | None = None
    if min_price_brl is not None:
        parsed_minimum = _parse_price(min_price_brl, "min_price_brl")
        if isinstance(parsed_minimum, dict):
            return parsed_minimum
        minimum = parsed_minimum

    maximum: Decimal | None = None
    if max_price_brl is not None:
        parsed_maximum = _parse_price(max_price_brl, "max_price_brl")
        if isinstance(parsed_maximum, dict):
            return parsed_maximum
        maximum = parsed_maximum

    if minimum is not None and maximum is not None and minimum > maximum:
        return _invalid_argument(
            "price_range",
            "min_price_brl must be less than or equal to max_price_brl",
        )

    folded_query = _fold_text(query) if query is not None else None
    category_id = CATEGORY_SLUG_TO_ID[category] if category is not None else None
    matches: list[Product] = []
    for product in sorted(store.products.values(), key=lambda item: item.product_id):
        if folded_query is not None and folded_query not in _fold_text(product.name):
            continue
        if category_id is not None and product.category_id != category_id:
            continue
        if minimum is not None and product.price_brl < minimum:
            continue
        if maximum is not None and product.price_brl > maximum:
            continue
        if status is not None and product.status != status:
            continue
        if available_only and not product.available:
            continue
        matches.append(product)

    returned = matches[:limit]
    filters: dict[str, object] = {
        "query": query.strip() if query is not None else None,
        "category": category,
        "min_price_brl": _money(minimum) if minimum is not None else None,
        "max_price_brl": _money(maximum) if maximum is not None else None,
        "status": status,
        "available_only": available_only,
        "limit": limit,
    }
    return {
        "count": len(returned),
        "total_matches": len(matches),
        "truncated": len(matches) > len(returned),
        "filters": filters,
        "products": [_product_summary(store, product) for product in returned],
    }


def get_order_status(
    store: CatalogStore,
    *,
    order_id: int,
) -> OrderLookupResult | ToolErrorResult:
    """Return one exact source-backed order without customer identity fields."""
    if isinstance(order_id, bool) or not isinstance(order_id, int) or order_id <= 0:
        return _invalid_argument("order_id", "must be a positive integer")

    order = store.orders.get(order_id)
    evidence = {"source_file": ORDERS_FILE}
    if order is None:
        return {
            "found": False,
            "order": None,
            "evidence": evidence,
            "error": {
                "code": "not_found",
                "field": "order_id",
                "message": f"No order found for order_id {order_id}.",
            },
        }

    items: list[OrderItemOutput] = []
    for item in order.items:
        product = store.products[item.product_id]
        items.append(
            {
                "product_id": item.product_id,
                "product_name": item.product_name,
                "quantity": item.quantity,
                "source": {"file": ORDER_ITEMS_FILE, "row": item.source_row},
                "product_source": {"file": PRODUCTS_FILE, "row": product.source_row},
            }
        )

    output: OrderOutput = {
        "order_id": order.order_id,
        "order_date": order.order_date.isoformat(),
        "status": order.status,
        "total_brl": _money(order.total_brl),
        "currency": "BRL",
        "payment_method": order.payment_method,
        "tracking_code": order.tracking_code,
        "estimated_delivery": (
            order.estimated_delivery.isoformat() if order.estimated_delivery else None
        ),
        "notes_pt": order.notes_pt,
        "items": items,
        "source": {"file": ORDERS_FILE, "row": order.source_row},
    }
    return {
        "found": True,
        "order": output,
        "evidence": evidence,
        "error": None,
    }


REGRET_WINDOW_DAYS = 7
DEFECT_WINDOW_DAYS = 30
ReturnReason = Literal["regret", "defect"]
ReturnBlocker = Literal["not_delivered", "cancelled", "missing_basis_date", "window_expired"]


class ReturnEligibilityOutput(TypedDict):
    """Deterministic return-window decision with its rule and dates."""

    order_id: int
    reason: ReturnReason
    eligible: bool
    blocker: ReturnBlocker | None
    rule_section: Literal["4.1", "4.2"]
    window_days: int
    basis: Literal["estimated_delivery", "order_date"]
    basis_date: str | None
    reference_date: str
    days_elapsed: int | None
    order_status: OrderStatus
    not_checked: list[str]
    source: SourceEvidence


class ReturnEligibilityResult(TypedDict):
    """Result of `check_return_eligibility`."""

    found: bool
    decision: ReturnEligibilityOutput | None
    evidence: dict[str, str]
    error: NotFoundDetail | None


def check_return_eligibility(
    store: CatalogStore,
    *,
    order_id: int,
    reason: ReturnReason,
    reference_date: date,
) -> ReturnEligibilityResult | ToolErrorResult:
    """Decide whether the policy time window still applies to one order.

    Rules (Store Policy v2.1): §4.1 regret = 7 calendar days after receipt; §4.2 defect
    exchange = 30 calendar days after purchase. `reference_date` comes from config, never
    from the system clock. The actual delivery date is not in the data, so
    `estimated_delivery` is used as the receipt date for delivered orders (basis is
    reported). Only the time window is decided here; product condition, purchase channel
    (§4.1 covers online purchases) and exclusions (§4.4) are listed in `not_checked`.
    """
    if isinstance(order_id, bool) or not isinstance(order_id, int) or order_id <= 0:
        return _invalid_argument("order_id", "must be a positive integer")
    if reason not in ("regret", "defect"):
        return _invalid_argument("reason", "must be 'regret' or 'defect'")
    if not isinstance(reference_date, date):
        return _invalid_argument("reference_date", "must be a date")

    evidence = {"source_file": ORDERS_FILE}
    order = store.orders.get(order_id)
    if order is None:
        return {
            "found": False,
            "decision": None,
            "evidence": evidence,
            "error": {
                "code": "not_found",
                "field": "order_id",
                "message": f"No order found for order_id {order_id}.",
            },
        }

    regret = reason == "regret"
    basis_date = order.estimated_delivery if regret else order.order_date
    window = REGRET_WINDOW_DAYS if regret else DEFECT_WINDOW_DAYS
    blocker: ReturnBlocker | None = None
    elapsed: int | None = None
    if order.status == "cancelled":
        blocker = "cancelled"
    elif order.status != "delivered":
        blocker = "not_delivered"
    elif basis_date is None:
        blocker = "missing_basis_date"
    else:
        elapsed = (reference_date - basis_date).days
        if elapsed > window:
            blocker = "window_expired"

    decision: ReturnEligibilityOutput = {
        "order_id": order.order_id,
        "reason": reason,
        "eligible": blocker is None,
        "blocker": blocker,
        "rule_section": "4.1" if regret else "4.2",
        "window_days": window,
        "basis": "estimated_delivery" if regret else "order_date",
        "basis_date": basis_date.isoformat() if basis_date else None,
        "reference_date": reference_date.isoformat(),
        "days_elapsed": elapsed,
        "order_status": order.status,
        "not_checked": [
            "product condition and original packaging",
            "purchase channel (section 4.1 covers online purchases)",
            "non-eligible items (section 4.4)",
            "actual delivery date (estimated_delivery is used as a proxy)",
        ],
        "source": {"file": ORDERS_FILE, "row": order.source_row},
    }
    return {"found": True, "decision": decision, "evidence": evidence, "error": None}
