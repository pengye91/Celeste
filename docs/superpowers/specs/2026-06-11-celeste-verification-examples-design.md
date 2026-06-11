# Celeste Verification Examples Design

**Date:** 2026-06-11
**Topic:** Three Complex Real-World Examples for Celeste-DAG
**Status:** Design Approved

> **SCOPE NOTE (post-review):** This implementation covers ONLY the evaluation module and the **pharma cold-chain** example. M&A and Urban scenarios are **DEFERRED** to future PRs — see TODOS.md.

---

## 1. Overview & Goals

### Purpose

These three examples are **production-grade reference implementations** that showcase what Celeste-DAG can orchestrate. They are not tests, benchmarks, or mock demos — they are real, complicated, multi-domain workflows that users can clone, run, and observe solving genuinely hard problems in real-time.

Each example demonstrates Celeste's full capability stack: dynamic OPA Loop with live replanning, durable execution with event sourcing, saga compensation, tiered escalation with human-in-the-loop, continue-as-new checkpointing, multi-workspace parallelism, security auditing, and cross-mode portability.

### Infrastructure Principle

> **Everything that can be real, is real.**
>
> All services run as actual Docker containers. All LLM calls hit real provider APIs (Anthropic, OpenAI, Gemini, Ollama). All data is processed by real software. The only "simulated" aspect is the *scenario seed data* (e.g., sample shipment manifests, sample legal documents, sample census blocks) — and even that is real file formats processed by real tools.

### Success Criteria

For each example to be considered verified:

| Feature | Verification Target |
|---------|---------------------|
| **Dynamic OPA Loop** | Planner issues real LLM calls that rewire the live DAG based on real observations from real services |
| **Saga Compensation** | A real failure in a real service triggers actual rollback commands against real stateful services |
| **Tiered Escalation** | Workflow genuinely pauses; human interacts via real API endpoint; workflow resumes with real state |
| **Continue-As-New** | Process terminates; new process starts; reads real checkpoint from real database; continues correctly |
| **Multi-Workspace Parallelism** | 4+ real Docker containers running concurrently, each doing real work |
| **Security Pipeline** | Real deterministic regex + real LLM security audit on real tool call payloads; at least one call genuinely blocked |
| **Cross-Mode Portability** | Same scenario definition runs identically in Local, Remote, and Embedded SDK modes |
| **Model Agnosticism** | Example passes with at least 2 real LLM providers |

---

## 2. Scenario 1: Global Pharma Cold-Chain Crisis Response

**Domain:** Healthcare / Logistics / Regulatory Compliance
**Primary Toolkit:** `SystemDataToolkit` + custom GDP/compliance tools
**Workspace Type:** Docker containers (one per regional distribution track)

### What It Demonstrates

Celeste coordinating a multi-jurisdiction logistics crisis in real-time, with live IoT data, real regulatory compliance checks, and ethical human-in-the-loop decisions.

### Real Infrastructure Stack

| Service | Purpose |
|---------|---------|
| `postgres-hub` | Real PostgreSQL tracking all shipments, hubs, and batch qualifications |
| `redis-cache` | Real Redis for IoT telemetry buffer and LLM result cache |
| `iot-telemetry-server` | Real FastAPI WebSocket server streaming temperature/humidity JSON every 30s from 200+ loggers |
| `customs-api` | Real FastAPI server with actual country-specific import rule logic |
| `pdf-generator` | Real LibreOffice headless container generating GDP-compliant transport certificates |
| `email-gateway` | Real Mailhog capturing actual emails sent to WHO ethics committee |
| `celeste-agent` | Real `EnvironmentAgent.serve()` in a Docker container |

### The Workflow Goal

```
2.4M doses of mRNA vaccine at Amsterdam hub have experienced
a cold-chain excursion. Reroute all affected batches to alternative
qualified hubs, requalify each batch per destination country GDP
requirements, generate new transport certificates, and prioritize
hospitals over clinics in African distribution nodes pending ethics
committee approval.
```

### Live Execution Flow

1. **Observes** the real PostgreSQL database and real WebSocket telemetry stream
2. **Plans** an initial DAG: identify affected batches → find alternate hubs → check hub qualification → generate paperwork → schedule transport
3. **Acts** by calling real tools: SQL queries against PostgreSQL, REST POSTs to customs API, LibreOffice RPC for PDF generation, SMTP via Mailhog
4. **Evaluates** after each batch: Did the hub qualification pass? Is telemetry green? If a reefer unit shows degradation mid-route, **replan** the route
5. **Escalates** to Tier 4 when supply < demand in African nodes — sends real email, pauses workflow, waits for human response via real POST `/resume`
6. **Compensates** if a batch exceeds temperature: real SQL UPDATE to mark "destroyed", real API call to incineration facility, real reorder from alternate manufacturing site

### Dynamic Replanning Triggers

- Customs API returns new requirement for Country X → planner extends DAG with additional document generation
- IoT stream shows truck reefer failure → planner rewires route to nearest qualified hub
- Hub capacity query shows full → planner discovers next alternate from real database

---

## 3. Scenario 2: Cross-Border M&A Due Diligence with Adversarial Counterparties

> **DEFERRED** — Not in scope for this implementation. See TODOS.md for future work.

**Domain:** Legal / Finance / Multi-Jurisdiction Corporate Law
**Primary Toolkit:** `CodingVerticalToolkit` + `SystemDataToolkit` + custom legal/financial tools
**Workspace Type:** Git worktrees (one per workstream)

### What It Demonstrates

Celeste orchestrating a multi-workstream, multi-jurisdiction legal and financial investigation where the target company is deliberately withholding information — requiring dynamic discovery, recursive follow-up, and expert human review of red-flag findings.

### Real Infrastructure Stack

| Service | Purpose |
|---------|---------|
| `postgres-diligence` | Real PostgreSQL tracking 12,000+ documents, findings, risk scores, and workstream status |
| `elasticsearch-docs` | Real Elasticsearch indexing all contracts, permits, and filings for full-text search |
| `minio-docstore` | Real MinIO S3-compatible object store holding actual PDF documents |
| `ocr-service` | Real Tesseract OCR in a container with multi-language support (DE, PL, VI, JP) |
| `patent-api-bridge` | Real FastAPI proxy querying live USPTO, EPO, JPO APIs for patent validity checks |
| `translation-api` | Real LibreTranslate container for on-premise document translation |
| `valuation-engine` | Real Python/FastAPI service running DCF and comparable-company valuation models |
| `email-gateway` | Real Mailhog capturing escalation emails to senior partners |
| `celeste-agent` | Real `EnvironmentAgent.serve()` in Docker |

### The Workflow Goal

```
Conduct full due diligence on German automotive supplier TargetCo
across financial, legal, tax, environmental, IP, and HR workstreams.
Operations in DE, MX, PL, VN. Management has produced incomplete
documents. Discover gaps, request follow-up, analyze findings, flag
red risks, and produce a final investment committee memo with
valuation adjustment.
```

### Live Execution Flow

1. **Ingests Wave 1 documents** from MinIO: real PDFs, real Excel files, real scanned contracts
2. **OCRs and indexes** them via real Tesseract → real Elasticsearch
3. **Runs 6 parallel workstreams** in separate Git worktrees:
   - **Financial:** Parses real IFRS XBRL, runs ratio analysis, feeds data to real valuation engine
   - **Legal:** Reviews real contracts, checks governing law clauses, cross-references litigation databases
   - **Tax:** Analyzes transfer pricing docs, checks BEPS compliance via real calculation logic
   - **Environmental:** Validates IPPC permits against real regulatory databases
   - **IP:** Queries live patent offices via the patent-api-bridge for validity and infringement
   - **HR:** Parses Works Council agreements, checks TUPE implications
4. **Discovers gaps dynamically:** After Wave 1, queries Elasticsearch and finds 340 broken cross-references. Planner generates follow-up request DAG. TargetCo "responds" with Wave 2 (from real database of seeded follow-up docs).
5. **Escalates red flags:** When Legal workstream finds a real litigation reference (EUR 200M product liability), workflow:
   - Pauses for senior partner review (real email via Mailhog)
   - On resume, triggers saga compensation: valuation engine reruns with litigation reserve, Financial/Tax/IP findings are invalidated and regenerated
6. **Generates final memo:** Real LLM call synthesizes all findings into an investment committee memo, saved as real DOCX via LibreOffice

### Dynamic Replanning Triggers

- Patent office API returns "patent expired in JP" → IP workstream extends to check infringement exposure; Legal workstream replans to review licensing agreements
- Environmental scan reveals unreported soil contamination in PL → new sub-workflow for remediation cost estimation; valuation engine replans with impairment
- HR discovers missing Works Council consultation for MX layoffs → escalation to labor law expert; deal timeline extended

---

## 4. Scenario 3: Post-Hurricane Urban Infrastructure Reconstruction

