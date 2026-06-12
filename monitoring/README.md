# Celeste Mission Control (CMC)

**Celeste Mission Control** is the operator-facing web UI for the [Celeste-DAG](../README.md) dynamic agentic workflow engine. It turns the engine's event-sourced runtime — OPA loops, DAG execution, saga compensation, security audits, multi-workspace isolation, checkpoint lineage, and human escalation — into a navigable, keyboard-first observatory where every workflow is a celestial object and the operator is the astronomer at the console.

CMC is built as a standalone Next.js 16 application that talks to the Celeste FastAPI backend over HTTP. It uses a retro-futuristic "Celestial Mission Control" aesthetic codified in [`../DESIGN.md`](../DESIGN.md).

---

## Features

- **Dashboard** — Fleet-wide health, orbital summary cards (active / completed / failed / paused), live throughput strip, alert flares, recent workflows.
- **Workflows list** — Searchable, filterable, paginated grid of workflow cards with status orbs, progress arcs, and live counts.
- **Workflow detail** — A mission-control home for one workflow with KPI strip, mini-constellation preview, lifecycle timeline, and contextual actions.
- **Six workflow subviews**
  - **Constellation** — A live, panning DAG view; nodes pulse with status, edges draw like constellation lines, camera drifts to the active node.
  - **OPA Loop** — Observe-Plan-Act cycle navigator with DAG diff visualization and evaluator rationale.
  - **Event Ledger** — Full audit trail of `TaskEvent` and `WorkflowEvent` rows with live tail, filter chips, and a JSON inspector.
  - **Security Audit** — Two-phase security pipeline coverage, blocked-call list, threat tag cloud, per-call verdicts.
  - **Workspaces** — Multi-workspace lifecycle, concurrency chart, leak alerts on spawn/destroy imbalance.
  - **Saga Compensation & Human Escalation** — Rollback choreography and tier-4 pause management with input editor.
- **Agents** — Registered environment agents, connectivity status, register form.
- **Observatory** — Cross-workflow global event ticker, feature verification summary, provider mix.
- **Keyboard-first** — Twelve core shortcuts for navigation, search, refresh, and workflow actions.
- **Live updates** — TanStack Query polling (1500 ms) while workflows are running; auto-stop when terminal.
- **Accessible** — `prefers-reduced-motion` honored, color paired with icon + text, focus rings, ARIA live regions, 4.5:1 contrast.

## Tech Stack

