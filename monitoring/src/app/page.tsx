"use client";

import { Shell } from "@/components/shell/shell";
import { Panel } from "@/components/ui/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { StatusOrb } from "@/components/ui/status-orb";
import { EmptyState } from "@/components/ui/empty-state";
import { useWorkflows } from "@/hooks/useWorkflow";
import { formatRelativeTime } from "@/lib/format";
import { isAlertStatus, statusOrbVariant, statusBadgeVariant } from "@/lib/workflowStatus";
import { cn } from "@/lib/utils";
import Activity from "lucide-react/dist/esm/icons/activity";
import Clock from "lucide-react/dist/esm/icons/clock";
import AlertTriangle from "lucide-react/dist/esm/icons/alert-triangle";
import CheckCircle from "lucide-react/dist/esm/icons/check-circle";
import PauseCircle from "lucide-react/dist/esm/icons/pause-circle";
import ArrowRight from "lucide-react/dist/esm/icons/arrow-right";
import Orbit from "lucide-react/dist/esm/icons/orbit";
import Link from "next/link";
import { useMemo, useSyncExternalStore } from "react";

function SummaryCard({
  label,
  value,
  icon: Icon,
  variant,
  large = false,
}: {
  label: string;
  value: string | number;
  icon: React.ElementType;
  variant: "default" | "success" | "warning" | "danger" | "info";
  large?: boolean;
}) {
  const colorMap = {
    default: "text-comet-300",
    success: "text-aurora-400",
    warning: "text-solar-400",
    danger: "text-mars-400",
    info: "text-nebula-400",
  };

  return (
    <Panel
      className={cn(
        "flex items-center gap-4 transition-all",
        large && "scale-[1.02] -translate-y-0.5 shadow-lg"
      )}
    >
      <div
        className={cn(
          "rounded-md bg-space-700 flex items-center justify-center",
          large ? "w-12 h-12" : "w-10 h-10"
        )}
      >
        <Icon
          className={cn(
            colorMap[variant],
            large ? "w-6 h-6" : "w-5 h-5"
          )}
        />
      </div>
      <div>
        <div
          className={cn(
            "font-display text-comet-100",
            large ? "text-3xl" : "text-2xl"
          )}
        >
          {value}
        </div>
        <div className="text-xs text-comet-500 font-body">{label}</div>
      </div>
    </Panel>
  );
}

function useClientTime(intervalMs = 30000) {
  return useSyncExternalStore(
    (callback) => {
      const id = setInterval(callback, intervalMs);
      return () => clearInterval(id);
    },
    () => Date.now(),
    () => 0
  );
}

