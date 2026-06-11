# Environment Agent Protocol & Dynamic Replanning Architecture

**Date:** 2026-06-11
**Status:** Design
**Scope:** Evolution of Celeste-DAG from a local co-located engine to a multi-mode system supporting local, remote, and embedded deployment.

---

## Problem Statement

Celeste-DAG's current architecture assumes the engine, database, and work all run on the same machine. The planner receives no automatic environment context — it plans blindly. The engine executes via local subprocess only. This works for local development but breaks when:

1. The engine runs as a remote service and needs to interact with distant environments
2. The planner needs environment state to make intelligent decisions about what tasks to create next
3. A workflow needs dynamic replanning mid-execution based on results from completed tasks

The core problem is **bidirectional environment interaction**: the engine needs eyes (observation) and hands (execution) in the target environment, regardless of where the engine itself runs.

## Design Goals

- Support three deployment modes: local (co-located), remote (service dispatching to distant environments), embedded (library imported by host applications)
- Enable dynamic replanning — the planner runs inside the execution loop, not before it
- Maintain the existing Elixir/OTP-inspired disciplines (share-nothing isolation, message-passing, supervision, let-it-crash with Saga compensation)
- Build on existing code (workspaces, event-sourced ledger, toolkits, security auditor) rather than replacing it
- Use MCP (Model Context Protocol) as the environment interaction standard — don't invent a new protocol

---

## Architecture Overview: Four Layers

```
┌──────────────────────────────────────────────────┐
│ Layer 4: Deployment Modes                         │
│   Local | Remote | Embedded                       │
├──────────────────────────────────────────────────┤
│ Layer 3: Durable Execution                        │
│   Event-sourced ledger with LLM result caching    │
│   Continue-As-New for long workflows              │
├──────────────────────────────────────────────────┤
│ Layer 2: OPA Loop (Observe → Plan → Act)          │
│   Continuous replanning cycle                     │
│   Tiered escalation: retry → replan → full → human│
├──────────────────────────────────────────────────┤
│ Layer 1: Environment Agent                        │
│   MCP-compatible observe + execute protocol       │
│   In-process | HTTP/WebSocket transports          │
└──────────────────────────────────────────────────┘
```

---

## Layer 1: Environment Agent

### Concept

An Environment Agent is a lightweight process that runs **inside** the target environment. It is the engine's sole interface to that environment — all observation and execution flows through it.

The Environment Agent is an MCP server. It speaks JSON-RPC over MCP's pluggable transport layer (stdio for local, WebSocket for remote). It inherits MCP's capability discovery, schema validation, and bidirectional communication for free.

**Protocol decision:** The engine-agent wire protocol uses MCP for tool schema discovery and semantics, but transports over WebSocket (primary) or stdio (local) rather than full MCP HTTP/SSE transport. This gives us schema standardization without the latency overhead of HTTP-per-call.

### Two Capabilities

**Observation** (read-only queries about environment state):

```python
# Discover what tools are available in this environment
result = await agent.call_tool("discover_tools", {})
# → [{"name": "read_file", "schema": {...}}, {"name": "run_command", "schema": {...}}]

# List files in a directory
result = await agent.call_tool("list_directory", {"path": "/src"})
# → ["main.py", "utils.py", "tests/"]

# Read a file
result = await agent.call_tool("read_file", {"path": "/src/main.py"})
# → {"content": "...", "size": 1024}

# Get environment snapshot (consolidated state)
result = await agent.call_tool("snapshot", {"paths": ["/src"], "include_processes": True})
# → {"files": {...}, "processes": [...], "tools": [...], "platform": "darwin"}
```

**Execution** (run commands, invoke tools, modify state):

```python
# Run a shell command
result = await agent.call_tool("run_command", {
    "command": "pytest",
    "args": ["-v"],
    "cwd": "/src",
    "timeout": 300
})
# → {"exit_code": 0, "stdout": "...", "stderr": "", "artifacts": []}

# Write a file
result = await agent.call_tool("write_file", {"path": "/src/new.py", "content": "..."})
# → {"success": true, "size": 256}

# Invoke a registered tool
result = await agent.call_tool("http_get", {"url": "https://api.example.com/data"})
# → {"status": 200, "body": "..."}
```

### Transport Modes

| Mode | Transport | Use Case | Status |
|------|-----------|----------|--------|
| **In-process** | Direct Python function calls (no network, no serialization) | Local development, embedded SDK | Primary for local |
| **WebSocket** | Persistent bidirectional connection with JSON-RPC framing | Remote orchestration, multi-machine | **Primary for remote** |
| **HTTP/SSE** | Agent runs as HTTP server, engine connects via HTTP POST + SSE streaming | Remote orchestration, legacy compatibility | Legacy fallback |
| **stdio** | Agent spawned as child process, communicates over stdin/stdout | CLI tools, local integrations, testing | Testing/CLI |

The engine selects the transport mode based on configuration. The protocol (JSON-RPC method names, parameter schemas, response shapes) is identical across all transports.

**Transport performance:** WebSocket is the primary remote transport because it avoids the 50-100ms HTTP roundtrip latency per tool call. A workflow with 100 tool calls saves 5-10 seconds of pure network overhead. HTTP/SSE remains as a legacy fallback for environments where WebSocket is blocked.

### Built-in Tools

Every Environment Agent exposes a standard set of observation and execution tools:

**Observation tools:**
- `snapshot` — consolidated environment state (files, processes, platform)
- `list_directory` — directory listing with metadata
- `read_file` — file content retrieval
- `discover_tools` — list all registered MCP tools with schemas
- `check_command` — verify a command is available (e.g., `check_command("python")`)
- `stat` — file/directory metadata (size, modified time, permissions)

**Execution tools:**
- `run_command` — execute a shell command with timeout and working directory
- `write_file` — create or overwrite a file
- `delete_file` — remove a file
- `mkdir` — create a directory tree

**Additional tools are registered dynamically** from the toolkit system (`SystemDataToolkit`, `WebScrapingToolkit`, `CodingVerticalToolkit`). The agent's `discover_tools` method returns the union of built-in tools and registered toolkit tools.

### Agent Lifecycle

```python
class EnvironmentAgent:
    """MCP-compatible environment agent."""

    async def start(self) -> None:
        """Start the agent. In-process: no-op. Remote: start WebSocket server."""

    async def stop(self) -> None:
        """Stop the agent gracefully. Closes connections, cancels in-flight tool calls."""

    async def call_tool(self, name: str, arguments: dict, timeout_ms: int | None = None) -> dict:
        """Invoke a tool on the agent. Works across all transports.
        
        Security pipeline:
        1. Engine-side SecurityAuditor validates the tool call before sending
        2. Agent-side SecurityAuditor validates before executing
        3. ToolRegistry allowlist check
        4. Driver dispatch to toolkit or built-in implementation
        """

    async def list_tools(self) -> list[dict]:
        """Discover available tools (MCP tools/list).
        Returns union of built-in tools and registered toolkit tools.
        """

    def register_toolkit(self, toolkit: BaseToolkit) -> None:
        """Register additional tools from a toolkit."""
```

### Security

The Environment Agent enforces the existing two-phase security model:

1. All tool calls pass through the `SecurityAuditor` before execution
2. All tool calls pass through the `ToolRegistry` allowlist validation
3. The agent only exposes tools that have been explicitly registered — no ad-hoc command execution outside the tool framework

For remote agents, additional transport-level security applies:
- TLS for WebSocket connections
- API key or mTLS authentication
- Session tokens with expiration
- Both engine-side and agent-side security audit (defense-in-depth)

---

## Layer 2: OPA Loop (Observe → Plan → Act)

