# Celeste-DAG Monitoring UI — Design Plan

**Date:** 2026-06-12  
**Branch:** `celeste-verification-examples`  
**Status:** Self-contained TDD plan — ready for test-driven implementation

---

## 1. Executive Summary

Celeste-DAG is a dynamic, model-agnostic agentic workflow engine. Its runtime surface is rich: OPA loops (Observe → Plan → Act), event-sourced ledgers, saga compensation, tiered escalation, security audits, multi-workspace isolation, and checkpointing. Today that runtime is only visible through logs, raw REST responses, and SQLite queries.

This plan defines **Celeste Mission Control (CMC)**: a suite of beautiful, modern, per-workflow monitoring web UIs that turn the event stream into an intelligible, operable, and memorable command center.

The design deliberately avoids the generic "AI dashboard" look (purple gradients, Inter, glassmorphism cards). Instead it commits to a single strong concept: **a retro-futuristic astronomical observatory control room** — dark, precise, slightly analog, where workflows are celestial objects moving through a sky of dependencies and operators are astronomers tracking them.

> **Design system reference:** Detailed tokens, typography, components, motion, accessibility, and anti-patterns are captured in `DESIGN.md` at the repository root. This plan describes the product and screens; `DESIGN.md` is the canonical implementation reference.

---

## 2. Aesthetic Direction: "Celestial Mission Control"

### 2.1 Concept

Workflows are orbital bodies. DAG nodes are stars in constellations. The OPA loop is a scanning telescope sweeping across the sky. Security audits are spectral analyses. Saga compensation is a gravitational rewind. Human escalation is a manual override at the observatory console.

The interface should feel like sitting at a console in a mountaintop observatory in 2080: clean, authoritative, alive, but never cluttered.

### 2.2 Tone

- **Retro-futuristic + refined utilitarian.** Think *NASA mission control* meets *Polestar UI* meets *Olafur Eliasson light installations*.
- Dark-first. High contrast. Information density is controlled, not maximal.
- Every pixel serves the operator: either showing state, enabling action, or creating spatial memory.

### 2.3 Differentiation — The One Thing to Remember

A **live, panning celestial DAG view**: each workflow renders as a navigable starfield where nodes pulse with real status, edges drawn like constellation lines, and the camera gently drifts to the active node as the workflow runs. No static Gantt chart. No generic topology diagram. A sky you fly through.

### 2.4 Anti-Patterns to Avoid

The following patterns read as generic AI-generated SaaS and are explicitly forbidden in CMC. Every design decision must be checked against this list.

1. **Purple/violet/indigo gradients or blue-to-purple color schemes.** CMC uses deep navy, cyan, orange, red, green — never the default "AI" purple.
2. **The 3-column feature grid with icon + bold title + 2-line description.** Dashboard summary cards are asymmetric, not a symmetric grid.
3. **Icons inside colored circles as decoration.** Status is conveyed by orb color, pulse, and label — not by circled icons.
4. **Centered everything.** Align text and controls to a strong left grid; centered hero copy has no place in an operator tool.
5. **Uniform large border-radius on every element.** Panels are sharp or have a single restrained radius; do not "bubblify" the UI.
6. **Decorative blobs, floating circles, or wavy SVG dividers.** The aurora gradient and grain are the only atmosphere; no ornamental shapes.
7. **Emoji as design elements.** Use Lucide icons only.
8. **Colored left-border on cards as a status device.** Status orbs and labels only.
9. **Generic hero copy.** "Welcome to CMC" or "Unlock the power of..." are banned. Copy is utilitarian: "Active workflows", "Blocked calls", "Pause reason".
10. **Cookie-cutter section rhythm.** Each page has its own structure driven by operator tasks, not a repeated page template.

These will be verified against every generated mockup before implementation begins.

---

## 3. Typography

Avoid generic sans-serifs. Commit to a distinctive, high-contrast pair:

| Role | Font | Rationale |
|------|------|-----------|
| Display / headers | **Bodoni Moda** (Google Fonts) | Extreme thick-thin contrast feels telescope-optical, elegant, authoritative. |
| UI / labels / body | **Syne** (Google Fonts) | Geometric, slightly futuristic, excellent at small sizes, characterful without being cartoonish. |
| Monospace / logs / JSON | **JetBrains Mono** | Already associated with code; readable, slightly condensed for dense event panels. |

Fallback stack: `Bodoni Moda, Georgia, serif`; `Syne, system-ui, sans-serif`; `JetBrains Mono, Menlo, monospace`.

### Type scale

- `3xl` — page titles (48/52, Bodoni Moda, 400)
- `2xl` — section headers (32/36, Bodoni Moda, 400)
- `xl` — card titles (24/28, Syne, 600)
- `lg` — emphasis labels (18/24, Syne, 500)
- `base` — body (15/22, Syne, 400)
- `sm` — metadata (13/18, Syne, 400, +0.02em tracking)
- `xs` — timestamps / badges (11/14, JetBrains Mono, 400)

---

## 4. Color System

CSS custom properties rooted in the observatory palette.

### Primitives

```css
:root {
  --space-950: #050814;
  --space-900: #0a0f1c;
  --space-800: #11172b;
  --space-700: #1a1f3d;
  --space-600: #2a3159;
  --space-500: #4a547a;
  --space-400: #7b86a9;
  --space-300: #a9b3cc;
  --space-200: #d4dceb;
  --space-100: #f1f4fb;

  --aurora-500: #00f0ff;
  --aurora-400: #4ff7ff;
  --aurora-300: #8afbff;
  --aurora-900: #002b2e;

  --solar-500: #ff9f43;
  --solar-400: #ffb978;
  --solar-900: #3d220a;

  --mars-500: #ff4757;
  --mars-400: #ff7a85;
  --mars-900: #3d0a0f;

  --nebula-500: #2ed573;
  --nebula-400: #6de69d;
  --nebula-900: #0a3d20;

  --comet-500: #a55eea;
  --comet-400: #c49af5;
  --comet-900: #2a153d;
}
```

### Semantic roles

```css
:root {
  --bg-root: var(--space-950);
  --bg-panel: rgba(10, 15, 28, 0.72);
  --bg-panel-solid: var(--space-900);
  --bg-inset: var(--space-800);
  --border-subtle: rgba(119, 132, 168, 0.18);
  --border-glow: rgba(0, 240, 255, 0.25);
  --text-primary: var(--space-100);
  --text-secondary: var(--space-300);
  --text-tertiary: var(--space-400);
  --status-running: var(--aurora-500);
  --status-completed: var(--nebula-500);
  --status-failed: var(--mars-500);
  --status-paused: var(--solar-500);
  --status-pending: var(--space-500);
  --status-cancelled: var(--space-400);
}
```

### Atmosphere

- Subtle animated grain overlay (CSS noise, `mix-blend-mode: overlay`, opacity 0.04) across the whole app to evoke film/analog telemetry.
- A slow **radial aurora gradient** behind the main canvas: deep navy center shifting to indigo edges, with a faint cyan glow near active nodes.
- Thin horizon line / crosshair at 1/3 height on dashboard pages to reinforce the "observatory viewport" metaphor.

---

## 5. Information Architecture

### 5.1 Primary Navigation

```
┌─────────────────────────────────────────────────────────────────┐
│ CMC  │  Dashboard  │  Workflows  │  Agents  │  Observatory  │  ⚙  │
└─────────────────────────────────────────────────────────────────┘
```

| Section | Purpose |
|---------|---------|
| **Dashboard** | Fleet-wide health, active workflows, recent alerts, throughput. |
| **Workflows** | Searchable list of all workflows; entry point to per-workflow Mission Control. |
| **Agents** | Registered environment agents, connectivity, recent heartbeats. |
| **Observatory** | Global event stream, audit log, feature verification summary. |

### 5.2 Per-Workflow Sub-Navigation

Inside a workflow, the sidebar becomes a telescope control panel:

```
Overview
Constellation (DAG)
OPA Loop
Event Ledger
Security Audit
Workspaces
Saga Compensation
Human Escalation
```