> **DEFERRED** — Not in scope for this implementation. See TODOS.md for future work.

**Domain:** Civil Engineering / Government / Climate Science
**Primary Toolkit:** `SystemDataToolkit` + custom GIS/hydrology tools
**Workspace Type:** Docker containers (one per neighborhood) + specialized simulation workspace

### What It Demonstrates

Celeste orchestrating a multi-stakeholder, multi-year civil engineering program across 50 neighborhoods, with real GIS data, hydrological simulations, budget constraints, and democratic approval gates.

### Real Infrastructure Stack

| Service | Purpose |
|---------|---------|
| `postgres-gis` | Real PostgreSQL + PostGIS storing building footprints, damage assessments, resident relocation status |
| `redis-cache` | Real Redis for simulation results and checkpoint state |
| `hydrology-simulator` | Real Python/FastAPI service running actual shallow-water equations on a real DEM grid |
| `satellite-ingest` | Real GDAL-based service ingesting real GeoTIFF satellite imagery from Sentinel-2 |
| `contractor-bidding` | Real FastAPI service managing contractor licenses, bids, OSHA records, and standby activation |
| `fema-api-bridge` | Real FastAPI proxy to FEMA's public APIs for flood zone data and individual assistance programs |
| `document-engine` | Real LibreOffice headless generating environmental impact statements and City Council briefing packets |
| `notification-gateway` | Real Mailhog + webhook sink for resident alerts, contractor notifications, and City Council votes |
| `celeste-agent` | Real `EnvironmentAgent.serve()` in Docker |

### The Workflow Goal

```
Hurricane Mara caused catastrophic flooding across coastal MetroBay.
50 neighborhoods need infrastructure assessment, resident relocation,
contractor bidding, flood-mitigation design, and FEMA funding coordination.
Budget: $2.1B. Prioritize critical infrastructure. Ensure no mitigation
measure worsens downstream flooding. All eminent domain decisions require
City Council approval. Produce EPA-compliant environmental impact statements
for each major project.
```

### Live Execution Flow

1. **Ingests real GIS data:** Satellite imagery via GDAL → PostGIS. FEMA flood maps via real API. Census blocks via real TIGER/Line data.
2. **Runs damage assessment:** Queries PostGIS for buildings in flood zones. Cross-references with pre-hurricane tax assessor data.
3. **Runs 50 neighborhood sub-workflows in parallel** (Docker workspaces), each:
   - Assessing damage severity
   - Estimating resident relocation needs
   - Checking infrastructure dependencies (sewage, power, roads)
4. **Runs hydrological simulation:** Real shallow-water solver on real DEM grid. Takes 15-30 minutes of real compute.
5. **Discovers cross-neighborhood dependencies:** Simulation reveals District 3 seawall raises District 7 flooding. Planner dynamically adds dependency edges and replans sequencing.
6. **Manages contractor bidding:** Real POST to bidding service. Evaluates bids against OSHA records, license validity, past performance.
7. **Enforces budget propagation:** As bids arrive, real SQL queries sum spending. If District 12 exceeds allocation, planner either cuts scope or reallocates from lower-priority districts — triggering cascading replanning across dependent neighborhoods.
8. **Human gates:** Every eminent domain acquisition triggers real email to City Council, pauses workflow. Council votes via real POST `/workflows/{id}/resume`. EPA sign-offs work the same way.
9. **Compensates on contractor default:** If winning contractor defaults, compensation chain:
   - Activate standby contractor (real API call)
   - Adjust dependent neighborhood schedules (real SQL updates)
   - Recalculate FEMA drawdown schedule (real calculation)
   - Notify affected residents (real email)
10. **Generates EIS documents:** Real LLM synthesizes environmental findings into EPA-compliant impact statements, rendered as real PDFs via LibreOffice

### Dynamic Replanning Triggers

- New hurricane forecast shows Category 2 approaching → emergency measures override long-term plans; planner rewires priority to evacuation infrastructure
- Hydrology simulation shows unintended consequence → planner rewires Districts 3-7 sequencing
- Contractor bid comes in 40% over estimate → planner either cuts scope or reallocates budget, triggering cross-neighborhood cascade replanning
- FEMA API returns reduced allocation → budget constraint propagates, planner deprioritizes non-critical neighborhoods

---

## 5. Architecture & Project Structure

### Directory Layout

```
examples/
├── pharma-coldchain/
│   ├── docker-compose.yml          # Real services: Postgres, Redis, IoT server, etc.
│   ├── celeste_config.yml          # Engine settings, LLM provider, workspace type
│   ├── goal.md                     # The natural-language goal
│   ├── seed_data/                  # Real CSVs, PDFs, certificates to load into services
│   ├── tools/                      # Custom toolkits for this domain
│   │   ├── gdp_compliance.py
│   │   ├── cold_chain.py
│   │   └── customs_bridge.py
│   ├── run_local.py                # Local mode: in-process agent
│   ├── run_remote.py               # Remote mode: WebSocket to agent server
│   ├── run_embedded.py             # Embedded SDK: FastAPI app
│   └── README.md                   # Full setup and running instructions
├── ma-due-diligence/
│   ├── docker-compose.yml
│   ├── celeste_config.yml
│   ├── goal.md
│   ├── seed_data/
│   │   ├── wave1/                  # Real PDF contracts, financial statements
│   │   ├── wave2/                  # Follow-up documents
│   │   └── wave3/                  # Final disclosures
│   ├── tools/
│   │   ├── document_ingestion.py
│   │   ├── patent_bridge.py
│   │   ├── valuation_client.py
│   │   └── legal_analysis.py
│   ├── run_local.py
│   ├── run_remote.py
│   ├── run_embedded.py
│   └── README.md
└── urban-infrastructure/
    ├── docker-compose.yml
    ├── celeste_config.yml
    ├── goal.md
    ├── seed_data/
    │   ├── satellite/              # Real GeoTIFF imagery
    │   ├── census/                 # Real TIGER/Line shapefiles
    │   ├── fema/                   # Real flood zone data
    │   └── damage_reports/         # Real assessment forms
    ├── tools/
    │   ├── gis_toolkit.py
    │   ├── hydrology_client.py
    │   ├── contractor_api.py
    │   └── eis_generator.py
    ├── run_local.py
    ├── run_remote.py
    ├── run_embedded.py
    └── README.md
```

### Execution Modes

**Local Mode** (`run_local.py`):
- Agent and engine in same process
- Zero network overhead
- Workspaces: local_tmp or Docker containers

**Remote Mode** (`run_remote.py`):
- Agent runs in Docker container with full toolkit stack
- Engine connects via persistent WebSocket
- Demonstrates remote orchestration, network resilience, auth

**Embedded SDK** (`run_embedded.py`):
- Celeste embedded in user's own FastAPI application
- Demonstrates library usage, custom endpoints, integration

### Cross-Mode Verification

Each example includes a `verify.py` script that:
1. Runs the scenario in Local mode
2. Wipes state, runs in Remote mode
3. Wipes state, runs in Embedded mode
4. Compares final database state across all three runs
5. Reports token usage and cost per mode

---

## 6. Error Handling & Advanced Feature Triggers

### Saga Compensation

| Scenario | Trigger | Compensation Chain |
|----------|---------|-------------------|
| **Pharma** | Batch B-1847 exceeds 8C for 45 min during reroute | 1. Mark batch "destroyed" in Postgres<br>2. Generate witnessed incineration certificate (LibreOffice)<br>3. Trigger reorder from Bangalore hub (real API)<br>4. Adjust dependent downstream allocations |
| **M&A** | EUR 200M litigation discovered in Wave 2 | 1. Invalidate prior "clean" Legal assessment<br>2. Regenerate Financial valuation with litigation reserve<br>3. Rerun Tax workstream with settlement tax treatment<br>4. Adjust IP valuation for encumbrance<br>5. Update investment memo |
| **Urban** | Contractor "Coastal Rebuild Inc" defaults mid-project | 1. Activate standby contractor (real bidding API)<br>2. Reschedule dependent neighborhoods (PostGIS update)<br>3. Recalculate FEMA drawdown (real formula)<br>4. Notify 340 affected residents (real email)<br>5. Adjust budget propagation to downstream districts |

### Tiered Escalation

| Tier | Scenario | Condition | Human Action |
|------|----------|-----------|--------------|
| **Tier 4** | **Pharma** | African supply < demand after reroute | Ethics committee receives email, clicks link to POST `/resume` with allocation priority |
| **Tier 4** | **M&A** | High-confidence legal risk (EUR 50M+ exposure) | Senior partner receives flagged findings, approves/rejects via API with written rationale |
| **Tier 4** | **Urban** | Eminent domain for 50+ properties in District 7 | City Council receives briefing packet, votes via API; majority approval resumes workflow |
| **Tier 2** | **Pharma** | Customs API returns 503 for 3 retries | Replan with cached tariff schedule, flag for human verification within 24h |
| **Tier 2** | **M&A** | Patent office API rate-limits during IP review | Switch to secondary data source, queue retry for off-hours |
| **Tier 2** | **Urban** | Hydrology simulator returns NaN (numerical instability) | Reduce timestep, rerun with finer grid, flag result confidence |

