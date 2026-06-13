"use client";

import { Shell } from "@/components/shell/shell";
import { Panel } from "@/components/ui/panel";
import { Badge } from "@/components/ui/badge";
import { StatusOrb } from "@/components/ui/status-orb";
import {
  useWorkflow,
  useWorkflowMetrics,
} from "@/hooks/useWorkflow";
import { useWorkflowEvents, useWorkflowWorkflowEvents } from "@/hooks/useWorkflowEvents";
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard";
import { formatTimestamp, formatDuration } from "@/lib/format";
import { WorkflowNav } from "@/components/workflow/workflow-nav";
import { cn } from "@/lib/utils";
import ArrowLeft from "lucide-react/dist/esm/icons/arrow-left";
import Copy from "lucide-react/dist/esm/icons/copy";
import RotateCcw from "lucide-react/dist/esm/icons/rotate-ccw";
import Layers from "lucide-react/dist/esm/icons/layers";
import Clock from "lucide-react/dist/esm/icons/clock";
import Shield from "lucide-react/dist/esm/icons/shield";
import Activity from "lucide-react/dist/esm/icons/activity";
import GitBranch from "lucide-react/dist/esm/icons/git-branch";
import Eye from "lucide-react/dist/esm/icons/eye";
import FileJson from "lucide-react/dist/esm/icons/file-json";
import CheckCircle2 from "lucide-react/dist/esm/icons/check-circle-2";
import ChevronRight from "lucide-react/dist/esm/icons/chevron-right";
import Sparkles from "lucide-react/dist/esm/icons/sparkles";
import Minus from "lucide-react/dist/esm/icons/minus";
import Link from "next/link";
import { Suspense, use, useState, useMemo, useEffect, useRef } from "react";
import { CycleChart } from "@/components/charts/cycle-chart";
import type { CycleData } from "@/components/charts/cycle-chart";

// ------------------------------------------------------------------
// Types
// ------------------------------------------------------------------

interface Cycle {
  cycleNumber: number;
  observation: string;
  planFragment: string;
  evaluatorDecision: string;
  timestamp: string;
  tokenCount: number | null;
  durationMs: number | null;
  nodeCount: number;
  eventIds: string[];
}

// ------------------------------------------------------------------
// Constants
// ------------------------------------------------------------------

const OPA_CYCLE_EVENT_TYPES = [
  "observation_captured",
  "plan_generated",
  "evaluation_result",
  "cycle_started",
  "workflow_paused",
  "workflow_resumed",
];

// ------------------------------------------------------------------
// Helpers
// ------------------------------------------------------------------

