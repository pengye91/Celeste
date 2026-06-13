"use client";

import { Suspense, use, useState, useMemo } from "react";
import Link from "next/link";
import { Shell } from "@/components/shell/shell";
import { Panel } from "@/components/ui/panel";
import { Badge } from "@/components/ui/badge";
import { StatusOrb } from "@/components/ui/status-orb";
import {
  useWorkflow,
  useWorkflowNodes,
} from "@/hooks/useWorkflow";
import { useWorkflowEvents } from "@/hooks/useWorkflowEvents";
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard";
import { formatTimestamp } from "@/lib/format";
import { WorkflowNav } from "@/components/workflow/workflow-nav";
import { cn } from "@/lib/utils";
import ArrowLeft from "lucide-react/dist/esm/icons/arrow-left";
import Copy from "lucide-react/dist/esm/icons/copy";
import Check from "lucide-react/dist/esm/icons/check";
import Undo2 from "lucide-react/dist/esm/icons/undo-2";
import CheckCircle2 from "lucide-react/dist/esm/icons/check-circle-2";
import XCircle from "lucide-react/dist/esm/icons/x-circle";
import AlertCircle from "lucide-react/dist/esm/icons/alert-circle";
import Clock from "lucide-react/dist/esm/icons/clock";
import Layers from "lucide-react/dist/esm/icons/layers";
import Activity from "lucide-react/dist/esm/icons/activity";

/* ───────────────────────────────────────────────
   Types
   ─────────────────────────────────────────────── */

interface CompensationStep {
  nodeName: string;
  command: string;
  status: "pending" | "running" | "completed" | "failed";
  eventId?: string;
  timestamp?: string;
  outcome?: string;
  matchedEvent?: {
    id: string;
    event_type: string;
    timestamp: string;
    event_data: Record<string, unknown> | null;
  };
}

/* ───────────────────────────────────────────────
   Helpers
   ─────────────────────────────────────────────── */

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
      type="button"
    >
      {copied ? (
        <Check className="w-3 h-3 text-nebula-400" />
      ) : (
        <Copy className="w-3 h-3" />
      )}
      {copied ? "Copied" : text.slice(0, 8)}
    </button>
  );
}

function statusToBadgeVariant(
  status: string
): "default" | "success" | "warning" | "danger" | "info" | "muted" {
  switch (status) {
    case "running":
      return "success";
    case "completed":
      return "success";
    case "failed":
      return "danger";
    case "paused":
      return "warning";
    case "cancelled":
      return "muted";
    default:
      return "muted";
  }
}

