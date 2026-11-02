# OWASP 2026 Security Mapping

## 1. References and interpretation

This document maps the implemented Empório da Música assessment agent to the official:

- [OWASP Top 10 for LLM Applications
  2026](https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/), published August 2026.
- [OWASP Top 10 for Agentic Applications
  2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/),
  Version 2026, published December 2025.

OWASP category names and IDs are reproduced for mapping; the applicability, controls, and
priorities below are specific to this repository. **Implemented** means present in code and linked
to evidence. **Recommended** means a future or production control and is not a current guarantee.
**Out of scope** means the required component or capability does not exist in this architecture.

Priority definitions are in [`threat-model.md`](threat-model.md).

## 2. OWASP Top 10 for LLM Applications 2026

### LLM01:2026 — Prompt Injection

- **Attack scenario:** Direct user text or indirect instructions in product descriptions, order
  notes, or retrieved policy passages tell the model to ignore scope, reveal hidden context, or call
  tools for an attacker-selected purpose.
- **Applicability:** High. All four text sources can enter the same model context.
- **Proposed mitigation:** **Implemented:** fixed read-only tools, strict argument schemas, role
  separation, untrusted-data labels, no cross-run memory. **Recommended:** expand adaptive direct
  and indirect injection tests; treat future state-changing tools or memory writes as privileged.
- **Verification method:**
  `tests/test_agent.py::test_instruction_like_policy_text_stays_data`,
  `tests/test_retrieval.py::test_instruction_like_policy_text_is_returned_verbatim_as_data`, and
  `tests/test_evaluation.py::test_e08_instruction_like_product_description_remains_data`.
- **Residual risk:** Prompt and role instructions cannot guarantee resistance by a live model.
- **Priority:** P0.

### LLM02:2026 — Sensitive Information Disclosure

- **Attack scenario:** A user enumerates order IDs, requests raw records, extracts another session,
  or causes an exception/API key to appear in a reply, trace, or export.
- **Applicability:** High for order operational data; medium for credentials and conversation state.
- **Proposed mitigation:** **Implemented:** do not load `customers.csv`; exclude identity fields;
  use `SecretStr`; sanitize tool/provider failures; disable LangSmith tracing; isolate sessions.
  **Recommended:** production authentication, order-ownership authorization, rate limits, field
  minimization, and transcript retention/access rules.
- **Verification method:** customer-field exclusion tests in `tests/test_order_tools.py` and
  `tests/test_tools.py`; secret/error/session tests in `tests/test_config.py` and
  `tests/test_agent.py`.
- **Residual risk:** Guessing an order ID is sufficient to retrieve tracking, payment, dates, and
  items. OpenRouter receives the active conversation and selected tool data.
- **Priority:** P0.

### LLM03:2026 — Excessive Agency

- **Attack scenario:** A compromised or mistaken model repeatedly invokes tools, attempts
  unauthorized arguments, or performs broad read queries unrelated to the customer's need.
- **Applicability:** Medium to high. Agency is read-only but includes operational order data.
- **Proposed mitigation:** **Implemented:** five-tool allowlist, no arbitrary SQL/code/network/write
  tool, strict schemas, call limits, timeout, recursion bound, and generic tool errors.
  **Recommended:** add deterministic authorization and per-user/query budgets before deployment.
- **Verification method:** approved-tool-set, malformed-argument, unexpected-tool-error, and runaway
  loop tests in `tests/test_agent.py`.
- **Residual risk:** A valid read call can still be abusive; the model cannot establish ownership.
- **Priority:** P0.

### LLM04:2026 — Supply Chain

- **Attack scenario:** A compromised Python dependency, model route, policy file, or build input
  changes behavior or injects malicious content.
- **Applicability:** Medium. The runtime depends on PyPI packages and an external provider/model.
- **Proposed mitigation:** **Implemented:** `uv.lock`, a small explicit dependency set, locked
  installation, provider/model configuration, policy hash regression check. **Recommended:** review
  lockfile changes, pin frozen source-data hashes, generate an SBOM for production, and use provider
  provenance controls where available.
- **Verification method:** `uv sync --locked`, dependency diff review, and
  `tests/test_retrieval.py::test_real_pdf_is_pinned_and_has_text_layer`.
- **Residual risk:** Lockfiles do not prove package or model provenance; remote model routing cannot
  be attested locally.
- **Priority:** P1.

### LLM05:2026 — Data and Model Poisoning

- **Attack scenario:** A structurally valid CSV row, PDF passage, or evaluation fixture is modified
  to insert misleading facts or model-directed instructions.
