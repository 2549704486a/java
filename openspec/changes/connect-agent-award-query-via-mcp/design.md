## Context

See `proposal.md` for the motivation. The Java application already exposes a local-only, default-off Streamable HTTP MCP Server whose sole Tool delegates directly to `AgentQueryService.getAwardDetail`. The Python Agent currently builds a local LangChain `get_award_detail` Tool that closes over `BusinessApiClient`; several deterministic Python Services use the same REST client method internally.

The current user Agent graph is constructed synchronously and executed with `agent.invoke()`. The compatibility spike proved that the official adapter returns an async-only remote Tool, while the exact pinned LangChain stack already supports `ainvoke()`. After explicit human approval, this change converts only the affected user Agent HTTP/CLI execution path to async. The operator Agent and deterministic Python Services remain synchronous. The adapter is stateless by default, so each remote Tool invocation can create and clean up its own MCP session rather than adding a project-specific long-lived Runtime.

## Goals / Non-Goals

**Goals:**

- Replace exactly one model-visible local Tool with the Java-discovered MCP Tool under an explicit experiment flag.
- Exercise real MCP initialization, discovery, Schema validation and Tool invocation from the Agent process.
- Preserve all deterministic Python Service calls, other Agent Tools and user-visible contracts.
- Convert only the user Agent request boundary needed to await the official remote Tool while preserving per-session ordering.
- Keep the integration thin and removable.

**Non-Goals:**

- No generic MCP client platform, Tool registry mirror, Capability layer or fallback router.
- No user-scoped or operator-scoped MCP authorization in this change.
- No migration of business writes or internal Service-to-Service traffic.
- No async conversion of the operator Agent, deterministic business Services, or unrelated background workflows.
- No hidden background event loop or per-Tool `asyncio.run()` bridge, and no major LangChain/Python upgrade merely to satisfy MCP integration.

## Decisions

### 1. Replace the model-visible Tool during Tool assembly

In REST mode, `build_tools()` continues selecting the existing local `get_award_detail`. In MCP mode, startup discovery supplies one remote LangChain Tool with the same name; Tool assembly selects that object in the same list position and omits the local duplicate.

```text
REST mode
  create_agent
    -> local get_award_detail
    -> BusinessApiClient
    -> Java REST

MCP mode
  MCP discovery
    -> remote get_award_detail BaseTool
    -> create_agent
    -> Java /mcp
    -> AgentQueryService
```

This switch MUST NOT be placed in `BusinessApiClient.get_award_detail`, because that method is also used by points planning, recommendation, growth memory and controlled exchange. Branching there would silently migrate deterministic internal calls and invalidate the experiment boundary.

**Alternative: keep the local Tool and call MCP inside it.** Rejected because the local description and Schema would remain the model-facing source; the experiment would test MCP as an RPC transport but not Tool discovery or remote contract consumption.

**Alternative: replace every Java-backed Tool.** Rejected because identity, authorization and write semantics are not established, and a bulk migration would prevent attributing failures to one boundary.

### 2. Use the official adapter and convert the affected user path to async

The preferred implementation is `langchain-mcp-adapters` over the official Python MCP SDK because it returns LangChain Tool objects from a standard MCP Server and avoids a project-owned Tool conversion layer. The implementation SHALL pin a compatible adapter/SDK pair and document the resolved dependency tree.

Before production edits, a disposable spike SHALL verify all of the following in the current environment:

- Streamable HTTP connection to the Java `0.18.4` Server succeeds;
- `get_tools()` discovers the Tool and structured output;
- whether the returned Tool can execute from the current synchronous `agent.invoke()` graph;
- initialization and invocation clean up without event-loop or shutdown errors.

The spike proved that the returned Tool is async-only. The reviewed implementation therefore uses `agent.ainvoke()` and async runtime methods for the user Agent path only. FastAPI awaits this path directly; the CLI creates one event loop at its process boundary. A custom sync adapter, background event loop, or hidden per-call `asyncio.run()` bridge SHALL NOT be introduced.

The per-session lock SHALL become an `asyncio.Lock` so concurrent requests for the same user/session remain ordered. Cancellation and failure SHALL release the lock in `finally`. Existing blocking deterministic confirmation work SHALL run outside the event loop thread without changing its business implementation.

### 3. Discover before readiness and fail closed

`AWARD_DETAIL_TRANSPORT` accepts `rest` or `mcp` and defaults to `rest`. MCP mode additionally requires a loopback `AWARD_DETAIL_MCP_URL` and bounded initialization/call timeouts.

During FastAPI lifespan startup, the runtime discovers and validates the remote Tool before the application reports readiness. Because user Agents are created lazily and cached per user, the validated identity-neutral remote Tool can be reused in subsequent graph construction without rebuilding all Agents at startup.

