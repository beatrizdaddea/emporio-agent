# Requirements Specification — Empório da Música Support Agent

**Status:** Approved, v2.

> [!NOTE]
> Sources inspected: the original assessment statement (`desafio_tecnico_ai_eng_artefact.pdf`, 3 pages, PT-BR, kept outside this repository), `data/políticas_da_loja.pdf` (policy manual v2.1, 8 pages), all 6 `data/*.csv`, `AGENTS.md`. Quotes are **English translations** of the PT-BR originals.

## 0. Decisions log

| # | Topic | Decision |
|---|---|---|
| DEC-1 | LLM provider | **OpenRouter free models** via its OpenAI-compatible API. Model ID, base URL and key come from `.env`. The chosen model must support tool calling |
| DEC-2 | Language | **English only**: code, docs, prompts, commits, agent replies, and example transcripts. Source data (product names, policy PDF) stays PT-BR as input; the agent answers in English. `AGENTS.md` line "replies to customers in PT-BR" will be updated (step 0) |
| DEC-3 | Personal data | **No personal data is used.** `customers.csv` isn't loaded. Order lookup is by `order_id` only and returns no customer fields |
| DEC-4 | Reference date | `REFERENCE_DATE=2026-03-23` (day after the last order, 2026-03-22) in `.env`/config, never `datetime.now()` |
| DEC-5 | Git | Incremental commit history (`D-02`) |
| DEC-6 | Interface | CLI only. **Frontend/UI is not mandatory** (see IF-01) |

## 1. Sources and priority scheme

| Tag | Source | Authority |
|---|---|---|
| `ST` | Original statement | **Only source of mandatory requirements** |
| `POL` | `políticas_da_loja.pdf` | Business content the agent must use correctly. Not a project requirement by itself |
| `AG` | `AGENTS.md` | Project engineering rules (self-imposed) |

- **P0**: explicit mandatory item in `ST`. If it's missing, the submission doesn't comply.
- **P1**: needed so a P0 item works correctly (from `POL`/`AG`, or explicitly *suggested* in `ST`).
- **P2**: optional; only once all P0/P1 items are done.

## 2. Traceability matrix

### 2.1 Functional requirements

| ID | Source (translated quote) | Pri | Implementation | Acceptance test | Evidence |
|---|---|---|---|---|---|
| FR-01 | ST: "A Python project of a text-message agent that serves Empório da Música customers." | P0 | `agent.py`: function-calling loop and CLI entry point | `uv run emporio` accepts a message, prints a reply, exits on `exit`/EOF. pytest runs the loop with a stub LLM | `src/emporio/agent.py`, `tests/test_agent.py` |
| FR-02 | ST: "Adopt a persona aligned with the store's identity and tone." POL §7.1: "informal but professional… like talking to a friend who knows music" | P0 | `prompts.py` system prompt: English replies, POL §7.1 tone, POL §7.2 flow (greet → understand → look up → answer → close) | Example transcripts: English, informal-professional tone, presents itself as the store's assistant (checklist in `examples/README.md`) | `src/emporio/prompts.py`, `examples/` |
| FR-03 | ST: "Receive and answer messages based on the provided context." POL §7.1: "never give prices, stock or deadlines without consulting the system" | P0 | Prompt rule: state only facts returned by tools; say so when nothing is found | pytest: unknown product/order → `found: false`. Example: unknown product → no invented price | `tests/test_tools.py`, `examples/` |
| FR-04 | ST: "Know when to query data (e.g., availability, prices, order status)" | P0 | `tools.py`: `search_products` (with English category enum mapped to `category_id`), `get_product`, `get_order_status` (structured dicts) | pytest on real CSVs: "Takamine GD20" → id 95, R$ 2199, stock 5; violões ≤ R$ 1000 → 14 rows, 12 active with stock > 0; order 8 → `shipped`, `BRJL5544332BR`. Transcript shows the tool trace | `tests/test_tools.py`, `examples/` |
| FR-05 | ST: "…and when to query policies (e.g., exchange rules, hours, payment methods)" | P0 | `retrieval.py`: extract the PDF at runtime, split into 28 section/subsection chunks; `search_policy(query)` tool (BM25 + EN→PT-BR glossary, top-3 passages with section/page refs) | pytest offline eval: 25 dev + 12 held-out questions retrieve the gold passage with a verbatim snippet in the top 3; 5 unsupported questions return no supporting passage (`docs/retrieval.md`) | `tests/test_retrieval.py`, `tests/test_policy_eval.py`, `examples/` |
| FR-06 | ST: "Handle questions outside the store's scope appropriately." POL §1/§7.1: instruments only; accessories politely redirected | P0 | Prompt rules for off-topic and accessory requests | ≥ 1 transcript: off-topic plus accessory request → polite refusal and redirect, no tool fabrication | `examples/`, `src/emporio/prompts.py` |
| FR-07 | ST: "Conversation history persistence: implement if it makes sense for the user experience." | P1 in-session / P2 across runs | LangGraph in-memory checkpoints plus `history.py` session transcript | pytest: second turn receives the first turn and separate sessions stay isolated (stub LLM). README justifies not persisting across runs | `tests/test_agent.py`, README |
| FR-08 | ST: "Data handling: do whatever data treatment you judge necessary." | P1 | Typed loaders, `specs` JSON parse, empty → `None`; steps recorded in `docs/data-notes.md` | pytest: typed values; `data/` hashes unchanged | `docs/data-notes.md`, tests |
| FR-09 | POL §6.2: promo price shown with original price and %; promotions not cumulative; PIX 5% not applied to promo prices. POL §7.3: expired promotion → transparent | P1 | `get_product` adds `active_promotion {percent, final_price}` only if `is_active == 1` | pytest: product 94 → 8%, final 5519.08; product 95 → no active promo | `tests/test_tools.py` |
| FR-10 | POL §7.3: out of stock → suggest alternatives; discontinued → offer equivalents | P1 | Tool output includes `status`, `stock_quantity`, `available` | pytest: 96 → `available: false` (active, stock 0); 113 → `discontinued`; 130 → `coming_soon` | `tests/test_tools.py` |
| FR-11 | POL §4.1: regret return within 7 calendar days after receipt; §4.2: defect exchange within 30 days after purchase | P1 | `check_return_eligibility(order_id)` uses `REFERENCE_DATE` (2026-03-23) | pytest: order 7 (delivered, est. 2026-02-17) → regret not eligible (34 days), defect not eligible (purchased 2026-02-03, 48 days); order 8 (`shipped`) → not delivered yet; order 17 (`cancelled`) → not applicable | `tests/test_check_return.py`, `examples/` |

