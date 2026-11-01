# Data Schema, Cleaning Rules & Anomalies (`docs/data-notes.md`)

All source files in `data/` are kept untouched in their original PT-BR format (`AGENTS.md`, `FR-08`). All normalization, type conversion, and joining happen in memory at startup inside `src/emporio/tools.py`.

---

## 1. Source Files & Schemas (`data/*.csv`)

All CSV files are UTF-8 encoded without BOM, comma-separated, and named `desafio_tecnico_ai_eng - <table>.csv`.

| File | Rows | Raw Columns | Loaded? |
|---|---|---|---|
| `desafio_tecnico_ai_eng - categories.csv` | 9 | `category_id, name, description` | Yes |
| `desafio_tecnico_ai_eng - products.csv` | 65 | `product_id, price_brl, name, category_id, description, stock_quantity, status, specs, created_at` | Yes |
| `desafio_tecnico_ai_eng - promotions.csv` | 25 | `promotion_id, product_id, discount_percent, description, is_active` | Yes |
| `desafio_tecnico_ai_eng - orders.csv` | 20 | `order_id, customer_id, order_date, status, total_brl, payment_method, tracking_code, estimated_delivery, notes` | Yes (`customer_id` dropped) |
| `desafio_tecnico_ai_eng - order_items.csv` | 22 | `order_id, quantity, product_id` | Yes |
| `desafio_tecnico_ai_eng - customers.csv` | 50 | `customer_id, name, phone, email, city` | **No** (`DEC-3`, `NFR-04`) |

---

## 2. English Category Slug Mapping (`CATEGORY_SLUG_TO_ID`)

Because customer conversations and tool schemas are in English (`DEC-2`) while the CSV data is in PT-BR, `src/emporio/tools.py` maps deterministic English category slugs to `category_id`:

| English Category Slug | `category_id` | PT-BR Name in `categories.csv` | Products in `products.csv` |
|---|---|---|---|
| `electric_guitars` | `1` | Guitarras | 5 |
| `bass` | `2` | Baixos | 4 |
| `drums_percussion` | `3` | Baterias e Percussão | 3 |
| `keyboards_pianos` | `4` | Teclados e Pianos | 3 |
| `acoustic_classical_guitars` | `5` | Violões | 35 |
| `woodwinds` | `6` | Instrumentos de Sopro (Madeiras) | 0 |
| `brass` | `7` | Instrumentos de Sopro (Metais) | 0 |
| `orchestral_strings` | `8` | Cordas Orquestrais | 0 |
| `ukuleles` | `9` | Ukuleles | 15 |

---

## 3. In-Code Cleaning & Normalization Steps (`src/emporio/tools.py`)

1. **Privacy & PII Exclusion (`DEC-3`, `NFR-04`):**
   - `desafio_tecnico_ai_eng - customers.csv` is never opened or read.
   - When reading `orders.csv`, the `customer_id` column is discarded before constructing `Order` objects.
2. **Whitespace & Empty String Normalization:**
   - All string fields are stripped of leading/trailing whitespace.
   - Optional fields on orders (`tracking_code`, `estimated_delivery`, `notes`) are converted from `""` to `None`.
3. **Type Conversions:**
   - Integer fields: `category_id`, `product_id`, `stock_quantity`, `promotion_id`, `discount_percent`, `order_id`, `quantity`.
   - Exact decimal currency fields: `products.price_brl`, calculated promotional prices, and
     `orders.total_brl`. Tool responses serialize money as two-decimal strings with an explicit
     `currency="BRL"` field.
   - Boolean flags: `promotions.is_active` (`"1"` → `True`, `"0"` → `False`).
   - ISO dates (`YYYY-MM-DD`): `products.created_at`, `orders.order_date`, and non-empty `orders.estimated_delivery` are parsed into `datetime.date`.
4. **JSON Parsing of Product `specs`:**
   - Every product's `specs` string is parsed via `json.loads()` into a `dict[str, str]`. All 65 rows contain valid JSON across 4 category-specific key schemas.
5. **Product Ordering:**
   - In `products.csv`, `product_id=145` (*Fender Stratocaster American Pro II*) appears before `product_id=131`. Products are sorted ascending by `product_id` (`81..145`) upon loading for deterministic ordering.
