# Containment Model: Agent vs Workspace

**Status:** Decided — 2026-06-15.
**Resolves:** TODO-5 (workspace/agent containment model for Docker/Firecracker).

---

## The problem

Celeste-DAG has two parallel execution paths that do not share a
containment boundary:

1. **The OPA loop** (`Engine.run` → `OPALoop.run` → `agent.call_tool`) — the
   primary path. Commands run through the agent's `ShellDriver`, which
   spawns subprocesses **directly on the engine host**. The workspace layer
   is never consulted.

2. **The legacy DAG engine** (`Engine.run_workflow` → `_execute_node` →
   `workspace.execute`) — the original path. Commands run inside a
   `BaseWorkspace` (LocalTmp / GitWorktree / Docker / Firecracker), which
   provides the sandbox.

The design spec
([`docs/superpowers/specs/2026-06-11-environment-agent-protocol-design.md`](superpowers/specs/2026-06-11-environment-agent-protocol-design.md)
§5, line 454) asserts: *"the agent runs inside the workspace's directory and
process boundary."* But the implementation has the OPA-loop agent and the
workspace as **two disconnected execution mechanisms that never meet** — the
agent has no `BaseWorkspace` field, and the OPA loop never calls
`workspace.execute()`.

This means `WORKSPACE_ENGINE=docker` (or `firecracker`) has **no effect** on
the OPA-loop path: even with Docker configured, the agent's `run_command`
runs on the host.

---

## Decision: workspace-backed driver

Add a `WorkspaceDriver` that implements the `BaseDriver` interface but
delegates `run_command` to a `workspace.execute()` call. The agent stays in
the engine process, but its tool calls are **proxied through a workspace**,
so the workspace's sandbox (temp dir / Docker container / Firecracker VM) is
the containment boundary for **both** execution paths.

```
Engine process
├── OPA Loop
│   └── Agent (in-process)
│       └── WorkspaceDriver          ← NEW (this doc)
│           └── workspace.execute()  ← existing sandbox
│                 ├── LocalTmpWorkspace   (default)
│                 ├── GitWorktreeWorkspace
│                 ├── DockerWorkspace     (docker exec)
│                 └── FirecrackerWorkspace(KVM)
│
└── Legacy DAG engine
    └── workspace.execute()          (unchanged)
```

**Why this approach:**

- It matches the spec's intent ("agent runs inside the workspace") via a
  concrete mechanism — the driver is the bridge.
- It does **not** require baking the agent into workspace images (unlike the
  "agent-inside-container" alternative). Existing Docker images work as-is.
- It unifies both execution paths under one containment boundary. Setting
  `WORKSPACE_ENGINE=docker` now affects the OPA loop too.
- It is **opt-in**. The new `EnvironmentAgent.in_workspace()` factory is
  additive; `in_process()`, `remote()`, and `serve()` keep their current
  drivers and behavior. No existing call site breaks.

---

## Deployment modes under the new model

### Mode 1: In-process + LocalTmp (default)

```
┌─────────────────────────────────────────┐
│  Engine process (single host)           │
│                                         │
│  Engine + OPA Loop                      │
│    └── Agent.in_workspace()             │
│          └── WorkspaceDriver            │
│                └── LocalTmpWorkspace    │
│                      (tempdir)          │
│  SQLite / PostgreSQL ledger             │
└─────────────────────────────────────────┘
```

The agent's `run_command` creates a subprocess inside the LocalTmp temp
directory. **No process/network isolation** — same as the current
`in_process()` behavior, but now the command runs in a managed workspace
directory rather than the engine's CWD. File operations (`read_file`,
`stat`, `snapshot`) work directly via `pathlib` against the workspace path.

### Mode 2: In-process + Docker

```
┌─────────────────────────────────────────┐
│  Engine process (orchestrator host)     │
│                                         │
│  Engine + OPA Loop                      │
│    └── Agent.in_workspace()             │
│          └── WorkspaceDriver            │
│                └── DockerWorkspace      │
│                      (docker exec)      │
│                                         │
│  SQLite / PostgreSQL ledger             │
└──────────────────┬──────────────────────┘
                   │ docker exec
                   ▼
┌─────────────────────────────────────────┐
│  Docker container (python:3.11)         │
│  └── subprocess.run(argv, shell=False)  │
└─────────────────────────────────────────┘
```

