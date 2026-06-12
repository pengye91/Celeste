# TODOS

Captured during /plan-eng-review on 2026-06-11.

---

## TODO-1: Add CI/CD pipeline for remote agent Docker image

- **What:** GitHub Actions workflow that builds and publishes a Docker image for `EnvironmentAgent.serve()`, plus PyPI publish for the SDK.
- **Why:** Phase 4 introduces a new deployable artifact (remote agent HTTP/WebSocket server) but the plan has zero CI/CD, container build, or release process. Code without distribution is code nobody can use.
- **Pros:** Makes remote deployment real; enables versioned releases; users can `docker pull` the agent.
- **Cons:** Adds maintenance burden for the CI pipeline; needs secrets management for registry auth.
- **Context:** The agent is a standalone Python process with FastAPI/websocket dependencies. A `Dockerfile` should be straightforward. Target platforms: linux/amd64, linux/arm64. Publish to GitHub Container Registry or Docker Hub.
- **Depends on:** Phase 4a (remote serve implementation) must be complete.

## TODO-2: Design human-in-the-loop escalation mechanism

- **What:** Define how Tier 4 escalation (human notification and response) actually works — API endpoint, webhook, email, or UI.
- **Why:** The plan says "pause workflow, notify, wait for human input" but has no mechanism for the human to respond or resume. This is a dead end in production.
- **Pros:** Makes escalation usable; enables human oversight for ambiguous goals.
- **Cons:** Adds UI/API complexity; needs notification infrastructure (email/Slack/webhook).
- **Context:** When `evaluate()` returns `ESCALATE`, the workflow pauses. A human needs to: (1) see why it escalated, (2) provide guidance, (3) resume or cancel the workflow. Start with a simple `POST /api/workflows/{id}/resume` endpoint that accepts human input as context.
- **Depends on:** Phase 2 (OPA Loop + Evaluator) must be complete.

## TODO-3: Add Alembic database migrations

- **What:** Set up Alembic for managing database schema changes, starting with the `WorkflowEvent` table and new `EventType` enum values.
- **Why:** Adding a new table (`WorkflowEvent`) and new enum values to `TaskEventType` requires schema migrations. Currently the project has no migration system.
- **Pros:** Safe schema evolution across environments; reproducible database state; required for production deployments.
- **Cons:** Adds a dependency (alembic); migration files need to be maintained.
- **Context:** The project uses SQLAlchemy 2.0 with async SQLite/PostgreSQL. Alembic works with async drivers. Initial migration should capture the current schema, then incremental migrations for `WorkflowEvent` and enum extensions.
- **Depends on:** Phase 3a (WorkflowEvent + replay schema) must be designed.

## TODO-4: Implement agent attestation for remote security audit

- **What:** Cryptographic signing of agent-side security audit results so the engine can verify the audit actually ran.
- **Why:** The outside voice flagged that a compromised target environment can bypass agent-side audit. The engine can't verify the agent ran its audit. The user chose to keep both-sides audit without crypto for now, but this is a known security gap.
- **Pros:** True defense-in-depth; engine can cryptographically verify audit execution.
- **Cons:** Adds significant complexity (key management, signing, verification); may be overkill for many use cases.
- **Context:** Agent generates an Ed25519 keypair on first start. Signs audit results. Engine verifies signature against a pinned public key. If verification fails, the tool call is blocked. Consider using Sigstore or similar for key transparency.
- **Depends on:** Phase 1a (agent implementation) and security architecture decisions.

## TODO-5: Design workspace/agent containment model for Docker/Firecracker

- **What:** Resolve the fundamental ambiguity: does the agent run inside the container/VM or outside it?
- **Why:** The outside voice flagged that the plan says "the agent runs inside the target environment" but also draws the workspace (Docker/Firecracker) as a separate box. This is a fundamental architectural ambiguity.
- **Pros:** Clear security boundaries; consistent deployment model; enables proper sandboxing.
- **Cons:** May require baking the agent into workspace images; adds startup latency.
- **Context:** Two options: (1) Agent runs inside the container/VM — needs to be in the image, has full access to the sandboxed filesystem. (2) Agent runs outside, proxies into the container/VM via docker exec or similar. Option 1 is cleaner for "agent in environment." Option 2 is easier for existing Docker workspace images. Decide before Phase 4 implementation.
- **Depends on:** Phase 1a (agent implementation) and workspace architecture review.

## TODO-6: Add configurable cycle limit and cost budget to OPA loop