function CopyButton({ text }: { text: string }) {
  const { copy } = useCopyToClipboard();
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={() => {
        copy(text, "workflow ID");
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
      className="inline-flex items-center gap-1 text-xs font-mono text-comet-500 hover:text-aurora-400 transition-colors"
      title="Copy ID"
    >
      <Copy className="w-3 h-3" />
      {copied ? "Copied" : text.slice(0, 8)}
    </button>
  );
}

function getObservationSummary(eventData: Record<string, unknown> | null): string {
  if (!eventData) return "No observation data";
  const goal = eventData.goal;
  if (typeof goal === "string") return goal;
  const summary = eventData.summary;
  if (typeof summary === "string") return summary;
  const observation = eventData.observation;
  if (typeof observation === "string") return observation;
  return "Observation recorded";
}

function getPlanFragment(eventData: Record<string, unknown> | null): string {
  if (!eventData) return "No plan data";
  const fragment = eventData.fragment;
  if (typeof fragment === "string") return fragment;
  const plan = eventData.plan;
  if (typeof plan === "string") return plan;
  if (typeof plan === "object" && plan !== null) {
    try {
      return JSON.stringify(plan, null, 2);
    } catch {
      return "Plan data (unserializable)";
    }
  }
  return "Plan generated";
}

function getEvaluatorDecision(eventData: Record<string, unknown> | null): string {
  if (!eventData) return "No evaluation data";
  const decision = eventData.decision;
  if (typeof decision === "string") return decision;
  const outcome = eventData.outcome;
  if (typeof outcome === "string") return outcome;
  return "Evaluation complete";
}

function getTokenCount(eventData: Record<string, unknown> | null): number | null {
  if (!eventData) return null;
  const tokens = eventData.tokens;
  if (typeof tokens === "number") return tokens;
  const tokenCount = eventData.token_count;
  if (typeof tokenCount === "number") return tokenCount;
  return null;
}

function getNodeCountFromPlan(eventData: Record<string, unknown> | null): number {
  if (!eventData) return 0;
  const plan = eventData.plan;
  if (Array.isArray(plan)) return plan.length;
  if (typeof plan === "object" && plan !== null) {
    const nodes = (plan as Record<string, unknown>).nodes;
    if (Array.isArray(nodes)) return nodes.length;
    const steps = (plan as Record<string, unknown>).steps;
    if (Array.isArray(steps)) return steps.length;
  }
  const fragment = eventData.fragment;
  if (typeof fragment === "string") {
    // Rough heuristic: count node-like mentions
    const matches = fragment.match(/node|step|task/gi);
    return matches ? Math.min(matches.length, 20) : 0;
  }
  return 0;
}

function extractNodeNamesFromPlan(eventData: Record<string, unknown> | null): string[] {
  if (!eventData) return [];
  const plan = eventData.plan;
  if (Array.isArray(plan)) {
    return plan
      .map((p) => (typeof p === "string" ? p : (p as Record<string, unknown>)?.name))
      .filter((n): n is string => typeof n === "string");
  }
  if (typeof plan === "object" && plan !== null) {
    const nodes = (plan as Record<string, unknown>).nodes;
    if (Array.isArray(nodes)) {
      return nodes
        .map((n) => (typeof n === "string" ? n : (n as Record<string, unknown>)?.name))
        .filter((n): n is string => typeof n === "string");
    }
    const steps = (plan as Record<string, unknown>).steps;
    if (Array.isArray(steps)) {
      return steps
        .map((s) => (typeof s === "string" ? s : (s as Record<string, unknown>)?.name))
        .filter((n): n is string => typeof n === "string");
    }
  }
  const fragment = eventData.fragment;
  if (typeof fragment === "string") {
    // Try to extract quoted names or bullet points
    const lines = fragment
      .split(/\n/)
      .map((l) => l.replace(/^[-*\d.]+\s*/, "").trim())
      .filter((l) => l.length > 0 && l.length < 100);
    return lines.slice(0, 20);
  }
  return [];
}

function parseCycles(events: { id: string; event_type: string; event_data: Record<string, unknown> | null; timestamp: string }[]): Cycle[] {
  const sorted = [...events].sort(
    (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
  );

  const cycles: Cycle[] = [];
  let currentCycle: Partial<Cycle> & { eventIds: string[] } | null = null;

  for (let i = 0; i < sorted.length; i++) {
    const event = sorted[i];
    const isCycleStart = event.event_type === "observation_captured" || event.event_type === "cycle_started";

    if (isCycleStart && currentCycle) {
      // Finalize previous cycle
      const startTime = new Date(currentCycle.timestamp!).getTime();
      const endTime = new Date(event.timestamp).getTime();
      cycles.push({
        ...currentCycle,
        durationMs: endTime - startTime,
      } as Cycle);
      currentCycle = null;
    }

    if (isCycleStart) {
      currentCycle = {
        cycleNumber: cycles.length + 1,
        observation: getObservationSummary(event.event_data),
        planFragment: "",
        evaluatorDecision: "",
        timestamp: event.timestamp,
        tokenCount: getTokenCount(event.event_data),
        durationMs: null,
        nodeCount: getNodeCountFromPlan(event.event_data),
        eventIds: [event.id],
      };
    } else if (currentCycle) {
      currentCycle.eventIds.push(event.id);
      if (event.event_type === "plan_generated") {
        currentCycle.planFragment = getPlanFragment(event.event_data);
        currentCycle.nodeCount = getNodeCountFromPlan(event.event_data);
      } else if (event.event_type === "evaluation_result") {
        currentCycle.evaluatorDecision = getEvaluatorDecision(event.event_data);
        if (currentCycle.tokenCount === null) {
          currentCycle.tokenCount = getTokenCount(event.event_data);
        }
      }
    }
  }

  if (currentCycle) {
    cycles.push({
      ...currentCycle,
      durationMs: null,
    } as Cycle);
  }

  // Compute duration for last cycle from last event in cycle to overall last event if available
  if (cycles.length > 0 && cycles[cycles.length - 1].durationMs === null && sorted.length > 0) {
    const lastCycle = cycles[cycles.length - 1];
    const lastEventTime = new Date(sorted[sorted.length - 1].timestamp).getTime();
    const cycleStartTime = new Date(lastCycle.timestamp).getTime();
    lastCycle.durationMs = lastEventTime - cycleStartTime;
  }

  return cycles;
}

// ------------------------------------------------------------------
// Plan Diff
// ------------------------------------------------------------------

function PlanDiff({
  currentNodes,
  previousNodes,
}: {
  currentNodes: string[];
  previousNodes: string[];
}) {
  const added = currentNodes.filter((n) => !previousNodes.includes(n));
  const removed = previousNodes.filter((n) => !currentNodes.includes(n));
  const unchanged = currentNodes.filter((n) => previousNodes.includes(n));

  if (added.length === 0 && removed.length === 0 && unchanged.length === 0) {
    return (
      <div className="text-xs text-comet-500 italic">
        No plan nodes available for comparison
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {added.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          <span className="text-[10px] text-nebula-400 uppercase tracking-wider w-full">
            Added
          </span>
          {added.map((n) => (
            <Badge key={n} variant="info" className="text-[10px]">
              <Sparkles className="w-3 h-3 mr-1" />
              {n}
            </Badge>
          ))}
        </div>
      )}
      {removed.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          <span className="text-[10px] text-mars-400 uppercase tracking-wider w-full">
            Removed
          </span>
          {removed.map((n) => (
            <Badge key={n} variant="danger" className="text-[10px]">
              <Minus className="w-3 h-3 mr-1" />
              {n}
            </Badge>
          ))}
        </div>
      )}
      {unchanged.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          <span className="text-[10px] text-comet-400 uppercase tracking-wider w-full">
            Unchanged
          </span>
          {unchanged.map((n) => (
            <Badge key={n} variant="default" className="text-[10px]">
              {n}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------
// KpiCard (inline, same pattern as main page)
// ------------------------------------------------------------------

function KpiCard({
  label,
  value,
  icon: Icon,
  variant = "default",
}: {
  label: string;
  value: string | number;
  icon: React.ElementType;
  variant?: "default" | "success" | "warning" | "danger" | "info";
}) {
  const colorMap = {
    default: "text-comet-300",
    success: "text-aurora-400",
    warning: "text-solar-400",
    danger: "text-mars-400",
    info: "text-nebula-400",
  };
  return (
    <Panel padding="md" className="flex items-center gap-3">
      <div className={cn("p-1.5 rounded-md bg-space-700", colorMap[variant])}>
        <Icon className="w-4 h-4" />
      </div>
      <div>
        <div className="text-lg font-mono text-comet-100">{value}</div>
        <div className="text-[10px] text-comet-500 uppercase tracking-wider">
          {label}
        </div>
      </div>
    </Panel>
  );
}

// ------------------------------------------------------------------
// Main Page
// ------------------------------------------------------------------

export default function OPALoopPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  return (
    <Suspense
      fallback={
        <Shell>
          <div className="space-y-4">
            <div className="h-8 w-64 bg-space-700/50 rounded animate-pulse" />
          </div>
        </Shell>
      }
    >
      <OPALoopPageInner params={params} />
    </Suspense>
  );
}

function OPALoopPageInner({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const { data: workflow, isLoading: wfLoading, error: wfError } = useWorkflow(id);
  const { data: metrics } = useWorkflowMetrics(id);
  const { data: allEvents, isLoading: eventsLoading, error: eventsError } = useWorkflowWorkflowEvents(id, {
    limit: 200,
  });

  const [selectedCycleIndex, setSelectedCycleIndex] = useState(0);
  const cycleListRef = useRef<HTMLDivElement>(null);

  // Filter OPA cycle events
  const opaEvents = useMemo(() => {
    if (!allEvents) return [];
    return allEvents.filter((e) =>
      OPA_CYCLE_EVENT_TYPES.includes(e.event_type)
    );
  }, [allEvents]);

  // Parse cycles
  const cycles = useMemo(() => parseCycles(opaEvents), [opaEvents]);

  // Build chart data
  const cycleChartData: CycleData[] = useMemo(
    () =>
      cycles.map((c) => ({
        cycleNumber: c.cycleNumber,
        tokenCount: c.tokenCount,
        durationMs: c.durationMs ?? 0,
        nodeCount: c.nodeCount,
        timestamp: c.timestamp,
      })),
    [cycles]
  );

  const hasTokenData = useMemo(
    () => cycles.some((c) => c.tokenCount !== null),
    [cycles]
  );

  // Keyboard navigation
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "ArrowUp" || e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedCycleIndex((prev) => {
          if (e.key === "ArrowUp") {
            return Math.max(0, prev - 1);
          }
          return Math.min(cycles.length - 1, prev + 1);
        });
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [cycles.length]);

  const selectedCycle = cycles[selectedCycleIndex] ?? null;

  const previousCycleNodes = useMemo(() => {
    if (!selectedCycle || selectedCycleIndex <= 0) return [];
    const prevCycle = cycles[selectedCycleIndex - 1];
    if (!prevCycle) return [];
    const prevPlanEvent = opaEvents.find(
      (e) =>
        e.event_type === "plan_generated" &&
        prevCycle.eventIds.includes(e.id)
    );
    return prevPlanEvent ? extractNodeNamesFromPlan(prevPlanEvent.event_data) : [];
  }, [selectedCycle, selectedCycleIndex, cycles, opaEvents]);

  const currentCycleNodes = useMemo(() => {
    if (!selectedCycle) return [];
    const planEvent = opaEvents.find(
      (e) =>
        e.event_type === "plan_generated" &&
        selectedCycle.eventIds.includes(e.id)
    );
    return planEvent ? extractNodeNamesFromPlan(planEvent.event_data) : [];
  }, [selectedCycle, opaEvents]);

  const isLoading = wfLoading || eventsLoading;
  const error = wfError || eventsError;

  return (
    <Shell>
      <div className="space-y-6">
        {/* Breadcrumb */}
        <div className="flex items-center gap-2 text-sm text-comet-500">
          <Link
            href="/workflows"
            className="flex items-center gap-1 hover:text-aurora-400 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            Workflows
          </Link>
          <span>/</span>
          <Link
            href={`/workflows/${id}`}
            className="hover:text-aurora-400 transition-colors"
          >
            {workflow?.name ?? id.slice(0, 8)}
          </Link>
          <span>/</span>
          <span className="text-comet-300">OPA Loop</span>
        </div>

        {/* Loading */}
        {isLoading && (
          <div className="space-y-4">
            <div className="h-8 w-64 bg-space-700/50 rounded animate-pulse" />
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              <div className="h-96 bg-space-700/50 rounded animate-pulse" />
              <div className="h-96 bg-space-700/50 rounded animate-pulse lg:col-span-2" />
            </div>
          </div>
        )}

        {/* Error */}
        {!isLoading && error && (
          <Panel className="text-center py-12">
            <p className="text-mars-400 text-sm">
              Failed to load OPA loop data: {error instanceof Error ? error.message : "Unknown error"}
            </p>
          </Panel>
        )}

        {/* Empty: no workflow */}
        {!isLoading && !error && !workflow && (
          <Panel className="text-center py-12">
            <p className="text-comet-500">Workflow not found</p>
          </Panel>
        )}

        {/* Empty: no cycles */}
        {!isLoading && !error && workflow && cycles.length === 0 && (
          <div className="space-y-6">
            {/* Header */}
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div className="flex items-start gap-4">
                <StatusOrb
                  variant={
                    workflow.status === "running"
                      ? "running"
                      : workflow.status === "completed"
                      ? "success"
                      : workflow.status === "failed"
                      ? "error"
                      : workflow.status === "paused"
                      ? "warning"
                      : "idle"
                  }
                  size="lg"
                  pulse={workflow.status === "running"}
                />
                <div>
                  <h1 className="text-3xl font-display text-comet-100">
                    {workflow.name}
                  </h1>
                  <div className="flex items-center gap-3 mt-2 flex-wrap">
                    <Badge
                      variant={
                        workflow.status === "running"
                          ? "success"
                          : workflow.status === "completed"
                          ? "success"
                          : workflow.status === "failed"
                          ? "danger"
                          : workflow.status === "paused"
                          ? "warning"
                          : "muted"
                      }
                    >
                      {workflow.status}
                    </Badge>
                    <span className="text-xs font-mono text-comet-500">
                      {workflow.id}
                    </span>
                    <CopyButton text={workflow.id} />
                  </div>
                </div>
              </div>
            </div>

            {/* Tab navigation */}
            <WorkflowNav activeTab="opa-loop" />

            <Panel className="text-center py-12">
              <Eye className="w-6 h-6 mx-auto mb-2 text-comet-500 opacity-50" />
              <p className="text-comet-500 text-sm">No OPA cycles recorded yet</p>
              <p className="text-comet-600 text-xs mt-1">
                Cycles will appear once observation or cycle_started events are received.
              </p>
            </Panel>
          </div>
        )}

        {/* Main content */}
        {!isLoading && !error && workflow && cycles.length > 0 && (
          <div className="space-y-6">
            {/* Header */}
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div className="flex items-start gap-4">
                <StatusOrb
                  variant={
                    workflow.status === "running"
                      ? "running"
                      : workflow.status === "completed"
                      ? "success"
                      : workflow.status === "failed"
                      ? "error"
                      : workflow.status === "paused"
                      ? "warning"
                      : "idle"
                  }
                  size="lg"
                  pulse={workflow.status === "running"}
                />
                <div>
                  <h1 className="text-3xl font-display text-comet-100">
                    {workflow.name}
                  </h1>
                  <div className="flex items-center gap-3 mt-2 flex-wrap">
                    <Badge
                      variant={
                        workflow.status === "running"
                          ? "success"
                          : workflow.status === "completed"
                          ? "success"
                          : workflow.status === "failed"
                          ? "danger"
                          : workflow.status === "paused"
                          ? "warning"
                          : "muted"
                      }
                    >
                      {workflow.status}
                    </Badge>
                    <span className="text-xs font-mono text-comet-500">
                      {workflow.id}
                    </span>
                    <CopyButton text={workflow.id} />
                  </div>
                </div>
              </div>
            </div>

            {/* Tab navigation */}
            <WorkflowNav activeTab="opa-loop" />

            {/* KPI Strip */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
              <KpiCard
                label="OPA Cycles"
                value={metrics?.cycle_count ?? cycles.length}
                icon={RotateCcw}
                variant="info"
              />
              <KpiCard
                label="Total Nodes"
                value={metrics?.total_nodes ?? "—"}
                icon={Layers}
              />
              <KpiCard
                label="Completed"
                value={
                  metrics
                    ? `${Math.round(metrics.completed_percent)}%`
                    : "—"
                }
                icon={Activity}
                variant="success"
              />
              <KpiCard
                label="Max Workspaces"
                value={metrics?.max_concurrent_workspaces ?? "—"}
                icon={GitBranch}
              />
              <KpiCard
                label="Security Pass"
                value={
                  metrics?.security_pass_rate !== null &&
                  metrics?.security_pass_rate !== undefined
                    ? `${Math.round(metrics.security_pass_rate * 100)}%`
                    : "—"
                }
                icon={Shield}
                variant={
                  metrics?.security_pass_rate !== null &&
                  metrics?.security_pass_rate !== undefined
                    ? metrics.security_pass_rate >= 0.9
                      ? "success"
                      : metrics.security_pass_rate >= 0.7
                      ? "warning"
                      : "danger"
                    : "default"
                }
              />
            </div>

            {/* Two-column layout: cycle navigator + detail */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              {/* Left: Cycle navigator */}
              <div
                ref={cycleListRef}
                className="space-y-2 max-h-[600px] overflow-y-auto pr-1"
                role="tablist"
                aria-label="OPA cycles"
              >
                {cycles.map((cycle, idx) => {
                  const isSelected = idx === selectedCycleIndex;
                  return (
                    <button
                      key={cycle.cycleNumber}
                      role="tab"
                      aria-selected={isSelected}
                      aria-controls="cycle-detail-panel"
                      id={`cycle-tab-${cycle.cycleNumber}`}
                      onClick={() => setSelectedCycleIndex(idx)}
                      className={cn(
                        "w-full text-left rounded-lg border p-3 transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-aurora-500/50",
                        isSelected
                          ? "bg-space-700 border-aurora-500/40 shadow-md"
                          : "bg-space-800 border-space-600 hover:bg-space-700/50 hover:border-space-500"
                      )}
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span
                            className={cn(
                              "text-xs font-mono font-semibold",
                              isSelected ? "text-aurora-400" : "text-comet-400"
                            )}
                          >
                            Cycle {cycle.cycleNumber}
                          </span>
                          {isSelected && (
                            <ChevronRight className="w-3 h-3 text-aurora-400" />
                          )}
                        </div>
                        <span className="text-[10px] font-mono text-comet-500">
                          {formatTimestamp(cycle.timestamp)}
                        </span>
                      </div>
                      <p className="text-xs text-comet-300 mt-1 line-clamp-2">
                        {cycle.observation}
                      </p>
                      <div className="flex items-center gap-2 mt-2">
                        {cycle.tokenCount !== null && (
                          <span className="text-[10px] font-mono text-aurora-400">
                            {cycle.tokenCount.toLocaleString()} tokens
                          </span>
                        )}
                        {cycle.durationMs !== null && (
                          <span className="text-[10px] font-mono text-comet-500">
                            {formatDuration(cycle.durationMs)}
                          </span>
                        )}
                        {cycle.nodeCount > 0 && (
                          <span className="text-[10px] font-mono text-nebula-400">
                            {cycle.nodeCount} nodes
                          </span>
                        )}
                      </div>
                    </button>
                  );
                })}
              </div>

              {/* Right: Cycle detail */}
              <div className="lg:col-span-2 space-y-4">
                {selectedCycle && (
                  <div
                    id="cycle-detail-panel"
                    role="tabpanel"
                    aria-labelledby={`cycle-tab-${selectedCycle.cycleNumber}`}
                    aria-live="polite"
                  >
                    <Panel variant="elevated" padding="lg" className="space-y-6">
                      {/* Cycle header */}
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3">
                          <Eye className="w-5 h-5 text-aurora-400" />
                          <h2 className="text-lg font-body font-medium text-comet-100">
                            Cycle {selectedCycle.cycleNumber}
                          </h2>
                        </div>
                        <div className="flex items-center gap-3 text-xs font-mono text-comet-500">
                          <span>{formatTimestamp(selectedCycle.timestamp)}</span>
                          {selectedCycle.durationMs !== null && (
                            <Badge variant="muted">
                              <Clock className="w-3 h-3 mr-1" />
                              {formatDuration(selectedCycle.durationMs)}
                            </Badge>
                          )}
                        </div>
                      </div>

                      {/* Observation */}
                      <div className="space-y-2">
                        <div className="flex items-center gap-2 text-sm text-comet-400">
                          <Eye className="w-4 h-4" />
                          <span className="font-medium">Observation</span>
                        </div>
                        <Panel variant="subtle" padding="md">
                          <p className="text-sm text-comet-200 leading-relaxed">
                            {selectedCycle.observation}
                          </p>
                        </Panel>
                      </div>

                      {/* Plan fragment */}
                      <div className="space-y-2">
                        <div className="flex items-center gap-2 text-sm text-comet-400">
                          <FileJson className="w-4 h-4" />
                          <span className="font-medium">Plan</span>
                          {selectedCycle.nodeCount > 0 && (
                            <Badge variant="info" className="text-[10px]">
                              {selectedCycle.nodeCount} nodes
                            </Badge>
                          )}
                        </div>
                        <Panel variant="subtle" padding="md">
                          <pre className="text-xs font-mono text-comet-200 whitespace-pre-wrap overflow-x-auto max-h-64 overflow-y-auto">
                            {selectedCycle.planFragment || "No plan fragment recorded"}
                          </pre>
                        </Panel>
                      </div>

                      {/* Evaluator decision */}
                      <div className="space-y-2">
                        <div className="flex items-center gap-2 text-sm text-comet-400">
                          <CheckCircle2 className="w-4 h-4" />
                          <span className="font-medium">Evaluator Decision</span>
                        </div>
                        <Panel variant="subtle" padding="md">
                          <p className="text-sm text-comet-200">
                            {selectedCycle.evaluatorDecision || "No evaluation recorded"}
                          </p>
                        </Panel>
                      </div>

                      {/* Plan diff */}
                      {selectedCycleIndex > 0 && (
                        <div className="space-y-2">
                          <div className="flex items-center gap-2 text-sm text-comet-400">
                            <GitBranch className="w-4 h-4" />
                            <span className="font-medium">Plan Diff</span>
                            <span className="text-[10px] text-comet-500">
                              vs Cycle {selectedCycleIndex}
                            </span>
                          </div>
                          <Panel variant="subtle" padding="md">
                            <PlanDiff
                              currentNodes={currentCycleNodes}
                              previousNodes={previousCycleNodes}
                            />
                          </Panel>
                        </div>
                      )}

                      {/* Token count */}
                      {selectedCycle.tokenCount !== null && (
                        <div className="flex items-center gap-2">
                          <Badge variant="info" className="text-xs">
                            <Sparkles className="w-3 h-3 mr-1" />
                            {selectedCycle.tokenCount.toLocaleString()} tokens
                          </Badge>
                        </div>
                      )}
                    </Panel>

                    {/* Cycle chart */}
                    <Panel variant="elevated" padding="lg">
                      <h3 className="text-sm font-medium text-comet-200 mb-4 flex items-center gap-2">
                        <Activity className="w-4 h-4 text-aurora-400" />
                        Cycle Metrics
                      </h3>
                      <CycleChart
                        data={cycleChartData}
                        hasTokenData={hasTokenData}
                        budget={metrics?.llm_tokens_accumulated ?? null}
                      />
                    </Panel>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </Shell>
  );
}