MCP initialization, missing Tool or Schema drift causes startup readiness failure. There is no automatic REST fallback in experiment mode; otherwise a successful answer would not prove which transport executed.

### 4. Enforce an exact allowlist and contract

Discovery output is filtered to the exact name `get_award_detail`. Validation requires one positive-integer `award_id`, no user/operator identity argument and no additional properties. Any other remote Tool is ignored and never bound to the model.

This is defense in depth: the Java Server currently exposes only one Tool, but future server expansion must not silently expand the user Agent's authority.

### 5. Preserve business Envelope and trace semantics

Java already returns the same five-field business Envelope through REST and MCP structured content. The remote Tool result must keep business failures such as `AWARD_NOT_FOUND` distinct from MCP transport/protocol failures.

The Python trace records the current request ID, Tool name, bounded arguments, elapsed time, result code when available, and `transport=mcp`. Java retains its own bounded `callId` summary. Cross-process shared correlation is not added in this identity-neutral pilot because the adapter's HTTP headers are static by default; this limitation is documented rather than solved with a custom transport.

### 6. Keep high-risk and identity-bound capabilities out

User points, eligibility, orders and notifications need trusted user identity that must not come from model arguments. Operator reads and all writes require operator identity and permissions. Those capabilities stay on the current local Tool/REST path until a separate design defines token delegation, least privilege, audit and session isolation.

## Risks / Trade-offs

- **[Adapter and SDK version drift]** → Pin and validate an exact pair in the spike; do not rely on floating latest versions.
- **[Async conversion can break callers or session ordering]** → Limit it to the user Agent boundary, await it from FastAPI/CLI, preserve per-session locking with `asyncio.Lock`, and cover cancellation-safe release with focused tests.
- **[Remote and local Tool descriptions differ]** → Compare name, input Schema and representative routing before enabling the experiment; accept wording differences only when behavior remains stable.
- **[MCP unavailable blocks experiment startup]** → This is intentional fail-closed behavior; rollback is changing the transport setting to `rest`.
- **[Only one direct Tool uses MCP]** → The result proves Agent consumption, not broad reuse or production value. Additional migration requires a separate proposal and evidence.
- **[No shared cross-process request ID]** → Keep Python and Java bounded traces and document the gap; solve dynamic identity/correlation headers with the future authentication design.

## Migration Plan

1. Run the dependency and synchronous invocation spike without modifying the production Agent path.
2. Record the async-only result and obtain explicit approval for the limited user-path async conversion.
3. Convert `run_agent`, user `AgentRuntime.answer`, FastAPI `/v1/chat`, and the CLI Agent boundary to async while leaving the operator Agent and deterministic Services unchanged.
4. Add default-off settings and startup discovery/contract validation.
5. Inject only the validated remote Tool into user Agent Tool assembly and preserve all other REST paths.
6. Run async ordering/cancellation, Tool-list isolation, contract, failure and Agent-level targeted checks.
7. Enable both Java and Agent flags for one local manual scenario, inspect Python and Java traces, then return the default to REST.
8. If any acceptance condition fails or complexity exceeds this design, remove the Python MCP dependency and integration files; the existing REST path requires no data migration.

## Compatibility Spike Result (2026-08-31)

The isolated Python 3.11 spike used `langchain==1.3.15`, `langchain-mcp-adapters==0.3.2`, and `mcp==1.29.1`. Adapter dependency resolution requires `mcp>=1.24.0,<2.0.0`; the unrelated `mcp==2.0.0` present in the project virtual environment is therefore not a compatible production dependency.

Against an isolated Java instance with MCP enabled on port `18088`, the official adapter successfully:

- discovered exactly `get_award_detail` over Streamable HTTP;
- preserved the expected one-argument JSON Schema;
- executed `tool.ainvoke({"award_id": 6})` and received the Java business Envelope.

The discovered LangChain `StructuredTool` had `response_format=content_and_artifact`, no synchronous `func`, and an asynchronous `coroutine`. Both direct `tool.invoke({"award_id": 6})` and a Fake Model-driven `create_agent(...).invoke(...)` failed with:

```text
NotImplementedError: StructuredTool does not support sync invocation.
```

This was the incompatibility gate defined above. No production Agent dependency, configuration, Tool assembly, or runtime code was changed during the spike. The user subsequently approved converting the affected user Agent execution path to asynchronous invocation. The approved scope is limited to `run_agent`, user `AgentRuntime.answer`, FastAPI `/v1/chat`, and the CLI Agent boundary; the operator Agent and deterministic Services remain synchronous, and a custom sync bridge remains rejected.
