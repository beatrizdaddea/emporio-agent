# Live Conversation Examples

This directory contains exactly five successful customer conversations from the opt-in OpenRouter
evaluation run at 2026-11-02T12:45:33+00:00. The configured model was
nvidia/nemotron-3.5-super-vl:free. Responses are preserved verbatim except for any explicitly
declared sensitive redaction; all five report zero redactions.

These artifacts are genuine live-model evidence, unlike the local deterministic browser scenarios
under ui-evidence/. Each file records the prompt, response, tool trace, sources, model, UTC
timestamp, latency, provider-reported token usage, and automatic checks.

| File | Scenario | Automatic status | Main evidence |
|---|---|---|---|
| [01-product-search.md](01-product-search.md) | Available acoustic/classical guitars up to R$1,000 | PASS | search_products and product CSV rows |
| [02-store-policy.md](02-store-policy.md) | Saturday opening hours | PASS | search_policy and Policy §2 p.2 |
| [03-order-status.md](03-order-status.md) | Status of order 8 | PASS | get_order_status and order/item/product rows |
| [04-out-of-scope.md](04-out-of-scope.md) | Coding plus guitar strings | PASS | No tool call; scoped refusal |
| [05-return-multi-tool.md](05-return-multi-tool.md) | Return eligibility for order 7 | PASS | Order, eligibility, and Policy §4.1 evidence |

The five saved responses were reviewed against their declared open-text criteria and did not reveal
a criterion failure. This does not make the run a statistical quality estimate. Two additional live
cases, E06 and E08, passed automatic checks but do not have preserved response bodies, so the full
seven-case run cannot be independently human-reviewed from repository artifacts.

See [the structured evaluation results](../docs/evaluation-results.md) for all preserved attempts,
including the initial HTTP 429, the partially passing run, the later seven-of-seven automatic
result, and review limitations.

## Reproduction

```powershell
uv run pytest -m live tests/live/test_live_flows.py -q -s
```

The live runner consumes OpenRouter quota, uses the local uncommitted environment configuration,
disables SDK retries and provider fallback, and enforces an 18-request ceiling. Successful example
cases can overwrite these files, so review the Git diff before retaining a new run. Provider/model
availability and response wording can change.