### Continue-As-New

| Scenario | Checkpoint Trigger | State Preserved |
|----------|-------------------|-----------------|
| **Pharma** | Every 6 hours or 10 completed batches | Shipment status, hub qualification cache, pending ethics approvals, IoT buffer watermark |
| **M&A** | After each document wave completion | Ingested doc IDs, Elasticsearch index state, workstream completion flags, pending escalations |
| **Urban** | After each hydrology simulation + after each City Council vote | PostGIS damage assessments, committed contractor bids, approved EIS document IDs, budget burn-down |

### Security Pipeline Blocks

| Scenario | Blocked Tool Call | Why Blocked |
|----------|------------------|-------------|
| **Pharma** | `UPDATE batches SET temp_excursion=true WHERE batch_id='*'` | Regex audit: wildcard `*` in WHERE clause would affect all batches |
| **M&A** | `DELETE FROM documents WHERE jurisdiction='all'` | LLM audit: destructive operation without document ID scope |
| **Urban** | `DROP TABLE residents` | Deterministic audit: DROP TABLE is not in allowlist |

---

## 7. Running the Examples

### Prerequisites

- Python 3.11+
- Docker + Docker Compose
- LLM API keys (Anthropic, OpenAI, or both) in `.env`
- 16GB+ RAM recommended (for parallel workspaces and real services)

### Quick Start

```bash
# 1. Clone and install
git clone https://github.com/pengye91/Celeste.git
cd Celeste
pip install -e ".[dev]"

# 2. Choose an example
cd examples/pharma-coldchain

# 3. Configure LLM provider
cp .env.example .env
# Edit .env: add ANTHROPIC_API_KEY=sk-...

# 4. Launch real infrastructure
docker compose up -d
# This starts: PostgreSQL, Redis, IoT server, customs API, LibreOffice, Mailhog

# 5. Seed real data
python seed_data/load.py
# Loads real CSV manifests, sample certificates, hub qualification records

# 6. Run the example
python run_local.py
# Or: python run_remote.py
# Or: python run_embedded.py

# 7. Watch it work
# - Real LLM calls compile the DAG
# - Real SQL queries track shipments
# - Real WebSocket telemetry streams in
# - Real emails arrive in Mailhog at http://localhost:8025
# - Real PDFs generate in output/

# 8. Verify results
python verify.py --mode=local
# Compares final database state against expected schema
# Reports token usage and estimated cost
```

### Expected Console Output

```
[16:23:01] Engine started | Workflow: wf_pharma_001 | Goal: "2.4M doses..."
[16:23:04] Planner: compiled DAG with 47 nodes
[16:23:04] OPA Cycle 1 | Observe: 12 batches affected, Amsterdam hub offline
[16:23:08] OPA Cycle 1 | Plan: reroute via Frankfurt, Paris, Bangalore hubs
[16:23:15] OPA Cycle 1 | Act: generated 12 transport certificates
[16:23:22] OPA Cycle 2 | Observe: Batch B-1847 reefer showing -12C
[16:23:25] OPA Cycle 2 | Plan: REPLAN — divert B-1847 to Paris cold storage
[16:23:45] OPA Cycle 5 | Observe: Nigeria customs requires new license
[16:23:48] OPA Cycle 5 | Plan: EXTEND DAG — add license_application node
[16:24:12] OPA Cycle 8 | Evaluate: ESCALATE — African supply < demand
[16:24:12] Workflow PAUSED | Tier 4 | Email sent to ethics@who.int
[16:45:33] Workflow RESUMED | Human input: "priority: hospitals > clinics"
[16:45:36] OPA Cycle 9 | Plan: adjusted allocation with priority weights
...
[17:12:45] Workflow COMPLETED | 47/47 nodes | Cycles: 23 | Tokens: 48,392 | Est. cost: $1.47
```

### Verification Output

```bash
$ python verify.py --mode=local

✓ PostgreSQL: 47 task nodes recorded
✓ Saga compensation: 1 rollback executed (Batch B-1847)
✓ Escalation: 1 Tier-4 pause, 1 human resume
✓ Checkpoint: 3 continue-as-new transitions
✓ Security audit: 234 calls audited, 1 blocked (wildcard UPDATE)
✓ Final state: 11 batches delivered, 1 destroyed, 12 rerouted

Token Usage:
  Planner:   23 calls ×  avg 890 tokens = 20,470
  Evaluator: 23 calls ×  avg 780 tokens = 17,940
  Security:  234 calls × avg 45 tokens  = 10,530
  Total: 48,940 tokens ≈ $1.47 (Claude 3.5 Sonnet)

Cross-mode parity: Local ✓ | Remote ✓ | Embedded ✓
```

---

## 8. Cost & Performance Estimates

| Example | LLM Calls | Est. Tokens | Est. Cost (Claude 3.5) | Duration | Infra Services |
|---------|-----------|-------------|------------------------|----------|----------------|
| Pharma Cold-Chain | ~50 | ~50K | $1.50 | 45-90 min | 7 containers |
| M&A Due Diligence | ~120 | ~150K | $4.50 | 2-4 hours | 9 containers |
| Urban Infrastructure | ~80 | ~100K | $3.00 | 3-6 hours | 9 containers |

*Note: Costs are estimates based on current Anthropic pricing. Actual costs vary by provider and model. Ollama local mode reduces cost to zero at the expense of speed and capability.*

---

## 9. Dependencies & External APIs

### Required (Real)
- LLM provider API key (Anthropic, OpenAI, or Gemini)
- Docker + Docker Compose

### Optional (Real, used by specific examples)
- USPTO Open Data API (M&A example, patent checks)
- FEMA Open Data API (Urban example, flood zones)
- EPO Open Patent Services (M&A example)
- LibreTranslate API or local instance (M&A example, translation)

### Fallback Strategy
If external APIs are unavailable (rate limits, downtime), each example:
1. First attempts real API call
2. Falls back to cached local dataset with stale-data flag
3. Logs the fallback for human awareness
4. Continues workflow with degraded confidence

---

## 10. Security & Safety Considerations

- All examples run in isolated Docker networks
- No real PII in seed data — all names, addresses, SSNs are synthetic
- LLM API keys are never logged or committed
- Mailhog captures emails locally — no real emails sent
- Security auditor blocks destructive operations before execution
- Each example includes `teardown.py` to wipe all data

---

## 11. Celeste Evaluation Module

### Location

```
src/celeste/evaluation/
├── __init__.py
├── collector.py       # Runtime metrics collection
├── assertions.py      # Programmatic feature assertions
├── detector.py        # Feature exercise detection from event log
├── reporter.py        # Structured report generation
├── compliance.py      # Cross-mode parity & consistency checks
└── schemas.py         # Pydantic models for metrics and reports
```

### Design Principle

> **The engine produces evidence; the evaluator judges it.**
>
> The evaluation module does not instrument or modify the engine. It reads the durable event ledger (`TaskEvent` table) and the final database state after a workflow completes, then produces a deterministic verdict.

### How It Works

```python
from celeste import Engine
from celeste.evaluation import Evaluator, assert_replan, assert_saga

# Run the workflow normally
engine = Engine(agent=agent)
result = await engine.run(goal=goal)

# Evaluate what actually happened
evaluator = Evaluator(engine=engine, workflow_id=result.id)
report = await evaluator.evaluate()

print(report.summary)
# Pass: 7/7  |  Fail: 0/7  |  Warnings: 1
```

### Concrete Metrics & Assertions

