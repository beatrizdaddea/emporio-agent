# Empório da Música Support Agent

English-language command-line support assistant for the fictional Empório da Música
instrument store. It uses a configurable OpenRouter free model to choose between five read-only,
source-backed tools for catalog, order, return-window, and store-policy questions.

## Quick start

Requirements: [uv](https://docs.astral.sh/uv/) and an OpenRouter API key.

```bash
uv python install 3.12
uv sync --locked
cp .env.example .env
```

On Windows PowerShell, use `Copy-Item .env.example .env`. Put the key in the local `.env`; never
commit that file. The configured model must be an explicit OpenRouter ID ending in `:free`.

Validate configuration without a network request, then start the chat:

```bash
uv run emporio --check-config
uv run emporio --trace
```

`--trace` writes tool names and concise source references to standard error. In the interactive
CLI, type an English question, then `exit` or `quit` to finish. Example prompts:

```text
Which acoustic/classical guitars are available for R$1,000 or less?
What's the status of order 8?
What time do you open on Saturdays?
```

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `OPENROUTER_API_KEY` | Local secret used only for model requests | required |
| `OPENROUTER_MODEL` | Explicit OpenRouter free model ID | `google/gemma-4-31b-it:free` |
| `OPENROUTER_BASE_URL` | OpenAI-compatible endpoint | `https://openrouter.ai/api/v1` |
| `REFERENCE_DATE` | Deterministic date for return-window decisions | `2026-03-23` |
| `DATA_DIR` | Supplied CSV and policy directory | `data` |

`REFERENCE_DATE`, rather than the computer clock, is used for every return deadline.

## Architecture and technical decisions

### Agent framework and orchestration

The agent uses `langchain.agents.create_agent` (LangGraph internally) because the required flow is
a bounded model↔tools loop with in-session checkpoints. A custom graph would add routing code
without a second workflow branch. Per turn, middleware allows at most five model calls and six
tool calls; the graph recursion limit is a final backstop.

The model can call exactly these read-only tools:

- `search_products`
- `get_product`
- `get_order_status`
- `check_return_eligibility`
- `search_policy`

There is no generated SQL, transaction API, order mutation, customer lookup, or arbitrary tool
dispatch. Tool arguments are validated with strict Pydantic schemas, and unexpected tool errors
become non-sensitive structured failures.

### Model provider

OpenRouter was selected because the assessment permits provider choice and exposes an
OpenAI-compatible API with explicit free model variants. The model ID remains configuration, not
business logic. Paid IDs are rejected. SDK retries and provider fallback are disabled because
failed free-tier requests consume scarce quota and silently changing models would make evaluation
less reproducible.

The deterministic system works offline, but the latest genuine model run received HTTP 429 before
tool selection. Live tool calling and the required conversation set therefore remain unverified;
see `docs/evaluation-results.md` and `docs/llm-smoke.md`.

### Data and function calling

CSV schemas, encoding, separators, nulls, identifiers, references, prices, and statuses are
validated at load time. Monetary values use `Decimal` internally and two-decimal BRL strings in
tool output. Every returned record carries its source filename and row. `customers.csv` is never
loaded, and order output excludes `customer_id` and customer contact fields.

Tool output is JSON data, never executable instructions. Catalog and order logic is independent
of the LLM, deterministic, and covered without an API key.

### Policy retrieval

The eight-page PT-BR policy PDF is extracted at startup and split into 28 numbered section and
subsection chunks. Retrieval uses deterministic BM25 plus a small English→PT-BR glossary and
returns the top three verbatim passages with section, page, document version, and hash evidence.
Embeddings and a vector database were rejected for this 28-chunk corpus: the measured held-out
hit@3 already meets the documented threshold without network calls or a model download.

### Prompt strategy and trust boundaries

The system prompt contains persona, English-only, scope, grounding, citation, privacy, and
untrusted-data rules, but no store facts. Prices, stock, orders, dates, and policies must come from
tool results in the current conversation. Unsupported facts must be reported as not found.

Policy text and product descriptions are placed in tool messages and explicitly labeled as data.
This reduces prompt-injection risk but does not prove resistance by every model; the real-model
injection case is still pending.

### Conversation history

LangGraph's in-memory checkpointer keeps messages under a random thread ID for one CLI session.
Separate sessions do not share state, and nothing persists across program runs. Durable history
was deferred because the assessment does not require accounts or a production identity model.

## Assumptions

- The CSV/PDF snapshot is the store system; "real time" means reading that snapshot at runtime.
- A promotion is active exactly when `is_active == 1`.
- Available means `status == "active"` and `stock_quantity > 0`.
- For this demo, possession of an order ID permits a read-only lookup. This is not production
  authorization.
- The assistant cannot place, cancel, modify, or refund orders, or register complaints.
- Product names remain verbatim PT-BR source data; customer-facing prose is English.
- Because no actual delivery timestamp exists, delivered orders use `estimated_delivery` as an
  explicitly disclosed proxy for the seven-day regret window.

## Tests and evaluation

Offline checks require no key or network:

```bash
uv run ruff check .
uv run pytest
```

The latest recorded offline run passed 156 tests with seven live tests deselected. The labeled
core cases are in `tests/evaluation_cases.json`; policy retrieval has separate dev, held-out,
unsupported, and trap cases.

Live evaluation is opt-in, uses one model, has no retries/fallback, and enforces an 18-request
ceiling:

```bash
uv run pytest -m live tests/live/test_live_flows.py -q -s
```

The latest attempt stopped after one HTTP 429. It did not produce successful assessment
conversations. Do not treat offline scripted replies or the preserved 429 artifact as successful
examples.

## Known limitations and next steps

- The required 3–5 genuine conversations are incomplete because the latest provider call was rate
  limited. They must be captured after quota is available.
- Real-model tool selection, final-answer faithfulness, and prompt-injection resistance have not
  passed live evaluation.
- Order IDs are sequential and there is no authentication. A production service must authenticate
  users and verify order ownership before exposing tracking or payment information.
- The policy glossary is hand-maintained; unsupported wording can retrieve a lexically related but
  non-answering passage. The prompt must still enforce the evidence contract.
- There is no actual delivery timestamp, holiday calendar, transaction API, durable history, or
  human handoff integration.
- Historical order totals intentionally are not recomputed from current catalog prices. Some
  supplied product descriptions conflict with their product names; names are treated as
  authoritative. Full anomalies are in `docs/data-notes.md`.
- Free-model availability and quotas can change. With more time, compare multiple explicit free
  tool-capable models on the same labeled set, add authenticated order access, and add history
  trimming for long sessions.

## Use of coding assistants

OpenAI Codex was used to inspect the supplied schemas, implement deterministic tools and tests,
run local verification, and record observed provider failures. Antigravity was used for
requirements/test-matrix design and independent review. Work was performed in small,
human-approved tasks: each task proposed signatures/files/tests first, preserved the original
`data/` files, and recorded failures rather than rewriting outputs to appear successful.

## Project structure

```text
src/emporio/   Agent, prompts, tools, retrieval, configuration, and session state
tests/         Offline suite plus explicitly marked optional live evaluation
data/          Supplied immutable CSV files and policy PDF
docs/          Requirements, ADR, data notes, retrieval and evaluation evidence
examples/      Genuine live attempts and their review status
```
