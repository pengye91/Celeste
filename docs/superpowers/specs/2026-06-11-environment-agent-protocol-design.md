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

The Environment Agent is an MCP server. It speaks JSON-RPC over MCP's pluggable transport layer (stdio for local, HTTP/SSE for remote). It inherits MCP's capability discovery, schema validation, and bidirectional communication for free.

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

| Mode | Transport | Use Case |
|------|-----------|----------|
| **In-process** | Direct Python function calls (no network, no serialization) | Local development, embedded SDK |
| **HTTP/SSE** | Agent runs as HTTP server, engine connects via HTTP POST + SSE streaming | Remote orchestration, multi-machine |
| **stdio** | Agent spawned as child process, communicates over stdin/stdout | CLI tools, local integrations, testing |

The engine selects the transport mode based on configuration. The protocol (JSON-RPC method names, parameter schemas, response shapes) is identical across all transports.

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
        """Start the agent. In-process: no-op. Remote: start HTTP server."""

    async def stop(self) -> None:
        """Stop the agent gracefully."""

    async def call_tool(self, name: str, arguments: dict) -> dict:
        """Invoke a tool on the agent. Works across all transports."""

    async def list_tools(self) -> list[dict]:
        """Discover available tools (MCP tools/list)."""

    def register_toolkit(self, toolkit: BaseToolkit) -> None:
        """Register additional tools from a toolkit."""
```

### Security

The Environment Agent enforces the existing two-phase security model:

1. All tool calls pass through the `SecurityAuditor` before execution
2. All tool calls pass through the `ToolRegistry` allowlist validation
3. The agent only exposes tools that have been explicitly registered — no ad-hoc command execution outside the tool framework

For remote agents, additional transport-level security applies:
- TLS for HTTP/SSE connections
- API key or mTLS authentication
- Session tokens with expiration

---

## Layer 2: OPA Loop (Observe → Plan → Act)

### Concept

The OPA loop replaces the current "planner generates full DAG upfront, engine executes it all" model with a continuous cycle. The planner is called **inside** the execution loop, not before it.

The planner decides batch size dynamically — it may produce 1 sequential task or 20 parallel fan-out tasks per cycle, depending on the situation.

### The Loop

```
while goal_not_achieved and not escalated:

    # 1. OBSERVE
    observation = await agent.call_tool("snapshot", ...)
    tool_schemas = await agent.list_tools()

    # 2. PLAN
    plan_fragment = await planner.plan(
        goal=workflow.goal,
        observation=observation,
        tool_schemas=tool_schemas,
        history=execution_history,       # past task results
        completed_node_ids=[...],        # what's done
        failed_node_ids=[...],           # what failed
    )
    # plan_fragment is a DAGFragment: a small batch of tasks with dependencies

    # 3. ACT
    await engine.execute_fragment(plan_fragment)
    # This runs tasks through the security gates, workspace, and agent
    # Results are recorded in the event ledger

    # 4. EVALUATE
    decision = evaluate(plan_fragment, workflow.goal)
    if decision == "DONE":
        break
    elif decision == "REPLAN":
        continue  # back to OBSERVE
    elif decision == "ESCALATE":
        await notify_human(...)
        break
    elif decision == "CONTINUE":
        continue  # back to OBSERVE
```

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
    url="http://worker-3.internal:8080",
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
await agent.start()  # Starts HTTP server
```

```
┌─────────────────────┐          ┌─────────────────────────┐
│  Celeste-DAG Server │          │  Target Environment     │
│                     │          │                         │
│  Engine             │  HTTP/   │  Environment Agent      │
│  OPA Loop           │◄─SSE────►│    ├── observe() calls  │
│  PostgreSQL ledger  │          │    └── execute() calls  │
│  FastAPI API        │          │                         │
│                     │          │  Workspace: Docker or   │
│                     │          │  Firecracker (optional) │
└─────────────────────┘          └─────────────────────────┘
```

The agent runs as a lightweight HTTP server on the target machine. The engine connects to it via HTTP POST (for requests) + SSE (for streaming results). The agent has full local filesystem and process access.

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
| `toolkits/` | Toolkits become the source of tools for Environment Agents (not just schema definitions for planner) | `BaseToolkit`, `SystemDataToolkit`, `WebScrapingToolkit`, `CodingVerticalToolkit` |
| `tools/security_auditor.py` | Applied by the Environment Agent before executing any tool call | Two-phase audit (deterministic + LLM fallback) |
| `tools/tool_registry.py` | Applied by the Environment Agent to validate tool calls | Strict allowlist, MCP schema generation |
| `core/llm/` | No changes | Multi-provider adapters |
| `api/app.py` | New endpoints: `POST /agents/register`, `GET /agents/{id}/status` for remote agent management | Existing workflow CRUD and execution endpoints |
| **New: `core/agent/`** | New module containing `EnvironmentAgent`, transport implementations, and tool dispatch | — |

### The Big Wiring Change

Today, toolkits are **schema-only** — they tell the planner what tools exist but have no execution logic. The engine runs raw shell commands via `workspace.execute()`.

In the new design, toolkits become **executable** — each `ToolDefinition` gains an `execute` method. The Environment Agent dispatches tool calls to the appropriate toolkit. The planner still receives MCP schemas from the agent (via `discover_tools`), but now those schemas are backed by real implementations.

```
Before:  Planner → reads toolkit schemas → generates plan with shell commands
         Engine  → runs shell commands via workspace.execute()

After:   Planner → queries agent.list_tools() → generates plan with tool calls
         Engine  → dispatches tool calls via agent.call_tool() → agent routes to toolkit
```

---

## Migration Strategy

This is an additive evolution, not a rewrite. The existing 529 tests continue to pass.

### Phase 1: Environment Agent (Foundation)
- Create `src/celeste_dag/core/agent/` module
- Implement `EnvironmentAgent` with in-process transport
- Add `execute` methods to `ToolDefinition` and toolkits
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
- Implement HTTP/SSE transport for `EnvironmentAgent`
- Implement `EnvironmentAgent.serve()` for running agents as standalone servers
- Add agent registration endpoints to the API
- Implement pull-mode workers for firewall/NAT traversal

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