| Layer | Choice |
|-------|--------|
| Framework | [Next.js 16](https://nextjs.org) (App Router, standalone output) |
| Language | TypeScript 5 |
| Styling | [Tailwind CSS v4](https://tailwindcss.com) + CSS custom properties (design tokens) |
| Data fetching / cache | [TanStack Query v5](https://tanstack.com/query) |
| UI primitives | [Radix UI](https://www.radix-ui.com) (themed wrappers) |
| Charts | [Recharts](https://recharts.org) |
| Animation | [Framer Motion](https://www.framer.com/motion) + CSS keyframes for ambient effects |
| Icons | [Lucide](https://lucide.dev) |
| Testing | [Vitest](https://vitest.dev) + Testing Library |
| Lint / format | ESLint (Next.js config) |
| Runtime | Node.js 20 |

## Quick Start

### Prerequisites

- Node.js 20+
- npm 10+
- A running Celeste FastAPI backend (default: `http://localhost:8000`)

### Install

```bash
cd monitoring
npm install
```

### Configure

Copy the example environment file and adjust the API URL if needed:

```bash
cp .env.example .env.local
```

The default points CMC at `http://localhost:8000`. CMC proxies `/api/*` requests to the Celeste API at build/runtime via the `rewrites()` block in `next.config.ts`.

### Develop

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

### Build

```bash
npm run build
npm run start
```

The build emits a standalone Next.js server in `.next/standalone` suitable for the included Dockerfile.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NEXT_PUBLIC_CELESTE_API_URL` | No | `http://localhost:8000` | Base URL of the Celeste FastAPI backend. Used by `next.config.ts` to proxy `/api/*` rewrites. Must be set at build time for production rewrites to work. |

CMC currently has no authentication. If the Celeste API is exposed beyond `localhost`, terminate it behind a network boundary or a reverse proxy.

## Scripts

| Script | Description |
|--------|-------------|
| `npm run dev` | Start the Next.js dev server with hot reload on port 3000. |
| `npm run build` | Produce a production build (standalone output in `.next/`). |
| `npm run start` | Run the production build (uses `server.js` from standalone output). |
| `npm run lint` | Run ESLint with the Next.js config. |
| `npm run type-check` | Run `tsc --noEmit` against the project. |
| `npm run test` | Run the Vitest unit-test suite once. |

## Project Structure

```
monitoring/
├── app/                          # Next.js App Router pages
│   ├── layout.tsx                # Root shell, fonts, providers
│   ├── page.tsx                  # Dashboard
│   ├── workflows/
│   │   ├── page.tsx              # Workflows list
│   │   └── [id]/
│   │       ├── page.tsx          # Workflow overview
│   │       ├── constellation/    # DAG view
│   │       ├── opa-loop/         # OPA cycle inspector
│   │       ├── ledger/           # Event ledger
│   │       ├── security/         # Security audit
│   │       ├── workspaces/       # Workspace lifecycle
│   │       ├── saga/             # Saga compensation
│   │       └── escalation/       # Human escalation
│   ├── agents/page.tsx
│   └── observatory/page.tsx
├── components/
│   ├── shell/                    # Navigation, top bar, layout primitives
│   ├── ui/                       # Buttons, badges, panels, inputs
│   ├── charts/                   # Reusable chart wrappers
│   ├── constellation/            # DAG canvas + node inspector
│   ├── workflow/                 # Workflow-specific cards and panels
│   └── agents/                   # Agent cards
├── lib/
│   ├── api.ts                    # Typed API client
│   ├── types.ts                  # Frontend type definitions
│   ├── colors.ts                 # Design token helpers
│   └── format.ts                 # Duration / timestamp formatters
├── hooks/
│   ├── useWorkflow.ts
│   ├── useWorkflowEvents.ts
│   └── usePolling.ts
├── styles/
│   ├── globals.css               # Tokens, fonts, grain overlay
│   └── animations.css            # Keyframes
├── public/                       # Static assets
├── Dockerfile                    # Multi-stage production image
├── .env.example
├── .dockerignore
├── next.config.ts
├── tailwind.config / postcss
├── tsconfig.json
├── vitest.config.ts
└── package.json
```

## Design System

The visual language — colors, typography, motion, components, accessibility, anti-patterns — is canonical in [`../DESIGN.md`](../DESIGN.md). All component and page implementations in `monitoring/` must align with that file. If a token, component recipe, or motion rule is missing here, the answer lives in `DESIGN.md`.

Key references:

- **Colors:** `--aurora-500` (cyan accent), `--solar-500` (warning), `--mars-500` (failure), `--nebula-500` (success), `--space-*` (neutrals).
- **Type:** Bodoni Moda (display), Syne (UI/body), JetBrains Mono (logs, JSON, timestamps).
- **Atmosphere:** Animated grain overlay, slow aurora gradient, status orbs with double-ring pulse.
- **Anti-patterns:** No purple/violet gradients, no circled icon decorations, no centered hero copy, no decorative blobs, no emoji as design elements.

## Keyboard Shortcuts

Core shortcuts for power users. Modifier keys are used to avoid clashing with browser defaults.

| Shortcut | Action | Context |
|----------|--------|---------|
| `Ctrl/Cmd + K` | Focus global search | Global |
| `Ctrl/Cmd + Shift + D` | Go to Dashboard | Global |
| `Ctrl/Cmd + Shift + W` | Go to Workflows | Global |
| `Ctrl/Cmd + Shift + O` | Go to Observatory | Global |
| `Ctrl/Cmd + Shift + A` | Go to Agents | Global |
| `Esc` | Close inspector / bottom sheet / modal / help | Global |
| `Ctrl/Cmd + R` | Refresh current view (browser default; triggers TanStack Query refetch) | Global |
| `Ctrl/Cmd + /` or `?` | Show keyboard shortcuts help | Global |
| `Ctrl/Cmd + Shift + C` | Copy workflow ID | Workflow page |
| `Ctrl/Cmd + Shift + P` | Pause/resume selected workflow (with confirmation) | Workflow page |
| `↑` / `↓` or `j` / `k` | Next/previous workflow in list when list is focused | Workflows list |
| `Enter` | Open selected workflow | Workflows list |

`event.preventDefault()` is only used for non-browser shortcuts, and never while a text field is focused.

## Deployment

### Docker

The included `Dockerfile` is a multi-stage build on `node:20-alpine` that produces a minimal runner image. Build the standalone output and serve via `node server.js`.

```bash
cd monitoring
docker build -t celeste-mission-control:latest .
docker run --rm -p 3000:3000 \
  -e NEXT_PUBLIC_CELESTE_API_URL=https://celeste.example.com \
  celeste-mission-control:latest
```

The image:

- Disables Next.js telemetry.
- Runs as the unprivileged `nextjs` user.
- Exposes port 3000.

### docker-compose

A worktree-root override is provided at [`../docker-compose.monitoring.yml`](../docker-compose.monitoring.yml). It adds the `monitoring` service alongside the existing Celeste API and points `NEXT_PUBLIC_CELESTE_API_URL` at the API service.

```bash
# From the worktree root, alongside the existing compose file (if any):
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up
```

If you are running CMC against a standalone Celeste backend, you can still use the monitoring compose file directly and point it at an external API URL.

### Continuous Integration

CMC has its own GitHub Actions workflow at [`.github/workflows/monitoring.yml`](../.github/workflows/monitoring.yml) that runs on push to `main` and on pull requests. It executes:

1. `npm ci` (with npm cache)
2. `npm run lint`
3. `npm run type-check`
4. `npm run test`
5. `npm run build`

The workflow sets `working-directory: monitoring` so it does not affect the parent Python CI in `.github/workflows/ci.yml`.

## Testing

- **Unit tests** — `npm run test` (Vitest) covers the API client, hooks, formatters, and key components.
- **End-to-end tests** — Playwright flows (planned) cover dashboard → workflow overview, list search/filter, and cancel/resume mutations.

## License

CMC is released under the **MIT License** — the same license as the parent Celeste-DAG project. See [`../LICENSE`](../LICENSE) at the worktree root for the full text.