### 2.2 Non-functional requirements and constraints

| ID | Source | Pri | Implementation | Acceptance test | Evidence |
|---|---|---|---|---|---|
| NFR-01 | ST: "Only mandatory technical constraint: Python as the main language." | P0 | Python codebase | Repo contains Python plus docs only | repo |
| NFR-02 | ST: "…the focus is the agent working correctly." | P0 | Deterministic tools, tests, real transcripts | `uv run pytest` green; examples come from real runs | test output, `examples/` |
| NFR-03 | ST: model/provider free choice, must be justified | P0 | OpenRouter (DEC-1); `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL` in `.env` | `.env.example` present; no key in git; README "Model" section | `.env.example`, README |
| NFR-04 | DEC-3, POL §9 (LGPD) | P1 | `customers.csv` not loaded; order output excludes `customer_id` | pytest: `get_order_status` result has no `customer_id`/name/email/phone keys | `tests/test_tools.py` |
| NFR-05 | DEC-2 | P1 | Prompt: always reply in English | All transcripts in English | `examples/` |
| NFR-06 | AG | P1 | Tool output is data, never instructions (JSON tool results) | pytest: instruction-like text in a field is returned verbatim as data | `tests/test_tools.py` |
| NFR-07 | AG | P1 | `ruff check` + `pytest` before "done" | Output pasted in each task report | — |

### 2.3 Expected interfaces

| ID | Source | Pri | Decision |
|---|---|---|---|
| IF-01 | ST: "Interaction interface: CLI, notebook, API, or simple UI — the focus is the agent working correctly." | P0 (at least one) | **CLI** (`uv run emporio`) |
| IF-02 | ST: "Framework(s)/approach: RAG, function calling, ReAct, SQL agent, hybrid, etc." | P0 (justify) | **Hybrid**: function calling over CSVs plus subsection-level lexical policy retrieval exposed as a tool (`search_policy`). No embeddings or vector DB (measured: not needed; see `docs/retrieval.md`). See `docs/adr/0001-agent-architecture.md` |

> [!IMPORTANT]
> **Frontend/UI is NOT mandatory.** The statement lists UI as one of four equal options. MVP = CLI. A UI is P2 and only gets built if all P0/P1 items are complete.

### 2.4 Expected deliverables

