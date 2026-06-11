# Celeste-DAG

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-693%20passing-brightgreen.svg)]()
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**A general-purpose, model-agnostic dynamic agentic workflow engine with durable execution and multi-environment deployment.**

Celeste-DAG compiles natural-language goals into executable DAGs, runs them inside isolated workspaces, and dynamically replans based on environment observations. It supports local development, remote orchestration, and embedded SDK usage — all through a unified Python framework.

---

## Table of Contents

- [Features](#features)
- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Installation](#installation)
- [Usage](#usage)
  - [Local Mode](#local-mode)
  - [Remote Mode](#remote-mode)
  - [Embedded SDK](#embedded-sdk)
- [Configuration](#configuration)
- [Project Structure](#project-structure)
- [Testing](#testing)
- [License](#license)

---

## Features

| Feature | Description |
|---------|-------------|
| **Dynamic OPA Loop** | Observe → Plan → Act → Evaluate cycles with continuous replanning |
| **Model-Agnostic LLM Layer** | Swap providers (Anthropic, OpenAI, Gemini, Ollama) without changing code |
| **Pluggable Workspaces** | Local tmp, Git worktree, Docker, or Firecracker microVM isolation |
| **MCP-Compatible Agent Protocol** | Environment Agent speaks JSON-RPC over WebSocket or in-process calls |
| **Durable Execution** | Event-sourced ledger with crash recovery and state replay |
| **Saga Compensation** | Automatic rollback of completed tasks on downstream failure |
| **Tiered Escalation** | Retry → Replan → Full replan → Human escalation |
| **Security Pipeline** | Two-phase audit (deterministic + LLM) before any tool execution |
| **Continue-As-New** | Long workflows checkpoint and spawn fresh runs automatically |

---

## Quick Start

```python
import asyncio
from celeste import Engine, EnvironmentAgent
from celeste.toolkits.system_data import SystemDataToolkit

async def main():
    agent = EnvironmentAgent.in_process(
        workdir="/tmp/my-project",
        toolkits=[SystemDataToolkit()],
    )

    engine = Engine(agent=agent)
    result = await engine.run(goal="List all Python files and count their lines")

    print(result.status)  # "completed"
    print(result.cycle_count)

asyncio.run(main())
```

---

## Architecture

Celeste-DAG is organized into four layers:

```
┌─────────────────────────────────────────────┐
│ Layer 4: Deployment Modes                     │
│   Local | Remote | Embedded                   │
├─────────────────────────────────────────────┤
│ Layer 3: Durable Execution                    │
│   Event-sourced ledger with LLM result cache  │
│   Continue-As-New for long workflows          │
├─────────────────────────────────────────────┤
│ Layer 2: OPA Loop (Observe → Plan → Act)      │
│   Continuous replanning cycle                 │
│   Tiered escalation: retry → replan → human   │
├─────────────────────────────────────────────┤
│ Layer 1: Environment Agent                    │
│   MCP-compatible observe + execute protocol   │
│   In-process | HTTP/WebSocket transports      │
└─────────────────────────────────────────────┘
```

**Design disciplines** (borrowed from Elixir/OTP):
- **Share-nothing isolation** — Workspaces are physically sandboxed actors
- **Message-passing** — State changes flow through async event queues only
- **Supervision trees** — Semaphore-throttled concurrency with lifecycle monitoring
- **Let-it-crash** — Individual tasks fail fast; Saga compensations restore clean state

---

## Installation

```bash
# Clone the repository
git clone git@github.com:pengye91/Celeste.git
cd Celeste

# Install with dependencies
pip install -e ".[dev]"

# Or install production dependencies only
pip install -e .
```

**Requirements:** Python 3.11+

---

## Usage

### Local Mode

Run everything in a single process with direct Python calls — zero network overhead.

```python
from celeste import Engine, EnvironmentAgent
from celeste.toolkits.system_data import SystemDataToolkit
from celeste.toolkits.web_scraping import WebScrapingToolkit

agent = EnvironmentAgent.in_process(
    workdir="/workspace",
    toolkits=[SystemDataToolkit(), WebScrapingToolkit()],
)

engine = Engine(agent=agent)
result = await engine.run(goal="Your automation goal here")
```

### Remote Mode

Connect to an agent running on a remote machine via persistent WebSocket.

```python
# On the target machine (agent)
from celeste import EnvironmentAgent

agent = EnvironmentAgent.serve(
    host="0.0.0.0",
    port=8080,
    workdir="/workspace",
    toolkits=[SystemDataToolkit()],
    auth_token="secret",
)
await agent.start()
```

```python
# On the orchestrator (engine)
from celeste import Engine, EnvironmentAgent

agent = EnvironmentAgent.remote(
    url="ws://worker-3.internal:8080",
    auth_token="secret",
)

engine = Engine(agent=agent)
result = await engine.run(goal="Your automation goal here")
```

### Embedded SDK

Use Celeste-DAG as a library inside your own application.

```python
from fastapi import FastAPI
from celeste import Engine, EnvironmentAgent

app = FastAPI()
engine = Engine(agent=EnvironmentAgent.in_process(workdir="/app/workspace"))

@app.post("/automate")
async def automate(request: dict):
    result = await engine.run(goal=request["goal"])
    return {"status": result.status}
```

---

## Configuration

All settings are managed via `EngineSettings` and can be overridden through environment variables or a `.env` file:

```bash
# .env
DATABASE_URL=sqlite+aiosqlite:///celeste.db
MAX_PARALLEL_SUBPROCESSES=4
LLM_PROVIDER=anthropic
LLM_MODEL=claude-3-5-sonnet-20241022
LLM_API_KEY=sk-...
SNAPSHOT_TIMEOUT_MS=5000
MAX_OPA_CYCLES=100
MAX_LLM_TOKENS=50000
```

Per-workflow overrides are also supported:

```python
result = await engine.run(
    goal="Expensive analysis",
    max_cycles=50,
    max_llm_tokens=20000,
)
```

---

## Project Structure

```
Celeste/
├── src/celeste/
│   ├── core/
│   │   ├── agent/              # Environment Agent Protocol
│   │   │   ├── agent.py        # EnvironmentAgent (in-process / remote / serve)
│   │   │   ├── driver.py       # ShellDriver, FilesystemDriver
│   │   │   ├── transport.py    # BaseTransport, InProcessTransport
│   │   │   ├── transport_ws.py # WebSocketTransport, WebSocketServer
│   │   │   └── transport_stdio.py  # StdioTransport
│   │   ├── opa_loop.py         # OPA Loop orchestrator
│   │   ├── evaluator.py        # LLM-based workflow evaluator
│   │   ├── planner.py          # DAG compiler (DAGFragment, DAGPlan)
│   │   ├── engine.py           # Execution engine & state replay
│   │   ├── context_window.py   # Prompt truncation & summarization
│   │   ├── checkpoint.py       # Continue-As-New checkpointing
│   │   ├── exceptions.py       # Custom exceptions
│   │   ├── llm/                # Multi-provider LLM adapters
│   │   │   ├── base.py
│   │   │   ├── anthropic.py
│   │   │   ├── openai.py
│   │   │   ├── gemini.py
│   │   │   └── ollama.py
│   │   └── workspaces/         # Sandbox implementations
│   │       ├── base.py
│   │       ├── local_tmp.py
│   │       ├── git_worktree.py
│   │       ├── docker.py
│   │       └── firecracker.py
│   ├── database/
│   │   ├── db.py               # Async SQLAlchemy session management
│   │   └── models.py           # Workflow, TaskNode, TaskEvent, WorkflowEvent
│   ├── toolkits/               # MCP-compatible tool registries
│   │   ├── base.py
│   │   ├── system_data.py
│   │   ├── web_scraping.py
│   │   └── coding_vertical.py
│   ├── tools/
│   │   ├── security_auditor.py # Two-phase security audit
│   │   └── tool_registry.py    # Strict allowlist validation
│   ├── api/                    # FastAPI endpoints
│   │   ├── app.py
│   │   └── schemas.py
│   └── config/
│       └── settings.py         # Pydantic-Settings configuration
├── tests/                      # 693 tests (unit + integration + E2E)
├── pyproject.toml
├── README.md
├── DEVELOPMENT.md              # Developer guide & architecture deep-dive
└── LICENSE
```

---

## Testing

```bash
# Run the full suite
pytest

# Run specific test modules
pytest tests/test_agent.py -v
pytest tests/test_opa_loop.py -v
pytest tests/test_remote_e2e.py -v

# Run with coverage
pytest --cov=src/celeste --cov-report=html
```

**Current status:** 693 tests passing, 0 failures.

---

## Security Architecture

Every tool call passes through a defense-in-depth pipeline:

```
[ Tool Call ]
     │
     ▼
┌────────────────────────┐
│ 1. Security Auditor    │  → Deterministic regex + LLM heuristic check
└───────────┬────────────┘
            │ (Pass)
            ▼
┌────────────────────────┐
│ 2. Tool Registry       │  → Strict allowlist validation
└───────────┬────────────┘
            │ (Pass)
            ▼
┌────────────────────────┐
│ 3. Isolated Workspace  │  → Executed inside sandbox (tmp / Docker / Firecracker)
└────────────────────────┘
```

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

## Acknowledgments

Celeste-DAG's architecture is inspired by:
- **Temporal.io** — event-sourced replay, durable execution
- **Elixir/OTP** — actor isolation, supervision trees, let-it-crash
- **MCP (Model Context Protocol)** — tool schema standardization
- **LangGraph** — state-based graph execution