- **What:** Hard limits on OPA loop iterations and LLM token/cost budget per workflow.
- **Why:** The outside voice flagged that the OPA loop has no termination guarantee. A confused planner can spin forever, burning LLM tokens and database events.
- **Pros:** Prevents runaway costs; enables production safety limits.
- **Cons:** Adds configuration complexity; hard limits may abort legitimate long workflows.
- **Context:** Add `MAX_OPA_CYCLES` (default: 100) and `MAX_LLM_COST_USD` (default: $5.00) to `EngineSettings`. When hit, the workflow escalates to Tier 4 (human). These should be configurable per-workflow, not just global.
- **Depends on:** Phase 2a (OPA Loop implementation).

## TODO-7: Implement WebSocket transport for remote mode

- **What:** WebSocket transport as the primary remote communication protocol, replacing HTTP/SSE.
- **Why:** Performance review showed HTTP/SSE adds 50-100ms latency per tool call. WebSocket provides persistent, bidirectional, lower-overhead communication. The user chose WebSocket over HTTP/SSE.
- **Pros:** Lower latency; persistent connection; supports multiplexing; better for high-frequency tool calls.
- **Cons:** Adds WebSocket server/client complexity; needs connection management (reconnect, heartbeat, backpressure).
- **Context:** Use `websockets` library or FastAPI's built-in WebSocket support. Protocol: JSON-RPC frames over WebSocket. Include heartbeat/ping-pong for connection liveness. Implement exponential backoff reconnection on the engine side.
- **Depends on:** Phase 1a (agent interface) and Phase 4a (remote serve).

## TODO-8: Add incremental snapshot with mtime cache

- **What:** `snapshot` tool that tracks last-modified times and only returns changed files on subsequent calls.
- **Why:** Performance review showed walking the full workspace on every cycle is O(n) and expensive for large codebases (100-500ms per call).
- **Pros:** Near-instant subsequent snapshots; reduces OPA loop latency significantly.
- **Cons:** mtime can be unreliable on some filesystems (VMs, network mounts); clock skew can cause stale data.
- **Context:** Agent maintains an in-memory cache of `{path: mtime}` from the last snapshot. On subsequent calls, only walks directories and returns files where `st_mtime > cached_mtime`. Include a `force_full=True` parameter to bypass the cache. Document the clock skew risk.
- **Depends on:** Phase 1a (agent implementation).

## TODO-9: Add configurable evaluator decision cache

- **What:** Cache evaluator LLM decisions keyed by (fragment hash + goal hash) with TTL.
- **Why:** The OPA loop makes 2 LLM calls per cycle (planner + evaluator). For a 10-cycle workflow, that's 20 LLM calls. At $3/M tokens, this is ~$0.30/workflow. The user chose a configurable evaluator cache.
- **Pros:** Cuts evaluator calls by ~60% for repetitive workflows; reduces cost significantly.
- **Cons:** Cached decisions may be stale if the environment changes between cycles; adds cache invalidation complexity.
- **Context:** Use an in-memory LRU cache (or Redis for distributed engines). Key: hash of (fragment nodes + goal + observation hash). TTL: 1 hour. Configurable via `EngineSettings.EVALUATOR_CACHE_ENABLED` and `EVALUATOR_CACHE_TTL_SECONDS`.
- **Depends on:** Phase 2a (OPA Loop + Evaluator implementation).

## TODO-10: Refactor BaseToolkit to add execute via driver interface

- **What:** Add driver-based execution to toolkits without breaking the frozen `ToolDefinition` dataclass.
- **Why:** The plan says toolkits become executable, but `ToolDefinition` is `@dataclass(frozen=True)` and `BaseToolkit` has no `execute` method. The outside voice flagged this as a breaking change.
- **Pros:** Toolkits are testable with mock drivers; execution backend is pluggable.
- **Cons:** Breaking change to existing toolkit implementations; all toolkits need new execute logic.
- **Context:** Introduce a `BaseDriver` ABC with methods like `read_file`, `run_command`, `http_get`. `BaseToolkit` gains an abstract `execute(name: str, args: dict, driver: BaseDriver) -> dict` method. `ToolDefinition` stays frozen (schema-only). The agent creates the appropriate driver and passes it to `toolkit.execute()`.
- **Depends on:** Phase 1a (agent + driver interface design).

## TODO-11: Implement M&A Due Diligence example