| ID | Source (translated) | Pri | Acceptance test | Evidence |
|---|---|---|---|---|
| D-01 | "Link to your project's public GitHub repository." | P0 | URL opens logged out | URL in email |
| D-02 | "Keep a commit history with real progress — don't force-push everything in a single commit." | P0 | `git log` ≥ 1 commit per feature; no force-push | git history |
| D-03 | "Don't change anything in the repository after the delivery date and time." | P0 | Repository frozen after submission | `git log -1 --format=%cI` |
| D-04 | README: "All instructions needed to run the project: environment setup, model provider, commands, etc." | P0 | Fresh clone + README only → CLI answers one question | `README.md` |
| D-05 | README: "Justification of technical decisions: framework, LLM, retrieval architecture, prompt strategy, etc." plus the five decision rows | P0 | One README subsection per item (7-heading checklist) | `README.md` |
| D-06 | README: "Known limitations: and what you would do with more time." | P0 | Section present, includes §4 data issues | `README.md` |
| D-07 | README: "Use of coding assistants… explain which one and how you used it." | P0 (applies) | Section names the tool and workflow | `README.md` |
| D-08 | "Assume a reasonable interpretation, document the assumption in the README and move on." | P0 | README "Assumptions" mirrors §5 and §0 | `README.md` |
| D-09 | "Include 3 to 5 conversations in .md or .txt, or image file, covering varied scenarios." | P0 | 3–5 English files in `examples/`, distinct scenario types | `examples/*.md` |
| D-10 | "At least one must show the agent handling a non-trivial situation — querying data in real time or applying policy rules." | P0 | ≥ 1 transcript with a tool trace and a policy decision (return eligibility) | `examples/*.md` |
| D-11 | Suggested scenarios: guitars ≤ R$1000; store address; Takamine GD20 price; regret/return | P1 | Each covered by an example or test | `examples/`, `tests/` |
| D-12 | "Reply to the email with the public repository link." | P0 (manual, you) | Email sent | out of repo |

### 2.5 Evaluation criteria (stated, no numeric rubric)

"We will evaluate your logic, clarity and initiative." / "More interested in how you solve the problem and make decisions than in a perfect solution." **No metrics will be reported unless actually measured.**

## 3. Input data schema (as found)

All CSVs are UTF-8, no BOM, comma-separated, named `desafio_tecnico_ai_eng - <table>.csv`.

| Table | Rows | Columns | Used? | Notes |
|---|---|---|---|---|
| categories | 9 | `category_id, name, description` | Yes | Categories 6, 7, 8 have no products |
| products | 65 | `product_id, price_brl, name, category_id, description, stock_quantity, status, specs, created_at` | Yes | IDs 81–145 contiguous; row 145 out of order. active 62, discontinued 2 (113, 136), coming_soon 1 (130). `specs` = JSON, 4 key schemas. Price R$ 159.90–19,567 |
| promotions | 25 | `promotion_id, product_id, discount_percent, description, is_active` | Yes | 4 active (products 90, 94, 121, 127). No dates. Products 93/96/99 have 2 rows each (all inactive) |
| orders | 20 | `order_id, customer_id, order_date, status, total_brl, payment_method, tracking_code, estimated_delivery, notes` | Yes, except `customer_id` | delivered 7, shipped 1, confirmed 4, pending 4, cancelled 4. Dates 2025-10-15 → 2026-03-22. 12 lack tracking/estimate. No actual delivery date |
| order_items | 22 | `order_id, quantity, product_id` | Yes | No unit price; orders 15 and 20 have 2 items |
| customers | 50 | `customer_id, name, phone, email, city` | **No** (DEC-3) | — |

Policy PDF: 10 numbered sections; the text extracts cleanly with `pypdf`.

## 4. Data and policy inconsistencies

| # | Finding | Handling (in `docs/data-notes.md`) |
|---|---|---|
| 1 | Order total ≠ items × current price: order 3 (3450 vs 3498), order 20 (1400 vs 1488) | Report `total_brl` as charged |
| 2 | Order 3 contains product 130, now `coming_soon` | Report as-is |
| 3 | Products 135–144: brand in `name` ≠ brand in `description` | `name` is authoritative; listed as a limitation |
| 4 | Email: cover `contato@emporiodamusica.com.br` vs §1.2 `contato@empóriodamusica.com.br` | Recorded only; agent quotes retrieved text |
| 5 | Two WhatsApp numbers (§1.2 vs §7) | Recorded only; not a requirement, no special handling |
| 6 | Credit-card minimum installment: table R$ 100 vs §3.1 tiers | Agent quotes the §3.1 rules, doesn't compute |
| 7 | "300+ instruments" in policy vs 65 in CSV | Answer from CSV only |
| 8 | No actual delivery date | `estimated_delivery` used as a proxy for delivered orders; stated in README |
| 9 | Using `REFERENCE_DATE` 2026-03-23, no order is inside a return window | Return example demonstrates a correct "not eligible" decision with reasons |
| 10 | Holidays "closed" but no holiday list | Limitation |

