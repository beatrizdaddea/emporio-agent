# Conversation Examples

The assessment requires 3–5 genuine English conversations. This directory contains exactly
five after the opt-in live evaluation succeeds. They are generated from the same labeled run
used by `docs/evaluation-results.md`; responses are not rewritten to improve their outcome.

**Current status:** zero successful conversations. `01-product-search.md` is a preserved HTTP 429
failure artifact and does not count toward the requirement; the other four files do not exist yet.

| File | Scenario | Requirements | Expected evidence |
|---|---|---|---|
| `01-product-search.md` | Available acoustic/classical guitars up to R$1,000 | FR-03, FR-04, D-10, D-11 | `search_products`, product CSV rows |
| `02-store-policy.md` | Saturday opening hours | FR-03, FR-05 | `search_policy`, Policy §2 p.2 |
| `03-order-status.md` | Status of order 8 | FR-03, FR-04 | `get_order_status`, order/item/product rows |
| `04-out-of-scope.md` | Coding plus guitar strings | FR-06 | No tool call; polite redirect |
| `05-return-multi-tool.md` | Return eligibility for order 7 | FR-04, FR-05, FR-11, D-10 | Order row, eligibility decision, Policy §4.1 p.4 |

Each file records the exact prompt, final response, tool trace, sources, model, UTC execution
time, latency, provider-reported token usage when available, automatic checks, and an explicit
human-review checklist. `NOT REVIEWED` is not treated as a pass.

Generate the examples once, without retry or fallback, using the shared 18-request ceiling:

```bash
uv run pytest -m live tests/live/test_live_flows.py -q -s
```

If the provider fails or an automatic check fails, the attempt remains in
`docs/evaluation-results.md`. Missing example files mean the corresponding genuine scenario
did not run; they must never be filled with a fabricated transcript.
