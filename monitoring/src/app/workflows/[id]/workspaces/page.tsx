"use client";

import { Shell } from "@/components/shell/shell";
import { Panel } from "@/components/ui/panel";
import { Badge } from "@/components/ui/badge";
import { StatusOrb } from "@/components/ui/status-orb";
import {
  useWorkflow,
  useWorkflowMetrics,
} from "@/hooks/useWorkflow";
import { useWorkflowEvents } from "@/hooks/useWorkflowEvents";
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard";
import { formatTimestamp, formatDuration } from "@/lib/format";
import { statusOrbVariant, statusBadgeVariant } from "@/lib/workflowStatus";
import { WorkflowNav } from "@/components/workflow/workflow-nav";
import { WorkspaceChart } from "@/components/charts/workspace-chart";
import type { ConcurrencyPoint } from "@/components/charts/workspace-chart";
import { cn } from "@/lib/utils";
import ArrowLeft from "lucide-react/dist/esm/icons/arrow-left";
import Copy from "lucide-react/dist/esm/icons/copy";
import Boxes from "lucide-react/dist/esm/icons/boxes";
import Activity from "lucide-react/dist/esm/icons/activity";
import AlertTriangle from "lucide-react/dist/esm/icons/alert-triangle";
import GitBranch from "lucide-react/dist/esm/icons/git-branch";
import Eye from "lucide-react/dist/esm/icons/eye";
import Play from "lucide-react/dist/esm/icons/play";
import Square from "lucide-react/dist/esm/icons/square";
import Link from "next/link";
import { Suspense, use, useState, useMemo } from "react";

// ------------------------------------------------------------------
// Types
// ------------------------------------------------------------------

interface LifecycleRow {
  id: string;
  eventType: "WORKSPACE_SPAWN" | "WORKSPACE_DESTROY";
  timestamp: string;
  durationMs: number | null;
  nodeName: string | null;
  status: string;
}

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

function getNodeNameFromEventData(eventData: Record<string, unknown> | null): string | null {
  if (!eventData) return null;
  const node = eventData.node;
  if (typeof node === "string") return node;
  const nodeName = eventData.node_name;
  if (typeof nodeName === "string") return nodeName;
  const nodeId = eventData.node_id;
  if (typeof nodeId === "string") return nodeId;
  return null;
}

/**
 * Compute concurrency over time from sorted spawn/destroy events.
 * Returns data points at every event timestamp showing the running count
 * immediately after that event.
 */
