# Celeste-DAG: General-Purpose Dynamic Agentic Workflow Engine

Welcome to the development directory of **Celeste-DAG**, a production-grade, highly scalable, and secure orchestration engine for compiling and executing domain-agnostic, **model-agnostic** AI-driven pipelines.

## Project Structure & Architecture Patterns

Celeste-DAG splits concerns between dynamic planning (Right Brain) and durable scheduler execution (Left Brain). Below is how our decoupled directories map to modern multi-agent coordination patterns:

* **`config/`**: System configuration, loading settings for local macOS / production AWS EC2.
  * `settings.py`: Configures global variables, standardizing `WORKSPACE_ENGINE: Literal["local_tmp", "git_worktree", "docker", "firecracker"] = "local_tmp"` and adding configurable multi-provider LLM credentials.
* **`src/core/`**: The state machine.
  * `engine.py` (Left Brain / Durable Scheduler): High-concurrency async scheduler. Limits task spikes and executes **Durable State Replays** on startup/restart by replaying transaction events to reconstruct execution graphs safely. Acts as the supervising parent node.
  * `planner.py` (Right Brain / Planner): Decoupled from any single provider; integrates with `src/core/llm/` to use structured JSON schemas to compile domain-agnostic DAGs. Generates **Saga / Compensation plans** (rollback actions) alongside mutating commands to handle nested dynamic failures gracefully.
  * `llm/` (Model-Agnostic LLM Adapter Layer): Standardizes model interactions across providers:
    * `base.py`: Abstract Base Class `BaseLLMClient` specifying completion schemas, raw context wrappers, and Pydantic structured output models.
    * `anthropic.py`: Adapter wrapping the official Anthropic Python SDK (Sonnet, Haiku, Opus).
    * `openai.py`: Adapter wrapping the official OpenAI SDK (GPT-4o, GPT-4o-mini).
    * `gemini.py`: Adapter wrapping Google's Generative AI SDK (Gemini Pro, Flash).
    * `ollama.py`: Gateway adapter for custom, local open-source endpoints (Ollama/vLLM) enabling completely private local operations.
  * `workspaces/` (Physical Sandbox & Workspace Actor Boundary): Declares the `BaseWorkspace` abstract interface. Implements:
    * `local_tmp.py`: Default lightweight local OS temporary directory isolation for general-purpose tasks.
    * `git_worktree.py`: Specialized git branch worktree isolation (specifically for the Coding vertical plugin).
    * `docker.py`: Runs actions inside Docker containers, optionally configured with a gVisor proxy kernel for system call isolation.
    * `firecracker.py`: Boots KVM-isolated minimal guest Linux microVMs for strong multi-tenant production isolation on EC2.
* **`src/database/`**: Persistent state ledger.
  * `db.py`: Dynamic database context manager (SQLite ↔ Postgres switching).
  * `models.py`: Database tables (`TaskNode`, `TaskEvent`, `Workflow`) designed as a durable, **Event-Sourced Transaction Log** that tracks precise state transitions to shield the system from process crashes.
* **`src/toolkits/`**: Decoupled, pluggable domain tool registries (MCP-compatible).
  * `base.py`: Abstract interface declaring registration routines for tool classes.
  * `system_data.py`: Pluggable toolkit for core data manipulation, OCR processing, CSV filtering, and PDF generation.
  * `web_scraping.py`: Web scraping/API automation toolkit (handling Playwright browser instances and HTTP requests).
  * `coding_vertical.py`: Specialized software-engineering vertical plugin (Git operations, compiler checks, pytest runner tools).
* **`src/tools/`**: Defensive boundaries.
  * `security_auditor.py`: Heuristic LLM Security Audit classifier.
  * `tool_registry.py`: Strict deterministic allowlist. Translates registered tools into standard **Model Context Protocol (MCP)** tool schemas.

---

## Architectural Implementation Guidelines (Enforcing Elixir/OTP Disciplines in Python)

