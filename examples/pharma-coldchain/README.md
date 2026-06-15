# Pharma Cold-Chain Crisis Response

A production-grade Celeste-DAG example orchestrating a multi-jurisdiction
pharmaceutical logistics crisis in real-time, with live IoT data, regulatory
compliance checks, and ethical human-in-the-loop decisions.

## Scenario

2.4M doses of mRNA vaccine at Amsterdam hub have experienced a cold-chain
excursion. All affected batches must be rerouted to alternative qualified
hubs, requalified per destination country GDP requirements, with new
transport certificates generated. Hospitals are prioritized over clinics
in African distribution nodes pending ethics committee approval.

See [goal.md](./goal.md) for the full natural-language goal.

## Prerequisites

- Python 3.11+
- Docker + Docker Compose
- LLM API key (Anthropic Claude recommended, OpenAI also supported)
- 16GB+ RAM (for parallel workspaces and real services)

## Quick Start

```bash
# 1. Clone and install Celeste (if not already done)
cd /path/to/Celeste
pip install -e ".[dev]"

# 2. Navigate to the example
cd examples/pharma-coldchain

# 3. Configure API keys
cp .env.example .env
# Edit .env: set LLM_API_KEY=sk-...

# 4. Launch the real infrastructure stack
docker compose up -d
# Starts: PostgreSQL, Redis, Mailhog, IoT telemetry server, customs API

# 5. (Optional) Seed data for a richer scenario
python seed_data/load.py

# 6. Run the scenario in local mode
python run_local.py

# 7. Watch Mailhog for escalation emails
open http://localhost:8025
```

## Services

| Service | Port | Purpose |
|---------|------|---------|
| `postgres-hub` | 5432 | PostgreSQL tracking shipments, hubs, and batch qualifications |
| `redis-cache` | 6379 | Redis for IoT telemetry buffer and LLM result cache |
| `email-gateway` | 1025 (SMTP), 8025 (UI) | Mailhog capturing escalation emails |

> **Note:** The previous compose file also defined `iot-telemetry-server`,
> `customs-api`, and `celeste-agent`. Those services were removed because
> their commands referenced files/modules that don't exist (PHARMA-1,
> PHARMA-14, DX-006). Local mode (`run_local.py`) does not need them —
> it runs everything in-process.

## Execution Modes

### Local Mode (`run_local.py`)

Agent and engine run in the same process with zero network overhead.
This is the default and recommended mode for development and demos.

```bash
python run_local.py
```

Environment variable overrides:

```bash
DATABASE_URL=postgresql+asyncpg://localhost:5432/pharma_coldchain \\
LLM_PROVIDER=openai LLM_MODEL=gpt-4o LLM_API_KEY=sk-... \\
python run_local.py
```

### Remote Mode (`run_remote.py` — stub)

> **Disabled.** The `celeste-agent` service was removed from
> docker-compose.yml (see DX-006 / PHARMA-14). To re-enable this mode,
> implement `src/celeste/core/agent/serve.py` and the corresponding
> compose service.

### Embedded Mode (`run_embedded.py` — stub)

Embeds Celeste inside a user's own FastAPI application. Demonstrates library
usage, custom endpoints, and integration patterns.

```bash
python run_embedded.py --host 127.0.0.1 --port 9000
```

## Verification

The example includes a verification script that judges the workflow's
execution against the event ledger:

```bash
# Run the scenario first to get a workflow_id:
python run_local.py
# (prints workflow_id on completion)

# Then verify:
python verify.py --mode=local --workflow-id=<uuid>
```

The evaluator checks 8 Celeste features:
1. Dynamic OPA Loop (replanning)
2. Saga Compensation
3. Tiered Escalation (human-in-the-loop)
4. Continue-As-New (checkpointing)
5. Multi-Workspace Parallelism
6. Security Pipeline
7. Cross-Mode Parity
8. Model Agnosticism

## Directory Structure

The example is split across two sibling directories because Python module
names cannot contain hyphens:

```
pharma-coldchain/                    # Runners, config, seed data, docs
├── docker-compose.yml               # Real infrastructure services
├── goal.md                          # Natural-language workflow goal
├── .env.example                     # Environment template (the only config source)
├── README.md                        # This file
├── run_local.py                     # Local mode runner
├── run_remote.py                    # Remote mode stub
├── run_embedded.py                  # Embedded SDK stub
├── verify.py                        # Evaluation wrapper
└── seed_data/                       # Seed data, schema, fallback tariffs

pharma_coldchain/                    # Custom pharma toolkits (Python module)
└── tools/                           # Importable via examples.pharma_coldchain.tools.*
    ├── cold_chain.py
    ├── customs_bridge.py
    ├── gdp_compliance.py
    └── pharma_toolkit.py
```

## Cost Estimate

The pharma scenario is LLM-driven: the planner generates DAG nodes
dynamically each OPA cycle, so node and cycle counts vary per run and
depend on the LLM provider. Cost scales roughly linearly with the
number of OPA cycles until `goal_achieved` (capped by `MAX_OPA_CYCLES`,
default 100). For budget control, set these in `.env`:

| Setting | Default | Description |
|---------|---------|-------------|
| `MAX_OPA_CYCLES` | 100 | Hard cap on OPA-loop iterations. When hit, escalates. |
| `MAX_LLM_TOKENS` | 50000 | Token budget per workflow. When hit, escalates. |
| `MAX_LLM_COST_USD` | 5.00 | USD cost ceiling per workflow (estimated from tokens). When hit, escalates. Set to 0 to disable. |
| `WORKFLOW_RETENTION_DAYS` | 0 (disabled) | Terminal workflows older than this are deleted by the background sweep. Set to 30+ in production. |

Approximate order-of-magnitude cost for a typical run:

| Provider | Est. Tokens | Est. Cost |
|----------|-------------|-----------|
| Anthropic Claude 3.5 Sonnet | ~50K | ~$1.50 |
| OpenAI GPT-4o | ~50K | ~$0.75 |
| Ollama (local) | ~50K | $0.00 |

## Teardown

```bash
# Stop and remove all services
docker compose down -v

# Or use the example runner from Python:
python -c "import asyncio; from celeste.examples.runner import ExampleRunner; asyncio.run(ExampleRunner('.').stop_services())"
```