function statusToOrbVariant(
  status: string
): "idle" | "running" | "success" | "error" | "warning" | "info" {
  switch (status) {
    case "running":
      return "running";
    case "completed":
      return "success";
    case "failed":
      return "error";
    case "paused":
      return "warning";
    case "pending":
    default:
      return "idle";
  }
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

/* ───────────────────────────────────────────────
   Build compensation steps from nodes + events
   ─────────────────────────────────────────────── */

function buildCompensationSteps(
  nodes: { name: string; status: string; command?: string; task_type?: string }[],
  events: { id: string; event_type: string; timestamp: string; event_data: Record<string, unknown> | null }[]
): CompensationStep[] {
  // 1. Select nodes that have a compensation_command
  const compensationNodes = nodes
    .filter((n) => {
      // Check for compensation_command in node data or in dag_definition
      const cmd = n.command;
      return cmd && typeof cmd === "string" && cmd.length > 0;
    })
    .map((n) => ({
      ...n,
      compensationCommand: n.command || "",
    }));

  if (compensationNodes.length === 0) {
    return [];
  }

  // 2. Order reverse dependency (highest sequence / most recently completed first)
  // We use the node order from the array as a proxy for dependency order
  // Reverse it so last-completed nodes are compensated first
  const orderedNodes = [...compensationNodes].reverse();

  // 3. Match compensation events to steps by compensation_command string
  const compensationEvents = events.filter(
    (e) =>
      e.event_type === "COMPENSATION_TRIGGERED" ||
      e.event_type === "COMPENSATION_COMPLETED" ||
      e.event_type === "COMPENSATION_FAILED"
  );

  const steps: CompensationStep[] = orderedNodes.map((node) => {
    // Find ALL matching events for this node, then pick the most terminal one
    const nodeEvents = compensationEvents.filter((e) => {
      const data = e.event_data || {};
      const eventCommand = data.compensation_command || data.command || data.node_name;
      return (
        (typeof eventCommand === "string" && eventCommand === node.compensationCommand) ||
        (typeof eventCommand === "string" && eventCommand === node.name)
      );
    });

    // Pick the most terminal event: failed > completed > triggered
    const priority: Record<string, number> = {
      COMPENSATION_FAILED: 3,
      COMPENSATION_COMPLETED: 2,
      COMPENSATION_TRIGGERED: 1,
    };
    const matchedEvent = nodeEvents.sort(
      (a, b) => (priority[b.event_type] || 0) - (priority[a.event_type] || 0)
    )[0];

    let status: CompensationStep["status"] = "pending";
    let outcome: string | undefined;

    if (matchedEvent) {
      if (matchedEvent.event_type === "COMPENSATION_TRIGGERED") {
        status = "running";
      } else if (matchedEvent.event_type === "COMPENSATION_COMPLETED") {
        status = "completed";
        outcome =
          typeof matchedEvent.event_data?.outcome === "string"
            ? matchedEvent.event_data.outcome
            : "Compensation completed successfully";
      } else if (matchedEvent.event_type === "COMPENSATION_FAILED") {
        status = "failed";
        outcome =
          typeof matchedEvent.event_data?.error === "string"
            ? matchedEvent.event_data.error
            : typeof matchedEvent.event_data?.reason === "string"
            ? matchedEvent.event_data.reason
            : "Compensation failed";
      }
    }

    return {
      nodeName: node.name,
      command: node.compensationCommand,
      status,
      eventId: matchedEvent?.id,
      timestamp: matchedEvent?.timestamp,
      outcome,
      matchedEvent: matchedEvent
        ? {
            id: matchedEvent.id,
            event_type: matchedEvent.event_type,
            timestamp: matchedEvent.timestamp,
            event_data: matchedEvent.event_data,
          }
        : undefined,
    };
  });

  return steps;
}

/* ───────────────────────────────────────────────
   Unmatched events timeline
   ─────────────────────────────────────────────── */

function getUnmatchedEvents(
  events: { id: string; event_type: string; timestamp: string; event_data: Record<string, unknown> | null }[],
  steps: CompensationStep[]
): { id: string; event_type: string; timestamp: string; event_data: Record<string, unknown> | null }[] {
  const matchedEventIds = new Set(steps.map((s) => s.eventId).filter(Boolean));
  return events.filter(
    (e) =>
      (e.event_type === "COMPENSATION_TRIGGERED" ||
        e.event_type === "COMPENSATION_COMPLETED" ||
        e.event_type === "COMPENSATION_FAILED") &&
      !matchedEventIds.has(e.id)
  );
}

/* ───────────────────────────────────────────────
   Chain Diagram (SVG)
   ─────────────────────────────────────────────── */

function ChainDiagram({ steps }: { steps: CompensationStep[] }) {
  const width = 800;
  const height = 120;
  const paddingX = 40;
  const paddingY = 30;

  const nodeCount = steps.length;
  if (nodeCount === 0) return null;

  const availableWidth = width - paddingX * 2;
  const stepX = nodeCount > 1 ? availableWidth / (nodeCount - 1) : 0;
  const startX = paddingX;
  const forwardY = paddingY + 20;
  const backY = paddingY + 60;

  const positions = steps.map((_, i) => ({
    x: startX + stepX * i,
    y: forwardY,
  }));

  const statusColor = (status: string): string => {
    switch (status) {
      case "completed":
        return "var(--nebula-500)";
      case "failed":
        return "var(--mars-500)";
      case "running":
        return "var(--aurora-500)";
      default:
        return "var(--space-500)";
    }
  };

  const statusIcon = (status: string) => {
    switch (status) {
      case "completed":
        return "✓";
      case "failed":
        return "✕";
      case "running":
        return "◐";
      default:
        return "○";
    }
  };

  return (
    <svg
      role="img"
      aria-label="Compensation chain diagram showing original node execution forward and compensation winding back"
      viewBox={`0 0 ${width} ${height}`}
      className="w-full h-auto"
      style={{ maxHeight: 140 }}
    >
      {/* Forward arrows (original execution) */}
      {positions.map((pos, i) => {
        if (i === positions.length - 1) return null;
        const nextPos = positions[i + 1];
        return (
          <g key={`forward-${i}`}>
            <line
              x1={pos.x}
              y1={pos.y}
              x2={nextPos.x - 14}
              y2={nextPos.y}
              stroke="var(--space-500)"
              strokeWidth={1.5}
              strokeDasharray="4 2"
              opacity={0.6}
            />
            <polygon
              points={`${nextPos.x - 14},${nextPos.y - 3} ${nextPos.x - 8},${nextPos.y} ${nextPos.x - 14},${nextPos.y + 3}`}
              fill="var(--space-500)"
              opacity={0.6}
            />
          </g>
        );
      })}

      {/* Compensation winding-back arrows */}
      {positions.map((pos, i) => {
        if (i === 0) return null;
        const prevPos = positions[i - 1];
        // Draw a curved arrow from current node back to previous
        const midX = (pos.x + prevPos.x) / 2;
        const cpY = backY + 10;
        return (
          <g key={`back-${i}`}>
            <path
              d={`M ${pos.x} ${pos.y + 10} Q ${midX} ${cpY} ${prevPos.x} ${prevPos.y + 10}`}
              fill="none"
              stroke={statusColor(steps[i].status)}
              strokeWidth={2}
              opacity={steps[i].status === "pending" ? 0.3 : 0.8}
              markerEnd={`url(#arrowhead-${steps[i].status})`}
            />
          </g>
        );
      })}

      {/* Arrow markers */}
      <defs>
        {["pending", "running", "completed", "failed"].map((status) => (
          <marker
            key={status}
            id={`arrowhead-${status}`}
            markerWidth="8"
            markerHeight="6"
            refX="7"
            refY="3"
            orient="auto"
          >
            <polygon
              points="0 0, 8 3, 0 6"
              fill={statusColor(status)}
              opacity={status === "pending" ? 0.3 : 0.8}
            />
          </marker>
        ))}
      </defs>

      {/* Nodes */}
      {positions.map((pos, i) => {
        const step = steps[i];
        const isRunning = step.status === "running";
        return (
          <g key={`node-${i}`}>
            {/* Node circle */}
            <circle
              cx={pos.x}
              cy={pos.y}
              r={10}
              fill="var(--space-800)"
              stroke={statusColor(step.status)}
              strokeWidth={2}
              opacity={isRunning ? 1 : 0.9}
              className={isRunning ? "animate-pulse" : ""}
            />
            {/* Status icon */}
            <text
              x={pos.x}
              y={pos.y}
              textAnchor="middle"
              dominantBaseline="central"
              fill={statusColor(step.status)}
              fontSize={10}
              fontFamily="monospace"
            >
              {statusIcon(step.status)}
            </text>
            {/* Node label */}
            <text
              x={pos.x}
              y={pos.y - 18}
              textAnchor="middle"
              fill="var(--space-200)"
              fontSize={11}
              fontFamily="sans-serif"
            >
              {step.nodeName.length > 14
                ? step.nodeName.slice(0, 12) + "…"
                : step.nodeName}
            </text>
            {/* Status label */}
            <text
              x={pos.x}
              y={pos.y + 22}
              textAnchor="middle"
              fill={statusColor(step.status)}
              fontSize={9}
              fontFamily="monospace"
              opacity={0.8}
            >
              {step.status}
            </text>
          </g>
        );
      })}

      {/* Legend */}
      <g transform={`translate(${width - 120}, 8)`}>
        <text x={0} y={0} fill="var(--space-400)" fontSize={9} fontFamily="monospace">
          Forward = execution
        </text>
        <text x={0} y={12} fill="var(--space-400)" fontSize={9} fontFamily="monospace">
          Curved = compensation
        </text>
      </g>
    </svg>
  );
}

/* ───────────────────────────────────────────────
   Step status icon
   ─────────────────────────────────────────────── */

function StepStatusIcon({ status }: { status: string }) {
  switch (status) {
    case "completed":
      return <CheckCircle2 className="w-4 h-4 text-nebula-400" aria-hidden="true" />;
    case "failed":
      return <XCircle className="w-4 h-4 text-mars-400" aria-hidden="true" />;
    case "running":
      return <Clock className="w-4 h-4 text-aurora-400 animate-pulse" aria-hidden="true" />;
    default:
      return <AlertCircle className="w-4 h-4 text-space-400" aria-hidden="true" />;
  }
}

function StepStatusLabel({ status }: { status: string }) {
  const labels: Record<string, string> = {
    pending: "Pending",
    running: "Running",
    completed: "Completed",
    failed: "Failed",
  };
  return <span className="text-xs font-medium capitalize">{labels[status] || status}</span>;
}

/* ───────────────────────────────────────────────
   Empty state illustration
   ─────────────────────────────────────────────── */

function EmptyStateIllustration() {
  return (
    <svg
      width="120"
      height="120"
      viewBox="0 0 120 120"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className="mx-auto mb-4"
      aria-hidden="true"
    >
      {/* Faint constellation grid */}
      <line x1="20" y1="20" x2="100" y2="20" stroke="var(--space-300)" strokeWidth="0.5" opacity="0.3" />
      <line x1="20" y1="60" x2="100" y2="60" stroke="var(--space-300)" strokeWidth="0.5" opacity="0.3" />
      <line x1="20" y1="100" x2="100" y2="100" stroke="var(--space-300)" strokeWidth="0.5" opacity="0.3" />
      <line x1="20" y1="20" x2="20" y2="100" stroke="var(--space-300)" strokeWidth="0.5" opacity="0.3" />
      <line x1="60" y1="20" x2="60" y2="100" stroke="var(--space-300)" strokeWidth="0.5" opacity="0.3" />
      <line x1="100" y1="20" x2="100" y2="100" stroke="var(--space-300)" strokeWidth="0.5" opacity="0.3" />

      {/* Single faint star (no compensation) */}
      <circle cx="60" cy="60" r="3" stroke="var(--space-300)" strokeWidth="1" opacity="0.5" />

      {/* Aurora accent point */}
      <circle cx="80" cy="40" r="2" fill="var(--aurora-500)" opacity="0.8" />
    </svg>
  );
}

/* ───────────────────────────────────────────────
   Main Page
   ─────────────────────────────────────────────── */

export default function SagaCompensationPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  return (
    <Suspense fallback={<Shell><div className="space-y-4"><div className="h-8 w-64 bg-space-700/50 rounded animate-pulse" /></div></Shell>}>
      <SagaCompensationPageInner params={params} />
    </Suspense>
  );
}