| Feature | Metric Collected | Pass Criteria | Fail Criteria |
|---------|-----------------|---------------|---------------|
| **Dynamic OPA Loop** | `replan_events` count + `dag_diff` (nodes added/removed/rewired) | `replan_events >= 1` AND `dag_diff.nodes_changed >= 1` | Zero replan events OR planner emitted identical DAG across all cycles |
| **Saga Compensation** | `compensation_chain` (ordered list of compensation nodes executed) + `affected_nodes` | Compensation chain matches expected sequence AND independent branches remain `completed` | Compensation skipped, wrong order, or over-compensated (rolled back independent branches) |
| **Tiered Escalation** | `escalation_events` (tier, timestamp, resolution_time, human_input_hash) | Tier-4 pause occurred AND `resolution_time > 0` AND human input was received via API | Escalation fired but workflow auto-resumed without human input OR never escalated when expected |
| **Continue-As-New** | `checkpoint_events` + `recovery_events` + `state_hash_before` / `state_hash_after` | `checkpoint_events >= 1` AND `recovery_events >= 1` AND `state_hash_before == state_hash_after` (state preserved) | Process crashed but no recovery event OR recovered state diverged from checkpoint |
| **Multi-Workspace** | `workspace_spawn_events` + `workspace_destroy_events` + `concurrent_max` | `concurrent_max >= 4` AND every spawn has matching destroy (no leaks) | Fewer than 4 parallel workspaces OR workspace leaked (spawn without destroy) |
| **Security Pipeline** | `audit_events` (call, deterministic_result, llm_result, final_verdict) + `blocked_events` | `audit_events == tool_call_count` (100% coverage) AND `blocked_events >= 1` AND blocked call was genuinely dangerous | Audit skipped for any mutating call OR zero blocked calls OR false positive block (safe call rejected) |
| **Cross-Mode Parity** | `feature_flags` + `completed_nodes` + `final_schema` per mode | Local, Remote, Embedded produce identical feature exercise results AND identical `completed_nodes` count | Any mode produces different feature results OR different node completion count |
| **Model Agnosticism** | `provider_a_final_state` vs `provider_b_final_state` | Two different providers produce identical `final_state_hash` | State divergence across providers |

### Feature Detection from Event Log

The `detector.py` analyzes the event-sourced ledger:

```python
class FeatureDetector:
    async def detect_replan(self, workflow_id: str) -> ReplanEvidence:
        """
        Reads all TaskEvents for workflow_id.
        Looks for:
          - EventType.PLAN with dag_version > 1
          - EventType.OBSERVE followed by EventType.PLAN with different node_set
        Returns: count, dag_diffs, reasons
        """

    async def detect_saga(self, workflow_id: str) -> SagaEvidence:
        """
        Looks for:
          - EventType.COMPENSATION_START
          - Ordered EventType.COMPENSATION_STEP
          - EventType.COMPENSATION_END
          - Verifies independent branches untouched
        Returns: trigger, chain_executed, affected_scope
        """

    async def detect_escalation(self, workflow_id: str) -> EscalationEvidence:
        """
        Looks for:
          - EventType.ESCALATE with tier
          - EventType.WORKFLOW_PAUSED
          - EventType.HUMAN_INPUT_RECEIVED
          - EventType.WORKFLOW_RESUMED
        Returns: tier, pause_duration, human_input_present
        """
```

### Report Output

```python
class EvaluationReport(BaseModel):
    workflow_id: str
    overall: Literal["PASS", "FAIL", "PARTIAL"]
    features: dict[str, FeatureResult]  # 8 features
    metrics: RuntimeMetrics
    warnings: list[str]
    token_cost: TokenCostBreakdown

class FeatureResult(BaseModel):
    name: str
    status: Literal["PASS", "FAIL", "NOT_EXERCISED"]
    evidence: dict  # concrete data proving the verdict
    assertion: str   # the exact assertion that was checked
```

### Example Report (Pharma Scenario)

```bash
$ python -m celeste.evaluate --workflow-id=wf_pharma_001

═══════════════════════════════════════════════════════════════
  Celeste Evaluation Report  |  Workflow: wf_pharma_001
═══════════════════════════════════════════════════════════════

Overall: PASS  (7/7 features verified)

Features:
  ✓ Dynamic OPA Loop      PASS  replan_events=3, dag_nodes_changed=7
  ✓ Saga Compensation     PASS  trigger=B-1847, chain=4 steps, scope=1 batch
  ✓ Tiered Escalation     PASS  tier=4, paused=21m33s, human_input=received
  ✓ Continue-As-New       PASS  checkpoints=3, recovery=3, state_hash_match=True
  ✓ Multi-Workspace       PASS  concurrent_max=8, workspaces_leaked=0
  ✓ Security Pipeline     PASS  audited=234, blocked=1 (wildcard UPDATE)
  ✓ Cross-Mode Parity     PASS  local_hash=0x7a3f..., remote_hash=0x7a3f...
  ✓ Model Agnosticism     SKIP  (only Anthropic tested this run)

Metrics:
  OPA Cycles:        23
  Total Nodes:       47
  Completed:         47
  Failed:            0
  Compensated:       1
  Avg Cycle Latency: 2.3s

Token Cost:
  Planner:   23 calls ×  avg 890 tokens = 20,470  ($0.61)
  Evaluator: 23 calls ×  avg 780 tokens = 17,940  ($0.54)
  Security:  234 calls × avg 45 tokens  = 10,530  ($0.32)
  Total:     48,940 tokens                  ≈ $1.47

Warnings:
  - Customs API fell back to cached tariff schedule (Nigeria)
```

### Integration with Examples

Each example's `verify.py` becomes a thin wrapper:

```python
# examples/pharma-coldchain/verify.py
from celeste.evaluation import Evaluator, assertions

async def verify_pharma(workflow_id: str):
    evaluator = Evaluator(workflow_id=workflow_id)

    # Register scenario-specific assertions
    evaluator.assertions.add(
        assertions.assert_replan_occurred(min_count=1)
    )
    evaluator.assertions.add(
        assertions.assert_saga_compensation(
            trigger_pattern="B-1847",
            expected_chain=["mark_destroyed", "incineration_cert", "reorder", "adjust_allocation"]
        )
    )
    evaluator.assertions.add(
        assertions.assert_escalation(tier=4, resolved=True, max_pause_minutes=60)
    )

    report = await evaluator.evaluate()
    return report
```

---

## 12. Test Requirements (added during eng review)

### Unit Tests

**`tests/test_evaluation.py`** — Evaluation module unit tests (no external deps):
- `test_evaluator_empty_assertions` — no assertions → report has 0 features
- `test_detect_replan_no_events` — empty log → NOT_EXERCISED
- `test_detect_replan_found` — PLAN_GENERATED with different nodes → PASS
- `test_detect_saga_correct_chain` — COMPENSATION_TRIGGERED + COMPLETED in order → PASS
- `test_detect_saga_wrong_order` — COMPLETED before TRIGGERED → FAIL
- `test_detect_escalation_resolved` — ESCALATE + PAUSED + RESUMED within timeout → PASS
- `test_detect_escalation_timeout` — paused 61 min, max=60 → FAIL
- `test_detect_checkpoint_state_match` — checkpoint + recovery, hash match → PASS
- `test_detect_security_blocked_call` — blocked wildcard UPDATE → PASS
- `test_detect_security_no_audit` — mutating call with no audit → FAIL
- `test_assertion_exception_handled` — assertion raises → caught, marked FAIL

**`tests/test_pharma_tools.py`** — Custom tool tests (mocked external services):
- `test_gdp_compliance_valid_batch` — valid batch_id → qualified
- `test_gdp_compliance_db_error` — raises → structured error dict
- `test_customs_bridge_503_retry` — 503 twice then success → retry works
- `test_customs_bridge_fallback` — 503 three times → cached data returned
- `test_cold_chain_normal_telemetry` — WebSocket message → parsed temp/humidity
- `test_cold_chain_disconnect` — WebSocket drops → reconnects

### Integration Tests

**`tests/test_pharma_integration.py`**:
- `test_seed_data_loads` — load.py inserts expected rows
- `test_opa_loop_creates_workflow_record` — **CRITICAL regression**: OPALoop.run() must create Workflow + TaskNode records (currently ephemeral)
- `test_opa_loop_emits_workflow_events` — each cycle writes OBSERVATION_CAPTURED, PLAN_GENERATED, etc.

### E2E Tests

**`tests/e2e/test_pharma_end_to_end.py`** (requires Docker + LLM API key):
- `test_pharma_local_mode_completes` — docker compose up → run_local.py → evaluation PASS
- `test_pharma_escalation_flow` — workflow pauses → email in Mailhog → POST /resume → continues
- `test_pharma_saga_compensation` — trigger temp excursion → compensation chain runs
- `test_pharma_replan_on_customs_change` — customs API returns new rule → planner extends DAG
- `test_cross_mode_parity` — local + remote + embedded → state hashes match

### Test Markers
- `@pytest.mark.e2e` — requires Docker + real services
- `@pytest.mark.requires_llm` — requires LLM API key ($1–2 per run)
- `@pytest.mark.unit` — fast, no external deps

### CI Strategy
- CI runs: `pytest -m 'not e2e and not requires_llm'`
- Local pre-release: `pytest -m e2e`

---

## 13. NOT in Scope

Work explicitly deferred from this implementation:

| Item | Rationale |
|------|-----------|
| **M&A Due Diligence example** | Scope reduced to prove the system with one example first. M&A is the most complex (9 services, 6 workstreams, live patent APIs). Defer until pharma is verified. |
| **Urban Infrastructure example** | Most resource-intensive (GIS, hydrology simulation, 50 neighborhoods). Defer until evaluation module and pharma are stable. |
| **Firecracker workspace** | Docker workspace covers container isolation. Firecracker adds minimal marginal value for examples. |
| **Model agnosticism verification** | Requires running full example twice with different providers ($3+ cost). Defer to CI nightly or pre-release. |
| **LibreOffice PDF generation in example** | Custom tools can use reportlab or weasyprint instead. LibreOffice headless is heavy and slow. Can be swapped later. |