To maintain the architectural safety of Erlang BEAM / Elixir systems within Python’s async cooperative runtime, all developers must adhere strictly to these architectural disciplines:

### 1. Share-Nothing State Isolation (Actor Boundary)
* **The Discipline**: Python objects are naturally mutable and shared across memory by default. This is banned in Celeste-DAG's core. 
* **Implementation Guidelines**:
  - Code executing inside any subclass of `BaseWorkspace` (`src/core/workspaces/`) must operate inside a strict **physical boundary** (the local tmp directory, worktree directory, container workspace, or guest VM).
  - Workspace adapters **must never** import or access database models (`TaskNode`, `Workflow`), shared dictionary caches, or SQLAlchemy sessions directly.
  - State inputs must be supplied strictly during adapter initialization as immutable schemas or plain variables, mimicking Elixir's process initialization.

### 2. Event-Driven Message-Passing Boundary
* **The Discipline**: Actors communicate solely via messages. Sandboxes report log outputs, exit codes, and resource metrics asynchronously.
* **Implementation Guidelines**:
  - Use `asyncio.Queue` or async callback protocols inside the Left Brain runner.
  - The workspace execution loop must yield output events as discrete messages (e.g., `stdout_line`, `error_occurred`, `execution_completed` events).
  - The engine receives these events and checkpoints them directly into the `TaskEvent` ledger. **No bypass writes**—the worker workspace itself never commits directly to the database.

### 3. Supervision Lifecycles & Concurrency Throttling
* **The Discipline**: Parents supervise child lifecycles, guaranteeing orderly shutdown and crash propagation.
* **Implementation Guidelines**:
  - The core async loop in `engine.py` acts as a master supervisor. It manages worker actor lifecycles using `asyncio.shield` and explicit Task cancellation wrappers.
  - Concurrency is strictly bounded by a local `asyncio.Semaphore(MAX_PARALLEL_SUBPROCESSES)` or Celery concurrency pools.
  - If the engine cancels a task, the supervisor is responsible for gracefully tearing down the child actor's physical workspace (unregistering the Git worktree, killing the container, or destroying the microVM).

### 4. Let-It-Crash & Saga Compensations
* **The Discipline**: Individual worker failures should not be handled by nesting complex, defensive try-catch statements that hide corrupt program states. Let the individual task process fail. The parent supervisor handles the failure cleanly.
* **Implementation Guidelines**:
  - If a command inside the workspace returns a non-zero exit code or raises an unhandled exception, **allow the actor process to terminate immediately**.
  - The supervisor (`engine.py`) intercepts the actor's exit, updates the node's database status to `"failed"`, writes a `TaskEvent` log, and cancels any pending concurrent branches.
  - The orchestrator then triggers the **Saga rollback engine**, reading previously successful database steps and executing their registered idempotent compensation commands in reverse order.

### 5. Multi-Provider LLM Client Standardization
* **The Discipline**: Planners must remain entirely decoupled from any specific API SDK syntax.
* **Implementation Guidelines**:
  - All LLM interactions (planning, routing, security auditing) must route through the `BaseLLMClient` adapter interface declared in `src/core/llm/base.py`.
  - Tool calling and schema output generation must be standardized using OpenAI-compatible JSON schemas (`function` / `parameters`). 
  - Each concrete adapter is responsible for translating this standard schema into its provider's native SDK layout (e.g. Anthropic's block schema, Gemini's tool structure, or Ollama's native JSON layout) and validating returning data back into Pydantic models.

### 6. MCP Compatibility
* **The Discipline**: Modular tool structures enable standard-compliant execution.
* **Implementation Guidelines**:
  - Register CLI tools and allowlist rules inside `src/toolkits/` classes using standard JSON schema tool definitions conforming to the **Model Context Protocol (MCP)** specification.

---

## Implementation Instructions

Refer to the detailed step-by-step architectural roadmap documented in `README.md` for task boundaries, test designs, and sandboxing details.

To start setting up dependencies:
```bash
# Create local virtual environment and activate
uv venv && source .venv/bin/activate
```