### Concept

The OPA loop replaces the current "planner generates full DAG upfront, engine executes it all" model with a continuous cycle. The planner is called **inside** the execution loop, not before it.

The planner decides batch size dynamically — it may produce 1 sequential task or 20 parallel fan-out tasks per cycle, depending on the situation.

### The Loop

```python
class OPALoop:
    """Observe → Plan → Act → Evaluate cycle with safety limits."""

    async def run(self, goal: str) -> WorkflowResult:
        """Run a workflow using sequential OPA cycles."""
        cycle_count = 0
        llm_tokens_accumulated = 0

        while True:
            # --- Safety limits ---
            cycle_count += 1
            if cycle_count >= self._settings.MAX_OPA_CYCLES:
                return self._escalate("max_cycles_exceeded")
            if llm_tokens_accumulated >= self._settings.MAX_LLM_TOKENS:
                return self._escalate("token_budget_exceeded")

            # 1. OBSERVE
            try:
                observation = await self._agent.call_tool(
                    "snapshot",
                    {},
                    timeout_ms=self._settings.SNAPSHOT_TIMEOUT_MS
                )
            except SnapshotTimeoutError:
                observation = {"truncated": True, "reason": "timeout", "files": {}}

            tool_schemas = await self._agent.list_tools()

            # 2. PLAN
            try:
                plan_fragment = await asyncio.wait_for(
                    self._planner.plan(
                        goal=goal,
                        observation=observation,
                        tool_schemas=tool_schemas,
                        history=self._execution_history,
                    ),
                    timeout=self._settings.PLANNER_TIMEOUT_MS / 1000
                )
                llm_tokens_accumulated += plan_fragment.token_usage
            except asyncio.TimeoutError:
                if cycle_count == 1:
                    return self._escalate("planner_timeout_no_progress")
                # Retry with simplified prompt on next cycle
                continue

            # 3. ACT
            await self._executor.execute_fragment(plan_fragment)

            # 4. EVALUATE
            decision = await self._evaluator.evaluate(plan_fragment, goal)
            llm_tokens_accumulated += decision.token_usage

            if decision == "DONE":
                return self._complete_workflow()
            elif decision == "ESCALATE":
                return self._escalate(decision.reason)
            elif decision in ("REPLAN", "CONTINUE"):
                continue  # back to OBSERVE
```

**Key design decisions:**
- **Sequential planning:** The planner waits for full fragment execution before planning the next cycle. This avoids resource conflicts and dependency violations that pipelined planning would introduce.
- **Hard limits:** `MAX_OPA_CYCLES` (default 100) and `MAX_LLM_TOKENS` (default 50000) prevent infinite loops.
- **Timeout handling:** Snapshot has 5s timeout with partial fallback. Planner has 60s timeout with tiered retry (escalate if no progress, replan if progress made).

### What the Planner Produces

A `DAGFragment` — not a full DAG, but a batch of tasks for one cycle:

```python
class DAGFragment(BaseModel):
    """A batch of tasks produced by one planning cycle."""
    nodes: list[DAGNode]
    reasoning: str                    # Why the planner chose these tasks
    estimated_remaining: int | None   # Planner's estimate of remaining cycles (optional)
    goal_achieved: bool = False       # Planner believes the goal is met

class DAGNode(BaseModel):
    """A single task in a fragment."""
    task_id: str
    command: str                      # Tool name or shell command
    arguments: dict[str, Any]
    depends_on: list[str]             # IDs of nodes this depends on (from this or previous fragments)
    preconditions: list[str] | None   # What must be true before execution
    postconditions: list[str] | None  # What this task guarantees after completion
    compensation: str | None          # Saga rollback command
```

### How the Fragment Graph Grows

```
Cycle 1:  [T1] → [T2]
           T1: discover_tools()
           T2: run_command("pip install -r requirements.txt")
           Depends_on: T2 depends on T1

Cycle 2:  [T1] → [T2] → [T3, T4, T5]   (fan-out based on T2's output)
           T3: read_file("src/auth.py")
           T4: read_file("src/api.py")
           T5: read_file("src/models.py")
           Depends_on: T3,T4,T5 all depend on T2

Cycle 3:  [T1] → [T2] → [T3,T4,T5] → [T6]  (join + continue)
           T6: run_command("pytest tests/")
           Depends_on: T6 depends on T3,T4,T5
```

### Tiered Escalation

When something goes wrong, the system escalates through four levels:

| Level | Trigger | Response | Scope | Who Handles |
|-------|---------|----------|-------|-------------|
| **1. Local retry** | Transient error (network timeout, process OOM) | Retry same task with backoff (max 3x) | Single task | Engine (automatic) |
| **2. Scoped replan** | Postcondition mismatch, tool failure, precondition violation | Replan only the affected subtree | Subtree from failure point | Planner (one LLM call) |
| **3. Full replan** | Environment changed drastically, goal no longer achievable with current approach | Re-observe environment, generate entirely new plan | Entire workflow | Planner (fresh OPA cycle) |
| **4. Human escalation** | All retries exhausted, security violation, ambiguous goal | Pause workflow, notify, wait for human input | Workflow paused | Human (manual) |

**Proactive precondition checking** (from the ALAS/SagaLLM research): Before executing a task, the engine validates its preconditions against the current environment state. If a precondition is violated, the engine escalates to scoped replan **before** attempting execution — catching problems early rather than after failure.

### The Planner's Prompt Structure

The planner receives structured context each cycle:

```
System: You are a dynamic task planner. Given the goal, current environment state,
available tools, and execution history, generate the next batch of tasks.

Goal: {workflow.goal}

Environment State:
{observation_snapshot}

Available Tools:
{tool_schemas_json}

Execution History:
- T1 (completed): discover_tools → found 12 tools
- T2 (completed): pip install → installed 15 packages
- T3 (completed): read_file auth.py → 234 lines, uses Flask-Login
- T4 (completed): read_file api.py → 189 lines, uses JWT
- T5 (failed): run_command mypy → exit code 1, type errors in auth.py:15, api.py:42

Remaining Goal: Fix type errors and ensure tests pass.

Generate the next DAGFragment. Include preconditions, postconditions,
and compensation commands for each task.
```

---

## Layer 3: Durable Execution

### Concept

The OPA loop must survive crashes, restarts, and network failures. This layer extends the existing `TaskEvent` ledger with additional event types and implements Temporal-style replay with LLM result caching.

### Event Types (Extended)

The current `TaskEvent` ledger tracks task lifecycle events. The new design adds event types for each phase of the OPA loop:

```python
class EventType(str, Enum):
    # Existing
    NODE_STARTED = "node_started"
    NODE_COMPLETED = "node_completed"
    NODE_FAILED = "node_failed"
    COMPENSATION_TRIGGERED = "compensation_triggered"
    WORKFLOW_SUBMITTED = "workflow_submitted"
    WORKFLOW_COMPLETED = "workflow_completed"

    # New — OPA loop events
    OBSERVATION_CAPTURED = "observation_captured"       # Environment snapshot
    PLAN_GENERATED = "plan_generated"                   # Planner output (LLM result cached)
    EVALUATION_RESULT = "evaluation_result"             # Loop decision (CONTINUE/REPLAN/ESCALATE)
    PRECONDITION_CHECKED = "precondition_checked"       # Proactive validation result
    COMPENSATION_COMPLETED = "compensation_completed"   # Saga rollback completed
    CYCLE_STARTED = "cycle_started"                     # OPA cycle boundary marker
    CHECKPOINT = "checkpoint"                           # Continue-As-New snapshot
```

### Crash Recovery (Replay)

When the engine restarts after a crash:

