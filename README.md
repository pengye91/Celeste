# Celeste-DAG: General-Purpose Dynamic Agentic Workflow Engine
## Implementation & Architecture Plan

> **Note**: This is a production-level, highly scalable, and secure system design for a domain-agnostic, **model-agnostic** agentic workflow engine. It is engineered to compile and run seamlessly on both local macOS systems and distributed single-node/multi-node AWS EC2 setups, enforcing strict sandboxing, multi-provider LLM integration, and fault-tolerant event coordination.

---

## 1. Goal & Objectives
To build a highly modular, secure, and resilient **General-Purpose Dynamic Agentic Workflow Engine** (named **Celeste-DAG**) that compiles and executes complex multi-step, dynamic pipelines for any automation domain (e.g., automated market research, web scraping, data transformation, API orchestrations, or code modification).

* **Scale**: Handle up to 100 parallel workflow runs locally or on a single AWS EC2 (e.g., t3.large / m5.large), throttle process-heavy commands to keep the host system healthy.
* **Security**: Sandbox untrusted dynamic LLM execution using an extensible, abstract Workspace model providing absolute file-system and process boundaries.
* **Model Agnosticism**: Standardize on an extensible, **multi-provider LLM client layer** supporting Anthropic Claude, OpenAI GPT, Google Gemini, and local open-source models (via Ollama or vLLM), allowing the engine to adapt dynamically to cost, performance, and data privacy needs.
* **Portability**: Work seamlessly on a developer's local MacBook and compile/run without adjustments inside a production EC2 Linux environment.

---

## 1.1 Unified Language Choice & Architectural Borrowing (Python + Elixir OTP Disciplines)

An architectural trade-off was made to implement Celeste-DAG as a **unified Python framework** rather than using Elixir/Erlang directly, despite the system modeling an Actor architecture.

### The Language Trade-Off Matrix (General-Purpose Perspective)

| Dimension | Python (Unified Framework) | Elixir (Erlang BEAM) |
| :--- | :--- | :--- |
| **First-Class AI/LLM SDKs** | **Gold Standard**: Official, instant API feature updates from all major providers (Anthropic, OpenAI, Google) with native Pydantic support. | Community-driven wrappers only; features often lag behind official releases. |
| **General-Purpose Ecosystem** | **Gold Standard**: Playwright/Selenium for scraping; Pandas/Polars for data; mature S3, PDF, OCR, and DB connectors. | Excellent text-processing, but fewer pre-built, domain-agnostic integration SDKs. |
| **Physical Sandbox Orchestration** | Straightforward execution, file-tracking, and workspace mounts via Python `asyncio`. | Complex; OS subprocesses require Erlang "Ports" which are notoriously difficult to sandbox and secure. |
| **Native Concurrency / Fault Tolerance** | Cooperative multitasking (`asyncio`), requires explicit structural disciplines. | **Gold Standard**: Native, preemptive lightweight processes, built-in mailboxes, and OTP supervision. |

### Enforcing "Elixir Rigor" in Python
To gain the ecosystem superpowers of Python without sacrificing the safety of the Actor Model, Celeste-DAG strictly enforces four core **Elixir/OTP-inspired design disciplines** within Python’s async runtime:

1. **Share-Nothing Isolation (Actor Boundary)**: Sandboxed worker environments are isolated stateful actors. They are physically sandboxed (via Ephemeral Directories, Docker, or microVMs) and have no access to the central engine's shared memory or global database sessions.
2. **Asynchronous Message-Passing**: Worker processes can never write to or alter the central scheduler’s records directly. They must emit structured JSON event messages (e.g., stdout streams, exit codes, state changes) to the central engine's async queues, keeping state transitions strictly message-driven.
3. **Supervision Trees**: Schedulers act as parent supervisors. They monitor the lifecycle of active child nodes (tasks), throttle concurrency via semaphores, and manage the parent execution path based on child events.
4. **"Let It Crash" with Saga Compensations**: Instead of using defensive, nested try-catch blocks that clutter code and mask deep logic failures, Celeste-DAG embraces the Elixir philosophy: *let the individual task crash*. The supervisor catches the crash, transitions the ledger status, and executes compiled **Saga Rollbacks** (compensations) in reverse order to return the system to a clean state.

