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
# Edit .env: set ANTHROPIC_API_KEY=sk-ant-...

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
| `iot-telemetry-server` | 8080 | FastAPI WebSocket streaming temperature/humidity from 200+ loggers |
| `customs-api` | 8090 | FastAPI server with country-specific import rule logic |
| `celeste-agent` | 8900 | Celeste environment agent (remote mode) |

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
LLM_PROVIDER=openai LLM_MODEL=gpt-4o OPENAI_API_KEY=sk-... \\
python run_local.py
```

### Remote Mode (`run_remote.py` — stub)

Connects to a Celeste agent server via WebSocket. Requires the `celeste-agent`
service from docker compose to be running.

```bash
docker compose up celeste-agent -d
python run_remote.py --agent-url ws://localhost:8900/ws
```

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

```
pharma-coldchain/
├── docker-compose.yml       # Real infrastructure services
├── celeste_config.yml        # Engine configuration
├── goal.md                   # Natural-language workflow goal
├── .env.example              # Environment template
├── README.md                 # This file
├── run_local.py              # Local mode runner
├── run_remote.py             # Remote mode stub
├── run_embedded.py           # Embedded SDK stub
├── verify.py                 # Evaluation wrapper
├── seed_data/                # Seed data, schema, fallback tariffs
└── tools/                    # Custom pharma toolkits
    ├── cold_chain.py
    ├── customs_bridge.py
    └── gdp_compliance.py
```

## Cost Estimate

Running the full pharma scenario (all 47 nodes, 23 OPA cycles):

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