function computeConcurrencySeries(
  events: { id: string; event_type: string; event_data: Record<string, unknown> | null; timestamp: string }[]
): ConcurrencyPoint[] {
  const sorted = [...events].sort(
    (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
  );

  let running = 0;
  const points: ConcurrencyPoint[] = [];

  for (const event of sorted) {
    if (event.event_type === "WORKSPACE_SPAWN") {
      running += 1;
    } else if (event.event_type === "WORKSPACE_DESTROY") {
      running = Math.max(0, running - 1);
    }
    points.push({
      timestamp: event.timestamp,
      concurrency: running,
    });
  }

  return points;
}

/**
 * Build lifecycle rows from spawn/destroy events.
 * For each destroy, try to find the most recent unmatched spawn and compute duration.
 */
function buildLifecycleRows(
  events: { id: string; event_type: string; event_data: Record<string, unknown> | null; timestamp: string }[]
): LifecycleRow[] {
  const sorted = [...events].sort(
    (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
  );

  const rows: LifecycleRow[] = [];
  const unmatchedSpawns: Map<string, typeof sorted[number]> = new Map();

  for (const event of sorted) {
    if (event.event_type === "WORKSPACE_SPAWN") {
      unmatchedSpawns.set(event.id, event);
      rows.push({
        id: event.id,
        eventType: "WORKSPACE_SPAWN",
        timestamp: event.timestamp,
        durationMs: null,
        nodeName: getNodeNameFromEventData(event.event_data),
        status: "spawned",
      });
    } else if (event.event_type === "WORKSPACE_DESTROY") {
      // Find most recent unmatched spawn
      let matchedSpawnId: string | null = null;
      for (const [spawnId] of unmatchedSpawns) {
        matchedSpawnId = spawnId;
        break;
      }

      const spawnTime = matchedSpawnId ? new Date(unmatchedSpawns.get(matchedSpawnId)!.timestamp).getTime() : null;
      const destroyTime = new Date(event.timestamp).getTime();
      const durationMs = spawnTime ? destroyTime - spawnTime : null;

      if (matchedSpawnId) {
        unmatchedSpawns.delete(matchedSpawnId);
      }

      rows.push({
        id: event.id,
        eventType: "WORKSPACE_DESTROY",
        timestamp: event.timestamp,
        durationMs,
        nodeName: getNodeNameFromEventData(event.event_data),
        status: "destroyed",
      });
    }
  }

  return rows.reverse();
}

// ------------------------------------------------------------------
// Main Page
// ------------------------------------------------------------------

export default function WorkspacesPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  return (
    <Suspense fallback={<Shell><div className="space-y-4"><div className="h-8 w-64 bg-space-700/50 rounded animate-pulse" /></div></Shell>}>
      <WorkspacesPageInner params={params} />
    </Suspense>
  );
}

function WorkspacesPageInner({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const { data: workflow, isLoading: wfLoading, error: wfError } = useWorkflow(id);
  const { data: metrics } = useWorkflowMetrics(id);
  const {
    data: spawnEvents,
    isLoading: spawnLoading,
    error: spawnError,
  } = useWorkflowEvents(id, {
    event_type: "WORKSPACE_SPAWN",
    limit: 200,
  });
  const {
    data: destroyEvents,
    isLoading: destroyLoading,
    error: destroyError,
  } = useWorkflowEvents(id, {
    event_type: "WORKSPACE_DESTROY",
    limit: 200,
  });

  const allEvents = useMemo(() => {
    const spawns = spawnEvents ?? [];
    const destroys = destroyEvents ?? [];
    return [...spawns, ...destroys];
  }, [spawnEvents, destroyEvents]);

  const concurrencyData = useMemo(() => computeConcurrencySeries(allEvents), [allEvents]);

  const lifecycleRows = useMemo(() => buildLifecycleRows(allEvents), [allEvents]);

  const totalSpawns = spawnEvents?.length ?? 0;
  const totalDestroys = destroyEvents?.length ?? 0;
  const hasLeak = totalSpawns !== totalDestroys;
  const activeWorkspaces = Math.max(0, totalSpawns - totalDestroys);
  const peakConcurrency = metrics?.max_concurrent_workspaces ?? null;

  const isLoading = wfLoading || spawnLoading || destroyLoading;
  const error = wfError || spawnError || destroyError;

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
          <span className="text-comet-300">Workspaces</span>
        </div>

        {/* Loading */}
        {isLoading && (
          <div className="space-y-4">
            <div className="h-8 w-64 bg-space-700/50 rounded animate-pulse" />
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div className="h-20 bg-space-700/50 rounded animate-pulse" />
              <div className="h-20 bg-space-700/50 rounded animate-pulse" />
              <div className="h-20 bg-space-700/50 rounded animate-pulse" />
              <div className="h-20 bg-space-700/50 rounded animate-pulse" />
            </div>
            <div className="h-64 bg-space-700/50 rounded animate-pulse" />
            <div className="h-48 bg-space-700/50 rounded animate-pulse" />
          </div>
        )}

        {/* Error */}
        {!isLoading && error && (
          <Panel className="text-center py-12">
            <p className="text-mars-400 text-sm">
              Failed to load workspace data:{" "}
              {error instanceof Error ? error.message : "Unknown error"}
            </p>
          </Panel>
        )}

        {/* Empty: no workflow */}
        {!isLoading && !error && !workflow && (
          <Panel className="text-center py-12">
            <p className="text-comet-500">Workflow not found</p>
          </Panel>
        )}

        {/* Empty: no workspaces */}
        {!isLoading && !error && workflow && allEvents.length === 0 && (
          <div className="space-y-6">
            {/* Header */}
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div className="flex items-start gap-4">
                <StatusOrb
                  variant={statusOrbVariant(workflow.status)}
                  size="lg"
                  pulse={workflow.status === "running"}
                />
                <div>
                  <h1 className="text-3xl font-display text-comet-100">
                    {workflow.name}
                  </h1>
                  <div className="flex items-center gap-3 mt-2 flex-wrap">
                    <Badge variant={statusBadgeVariant(workflow.status)}>
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
            <WorkflowNav activeTab="workspaces" />

            <Panel className="text-center py-12">
              <Eye className="w-6 h-6 mx-auto mb-2 text-comet-500 opacity-50" />
              <p className="text-comet-500 text-sm">No workspaces spawned</p>
              <p className="text-comet-600 text-xs mt-1">
                Workspaces will appear here once the workflow begins spawning them.
              </p>
            </Panel>
          </div>
        )}

        {/* Main content */}
        {!isLoading && !error && workflow && allEvents.length > 0 && (
          <div className="space-y-6">
            {/* Header */}
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div className="flex items-start gap-4">
                <StatusOrb
                  variant={statusOrbVariant(workflow.status)}
                  size="lg"
                  pulse={workflow.status === "running"}
                />
                <div>
                  <h1 className="text-3xl font-display text-comet-100">
                    {workflow.name}
                  </h1>
                  <div className="flex items-center gap-3 mt-2 flex-wrap">
                    <Badge variant={statusBadgeVariant(workflow.status)}>
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
            <WorkflowNav activeTab="workspaces" />

            {/* Leak alert */}
            {hasLeak && (
              <div
                role="alert"
                aria-live="assertive"
                className="rounded-lg border border-mars-500/40 bg-mars-900/30 p-4 flex items-start gap-3"
              >
                <AlertTriangle className="w-5 h-5 text-mars-400 shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm font-medium text-mars-300">
                    Workspace leak detected
                  </p>
                  <p className="text-xs text-mars-400 mt-1">
                    {totalSpawns} workspace{totalSpawns !== 1 ? "s" : ""} spawned but only{" "}
                    {totalDestroys} destroyed. {activeWorkspaces} workspace
                    {activeWorkspaces !== 1 ? "s" : ""} may still be running.
                  </p>
                </div>
              </div>
            )}

            {/* KPI Strip */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <KpiCard
                label="Peak Concurrency"
                value={peakConcurrency ?? "—"}
                icon={Activity}
                variant="info"
              />
              <KpiCard
                label="Active Workspaces"
                value={activeWorkspaces}
                icon={Boxes}
                variant={activeWorkspaces > 0 ? "success" : "default"}
              />
              <KpiCard
                label="Total Spawns"
                value={totalSpawns}
                icon={Play}
                variant="success"
              />
              <KpiCard
                label="Total Destroys"
                value={totalDestroys}
                icon={Square}
                variant={hasLeak ? "danger" : "default"}
              />
            </div>

            {/* Concurrency Chart */}
            <Panel variant="elevated" padding="lg">
              <h3 className="text-sm font-medium text-comet-200 mb-4 flex items-center gap-2">
                <GitBranch className="w-4 h-4 text-aurora-400" />
                Concurrency Over Time
              </h3>
              <WorkspaceChart
                data={concurrencyData}
                peakConcurrency={peakConcurrency}
              />
            </Panel>

            {/* Lifecycle Table */}
            <Panel variant="elevated" padding="lg">
              <h3 className="text-sm font-medium text-comet-200 mb-4 flex items-center gap-2">
                <Boxes className="w-4 h-4 text-nebula-400" />
                Workspace Lifecycle
              </h3>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-space-600">
                      <th className="text-left py-2 px-3 text-xs font-medium text-comet-400 uppercase tracking-wider">
                        Event
                      </th>
                      <th className="text-left py-2 px-3 text-xs font-medium text-comet-400 uppercase tracking-wider">
                        Timestamp
                      </th>
                      <th className="text-left py-2 px-3 text-xs font-medium text-comet-400 uppercase tracking-wider">
                        Duration
                      </th>
                      <th className="text-left py-2 px-3 text-xs font-medium text-comet-400 uppercase tracking-wider">
                        Node
                      </th>
                      <th className="text-left py-2 px-3 text-xs font-medium text-comet-400 uppercase tracking-wider">
                        Status
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {lifecycleRows.map((row) => (
                      <tr
                        key={row.id}
                        className="border-b border-space-700/50 hover:bg-space-700/30 transition-colors"
                      >
                        <td className="py-2 px-3">
                          <Badge
                            variant={
                              row.eventType === "WORKSPACE_SPAWN"
                                ? "success"
                                : "danger"
                            }
                            className="text-[10px]"
                          >
                            {row.eventType === "WORKSPACE_SPAWN" ? (
                              <Play className="w-3 h-3 mr-1" />
                            ) : (
                              <Square className="w-3 h-3 mr-1" />
                            )}
                            {row.eventType === "WORKSPACE_SPAWN"
                              ? "Spawn"
                              : "Destroy"}
                          </Badge>
                        </td>
                        <td className="py-2 px-3 font-mono text-xs text-comet-300">
                          {formatTimestamp(row.timestamp)}
                        </td>
                        <td className="py-2 px-3 font-mono text-xs text-comet-300">
                          {row.durationMs !== null
                            ? formatDuration(row.durationMs)
                            : row.eventType === "WORKSPACE_DESTROY"
                            ? "—"
                            : "Running"}
                        </td>
                        <td className="py-2 px-3 text-xs text-comet-300">
                          {row.nodeName ?? "—"}
                        </td>
                        <td className="py-2 px-3">
                          <span
                            className={cn(
                              "text-xs font-medium",
                              row.status === "spawned"
                                ? "text-aurora-400"
                                : "text-mars-400"
                            )}
                          >
                            {row.status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          </div>
        )}
      </div>
    </Shell>
  );
}