---

## 2. Tech Stack & Dependencies
* **Core Language**: Python 3.11+ / FastAPI (fully asynchronous coroutine-driven HTTP server).
* **Worker Queue & State Management**: 
  - Local: SQLite + Python's in-memory asyncio queues / semaphores (lightweight, zero-infra setup).
  - Production EC2: PostgreSQL + Celery/Redis (highly durable, distributed worker queues).
* **Workspace Isolation**: Ephemeral tmp directories, Docker/gVisor container runtimes, or Linux-KVM Firecracker microVMs.
* **LLM Providers (Multi-Engine client)**: Standardized abstract API supporting Anthropic SDK, OpenAI SDK, Google Generative AI SDK, and Ollama/vLLM HTTP gateways.

---

## 3. Directory Layout (Decoupled, Extensible Architecture)
```text
~/src/agentic-dynamic-workflows/
├── .env.example                # Example credentials, model providers, and engine settings
├── pyproject.toml              # Decoupled dependencies (FastAPI, httpx, pydantic, sqlalchemy)
├── README.md                   # Setup and operations documentation
├── config/
│   ├── __init__.py
│   └── settings.py             # Dual-environment configuration (Local / AWS EC2 production)
├── src/
│   ├── __init__.py
│   ├── api/                    # API endpoints for pipeline lifecycle & session triggering
│   ├── core/
│   │   ├── engine.py           # Programmatic Left Brain: asyncio DAG scheduler & durable state replayer (Supervisor)
│   │   ├── planner.py          # Cognitive Right Brain: Abstract LLM DAG compiler & Saga generator
│   │   ├── llm/                # Extensible Multi-Provider LLM Client Layer
│   │   │   ├── __init__.py
│   │   │   ├── base.py         # BaseLLMClient interface declaring standardized completion & structured output APIs
│   │   │   ├── anthropic.py    # Anthropic Claude client adapter (Sonnet, Haiku, Opus)
│   │   │   ├── openai.py       # OpenAI GPT client adapter (GPT-4o, GPT-4o-mini)
│   │   │   ├── gemini.py       # Google Gemini client adapter (Gemini 1.5 Pro, Flash)
│   │   │   └── ollama.py       # Local open-source model client adapter (Ollama/vLLM HTTP gateway)
│   │   └── workspaces/         # Abstract & Pluggable physical sandboxes (Actor Boundaries)
│   │       ├── __init__.py
│   │       ├── base.py         # BaseWorkspace interface declaring setup, execute, and teardown
│   │       ├── local_tmp.py    # Local Ephemeral Directory workspace (Default lightweight engine)
│   │       ├── git_worktree.py # Specialized Git Worktree workspace (Coding vertical plugin)
│   │       ├── docker.py       # Docker container / gVisor workspace (High-isolation engine)
│   │       └── firecracker.py  # Firecracker microVM workspace (Bare-metal production multi-tenancy)
│   ├── database/
│   │   ├── db.py               # SQLAlchemy async engine configuration (SQLite/Postgres switcher)
│   │   └── models.py           # TaskNode, TaskEvent, and Workflow DAG ledger schemas (Event Sourced log)
│   └── toolkits/               # Decoupled, pluggable domain tool registries (MCP-compatible)
│       ├── __init__.py
101│       ├── base.py             # Interface for pluggable toolkits
102│       ├── system_data.py      # Core data/file manipulation tools (System, OCR, JSON, PDF)
103│       ├── web_scraping.py     # Web scraping/API automation toolkit (Playwright/HTTP)
104│       └── coding_vertical.py  # Software Engineering plugin (Git, compiler, test runner toolkit)
105└── tests/                      # Suite of unit and E2E isolation tests
```