function ThroughputStrip({ workflows }: { workflows: { status: string; created_at: string }[] }) {
  const now = useClientTime(30000);
  const { buckets, maxVal } = useMemo(() => {
    const oneHour = 60 * 60 * 1000;
    const buckets: { completed: number; failed: number; running: number }[] = Array.from(
      { length: 12 },
      () => ({ completed: 0, failed: 0, running: 0 })
    );
    if (now === 0) {
      return { buckets, maxVal: 1 };
    }
    workflows.forEach((w) => {
      const t = new Date(w.created_at).getTime();
      if (now - t > oneHour) return;
      const idx = Math.min(11, Math.floor((now - t) / (oneHour / 12)));
      if (w.status === "completed") buckets[idx].completed++;
      else if (w.status === "failed") buckets[idx].failed++;
      else if (w.status === "running") buckets[idx].running++;
    });
    const maxVal = Math.max(1, ...buckets.map((b) => b.completed + b.failed + b.running));
    return { buckets, maxVal };
  }, [now, workflows]);

  return (
    <Panel variant="elevated" padding="md">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-body font-medium text-comet-100 flex items-center gap-2">
          <Activity className="w-4 h-4 text-aurora-400" />
          Live Throughput (last hour)
        </h2>
        <span className="text-xs text-comet-500">12 x 5 min buckets</span>
      </div>
      <div className="flex items-end gap-1 h-16">
        {buckets.map((b, i) => {
          const total = b.completed + b.failed + b.running;
          const h = total === 0 ? 2 : Math.max(2, (total / maxVal) * 100);
          return (
            <div
              key={i}
              className="flex-1 flex flex-col justify-end gap-px rounded-sm overflow-hidden"
              style={{ height: `${h}%` }}
              title={`${b.running} running, ${b.completed} completed, ${b.failed} failed`}
            >
              {b.running > 0 && (
                <div
                  className="w-full bg-aurora-500/60"
                  style={{ height: `${(b.running / total) * 100}%` }}
                />
              )}
              {b.completed > 0 && (
                <div
                  className="w-full bg-aurora-400/40"
                  style={{ height: `${(b.completed / total) * 100}%` }}
                />
              )}
              {b.failed > 0 && (
                <div
                  className="w-full bg-mars-500/60"
                  style={{ height: `${(b.failed / total) * 100}%` }}
                />
              )}
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

function AlertFlare({ workflows }: { workflows: { id: string; name: string; status: string }[] }) {
  // Terminal/stuck states that need a human's eyes. The canonical set lives
  // in workflowStatus.ts so new statuses (e.g. escalated) can't be missed.
  const alerts = workflows.filter((w) => isAlertStatus(w.status));

  return (
    <Panel variant="elevated" padding="md">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-body font-medium text-comet-100 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-mars-400" />
          Alert Flares
        </h2>
        <Badge variant="danger">{alerts.length}</Badge>
      </div>
      {alerts.length === 0 ? (
        <div className="text-center py-6 text-comet-500 text-sm">
          <CheckCircle className="w-5 h-5 mx-auto mb-2 opacity-50" />
          All systems nominal
        </div>
      ) : (
        <div className="space-y-2">
          {alerts.map((w) => (
            <Link
              key={w.id}
              href={`/workflows/${w.id}`}
              className="flex items-center gap-3 p-2 rounded-md bg-space-800/50 border border-space-600 hover:border-mars-500/40 transition-colors group"
            >
              <StatusOrb
                variant={statusOrbVariant(w.status)}
                size="md"
              />
              <div className="flex-1 min-w-0">
                <div className="text-sm text-comet-200 truncate">{w.name}</div>
                <div className="text-xs text-comet-500">{w.status}</div>
              </div>
              <ArrowRight className="w-4 h-4 text-comet-500 group-hover:text-comet-300 transition-colors" />
            </Link>
          ))}
        </div>
      )}
    </Panel>
  );
}

function RecentWorkflowsTable({
  workflows,
  isLoading,
  error,
  onRetry,
}: {
  workflows: { id: string; name: string; status: string; created_at: string }[];
  isLoading: boolean;
  error?: Error | null;
  onRetry?: () => void;
}) {
  return (
    <Panel variant="elevated" padding="lg">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-body font-medium text-comet-100">
          Recent Workflows
        </h2>
        <Link
          href="/workflows"
          className="text-xs text-aurora-400 hover:text-aurora-300 transition-colors"
        >
          View all →
        </Link>
      </div>

      {error ? (
        <div
          role="alert"
          className="flex items-center justify-between gap-3 p-3 rounded-md bg-mars-500/10 border border-mars-500/30"
        >
          <div className="flex items-center gap-2 text-sm text-mars-400">
            <StatusOrb variant="error" size="md" label="Failed to load recent workflows" />
            <span>Couldn&apos;t load recent workflows.</span>
          </div>
          {onRetry ? (
            <Button variant="danger" size="sm" onClick={onRetry}>
              Retry
            </Button>
          ) : null}
        </div>
      ) : isLoading ? (
        <div className="space-y-3">
          {[...Array(5)].map((_, i) => (
            <div
              key={i}
              className="h-12 bg-space-700/50 rounded-md animate-pulse"
            />
          ))}
        </div>
      ) : workflows.length === 0 ? (
        <EmptyState
          compact
          icon={<Orbit className="w-10 h-10 text-comet-500 opacity-60" aria-hidden="true" />}
          title="No active workflows"
          description="The observatory is quiet. Submit a workflow to begin."
          action={{ label: "Go to workflows", href: "/workflows" }}
        />
      ) : (
        <div className="space-y-2">
          {workflows.slice(0, 8).map((workflow) => (
            <Link
              key={workflow.id}
              href={`/workflows/${workflow.id}`}
              className="flex items-center gap-4 p-3 rounded-md bg-space-800/50 border border-space-600 hover:border-space-500 transition-colors"
            >
              <StatusOrb
                variant={statusOrbVariant(workflow.status)}
                size="md"
                pulse={workflow.status === "running"}
              />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-body text-comet-200 truncate">
                  {workflow.name}
                </div>
                <div className="flex items-center gap-3 mt-0.5">
                  <span className="text-xs text-comet-500 font-mono">
                    {workflow.id.slice(0, 8)}
                  </span>
                  <Badge variant={statusBadgeVariant(workflow.status)}>
                    {workflow.status}
                  </Badge>
                </div>
              </div>
              <div className="flex items-center gap-1 text-xs text-comet-500 shrink-0">
                <Clock className="w-3 h-3" />
                <span>{formatRelativeTime(workflow.created_at)}</span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </Panel>
  );
}

export default function DashboardPage() {
  const {
    data: workflowsData,
    isLoading,
    error,
    refetch,
  } = useWorkflows({ limit: 50, offset: 0 });

  const workflows = workflowsData?.items || [];
  const activeCount = workflows.filter((w) => w.status === "running").length;
  const completedCount = workflows.filter((w) => w.status === "completed").length;
  const failedCount = workflows.filter((w) => w.status === "failed").length;
  const pausedCount = workflows.filter((w) => w.status === "paused").length;

  return (
    <Shell>
      <div className="space-y-6">
        {/* Header */}
        <div>
          <h1 className="text-4xl font-display tracking-wide text-comet-100">
            Celeste Mission Control
          </h1>
          <p className="text-sm text-comet-500 mt-1 font-body">
            Real-time workflow orchestration overview
          </p>
        </div>

        {/* Orbital Summary Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <SummaryCard
            label="Active"
            value={activeCount}
            icon={Activity}
            variant="success"
            large
          />
          <SummaryCard
            label="Completed"
            value={completedCount}
            icon={CheckCircle}
            variant="default"
          />
          <SummaryCard
            label="Failed"
            value={failedCount}
            icon={AlertTriangle}
            variant="danger"
          />
          <SummaryCard
            label="Paused"
            value={pausedCount}
            icon={PauseCircle}
            variant="warning"
          />
        </div>

        {/* Throughput + Alerts */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2">
            <ThroughputStrip workflows={workflows} />
          </div>
          <div>
            <AlertFlare workflows={workflows} />
          </div>
        </div>

        {/* Recent Workflows */}
        <RecentWorkflowsTable
          workflows={workflows}
          isLoading={isLoading}
          error={error}
          onRetry={() => void refetch()}
        />
      </div>
    </Shell>
  );
}