- **Applicability:** Medium. Source data is local and controlled, but natural-language fields are
  placed in tool messages.
- **Proposed mitigation:** **Implemented:** immutable-data rule, schema/reference/duplicate checks,
  policy hash, source evidence, and explicit untrusted-data labeling. **Recommended:** pin all frozen
  assessment inputs and require review when hashes or evaluation gold values change.
- **Verification method:** duplicate/missing-column tests in `tests/test_tools.py` and
  `tests/test_order_tools.py`; policy hash/heading tests; injection fixtures.
- **Residual risk:** Schema validation cannot identify semantically malicious but well-formed text.
- **Priority:** P1.

### LLM06:2026 — Unbounded Consumption

- **Attack scenario:** Repeated prompts, oversized input, recursive tool use, slow provider calls, or
  many fresh sessions exhaust quota, time, memory, or concurrency.
- **Applicability:** Medium locally; high if the UI is exposed publicly.
- **Proposed mitigation:** **Implemented:** 1,000-character input cap, 2,048 output-token cap,
  30-second timeout, no retries, per-turn model/tool limits, CLI thread model limit, recursion backstop, and
  live-evaluation request ceiling. **Recommended:** authenticated rate limits, global budgets,
  concurrency limits, monitoring, and retention bounds.
- **Verification method:** oversized-input and loop-cap tests in `tests/test_agent.py`; provider
  negative paths and request-18 ceiling in `tests/test_evaluation.py`.
- **Residual risk:** No per-user or deployment-global limit; creating a new session resets the
  thread budget. The Streamlit UI also creates a fresh agent/checkpointer per submitted turn, so the
  CLI thread-level budget does not accumulate there.
- **Priority:** P1.

### LLM07:2026 — Misinformation

- **Attack scenario:** The model invents or distorts products, prices, availability, order state,
  delivery dates, return eligibility, or policy rules.
- **Applicability:** High. Incorrect output can directly affect customer decisions.
- **Proposed mitigation:** **Implemented:** deterministic typed tools, exact prices, source evidence,
  not-found behavior, policy citations, reference date, retrieval benchmark, and prompt grounding.
  **Recommended:** deterministic evidence requirements for high-impact response fields and explicit
  human review for open text.
- **Verification method:** E01–E07 exact cases in `tests/test_evaluation.py`; catalog/order tests;
  supported, unsupported, and trap retrieval tests in `tests/test_policy_eval.py`.
- **Residual risk:** Evidence correctness and one seven-case automatic live pass do not prove
  general tool selection or answer faithfulness. Only five final responses are preserved for human
  review; E06 and E08 remain automatically checked but not independently reviewable as open text.
- **Priority:** P0.

### LLM08:2026 — Hidden Context Exposure

- **Attack scenario:** A user elicits the system prompt, tool schema, prior conversation, internal
  configuration, reasoning-like content, or exception details.
- **Applicability:** Medium. Hidden context exists, but secrets are not intentionally placed in it.
- **Proposed mitigation:** **Implemented:** no secrets/store facts in the system prompt, prompt-level
  refusal, separate sessions, sanitized errors and traces, secret-safe repr. **Recommended:** treat
  prompts as public and never depend on secrecy for authorization or safety.
- **Verification method:** system-prompt-content, session-isolation, secret-repr, and error-leak tests
  in `tests/test_agent.py` and `tests/test_config.py`.
- **Residual risk:** A model can infer or reproduce hidden instructions. Active conversation context
  is disclosed to the configured provider by design.
- **Priority:** P1.

### LLM09:2026 — Vector and Embedding Weaknesses

- **Attack scenario:** Not applicable: there is no embedding model, vector index, nearest-neighbor
  store, or multi-tenant vector collection.
- **Applicability:** Out of scope for the implemented architecture.
- **Proposed mitigation:** **Out of scope:** do not add vector infrastructure without a measured need
  and a new threat review. BM25 corpus poisoning and relevance failures remain mapped to LLM01,
  LLM05, and LLM07.
- **Verification method:** dependency and architecture inventory; `src/emporio/retrieval.py` uses a
  deterministic in-memory BM25 index.
- **Residual risk:** Lexical retrieval can return related but non-answering passages, but that is not
  an embedding-specific weakness.
- **Priority:** P2/out of scope.

### LLM10:2026 — Improper Output Handling

- **Attack scenario:** Model output contains malicious Markdown, a deceptive external link, or text
  that a downstream consumer treats as executable or authoritative.
- **Applicability:** Low to medium. Output is printed/rendered/exported, not executed or used for a
  transaction.