1. Find all workflows with status `RUNNING` in the database
2. For each workflow, read the full `TaskEvent` ledger ordered by sequence number
3. Replay events to reconstruct in-memory state:
   - `WORKFLOW_SUBMITTED` → restore goal and context
   - `OBSERVATION_CAPTURED` → restore last known environment state
   - `PLAN_GENERATED` → restore current DAG fragment (read the recorded plan, do NOT call LLM)
   - `NODE_STARTED/COMPLETED/FAILED` → restore task statuses
   - `EVALUATION_RESULT` → restore last loop decision
4. Determine the OPA loop position from the last event:
   - Last event was `OBSERVATION_CAPTURED` → resume at PLAN phase
   - Last event was `PLAN_GENERATED` → resume at ACT phase (execute the plan)
   - Last event was `NODE_COMPLETED/FAILED` → resume at EVALUATE phase
   - Last event was `EVALUATION_RESULT("CONTINUE")` → start new OBSERVE phase
5. Resume the OPA loop from that position

**Critical rule: LLM calls are NEVER re-executed during replay.** Every LLM output (plans, security audits) is persisted as an event. Replay reads the recorded output. This gives us Temporal's durability without Temporal's determinism constraint.

### Continue-As-New

When the event ledger for a workflow exceeds a configurable threshold (default: 500 events or 10MB):

1. Record a `CHECKPOINT` event containing the full workflow state:
   - Goal, context, completed node IDs with outputs, failed node IDs, current OPA cycle number
2. Create a new workflow run with the checkpoint as initial state
3. Archive the old event ledger (readable for auditing, but not replayed)

This prevents replay performance from degrading over time for long-running workflows.

---

## Layer 4: Deployment Modes

### Mode 1: Local Development

```python
# As a library (no server)
from celeste_dag import Engine, EnvironmentAgent, LocalWorkspace

agent = EnvironmentAgent.in_process(
    workdir="/Users/tom/my-project",
    toolkits=[SystemDataToolkit(), CodingVerticalToolkit()],
)

engine = Engine(
    agent=agent,
    workspace_factory=LocalWorkspace.factory,
    settings=EngineSettings(DATABASE_URL="sqlite+aiosqlite:///celeste.db"),
)

result = await engine.run(goal="Fix the failing tests in the auth module")
```

```
┌─────────────────────────────────────────┐
│  Single Process                         │
│                                         │
│  Engine ←→ OPA Loop                     │
│     │                                   │
│     ├── Environment Agent (in-process)  │
│     │     └── direct os/subprocess calls│
│     │                                   │
│     ├── Workspace: LocalTmp or          │
│     │   GitWorktree                     │
│     │                                   │
│     └── SQLite ledger                   │
│                                         │
│  FastAPI: optional admin/monitor UI     │
└─────────────────────────────────────────┘
```

The agent wraps `os.*`, `subprocess.*`, and `pathlib.*` behind its protocol. Zero network overhead. FastAPI is optional — the engine works as a plain async library.

**Agent-Workspace relationship:** In local mode, the Environment Agent does **not** bypass workspace isolation. When the engine needs to execute a task, it still creates a workspace (LocalTmp, GitWorktree, etc.) and runs the agent's tool calls **inside** that workspace's working directory. The agent provides the protocol; the workspace provides the sandbox. For observation tools (read_file, list_directory, snapshot), the agent reads from the workspace's directory. For execution tools (run_command, write_file), the agent runs within the workspace's directory and process boundary.

### Mode 2: Remote Orchestration

```python
# Engine on server
from celeste_dag import Engine, EnvironmentAgent

agent = EnvironmentAgent.remote(
    url="ws://worker-3.internal:8080",
    auth_token="...",
)

engine = Engine(agent=agent, settings=EngineSettings(
    DATABASE_URL="postgresql+asyncpg://...",
))
```

```python
# Agent on target machine (separate process)
from celeste_dag import EnvironmentAgent

agent = EnvironmentAgent.serve(
    host="0.0.0.0",
    port=8080,
    workdir="/workspace",
    toolkits=[SystemDataToolkit(), WebScrapingToolkit()],
    auth_token="...",
)
await agent.start()  # Starts WebSocket server
```

```
┌─────────────────────┐          ┌─────────────────────────┐
│  Celeste-DAG Server │          │  Target Environment     │
│                     │          │                         │
│  Engine             │   WS/    │  Environment Agent      │
│  OPA Loop           │◄─WS─────►│    ├── observe() calls  │
│  PostgreSQL ledger  │          │    └── execute() calls  │
│  FastAPI API        │          │                         │
│                     │          │  Workspace: Docker or   │
│                     │          │  Firecracker (optional) │
└─────────────────────┘          └─────────────────────────┘
```

The agent runs as a lightweight WebSocket server on the target machine. The engine connects via a persistent WebSocket connection. This avoids the 50-100ms HTTP roundtrip latency per tool call. The agent has full local filesystem and process access.

For environments behind firewalls/NAT, the agent can run in **pull mode** — it long-polls the engine for tasks instead of the engine pushing to it. This is the Buildkite/Temporal worker pattern.

### Mode 3: Embedded SDK

```python
# Host application embeds Celeste-DAG
from celeste_dag import Engine, EnvironmentAgent

# Register host application's own tools
agent = EnvironmentAgent.in_process(
    workdir="/app/workspace",
    toolkits=[
        SystemDataToolkit(),
        CustomToolkit(my_custom_tools=[...]),
    ],
)

engine = Engine(agent=agent)

# Use in a web app, CLI tool, or any Python application
@app.post("/automate")
async def automate(request: AutomationRequest):
    result = await engine.run(
        goal=request.goal,
        context=request.context,
    )
    return result
```

The host app creates an in-process agent, registers its own tools, and calls the engine directly. No separate server process, no network. The engine is a library.

### Configuration

The deployment mode is selected by how the `EnvironmentAgent` is constructed, not by a global setting:

```python
# Local (in-process)
agent = EnvironmentAgent.in_process(workdir=..., toolkits=[...])

# Remote (connect to existing agent)
agent = EnvironmentAgent.remote(url=..., auth_token=...)

# Remote (pull mode — agent polls engine)
agent = EnvironmentAgent.remote_pull(engine_url=..., poll_interval=5)

# Serve (run agent as standalone server for remote mode)
agent = EnvironmentAgent.serve(host=..., port=..., workdir=..., toolkits=[...])
```

---

## Relationship to Existing Components

| Component | What Changes | What Stays |
|-----------|-------------|------------|
| `engine.py` | Add OPA loop, remove single-shot execution | Event recording, Semaphore concurrency, workspace factory |
| `planner.py` | Accept observation + tool schemas as input, produce `DAGFragment` instead of full `DAGPlan` | LLM client integration, structured output, fan-out generation |
| `workspaces/` | No changes. Workspaces define sandbox boundaries. Agent runs inside them. | `BaseWorkspace` ABC, `LocalTmpWorkspace`, `GitWorktreeWorkspace` |
| `database/models.py` | Add new `EventType` values for OPA loop events | `Workflow`, `TaskNode`, `TaskEvent` models |
| `database/db.py` | No changes | SQLite/PostgreSQL switching |
| `toolkits/` | Toolkits gain `execute(name, args, driver)` method. `ToolDefinition` stays frozen schema-only. | `BaseToolkit`, `SystemDataToolkit`, `WebScrapingToolkit`, `CodingVerticalToolkit` |
| `tools/security_auditor.py` | Applied by the Environment Agent before executing any tool call | Two-phase audit (deterministic + LLM fallback) |
| `tools/tool_registry.py` | Applied by the Environment Agent to validate tool calls | Strict allowlist, MCP schema generation |
| `core/llm/` | No changes | Multi-provider adapters |
| `api/app.py` | New endpoints: `POST /agents/register`, `GET /agents/{id}/status` for remote agent management | Existing workflow CRUD and execution endpoints |
| **New: `core/agent/`** | `EnvironmentAgent`, `BaseDriver`, `ShellDriver`, `FilesystemDriver`, transport implementations | — |
| **New: `core/opa_loop.py`** | `OPALoop` class with sequential planning and safety limits | — |
| **New: `core/evaluator.py`** | `Evaluator` class with LLM-based decision and optional cache | — |
| **New: `core/context_window.py`** | `ContextWindowManager` for prompt truncation and summarization | — |
| **New: `database/models.py`** | `WorkflowEvent` table, extended `EventType` enum | — |

