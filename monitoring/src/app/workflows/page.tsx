"use client";

import { Shell } from "@/components/shell/shell";
import { Panel } from "@/components/ui/panel";
import { Badge } from "@/components/ui/badge";
import { StatusOrb } from "@/components/ui/status-orb";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useWorkflows, useWorkflowMetrics } from "@/hooks/useWorkflow";
import type { WorkflowMetrics } from "@/lib/types";
import { useUrlState } from "@/hooks/useUrlState";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { formatRelativeTime } from "@/lib/format";
import { getStatusVariant } from "@/lib/workflowStatus";
import { cn } from "@/lib/utils";
import Clock from "lucide-react/dist/esm/icons/clock";
import RotateCcw from "lucide-react/dist/esm/icons/rotate-ccw";
import ChevronLeft from "lucide-react/dist/esm/icons/chevron-left";
import ChevronRight from "lucide-react/dist/esm/icons/chevron-right";
import Search from "lucide-react/dist/esm/icons/search";
import Orbit from "lucide-react/dist/esm/icons/orbit";
import Layers from "lucide-react/dist/esm/icons/layers";
import X from "lucide-react/dist/esm/icons/x";
import { Suspense, useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

const STATUS_OPTIONS = [
  "all",
  "running",
  "completed",
  "failed",
  "escalated",
  "paused",
  "pending",
  "cancelled",
] as const;
type StatusFilterValue = (typeof STATUS_OPTIONS)[number];

const STATUS_FILTERS: { value: StatusFilterValue; label: string; variant: "success" | "default" | "danger" | "warning" | "muted" | "info" }[] = [
  { value: "running", label: "Running", variant: "success" },
  { value: "completed", label: "Completed", variant: "default" },
  { value: "failed", label: "Failed", variant: "danger" },
  { value: "escalated", label: "Escalated", variant: "danger" },
  { value: "paused", label: "Paused", variant: "warning" },
  { value: "pending", label: "Pending", variant: "muted" },
  { value: "cancelled", label: "Cancelled", variant: "info" },
];

function ProgressArc({ progress }: { progress: number }) {
  const radius = 18;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - progress * circumference;
  return (
    <div className="relative w-10 h-10 shrink-0">
      <svg className="w-10 h-10 -rotate-90" viewBox="0 0 40 40">
        <circle
          cx="20"
          cy="20"
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth="3"
          className="text-space-600"
        />
        <circle
          cx="20"
          cy="20"
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth="3"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          className="text-aurora-400 transition-all duration-500"
        />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center text-[10px] font-mono text-comet-300">
        {Math.round(progress * 100)}%
      </span>
    </div>
  );
}

function WorkflowCardWithMetrics({
  workflow,
  selected,
}: {
  workflow: {
    id: string;
    name: string;
    status: string;
    created_at: string;
  };
  selected?: boolean;
}) {
  // MNT-019: fetch real metrics per workflow instead of forcing zeros.
  // The list-page WorkflowListItem doesn't include progress/cycle_count
  // because the GET /api/workflows list endpoint doesn't return them.
  // We fetch the per-workflow metrics endpoint and merge the result
  // here so each card displays its own live data.
  const { data: metrics } = useWorkflowMetrics(workflow.id);
  return (
    <WorkflowCard
      workflow={{
        ...workflow,
        progress: metrics?.completed_percent,
        cycle_count: metrics?.cycle_count,
        node_count: metrics?.total_nodes,
        elapsed_seconds: metrics?.elapsed_seconds,
      }}
      selected={selected}
    />
  );
}

function WorkflowCard({
  workflow,
  selected,
}: {
  workflow: {
    id: string;
    name: string;
    status: string;
    created_at: string;
    progress?: number;
    cycle_count?: number;
    node_count?: number;
    elapsed_seconds?: number;
  };
  selected?: boolean;
}) {
  // Canonical status -> {orb, badge} mapping lives in workflowStatus.ts
  // so every page handles all statuses (incl. escalated) consistently.
  const statusConfig = getStatusVariant(workflow.status);

  const elapsed = workflow.elapsed_seconds
    ? workflow.elapsed_seconds < 60
      ? `${Math.round(workflow.elapsed_seconds)}s`
      : workflow.elapsed_seconds < 3600
      ? `${Math.floor(workflow.elapsed_seconds / 60)}m ${Math.round(workflow.elapsed_seconds % 60)}s`
      : `${Math.floor(workflow.elapsed_seconds / 3600)}h ${Math.floor((workflow.elapsed_seconds % 3600) / 60)}m`
    : "—";

  return (
    <Link
      href={`/workflows/${workflow.id}`}
      role="option"
      aria-selected={selected ? "true" : "false"}
      data-workflow-row
      data-workflow-id={workflow.id}
      className={cn(
        "group flex flex-col gap-3 p-4 rounded-lg bg-space-800 border transition-all",
        selected
          ? "border-aurora-500/60 ring-2 ring-aurora-500/40"
          : "border-space-600 hover:border-aurora-500/30"
      )}
    >
      {/* Header */}
      <div className="flex items-start gap-3">
        <StatusOrb
          variant={statusConfig.orb}
          size="md"
          pulse={workflow.status === "running"}
        />
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-body text-comet-200 truncate group-hover:text-comet-100 transition-colors">
            {workflow.name}
          </h3>
          <div className="flex items-center gap-2 mt-1">
            <Badge variant={statusConfig.badge}>{workflow.status}</Badge>
            <span className="text-[10px] font-mono text-comet-500">
              {workflow.id.slice(0, 8)}
            </span>
          </div>
        </div>
        <ProgressArc progress={workflow.progress ?? 0} />
      </div>

      {/* Description placeholder — truncated */}
      <p className="text-xs text-comet-500 line-clamp-2">
        Workflow {workflow.id.slice(0, 8)} — created{" "}
        {formatRelativeTime(workflow.created_at)}
      </p>

      {/* Metrics strip */}
      <div className="grid grid-cols-3 gap-2 pt-2 border-t border-space-600/50">
        <div className="flex items-center gap-1.5">
          <RotateCcw className="w-3 h-3 text-comet-500" />
          <span className="text-xs font-mono text-comet-400">
            {workflow.cycle_count ?? 0}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <Layers className="w-3 h-3 text-comet-500" />
          <span className="text-xs font-mono text-comet-400">
            {workflow.node_count ?? 0}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <Clock className="w-3 h-3 text-comet-500" />
          <span className="text-xs font-mono text-comet-400">{elapsed}</span>
        </div>
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between text-[10px] text-comet-500">
        <span>Updated {formatRelativeTime(workflow.created_at)}</span>
        <ChevronRight className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity" />
      </div>
    </Link>
  );
}

function CardShimmer() {
  return (
    <div className="flex flex-col gap-3 p-4 rounded-lg bg-space-800 border border-space-600 animate-pulse">
      <div className="flex items-start gap-3">
        <div className="w-2.5 h-2.5 rounded-full bg-space-600" />
        <div className="flex-1 space-y-2">
          <div className="h-4 bg-space-600 rounded w-3/4" />
          <div className="h-3 bg-space-600 rounded w-1/3" />
        </div>
        <div className="w-10 h-10 rounded-full bg-space-600" />
      </div>
      <div className="h-3 bg-space-600 rounded w-full" />
      <div className="grid grid-cols-3 gap-2 pt-2">
        <div className="h-3 bg-space-600 rounded" />
        <div className="h-3 bg-space-600 rounded" />
        <div className="h-3 bg-space-600 rounded" />
      </div>
    </div>
  );
}

function WorkflowsFallback() {
  // Lightweight skeleton that matches the page's structure so the
  // Suspense boundary is not jarring while URL state resolves.
  return (
    <div className="space-y-6" data-testid="workflows-fallback">
      <div>
        <h1 className="text-3xl font-display tracking-wide text-comet-100">
          Workflows
        </h1>
        <p className="text-sm text-comet-500 mt-1">Loading…</p>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {[...Array(6)].map((_, i) => (
          <CardShimmer key={i} />
        ))}
      </div>
    </div>
  );
}

/**
 * Workflows list page.
 *
 * Next.js 16 requires `useSearchParams` (consumed by `useUrlState`) to
 * be rendered inside a `<Suspense>` boundary so the rest of the page
 * can still be prerendered. We split the page into a thin wrapper
 * (`WorkflowsPage`) and a body (`WorkflowsContent`) that owns the
 * URL state.
 */
export default function WorkflowsPage() {
  return (
    <Shell>
      <Suspense fallback={<WorkflowsFallback />}>
        <WorkflowsContent />
      </Suspense>
    </Shell>
  );
}

function WorkflowsContent() {
  const [page, setPage] = useState(0);
  const pageSize = 12;
  // Status filter and search box are URL-backed so a view is shareable
  // and survives reload. The allow-list enforces the canonical status
  // values — anything out of set falls back to "all".
  const [statusFilter, setStatusFilter] = useUrlState(
    "status",
    "all",
    STATUS_OPTIONS
  );
  const [query, setQuery] = useUrlState("search", "");
  const [selectedIndex, setSelectedIndex] = useState(0);

  const { data, isLoading } = useWorkflows({
    limit: pageSize,
    offset: page * pageSize,
    status: statusFilter === "all" ? undefined : statusFilter,
  });

  const workflows = useMemo(() => data?.items || [], [data]);
  const total = data?.total || 0;
  const totalPages = Math.ceil(total / pageSize);

  // Client-side name filtering
  const filteredWorkflows = useMemo(() => {
    if (!query.trim()) return workflows;
    const q = query.toLowerCase();
    return workflows.filter((w) => w.name.toLowerCase().includes(q));
  }, [workflows, query]);

  // Clamp the selectedIndex for the current list size. The cursor
  // automatically follows a shorter list (e.g. after filtering) on
  // the next render — no extra effect required.
  const safeIndex =
    filteredWorkflows.length === 0
      ? 0
      : Math.min(selectedIndex, filteredWorkflows.length - 1);

  const router = useRouter();
  useKeyboardShortcuts({
    j: () => {
      if (filteredWorkflows.length === 0) return;
      setSelectedIndex((i) => Math.min(i + 1, filteredWorkflows.length - 1));
    },
    k: () => {
      if (filteredWorkflows.length === 0) return;
      setSelectedIndex((i) => Math.max(i - 1, 0));
    },
    Enter: () => {
      const target = filteredWorkflows[safeIndex];
      if (target) router.push(`/workflows/${target.id}`);
    },
  });

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-display tracking-wide text-comet-100">
            Workflows
          </h1>
          <p className="text-sm text-comet-500 mt-1">
            {total} total workflows
          </p>
        </div>
      </div>

      {/* Search + Filters */}
      <div className="space-y-3">
        <div className="relative max-w-md">
          <label htmlFor="workflow-search" className="sr-only">
            Search workflows by name
          </label>
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-comet-500" aria-hidden="true" />
          <Input
            id="workflow-search"
            placeholder="Search by name..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="pl-9 bg-space-800 border-space-500 text-sm"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery("")}
              aria-label="Clear search"
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-comet-500 hover:text-comet-300"
            >
              <X className="w-4 h-4" aria-hidden="true" />
            </button>
          )}
        </div>

        <div className="flex flex-wrap gap-2" role="group" aria-label="Filter workflows by status">
          <button
            type="button"
            onClick={() => setStatusFilter("all")}
            aria-pressed={statusFilter === "all"}
            className={cn(
              "inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-mono font-medium rounded-sm border transition-colors",
              statusFilter === "all"
                ? "bg-aurora-500/10 text-aurora-400 border-aurora-500/30"
                : "bg-space-800 text-comet-400 border-space-600 hover:bg-space-700 hover:text-comet-200"
            )}
          >
            All
          </button>
          {STATUS_FILTERS.map((f) => {
            const active = statusFilter === f.value;
            return (
              <button
                key={f.value}
                type="button"
                onClick={() => setStatusFilter(active ? "all" : f.value)}
                aria-pressed={active}
                className={cn(
                  "inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-mono font-medium rounded-sm border transition-colors",
                  active
                    ? "bg-aurora-500/10 text-aurora-400 border-aurora-500/30"
                    : "bg-space-800 text-comet-400 border-space-600 hover:bg-space-700 hover:text-comet-200"
                )}
              >
                <StatusOrb
                  label={`${f.label} status indicator`}
                  variant={
                    f.value === "running"
                      ? "running"
                      : f.value === "completed"
                      ? "success"
                      : f.value === "failed"
                      ? "error"
                      : f.value === "paused"
                      ? "warning"
                      : "idle"
                  }
                  size="sm"
                />
                {f.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Cards Grid */}
      {isLoading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {[...Array(6)].map((_, i) => (
            <CardShimmer key={i} />
          ))}
        </div>
      ) : filteredWorkflows.length === 0 ? (
        <Panel className="text-center py-16">
          <Orbit className="w-12 h-12 mx-auto mb-4 text-comet-500 opacity-50" aria-hidden="true" />
          <p className="text-lg font-display text-comet-300 mb-1">
            The sky is clear
          </p>
          <p className="text-sm text-comet-500 mb-5">
            No workflows match your filters.
          </p>
          <Button asChild variant="primary" size="default">
            <a
              href="https://docs.celeste.dev/workflows/getting-started"
              target="_blank"
              rel="noopener noreferrer"
            >
              Start a workflow
            </a>
          </Button>
        </Panel>
      ) : (
        <>
          <div
            className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4"
            data-workflow-list
            role="listbox"
            aria-label="Workflows"
            tabIndex={0}
          >
            {filteredWorkflows.map((workflow, i) => (
              <WorkflowCardWithMetrics
                key={workflow.id}
                workflow={workflow}
                selected={i === safeIndex}
              />
            ))}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between pt-4 border-t border-space-500">
              <div className="text-xs text-comet-500">
                Page {page + 1} of {totalPages} · {total} total
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="subtle"
                  size="sm"
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  disabled={page <= 0}
                  aria-label="Previous page"
                >
                  <ChevronLeft className="w-4 h-4" aria-hidden="true" />
                </Button>
                <Button
                  variant="subtle"
                  size="sm"
                  onClick={() =>
                    setPage((p) => Math.min(totalPages - 1, p + 1))
                  }
                  disabled={page >= totalPages - 1}
                  aria-label="Next page"
                >
                  <ChevronRight className="w-4 h-4" aria-hidden="true" />
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
