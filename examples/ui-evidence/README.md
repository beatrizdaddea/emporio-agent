# UI End-to-End Evidence

This directory contains browser-recorded evidence for the Empório da Música Streamlit UI.
All six scenarios were executed on November 2, 2026, in the explicitly selected
`Local Deterministic Agent (100% Offline)` mode.

> **Execution classification:** deterministic/mocked model orchestration, not a live OpenRouter
> execution. The browser, Streamlit UI, LangGraph loop, five application tools, supplied CSV data,
> and PDF policy retrieval are real. The model decision layer is
> `local/deterministic-grounded-agent:free`; it makes no provider or network request.

## Coverage

| ID | Scenario | Status | Critical evidence | Screenshot | Video |
|---|---|---|---|---|---|
| 01 | Product search (PT-BR) | PASS | 12 available violões at or below R$1,000; catalog sources | [PNG](screenshots/01-product-search-pt.png) | [WebM](videos/01-product-search-pt.webm) |
| 02 | Product search (English) | PASS | English answer with the same catalog names and BRL prices | [PNG](screenshots/02-product-search-en.png) | [WebM](videos/02-product-search-en.webm) |
| 03 | Store return policy | PASS | Policy §4 and §4.1 retrieved from page 4 | [PNG](screenshots/03-store-policy.png) | [WebM](videos/03-store-policy.webm) |
| 04 | Multi-tool return question | PASS | Order 4 + eligibility + policy evidence | [PNG](screenshots/04-multi-tool-conversation.png) | [WebM](videos/04-multi-tool-conversation.webm) |
| 05 | Out-of-scope question | PASS | Scoped refusal, no tool call, no unrelated answer | [PNG](screenshots/05-out-of-scope.png) | [WebM](videos/05-out-of-scope.webm) |
| 06 | PT-BR to English follow-up | PASS | Both turns displayed; scripted follow-up answered in English | [PNG](screenshots/06-language-switch.png) | [WebM](videos/06-language-switch.webm) |

## Scenario results

### 01 — Product search (PT-BR)

- **Objective:** submit a PT-BR catalog question through the chat and validate grounded names,
  prices, availability, and response language.
- **Input:** `Quais violões vocês têm por até R$ 1.000?`
- **Expected:** `search_products` uses the acoustic/classical category, a R$1,000 maximum, and the
  available-only filter; the answer is in PT-BR.
- **Actual:** the UI showed 12 active, in-stock catalog products. Deterministic checks included
  `Tagima Memphis AC-39 Nylon Natural — R$ 429.90` and
  `Yamaha C40 Nylon Natural — R$ 599.90`. Zero-stock product 96 and discontinued product 113 were
  absent. The expanded evidence showed the expected tool arguments and CSV source rows.
- **Status:** PASS.

### 02 — Product search (English)

- **Objective:** validate an English response while preserving exact source product values.
- **Input:** `Which guitars do you have under R$1,000?`
- **Expected:** English answer, available acoustic/classical catalog products only, and no price
  above R$1,000.
- **Actual:** the response was in English and contained the expected names and BRL prices. It did
  not contain `Takamine GD20 Dreadnought Natural`, whose R$2,199 price exceeds the filter.
- **Status:** PASS.

### 03 — Store return policy

- **Objective:** verify that the answer comes from the supplied policy document.
- **Input:** `Qual é a política de devolução da loja?`
- **Expected:** `search_policy` retrieves the return section without adding unsupported rules.
- **Actual:** the UI displayed policy §4 and §4.1 from page 4: seven calendar days after receipt for
  online purchases, original packaging and no signs of use, refund through the original payment
  method within ten business days, and store-paid return shipping for regret returns.
- **Status:** PASS.

### 04 — Multi-tool return question

- **Objective:** combine a real guitar order with deterministic return eligibility and policy
  evidence.
