# ADR-0001: Source-Grounded, Bounded Customer-Support Agent

- **Status:** Accepted and updated after implementation review
- **Scope:** orchestration, provider, data, retrieval, security, testing, and language

The original assessment statement is not stored in the repository. Requirements attributed to it
use the provisional English transcription in docs/requirements.md.

## Decision 01 — Agent Architecture

### Context

The application must decide when to consult catalog, order, return, and policy data. It has one
model-to-tools loop, no transaction, no approval branch, and no multi-agent communication.

### Decision

Use langchain.agents.create_agent, which uses LangGraph internally, with five structured tools,
InMemorySaver, call-limit middleware, and a recursion backstop. Do not build a custom graph.

The CLI constructs the agent once and preserves model-visible in-process history. The Streamlit UI
currently creates a new agent/checkpointer for every submitted turn; it preserves the visible and
exported transcript, but it does not pass earlier messages to the next live model call.

### Alternatives considered

| Alternative | Outcome | Rationale |
|---|---|---|
| Hand-written provider tool loop | Superseded | The standard agent already supplies the bounded loop and checkpoints |
| Custom LangGraph router | Rejected | No second workflow branch justifies extra routing code or model calls |
| Multi-agent workflow | Rejected | No separate authorized role or task requires it |
| Put all data in the system prompt | Rejected | Excess context and weak consultation/provenance boundaries |

### Consequences and trade-offs

The design minimizes orchestration code and supports offline fake-model testing. Framework behavior
remains a dependency, tool schemas consume context, and the current UI does not preserve model
context or thread-level limits across submitted turns.

### Validation evidence

tests/test_agent.py covers tool round trips, limits, failures, CLI history, and session isolation.
The UI helper and E2E suites cover rendered behavior but do not prove live multi-turn memory.

## Decision 02 — LLM Provider

### Context

The provider must support OpenAI-compatible function calling and a no-cost model option. Free model
availability, rate limits, and routing can change independently of the repository.

### Decision

Use OpenRouter through ChatOpenAI. Require openrouter/free or an explicit model ending in :free;
read credentials, model, and base URL from environment configuration; disable SDK retries.
CLI and live evaluation disable provider fallback. The Streamlit UI exposes upstream fallback as a
user option and enables it by default, and its auto-fallback mode can replace provider failures with
the local deterministic model.

The repository default is google/gemma-4-31b-it:free. The successful preserved live evaluation used
nvidia/nemotron-3.5-super-vl:free, so those results apply only to that run.

### Alternatives considered

| Alternative | Outcome | Rationale |
|---|---|---|
| Provider-specific SDK | Rejected | Unnecessary binding to one upstream model provider |
| Paid model | Rejected | The implementation intentionally enforces the free-tier constraint |
| openrouter/free auto-router | Supported, not used for preserved evaluation | Convenient but weakens model identity |
| Automatic retry | Rejected | Consumes quota and reduces failure reproducibility |

### Consequences and trade-offs

Model replacement is configuration-only, but free-tier latency, availability, and tool quality are
external risks. OpenRouter receives active conversation and selected tool data. The UI's provider
and local fallbacks require reviewers to inspect per-turn model metadata. There is no generic
multi-provider abstraction beyond the OpenAI-compatible endpoint.

### Validation evidence

Configuration and smoke tests cover model restrictions and provider options. Historical attempts
are in docs/llm-smoke.md; live Nemotron results are in docs/evaluation-results.md and examples/.

## Decision 03 — Structured Data

### Context

Prices, stock, identifiers, order states, and deadlines require exact values. The supplied data is a
small immutable CSV snapshot and includes an unnecessary customer table.

### Decision

Load inspected schemas into typed in-memory objects and expose deterministic Python functions. Use
Decimal for money, exact identifiers, explicit availability rules, schema and referential-integrity
validation, and structured errors. Never load customers.csv; discard customer_id from orders.
Use REFERENCE_DATE for return decisions and disclose estimated_delivery as a proxy when actual
delivery time is unavailable.

### Alternatives considered

| Alternative | Outcome | Rationale |
|---|---|---|
| RAG over CSV rows | Rejected | Approximate retrieval is unsuitable for exact facts |
| Generated SQL agent | Rejected | No database exists and arbitrary querying adds agency |
| Embed rows in prompts | Rejected | Expensive, opaque, and harder to validate |
| Load customer records | Rejected | Not required and increases privacy exposure |

### Consequences and trade-offs

Exact facts are independently testable with row evidence, but the snapshot is not a production
system. Source anomalies are preserved rather than silently corrected. Sequential order IDs remain
enumerable and possession of an ID is treated as sufficient access.

### Validation evidence

tests/test_tools.py, tests/test_order_tools.py, tests/test_check_return.py, and docs/data-notes.md.

## Decision 04 — Policy Retrieval

### Context

Policy rules are natural-language content in an eight-page PT-BR PDF. The corpus has only 28
section/subsection chunks and customers may ask in English.

### Decision

Extract with pypdf, normalize documented layout artifacts, fail on a missing text layer or known
heading, and build an in-memory BM25 index. Use section chunks and an English-to-PT-BR glossary.
Return the top three verbatim passages with section, page, version, and hash evidence. Treat lexical
overlap as candidate evidence, not proof that a passage answers the question.