### The Big Wiring Change

Today, toolkits are **schema-only** — they tell the planner what tools exist but have no execution logic. The engine runs raw shell commands via `workspace.execute()`.

In the new design, toolkits become **executable via a driver interface** — `BaseToolkit` gains an `execute(name, args, driver)` method that receives a driver object (filesystem, shell, HTTP) and performs the actual operation. `ToolDefinition` remains a frozen schema dataclass. The Environment Agent creates the appropriate driver and dispatches tool calls. The planner still receives MCP schemas from the agent (via `discover_tools`), but now those schemas are backed by real implementations.

```
Before:  Planner → reads toolkit schemas → generates plan with shell commands
         Engine  → runs shell commands via workspace.execute()

After:   Planner → queries agent.list_tools() → generates plan with tool calls
         Engine  → dispatches tool calls via agent.call_tool() 
                → agent creates driver → toolkit.execute(driver) → actual operation
```

---

## Module Breakdown

This section lists every file that must be created or modified. A coding agent should create these files in order, writing tests first per the TDD Test Plan.

### New Files

| File | Classes / Functions | Phase |
|------|---------------------|-------|
| `src/celeste_dag/core/agent/__init__.py` | Module exports | 1 |
| `src/celeste_dag/core/agent/agent.py` | `EnvironmentAgent` | 1 |
| `src/celeste_dag/core/agent/driver.py` | `BaseDriver`, `ShellDriver`, `FilesystemDriver` | 1 |
| `src/celeste_dag/core/agent/transport.py` | `BaseTransport`, `InProcessTransport` | 1 |
| `src/celeste_dag/core/agent/transport_ws.py` | `WebSocketTransport`, `WebSocketServer` | 4 |
| `src/celeste_dag/core/agent/transport_stdio.py` | `StdioTransport` | 1 |
| `src/celeste_dag/core/opa_loop.py` | `OPALoop`, `WorkflowResult` | 2 |
| `src/celeste_dag/core/evaluator.py` | `Evaluator`, `EvaluatorDecision` | 2 |
| `src/celeste_dag/core/context_window.py` | `ContextWindowManager` | 2 |
| `src/celeste_dag/core/exceptions.py` | `PlannerTimeoutError`, `SnapshotTimeoutError`, `ToolTimeoutError`, `PathTraversalError`, `AuthenticationError` | 1-2 |
| `tests/test_agent.py` | See TDD Test Plan — Phase 1 | 1 |
| `tests/test_driver_interface.py` | See TDD Test Plan — Driver | 1 |
| `tests/test_agent_transports.py` | See TDD Test Plan — Transports | 1+4 |
| `tests/test_opa_loop.py` | See TDD Test Plan — OPA Loop | 2 |
| `tests/test_evaluator.py` | See TDD Test Plan — Evaluator | 2 |
| `tests/test_workflow_events.py` | See TDD Test Plan — WorkflowEvent | 3 |
| `tests/test_checkpoint.py` | See TDD Test Plan — Continue-As-New | 3 |
| `tests/test_remote_e2e.py` | See TDD Test Plan — E2E | 4 |
| `.github/workflows/agent-docker.yml` | CI/CD for agent Docker image | 4 |

### Modified Files

| File | Changes | Phase |
|------|---------|-------|
| `src/celeste_dag/core/engine.py` | Add `OPALoop` integration, `run()` method, delegate execution to `WorkflowExecutor` | 2 |
| `src/celeste_dag/core/planner.py` | Add `observation` + `tool_schemas` params to `plan()`. Merge `DAGNode` models. | 2 |
| `src/celeste_dag/database/models.py` | Add `WorkflowEvent` model, extend `EventType` enum | 3 |
| `src/celeste_dag/toolkits/base.py` | Add `execute(name, args, driver)` abstract method to `BaseToolkit` | 1 |
| `src/celeste_dag/toolkits/system_data.py` | Implement `execute()` for `read_file`, `list_directory`, `snapshot`, `run_command` | 1 |
| `src/celeste_dag/toolkits/web_scraping.py` | Implement `execute()` for `http_get`, etc. | 1 |
| `src/celeste_dag/toolkits/coding_vertical.py` | Implement `execute()` for coding-specific tools | 1 |
| `src/celeste_dag/config/settings.py` | Add all new settings from Configuration Reference | 1-2 |
| `src/celeste_dag/api/app.py` | Add `/agents/register`, `/agents/{id}/status` endpoints | 4 |
| `tests/test_engine.py` | Rewrite for OPA loop behavior | 2 |
| `tests/test_planner.py` | Add observation context tests | 2 |
| `tests/test_toolkits.py` | Add execution tests via driver | 1 |
| `tests/test_api.py` | Add agent endpoint tests | 4 |

---

## Migration Strategy

This is an additive evolution, not a rewrite. The existing 529 tests continue to pass.

### Phase 1: Environment Agent (Foundation)
- Create `src/celeste_dag/core/agent/` module
- Implement `EnvironmentAgent` with in-process transport
- Implement `BaseDriver`, `ShellDriver`, `FilesystemDriver`
- Refactor `BaseToolkit` to add `execute(name, args, driver)` abstract method
- Wire the agent into the existing engine as an optional layer (engine works with or without it)

### Phase 2: OPA Loop (Replanning)
- Refactor `engine.py` to support the OPA loop cycle
- Update `planner.py` to produce `DAGFragment` and accept observation context
- Add new `EventType` values to the event ledger
- Implement the tiered escalation system

### Phase 3: Durable Execution (Crash Recovery)
- Extend replay logic to handle new event types
- Implement LLM result caching (record plan outputs, skip LLM on replay)
- Implement Continue-As-New for long workflows
- Implement proactive precondition checking

### Phase 4: Remote Deployment (Multi-Machine)
- Implement WebSocket transport for `EnvironmentAgent` (primary)
- Implement HTTP/SSE transport as legacy fallback
- Implement `EnvironmentAgent.serve()` for running agents as standalone WebSocket servers
- Add agent registration endpoints to the API
- Implement pull-mode workers for firewall/NAT traversal
- Add CI/CD pipeline for building/publishing agent Docker images

---

## Research Sources

### Agent Orchestration
- LangGraph: State-based graph execution with conditional edges and `Send` API for fan-out
- Temporal.io: Workflow/activity split, event-sourced replay, pull-based workers, Continue-As-New
- AutoGen/AG2: Code writer/executor separation, multiple execution backends
- Prefect: Flows as Python code, dynamic task mapping
- Airflow: `expand()` for dynamic fan-out, XCom for inter-task data

### Deployment Topologies
- MCP (Model Context Protocol): JSON-RPC over pluggable transport (stdio, HTTP/SSE), capability discovery
- Ansible: Agentless push model, ship-module-execute-cleanup, idempotent design
- SaltStack: Minion-initiated outbound connections, ZeroMQ message bus, Grains for observation
- Buildkite: Agent long-polls for work, POSTs results
- Kubernetes Operators: Reconciliation loop (observe → diff → act → repeat)