---

## 4. Multi-Layer Security Architecture (Defense-in-Depth)

```
[ LLM Proposed Action/Command Tool Call ]
                   │
                   ▼
       ┌───────────────────────┐
       │ 1. HEURISTIC AUDITOR  │  -> Cognitive safety classifier (LLM Security Inspector)
       └───────────┬───────────┘
                   │ (Pass)
                   ▼
       ┌───────────────────────┐
       │ 2. DETERMINISTIC CHECK│  -> Hard allowlist validation of binaries & arguments
       └───────────┬───────────┘
                   │ (Pass)
                   ▼
       ┌───────────────────────┐
       │ 3. ISOLATED WORKSPACE │  -> Non-blocking execution inside pluggable Workspace
       └───────────────────────┘     (LocalTmp, GitWorktree, Docker, or Firecracker microVM)
```

---

## 4.1 Extensible Physical Workspace Runtimes

Instead of hardcoding the execution sandbox around code-modification and Git setups, Celeste-DAG separates the execution environment into pluggable **Workspaces**. Schedulers do not need to know how the files are physically managed or isolated; they simply interact with an abstract execution interface.

### Sandbox / Workspace Trade-Off Matrix

| Workspace Engine | Isolation Level | Host OS Requirements | Lifecycle Overhead | Target Environment |
| :--- | :--- | :--- | :--- | :--- |
| **Local Tmp (`local_tmp.py`)** | Process level (Local temporary OS directory) | macOS or Linux | **Near zero** (<10ms setup) | Local macOS development & general purpose lightweight tasks |
| **Git Worktree (`git_worktree.py`)** | Version control level (Ephemeral branch + dedicated folder) | macOS or Linux (Git required) | **Low** (<50ms setup) | Developers working on the specialized Software Engineering coding vertical |
| **Docker / gVisor (`docker.py`)** | Container level (Shared host kernel, optional gVisor proxy kernel isolation) | macOS or Linux (Docker daemon) | **Low** (~200ms container init) | Local integration tests & single-tenant EC2 pipelines |
| **Firecracker MicroVM (`firecracker.py`)** | Virtualization level (Separate Linux guest kernel via KVM) | Linux (KVM-enabled instance, e.g. bare metal or AWS `.metal` instances) | **Medium** (~100–300ms boot) | Production multi-tenant AWS EC2 environments with untrusted code |

---

## 5. Advanced Orchestration Framework (Paradigm Convergence)

Celeste-DAG implements a modern **Paradigm Convergence** pattern that guarantees robustness, reliability, and security by unifying three advanced multi-agent orchestration paradigms:

1. **Cognitive Dynamic DAGs (Right Brain)**: Schedulers cannot rely on static templates when working in dynamic environments. Celeste-DAG uses the standardized **LLM Client Layer** to dynamically compile execution plans at runtime based on the task's domain context. Under dynamic fan-out or map-reductions (e.g. processing $N$ scraped web links or $N$ PDF documents), task execution chains expand on the fly. To mitigate downstream worker failures, the Planner compiles **Saga / Compensation patterns**—dynamic rollback tasks scheduled to run in reverse if any concurrent task branch fails.
2. **Durable Execution (Left Brain)**: High-availability agent runs must be resilient to host process restarts, server crashes, and network timeouts. Celeste-DAG treats the database DAG ledger as an **Event Sourced Log**. Execution states, output variables, and transaction records (`TaskEvent`) are checkpointed at every step. If the server crashes, the engine uses **State Replay** to reconstruct the exact execution state on restart, resuming exactly where it was interrupted without re-executing expensive physical tools.
3. **The Actor Model (Physical Workspace Boundary)**: Each active workspace is treated as an isolated, stateful **Actor** encapsulating its own private directory, data environment, and executing tools. These actors communicate asynchronously with the core Left-Brain scheduler via standard, schemas-enforced event-driven interfaces. This prevents concurrency conflicts (no shared state) and simplifies error supervision.