function SagaCompensationPageInner({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);

  const { data: workflow, isLoading: wfLoading, error: wfError } = useWorkflow(id);
  const { data: nodesData, isLoading: nodesLoading } = useWorkflowNodes(id);

  // Fetch all compensation events (unfiltered, then filter client-side per spec)
  const { data: allEvents, isLoading: eventsLoading, error: eventsError } = useWorkflowEvents(id, {
    limit: 200,
  });

  // Build compensation steps
  const steps = useMemo(() => {
    if (!nodesData || !allEvents) return [];
    return buildCompensationSteps(nodesData, allEvents);
  }, [nodesData, allEvents]);

  // Unmatched events
  const unmatchedEvents = useMemo(() => {
    if (!allEvents || steps.length === 0) return [];
    return getUnmatchedEvents(allEvents, steps);
  }, [allEvents, steps]);

  // Summary counts
  const summary = useMemo(() => {
    const triggered = steps.filter((s) => s.status !== "pending").length;
    const completed = steps.filter((s) => s.status === "completed").length;
    const failed = steps.filter((s) => s.status === "failed").length;
    return { triggered, completed, failed, total: steps.length };
  }, [steps]);

  const isLoading = wfLoading || nodesLoading || eventsLoading;
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
          <span className="text-comet-300">Saga Compensation</span>
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
            <div className="h-40 bg-space-700/50 rounded animate-pulse" />
            <div className="h-64 bg-space-700/50 rounded animate-pulse" />
          </div>
        )}

        {/* Error */}
        {!isLoading && error && (
          <Panel className="text-center py-12">
            <p className="text-mars-400 text-sm">
              Failed to load saga compensation data:{" "}
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

        {/* Empty: no compensation recorded */}
        {!isLoading && !error && workflow && steps.length === 0 && (
          <div className="space-y-6">
            {/* Header */}
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div className="flex items-start gap-4">
                <StatusOrb
                  variant={statusToOrbVariant(workflow.status)}
                  size="lg"
                  pulse={workflow.status === "running"}
                />
                <div>
                  <h1 className="text-3xl font-display text-comet-100">
                    {workflow.name}
                  </h1>
                  <div className="flex items-center gap-3 mt-2 flex-wrap">
                    <Badge variant={statusToBadgeVariant(workflow.status)}>
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
            <WorkflowNav activeTab="saga" />

            <Panel className="text-center py-12">
              <EmptyStateIllustration />
              <p className="text-comet-500 text-sm">No compensation recorded</p>
              <p className="text-comet-600 text-xs mt-1 max-w-md mx-auto">
                Compensation steps appear when a node fails and rollback choreography is triggered.
                Nodes with a <code className="text-aurora-400 font-mono">compensation_command</code> will be shown here in reverse dependency order.
              </p>
            </Panel>
          </div>
        )}

        {/* Main content */}
        {!isLoading && !error && workflow && steps.length > 0 && (
          <div className="space-y-6">
            {/* Header */}
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div className="flex items-start gap-4">
                <StatusOrb
                  variant={statusToOrbVariant(workflow.status)}
                  size="lg"
                  pulse={workflow.status === "running"}
                />
                <div>
                  <h1 className="text-3xl font-display text-comet-100">
                    {workflow.name}
                  </h1>
                  <div className="flex items-center gap-3 mt-2 flex-wrap">
                    <Badge variant={statusToBadgeVariant(workflow.status)}>
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
            <WorkflowNav activeTab="saga" />

            {/* Summary counts */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <KpiCard
                label="Triggered"
                value={summary.triggered}
                icon={Undo2}
                variant="info"
              />
              <KpiCard
                label="Completed"
                value={summary.completed}
                icon={CheckCircle2}
                variant="success"
              />
              <KpiCard
                label="Failed"
                value={summary.failed}
                icon={XCircle}
                variant="danger"
              />
              <KpiCard
                label="Total Steps"
                value={summary.total}
                icon={Layers}
                variant="default"
              />
            </div>

            {/* Chain diagram */}
            <Panel variant="elevated" padding="lg">
              <h2 className="text-lg font-body font-medium text-comet-100 mb-4 flex items-center gap-2">
                <Undo2 className="w-5 h-5 text-aurora-400" />
                Compensation Chain
              </h2>
              <ChainDiagram steps={steps} />
            </Panel>

            {/* Per-step status list */}
            <Panel variant="elevated" padding="lg">
              <h2 className="text-lg font-body font-medium text-comet-100 mb-4 flex items-center gap-2">
                <Activity className="w-5 h-5 text-aurora-400" />
                Step Details
              </h2>
              <div className="space-y-3" role="list" aria-label="Compensation steps">
                {steps.map((step, index) => (
                  <div
                    key={step.nodeName}
                    role="listitem"
                    className={cn(
                      "flex items-start gap-4 p-4 rounded-lg border transition-colors",
                      step.status === "failed"
                        ? "bg-mars-500/5 border-mars-500/20"
                        : step.status === "completed"
                        ? "bg-nebula-500/5 border-nebula-500/20"
                        : step.status === "running"
                        ? "bg-aurora-500/5 border-aurora-500/20"
                        : "bg-space-800 border-space-600"
                    )}
                  >
                    {/* Step number */}
                    <div className="flex flex-col items-center gap-1 shrink-0">
                      <span className="text-[10px] font-mono text-comet-500 uppercase">
                        Step
                      </span>
                      <span className="text-lg font-mono text-comet-300">
                        {index + 1}
                      </span>
                    </div>

                    <div className="flex-1 min-w-0 space-y-2">
                      {/* Name + status */}
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-medium text-comet-100">
                          {step.nodeName}
                        </span>
                        <Badge
                          variant={
                            step.status === "completed"
                              ? "success"
                              : step.status === "failed"
                              ? "danger"
                              : step.status === "running"
                              ? "info"
                              : "muted"
                          }
                          className="text-[10px]"
                        >
                          <StepStatusIcon status={step.status} />
                          <StepStatusLabel status={step.status} />
                        </Badge>
                      </div>

                      {/* Command snippet */}
                      <div className="font-mono text-xs text-comet-300 bg-space-900/80 rounded-md p-2 border border-space-700/50 overflow-x-auto">
                        {step.command}
                      </div>

                      {/* Outcome */}
                      {step.outcome && (
                        <p
                          className={cn(
                            "text-xs",
                            step.status === "failed"
                              ? "text-mars-400"
                              : "text-nebula-400"
                          )}
                        >
                          {step.outcome}
                        </p>
                      )}

                      {/* Timestamp */}
                      {step.timestamp && (
                        <p className="text-[10px] font-mono text-comet-500">
                          {formatTimestamp(step.timestamp)}
                        </p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </Panel>

            {/* Unmatched events timeline */}
            {unmatchedEvents.length > 0 && (
              <Panel variant="elevated" padding="lg">
                <h2 className="text-lg font-body font-medium text-comet-100 mb-4 flex items-center gap-2">
                  <AlertCircle className="w-5 h-5 text-solar-400" />
                  Unmatched Events
                </h2>
                <div className="space-y-2" role="list" aria-label="Unmatched compensation events">
                  {unmatchedEvents.map((event) => (
                    <div
                      key={event.id}
                      role="listitem"
                      className="flex items-center gap-3 p-3 rounded bg-space-800/50 border border-space-600/50"
                    >
                      <StatusOrb
                        variant={
                          event.event_type === "COMPENSATION_COMPLETED"
                            ? "success"
                            : event.event_type === "COMPENSATION_FAILED"
                            ? "error"
                            : "running"
                        }
                        size="sm"
                      />
                      <span className="text-xs font-mono text-aurora-400 shrink-0 w-40 truncate">
                        {event.event_type}
                      </span>
                      <div className="flex-1 h-px bg-space-600/50" />
                      <span className="text-xs text-comet-500 shrink-0">
                        {formatTimestamp(event.timestamp)}
                      </span>
                    </div>
                  ))}
                </div>
              </Panel>
            )}
          </div>
        )}
      </div>
    </Shell>
  );
}