### Academic Research
- LLMCompiler (Kim et al.): Streaming DAG with variable references, dynamic replanning via Joiner
- HTN Plan Repair (Goldman et al., ICAPS 2025): Dependency-graph-based scoped repair with backjumping
- ALAS (arXiv:2505.12501): Disruption-aware planning with local-first escalation
- SagaLLM (arXiv:2503.11951): Saga pattern applied to multi-agent LLM planning
- Plan-and-Act (arXiv:2503.09572): +34 percentage point improvement over ReAct via per-step replanning
- Agent Interoperability Protocols Survey (arXiv:2505.02279): MCP → ACP → A2A → ANP adoption roadmap

---

## Configuration Reference

All new settings are added to `EngineSettings` (`src/celeste_dag/config/settings.py`).

| Setting | Default | Description |
|---------|---------|-------------|
| `SNAPSHOT_TIMEOUT_MS` | 5000 | Max time (ms) for `snapshot` tool before partial fallback |
| `SNAPSHOT_FULL_INTERVAL_CALLS` | 10 | Auto full-snapshot every N calls |
| `SNAPSHOT_FULL_INTERVAL_SECONDS` | 300 | Auto full-snapshot every N seconds |
| `PLANNER_TIMEOUT_MS` | 60000 | Max time (ms) for planner LLM call |
| `PLANNER_MAX_RETRIES` | 2 | Planner timeout retries before escalation |
| `MAX_OPA_CYCLES` | 100 | Hard limit on OPA loop iterations |
| `MAX_LLM_TOKENS` | 50000 | Cumulative token budget per workflow |
| `EVALUATOR_CACHE_ENABLED` | True | Whether to cache evaluator decisions |
| `EVALUATOR_CACHE_TTL_SECONDS` | 3600 | TTL for evaluator decision cache |
| `WORKSPACE_ENGINE` | "local_tmp" | Workspace type (local_tmp, git_worktree, docker, firecracker) |

Per-workflow overrides via `engine.run(goal, max_cycles=50, max_llm_tokens=20000)`.

---

## TDD Test Plan

This section is written for a coding agent to implement the plan using strict test-driven development. **Every test listed below must be written before the implementation that makes it pass.**

### Test Infrastructure

**Shared fixtures** (in `tests/conftest.py` or equivalent):

```python
@pytest.fixture
async def mock_llm_client():
    """Returns a stub LLM client that records calls and returns canned responses."""
    ...

@pytest.fixture
async def mock_workspace():
    """Returns a mock workspace that yields configurable events."""
    ...

@pytest.fixture
async def in_memory_db():
    """Sets up an in-memory SQLite database for isolated tests."""
    ...

@pytest.fixture
async def engine(mock_llm_client, mock_workspace, in_memory_db):
    """Returns a configured Engine instance with mocked dependencies."""
    ...
```

---

### Phase 1 Tests: Environment Agent

**File: `tests/test_agent.py`**

#### `test_agent_in_process_start_stop_is_noop`
- **Setup:** `agent = EnvironmentAgent.in_process(workdir="/tmp", toolkits=[])`
- **Action:** `await agent.start()` then `await agent.stop()`
- **Assert:** No exceptions raised. `agent.is_running` is False before start and after stop.

#### `test_agent_call_tool_builtin_snapshot`
- **Setup:** In-process agent with `workdir="/tmp"`. Create file `/tmp/test.txt` with content `"hello"`.
- **Action:** `result = await agent.call_tool("snapshot", {"paths": ["/tmp"]})`
- **Assert:** `result["files"]` contains `"/tmp/test.txt"`. `result["platform"]` is non-empty.

#### `test_agent_call_tool_builtin_read_file`
- **Setup:** In-process agent with `workdir="/tmp"`. Create `/tmp/readme.md`.
- **Action:** `result = await agent.call_tool("read_file", {"path": "/tmp/readme.md"})`
- **Assert:** `result["content"] == "# Hello"`. `result["size"] == 7`.

#### `test_agent_call_tool_builtin_run_command`
- **Setup:** In-process agent.
- **Action:** `result = await agent.call_tool("run_command", {"command": "echo", "args": ["hello"]})`
- **Assert:** `result["exit_code"] == 0`. `result["stdout"] == "hello"`.

#### `test_agent_call_tool_routes_to_toolkit`
- **Setup:** Mock toolkit with one tool `"mock_tool"`. Register via `agent.register_toolkit(mock_toolkit)`.
- **Action:** `result = await agent.call_tool("mock_tool", {"arg": 1})`
- **Assert:** Mock toolkit's `execute()` was called with `("mock_tool", {"arg": 1}, driver)`.

#### `test_agent_call_tool_not_found_returns_error`
- **Setup:** In-process agent with no registered toolkits.
- **Action:** `result = await agent.call_tool("nonexistent", {})`
- **Assert:** `result["error"] == "tool_not_found"`. `result["tool_name"] == "nonexistent"`.

#### `test_agent_call_tool_security_audit_blocks`
- **Setup:** Agent with mock `SecurityAuditor` that always returns `is_safe=False`.
- **Action:** `result = await agent.call_tool("run_command", {"command": "rm -rf /"})`
- **Assert:** `result["error"] == "security_audit_failed"`. Command was NOT executed.

#### `test_agent_call_tool_tool_registry_blocks`
- **Setup:** Agent with empty `ToolRegistry`.
- **Action:** `result = await agent.call_tool("run_command", {"command": "echo hi"})`
- **Assert:** `result["error"] == "tool_not_allowed"`. Command was NOT executed.

#### `test_agent_call_tool_timeout_raises`
- **Setup:** Mock driver that sleeps for 10s.
- **Action:** `result = await agent.call_tool("slow_tool", {}, timeout_ms=100)`
- **Assert:** `result["error"] == "tool_timeout"`. `result["timeout_ms"] == 100`.

#### `test_agent_list_tools_returns_union`
- **Setup:** Agent with built-in tools + 1 registered toolkit with 2 tools.
- **Action:** `tools = await agent.list_tools()`
- **Assert:** Length is `len(builtin_tools) + 2`. Each tool has `name`, `description`, `inputSchema`.

#### `test_agent_register_toolkit_duplicate_overwrites`
- **Setup:** Register toolkit A with tool `"t1"`. Register toolkit B with tool `"t1"`.
- **Action:** `tools = await agent.list_tools()`
- **Assert:** Tool `"t1"` routes to toolkit B (last registered wins).

---

### Phase 1 Tests: Driver Interface

**File: `tests/test_driver_interface.py`**

#### `test_shell_driver_run_command`
- **Setup:** `driver = ShellDriver(cwd="/tmp")`
- **Action:** `result = await driver.run_command("echo hello", args=[], timeout=5)`
- **Assert:** `result.exit_code == 0`. `result.stdout == "hello"`.

#### `test_shell_driver_detects_sigkill`
- **Setup:** `driver = ShellDriver(cwd="/tmp")`
- **Action:** Start long-running command, `kill -9` the PID, await result.
- **Assert:** `result.exit_code == -9`. `result.killed_by_signal == 9`.

#### `test_filesystem_driver_read_file`
- **Setup:** `driver = FilesystemDriver(base_path="/tmp")`. Write `"content"` to `/tmp/file.txt`.
- **Action:** `result = await driver.read_file("/tmp/file.txt")`
- **Assert:** `result.content == "content"`. `result.size == 7`.