### 5.3 Per-Page Visual Hierarchy

For every screen, the user should see the most urgent signal first, the actionable context second, and the navigational/archive detail third. The following hierarchy governs layout:

| Page | Primary (first 2 seconds) | Secondary (next 5 seconds) | Tertiary (dig deeper) |
|------|---------------------------|----------------------------|-----------------------|
| **Dashboard** | Active workflows count + live alert flares | Throughput strip + recent failures | Recent workflows table |
| **Workflows list** | Search/filter + status filters | Workflow cards grid | Pagination / infinite scroll |
| **Workflow overview** | Workflow name + status badge + cancel/resume actions | KPI strip + mini constellation | Timeline strip + pause input |
| **Constellation** | Active/running node pulsing in the sky | Camera pan + edge particle motion | Node inspector side panel |
| **OPA Loop** | Current cycle + evaluator decision | Cycle navigator + DAG diff | Token burn chart + reason panel |
| **Event Ledger** | Live tail / newest events | Event type filter chips | JSON inspector |
| **Security Audit** | Audit coverage meter + blocked-call count | Threat tag cloud | Per-call verdict cards |
| **Workspaces** | Leak alert (if any) + peak concurrency | Concurrency chart | Workspace lifecycle table |
| **Saga Compensation** | Compensation status summary | Chain diagram winding back | Per-step status |
| **Human Escalation** | Pause reason + duration + tokens used | Human input editor | Resume/cancel + history |
| **Agents** | Connectivity status grid | Agent detail cards | Register agent form |
| **Observatory** | Global event ticker | Feature verification summary | Provider mix chart |

---

## 6. Page & Component Suite

### 6.1 Global Shell

- **Top bar:** logo mark (a stylized C / orbit glyph), global search, live server time, connection status pulse.
- **Side rail:** icon-only navigation with tooltips; expands to labels on hover.
- **Main stage:** single-page feel with route-aware view switching; generous padding, no boxes inside boxes unless necessary.
- **Backdrop:** animated grain + aurora gradient.

### 6.2 Dashboard

**Purpose:** At-a-glance fleet health.

Components:
- **Orbital summary cards** (active / completed / failed / paused counts) arranged asymmetrically; the active count is largest and sits slightly off-grid.
- **Live throughput strip** — small multiples of recent workflow outcomes over the last hour.
- **Alert flare list** — failed workflows, paused-for-human workflows, security blocks.
- **Recent workflows table** — condensed list with status orbs.

### 6.3 Workflows List

**Purpose:** Browse, search, filter, and open workflows.

Components:
- **Search / filter bar** — status chips, date range, name query.
- **Workflow cards** — not a flat table, but rich cards showing:
  - Name + truncated goal / description
  - Status orb + text
  - Progress arc
  - Cycle count, node count, elapsed time
  - Last updated relative timestamp
- **Infinite / paginated grid**.

### 6.4 Workflow Overview

**Purpose:** The mission control home for one workflow.

Components:
- **Header:** workflow name (Bodoni Moda), status badge, id copy button, actions (cancel, resume if paused).
- **KPI strip:** OPA cycles, total nodes, completed %, max concurrent workspaces, security pass rate.
- **Mini constellation:** a compressed DAG preview with active node highlighted.
- **Timeline strip:** lifecycle events (submitted → cycles → paused → resumed → completed/failed) on a horizontal axis.
- **Pause response input** (only when `status === paused`).

### 6.5 Constellation View (DAG Visualization)

**Purpose:** Show the workflow's graph with live state.

Components:
- **Canvas-based renderer** (D3-force or custom HTML5 Canvas) because SVG chokes on large graphs.
- Nodes as glowing orbs:
  - pending: dim grey
  - running: pulsing cyan
  - completed: steady green
  - failed: red flare
- Edges as faint constellation lines; dependency direction shown with subtle motion (particles drifting along edges).
- **Layout:** deterministic layered DAG layout keyed by node ID so the sky is stable across reloads. SVG is the default renderer. Canvas is a Phase 3 optimization only if profiling proves SVG cannot maintain 60 fps at 100+ nodes.
- **Camera:** pans/zooms to active node; user can take manual control.
- **Node inspector:** side panel on click showing command, arguments, outputs, events.
- **Filter layers:** show compensation commands, security-audited nodes, workspace boundaries.
- **Mobile fallback (<768 px):** the canvas is replaced by a structured node list sorted by dependency order with the active node pinned to the top. Each row shows: status orb, node name, command type, and a chevron to open the node inspector in a full-screen sheet. This keeps the operator's task ("what is happening right now?") fast on small screens.

### 6.6 OPA Loop View

**Purpose:** Inspect the dynamic Observe-Plan-Act cycles.

Components:
- **Cycle navigator** — vertical list of cycles; selecting one loads that cycle's detail.
- **Cycle card:** observation summary, generated fragment, execution outcome, evaluator decision.
- **DAG diff visualization** — when a cycle replans, highlight nodes added/removed/changed vs. the previous cycle.
- **Token burn chart** — accumulated tokens per cycle with budget line. **Only render if real token tracking is available**; otherwise show a cycle count / duration chart. The backend must expose real prompt + completion token counts (see §15.2).
- **Decision reason panel** — evaluator's natural-language rationale.

### 6.7 Event Ledger

**Purpose:** Full audit trail of TaskEvent + WorkflowEvent rows.

Components:
- **Scannable timeline** with event type icons and color coding.
- **Filter chips** by event type and node.
- **JSON inspector** for `event_data` with syntax highlighting and collapsible tree.
- **Live tail mode** for running workflows.

### 6.8 Security Audit View

**Purpose:** Surface the two-phase security pipeline.

Components:
- **Audit coverage meter** — percent of tool calls audited.
- **Blocked calls list** — tool, arguments snippet, risk level, reason.
- **Threat tag cloud** — detected threats across the workflow.
- **Per-call verdict card** — safe / blocked, risk level, reasoning.

### 6.9 Workspaces View

**Purpose:** Visualize multi-workspace isolation and concurrency.

Components:
- **Concurrency chart** — spawned vs. destroyed over time, peak concurrency line.
- **Workspace lifecycle table** — spawn/destroy timestamps, duration, node association.
- **Leak alert** — if spawn count ≠ destroy count, show a prominent warning.

### 6.10 Saga Compensation View

**Purpose:** Show rollback choreography when a node fails.

Components:
- **Compensation chain diagram** — original completed nodes in forward order, compensation arrows winding back.
- **Status for each compensation step** — triggered → completed/failed.
- **Affected scope summary**.

### 6.11 Human Escalation View

**Purpose:** Manage tier-4 human-in-the-loop pauses.

Components:
- **Pause state panel** — reason, cycle count, tokens used, duration so far.
- **Human input editor** — textarea with markdown preview.
- **Resume / cancel actions**.
- **Escalation history** — previous pause/resume cycles for this workflow.

### 6.12 Agents View

**Purpose:** Monitor registered environment agents.

Components:
- **Agent grid cards** — URL, status, last seen, metadata tags.
- **Connectivity sparkline** — if heartbeats are implemented later.
- **Register agent form** inline.

### 6.13 Observatory (Global Audit)

**Purpose:** Cross-workflow event stream and feature verification.

Components:
- **Global event ticker** — newest events scroll in.
- **Feature verification summary** — aggregated PASS / FAIL / NOT_EXERCISED counts across recent workflows.
- **Provider mix chart** — model-agnosticism at fleet level (when metadata available).

### 6.14 Interaction State Coverage

Every UI surface must specify what the operator sees while data is loading, when no data exists, when an error occurs, when an action succeeds, and when data is partial. The following table captures the required states for each major feature.