- **What:** Full example with 9 services (Elasticsearch, MinIO, OCR, patent APIs, valuation engine), 6 parallel workstreams, document ingestion, and live patent validity checks.
- **Why:** Proves Celeste handles complex multi-domain legal/financial workflows with adversarial data and recursive discovery.
- **Pros:** Rich demo covering legal, financial, tax, environmental, IP, and HR domains; most comprehensive showcase of multi-workstream parallelism.
- **Cons:** 9 Docker services, 2-4 hour runtime, ~$4.50 LLM cost, requires live patent APIs (USPTO/EPO/JPO) with rate limits and fallbacks.
- **Context:** Deferred from 2026-06-11 scope reduction. Depends on evaluation module and pharma example being stable. The seed data needs real PDF contracts, financial statements, and follow-up documents.
- **Depends on:** This PR (evaluation module + pharma example) must be complete and verified.

## TODO-12: Implement Urban Infrastructure example

- **What:** Full example with GIS/PostGIS, hydrology simulation (shallow-water equations on DEM grid), 50 neighborhood sub-workflows, contractor bidding, FEMA funding, and City Council approval gates.
- **Why:** Proves Celeste handles geospatial data, scientific simulation, budget optimization, and democratic governance workflows.
- **Pros:** Most impressive demo; real hydrology simulation; multi-stakeholder coordination.
- **Cons:** 15-30 min hydrology simulation per run, 9 Docker services, ~$3 LLM cost, complex seed data (GeoTIFF, TIGER/Line shapefiles, FEMA flood zones).
- **Context:** Deferred from 2026-06-11 scope reduction. Depends on evaluation module and pharma example being stable. The simulation workspace is specialized and may need custom workspace type.
- **Depends on:** This PR (evaluation module + pharma example) must be complete and verified.

## TODO-13: Fix OPA loop history memory leak

- **What:** `OPALoop.run()` appends full observation + fragment + execution result to an in-memory `history` list every cycle. For long workflows this grows unbounded and may OOM.
- **Why:** Found by outside voice review. A 23-cycle pharma workflow with real observations could consume hundreds of MB in history alone.
- **Pros:** Prevents OOM crashes on long workflows; reduces memory footprint.
- **Cons:** Truncating history may reduce planner context quality. Need a smart summarization strategy.
- **Context:** Current code at `opa_loop.py:180-260` appends to `history` with no size limit. Fix: keep last 5 cycles in full + condensed summary of earlier cycles. Summarize by keeping only node names, decision, and token count.
- **Depends on:** This PR (OPA loop integration with workflow engine).

## TODO-14: Add model agnosticism verification

- **What:** Run the pharma example with at least 2 different LLM providers (e.g., Anthropic + OpenAI) and verify structural parity.
- **Why:** Success criterion requires the example to pass with at least 2 real LLM providers.
- **Pros:** Validates that Celeste is not coupled to a single provider's quirks.
- **Cons:** Non-deterministic LLM output means runs will differ; requires running example twice ($3+ cost); may need temperature=0 and retry logic.
- **Context:** The cross-mode parity criterion was changed from hash-based to structural parity during review. Model agnosticism should use the same structural comparison. Best done as CI nightly or pre-release gate.
- **Depends on:** Pharma example completion.

## TODO-15: Generate CMC visual mockups before Phase 1 implementation

- **What:** Configure `OPENAI_API_KEY` for the gstack designer and generate visual mockup variants for the Dashboard, Workflow Overview, and Constellation views. Run them through the AI slop checklist and capture an approved direction.
- **Why:** The design plan is text-only right now. Implementers will build from descriptions, and we have no way to verify the observatory aesthetic doesn't look like a generic AI dashboard until we see it.
- **Pros:** Catches aesthetic problems before code; gives implementers a concrete visual reference; verifies anti-patterns are avoided.
- **Cons:** Requires an OpenAI API key and image-generation credits; adds a planning day before coding starts.
- **Context:** Run `~/.claude/skills/gstack/design/dist/design setup` or set `OPENAI_API_KEY`, then use `$D variants` and `$D compare` to generate and review options. Reference `DESIGN.md` for tokens and `docs/superpowers/specs/2026-06-12-monitoring-ui-design-plan.md` §2.4 for the anti-pattern checklist.
- **Depends on:** Design plan approval and access to an OpenAI API key.

## TODO-16: Create SVG assets for empty-state illustrations