---

## 6. Implementation Tasks (Bite-Sized Roadmap)

### Phase 1: Environment & Project Config Setup
- [ ] **Task 1.1**: Define project metadata and dependencies in `pyproject.toml` (using modern PEP 621 packaging style with `hatchling` or `poetry`).
- [ ] **Task 1.2**: Write unified environment configuration system in `config/settings.py` using `Pydantic-Settings`. Standardize key settings:
  ```python
  class EngineSettings(BaseSettings):
      ENVIRONMENT: Literal["local", "production"] = "local"
      DATABASE_URL: str = "sqlite+aiosqlite:///celeste.db"
      MAX_PARALLEL_SUBPROCESSES: int = 4  # Throttle limit
      STRICT_SECURITY_MODE: bool = True
      WORKSPACE_ENGINE: Literal["local_tmp", "git_worktree", "docker", "firecracker"] = "local_tmp"
      LLM_PROVIDER: Literal["anthropic", "openai", "gemini", "ollama"] = "anthropic"
      LLM_MODEL: str = "claude-3-5-sonnet-20241022"
      LLM_API_KEY: SecretStr | None = None
      LLM_BASE_URL: str | None = None  # Needed for local open-source engines (Ollama/vLLM)
  ```

### Phase 2: The Persistence Layer (Durable Event-Sourced Ledger)
- [ ] **Task 2.1**: Implement database schema using SQLAlchemy 2.0 in `src/database/models.py`. Track DAG edges via adjacency links (`previous_node_ids`, `next_node_ids`), execution `"status"` (`pending`, `running`, `completed`, `failed`), retry bounds, and granular string `"outputs"`.
- [ ] **Task 2.2**: Implement a `TaskEvent` table in `src/database/models.py` to act as an event-sourced ledger, tracking transactional changes (e.g., `event_type="node_started"`, `event_type="node_completed"`, `event_type="compensation_triggered"`) to support complete durable state replays.
- [ ] **Task 2.3**: Write database session context manager in `src/database/db.py` to auto-switch between SQLite (`aiosqlite` local) and PostgreSQL (`asyncpg` EC2 production) based on `settings.DATABASE_URL`.

### Phase 3: The Left Brain (Abstract Workspace & Actor Sandbox)
- [ ] **Task 3.1**: Implement the abstract workspace interface in `src/core/workspaces/base.py`. Define the standard API (`setup()`, `execute()`, `teardown()`) that all concrete physical sandboxes must inherit.
- [ ] **Task 3.2**: Implement concrete workspace engines in `src/core/workspaces/`:
  - `local_tmp.py`: Default lightweight local temporary directory workspace.
  - `git_worktree.py`: Specialized git branch worktree isolation (Coding vertical).
  - `docker.py`: Wraps task runs inside Docker containers (supports gVisor isolation).
  - `firecracker.py`: Ephemeral guest KVM Linux microVM workspace for multi-tenant production.
- [ ] **Task 3.3**: Model each running workspace as an **asynchronous Actor boundary**. The workspace must encapsulate state strictly, executing processes and streaming outputs/logs as asynchronous messaging events back to the main engine.
- [ ] **Task 3.4**: Write the **Pluggable Toolkit interface** in `src/toolkits/base.py` and implement core general-purpose registries (such as `system_data.py` for OCR/PDF parsing and `web_scraping.py` for Playwright/HTTP automation). Design the registry to conform to standard **Model Context Protocol (MCP)** tool schemas.
- [ ] **Task 3.5**: Implement the coding-specific vertical registry in `src/toolkits/coding_vertical.py` (exposing specialized Git and test runner tools).
- [ ] **Task 3.6**: Write and integrate the **Heuristic LLM Security Auditor** in `src/tools/security_auditor.py` to classify commands/actions using the abstract LLM Client layer before execution.
- [ ] **Task 3.7**: Implement the extensible multi-provider LLM client interfaces in `src/core/llm/`. Write the base interface `BaseLLMClient` and concrete provider adapters (`anthropic.py`, `openai.py`, `gemini.py`, and `ollama.py`) to standardize completion schema formatting.