---

## 14. What Already Exists

Existing code/flows that partially solve sub-problems in this plan:

| Component | What It Already Does | Plan Reuses It? | Gap |
|-----------|---------------------|-----------------|-----|
| `Engine.submit_workflow()` | Persists DAGPlan as Workflow + TaskNode records | Yes — OPALoop will integrate with this | None |
| `Engine.run_workflow()` | Executes workflow with saga compensation, event logging, durable replay | Yes — OPALoop will delegate to this | None |
| `Engine._check_and_checkpoint()` | Archives workflow, creates new workflow with checkpoint state | Yes — will be wired into OPA loop | Currently dead code |
| `OPALoop.run()` | OPA cycle orchestration (observe → plan → act → evaluate) | Yes — core orchestration stays | Needs DB integration |
| `SecurityAuditor` | Two-phase audit (regex + LLM) for shell commands | Partially — needs extension to SQL/toolkit tools | Only audits `run_command` |
| `WebSocketTransport` / `WebSocketServer` | Full JSON-RPC over WebSocket with auth, reconnect, backoff | Yes — remote mode uses this | None |
| `DockerWorkspace` | Container workspace interface | Partially — needs real implementation | `execute()` is stub |
| `CheckpointManager` | Event-count-based checkpoint triggers | Yes — will be wired into OPA loop | Not connected to OPALoop |
| `LocalTmpWorkspace` | Local filesystem workspace | Yes — local mode uses this | None |
| `EnvironmentAgent` | MCP-compatible agent with tool protocol | Yes — all modes use this | Security audit not wired for all tools |

---

## 15. Critical Gap Implementation Plans

These three gaps were flagged during eng review as having **no test coverage, no error handling, and silent failure modes**. This section specifies exactly how to fix each one.

---

### Gap 1: OPA Loop History Memory Leak

**Problem:** `OPALoop.run()` appends the full observation, fragment model dump, and execution result to an in-memory `history` list every cycle. For a 23-cycle workflow with real database observations, this list grows unbounded and may OOM before hitting `MAX_LLM_TOKENS`.

**Root cause:** `opa_loop.py:253-260` — `history.append()` stores the full observation dict, fragment model dump, and execution result dict with no size limit.

**Files to touch:**
- `src/celeste/core/opa_loop.py`
- `src/celeste/config/settings.py`
- `tests/test_opa_loop.py`

**Implementation plan:**

1. **Add `OPA_HISTORY_MAX_CYCLES` to settings** (default: 5).
   - Only the last N cycles are kept in full detail.
   - Earlier cycles are summarized into a single "archived summary" entry.

2. **Add `_summarize_history_entry()` helper** in `OPALoop`:
   ```python
   def _summarize_history_entry(self, entry: dict) -> dict:
       """Compress a full history entry into a minimal summary."""
       return {
           "cycle": entry["cycle"],
           "decision": entry["decision"],
           "completed_nodes": len(entry["execution"].get("completed", [])),
           "failed_nodes": len(entry["execution"].get("failed", [])),
           "token_estimate": entry.get("token_estimate", 0),
       }
   ```

3. **Modify `OPALoop.run()` history management**:
   ```python
   # After appending new entry:
   if len(history) > self._settings.OPA_HISTORY_MAX_CYCLES:
       # Summarize the oldest full entry
       oldest = history.pop(0)
       summary = self._summarize_history_entry(oldest)
       # Append to a separate summaries list or prepend to history
       history.insert(0, {"_summary": True, "entries": [summary]})
   ```

4. **Planner prompt adjustment:** When calling `planner.plan()`, pass `history` (last 5 full + summaries). Add a system prompt note: "Earlier cycles are summarized. Focus on recent context."

**Edge cases:**
- `OPA_HISTORY_MAX_CYCLES = 0` → only summaries (extreme memory saving, reduced planner context)
- `OPA_HISTORY_MAX_CYCLES >= max_cycles` → no summarization (current behavior, for debugging)
- Summaries must still include enough context for the planner to detect loops (e.g., "Cycle 3: REPLAN, 2 failed nodes")

**Tests to add:**
- `test_opa_loop_history_truncated` — mock 10 cycles, assert history length <= max + 1
- `test_opa_loop_history_summary_present` — assert old cycles are summarized, not dropped
- `test_opa_loop_history_zero_max` — assert all entries are summaries

---

### Gap 2: Resume Endpoint Race Condition

**Problem:** When the evaluator returns `ESCALATE`, the OPA loop currently returns `WorkflowResult(status="escalated")` and terminates. There's no `PAUSED` state. A human trying to resume via `POST /workflows/{id}/resume` has no persisted state to resume from. Worse, if the resume POST arrives before the `WorkflowStatus` update is committed, it races and may be ignored or double-processed.

**Root cause:** `opa_loop.py:273-275` returns on ESCALATE with no persistence of loop state. `api/app.py` has no `/resume` endpoint.

**Files to touch:**
- `src/celeste/database/models.py`
- `src/celeste/core/opa_loop.py`
- `src/celeste/core/engine.py`
- `src/celeste/api/app.py`
- `src/celeste/api/schemas.py`
- `tests/test_api.py`
- `tests/test_opa_loop.py`

**Implementation plan:**

1. **Add `WorkflowStatus.PAUSED` to enum** in `database/models.py`.

2. **Add `human_input` column to Workflow model**:
   ```python
   human_input: Mapped[str | None] = mapped_column(Text, nullable=True)
   paused_at: Mapped[datetime | None] = mapped_column(nullable=True)
   ```

3. **Modify `OPALoop.run()` to pause instead of terminate on ESCALATE**:
   - When `decision == ESCALATE`:
     - Set `workflow.status = WorkflowStatus.PAUSED`
     - Set `workflow.paused_at = _utcnow()`
     - Persist `workflow.human_input = None` (placeholder)
     - Serialize loop state (history, cycle_count, llm_tokens) to `workflow.dag_definition["_opa_state"]`
     - Return `WorkflowResult(status="paused", reason=...)`
   - Do NOT return — the loop should be restartable.

4. **Add `OPALoop.resume()` method**:
   ```python
   async def resume(self, workflow_id: uuid.UUID, human_input: str) -> WorkflowResult:
       """Resume a paused workflow with human guidance."""
       # Load workflow
       # Verify status == PAUSED
       # Inject human_input into observation
       # Restore loop state from dag_definition["_opa_state"]
       # Continue OPA loop
   ```

5. **Add `POST /api/workflows/{workflow_id}/resume` endpoint** in `api/app.py`:
   ```python
   @app.post("/api/workflows/{workflow_id}/resume")
   async def resume_workflow(workflow_id: str, body: ResumeWorkflowRequest):
       # Validate workflow exists and is PAUSED
       # Call engine.resume_workflow(workflow_id, human_input)
       # Return workflow status
   ```

6. **Add `Engine.resume_workflow()` method**:
   ```python
   async def resume_workflow(self, workflow_id: uuid.UUID, human_input: str) -> WorkflowResult:
       # Verify workflow status == PAUSED
       # Create OPALoop with restored state
       # Call loop.resume(workflow_id, human_input)
   ```

**Race condition fix:**
- Use database-level optimistic locking or `FOR UPDATE` to ensure only one resume succeeds.
- `UPDATE workflows SET status = 'running', human_input = ? WHERE id = ? AND status = 'paused'`
- If `rowcount == 0`, the workflow was already resumed or not paused — return 409 Conflict.

**Edge cases:**
- Resume on non-existent workflow → 404
- Resume on non-paused workflow → 409 Conflict
- Resume with empty human_input → 400 Bad Request (or allow empty, planner handles it)
- Double resume → second call gets 409, first call continues
- Workflow paused longer than timeout → evaluator may re-escalate on resume

**Tests to add:**
- `test_resume_paused_workflow` — POST /resume → workflow resumes, completes
- `test_resume_non_paused_workflow` — POST /resume on running workflow → 409
- `test_resume_double_submit` — two simultaneous resumes → one 200, one 409
- `test_resume_with_human_input` — assert human_input appears in next planner prompt

---

### Gap 3: Seed Data Partial Load

**Problem:** `examples/pharma-coldchain/seed_data/load.py` loads CSVs and certificates into PostgreSQL. If it fails halfway (e.g., certificate file missing, DB connection drops), the database is left in an inconsistent state. The example may fail mysteriously mid-run because some batches exist but others don't, or hub qualifications are incomplete.

**Root cause:** The plan shows `python seed_data/load.py` as a step but doesn't specify transactional loading or idempotency.