## 5. Assumptions (mirrored in README)

- A1. CSV snapshot = "the system"; "real-time" = queried at runtime from files.
- A2. A promotion is valid iff `is_active == 1`.
- A3. Available = `status == active` and `stock_quantity > 0`.
- A4. Anyone with an order ID may see its status, dates, tracking and items; no customer data is exposed (DEC-3).
- A5. No side-effect actions (no ordering, cancelling, complaint registration); complaints are redirected to the human team (POL §7.3).
- A6. Policy content is in PT-BR; the agent translates it into English replies, and product names are kept verbatim.

## 6. Remaining risks

| ID | Risk | Mitigation |
|---|---|---|
| R-1 | OpenRouter free models: rate limits, availability changes, uneven tool-calling support | Model ID in `.env`; verify tool calling with one smoke call before step 7; README notes how to switch model |
| R-2 | Live LLM calls need network (outside the sandbox) | Unit tests use a stub LLM; only example generation and smoke tests call OpenRouter |
| R-3 | D-02 needs real commit history | Incremental commits per feature |
| R-4 | `AGENTS.md` said PT-BR replies | Resolved in step 0: updated to English replies (DEC-2) |

## 7. One-page minimum compliant MVP

**Scope:** a Python CLI chat agent that answers Empório da Música customers in English, using an OpenRouter free model with function calling over the CSVs and section retrieval over the policy PDF. No personal data.

| Component | File | Covers |
|---|---|---|
| Config (`.env`: OpenRouter key/model/base URL, `REFERENCE_DATE`, data dir) | `config.py`, `.env.example` | NFR-03, FR-11 |
| Tools: `search_products`, `get_product`, `get_order_status`, `check_return_eligibility` | `tools.py` | FR-04, FR-08–11, NFR-04 |
| Policy retrieval: `search_policy` | `retrieval.py` | FR-05 |
| Persona, scope, grounding, English-only rules | `prompts.py` | FR-02, FR-03, FR-06, NFR-05 |
| In-session history | `history.py` | FR-07 |
| Agent loop and CLI | `agent.py` | FR-01, IF-01 |
| Tests (one per tool plus agent loop with a stub LLM) | `tests/` | NFR-02 |
| 4–5 real English transcripts (guitars ≤ R$1000, address, Takamine price, return eligibility, off-topic/accessory) | `examples/` | D-09–D-11 |
| README and `docs/data-notes.md` | root, `docs/` | D-04–D-08 |

**Out of MVP:** UI, persistent cross-run history, vector DB, order mutations, customer data, production authentication/authorization.

**Definition of done:** `uv run ruff check` clean; `uv run pytest` green; fresh-clone README dry run works; every P0 row ticked with evidence; pushed to a public repo.

## 8. Prioritized plan (one small change = one commit)

| # | Task | Files | Verify |
|---|---|---|---|
| 0 | Requirements spec; update AGENTS.md language line | `docs/requirements.md`, `AGENTS.md` | Review |
| 1 | Scaffold: `pyproject.toml` (uv, ruff, pytest, openai SDK, pypdf), `.gitignore`, `.env.example`, `config.py` | root, `src/emporio/config.py`, `tests/test_config.py` | ruff, pytest |
| 2 | CSV loaders and cleaning plus data notes | `tools.py`, `docs/data-notes.md`, tests | pytest |
| 3 | Product tools | `tools.py`, tests | pytest |
| 4 | Order status and return eligibility | `tools.py`, tests | pytest |
| 5 | Policy retrieval tool | `retrieval.py`, tests | pytest |
| 6 | System prompt | `prompts.py` | review |
| 7 | Agent loop, history, CLI, OpenRouter smoke call | `agent.py`, `history.py`, tests | pytest and manual smoke test |
| 8 | Real example transcripts | `examples/` | checklist |
| 9 | README | `README.md` | fresh-clone dry run |
| 10 | Compliance pass, push, freeze | — | matrix ticked |