- **What:** Create the SVG line-art assets defined in the design plan §6.16 for key empty states: observatory dome, empty starfield, silent telescope, empty docking port, blank crosshair sky, telescope lens cap.
- **Why:** Empty states are features. A text-only empty state feels abandoned; a small, on-brand illustration makes the product feel intentional.
- **Pros:** Improves first-run experience; reinforces the observatory metaphor; reduces operator confusion.
- **Cons:** Requires illustration time; must respect the dark palette and not feel emoji-like or stock.
- **Context:** Design specs are complete in §6.16: minimal line art in `--space-300` / `--aurora-500`, no gradients, no decorative blobs, 120×120 px bounding box. Each illustration should include a primary action button.
- **Depends on:** DESIGN.md approval and visual direction from TODO-15.

## TODO-17: Schedule post-implementation design review

- **What:** After Phase 1 implementation is complete and approved mockups exist (TODO-15), run `/design-review` to visually QA the built UI against the plan, DESIGN.md, and approved mockups.
- **Why:** Text plans drift from real implementations. A visual audit catches spacing, color, hierarchy, and interaction regressions that code review misses.
- **Pros:** Ensures the shipped UI matches the intentional design; catches AI slop that crept in during implementation.
- **Cons:** Requires a working build and a browser; adds review time; cannot run until there is something to screenshot.
- **Context:** Target the review after Dashboard + Workflows list + Workflow overview are functional (end of Phase 1). Include the Constellation view if mockups are approved before then. Update this TODO's status once Phase 1 is ready.
- **Depends on:** Completion of Phase 1 implementation and TODO-15 mockups.

## TODO-18: Implement real LLM token tracking

- **What:** Replace the hardcoded `+= 100` token heuristic in `OPALoop` with actual prompt + completion token counts from LLM client responses. Persist real usage in `WorkflowEvent` and `WorkflowResult`.
- **Why:** The token burn chart in the OPA Loop view requires real data. Synthetic token counts mislead operators and undermine trust.
- **Pros:** Accurate cost/usage visibility; enables future cost budgeting; makes the token burn chart meaningful.
- **Cons:** Requires touching every LLM provider client (Anthropic, OpenAI, Google); response formats differ; needs graceful fallback if provider does not return usage.
- **Context:** Added to Phase 0 after outside voice review. The metrics endpoint (`GET /api/workflows/{id}/metrics`) depends on this.
- **Depends on:** Phase 0 backend work.

## TODO-19: Add workflow retention policy and cleanup

- **What:** Add `WORKFLOW_RETENTION_DAYS` to `EngineSettings`, implement a background cleanup task that archives/deletes old workflows and their events, and add `status`/`created_after` filters to `GET /api/workflows`.
- **Why:** Workflows are never deleted today. The database grows unbounded, degrading the Workflows list and Dashboard over time.
- **Pros:** Predictable database size; faster list queries; clearer operator view of recent workflows.
- **Cons:** Adds a background task; need to decide archive vs. hard delete; cleanup must not race with running workflows.
- **Context:** Added to Phase 0 after outside voice review. Cleanup should respect checkpoint lineage (`parent_workflow_id`).
- **Depends on:** Phase 0 backend work.

## TODO-20: Add checkpoint lineage to Workflow model

- **What:** Add `parent_workflow_id` to the `Workflow` SQLAlchemy model, populate it in `CheckpointManager`, and expose it in the API so the UI can show "continued as" links.
- **Why:** `CheckpointManager` creates new workflow runs when event thresholds are hit. Without lineage, operators lose track of workflows they were monitoring.
- **Pros:** Maintains operator mental model; enables workflow history tracing; required for retention policy to handle checkpoint chains correctly.
- **Cons:** Schema migration; need to update checkpoint logic and API schemas.
- **Context:** Added to Phase 0 after outside voice review. Also consider adding an index on `parent_workflow_id`.
- **Depends on:** Phase 0 backend work.

## TODO-21: Add monitoring app CI/CD pipeline

- **What:** Create `.github/workflows/monitoring.yml` to lint, type-check, build, and test the `monitoring/` Next.js app on PR/push. Include a `monitoring/Dockerfile` and docker-compose override.
- **Why:** The monitoring app is a new deployable artifact. Without CI, the build rots and nobody can deploy it.
- **Pros:** Reliable builds; catches TypeScript/type errors early; enables containerized deployment.
- **Cons:** Adds CI maintenance; need to choose npm/bun/pnpm and Node version.
- **Context:** Added to Phase 1 after eng review. Align package manager with the rest of the repo.
- **Depends on:** Next.js project scaffold in Phase 1.