- **Proposed mitigation:** **Implemented:** no code/SQL/shell/eval or transactional output sink;
  concise evidence display; no application-enabled unsafe HTML. **Recommended:** treat all model
  text and exports as untrusted, review link behavior, and do not equate `status=ok` with factual
  correctness.
- **Verification method:** `tests/test_ui_helpers.py::test_export_evidence_markdown_and_json` plus a
  manual malicious-Markdown rendering check.
- **Residual risk:** A person can follow a malicious link or trust a deceptive answer; third-party
  Markdown viewers may render exports differently.
- **Priority:** P2 for code execution; P0 where the impact is misinformation.

## 3. OWASP Top 10 for Agentic Applications 2026

### ASI01 — Agent Goal Hijack

- **Attack scenario:** User or retrieved content changes the support goal to prompt disclosure,
  unrelated assistance, or attacker-selected tool calls.
- **Applicability:** High because a model selects tools from natural-language context.
- **Proposed mitigation:** **Implemented:** declarative scope, untrusted-data labels, fixed read-only
  tools, bounded loop. **Recommended:** broader adaptive injection testing and re-review before any
  new capability.
- **Verification method:** injection and out-of-scope cases in `tests/test_agent.py`,
  `tests/test_evaluation.py`, and optional live cases.
- **Residual risk:** The model may still follow a malicious instruction within the bounded response.
- **Priority:** P0.

### ASI02 — Tool Misuse and Exploitation

- **Attack scenario:** The model uses valid tools to enumerate orders, issues excessive broad
  searches, or submits malicious/extra parameters.
- **Applicability:** High for read-data misuse; low for destructive actions because none exist.
- **Proposed mitigation:** **Implemented:** strict allowlist and schemas, no arbitrary dispatch,
  read-only functions, call limits. **Recommended:** authorization and query-abuse controls for a
  deployed service.
- **Verification method:** approved-tool, malformed-argument, order-privacy, and loop-cap tests.
- **Residual risk:** Valid arguments do not imply authorized intent.
- **Priority:** P0.

### ASI03 — Identity and Privilege Abuse

- **Attack scenario:** An unauthenticated user accesses another customer's order through a guessed
  ID, or application-wide provider credentials are abused.
- **Applicability:** High. The demo has no customer identity or ownership model.
- **Proposed mitigation:** **Implemented:** no customer lookup/data and least-capability read tools.
  **Recommended:** authenticate users, authorize order ownership in trusted code, scope credentials,
  and monitor enumeration before production.
- **Verification method:** customer-field exclusion and secret-handling tests; production
  authentication is absent and therefore cannot be verified.
- **Residual risk:** Order operational details remain accessible to anyone with or guessing an ID.
- **Priority:** P0/production blocker.

### ASI04 — Agentic Supply Chain Vulnerabilities

- **Attack scenario:** A compromised agent framework, model/provider route, dependency, or future
  dynamic tool changes tool behavior or instructions.
- **Applicability:** Medium. There is no MCP or dynamic tool registry, but external packages and the
  provider remain trusted dependencies.
- **Proposed mitigation:** **Implemented:** static local tool registration and lockfile.
  **Recommended:** dependency review/SBOM, source hash review, explicit model identity in evidence,
  and no unreviewed runtime tool discovery.
- **Verification method:** dependency inventory, `uv sync --locked`, exact registered-tool test.
- **Residual risk:** The project cannot independently verify remote model/provider internals.
- **Priority:** P1.

### ASI05 — Unexpected Code Execution (RCE)

- **Attack scenario:** The category would apply if model output reached a shell, interpreter,
  dynamic import, unsafe deserializer, generated SQL executor, or writable filesystem tool.
- **Applicability:** Out of scope: none of those capabilities exists in the agent.
- **Proposed mitigation:** **Out of scope:** keep executable tools absent. Any future code or shell
  tool requires sandboxing, strict policy, and a new threat review.
- **Verification method:** exact tool allowlist and code inspection for execution sinks.
- **Residual risk:** A compromised dependency can still execute code as a conventional software
  supply-chain attack, covered by LLM04/ASI04.
- **Priority:** P2/out of scope.

### ASI06 — Memory and Context Poisoning

- **Attack scenario:** A malicious earlier message influences ambiguous follow-ups or later tool
  selection in the same session.
- **Applicability:** Medium within one process; low across sessions because no durable memory exists.
- **Proposed mitigation:** **Implemented:** random thread IDs, separate CLI sessions, in-memory-only
  checkpoints, no model-controlled memory-write tool. The UI currently discards model-visible
  history between submitted turns. **Recommended:** preserve one bounded UI checkpointer per session,
  bound history size, and treat
  any future persistent memory write as privileged.