#### `test_filesystem_driver_list_directory`
- **Setup:** `driver = FilesystemDriver(base_path="/tmp")`. Create `/tmp/a.txt`, `/tmp/b.txt`.
- **Action:** `result = await driver.list_directory("/tmp")`
- **Assert:** `result.files == ["a.txt", "b.txt"]`.

#### `test_filesystem_driver_enforces_base_path`
- **Setup:** `driver = FilesystemDriver(base_path="/tmp/workspace")`
- **Action:** `await driver.read_file("/etc/passwd")`
- **Assert:** Raises `PathTraversalError`.

---

### Phase 1 Tests: Transports

**File: `tests/test_agent_transports.py`**

#### `test_in_process_transport_direct_call`
- **Setup:** `transport = InProcessTransport(agent_instance)`
- **Action:** `result = await transport.send_request("call_tool", {"name": "snapshot", "args": {}})`
- **Assert:** `result["files"]` is a dict. No serialization occurred.

#### `test_websocket_transport_roundtrip`
- **Setup:** Start agent WebSocket server on `ws://localhost:8765`. Connect client transport.
- **Action:** `result = await transport.send_request("call_tool", {"name": "read_file", "args": {"path": "/tmp/test.txt"}})`
- **Assert:** `result["content"] == "hello"`.

#### `test_websocket_transport_auth_failure`
- **Setup:** Agent server with `auth_token="secret"`. Client transport with wrong token.
- **Action:** `await transport.send_request("call_tool", {...})`
- **Assert:** Raises `AuthenticationError` with 401 status code.

#### `test_websocket_transport_reconnection`
- **Setup:** Connected WebSocket transport.
- **Action:** Server closes connection. Client retries with exponential backoff.
- **Assert:** Reconnects within 3 attempts. Subsequent call succeeds.

#### `test_stdio_transport_json_rpc`
- **Setup:** Spawn agent as subprocess with stdio transport.
- **Action:** Send JSON-RPC request: `{"jsonrpc": "2.0", "method": "call_tool", "params": {"name": "snapshot"}, "id": 1}`
- **Assert:** Response contains `result` with snapshot data.

---

### Phase 2 Tests: OPA Loop

**File: `tests/test_opa_loop.py`**

#### `test_opa_loop_goal_achieved_in_one_cycle`
- **Setup:** Mock planner returns fragment with `goal_achieved=True`. Mock evaluator returns `DONE`.
- **Action:** `result = await opa_loop.run(goal="do nothing")`
- **Assert:** `result.status == "completed"`. `cycle_count == 1`.

#### `test_opa_loop_goal_achieved_in_n_cycles`
- **Setup:** Mock planner returns fragments that build a chain. Cycle 3 returns `goal_achieved=True`.
- **Action:** `result = await opa_loop.run(goal="build chain")`
- **Assert:** `result.status == "completed"`. `cycle_count == 3`.

#### `test_opa_loop_tier1_retry_transient_failure`
- **Setup:** Fragment node fails with `process_killed`. Mock executor fails once, succeeds on retry.
- **Action:** `result = await opa_loop.run(goal="retry me")`
- **Assert:** Node was retried. `result.status == "completed"`.

#### `test_opa_loop_tier1_retry_exhausted_escalates_to_tier2`
- **Setup:** Fragment node fails 4 times (max retries = 3).
- **Action:** `result = await opa_loop.run(goal="fail forever")`
- **Assert:** `result.status == "escalated"`. `result.reason == "tier1_retries_exhausted"`.

#### `test_opa_loop_tier2_scoped_replan`
- **Setup:** Node fails with postcondition mismatch. Mock planner returns replacement fragment.
- **Action:** `result = await opa_loop.run(goal="replan subtree")`
- **Assert:** Scoped replan was triggered. Replacement fragment executed.

#### `test_opa_loop_tier3_full_replan`
- **Setup:** Environment changes drastically (simulated by mock agent returning different snapshot). Mock planner returns entirely new plan.
- **Action:** `result = await opa_loop.run(goal="adapt to change")`
- **Assert:** Full replan was triggered. New fragment executed.

#### `test_opa_loop_max_cycles_exceeded`
- **Setup:** Mock planner always returns `goal_achieved=False`, evaluator returns `CONTINUE`.
- **Action:** `result = await opa_loop.run(goal="never end", max_cycles=5)`
- **Assert:** `result.status == "escalated"`. `result.reason == "max_cycles_exceeded"`. `cycle_count == 5`.

#### `test_opa_loop_token_budget_exceeded`
- **Setup:** Mock planner returns fragments with high token usage.
- **Action:** `result = await opa_loop.run(goal="expensive", max_llm_tokens=100)`
- **Assert:** `result.status == "escalated"`. `result.reason == "token_budget_exceeded"`.

#### `test_opa_loop_evaluator_returns_escalate`
- **Setup:** Mock evaluator returns `ESCALATE` with `reason="ambiguous_goal"`.
- **Action:** `result = await opa_loop.run(goal="ambiguous")`
- **Assert:** `result.status == "escalated"`. `result.reason == "ambiguous_goal"`.

#### `test_opa_loop_agent_unreachable_during_observation`
- **Setup:** Mock agent raises `ConnectionError` on `call_tool("snapshot")`.
- **Action:** `result = await opa_loop.run(goal="unreachable")`
- **Assert:** `result.status == "escalated"`. `result.reason == "agent_unreachable"`.

#### `test_opa_loop_sequential_planning_no_pipeline`
- **Setup:** Mock planner and executor both take 100ms.
- **Action:** `await opa_loop.run(goal="sequential")`
- **Assert:** Verify that `planner.plan()` is NOT called while `executor.execute_fragment()` is in progress.

---

### Phase 2 Tests: Planner

**File: `tests/test_planner.py`**

#### `test_planner_accepts_observation_context`
- **Setup:** Planner with mock LLM client. Pass `observation={"files": {"a.py": "..."}}`.
- **Action:** `fragment = await planner.plan(goal="read a.py", observation=observation, tool_schemas=[...])`
- **Assert:** Mock LLM client received message containing `"files": {"a.py": "..."}`.

#### `test_planner_returns_dag_fragment`
- **Setup:** Mock LLM returns JSON matching `DAGFragment` schema.
- **Action:** `fragment = await planner.plan(goal="test", observation={}, tool_schemas=[])`
- **Assert:** `isinstance(fragment, DAGFragment)`. `len(fragment.nodes) > 0`.

#### `test_planner_timeout_raises_planner_timeout_error`
- **Setup:** Mock LLM client that sleeps for 120s.
- **Action:** `await planner.plan(goal="slow", timeout_ms=100)`
- **Assert:** Raises `PlannerTimeoutError`.

#### `test_planner_timeout_no_progress_escalates`
- **Setup:** OPA loop with `cycle_count=1`, planner times out.
- **Action:** `result = await opa_loop.run(goal="timeout on first cycle")`
- **Assert:** `result.status == "escalated"`. `result.reason == "planner_timeout_no_progress"`.

#### `test_planner_timeout_with_progress_replans`
- **Setup:** OPA loop with `cycle_count=3`, planner times out.
- **Action:** `result = await opa_loop.run(goal="timeout after progress")`
- **Assert:** Loop retries with simplified prompt. No escalation.

#### `test_dag_node_merged_model`
- **Setup:** Create `DAGNode` with only required fields (`task_id`, `command`).
- **Action:** Create `DAGNode` with all fields including `preconditions`, `postconditions`, `goal_achieved`.
- **Assert:** Both are valid. Optional fields default to `None`.

---

### Phase 2 Tests: Evaluator

**File: `tests/test_evaluator.py`**

