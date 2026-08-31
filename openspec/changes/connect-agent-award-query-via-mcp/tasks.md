## 1. Compatibility Gate

- [x] 1.1 Create an isolated dependency spike for `langchain-mcp-adapters` and the Python MCP SDK, pin an exact compatible version pair, and verify dependency installation succeeds without upgrading the existing LangChain application stack.
- [x] 1.2 Use the running Java Streamable HTTP endpoint to discover `get_award_detail`, invoke it once, and verify its structured business Envelope can be consumed by the current synchronous `agent.invoke()` graph without event-loop or shutdown errors; if this fails or requires a global async migration, record the evidence and stop this change without editing the production Agent path.
- [x] 1.3 Record the async-only compatibility result, obtain explicit approval for a limited user-Agent async conversion, and update the proposal, design, requirements, and Chinese review note before production edits.

## 2. User Agent Async Boundary

- [x] 2.1 Convert `run_agent`, user `AgentRuntime.answer`, and state updates to await LangChain async APIs while preserving request context and Tool tracing.
- [x] 2.2 Replace the per-session blocking lock with cancellation-safe async ordering, and keep deterministic confirmation work off the event-loop thread without changing its business behavior.
- [x] 2.3 Await the user runtime from FastAPI `/v1/chat` and the CLI Agent boundary, while keeping the operator Agent and deterministic CLI planning paths synchronous.

## 3. Configuration And Startup

- [x] 3.1 Add `AWARD_DETAIL_TRANSPORT=rest|mcp`, loopback MCP URL, and bounded timeout settings with REST as the default, and verify invalid modes, non-loopback URLs, and missing MCP settings are rejected by focused configuration checks.
- [x] 3.2 Add startup MCP discovery that selects only `get_award_detail`, validates its exact one-argument input contract, and exposes a structured initialization result; verify missing Tools, additional advertised Tools, Schema drift, and an unavailable endpoint behave as specified.
- [x] 3.3 Wire MCP initialization into the FastAPI lifespan before readiness while preserving the no-MCP REST startup path, and verify experiment-mode initialization failure prevents readiness without silently falling back to REST.

## 4. Agent Tool Assembly

- [x] 4.1 Extend user-Agent Tool assembly to accept the validated remote Tool and replace only the model-visible local `get_award_detail` Tool in MCP mode; verify Tool names remain unique and every other local Tool is unchanged.
- [x] 4.2 Keep `BusinessApiClient.get_award_detail` unchanged for points planning, recommendation, growth memory, and controlled exchange, and verify focused Service tests still observe REST calls for these deterministic internal workflows when MCP mode is enabled.
- [x] 4.3 Add bounded Tool tracing for `transport=mcp`, elapsed time, and business result code without logging credentials or full award payloads, and verify a representative success and `AWARD_NOT_FOUND` trace contain the expected metadata.

## 5. Focused Verification

- [x] 5.1 Verify default configuration starts without Java MCP availability and the direct award-detail Tool continues using REST.
- [x] 5.2 Verify MCP experiment mode returns equivalent business Envelope fields for an existing award and treats a missing award as `AWARD_NOT_FOUND` rather than a protocol failure.
- [x] 5.3 Run one real Agent-level scenario and verify the trace contains exactly one model-visible MCP `get_award_detail` invocation with the expected `award_id`, no direct REST award-detail call for that Tool execution, and a final answer grounded in the structured result.
- [x] 5.4 Verify same-session ordering and lock release after Agent failure or cancellation, then perform a focused review against `CODE_REVIEW.md`, run only the affected Python and Java checks plus `openspec validate connect-agent-award-query-via-mcp --strict`, and record the exact commands and outcomes.

## 6. Documentation And Rollback

- [x] 6.1 Add one `docs/agent-design/` implementation document describing the proven call path, configuration, compatibility boundary, evidence, and one-command rollback to REST; verify it does not claim that identity-bound reads, writes, or internal Service calls use MCP.
- [x] 6.2 Update the current course-coverage/priority roadmap and development journal with only implemented evidence, then verify the repository contains no parallel MCP architecture or stale claim that all Java methods were migrated.