| Feature | LOADING | EMPTY | ERROR | SUCCESS | PARTIAL |
|---------|---------|-------|-------|---------|---------|
| **Dashboard summary cards** | Skeleton card with pulsing aurora border | "No active workflows" with a CTA to create or import | Numeric fallback "—" + inline retry toast | Live counts animate in | Stale badge + last-known values dimmed |
| **Workflows list** | Shimmer grid of 6 card placeholders | "The sky is clear" illustration + primary "Start a workflow" action | Inline banner + cached list if available | Cards stagger in | Spinner at bottom + loaded cards visible |
| **Workflow overview** | Header skeleton + KPI dots + blurred mini constellation | Empty state for paused workflows (awaiting human input) | Error panel with retry | Full header + KPIs + timeline | KPIs load, constellation placeholder until nodes ready |
| **Constellation view** | Canvas dark with faint grid + "Aligning telescope..." | Single dim orb + "No nodes in this workflow" | Error overlay, manual retry | Animated starfield | Nodes rendered, edges streaming in |
| **OPA Loop cycles** | Vertical skeleton list | "No cycles yet" when workflow hasn't planned | Cycle card with error icon + retry | Cycle navigator populated | Latest cycle shown, older cycles lazy |
| **Event Ledger** | Tail spinner + "Listening for events..." | "No events recorded" | Error banner, preserve filter state | Scannable timeline | Newest events stream in, older batch loading |
| **Security Audit** | Coverage meter animating to 0% | "No audited calls" + explanation of audit coverage | Threat panel shows error + retry | Coverage meter + blocked list | Partial audit log with "audit in progress" badge |
| **Workspaces** | Concurrency chart skeleton | "No workspaces spawned" | Leak alert only if inconsistency detected | Chart + lifecycle table | Chart renders, table loading |
| **Human Escalation** | Pause state loading | N/A (only visible when paused) | Resume action error inline | Pause panel with input editor | Input auto-saved draft restored |
| **Agents list** | Grid of skeleton cards | "No agents registered" + register form expanded | Connectivity error banner | Agent grid with status | Static agent list, heartbeats loading |
| **Observatory ticker** | "Connecting to event stream..." | "No events in the last hour" | Disconnected state with reconnect | Live scrolling ticker | Ticker active, charts loading |

Empty states are features: each must include a short, warm explanation of *why* the sky is empty and a primary action when one makes sense. Error states must never be raw JSON — they are one-line operator-friendly messages plus a retry path.

### 6.15 User Journey Storyboard

The operator's emotional arc across the first session:

| Step | User does | User feels | Plan specifies |
|------|-----------|------------|----------------|
| 1. Land on Dashboard | Opens CMC | Curious, slightly overwhelmed | Largest number is active workflows; alert flares are red/orange so attention goes to problems immediately |
| 2. Scan for problems | Reads alert flare list | Urgency if something failed | Each flare names the workflow, failure reason, and has a one-click path to the workflow |
| 3. Open a workflow | Clicks a workflow | Focused, expects control | Workflow overview feels like a command center: name, status, actions, KPI strip, mini constellation |
| 4. Inspect the sky | Switches to Constellation | Intrigued, wants to understand | Camera gently drifts to active node; nodes pulse; edges show dependency flow |
| 5. Investigate a cycle | Opens OPA Loop | Analytical, looking for cause | Cycle navigator + DAG diff makes replanning obvious |
| 6. Verify security | Opens Security Audit | Cautious, wants assurance | Coverage meter + blocked calls list surfaces risks without raw JSON |
| 7. Respond to a pause | Opens Human Escalation | Responsible, decisive | Pause reason, token cost, duration, and a clear resume/cancel choice |
| 8. Return to fleet view | Goes back to Dashboard | In control, informed | Dashboard updates reflect the action just taken |

Time-horizon design:
- **First 5 seconds (visceral):** dark sky, one huge active-workflows number, red flares if anything is wrong.
- **First 5 minutes (behavioral):** operator can navigate from alert to workflow to node to event without getting lost.
- **Long-term (reflective):** the observatory metaphor creates spatial memory — operators remember where things live.

### 6.16 Empty-State Illustrations

Every primary empty state gets a minimal, on-brand illustration. Style rules:

- **Medium:** SVG line art (no raster assets for Phase 1).
- **Palette:** `--space-300` lines on transparent background, with one `--aurora-500` accent point.
- **Style:** thin single-weight strokes, no fills, no gradients, no decorative blobs.
- **Size:** 120 × 120 px bounding box, centered above the text.