### Phase 4: The Right Brain (The Cognitive DAG Planner & Saga Manager)
- [ ] **Task 4.1**: Implement the planner in `src/core/planner.py`. Write a model-agnostic LLM controller that formats the workspace context, registers available Toolkits, and takes the user request, invoking standard structured JSON completion schemas from our adapter layer to compile your DAG node protocol.
- [ ] **Task 4.2**: Implement dynamic map-phase "Fan-Out" generation in the planner. If an active task node emits an array of size $N$ (e.g., $N$ links to scrape, $N$ files to process), the Orchestrator reads the output array and dynamically spawns $N$ downstream parallel task nodes linked in the database.
- [ ] **Task 4.3**: Integrate **Saga / Compensation Pattern generation** in `src/core/planner.py`. When the planner generates a task node that mutates workspace or external state, it must also define a `compensation_command` or rollback sequence. If a downstream dynamic task node fails, the orchestrator compiles and runs the compensation DAG in reverse.

### Phase 5: The Durable Orchestrator State Engine
- [ ] **Task 5.1**: Implement the main execution engine in `src/core/engine.py`. This is a non-blocking asyncio loop using an `asyncio.Semaphore(MAX_PARALLEL_SUBPROCESSES)` to throttle active process execution. It loops, reads pending nodes with satisfied dependency statuses, and feeds them to the execution thread safely.
- [ ] **Task 5.2**: Build **Durable State Replay** mechanisms into `src/core/engine.py`. On orchestrator startup, if existing workflow runs are found in the database with incomplete statuses, the engine must read the `TaskEvent` ledger, rebuild the in-memory state representation, and resume execution from the last safe checkpoint without re-running completed nodes.
- [ ] **Task 5.3**: Build the Web API layer in `src/api/` using FastAPI to expose routes for triggering pipelines, retrieving real-time logs, tracking budgets, and rendering DAG live statuses.

---

## 7. Verification & Test Suite Strategy
1. **Unit Tests**: Mock the core `BaseLLMClient` to verify that the general-purpose DAG and compensation Sagas are compiled properly according to standard JSON schemas, independent of physical APIs. Test the dynamic Semaphore scheduler under heavy mock concurrency loads.
2. **Local Ephemeral Workspace Test**: Verify that executing basic tasks inside a `local_tmp` workspace config creates, writes files, and destroys folders cleanly.
3. **Multi-Provider LLM Client Integration Test**: Write client integration tests using mocked payloads (and live integration tests if keys are provided) to verify that Anthropic, OpenAI, Gemini, and local Ollama adapters cleanly parse and output validated Pydantic JSON schemas.
4. **Coding Vertical Integration Test**: Configure `WORKSPACE_ENGINE="git_worktree"`; verify that spawning actual code modifications creates, commits, and teardowns Git Worktrees cleanly without corrupting the workspace.
5. **Durable Replay Test**: Run a mock multi-stage DAG, abruptly terminate the process mid-run, restart the engine, and verify that the scheduler performs a State Replay, skipping completed nodes and executing remaining pending tasks exactly once.
6. **Docker Workspace Test**: Configure `WORKSPACE_ENGINE="docker"`; run a mock scraping task and verify that Playwright commands execute inside the container, writing outputs back to the host filesystem.
7. **Security Injection Test**: Feed a prompt-injection payload to the CLI executor; assert that the deterministic allowlist successfully blocks execution and returns a safe security exception.
