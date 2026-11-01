# Structured Evaluation Results

This document separates deterministic offline evidence from optional observations made with a
real OpenRouter model. Exact structured facts are automatically scored; open text always remains
subject to the documented human-review checklist.

## Reproducible commands

Offline, with no API key or network request:

```powershell
$env:OPENROUTER_API_KEY=''
uv run ruff check .
uv run pytest -m "not live"
```

Opt-in live run, using the model and key in the local uncommitted `.env`:

```powershell
uv run pytest -m live tests/live/test_live_flows.py -q -s
```

The live runner uses one configured model, disables SDK retries and provider fallback, stops
after provider/runtime failure, and refuses a nineteenth provider request. The five conversation
examples are generated from the same run, so they consume no additional quota.

## Dataset and scoring

- Core labeled set: `tests/evaluation_cases.json` (10 cases).
- Offline cases: 9 cases; live cases: 7 cases; six cases run in both modes.
- Existing policy benchmark: 25 dev, 12 held-out, 5 unsupported, and 2 trap questions in
  `tests/policy_eval_cases.py`. Supported cases run with both English and PT-BR queries.
- Structured facts, tool names, errors, source rows, policy sections, and verbatim snippets use
  exact comparisons.
- Regex checks are limited to the presence or absence of explicitly labeled facts or unsafe
  patterns. They do not establish overall answer quality.
- Tone, usefulness, translation faithfulness, nuanced refusals, and prompt-injection handling
  require explicit human review. An unreviewed answer is never counted as correct open text.

## Offline observation

- Execution date: `2026-11-01`.
- Python: `3.12.13`.
- Model ID: `not applicable` (no model was constructed or called).
- Core dataset: `10` labeled cases total; `9` have deterministic offline coverage.
- Prompts and expected values: recorded verbatim in `tests/evaluation_cases.json`.
- Ruff observation: `All checks passed!`.
- Pytest observation: `156 passed, 7 deselected in 11.93s`.
- Deselected tests: the seven explicitly marked live cases.
- API key for the run: empty process value.
- Provider requests: `0`.
- Token usage: `not applicable`.
- Per-case model latency: `not applicable`; total pytest wall time reported by pytest was
  `11.93s`.

The offline observation covers exact catalog/order facts and evidence, retrieval relevance,
unknown entities, the untrusted-data boundary, provider 429/timeout mapping, no-retry behavior,
token-usage aggregation, and the hard live-request ceiling. Real-model tool choice and open text
remain live/human-review concerns.

## Known limitations

- The core set is deliberately small and is not a statistical quality estimate.
- Scripted offline agent tests verify orchestration and failure handling, not whether a real model
  will independently choose the right tool.
- The retrieval benchmark proves passage relevance, not final-answer faithfulness.
- Live results describe one model, configuration, date, and run. Free-model availability and
  behavior can change.
- Client wall-clock latency includes local orchestration, tool execution, and network time; it is
  not server-only latency.
- Token counts are recorded only when the provider returns usage metadata; missing counts are
  reported as `not reported` and never estimated.
- The synthetic injection case covers one known attack pattern and is not a security proof.
- Rate-limit and timeout behavior is deterministically simulated offline. A live run records a
  real provider failure only if one actually occurs.

## Live observations

The append-only attempts below are genuine. A provider failure is retained and is not converted
into a successful result.

## Live run: 2026-11-01T18:37:28+00:00

- Model: `google/gemma-4-31b-it:free`
- Cases attempted: `1/7`
- Cases passing automatic checks: `0/1`
- Provider requests: `1/18`
- Aborted: `rate_limited`
- Token usage: `not reported`
- Open-text verdicts: `NOT REVIEWED`

### E01_catalog_filtered — FAIL

- Prompt: `Which acoustic/classical guitars are available for R$1,000 or less?`
- Latency: `692.5 ms`
- Token usage: `not reported`
- Error: `rate_limited`
- Trace: no tools
- FAIL: required tool used: search_products
- FAIL: catalog source traced
- REVIEW_REQUIRED: The answer does not claim unavailable products are available.
- REVIEW_REQUIRED: The English answer is useful and grounded in the returned list.

### P10 status after this attempt

- Successful genuine conversations: `0/5`.
- Preserved failure artifact: `examples/01-product-search.md`.
- Files `02-store-policy.md` through `05-return-multi-tool.md` were deliberately not created.
- P10 remains incomplete. Complete it only with a later explicit live run after provider quota is
  available; do not replace the missing conversations with scripted or hand-written output.