### Alternatives considered

| Alternative | Outcome | Rationale |
|---|---|---|
| Fixed topic enum | Replaced | Coarse passages and model-dependent selection |
| Local multilingual embeddings | Deferred | More dependencies with no measured hit@3 benefit |
| Hosted embeddings | Rejected | Network, quota, privacy, and reproducibility costs |
| Vector database | Rejected | No benefit for 28 startup-built chunks |

### Consequences and trade-offs

Retrieval is deterministic and offline, but English coverage depends partly on a maintained glossary,
related non-answering passages can rank highly, and hard-coded headings intentionally reject an
unreviewed policy version.

### Validation evidence

tests/test_retrieval.py, tests/test_policy_eval.py, and docs/retrieval.md.

## Decision 05 — Security

### Context

Customer input and natural-language source fields are untrusted. The model needs read access but no
transaction, code execution, or customer-identity capability.

### Decision

Use exactly five read-only tools with strict arguments; exclude arbitrary SQL, code, shell,
filesystem, browser, payment, and messaging capabilities; exclude customer identity; sanitize
provider/tool failures; disable LangSmith tracing; and enforce a 1,000-character input cap,
2,048-token output cap, 30-second timeout, zero SDK retries, five model calls and six tool calls per
turn, plus recursion backstop. Treat prompt rules as partial controls, never as proof.

### Alternatives considered

| Alternative | Outcome | Rationale |
|---|---|---|
| Second LLM guardrail | Rejected | Adds cost and another manipulable boundary |
| Generic sanitization as injection prevention | Rejected | Legitimate text can resemble instructions |
| State-changing tools | Rejected | Not required and materially increase impact |
| Production authentication | Deferred | Required before deployment but beyond assessment scope |

### Consequences and trade-offs

Wrong model behavior cannot directly transact or execute code, but valid read calls can enumerate
order data. There is no authentication, ownership authorization, per-user/global rate limit, or
security proof against adaptive prompt injection.

### Validation evidence

docs/security/threat-model.md, docs/security/owasp-mapping.md, and the tool/privacy/error/limit tests.

## Decision 06 — Testing and Evaluation

### Context

Provider behavior is nondeterministic and rate-limited. Exact data and retrieval behavior can be
evaluated offline; final wording and nuanced safety require real-model observation and human review.

### Decision

Use layered evidence:

1. Default offline pytest for tools, retrieval, fake-model orchestration, language, failures, and UI helpers.
2. Exact policy development, held-out, unsupported, and trap benchmarks.
3. Opt-in live OpenRouter scenarios with an 18-request ceiling, automatic checks, and preserved failures.
4. Opt-in Playwright UI tests using the local deterministic model, with committed screenshots and
   videos. Playwright trace archives remain local because they contain browser session metadata.
5. Human review for open-text quality; automatic patterns are not semantic proof.

### Alternatives considered

| Alternative | Outcome | Rationale |
|---|---|---|
| Mandatory live tests | Rejected | Network and quota would make the default suite unreliable |
| Unit tests only | Rejected | Would miss full orchestration and rendered UI behavior |
| LLM-as-judge as final authority | Rejected | Not an independent deterministic control |
| Label deterministic UI tests as live AI E2E | Rejected | They exercise UI/tools, not provider model quality |

### Consequences and trade-offs

Default checks are reproducible, but scripted models do not prove real model selection. Browser
evidence does not prove live behavior or model memory. Only five of seven latest live responses were
saved, so complete human review cannot be reconstructed.

### Validation evidence

Current observation: Ruff passed and pytest reported 172 passed, 13 deselected. Additional evidence
is in docs/evaluation-results.md, examples/, and examples/ui-evidence/.

## Decision 07 — Language Support

### Context

Source data remains PT-BR while customers may write in PT-BR or English. Retrieved instructions
must not control response language.

### Decision

Resolve en or pt-BR in application code from the latest meaningful customer message. Explicit
language requests take precedence; ambiguous messages preserve established session language, with
English as the neutral first-turn default. Supply the result through a trusted per-turn system
directive. Preserve product names, identifiers, statuses, prices, dates, and evidence references.
Do not translate source files.

### Alternatives considered

| Alternative | Outcome | Rationale |
|---|---|---|
| LLM-only detection | Rejected | Less deterministic and more exposed to retrieved text |
| Translate persisted sources | Rejected | Creates another truth copy and violates source preservation |
| PT-BR only | Rejected | Does not satisfy bilingual support |
| External detector | Rejected | Unnecessary service for two languages |

### Consequences and trade-offs

Language behavior is cheap and testable, but heuristic detection can misclassify short or mixed
text. Ambiguous follow-up preservation works in the long-lived CLI session; the current UI does not
pass previous messages to its newly constructed agent.

### Validation evidence

tests/test_language.py, bilingual agent tests, UI helper tests, English live examples, and PT-BR
deterministic UI evidence.

## Overall Consequences

The architecture is appropriately small for the assessment: deterministic functions own exact
facts, lexical retrieval owns evidence selection, and one bounded model owns tool choice and
wording. It is not production-ready because authorization, durable state, global abuse controls,
service integrations, complete live human review, and genuine UI multi-turn memory are absent.