#### `test_evaluator_returns_done`
- **Setup:** Mock LLM returns `{"decision": "DONE", "reason": "goal achieved"}`.
- **Action:** `decision = await evaluator.evaluate(fragment, goal="done goal")`
- **Assert:** `decision == "DONE"`.

#### `test_evaluator_returns_replan`
- **Setup:** Mock LLM returns `{"decision": "REPLAN", "reason": "postconditions not met"}`.
- **Action:** `decision = await evaluator.evaluate(fragment, goal="replan goal")`
- **Assert:** `decision == "REPLAN"`.

#### `test_evaluator_returns_escalate`
- **Setup:** Mock LLM returns `{"decision": "ESCALATE", "reason": "ambiguous"}`.
- **Action:** `decision = await evaluator.evaluate(fragment, goal="ambiguous goal")`
- **Assert:** `decision == "ESCALATE"`. `decision.reason == "ambiguous"`.

#### `test_evaluator_returns_continue`
- **Setup:** Mock LLM returns `{"decision": "CONTINUE", "reason": "more work needed"}`.
- **Action:** `decision = await evaluator.evaluate(fragment, goal="continue goal")`
- **Assert:** `decision == "CONTINUE"`.

#### `test_evaluator_cache_hit`
- **Setup:** Enable cache. Call evaluate twice with same fragment + goal.
- **Action:** Second call returns cached decision without LLM call.
- **Assert:** Mock LLM client called exactly once.

#### `test_evaluator_cache_miss_different_goal`
- **Setup:** Enable cache. Call evaluate with different goals.
- **Action:** Both calls hit LLM.
- **Assert:** Mock LLM client called twice.

---

### Phase 3 Tests: WorkflowEvent & Replay

**File: `tests/test_workflow_events.py`**

#### `test_workflow_event_recording`
- **Setup:** Workflow in database.
- **Action:** Record `WorkflowEvent(type=OBSERVATION_CAPTURED, workflow_id=wf.id, sequence_number=1)`.
- **Assert:** Event persisted. `sequence_number == 1`. `task_node_id is None`.

#### `test_workflow_event_sequence_ordering`
- **Setup:** Record events with sequence numbers 3, 1, 2.
- **Action:** Query `select(WorkflowEvent).order_by(WorkflowEvent.sequence_number)`.
- **Assert:** Results are [1, 2, 3].

#### `test_replay_resume_from_observation`
- **Setup:** Workflow events: WORKFLOW_SUBMITTED, OBSERVATION_CAPTURED. No PLAN_GENERATED.
- **Action:** `await engine.replay_workflow(wf.id)`
- **Assert:** OPA loop resumes at PLAN phase. Planner is called (not skipped).

#### `test_replay_resume_from_plan`
- **Setup:** Workflow events: WORKFLOW_SUBMITTED, OBSERVATION_CAPTURED, PLAN_GENERATED.
- **Action:** `await engine.replay_workflow(wf.id)`
- **Assert:** OPA loop resumes at ACT phase. Cached plan is executed. NO LLM call.

#### `test_replay_resume_from_evaluation_continue`
- **Setup:** Events ending with EVALUATION_RESULT("CONTINUE").
- **Action:** `await engine.replay_workflow(wf.id)`
- **Assert:** OPA loop starts new OBSERVE phase.

#### `test_replay_llm_never_re_executed`
- **Setup:** Events include PLAN_GENERATED with cached plan.
- **Action:** Replay and verify no LLM calls.
- **Assert:** Mock LLM client called zero times during replay.

---

### Phase 3 Tests: Continue-As-New

**File: `tests/test_checkpoint.py`**

#### `test_checkpoint_triggered_at_threshold`
- **Setup:** Workflow with 499 events. Threshold = 500.
- **Action:** Add 2 more events.
- **Assert:** `CHECKPOINT` event recorded. New workflow created with checkpoint state.

#### `test_checkpoint_contains_full_state`
- **Setup:** Workflow with completed nodes, failed nodes, cycle count.
- **Action:** Trigger checkpoint.
- **Assert:** Checkpoint contains goal, context, completed_node_ids, failed_node_ids, cycle_count.

#### `test_resume_from_checkpoint`
- **Setup:** New workflow created from checkpoint.
- **Action:** `await engine.run_workflow(new_wf_id)`
- **Assert:** Workflow resumes from checkpoint state. No re-execution of pre-checkpoint nodes.

---

### Phase 4 Tests: Remote E2E

**File: `tests/test_remote_e2e.py`**

#### `test_e2e_remote_agent_roundtrip`
- **Setup:** `agent = EnvironmentAgent.serve(host="127.0.0.1", port=8765)`. `engine = Engine(agent=EnvironmentAgent.remote(url="ws://127.0.0.1:8765"))`.
- **Action:** `result = await engine.run(goal="echo hello")`
- **Assert:** `result.status == "completed"`.

#### `test_e2e_remote_auth_failure`
- **Setup:** Agent with `auth_token="secret"`. Engine with wrong token.
- **Action:** `await engine.run(goal="test")`
- **Assert:** Raises `AuthenticationError`.

#### `test_e2e_remote_reconnection`
- **Setup:** Connected engine + agent. Kill agent process. Restart agent.
- **Action:** `await engine.run(goal="after reconnect")`
- **Assert:** Engine reconnects. Workflow completes.

---

### Regression Tests

**File: `tests/test_engine.py`** (rewritten)

#### `test_submit_workflow_creates_db_records`
- **Setup:** Engine with in-memory DB.
- **Action:** `wf_id = await engine.submit_workflow(SAMPLE_PLAN)`
- **Assert:** Workflow row exists. TaskNode rows == plan.nodes count.

#### `test_run_workflow_opa_loop_integration`
- **Setup:** Engine with mocked planner + evaluator.
- **Action:** `await engine.run_workflow(wf_id)`
- **Assert:** Mock planner called at least once. Mock evaluator called after each fragment.

#### `test_saga_compensation_reverse_order`
- **Setup:** Plan with 3 nodes, nodes 1 and 2 have compensation commands. Node 3 fails.
- **Action:** `await engine.run_workflow(wf_id)`
- **Assert:** Compensation executed in order: node 2 first, then node 1.

#### `test_replay_resets_orphaned_running_nodes`
- **Setup:** Workflow with node status RUNNING but no terminal event.
- **Action:** `await engine.start()` (triggers replay)
- **Assert:** Node status reset to PENDING.

#### `test_semaphore_limits_concurrency`
- **Setup:** Plan with 5 parallel nodes. `MAX_PARALLEL_SUBPROCESSES = 2`.
- **Action:** `await engine.run_workflow(wf_id)`
- **Assert:** Max 2 nodes executing simultaneously at any point.

---

## Failure Mode Mitigations

This section addresses the 5 critical failure mode gaps identified during /plan-eng-review.

### Gap 1: Snapshot Timeout on Large Workspace

**Problem:** `call_tool("snapshot", ...)` walks the filesystem with no timeout. Large workspaces can hang indefinitely, stalling the OPA loop.

**Mitigation:**
- `snapshot` tool accepts a `timeout_ms` parameter (default: 5000ms)
- Agent wraps the filesystem walk in `asyncio.wait_for()` with the timeout
- On timeout, agent returns partial results collected so far with `truncated: true` and `reason: "timeout"`
- OPA loop continues with partial observation rather than hanging
- `EngineSettings.SNAPSHOT_TIMEOUT_MS` makes the default configurable per-deployment

**Test requirement:** `tests/test_agent.py` — verify snapshot returns partial results on timeout, verify `truncated` flag is set.

### Gap 2: Planner LLM Timeout Fallback