- **Input:** `Comprei o violão do pedido 4 e quero saber se posso devolver. Como funciona?`
- **Expected:** invoke `get_order_status`, `check_return_eligibility`, and `search_policy`; explicitly
  identify missing evidence.
- **Actual:** order 4 contained `Giannini GF-3D Dreadnought Sunburst`, status `delivered`. With the
  configured reference date of 2026-03-23 and estimated delivery proxy of 2025-12-22, the result
  was `window_expired` after 91 days. The answer explicitly stated that actual delivery date,
  purchase channel, product condition/packaging, and §4.4 exclusions were not verified.
- **Status:** PASS.

### 05 — Out-of-scope question

- **Objective:** verify a polite store-scope boundary without fabricated external knowledge.
- **Input:** `Qual é a capital da França?`
- **Expected:** a scoped refusal, no tool invocation, and no unrelated business data.
- **Actual:** the UI redirected the customer to supported Empório da Música topics, displayed
  `No tools invoked`, and did not answer `Paris` or fabricate store data.
- **Status:** PASS.

### 06 — Language switching and transcript continuity

- **Objective:** display consecutive PT-BR and English turns and exercise the deterministic
  follow-up route.
- **Inputs:**
  1. `Quais violões vocês têm por até R$ 1.000?`
  2. `Which of those guitars is the cheapest?`
- **Expected:** preserve both turns in the rendered transcript, answer the second message in
  English, and use catalog values.
- **Actual:** both turns remained visible. The scripted English follow-up identified
  `Tagima Memphis AC-39 Nylon Natural` at `R$ 429.90`, matching the catalog and the preceding list.
- **Status:** PASS.

This scenario does **not** prove model-visible conversation memory. `ui.py` creates a new agent and
in-memory checkpointer for each submitted turn. The deterministic model recognizes this follow-up
and performs a new catalog search; earlier messages are not supplied to that new agent.

## Environment and reproduction

- Python: 3.12.13
- Playwright: 1.64.1
- Browser: Playwright Chromium 156.0.8078.4, headless
- Video viewport: 1440 × 1000
- Final screenshot viewport: 1440 × 1600
- UI server: Streamlit on a dynamically allocated `127.0.0.1` port
- Provider: none (offline deterministic execution)
- OpenRouter requests: 0

```powershell
uv sync --locked
uv run playwright install chromium
uv run pytest -m e2e tests/e2e -q -s
```

The regular offline suite deliberately excludes browser and live-provider tests:

```powershell
uv run ruff check .
uv run pytest
```

Observed verification results for this evidence set:

- Ruff: `All checks passed!`
- Offline pytest: `172 passed, 13 deselected in 5.49s`
- Browser E2E: `6 passed in 25.94s`
- Videos: six valid WebM files, 3.52–6.24 seconds each, all non-empty
- Screenshots: six readable PNG files, each 1440 × 1600
- Local traces: six valid ZIP files were reviewed for archive integrity and sensitive content, then
  excluded from Git because browser traces include session metadata
- Failure artifacts: none
- Credential pattern scan: clean

## Known limitations

- These artifacts prove the deterministic/offline execution path, not live OpenRouter model
  selection or wording. They must not be cited as live LLM evidence.
- The UI preserves the displayed/exported transcript but currently does not preserve model-visible
  history between submitted turns. Scenario 06 is not evidence of genuine contextual memory.
- The disabled provider-fallback checkbox remains displayed as `True` in local mode; no provider
  request or provider fallback occurs in these recordings.
- Only desktop Chromium was recorded. Firefox, WebKit, mobile layouts, and accessibility audits are
  outside this evidence run.
- Session IDs, local ports, latency, and timestamps vary on reproduction.
- The supplied order data has no actual delivery timestamp. Return calculations therefore disclose
  use of `estimated_delivery` as a proxy.
- Playwright traces are generated locally under `examples/ui-evidence/traces/` and ignored by Git.
  They can be opened with `uv run playwright show-trace <path-to-zip>`.