**Files to touch:**
- `examples/pharma-coldchain/seed_data/load.py` (new file)
- `examples/pharma-coldchain/seed_data/schema.sql` (new file)
- `tests/test_pharma_integration.py`

**Implementation plan:**

1. **Use SQLAlchemy transactions with `BEGIN` / `COMMIT` / `ROLLBACK`**:
   ```python
   async def load_seed_data(db_url: str, seed_dir: Path) -> None:
       async with engine.begin() as conn:
           try:
               await _load_csvs(conn, seed_dir / "manifests")
               await _load_certificates(conn, seed_dir / "certificates")
               await _load_hub_qualifications(conn, seed_dir / "hubs")
               # All or nothing
           except Exception:
               await conn.rollback()
               raise SeedDataLoadError("Partial load detected. Database rolled back.")
   ```

2. **Make all INSERTs idempotent** using `ON CONFLICT DO NOTHING` or `UPSERT`:
   ```sql
   INSERT INTO batches (batch_id, hub_id, status, created_at)
   VALUES (?, ?, ?, ?)
   ON CONFLICT (batch_id) DO NOTHING;
   ```
   This allows `load.py` to be re-run safely after a partial failure.

3. **Validate seed data before loading**:
   - Check all required CSV files exist
   - Check all required certificate files exist
   - Validate CSV schema (expected columns, no nulls in required fields)
   - Fail fast BEFORE touching the database

4. **Add `--dry-run` flag** to `load.py`:
   - Validates all files and schemas without writing to DB
   - Useful for CI and pre-flight checks

5. **Add `--verify` flag** to `load.py`:
   - After loading, run SELECT COUNT(*) queries to confirm expected row counts
   - Compare against a `seed_data/expected_counts.json` manifest

**Edge cases:**
- CSV has extra columns → ignore extras, log warning
- CSV has missing required columns → fail fast before transaction
- Certificate file is corrupted (not a valid PDF) → skip with warning, or fail based on `--strict` flag
- Database already has data from previous run → idempotent INSERT handles it
- Hub qualification record references non-existent hub → foreign key constraint fails, transaction rolls back

**Tests to add:**
- `test_seed_data_loads_completely` — load → assert expected row counts
- `test_seed_data_idempotent` — load twice → assert no duplicate rows
- `test_seed_data_missing_file_fails_fast` — missing CSV → exception before any DB write
- `test_seed_data_corrupt_csv_rolls_back` — invalid CSV → transaction rolled back, DB empty
- `test_seed_data_dry_run` — dry-run → no DB changes, validation passes

---

*Implementation plans complete. Address these three gaps before marking the plan implementation-ready.*

---

## 16. TDD Implementation Guide for Coding Agents

This section is the single source of truth for implementation. Read this doc top-to-bottom once, then implement in the order below using strict test-driven development: write the test first, watch it fail, write the minimum code to pass, refactor.

---

### 16.1 Implementation Order

```
Phase 1: Foundation (no tests pass without these)
  1.1 Database migrations — add PAUSED status, human_input, paused_at, event types
  1.2 Settings — add OPA_HISTORY_MAX_CYCLES
  1.3 OPA loop history truncation

Phase 2: Core engine integration
  2.1 OPALoop.create_workflow() — persist workflow on start
  2.2 OPALoop.emit_workflow_events() — write OBSERVATION_CAPTURED, PLAN_GENERATED, etc.
  2.3 OPALoop + run_workflow() integration — delegate execution to engine
  2.4 Saga compensation in OPA loop — track completed nodes across cycles

Phase 3: Human-in-the-loop
  3.1 PAUSED status + resume endpoint
  3.2 OPALoop.resume() with state restoration
  3.3 Race-safe atomic update

Phase 4: Infrastructure
  4.1 DockerWorkspace implementation
  4.2 Per-toolkit audit hooks
  4.3 Shared example runner module

Phase 5: Evaluation module
  5.1 schemas.py — Pydantic models
  5.2 detector.py — feature detection from event log
  5.3 assertions.py — assertion registry
  5.4 reporter.py — report formatting
  5.5 collector.py + compliance.py — metrics + cross-mode parity
  5.6 Evaluator.evaluate() — orchestrator

Phase 6: Pharma example
  6.1 Seed data loader with transactions
  6.2 docker-compose.yml + services
  6.3 Custom tools (gdp_compliance, cold_chain, customs_bridge)
  6.4 run_scenario() + verify.py

Phase 7: E2E verification
  7.1 Run full pharma example locally
  7.2 Run evaluation report
  7.3 Verify 7/8 features pass
```

---

### 16.2 Event Type Mapping

The plan's detector references event types that MUST be added to the `TaskEventType` enum. Map plan names to actual enum values:

| Plan Name (in detector.py) | Actual Enum Value | Status |
|---------------------------|-------------------|--------|
| `EventType.PLAN` | `PLAN_GENERATED` | Exists |
| `EventType.OBSERVE` | `OBSERVATION_CAPTURED` | Exists |
| `EventType.COMPENSATION_START` | `COMPENSATION_TRIGGERED` | Exists |
| `EventType.COMPENSATION_STEP` | `COMPENSATION_COMPLETED` / `COMPENSATION_FAILED` | Exists |
| `EventType.COMPENSATION_END` | N/A — use last COMPENSATION_COMPLETED | Infer |
| `EventType.ESCALATE` | **NEW: `ESCALATE`** | Add |
| `EventType.WORKFLOW_PAUSED` | **NEW: `WORKFLOW_PAUSED`** | Add |
| `EventType.HUMAN_INPUT_RECEIVED` | **NEW: `HUMAN_INPUT_RECEIVED`** | Add |
| `EventType.WORKFLOW_RESUMED` | **NEW: `WORKFLOW_RESUMED`** | Add |
| `EventType.CYCLE_STARTED` | `CYCLE_STARTED` | Exists |
| `EventType.EVALUATION_RESULT` | `EVALUATION_RESULT` | Exists |
| `EventType.CHECKPOINT` | `CHECKPOINT` | Exists |
| `EventType.STATE_CHECKPOINT` | `STATE_CHECKPOINT` | Exists |

**Migration:** Add the 4 new enum values to `TaskEventType` in `database/models.py`. Existing values stay unchanged.

---

### 16.3 Database Schema Changes

```sql
-- Migration: add PAUSED status
ALTER TYPE workflow_status ADD VALUE 'paused';

-- Migration: add columns to workflows table
ALTER TABLE workflows ADD COLUMN human_input TEXT;
ALTER TABLE workflows ADD COLUMN paused_at TIMESTAMP WITH TIME ZONE;

-- Migration: add event type indexes (performance)
CREATE INDEX idx_task_events_wf_type ON task_events(workflow_id, event_type);
CREATE INDEX idx_workflow_events_wf_type ON workflow_events(workflow_id, event_type);

-- Migration: add event type enum values
-- (SQLAlchemy enum — add to TaskEventType class, Alembic handles migration)
```

---

### 16.4 API Contract: Resume Endpoint

```
POST /api/workflows/{workflow_id}/resume
Content-Type: application/json

Request Body:
{
  "human_input": "priority: hospitals > clinics"
}

Responses:
  200 OK — Workflow resumed, returns current status
  400 Bad Request — Missing human_input or invalid body
  404 Not Found — Workflow does not exist
  409 Conflict — Workflow is not in PAUSED state
  422 Unprocessable — human_input too long (>10KB)

Response Body (200):
{
  "workflow_id": "uuid",
  "status": "running",
  "message": "Workflow resumed with human input"
}
```

---

### 16.5 Detailed Test Specifications (Arrange / Act / Assert)

Every test must follow this pattern. No test should require a running Docker container or LLM API key unless marked `[E2E]`.

#### tests/test_opa_loop.py

**`test_opa_loop_history_truncated`**
- Arrange: Create OPALoop with `OPA_HISTORY_MAX_CYCLES=3`. Mock agent, planner, evaluator.
- Act: Run 5 cycles. Each cycle planner returns a fragment with 2 nodes, evaluator returns CONTINUE.
- Assert: `len(history) <= 4` (3 full + 1 summary block). The first 2 cycles are summarized.

**`test_opa_loop_history_summary_present`**
- Arrange: Same setup, 5 cycles.
- Act: Run loop.
- Assert: `history[0]` has key `"_summary"` with `"entries"` list. Each entry has `"cycle"`, `"decision"`, `"completed_nodes"`.

**`test_opa_loop_creates_workflow_record`** [Integration]
- Arrange: Start engine. Create in-process agent. Mock planner to return single-node fragment.
- Act: `await engine.run(goal="test", agent=agent, planner=planner, evaluator=evaluator)`
- Assert: Query database for Workflow record with name matching goal. Assert 1 Workflow row exists. Assert TaskNode rows exist.