6. **Computed Product Availability (`FR-10`, Store Policy §7.3):**
   - `available` is computed as `status == "active" and stock_quantity > 0`.
   - Specifically:
     - `product_id=96` (*Giannini GF-3D Dreadnought Sunburst*) has `status="active"` and `stock_quantity=0` → `available=False`.
     - `product_id=113` (*Shelby SN-7C 7 Cordas Nylon Natural*) has `status="discontinued"` and `stock_quantity=0` → `available=False`.
     - `product_id=136` (*Ibanez Bass 2X Electric Bass*) has `status="discontinued"` and `stock_quantity=13` → `available=False`.
     - `product_id=130` (*Kala KA-ABP-CTG Barítono Cedar*) has `status="coming_soon"` and `stock_quantity=2` → `available=False`.
7. **Active Promotion Joining & Price Calculation (`FR-09`, Store Policy §6.2, §7.3):**
   - `promotions.csv` has 25 rows, of which only 4 have `is_active == 1` (products `90`, `94`, `121`, `127`).
   - Inactive promotions (`is_active == 0`, including duplicate inactive entries on products `93`, `96`, `99`) are not attached as `active_promotion` on the product.
   - For the 4 active promotions, `promo_price_brl` is computed as `round(price_brl * (100 - discount_percent) / 100, 2)`.
8. **Order Items Resolution:**
   - `order_items.csv` rows are grouped by `order_id` in file order and enriched with the referenced product's `name` from `products.csv`.
9. **Schema and Identifier Validation:**
   - Every loaded CSV header must exactly match the inspected source schema above. Missing,
     additional, reordered, or malformed-width columns fail closed with `DataSchemaError`.
   - Primary identifiers (`category_id`, `product_id`, `promotion_id`, and `order_id`) must be
     unique. Duplicate identifiers, multiple active promotions for one product, and orphan
     product/order references fail closed with `DataIntegrityError`; records are never silently
     overwritten.

### Product source profile

- `products.csv` has 65 records, unique product IDs and names, and no missing values or surrounding whitespace in any field.
- Its `price_brl` values use an ungrouped decimal-point format with no currency symbol. Twelve values include a decimal point; the observed range is `159.90` through `19567.00` after normalization.
- Catalog code parses product prices as `Decimal`, applies inclusive price boundaries, and serializes every returned amount as a two-decimal string with `currency="BRL"`.
- The BRL currency is explicit in the source column name (`price_brl`); input filters additionally accept controlled PT-BR strings such as `R$ 1.000,00`.

### Read-only catalog contracts

- `get_product` accepts exactly one positive `product_id` or complete `exact_name`. Exact-name matching ignores case, accents, and surrounding whitespace, but it does not use fuzzy or partial matching.
- `search_products` supports a name substring, English category slug, inclusive price range, source status, computed availability, and a maximum result limit of 20.
- Search results are always ordered by ascending `product_id`. They return concise JSON-serializable summaries rather than the complete CSV or product descriptions.
- Exact results include the source description and specifications. Both exact and search results include source filename and one-based CSV row evidence.
- Not-found lookups return `found=false`; malformed inputs return a structured `invalid_argument` error without querying arbitrary data or generating SQL.

### Order source profile and read-only contract

- `orders.csv` has 20 unique `order_id` values. `order_items.csv` has 22 rows: orders 15 and 20
  have two items and every other order has one. There are no orphan order or product references.
- `tracking_code` and `estimated_delivery` are empty on 12 orders; `notes` is empty on 16.
  Empty optional source fields become `None` and are returned as JSON `null`; no missing status,
  tracking event, delivery date, or note is inferred.
- `get_order_status(store, order_id=...)` accepts one positive integer and performs an exact
  identifier lookup. Unknown IDs return `found=false`, `order=null`, and a structured
  `not_found` error. Malformed IDs return `invalid_argument`.
- Results preserve `order_date`, `status`, historical `total_brl`, `payment_method`, optional
  tracking/estimated-delivery/note values, and line-item order. Each order and line item includes
  CSV filename/row evidence; joined product names also include their product-row evidence.
- `customer_id` is deliberately omitted and `customers.csv` is never loaded. The demo assumes
  that possession of an order ID permits lookup (`A4`), which is **not production-ready
  authorization**. A production service must authenticate the customer and verify order ownership
  before returning any order data. No customer file content may be sent to a third-party LLM.

---

## 3b. Policy PDF Extraction & Cleaning (`src/emporio/retrieval.py`)

Source: `data/políticas_da_loja.pdf`, 180,519 bytes, SHA-256
`b7527f96896929f4ba929de117651c6717e25b7a3b92b34bc54d5ba32f6156f7`, 8 pages, producer
`Skia/PDF m150 Google Docs Renderer`, not encrypted. **Born-digital:** every page has a text layer
and no images, so no OCR is involved. The file is never modified. All steps run in memory on every
load, and nothing is cached on disk.

