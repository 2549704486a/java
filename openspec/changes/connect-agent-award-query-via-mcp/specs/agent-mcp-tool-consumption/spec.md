## Purpose

让用户 Agent 在显式实验模式下通过标准 MCP 发现并调用经过允许的 Java 业务 Tool，同时维持默认 REST 基线、调用范围隔离和可判定的失败行为。

## ADDED Requirements

### Requirement: MCP consumption is explicit and default-off
The system SHALL keep the existing REST-backed Agent Tool path as the default. The MCP-backed award query SHALL exist only when an explicit Agent-side experiment configuration is enabled.

#### Scenario: Default configuration uses REST
- **WHEN** the Agent starts without the MCP award-query experiment enabled
- **THEN** the Agent SHALL expose the existing local `get_award_detail` Tool
- **AND** it SHALL NOT initialize an MCP client or require the Java MCP endpoint

#### Scenario: Explicit experiment enables MCP
- **WHEN** the Agent starts with the MCP award-query experiment explicitly enabled and the configured Java MCP endpoint is valid
- **THEN** the Agent SHALL discover the remote `get_award_detail` Tool before accepting user requests
- **AND** the model-visible Tool with that name SHALL invoke the Java MCP Server instead of the REST award-detail endpoint

### Requirement: Only the approved remote Tool is model-visible
The system SHALL import only the allowlisted `get_award_detail` MCP Tool. It MUST NOT automatically expose additional Tools later advertised by the same MCP Server.

#### Scenario: Server advertises the approved Tool
- **WHEN** MCP discovery returns `get_award_detail` with exactly one required positive-integer `award_id` argument and no additional arguments
- **THEN** the Agent SHALL replace the local model-visible Tool with that remote Tool
- **AND** the Agent SHALL keep the remaining local Tool set unchanged

#### Scenario: Server advertises additional Tools
- **WHEN** MCP discovery returns `get_award_detail` together with other Tool definitions
- **THEN** only `get_award_detail` SHALL be eligible for Agent registration
- **AND** no additional remote Tool SHALL become visible to the model

### Requirement: Contract and connection failures are explicit
In MCP experiment mode, the system SHALL reject startup readiness when the endpoint cannot be reached, the approved Tool is absent, or its input contract differs from the expected contract. It MUST NOT silently fall back to REST.

#### Scenario: MCP endpoint is unavailable
- **WHEN** the experiment is enabled and MCP initialization or Tool discovery cannot complete within the configured timeout
- **THEN** the Agent SHALL report a structured MCP initialization failure
- **AND** it SHALL NOT report itself ready or substitute the REST Tool

#### Scenario: Tool contract has drifted
- **WHEN** the discovered `get_award_detail` Tool is missing `award_id`, accepts identity parameters, or otherwise differs from the expected input contract
- **THEN** the Agent SHALL reject the remote Tool before serving user traffic
- **AND** it SHALL identify contract drift as the failure category

### Requirement: Business result semantics remain consistent
The MCP-backed Tool SHALL preserve the existing award-query business Envelope so that the Agent can distinguish a successful query, an absent award, and a protocol or transport failure without parsing free-form text.

#### Scenario: Existing award is queried
- **WHEN** the model invokes `get_award_detail` with an existing positive award ID in MCP experiment mode
- **THEN** the Tool result SHALL contain the same `success`, `code`, `data`, `message`, and `retryable` values as the Java REST award-detail result for the same business fact

#### Scenario: Award does not exist
- **WHEN** the model invokes `get_award_detail` with a positive award ID that does not exist
- **THEN** the Tool execution SHALL complete as a business result with `success=false` and `code=AWARD_NOT_FOUND`
- **AND** it SHALL NOT be misclassified as an MCP protocol failure

### Requirement: Existing internal business calls remain on REST
The experiment SHALL change only the model-visible direct award-detail Tool. Award queries made inside deterministic Python planning, recommendation, memory, or controlled-exchange services MUST continue using the existing REST client.

#### Scenario: Points planning uses award details
- **WHEN** the user asks for a points plan while the MCP award-query experiment is enabled
- **THEN** the deterministic planning service SHALL continue obtaining its required business facts through the existing REST client
- **AND** the experiment SHALL NOT introduce an extra model-visible MCP call into that workflow

#### Scenario: Controlled exchange uses award details
- **WHEN** the user prepares or confirms a controlled exchange while the experiment is enabled
- **THEN** the existing confirmation, identity, idempotency and old transaction-message chain SHALL remain unchanged
- **AND** internal award-detail lookup SHALL continue through REST

### Requirement: The affected user Agent path awaits async Tools without widening the migration
The system SHALL execute the user Agent through `ainvoke()` and await it from HTTP and CLI boundaries. It SHALL preserve per-session ordering and SHALL NOT convert the operator Agent or deterministic Python Services to MCP or async merely as a side effect of this change.

#### Scenario: HTTP user chat invokes an async remote Tool
- **WHEN** `/v1/chat` handles a user request in MCP experiment mode
- **THEN** the FastAPI route SHALL await the user runtime and Agent directly
- **AND** it SHALL NOT create a nested or background event loop to invoke the remote Tool

#### Scenario: CLI user Agent invokes an async remote Tool
- **WHEN** the interactive or one-shot CLI runs the user Agent
- **THEN** the CLI SHALL create one event loop at the process boundary and await the user Agent flow
- **AND** deterministic CLI planning modes that do not invoke the Agent SHALL remain on their existing synchronous REST path

#### Scenario: Concurrent requests share a session
- **WHEN** two user requests target the same `user_id` and `session_id`
- **THEN** the runtime SHALL execute them in session order using an async-compatible lock
- **AND** cancellation or failure SHALL release the lock so a later request can proceed

#### Scenario: Operator Agent is used
- **WHEN** an operator conversation executes during or after this change
- **THEN** its existing synchronous runtime and Tool path SHALL remain unchanged

### Requirement: MCP use is observable without exposing business payloads
The system SHALL record whether the model-visible award-detail Tool used REST or MCP, retain the current request-level Tool trace, and avoid logging complete award payloads or credentials.

#### Scenario: MCP Tool completes
- **WHEN** an MCP-backed award-detail call succeeds or returns a business failure
- **THEN** the Agent trace SHALL identify `get_award_detail` and `transport=mcp`
- **AND** logs SHALL include bounded status and elapsed-time information without the full Tool response

### Requirement: End-to-end Agent behavior is verified
The change SHALL be accepted only after an Agent-level scenario proves that a user request causes the model-visible remote Tool to execute through MCP and that the resulting answer is based on the returned structured business data.

#### Scenario: User asks for an award detail
- **WHEN** a representative user asks for the details of a known award while MCP experiment mode is enabled
- **THEN** the execution trace SHALL contain exactly one model-visible `get_award_detail` MCP call with the expected `award_id`
- **AND** the Java REST award-detail endpoint SHALL not be called by that direct Tool execution
- **AND** the final answer SHALL reflect the structured MCP result