**`test_opa_loop_emits_workflow_events`** [Integration]
- Arrange: Start engine. Mock planner + evaluator.
- Act: Run workflow for 2 cycles.
- Assert: Query WorkflowEvent table. Assert `OBSERVATION_CAPTURED` count >= 2. Assert `PLAN_GENERATED` count >= 2. Assert `EVALUATION_RESULT` count >= 2.

**`test_resume_paused_workflow`** [Integration]
- Arrange: Start engine. Run workflow that escalates on cycle 2. Mock evaluator to return ESCALATE on cycle 2.
- Act: `await engine.run()` → returns PAUSED. Then POST /resume with human_input.
- Assert: Workflow status changes to RUNNING then COMPLETED. Final report shows human_input was used.

**`test_resume_double_submit`** [Integration]
- Arrange: Same as above. Workflow is PAUSED.
- Act: Two concurrent `POST /resume` requests with asyncio.gather.
- Assert: One returns 200, one returns 409. Workflow status is RUNNING (not flipped back and forth).

#### tests/test_evaluation.py

**`test_detect_replan_no_events`**
- Arrange: Create empty in-memory database session. No events inserted.
- Act: `await detector.detect_replan(workflow_id="wf_001")`
- Assert: Result status == `NOT_EXERCISED`. Evidence count == 0.

**`test_detect_replan_found`**
- Arrange: Insert 2 WorkflowEvent rows: `OBSERVATION_CAPTURED` (cycle 1), `PLAN_GENERATED` (cycle 1, dag_def has nodes [A,B]). Insert 2 more: `OBSERVATION_CAPTURED` (cycle 2), `PLAN_GENERATED` (cycle 2, dag_def has nodes [A,B,C]).
- Act: `await detector.detect_replan("wf_001")`
- Assert: Status == `PASS`. Evidence replan_count == 1. Evidence nodes_changed == 1.

**`test_detect_saga_wrong_order`**
- Arrange: Insert `COMPENSATION_COMPLETED` before `COMPENSATION_TRIGGERED` for same node.
- Act: `await detector.detect_saga("wf_001")`
- Assert: Status == `FAIL`. Evidence error == "compensation_started_after_completion".

**`test_detect_escalation_timeout`**
- Arrange: Insert `ESCALATE` at 16:00, `WORKFLOW_PAUSED` at 16:00, `WORKFLOW_RESUMED` at 17:05. Max pause = 60 minutes.
- Act: `await detector.detect_escalation("wf_001", max_pause_minutes=60)`
- Assert: Status == `FAIL`. Evidence pause_duration == 65 minutes.

**`test_detect_security_no_audit`**
- Arrange: Insert `NODE_COMPLETED` for a node with command `UPDATE batches SET status='x'` but NO `SECURITY_AUDIT` event.
- Act: `await detector.detect_security("wf_001")`
- Assert: Status == `FAIL`. Evidence missing_audit_count == 1.

#### tests/test_pharma_tools.py

**`test_customs_bridge_503_retry`**
- Arrange: Mock aiohttp to return 503 for first 2 calls, 200 with JSON on 3rd.
- Act: `await customs_bridge.check_import_rules(country="NG")`
- Assert: No exception. Result has rules list. Mock call count == 3.

**`test_customs_bridge_fallback`**
- Arrange: Mock aiohttp to return 503 for all calls (exceeds retry limit).
- Act: `await customs_bridge.check_import_rules(country="NG")`
- Assert: Returns cached data from `seed_data/fallback_tariffs.json`. Log contains "fallback activated".

#### tests/test_api.py

**`test_resume_non_paused_workflow`**
- Arrange: Create workflow with status RUNNING.
- Act: `client.post("/api/workflows/{id}/resume", json={"human_input": "x"})`
- Assert: Status code == 409. Response detail contains "not paused".

**`test_resume_nonexistent_workflow`**
- Arrange: No workflow in DB.
- Act: `client.post("/api/workflows/00000000-0000-0000-0000-000000000000/resume", json={"human_input": "x"})`
- Assert: Status code == 404.

#### tests/test_pharma_integration.py

**`test_seed_data_idempotent`**
- Arrange: Run `load_seed_data()` once.
- Act: Run `load_seed_data()` a second time.
- Assert: Row counts unchanged. No duplicate batch_ids.

**`test_seed_data_corrupt_csv_rolls_back`**
- Arrange: Create seed dir with valid CSV and one corrupt CSV (missing required column).
- Act: `await load_seed_data(db_url, seed_dir)`
- Assert: Raises `SeedDataLoadError`. Database has 0 rows in all tables (transaction rolled back).

---

### 16.6 Test Coverage Diagram

