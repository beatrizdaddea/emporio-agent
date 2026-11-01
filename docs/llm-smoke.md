# OpenRouter LLM Smoke Check

## Scope

The smoke runner validates an isolated OpenRouter connection independently from the customer-facing
agent loop. It permits only explicit `:free` model IDs, performs no model
fallback, disables SDK retries and provider fallback, and uses a read-only toy tool.

The planned successful request budget is three calls:

1. One exact English response.
2. One forced `lookup_test_code` request with `item="alpha"`.
3. One follow-up after local tool execution returns the fixed code `A-17`.

## Tested model

- Model: `google/gemma-4-31b-it:free`
- Date: 2026-10-31
- Client: OpenAI-compatible Python SDK pointed at OpenRouter
- Automatic retries: disabled
- Provider fallback: disabled
- Paid-model fallback: unavailable by construction

## Observed live result

The first English-response request failed before a model response was received.

```text
phase=english
status=error
latency_ms=350.2
finish_reason=none
error_class=APIConnectionError
```

No HTTP response status, response body or tool-call structure was available. The client-side
evidence cannot establish whether the request reached OpenRouter or affected quota. No API
key, request headers, prompts, response content or exception message were logged.

The alternative free model was not called because the failure was at the connection layer,
not evidence that the selected model lacked tool support.

## Offline verification

Mock-based tests cover:

- Rejection of model IDs without the `:free` suffix.
- The exact English-response contract.
- Tool-call type, name, JSON arguments and non-empty call ID.
- One local read-only mock execution.
- A follow-up tool message with the matching call ID.
- Use of the mock result in the final response.
- Provider exception-class logging without exception details.

The original focused suite passed with 5 tests on Python 3.13.12. The current project suite is
also exercised on Python 3.12; see `docs/evaluation-results.md` for the latest recorded command.

## Limitations

- The actual English response remains unverified.
- The live `tool_calls` response structure remains unverified.
- Live tool execution plus follow-up remains unverified.
- The environment blocked both Python/package downloads and the OpenRouter connection.
- Free-model availability, quotas and provider behavior can change independently of this
  repository.

## Re-run on 2026-11-01 (P08, network allowed)

| Attempt | Model | Result |
|---|---|---|
| 1 (sandbox) | `meta-llama/llama-3.3-70b-instruct:free` (from local `.env`) | `APIConnectionError` (no network in the sandbox) |
| 2 | same | **HTTP 404 Not Found**. OpenRouter's public `/models` list no longer contains this ID |
| 3 | `google/gemma-4-31b-it:free` (repo default, set only through the process environment; `.env` untouched) | **HTTP 429 Too Many Requests** on the first request |

Result: **tool calling is still not verified live.** The configured model is now
`google/gemma-4-31b-it:free`, whose OpenRouter metadata advertises tool support, but advertising
isn't verification. A later end-to-end evaluation again received HTTP 429 on its first request
(`docs/evaluation-results.md`). No retry or model fallback was used. After rotating the exposed
local credential and restoring quota, re-run this smoke command before `uv run pytest -m live`.