**Problem:** `planner.plan()` calls the LLM with no timeout. A slow or unavailable LLM causes the OPA loop to hang indefinitely.

**Mitigation:**
- `Planner.plan()` accepts a `timeout_ms` parameter (default: 60000ms)
- On timeout, raises `PlannerTimeoutError`
- OPA loop catches `PlannerTimeoutError` with tiered behavior:
  - If no tasks have been executed yet → **ESCALATE** (cannot proceed without any plan)
  - If tasks have already been executed → **REPLAN** with a simplified prompt (truncated history, fewer tool schemas)
  - Retry up to `PLANNER_MAX_RETRIES` times (default: 2) with exponential backoff (2s, 4s)
- `EngineSettings.PLANNER_TIMEOUT_MS` (default: 60000) and `EngineSettings.PLANNER_MAX_RETRIES` (default: 2) make both values configurable
- After all retries exhausted → **ESCALATE** to Tier 4

**Test requirement:** `tests/test_planner.py` — verify timeout raises `PlannerTimeoutError`, verify retry behavior with mocked LLM, verify escalation after max retries.

### Gap 3: Subprocess OOM/Killed Detection

**Problem:** `run_command` subprocess can be killed by SIGKILL (OOM killer). Current code checks `returncode` but doesn't distinguish SIGKILL (-9) from a normal exit failure. The OPA loop can't tell if it should retry (OOM might be transient) or escalate.

**Mitigation:**
- After `proc.wait()`, check if `returncode < 0` — process was killed by a signal
- Emit `execution_killed` event with `signal: abs(returncode)` and `reason: "process_killed"`
- Agent returns structured error: `{"error": "process_killed", "signal": 9, "context": "Process may have been killed by OOM killer or system signal"}`
- OPA loop treats `process_killed` as **Tier 1 transient error** → retry with exponential backoff (up to 3×)
- After max retries → **Tier 2 scoped replan** (e.g., suggest running with fewer parallel tasks or smaller input)
- Distinguish from normal non-zero exit (`execution_failed`) which does NOT auto-retry

**Test requirement:** `tests/test_agent.py` — simulate SIGKILL with `kill -9`, verify `execution_killed` event, verify Tier 1 retry behavior, verify escalation after max retries.

### Gap 4: Evaluator Ambiguous Decision → Cycle Limit / Token Budget

**Problem:** LLM-based `evaluate()` might return CONTINUE or REPLAN indefinitely. A confused planner/evaluator pair could spin forever, burning tokens and events. No termination guarantee exists in the current design.

**Mitigation:**
- `EngineSettings` gains:
  - `MAX_OPA_CYCLES` (default: 100) — hard limit on OPA loop iterations per workflow
  - `MAX_LLM_TOKENS` (default: 50000) — cumulative token budget (prompt + completion) across all planner and evaluator calls
- `OPALoop` tracks:
  - `cycle_count` — increments each OBSERVE→PLAN→ACT→EVALUATE cycle
  - `llm_tokens_accumulated` — sums `usage.total_tokens` from every LLM call
- Before each new cycle:
  - If `cycle_count >= MAX_OPA_CYCLES` → **ESCALATE** with `reason: "max_cycles_exceeded"`
  - If `llm_tokens_accumulated >= MAX_LLM_TOKENS` → **ESCALATE** with `reason: "token_budget_exceeded"`
- Both limits recorded in the event ledger for audit
- Override per-workflow: `engine.run(goal, max_cycles=50, max_llm_tokens=20000)`
- Token budget is preferred over cost budget because token counts are deterministic from LLM responses, while pricing varies by provider and changes over time

**Test requirement:** `tests/test_opa_loop.py` — verify cycle limit triggers escalation, verify token budget triggers escalation, verify overrides work.

### Gap 5: Incremental Snapshot Stale Cache Fallback

**Problem:** Incremental snapshots use mtime cache to skip unchanged files. But clock skew (VMs, containers, network mounts) can make mtime unreliable, causing stale observations that mislead the planner.

**Mitigation:**
- `snapshot` tool gains `force_full: bool` parameter (default: false)
- Agent auto-triggers full snapshot every `SNAPSHOT_FULL_INTERVAL_CALLS` (default: 10) or every `SNAPSHOT_FULL_INTERVAL_SECONDS` (default: 300)
- Both intervals are configurable via `EngineSettings`
- OPA loop can request `force_full=True` when it detects inconsistencies (e.g., planner references a file that the snapshot says doesn't exist)
- Planner can optionally include `request_full_snapshot: true` in its output when it suspects stale data
- On `force_full=True`, the agent bypasses the mtime cache and performs a complete filesystem walk

**Test requirement:** `tests/test_agent.py` — verify incremental snapshot uses cache, verify full snapshot bypasses cache, verify auto full-snapshot triggers at correct intervals.

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | ISSUES | 17 issues, 5 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |

- **OUTSIDE VOICE:** Claude subagent review — 15 findings, 3 substantive tensions. User resolved all tensions: hybrid protocol (MCP schemas + custom WebSocket), both-sides security audit, sequential planning.
- **CROSS-MODEL:** Pipelined planning was recommended by review but rejected after outside voice raised correctness risks. MCP adoption was accepted by review but challenged by outside voice; user chose hybrid.
- **UNRESOLVED:** 0 unresolved decisions.
- **VERDICT:** Eng Review CLEARED — All 5 critical failure mode gaps resolved via Failure Mode Mitigations section.

### Critical Gaps (RESOLVED)

1. **Snapshot timeout on large workspace** — RESOLVED: `snapshot` has configurable timeout (default 5s) with partial-results fallback.
2. **Planner LLM timeout** — RESOLVED: `Planner.plan()` has 60s timeout with tiered fallback (escalate if no progress, replan with retries if progress made).
3. **Subprocess OOM/killed** — RESOLVED: `run_command` detects SIGKILL/SIGTERM, emits `execution_killed` event, treated as Tier 1 transient error.
4. **Evaluator ambiguous decision** — RESOLVED: OPA loop has hard `MAX_OPA_CYCLES` (default 100) and `MAX_LLM_TOKENS` (default 50000) budget. Escalates when exceeded.
5. **Incremental snapshot stale cache** — RESOLVED: Auto full-snapshot every N calls or M minutes, plus explicit `force_full` flag.

### Scope Decisions

- **Full plan accepted** (Phases 1-4). Complexity check triggered (~10-12 files, 4+ new abstractions). User chose to proceed as-is.
- **CI/CD added to scope** for Phase 4 remote agent artifact.
- **TODOS.md created** with 10 deferred/tracked items.

### Architecture Changes from Review

| Topic | Plan Before | Plan After Review |
|-------|------------|-------------------|
| Transport | HTTP/SSE primary | WebSocket primary, HTTP/SSE legacy |
| Security audit | Agent-side only (implied) | Both engine + agent side |
| Planning model | Pipelined (implied in tests) | Sequential with explicit cycle limits |
| Event schema | TaskEvent only | TaskEvent + WorkflowEvent table |
| Protocol | Full MCP | Hybrid: MCP schemas, custom WebSocket transport |
| Workspace boundary | Agent wraps workspace | Agent subsumes workspace in local mode |
| Engine structure | Monolithic Engine | Engine + OPALoop + WorkflowExecutor |
| Node model | Two DAGNode types | Single unified DAGNode with optional fields |
| Toolkit execution | ToolDefinition gains execute | BaseToolkit.execute(driver) with driver interface |
| Context limits | Not addressed | ContextWindowManager with truncation rules |
| Snapshot performance | Full walk every cycle | Incremental with mtime cache |
| Evaluator cost | No mitigation | Configurable decision cache |