The agent stays on the orchestrator host, but every `run_command` is
proxied into the container via `docker exec`. **Real container isolation:**
the command runs inside the container's filesystem, network namespace, and
process space. File operations (`read_file`, `stat`) are **not supported**
in this mode (the container filesystem is not mounted on the host) and
raise `NotImplementedError` — use `run_command("cat", ...)` instead.

### Mode 3: Remote (WebSocket) — unchanged

```
┌─────────────────────┐          ┌─────────────────────────┐
│  Orchestrator host  │          │  Target host            │
│                     │   WS     │                         │
│  Engine + OPA Loop  │◄────────►│  Agent server           │
│  Agent.remote()     │  JSON-RPC│    └── ShellDriver      │
│  (thin proxy)       │          │    └── FilesystemDriver │
│                     │          │    └── own filesystem   │
└─────────────────────┘          └─────────────────────────┘
```

The agent runs as a WebSocket server on a separate host. Every tool call is
forwarded over the network. The **containment boundary is the remote host
itself** — the agent server owns its drivers and runs commands locally. This
mode does **not** use `WorkspaceDriver`; the remote host IS the sandbox. No
changes to this mode.

---

## The BaseDriver ↔ BaseWorkspace contract bridge

The two interfaces are structurally incompatible; `WorkspaceDriver` bridges
them:

| Concern | `BaseDriver.run_command` | `BaseWorkspace.execute` |
|---------|--------------------------|-------------------------|
| Args | `command: str`, `args: list[str]`, `cwd`, `timeout` | `command: str`, `arguments: dict`, `env` |
| Return | `CommandResult` (single awaitable) | `AsyncIterator[WorkspaceEvent]` (stream) |
| Exit code | `CommandResult.exit_code` | `event.data["exit_code"]` on terminal event |
| stdout/stderr | `CommandResult.stdout` / `.stderr` | accumulated from `stdout_line` / `stderr_line` events |

**Translation (in `WorkspaceDriver.run_command`):**

1. Build `arguments = {"argv": [command] + list(args)}`. The `"argv"` key is
   the convention both `DockerWorkspace` and `LocalTmpWorkspace` expect.
2. Call `workspace.execute(command, arguments=arguments)`.
3. Iterate the full `WorkspaceEvent` stream:
   - Accumulate `event.data` from `stdout_line` events → `stdout` buffer.
   - Accumulate `event.data` from `stderr_line` events → `stderr` buffer.
   - On `execution_completed`: exit_code = 0.
   - On `execution_failed`: exit_code = `event.data.get("exit_code", 1)`.
4. Apply `timeout` via `asyncio.wait_for` around the stream consumption.
5. Return `CommandResult(exit_code, stdout, stderr)`.

**File operations** (`read_file`, `write_file`, `list_directory`, `stat`):
implemented via `pathlib` against `workspace.get_workspace_path()`. This works
for LocalTmp and GitWorktree (shared filesystem). For Docker/Firecracker,
these raise `NotImplementedError` — the container filesystem is not
accessible from the host process. Use `run_command("cat", ...)` /
`run_command("ls", ...)` instead.

---

## What changed in the codebase

| Component | Change |
|-----------|--------|
| **NEW `core/agent/workspace_driver.py`** | `WorkspaceDriver(BaseDriver)` — bridges the two contracts. |
| `core/agent/agent.py` | New `in_workspace()` factory method. |
| `core/agent/driver.py` | No changes. |
| `core/workspaces/*` | No changes. |
| `core/engine.py` | `Engine.run()` builds an `in_workspace()` agent when no agent is provided. |
| `core/opa_loop.py` | No changes. It already calls `agent.call_tool()` — it doesn't know or care which driver backs the agent. |

---

## Out of scope (follow-up work)

- **Container-aware file ops:** `read_file`/`stat` inside a Docker container
  could be implemented via `docker exec cat/ls/stat`. Currently they raise
  `NotImplementedError`. The snapshot mtime cache degrades gracefully (the
  agent catches the error and returns an empty snapshot).
- **FirecrackerWorkspace:** still a stub (`execute()` raises
  `NotImplementedError`). `WorkspaceDriver` will propagate the error
  cleanly.
- **Agent attestation (TODO-4):** orthogonal — signing audit results so the
  engine can verify the agent ran its security check. This doc is about
  *where* commands run, not *whether* they're audited.