- **Verification method:**
  `tests/test_agent.py::test_follow_up_turn_receives_earlier_messages` and
  `test_separate_sessions_do_not_share_memory`.
- **Residual risk:** Poisoned context remains influential for the lifetime of its session.
- **Priority:** P1.

### ASI07 — Insecure Inter-Agent Communication

- **Attack scenario:** Would require spoofed or untrusted messages between multiple agents.
- **Applicability:** Out of scope: one agent, no sub-agents, A2A protocol, or agent message bus.
- **Proposed mitigation:** **Out of scope:** do not introduce multi-agent communication without
  authenticated identities, message integrity, authorization, and provenance.
- **Verification method:** architecture and dependency inventory.
- **Residual risk:** Model/tool messages exist inside one orchestrator but are covered by prompt
  injection and tool-validation risks, not inter-agent communication.
- **Priority:** P2/out of scope.

### ASI08 — Cascading Failures

- **Attack scenario:** Wrong retrieval leads to a wrong model conclusion; repeated correction calls
  hit limits; provider failure triggers a fallback whose answer is mistaken for live-model output.
- **Applicability:** Low to medium because there are multi-step tool flows but no downstream
  transaction or multi-agent cascade.
- **Proposed mitigation:** **Implemented:** deterministic tool results, source evidence, bounded
  calls, fixed failures, model identity/evidence in UI exports. **Recommended:** keep fallback and
  error state visible and never silently convert a failed live evaluation into a pass.
- **Verification method:** multi-tool, provider failure, call-cap, and UI evidence-export tests.
- **Residual risk:** A wrong but schema-valid fact interpretation can propagate into a fluent answer.
- **Priority:** P1.

### ASI09 — Human-Agent Trust Exploitation

- **Attack scenario:** A confident, friendly response or green runtime status persuades a user to
  trust an unsupported policy, availability, or eligibility claim.
- **Applicability:** High for customer support and evaluator review.
- **Proposed mitigation:** **Implemented:** source traces, citations, explicit error status, genuine
  failure preservation, human-review labels. **Recommended:** distinguish runtime success from
  factual validation in every interface and require human review for open-text evaluation.
- **Verification method:** exact evidence tests, export tests, and the review workflow documented in
  `docs/evaluation-results.md`.
- **Residual risk:** Users may ignore evidence or limitations; citations can be present but
  misinterpreted.
- **Priority:** P0.

### ASI10 — Rogue Agents

- **Attack scenario:** Would involve persistent goals, concealment, self-modification, unauthorized
  autonomous action, or continued background execution.
- **Applicability:** Low. The agent is request-driven, single-process, read-only, bounded, and has no
  durable goals or self-modification capability.
- **Proposed mitigation:** **Implemented:** least-agency design, no background tasks or write tools,
  bounded loop. **Recommended:** preserve this design and re-review if autonomy is expanded.
- **Verification method:** tool allowlist, call-limit tests, and architecture inspection.
- **Residual risk:** A model can deviate in one answer or select an incorrect read tool, already
  covered by ASI01/ASI02; it cannot independently persist or transact.
- **Priority:** P2.

## 4. Cross-framework priority summary

| Project risk | LLM 2026 | Agentic 2026 | Priority |
|---|---|---|---|
| Direct/indirect instruction manipulation | LLM01 | ASI01, ASI06 | P0 |
| Unauthenticated order disclosure | LLM02 | ASI02, ASI03 | P0 |
| Read-tool abuse and overreach | LLM03 | ASI02 | P0 |
| Unsupported business claims and human over-trust | LLM07 | ASI08, ASI09 | P0 |
| Secret/hidden-context exposure | LLM02, LLM08 | ASI03 | P1, with order data P0 |
| Resource/quota exhaustion | LLM06 | ASI08 | P1 |
| Dependency/model/data poisoning | LLM04, LLM05 | ASI04, ASI06 | P1 |
| Rendered/exported malicious output | LLM10 | ASI09 | P2, with misinformation P0 |
| Vector/embedding weakness | LLM09 | — | Out of scope |
| RCE, inter-agent messaging, rogue autonomy | — | ASI05, ASI07, ASI10 | Out of scope or low |

## 5. Evidence limitations

Offline tests demonstrate deterministic controls and simulated provider failures. The latest live
run passed seven automatic tool/pattern checks, but only five response bodies are preserved for
human review. These observations do not demonstrate that a real model resists adaptive attacks,
always chooses the correct tool, or always phrases evidence faithfully. This mapping therefore does
not claim live-model security assurance.