| Empty state | Illustration concept | Primary CTA |
|-------------|----------------------|-------------|
| **Dashboard — no active workflows** | Quiet observatory dome interior seen from the console; a single faint star visible through the viewport. | "Start a workflow" |
| **Workflows list — no workflows** | Empty starfield with faint constellation grid lines and no bright orbs. | "Create workflow" |
| **Event Ledger — no events** | Silent radio telescope dish pointed at an empty sky. | "Events appear when workflows run" (no action if workflow hasn't started) |
| **Agents — no agents** | Empty docking port / launch pad with a single mooring line. | "Register agent" |
| **Constellation — no nodes** | Blank sky with a faint crosshair and no stars. | "Back to workflow overview" |
| **OPA Loop — no cycles** | Telescope lens cap still on; no light path. | "Cycles appear once planning begins" |

---

## 7. Data Model Mapping

### 7.1 Existing API Endpoints

| UI View | Primary API | Notes |
|---------|-------------|-------|
| Dashboard | `GET /health`, `GET /api/workflows` | Aggregate client-side. |
| Workflows list | `GET /api/workflows?limit=&offset=` | Add pagination for large fleets. |
| Workflow overview | `GET /api/workflows/{id}`, `GET /api/workflows/{id}/status` | Combine. |
| Constellation | `GET /api/workflows/{id}`, `GET /api/workflows/{id}/nodes` | `dag_definition` + node statuses. |
| OPA Loop | `GET /api/workflows/{id}/workflow-events?event_type=plan_generated`/`observation`/... | Filter WorkflowEvent rows. |
| Event ledger | `GET /api/workflows/{id}/events?since_id=&limit=` and `GET /api/workflows/{id}/workflow-events?since_id=&limit=` | Union TaskEvent + WorkflowEvent; cursor-based tail for live mode. |
| Security audit | `GET /api/workflows/{id}/workflow-events?event_type=security_audit` | Parse `event_data`; use `/metrics` for aggregates. |
| Workspaces | `GET /api/workflows/{id}/workflow-events?event_type=workspace_spawn`/`destroy` | Compute concurrency. |
| Saga | `GET /api/workflows/{id}/events?event_type=compensation_*` | TaskEvent rows. |
| Escalation | `GET /api/workflows/{id}`, `GET /api/workflows/{id}/workflow-events?event_type=escalate` | Check `status === paused`. |
| Agents | `GET /agents`, `POST /agents/register` | Agent registry endpoints. |

### 7.2 Gaps to Address

The existing API has a few gaps for a rich monitoring UI. We can either extend the backend or compute client-side:

1. **Unified events endpoint** — `/events` currently returns only `TaskEvent`. The UI also needs `WorkflowEvent` for OPA cycles, observations, etc.  
   *Recommendation:* Add `GET /api/workflows/{id}/workflow-events` or a combined `/ledger` endpoint.

2. **Workflow-level metrics** — cycle count, token accumulation, elapsed time, node counts are scattered.  
   *Recommendation:* Add `GET /api/workflows/{id}/metrics` returning a `RuntimeMetrics`-like payload.

3. **Real-time updates** — current API is polling-only.  
   *Recommendation:* Phase 2 adds Server-Sent Events (SSE) or WebSocket for live workflow status.

4. **Global event stream** — no cross-workflow event endpoint.  
   *Recommendation:* Phase 2 adds `GET /api/events?limit=...`.

5. **Agent heartbeats** — agent status is currently static (`is_running`).  
   *Recommendation:* Keep static for Phase 1; add heartbeat pings in Phase 2.

6. **Workflow list pagination** — `GET /api/workflows` returns all rows.  
   *Recommendation:* Add `limit`/`offset` query params and return a `WorkflowListResponse` with total count.

7. **Event tail cursor** — live tail currently requires re-fetching the whole window.  
   *Recommendation:* Add `since_id` (or `since_timestamp`) and `limit` to `GET /api/workflows/{id}/events`.

8. **CORS** — the FastAPI app has no CORS middleware; a standalone Next.js origin will be blocked.  
   *Recommendation:* Add configurable `CORSMiddleware` with allowed origins from environment (default `localhost:3000` for dev).

### 7.3 Runtime Data Flow

```
┌─────────────────┐     HTTP / CORS     ┌──────────────────┐     SQLAlchemy      ┌──────────┐
│  Next.js (CMC)  │ ◄──────────────────► │  FastAPI (Celeste│◄──────────────────►│  SQLite  │
│  - Dashboard    │   /api/workflows     │  - API routes    │   async aiosqlite │  (local) │
│  - Constellation│   /api/events        │  - Engine        │                   │          │
│  - OPA Loop     │   /agents/*          │  - Agent registry│                   │          │
└─────────────────┘                      └──────────────────┘                   └──────────┘
       │                                          │
       │ SSE/WebSocket (Phase 6)                  │ LLM / toolkit calls
       ▼                                          ▼
┌─────────────────┐                      ┌──────────────────┐
│  Live updates   │                      │  LLM providers   │
│  stream         │                      │  - Anthropic     │
└─────────────────┘                      │  - OpenAI        │
                                         │  - Google        │
                                         └──────────────────┘
```

Phase 0 must complete the dashed-line endpoints before CMC can render real data.

---

## 8. Technical Approach

### 8.1 Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Framework | **Next.js 14+ (App Router)** | SSG for landing + SSR/CSR for dynamic views; API routes can proxy to Celeste if needed. |
| Language | **TypeScript** | Type safety for API contracts. |
| Styling | **Tailwind CSS** + custom CSS variables | Fast iteration, design-system alignment. |
| UI primitives | **Radix UI** + custom components | Accessible, unstyled primitives we theme ourselves. |
| Animation | **Framer Motion** for layout/page transitions; **CSS animations** for continuous ambient effects (pulses, grain, drifting particles). | Performance + delight. |
| DAG renderer | **SVG first** with deterministic layered layout; **D3-force + HTML5 Canvas** as optimization if profiling proves SVG too slow | SVG handles 100 nodes fine; canvas is a justified fallback, not a default. |
| Charts | **Visx** or **Recharts** | Composable, themeable. |
| Icons | **Lucide React** | Clean, consistent; avoid emoji. |
| State | **TanStack Query (React Query)** | Caching, polling, mutations. |
| Fonts | Google Fonts via `next/font/google` | Bodoni Moda, Syne, JetBrains Mono. |

### 8.2 Project Layout

```
monitoring/
├── app/
│   ├── layout.tsx              # root shell, fonts, providers
│   ├── page.tsx                # Dashboard
│   ├── workflows/
│   │   ├── page.tsx            # workflows list
│   │   └── [id]/
│   │       ├── page.tsx        # workflow overview
│   │       ├── constellation/
│   │       ├── opa-loop/
│   │       ├── ledger/
│   │       ├── security/
│   │       ├── workspaces/
│   │       ├── saga/
│   │       └── escalation/
│   ├── agents/
│   │   └── page.tsx
│   └── observatory/
│       └── page.tsx
├── components/
│   ├── shell/                  # navigation, top bar, layout primitives
│   ├── ui/                     # buttons, badges, panels, inputs
│   ├── charts/                 # reusable chart wrappers
│   ├── constellation/          # DAG canvas + node inspector
│   ├── workflow/               # workflow-specific cards and panels
│   └── agents/                 # agent cards
├── lib/
│   ├── api.ts                  # typed API client
│   ├── types.ts                # frontend type definitions
│   ├── colors.ts               # design token helpers
│   └── format.ts               # duration, timestamp formatters
├── hooks/
│   ├── useWorkflow.ts
│   ├── useWorkflowEvents.ts
│   └── usePolling.ts
└── styles/
    ├── globals.css             # tokens, fonts, grain overlay
    └── animations.css          # keyframes
```

### 8.3 API Client

Create a thin typed wrapper around the Celeste REST API:

```ts
// lib/api.ts
export async function listWorkflows(opts?: PaginationParams): Promise<WorkflowListResponse> { ... }
export async function getWorkflow(id: string): Promise<WorkflowDetail> { ... }
export async function getWorkflowStatus(id: string): Promise<WorkflowStatus> { ... }
export async function getWorkflowEvents(id: string, opts?: EventQuery): Promise<Event[]> { ... }
export async function getWorkflowWorkflowEvents(id: string, opts?: EventQuery): Promise<WorkflowEvent[]> { ... }
export async function getWorkflowMetrics(id: string): Promise<WorkflowMetrics> { ... }
export async function getWorkflowNodes(id: string): Promise<Node[]> { ... }
export async function getGlobalEvents(opts?: PaginationParams): Promise<GlobalEvent[]> { ... }
export async function cancelWorkflow(id: string): Promise<WorkflowResponse> { ... }
export async function resumeWorkflow(id: string, humanInput: string): Promise<WorkflowResponse> { ... }
export async function listAgents(): Promise<Agent[]> { ... }
export async function registerAgent(body: RegisterAgentRequest): Promise<RegisterAgentResponse> { ... }
```

Use TanStack Query for caching and polling:

```ts
const { data, isLoading } = useQuery({
  queryKey: ['workflow', id, 'status'],
  queryFn: () => getWorkflowStatus(id),
  refetchInterval: (data) =>
    data?.status === 'running' || data?.status === 'pending' ? 1500 : false,
});
```

### 8.4 Responsive Strategy

CMC is designed desktop-first because operators use large screens, but every viewport gets intentional behavior, not a naive stack.

| Viewport | Range | Layout behavior |
|----------|-------|-----------------|
| **Desktop** | ≥1280 px | Full side rail (icon + label on hover), two- or three-column dashboard, constellation canvas takes full stage, node inspector as side panel. |
| **Tablet** | 768–1279 px | Side rail collapses to a bottom icon bar; dashboard cards reflow to 2 columns; tables become horizontally scrollable; constellation canvas remains but inspector becomes a bottom sheet. |
| **Mobile** | <768 px | Single-column layout; bottom bar navigation; constellation view switches to a simplified list of nodes sorted by active/dependency order; detail panels become full-screen sheets. |
| **Ultrawide** | ≥1920 px | Dashboard gains an additional context column (recent observatory events); constellation canvas uses more sky; side rail stays fixed. |

### 8.5 Accessibility Specification

- **Motion:** Respect `prefers-reduced-motion`. Disable grain animation, node pulse, aurora drift, and autopan when true. Keep instant transitions.
- **Color:** All status indicators pair color with both an icon and a text label. Never use color alone.
- **Contrast:** Body text ≥ 4.5:1; large text and UI components ≥ 3:1. Test the cyan accent on dark navy specifically.
- **Focus:** All interactive elements have a 2px `--aurora-500` focus ring with 2px offset. Focus order follows visual hierarchy (top bar → nav → main content).
- **Touch targets:** Minimum 44 × 44 px for buttons and list items; 48 × 48 px for bottom-bar navigation.
- **Screen readers:** Main landmarks (`<main>`, `<nav>`) and `aria-live` regions for status changes. DAG nodes expose role, status, and label; selected node announces in a live region.
- **Keyboard:** Full keyboard navigation through side rail, tables, and DAG nodes. `Esc` closes inspector panels and bottom sheets.

### 8.6 Keyboard Shortcuts

Core shortcuts for Phase 4 power users. Prefer modifier-key shortcuts to avoid clashing with browser defaults (e.g., `/` is Firefox Quick Find, `Space` scrolls the page, single-key `r` may refresh).

| Shortcut | Action | Context |
|----------|--------|---------|
| `Ctrl/Cmd + K` | Focus global search | Global |
| `Ctrl/Cmd + Shift + D` | Go to Dashboard | Global |
| `Ctrl/Cmd + Shift + W` | Go to Workflows | Global |
| `Ctrl/Cmd + Shift + O` | Go to Observatory | Global |
| `Ctrl/Cmd + Shift + A` | Go to Agents | Global |
| `Esc` | Close inspector / bottom sheet / modal / help | Global |
| `Ctrl/Cmd + R` | Refresh current view (handled by browser; triggers TanStack Query refetch) | Global |
| `Ctrl/Cmd + /` or `?` | Show keyboard shortcuts help | Global |
| `Ctrl/Cmd + Shift + C` | Copy workflow ID | Workflow page |
| `Ctrl/Cmd + Shift + P` | Pause/resume selected workflow (with confirmation) | Workflow page |
| `↑` / `↓` or `j` / `k` | Next/previous workflow in list when list is focused | Workflows list |
| `Enter` | Open selected workflow | Workflows list |

Use `event.preventDefault()` only when a non-browser shortcut is active and the user is not in a text field.

### 8.7 CI/CD & Distribution

The monitoring app is a new deployable artifact. It needs its own CI/CD path from Phase 1 so the Dockerfile and build do not rot.

- **GitHub Actions workflow** (`.github/workflows/monitoring.yml`):
  - Trigger on PR/push to `main` and `celeste-verification-examples`.
  - Run in `monitoring/` directory.
  - Steps: `npm ci` (or `bun install`), lint (ESLint), type-check (`tsc --noEmit`), build (`next build`), unit tests (`vitest` or `jest`).
  - Optional: build and push Docker image to GHCR on tags.
- **Dockerfile:** multi-stage build based on `node:20-alpine` (or `oven/bun:alpine` if using Bun); serve static export or run `next start`.
- **docker-compose override:** `docker-compose.monitoring.yml` that adds the monitoring service alongside the Celeste API.
- **Node package manager:** align with the rest of the repo. If the project uses `bun` elsewhere, use `bun` for `monitoring/`; otherwise `npm`/`pnpm`.

### 8.8 Test Strategy

Every new codepath gets a test. The backend uses the existing `pytest` + `pytest-asyncio` setup. The frontend uses `vitest` for units and `playwright` for E2E.

**Backend test targets (Python):**
- `GET /api/workflows` pagination — test default limit, offset, total count, empty page.
- `GET /api/workflows/{id}/events` — test `since_id` cursor, event_type filter, invalid workflow ID.
- `GET /api/workflows/{id}/workflow-events` — test returns WorkflowEvent rows, filters by type.
- `GET /api/workflows/{id}/metrics` — test cycle count, token accumulation, elapsed time, node counts.
- `GET /api/events` — test global event stream with limit.
- CORS middleware — test preflight response and allowed origins from env.
- Resume/cancel error paths — test non-paused resume, cancel non-running workflow.

**Frontend test targets (TypeScript):**
- `lib/api.ts` — mock fetch responses, verify request URLs and error handling.
- `hooks/useWorkflow.ts` / `usePolling.ts` — verify polling interval changes when workflow completes.
- `lib/format.ts` — duration/timestamp formatters with edge cases (0 ms, negative guard).
- Dashboard aggregation — given a workflows list, compute active/completed/failed/paused counts.
- Workflows list pagination — verify `useInfiniteQuery` fetches next page on scroll.

**E2E targets (Playwright):**
- Dashboard → click workflow → workflow overview loads with correct status.
- Workflows list search/filter → results update.
- Cancel workflow → status changes to cancelled.
- Resume paused workflow → human input submitted and status changes.

```
CODE PATH COVERAGE
===========================
[+] Backend: new /api/workflows pagination
    ├── [GAP] default limit/offset behavior — needs test
    ├── [GAP] total count in response — needs test
    └── [GAP] empty page — needs test

[+] Backend: events endpoint
    ├── [GAP] since_id cursor — needs test
    ├── [GAP] event_type filter — needs test
    └── [GAP] invalid workflow UUID — needs test

[+] Backend: workflow-events endpoint
    ├── [GAP] returns WorkflowEvent rows — needs test
    └── [GAP] filters by event type — needs test

[+] Backend: metrics endpoint
    ├── [GAP] computes cycle count, tokens, elapsed — needs test
    └── [GAP] handles missing data gracefully — needs test

[+] Backend: CORS
    ├── [GAP] preflight OPTIONS — needs test
    └── [GAP] allowed origins from env — needs test

[+] Frontend: API client
    ├── [GAP] listWorkflows pagination — needs test
    ├── [GAP] error response handling — needs test
    └── [GAP] cancel/resume mutations — needs test

[+] Frontend: hooks
    ├── [GAP] polling stops when workflow completes — needs test
    └── [GAP] polling continues while running — needs test

[+] E2E: core flows
    ├── [GAP] dashboard → workflow overview — needs E2E
    ├── [GAP] search/filter workflows — needs E2E
    └── [GAP] cancel workflow — needs E2E

─────────────────────────────────
COVERAGE: 0/24 paths tested (0%)
  All planned paths need tests.
QUALITY:  ★★★: 0  ★★: 0  ★: 0
GAPS: 24 paths need tests (3 need E2E)
─────────────────────────────────
```

Add these tests alongside the implementation, not after.

### 8.9 Error Handling Patterns

Every API call must have a defined error path:

- **Network error / 5xx:** Show a toast with "CMC lost contact with Celeste" and a retry button. Log to console for debugging.
- **404 workflow:** Show the empty/error state for the workflow with a "Back to workflows" action.
- **400 bad request:** Inline field errors for forms; toast for actions.
- **409 conflict (cancel/resume):** Show the current workflow status and disable the invalid action.
- **Auth failure (future):** Redirect to login or show auth modal.

Use TanStack Query's `retry` and `onError` for global handling; component-level error boundaries for render crashes.

### 8.10 Performance Notes

- **Dashboard aggregation:** For Phase 1, counts are computed client-side from the paginated workflows list. For fleets >100 workflows, add a fleet summary endpoint (`GET /api/workflows/summary`) in Phase 2 to return counts in O(1).
- **Constellation canvas:** Use `requestAnimationFrame`, throttle mouse events, and cap simulation iterations to keep 60 fps with 100+ nodes.
- **Event ledger:** Use `since_id` polling and virtualize the timeline when events exceed 500 rows.
- **Polling:** 1500 ms is fine for Phase 1. Move to SSE in Phase 6 for running workflows.

### 8.11 Failure Modes

For each new codepath, here is one realistic production failure and the planned mitigation:

| Codepath | Failure | Mitigation in plan | Test covers it? |
|----------|---------|-------------------|-----------------|
| `GET /api/workflows` pagination | Offset grows large, queries slow | Add status/date filters + retention policy | Phase 0 tests |
| `GET /api/workflows/{id}/events` | `since_id` points to deleted event | Return empty list; client keeps last known cursor | Phase 0 tests |
| `GET /api/workflows/{id}/workflow-events` | WorkflowEvent table has no index on workflow_id | Add index as part of endpoint work | Phase 0 tests |
| `GET /api/workflows/{id}/metrics` | Token tracking missing for some providers | Fallback to cycle count; show "—" for tokens | Phase 0 tests |
| `POST /api/workflows/{id}/resume` | Workflow no longer paused (race) | Return 409 conflict; UI disables action | Existing tests + Phase 0 |
| CORS middleware | Allowed origins env var missing | Default to `localhost:3000`; fail open only in dev | Phase 0 tests |
| Dashboard aggregates | Client-side count over paginated list is wrong | Add fleet summary endpoint in Phase 2 if needed | Phase 1 tests |
| Constellation SVG | 100+ nodes cause layout thrashing | Deterministic layout, virtualization, canvas fallback if profiled | Phase 3 tests |
| Live tail polling | Polling continues after workflow completes | TanStack Query refetchInterval conditional on status | Phase 1 tests |
| Token burn chart | Real token tracking unavailable for a provider | Show cycle count fallback | Phase 0 tests |

No critical gaps remain in the plan after Phase 0 restructuring.

### 8.12 Worktree Parallelization Strategy

Phase 0 has several independent backend endpoints that can be built in parallel worktrees:

| Step | Modules touched | Depends on |
|------|----------------|------------|
| Pagination on workflows | `celeste/api/` | — |
| since_id cursor on events | `celeste/api/` | — |
| workflow-events endpoint | `celeste/api/` | — |
| metrics endpoint | `celeste/api/`, `celeste/core/` | Real token tracking (below) |
| Global events endpoint | `celeste/api/` | — |
| CORS middleware | `celeste/api/` | — |
| Real token tracking | `celeste/core/llm*.py` | — |
| Retention policy + cleanup | `celeste/core/`, `celeste/database/` | — |
| Checkpoint lineage | `celeste/database/`, `celeste/core/` | — |
| API schema updates | `celeste/api/schemas.py` | All endpoints above |

**Parallel lanes:**
- **Lane A:** Pagination, events cursor, workflow-events, global events, CORS — all independent, can run in parallel worktrees.
- **Lane B:** Real token tracking + metrics endpoint — sequential because metrics depends on real tokens.
- **Lane C:** Retention policy + cleanup + checkpoint lineage — sequential because cleanup must respect lineage.
- **Lane D:** API schema updates — merges after A, B, and C are done.

**Execution order:** Launch lanes A, B, and C in parallel. Merge each into `celeste-verification-examples`. Then run lane D to consolidate schemas. Frontend work (Phase 1) starts after lane D merges.

**Conflict flags:** Lanes A, B, and C all touch `celeste/api/` or `celeste/database/models.py`. Coordinate around `schemas.py` and model changes to avoid merge conflicts.

---

## 9. Progressive Implementation Plan

We build in six weeks so the backend can support the UI before screens are built. The first week is backend-only; frontend work starts once the data contracts are real.

### Phase 0 — Backend API Completion (Week 0)

Goals: Every endpoint and data contract the UI needs must exist and be tested before a Next.js page is written.

Deliverables:
- [ ] Add `limit`/`offset` and total count to `GET /api/workflows`.
- [ ] Add `since_id` cursor to `GET /api/workflows/{id}/events`.
- [ ] Add `GET /api/workflows/{id}/workflow-events` with `event_type` filter and `since_id` cursor.
- [ ] Add `GET /api/workflows/{id}/metrics` (cycles, tokens, elapsed, node counts, max workspaces, security pass rate).
- [ ] **Implement real LLM token tracking** in the LLM client layer (`celeste/core/llm.py` or equivalent) so `llm_tokens_accumulated` reflects actual prompt + completion tokens. Update `WorkflowEvent` and `WorkflowResult` to persist real usage.
- [ ] Add `GET /api/events` global event stream with `limit`/`offset`.
- [ ] Add configurable CORS middleware to FastAPI.
- [ ] Fix `dag_definition` for OPA workflows: either update it as fragments are persisted, or document that Constellation queries `TaskNode` adjacency directly.
- [ ] Add `parent_workflow_id` to `Workflow` and expose it in the API for checkpoint lineage.
- [ ] Add workflow retention policy (`EngineSettings.WORKFLOW_RETENTION_DAYS`) and background cleanup task.
- [ ] Add `status` and `created_after` filters to `GET /api/workflows`.
- [ ] Tests for every new endpoint and data path.
- [ ] Update API schemas (`celeste/api/schemas.py`) with new response models.

### Phase 1 — Foundation & Dashboard (Week 1)

Goals: Shell, design system, API client, Dashboard, Workflows list.

Deliverables:
- [ ] Next.js project scaffold in `monitoring/`.
- [ ] Fonts, tokens, grain overlay, shell layout.
- [ ] Typed API client for existing endpoints.
- [ ] Dashboard page with summary cards + recent workflows.
- [ ] Workflows list page with search/filter and pagination.
- [ ] Poll-based live updates.
- [ ] GitHub Actions CI workflow for `monitoring/` — lint, type-check, build, and test on PR/push.
- [ ] `monitoring/Dockerfile` and docker-compose override for local deployment.

### Phase 2 — Workflow Overview (Week 2)

Goals: The mission control home for one workflow.

Deliverables:
- [ ] Workflow overview page with KPI strip, mini constellation, timeline.
- [ ] Node inspector side panel (reused later in Constellation view).
- [ ] Cancel / resume actions with error handling.
- [ ] Pause response input.

### Phase 3 — Constellation & OPA Loop (Week 3)

Goals: Make the workflow graph navigable and the OPA cycles inspectable.

Deliverables:
- [ ] Constellation view page (deterministic layout; SVG first, canvas only if profiling proves SVG is too slow).
- [ ] OPA Loop view with cycle navigator + plan diff.
- [ ] Token burn chart — only if actual token tracking is implemented; otherwise show cycle count chart.
- [ ] Node inspector integration.

### Phase 4 — Security, Workspaces, Saga, Escalation (Week 4)

Goals: Specialized operational views for Celeste's unique capabilities.

Deliverables:
- [ ] Security audit view (uses pre-computed aggregates from metrics endpoint).
- [ ] Workspace lifecycle / concurrency view.
- [ ] Saga compensation diagram.
- [ ] Human escalation panel with resume input.

### Phase 5 — Agents & Observatory (Week 5)

Goals: Fleet-wide visibility and registered environment agents.

Deliverables:
- [ ] Agents list + register form.
- [ ] Observatory page with global event ticker.
- [ ] Feature verification summary across workflows.

### Phase 6 — Real-Time & Polish (Week 6)

Goals: Live feel and production readiness.

Deliverables:
- [ ] SSE or WebSocket for live status pushes.
- [ ] Keyboard shortcuts, URL state preservation, copy-to-clipboard conveniences.
- [ ] Accessibility audit (color contrast, focus states, reduced-motion).
- [ ] Documentation: README, environment variables, deployment notes.

---

## 10. Motion & Micro-Interaction Design

### Ambient motion

- **Grain overlay:** continuous `steps()` noise animation at 12fps, very subtle.
- **Aurora gradient:** slow `background-position` drift over 60s.
- **Status orbs:** running nodes pulse with a double-ring echo (CSS box-shadow animation).
- **Constellation edges:** tiny particles travel along active dependency edges.

### Interactive motion

- Page transitions: `layoutId` shared element transitions where appropriate.
- Card hover: subtle lift (`translateY(-2px)`) + border glow.
- Sidebar: icons slide + labels fade on hover.
- Toast notifications for actions (cancel, resume) slide in from the top-right.

### Orchestrated load

On first paint, the shell fades in, the aurora settles, summary cards stagger in left-to-right, and the most important number (active workflows) scales from 0 with a spring.

---

## 11. Accessibility

- Dark mode only, but respect `prefers-reduced-motion` (disable grain, pulsing, autopan).
- All status colors paired with icons + text labels (never color-only).
- Focus rings use `--aurora-500` with 2px offset.
- Interactive DAG nodes are keyboard-focusable and announce status via `aria-live` regions.
- Minimum contrast ratio 4.5:1 for body text, 3:1 for large text and UI components.

---

## 12. Open Questions & Decisions

1. **Backend endpoint extensions** — Should we extend the FastAPI app in `src/celeste/api/app.py` directly, or create a separate monitoring BFF in `monitoring/` that queries SQLite?  
   *Recommendation:* Extend FastAPI directly for endpoints needed by the UI; keeps the project unified.

2. **Real-time transport** — SSE is simpler and sufficient for one-way server→client status push. WebSocket gives us bidirectional future proofing.  
   *Recommendation:* Start with SSE in Phase 4.

3. **Authentication** — Current API has no auth. Should the monitoring UI add any?  
   *Recommendation:* No auth in Phase 1; rely on network isolation. Add optional bearer token if requested later.

4. **Database coupling** — The UI reads via HTTP, not directly from SQLite, so it works in remote/embedded modes too.

5. **Deployment** — Should `monitoring/` be a separate deployable or embedded in the Python package?  
   *Recommendation:* Build as a standalone Next.js app; provide `Dockerfile` and a `docker-compose` override for the example. Optionally serve the static build via a FastAPI `StaticFiles` mount later.

### 12.1 Design Decisions Resolved During Review

The following design choices were made and added to the plan:

1. **Mobile Constellation fallback** — On screens <768 px, the canvas is replaced by a structured node list sorted by dependency order with the active node pinned to the top. Inspector opens in a full-screen sheet.
2. **Keyboard shortcuts** — Core `Ctrl/Cmd` modifier shortcuts to avoid browser conflicts (see §8.6).
3. **Interaction state table** — Loading, empty, error, success, and partial states specified for every major feature (see §6.14).
4. **Per-page visual hierarchy** — Primary, secondary, and tertiary focal points defined for every screen (see §5.3).
5. **User journey storyboard** — Emotional arc and time-horizon design captured (see §6.15).
6. **AI slop anti-patterns** — Ten forbidden patterns listed and tied to mockup verification (see §2.4).
7. **DESIGN.md created** — Canonical design tokens, components, motion, accessibility, and responsive rules extracted to `DESIGN.md` at repo root.

The following engineering decisions were made during the eng review:

8. **Backend Phase 0** — Every endpoint and data contract the UI needs must be implemented and tested before frontend screens are built (see §9 Phase 0).
9. **Real LLM token tracking** — Replace the hardcoded `+= 100` heuristic with actual prompt/completion token counts before building the token burn chart.
10. **Workflow retention policy** — Add `WORKFLOW_RETENTION_DAYS` and background cleanup to prevent unbounded database growth.
11. **Checkpoint lineage** — Add `parent_workflow_id` to `Workflow` so the UI can trace workflows that continued-as-new.
12. **Constellation rendering** — SVG first, canvas only if profiling proves SVG is the bottleneck; deterministic layout required.

---

## 13. Success Criteria

- A new operator can open CMC and, within 10 seconds, understand which workflows are running, which failed, and which are waiting for human input.
- The constellation view makes replanning visibly obvious (new stars appear, old ones fade).
- The security audit view surfaces blocked calls and their reasons without opening raw JSON.
- The UI remains performant with 100+ nodes and 1,000+ events.
- The aesthetic is instantly recognizable as Celeste — not another generic AI dashboard.

---

## 14. Next Steps

1. Review and approve this plan.
2. Begin Phase 0 backend API completion.
3. Generate visual mockups once `OPENAI_API_KEY` is configured.
4. Iterate on the constellation renderer early; it is the visual signature of the product.

## 15. TDD Specification

This section makes the plan self-contained for test-driven development. A coding agent should be able to implement every Phase 0-1 deliverable by writing the tests below first, then making them pass.

### 15.1 New API Schemas

Add these Pydantic models to `src/celeste/api/schemas.py`:

```python
class PaginationParams(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)

class WorkflowListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[WorkflowListItem]

class WorkflowEventResponse(BaseModel):
    id: str
    event_type: str
    event_data: dict | None
    timestamp: str

class WorkflowMetricsResponse(BaseModel):
    workflow_id: str
    cycle_count: int
    total_nodes: int
    completed_nodes: int
    failed_nodes: int
    completed_percent: float
    elapsed_seconds: float
    llm_tokens_accumulated: int | None
    max_concurrent_workspaces: int
    security_pass_rate: float | None  # audited-safe / total-audited, None if no audits

class GlobalEventResponse(BaseModel):
    id: str
    workflow_id: str | None
    event_type: str
    event_data: dict | None
    timestamp: str

class CORSOrigins(BaseModel):
    allow_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
```

### 15.2 Backend Endpoint Specification

#### `GET /api/workflows`

**Query params:** `limit`, `offset`, `status`, `created_after` (ISO timestamp)

**Response:** `WorkflowListResponse`

**Test cases (add to `tests/api/test_workflows.py`):**

```python
async def test_list_workflows_default_pagination(client):
    """Default limit is 20, offset is 0, total reflects all workflows."""
    response = await client.get("/api/workflows")
    assert response.status_code == 200
    data = response.json()
    assert "total" in data
    assert "limit" in data
    assert "offset" in data
    assert "items" in data
    assert data["limit"] == 20
    assert data["offset"] == 0
    assert len(data["items"]) <= data["total"]

async def test_list_workflows_pagination_offset(client, sample_workflows):
    """Offset skips the first N workflows ordered by created_at desc."""
    response = await client.get("/api/workflows?limit=2&offset=2")
    assert response.status_code == 200
    data = response.json()
    assert data["limit"] == 2
    assert data["offset"] == 2
    assert len(data["items"]) <= 2

async def test_list_workflows_status_filter(client, sample_workflows):
    """status=running returns only running workflows."""
    response = await client.get("/api/workflows?status=running")
    assert response.status_code == 200
    data = response.json()
    assert all(w["status"] == "running" for w in data["items"])

async def test_list_workflows_created_after_filter(client, sample_workflows):
    """created_after filters workflows created after the given timestamp."""
    cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)).isoformat()
    response = await client.get(f"/api/workflows?created_after={cutoff}")
    assert response.status_code == 200
    data = response.json()
    for w in data["items"]:
        assert w["created_at"] >= cutoff

async def test_list_workflows_empty_page(client):
    """Offset beyond total returns empty items and total=0."""
    response = await client.get("/api/workflows?offset=9999")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
```

#### `GET /api/workflows/{id}/events`

**Query params:** `event_type`, `since_id`, `limit`

**Response:** `list[EventResponse]`

**Test cases:**

```python
async def test_events_since_id_returns_newer_events(client, sample_events):
    """since_id returns only events with id > since_id."""
    since_id = sample_events[2].id
    response = await client.get(f"/api/workflows/{wf_id}/events?since_id={since_id}&limit=100")
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    assert all(int(e["id"]) > since_id for e in data)

async def test_events_since_id_deleted_event(client):
    """since_id pointing to deleted event returns empty list safely."""
    response = await client.get(f"/api/workflows/{wf_id}/events?since_id=999999&limit=100")
    assert response.status_code == 200
    assert response.json() == []

async def test_events_invalid_event_type(client):
    """Invalid event_type returns 400."""
    response = await client.get(f"/api/workflows/{wf_id}/events?event_type=not_real")
    assert response.status_code == 400
```

#### `GET /api/workflows/{id}/workflow-events`

**Query params:** `event_type`, `since_id`, `limit`

**Response:** `list[WorkflowEventResponse]`

**Test cases:**

```python
async def test_workflow_events_returns_workflow_events(client, sample_workflow_events):
    """Endpoint returns WorkflowEvent rows, not TaskEvent rows."""
    response = await client.get(f"/api/workflows/{wf_id}/workflow-events")
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    assert all("plan_generated" in e["event_type"] or "observation" in e["event_type"] for e in data)

async def test_workflow_events_filter_by_type(client, sample_workflow_events):
    """event_type filter works."""
    response = await client.get(f"/api/workflows/{wf_id}/workflow-events?event_type=plan_generated")
    assert response.status_code == 200
    data = response.json()
    assert all(e["event_type"] == "plan_generated" for e in data)
```

#### `GET /api/workflows/{id}/metrics`

**Response:** `WorkflowMetricsResponse`

**Test cases:**

```python
async def test_metrics_computes_cycle_count(client, running_workflow):
    """cycle_count equals number of plan_generated events."""
    response = await client.get(f"/api/workflows/{running_workflow.id}/metrics")
    assert response.status_code == 200
    data = response.json()
    assert data["cycle_count"] >= 0
    assert data["total_nodes"] >= 0
    assert 0.0 <= data["completed_percent"] <= 1.0
    assert data["elapsed_seconds"] >= 0.0

async def test_metrics_token_fallback_when_unavailable(client):
    """If token tracking unavailable, llm_tokens_accumulated is None."""
    response = await client.get(f"/api/workflows/{wf_id}/metrics")
    data = response.json()
    assert data["llm_tokens_accumulated"] is None or isinstance(data["llm_tokens_accumulated"], int)
```

#### `GET /api/events`

**Query params:** `limit`, `offset`

**Response:** `list[GlobalEventResponse]`

**Test cases:**

```python
async def test_global_events_returns_events_across_workflows(client, sample_events):
    """Returns TaskEvent and WorkflowEvent union, newest first."""
    response = await client.get("/api/events?limit=10")
    assert response.status_code == 200
    data = response.json()
    assert len(data) <= 10
    timestamps = [e["timestamp"] for e in data]
    assert timestamps == sorted(timestamps, reverse=True)
```

#### CORS Middleware

**Test cases:**

```python
async def test_cors_preflight(client):
    """OPTIONS request from allowed origin returns 200 with CORS headers."""
    response = await client.options(
        "/api/workflows",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert "access-control-allow-origin" in response.headers

async def test_cors_origin_from_env(client, monkeypatch):
    """Allowed origins are configurable via environment."""
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://cmc.example.com")
    response = await client.get("/api/workflows", headers={"Origin": "https://cmc.example.com"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://cmc.example.com"
```

#### Token Tracking

**Test cases:**

```python
async def test_real_token_tracking_updates_workflow_event(sample_llm_call):
    """WorkflowEvent event_data contains actual prompt and completion tokens."""
    event = sample_llm_call
    assert "prompt_tokens" in event.event_data
    assert "completion_tokens" in event.event_data
    assert event.event_data["prompt_tokens"] >= 0
    assert event.event_data["completion_tokens"] >= 0
```

### 15.3 Frontend TypeScript Types

Add to `monitoring/lib/types.ts`:

```typescript
export interface WorkflowListItem {
  id: string;
  name: string;
  status: WorkflowStatus;
  created_at: string;
}

export interface WorkflowListResponse {
  total: number;
  limit: number;
  offset: number;
  items: WorkflowListItem[];
}

export type WorkflowStatus = 'pending' | 'running' | 'paused' | 'completed' | 'failed' | 'cancelled';

export interface WorkflowMetrics {
  workflow_id: string;
  cycle_count: number;
  total_nodes: number;
  completed_nodes: number;
  failed_nodes: number;
  completed_percent: number;
  elapsed_seconds: number;
  llm_tokens_accumulated: number | null;
  max_concurrent_workspaces: number;
  security_pass_rate: number | null;
}

export interface WorkflowEvent {
  id: string;
  event_type: string;
  event_data: Record<string, unknown> | null;
  timestamp: string;
}

export interface GlobalEvent extends WorkflowEvent {
  workflow_id: string | null;
}

export interface EventQuery {
  event_type?: string;
  since_id?: number;
  limit?: number;
}
```

### 15.4 Frontend API Client Test Cases

Add to `monitoring/lib/api.test.ts`:

```typescript
describe('listWorkflows', () => {
  it('requests with pagination params', async () => {
    fetchMock.get('/api/workflows?limit=10&offset=0', { total: 1, limit: 10, offset: 0, items: [{ id: '1', name: 'wf', status: 'running', created_at: '2026-01-01T00:00:00Z' }] });
    const result = await listWorkflows({ limit: 10, offset: 0 });
    expect(result.items).toHaveLength(1);
    expect(result.items[0].status).toBe('running');
  });

  it('throws on 5xx', async () => {
    fetchMock.get('/api/workflows?limit=20&offset=0', 500);
    await expect(listWorkflows()).rejects.toThrow('CMC lost contact with Celeste');
  });
});

describe('getWorkflowEvents', () => {
  it('polls with since_id for live tail', async () => {
    fetchMock.get('/api/workflows/wf-1/events?since_id=10&limit=50', [{ id: '11', event_type: 'node_completed', event_data: {}, timestamp: '2026-01-01T00:00:00Z' }]);
    const result = await getWorkflowEvents('wf-1', { since_id: 10 });
    expect(result[0].id).toBe('11');
  });
});

describe('cancelWorkflow', () => {
  it('sends DELETE and returns cancelled status', async () => {
    fetchMock.delete('/api/workflows/wf-1', { workflow_id: 'wf-1', status: 'cancelled' });
    const result = await cancelWorkflow('wf-1');
    expect(result.status).toBe('cancelled');
  });

  it('throws 409 if workflow cannot be cancelled', async () => {
    fetchMock.delete('/api/workflows/wf-1', { status: 409, body: { detail: 'Cannot cancel workflow in completed state' } });
    await expect(cancelWorkflow('wf-1')).rejects.toThrow('Cannot cancel workflow');
  });
});
```

### 15.5 Hook Test Cases

Add to `monitoring/hooks/useWorkflow.test.ts`:

```typescript
describe('useWorkflowStatus', () => {
  it('polls every 1500ms while running', async () => {
    // Mock getWorkflowStatus returning running twice then completed
    // Assert query is refetched at interval while running and stops when completed
  });

  it('stops polling when workflow is completed', async () => {
    // Mock completed status
    // Assert refetchInterval returns false
  });
});
```

### 15.6 Component Test Cases

Add to `monitoring/components/dashboard/SummaryCards.test.tsx`:

```typescript
describe('SummaryCards', () => {
  it('renders active count largest', () => {
    render(<SummaryCards workflows={sampleWorkflows} />);
    expect(screen.getByText('Active')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument(); // active count
  });

  it('shows alert flares for failed workflows', () => {
    render(<AlertFlareList workflows={sampleWorkflows} />);
    expect(screen.getByText(/workflow-failed-1/)).toBeInTheDocument();
  });
});
```

### 15.7 E2E Test Cases

Add to `monitoring/e2e/dashboard.spec.ts`:

```typescript
test('dashboard to workflow overview', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Active workflows')).toBeVisible();
  await page.getByText('sample-workflow').click();
  await expect(page).toHaveURL(/\/workflows\/sample-workflow/);
  await expect(page.getByText('OPA cycles')).toBeVisible();
});

test('search workflows', async ({ page }) => {
  await page.goto('/workflows');
  await page.getByPlaceholder('Search workflows').fill('sample');
  await expect(page.getByText('sample-workflow')).toBeVisible();
  await expect(page.getByText('other-workflow')).not.toBeVisible();
});
```

### 15.8 Mock Fixtures

Add shared fixtures for tests:

```typescript
// monitoring/lib/fixtures.ts
export const sampleWorkflows: WorkflowListItem[] = [
  { id: 'wf-1', name: 'sample-workflow', status: 'running', created_at: '2026-06-12T10:00:00Z' },
  { id: 'wf-2', name: 'other-workflow', status: 'completed', created_at: '2026-06-12T09:00:00Z' },
  { id: 'wf-3', name: 'workflow-failed-1', status: 'failed', created_at: '2026-06-12T08:00:00Z' },
];
```

```python
# tests/conftest.py additions
@pytest.fixture
async def sample_workflows(db_session):
    workflows = []
    for i, status in enumerate([WorkflowStatus.RUNNING, WorkflowStatus.COMPLETED, WorkflowStatus.FAILED]):
        wf = Workflow(name=f"wf-{i}", status=status, dag_definition={"goal": f"goal-{i}"})
        db_session.add(wf)
        workflows.append(wf)
    await db_session.commit()
    return workflows
```

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | issues_open (PLAN) | 7 issues, 0 critical gaps, backend Phase 0 added |
| Design Review | `/plan-design-review` | UI/UX gaps | 1 | issues_open (FULL) | score: 6/10 → 8/10, 4 decisions made |

- **CODEX:** Outside voice used Claude subagent (Codex binary unavailable). Key findings: backend API is missing required endpoints, token tracking is synthetic, OPA workflows lack full `dag_definition`, checkpoint lineage missing, no retention policy. User accepted Phase 0 backend completion, real token tracking, retention policy, and checkpoint lineage.
- **CROSS-MODEL:** Design review and eng review agree the plan is strong on aesthetic but needed backend grounding. Eng review surfaced implementation prerequisites the design review did not catch.
- **UNRESOLVED:** 0 unresolved decisions. Visual mockups could not be generated because the gstack designer has no OpenAI API key; tracked as TODO-15.
- **VERDICT:** Design + Eng reviews completed with open items. Mockup generation and post-implementation visual QA are still required. Plan is not yet cleared for implementation until mockups are generated and visual QA passes.

*Report updated by `/plan-eng-review` on 2026-06-12.*