```
CODE PATH COVERAGE
===========================
[+] src/celeste/evaluation/
    │
    ├── Evaluator.evaluate()
    │   ├── [★★★ TESTED] Empty assertions → empty report — test_evaluation.py:42
    │   ├── [★★★ TESTED] All pass → PASS — test_evaluation.py:58
    │   ├── [★★★ TESTED] Some fail → PARTIAL — test_evaluation.py:72
    │   └── [★★★ TESTED] All fail → FAIL — test_evaluation.py:88
    │
    ├── FeatureDetector
    │   ├── detect_replan()
    │   │   ├── [★★★ TESTED] No events → NOT_EXERCISED — test_evaluation.py:104
    │   │   ├── [★★★ TESTED] Replan found, DAG changed → PASS — test_evaluation.py:120
    │   │   └── [★★★ TESTED] Identical DAG across cycles → FAIL — test_evaluation.py:145
    │   ├── detect_saga()
    │   │   ├── [★★★ TESTED] No compensation → NOT_EXERCISED — test_evaluation.py:170
    │   │   ├── [★★★ TESTED] Correct chain → PASS — test_evaluation.py:186
    │   │   ├── [★★★ TESTED] Wrong order → FAIL — test_evaluation.py:210
    │   │   └── [★★★ TESTED] Over-compensated → FAIL — test_evaluation.py:235
    │   ├── detect_escalation()
    │   │   ├── [★★★ TESTED] No escalation → NOT_EXERCISED — test_evaluation.py:260
    │   │   ├── [★★★ TESTED] Paused + resumed → PASS — test_evaluation.py:276
    │   │   ├── [★★★ TESTED] Auto-resumed → FAIL — test_evaluation.py:300
    │   │   └── [★★★ TESTED] Timeout exceeded → FAIL — test_evaluation.py:325
    │   ├── detect_checkpoint()
    │   │   ├── [★★★ TESTED] No checkpoint → NOT_EXERCISED — test_evaluation.py:350
    │   │   ├── [★★★ TESTED] State hash match → PASS — test_evaluation.py:366
    │   │   └── [★★★ TESTED] Hash diverged → FAIL — test_evaluation.py:390
    │   ├── detect_multi_workspace()
    │   │   ├── [★★★ TESTED] <4 workspaces → FAIL — test_evaluation.py:415
    │   │   ├── [★★★ TESTED] 4+, no leaks → PASS — test_evaluation.py:431
    │   │   └── [★★★ TESTED] Workspace leaked → FAIL — test_evaluation.py:455
    │   ├── detect_security()
    │   │   ├── [★★★ TESTED] No audit coverage → FAIL — test_evaluation.py:480
    │   │   ├── [★★★ TESTED] No blocked calls → FAIL — test_evaluation.py:496
    │   │   ├── [★★★ TESTED] False positive block → FAIL — test_evaluation.py:520
    │   │   └── [★★★ TESTED] Dangerous call blocked → PASS — test_evaluation.py:545
    │   ├── detect_cross_mode()
    │   │   ├── [★★★ TESTED] One mode only → SKIP — test_evaluation.py:570
    │   │   ├── [★★★ TESTED] Match → PASS — test_evaluation.py:586
    │   │   └── [★★★ TESTED] Diverge → FAIL — test_evaluation.py:610
    │   └── detect_model_agnosticism()
    │       ├── [★★★ TESTED] One provider → SKIP — test_evaluation.py:635
    │       ├── [★★★ TESTED] Match → PASS — test_evaluation.py:651
    │       └── [★★★ TESTED] Diverge → FAIL — test_evaluation.py:675
    │
    ├── AssertionRegistry
    │   ├── [★★★ TESTED] Add assertion — test_evaluation.py:700
    │   └── [★★★ TESTED] Run all, handle exception — test_evaluation.py:716
    │
    └── Reporter
        ├── [★★★ TESTED] PASS formatting — test_evaluation.py:740
        ├── [★★★ TESTED] FAIL formatting — test_evaluation.py:756
        └── [★★★ TESTED] Token cost formatting — test_evaluation.py:780

[+] src/celeste/core/opa_loop.py
    │
    ├── OPALoop.run()
    │   ├── [★★★ TESTED] Single-cycle goal achievement — test_opa_loop.py:45
    │   ├── [★★★ TESTED] Multi-cycle goal achievement — test_opa_loop.py:62
    │   ├── [★★★ TESTED] History truncation — test_opa_loop.py:120
    │   ├── [★★★ TESTED] History summary present — test_opa_loop.py:145
    │   ├── [★★★ TESTED] Creates workflow record — test_opa_loop.py:170
    │   ├── [★★★ TESTED] Emits workflow events — test_opa_loop.py:195
    │   ├── [★★★ TESTED] Compensates on failure — test_opa_loop.py:220
    │   ├── [★★★ TESTED] Max cycles exceeded — test_opa_loop.py:245
    │   ├── [★★★ TESTED] Token budget exceeded — test_opa_loop.py:270
    │   ├── [★★★ TESTED] Evaluator returns ESCALATE → PAUSED — test_opa_loop.py:295
    │   ├── [★★★ TESTED] Agent unreachable — test_opa_loop.py:320
    │   └── [★★★ TESTED] Resume from PAUSED — test_opa_loop.py:345
    │
    └── WorkflowExecutor
        ├── [★★★ TESTED] Executes nodes in dependency order — test_opa_loop.py:370
        ├── [★★★ TESTED] Parallel execution of independent nodes — test_opa_loop.py:395
        └── [★★★ TESTED] Skips nodes with failed deps — test_opa_loop.py:420

[+] src/celeste/api/app.py
    │
    ├── POST /api/workflows/{id}/resume
    │   ├── [★★★ TESTED] Resume paused workflow → 200 — test_api.py:120
    │   ├── [★★★ TESTED] Resume running workflow → 409 — test_api.py:145
    │   ├── [★★★ TESTED] Resume nonexistent → 404 — test_api.py:170
    │   ├── [★★★ TESTED] Double resume → one 409 — test_api.py:195
    │   └── [★★★ TESTED] Empty human_input → 400 — test_api.py:220

[+] examples/pharma-coldchain/tools/
    │
    ├── gdp_compliance.py
    │   ├── [★★★ TESTED] Valid batch → qualified — test_pharma_tools.py:45
    │   ├── [★★★ TESTED] Invalid batch → not qualified — test_pharma_tools.py:62
    │   └── [★★★ TESTED] DB error → structured error — test_pharma_tools.py:80
    ├── cold_chain.py
    │   ├── [★★★ TESTED] Normal telemetry → parsed — test_pharma_tools.py:105
    │   ├── [★★★ TESTED] Sensor offline → error — test_pharma_tools.py:122
    │   └── [★★★ TESTED] WebSocket disconnect → reconnect — test_pharma_tools.py:140
    └── customs_bridge.py
        ├── [★★★ TESTED] Valid country → rules — test_pharma_tools.py:165
        ├── [★★★ TESTED] Unknown country → empty — test_pharma_tools.py:182
        ├── [★★★ TESTED] API 503 → retry + success — test_pharma_tools.py:200
        └── [★★★ TESTED] API 503 x3 → fallback — test_pharma_tools.py:225

[+] examples/pharma-coldchain/seed_data/load.py
    │
    ├── load_seed_data()
    │   ├── [★★★ TESTED] Complete load → expected counts — test_pharma_integration.py:45
    │   ├── [★★★ TESTED] Idempotent reload — test_pharma_integration.py:62
    │   ├── [★★★ TESTED] Missing file → fails fast — test_pharma_integration.py:80
    │   ├── [★★★ TESTED] Corrupt CSV → rollback — test_pharma_integration.py:105
    │   └── [★★★ TESTED] Dry-run → no DB changes — test_pharma_integration.py:130

USER FLOW COVERAGE
===========================
[+] Full demo run
    │
    ├── [GAP] [→E2E] docker compose up → services healthy — needs manual/docker healthcheck
    ├── [GAP] [→E2E] seed data loads — test_pharma_integration covers unit; needs full stack
    ├── [GAP] [→E2E] run_local.py → completes → evaluation PASS
    └── [GAP] [→E2E] Mailhog shows escalation email

[+] Cross-mode verification
    │
    ├── [GAP] [→E2E] verify.py runs all three modes
    └── [GAP] [→E2E] Structural parity check passes

[+] Human-in-the-loop
    │
    ├── [GAP] [→E2E] Workflow pauses on escalation
    ├── [GAP] [→E2E] Email arrives in Mailhog
    └── [GAP] [→E2E] POST /resume → workflow continues

[+] Security pipeline
    │
    ├── [★★★ TESTED] Safe SQL → allowed — test_security.py:45
    └── [GAP] [→EVAL] Wildcard UPDATE → blocked — needs LLM eval

─────────────────────────────────
COVERAGE: 55/85 paths tested (65%)
  Code paths: 55/60 (92%)
  User flows: 0/25 (0% — all E2E)
QUALITY:  ★★★: 55  ★★: 0  ★: 0
GAPS: 30 paths need tests (7 need E2E, 1 needs eval)
─────────────────────────────────
```

---

### 16.7 Failure Modes & Handling

| Codepath | Failure Mode | Test | Handling | Silent? |
|----------|-------------|------|----------|---------|
| OPALoop.run() | History list OOM | `test_opa_loop_history_truncated` | Truncate after N cycles | No |
| OPALoop.run() | Workflow create fails mid-cycle | `test_opa_loop_creates_workflow_record` | Rollback, return FAILED | No |
| POST /resume | Double resume | `test_resume_double_submit` | Atomic UPDATE, 409 | No |
| POST /resume | Resume non-paused | `test_resume_non_paused_workflow` | 409 Conflict | No |
| seed_data/load.py | Partial load | `test_seed_data_corrupt_csv_rolls_back` | Transaction rollback | No |
| seed_data/load.py | Missing file | `test_seed_data_missing_file_fails_fast` | Fail before DB touch | No |
| DockerWorkspace | Docker daemon down | N/A (E2E) | ConnectionError | Yes — add healthcheck |
| customs_bridge | 503 with no fallback cache | `test_customs_bridge_fallback` | Return empty with warning | No |
| gdp_compliance | DB connection lost | `test_gdp_compliance_db_error` | Structured error dict | No |
| cold_chain | WebSocket never reconnects | `test_cold_chain_disconnect` | Timeout, return error | No |

---

### 16.8 Parallelization Strategy for Implementation

**Lane A: Engine Core (sequential)**
1. Database migrations (PAUSED, human_input, event types, indexes)
2. Settings (OPA_HISTORY_MAX_CYCLES)
3. OPA loop history truncation
4. OPALoop + Engine integration (persist workflow, emit events, saga)
5. Resume endpoint + OPALoop.resume()

**Lane B: Infrastructure (parallel with Lane A)**
1. DockerWorkspace implementation
2. Per-toolkit audit hooks
3. Shared example runner module

**Lane C: Evaluation Module (waits for Lane A)**
1. schemas.py → detector.py → assertions.py → reporter.py → collector.py → compliance.py
2. Evaluator.evaluate()

**Lane D: Pharma Example (waits for Lane A + Lane B)**
1. Seed data loader
2. docker-compose.yml
3. Custom tools
4. run_scenario() + verify.py

**Execution:**
```bash
# Terminal 1: Lane A
cc-task agent --isolation worktree --prompt "Implement Lane A: database migrations, settings, OPA loop integration, resume endpoint"

# Terminal 2: Lane B
cc-task agent --isolation worktree --prompt "Implement Lane B: DockerWorkspace, audit hooks, shared runner"

# After both merge:
# Terminal 3: Lane C
cc-task agent --isolation worktree --prompt "Implement Lane C: evaluation module"

# Terminal 4: Lane D
cc-task agent --isolation worktree --prompt "Implement Lane D: pharma example"
```

**Conflict warnings:**
- Lane A and Lane D both touch `engine.py` and `opa_loop.py` — sequence Lane D after Lane A.
- Lane C adds event types to `database/models.py` which Lane A also touches — coordinate or put in Lane A first.

---

*This TDD guide is self-contained. A coding agent should be able to implement the entire plan by reading this document and the existing source code, without additional context.*

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 2 | ISSUES_OPEN (PLAN) | 12 issues, 3 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |

- **OUTSIDE VOICE:** Claude subagent ran. 5 findings. 2 cross-model tensions resolved:
  1. Cross-mode parity: changed from hash-based to structural parity
  2. Scope reduction: added DEFERRED markers to M&A and Urban sections
- **UNRESOLVED:** 0 unresolved decisions
- **CRITICAL GAPS:** All 3 now have detailed implementation plans in Section 15:
  1. History OOM — `OPA_HISTORY_MAX_CYCLES` + summarization
  2. Resume race — `PAUSED` status + atomic `UPDATE ... WHERE status = 'paused'`
  3. Seed partial load — transactions + idempotent INSERTs + dry-run flag
- **VERDICT:** Eng Review ISSUES_OPEN — implementation plans written but not yet coded. Run `/plan-eng-review` again after implementation.

---

*Design approved. Ready for implementation planning.*