1. **Text extraction:** `pypdf` `page.extract_text()` (plain mode) per page.
2. **Whitespace collapse:** the extractor separates every word with `\n \n`; all whitespace runs
   become one space. Side effect: §1.2 phone reads `(67) 3341 - 4444` (kept verbatim).
3. **Bullet fix:** the control character `\x07` used as the bullet in §5.1 becomes `•`.
4. **Running header/footer removal:** the leading `Empório da Música Manual de Políticas e
   Procedimentos` and trailing `Página N` on each page are stripped.
5. **Text-layer check:** any page with < 50 characters after normalization raises
   `PolicyExtractionError` listing the pages (scanned/image-only PDFs are rejected, never guessed).
6. **Cover exclusion:** page 1 is checked and used to read `Versão 2.1`, but it isn't chunked.
7. **Chunking:** the text is split at the 28 known heading titles (`POLICY_HEADINGS`), matched in
   order. A missing heading fails fast. Generic `^\d+\.` splitting is avoided because §7.2 contains
   a numbered list (`1. Saudação` … `5. Fechamento`). Each chunk keeps the pages it spans (§5.2 →
   4–5, §7.2 → 6–7, §9 → 7–8).
8. **Tokenization for ranking only:** casefold + accent fold, PT/EN stopwords, trailing-`s` strip,
   6-character prefix stem. Returned `text_pt` is always the verbatim normalized chunk.

---

## 4. Documented Data & Policy Anomalies

| # | Anomaly | Handling in Code / Agent |
|---|---|---|
| 1 | **Order total vs. sum of current item prices:** `order_id=3` has `total_brl=3450.0` (2 × product 130 at current `1749.0` = `3498.0`); `order_id=20` has `total_brl=1400.0` (products 107 + 84 at current prices = `1488.0`). | `Order.total_brl` preserves the historical amount charged in `orders.csv`; totals are never recomputed from current catalog prices. |
| 2 | **Delivered order contains `coming_soon` item:** `order_id=3` (`delivered`) references `product_id=130`, whose current catalog status is `coming_soon`. | Reported as recorded in `orders.csv` / `order_items.csv`. |
| 3 | **Brand mismatch between `name` and `description` (`product_id` 135–144):** e.g., `135` is named *Music Man Bass 1X Electric Bass* but its description says *Contrabaixo elétrico Fender Jazz Bass*; `142` is named *Teclado Sintetizador Korg Synth 1 Pro* but its description says *Sintetizador workstation Roland*. | `Product.name` is treated as the authoritative product name; noted as a dataset limitation in `README.md`. |
| 4 | **Empty categories:** Categories `6` (*Madeiras*), `7` (*Metais*), and `8` (*Cordas Orquestrais*) exist in `categories.csv` but have zero rows in `products.csv`. | Category enum still includes `woodwinds`, `brass`, and `orchestral_strings`; searches return 0 results cleanly. |
| 5 | **Promotions have no start/end dates:** `promotions.csv` only has `is_active` (`0` or `1`). | `is_active == 1` is the sole criterion for an active promotion (`A2`). |
| 6 | **Missing actual delivery date in `orders.csv`:** All 7 `delivered` orders have `estimated_delivery` populated, but there is no `delivered_at` column. | Return eligibility (`FR-11`) uses `estimated_delivery` as the proxy delivery date for `delivered` orders and explicitly labels `basis="estimated_delivery"`. |
| 7 | **Store email spelling in policy PDF:** Cover page says `contato@emporiodamusica.com.br` (ASCII); §1.2 says `contato@empóriodamusica.com.br` (with accent). | Recorded here; agent cites the policy section text. |
| 8 | **WhatsApp number in policy PDF:** §1.2 lists `(67) 3341-4444` under Phone/WhatsApp; §7 lists `(67) 3321-4500`. | Recorded here for completeness. Retrieval caveat: the query `WhatsApp` ranks §7, §2, §5.3, so §1.2 isn't in the top 3 and the agent may see only one number (`docs/retrieval.md` §6). |
| 9 | **Credit-card minimum installment inconsistency in policy PDF:** §3 table says minimum installment `R$ 100,00`; §3.1 lists tiered rules (`≤3x` min `R$ 50,00`, `4x–6x` min `R$ 80,00`, `7x–12x` min `R$ 100,00`). | §3 and §3.1 are separate chunks. Installment queries rank both in the top 2, so the agent sees the table and the detailed §3.1 tiers together. |
| 10 | **Catalog size claim in policy PDF:** §1 claims "more than 300 instruments", whereas `products.csv` has 65 products. | Catalog tools query `products.csv` exclusively. |
