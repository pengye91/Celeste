"use client";

import { Shell } from "@/components/shell/shell";
import { Panel } from "@/components/ui/panel";
import { Badge } from "@/components/ui/badge";
import { StatusOrb } from "@/components/ui/status-orb";
import { Button } from "@/components/ui/button";
import {
  useWorkflow,
  useWorkflowStatus,
  useWorkflowMetrics,
  useCancelWorkflow,
  useResumeWorkflow,
} from "@/hooks/useWorkflow";
import { useWorkflowEvents } from "@/hooks/useWorkflowEvents";
import { useToast } from "@/hooks/useToast";
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { formatTimestamp } from "@/lib/format";
import { cn } from "@/lib/utils";
import ArrowLeft from "lucide-react/dist/esm/icons/arrow-left";
import Copy from "lucide-react/dist/esm/icons/copy";
import Ban from "lucide-react/dist/esm/icons/ban";
import Play from "lucide-react/dist/esm/icons/play";
import RotateCcw from "lucide-react/dist/esm/icons/rotate-ccw";
import Layers from "lucide-react/dist/esm/icons/layers";
import Clock from "lucide-react/dist/esm/icons/clock";
import Shield from "lucide-react/dist/esm/icons/shield";
import Activity from "lucide-react/dist/esm/icons/activity";
import GitBranch from "lucide-react/dist/esm/icons/git-branch";
import Orbit from "lucide-react/dist/esm/icons/orbit";
import Pause from "lucide-react/dist/esm/icons/pause";
import Link from "next/link";
import { useState, useCallback, useMemo, useEffect } from "react";
import { NodeInspector } from "@/components/workflow/node-inspector";
import { WorkflowNav } from "@/components/workflow/workflow-nav";
import type { NodeInspectorNode } from "@/components/workflow/node-inspector";

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
      aria-label="Copy workflow ID"
    >
      <Copy className="w-3 h-3" aria-hidden="true" />
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

// --- Enhanced MiniConstellation ---

interface ConstellationNode {
  name: string;
  status: string;
  dependencies?: string[];
}

function MiniConstellation({
  nodes,
  onNodeClick,
}: {
  nodes: ConstellationNode[];
  onNodeClick?: (node: ConstellationNode) => void;
}) {
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const [isMobile, setIsMobile] = useState(false);

  // Detect mobile on mount and resize. The listener is registered
  // once and removed on unmount; the previous useState(() => ...)
  // side-effect hack registered a fresh listener on every render
  // and discarded the cleanup.
  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 768);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);

  if (nodes.length === 0) {
    return (
      <Panel className="text-center py-8 text-comet-500 text-sm">
        <Orbit className="w-6 h-6 mx-auto mb-2 opacity-50" />
        No nodes in this workflow
      </Panel>
    );
  }

  // Mobile fallback: keep the existing grid from Phase 1
  if (isMobile) {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {nodes.map((node) => (
          <button
            key={node.name}
            onClick={() => onNodeClick?.(node)}
            className="flex items-center gap-2 p-2 rounded-md bg-space-800/50 border border-space-600/50 hover:bg-space-700/50 hover:border-space-500/50 transition-colors text-left"
          >
            <StatusOrb
              variant={
                node.status === "running"
                  ? "running"
                  : node.status === "completed"
                  ? "success"
                  : node.status === "failed"
                  ? "error"
                  : "idle"
              }
              size="sm"
              pulse={node.status === "running"}
            />
            <span className="text-xs font-mono text-comet-300 truncate">
              {node.name}
            </span>
          </button>
        ))}
      </div>
    );
  }

  // Build a simple layered layout
  const nodeMap = new Map<string, ConstellationNode & { layer: number; index: number }>();
  const layers: string[][] = [];

  // Compute layers: root nodes (no deps) at layer 0, dependents below
  const visited = new Set<string>();
  const computeLayer = (name: string): number => {
    if (visited.has(name)) return nodeMap.get(name)?.layer ?? 0;
    visited.add(name);
    const node = nodes.find((n) => n.name === name);
    if (!node) return 0;
    if (!node.dependencies || node.dependencies.length === 0) {
      nodeMap.set(name, { ...node, layer: 0, index: 0 });
      return 0;
    }
    const maxDepLayer = Math.max(...node.dependencies.map(computeLayer));
    const layer = maxDepLayer + 1;
    nodeMap.set(name, { ...node, layer, index: 0 });
    return layer;
  };

  nodes.forEach((n) => computeLayer(n.name));

  // Group by layer and assign horizontal index
  nodeMap.forEach((node) => {
    if (!layers[node.layer]) layers[node.layer] = [];
    node.index = layers[node.layer].length;
    layers[node.layer].push(node.name);
  });

  const layerCount = layers.length;
  const containerWidth = 100; // percent
  const paddingX = 10;
  const paddingY = 20;

  const getX = (layerIndex: number, nodeIndex: number, layerSize: number): number => {
    if (layerSize === 1) return 50;
    const availableWidth = containerWidth - paddingX * 2;
    const step = availableWidth / (layerSize - 1);
    return paddingX + step * nodeIndex;
  };

  const getY = (layerIndex: number): number => {
    if (layerCount <= 1) return 50;
    const availableHeight = 100 - paddingY * 2;
    const step = availableHeight / (layerCount - 1);
    return paddingY + step * layerIndex;
  };

  const orbColor = (status: string): string => {
    switch (status) {
      case "running":
        return "bg-cyan-400 shadow-[0_0_12px_rgba(34,211,238,0.6)]";
      case "completed":
        return "bg-aurora-400 shadow-[0_0_8px_rgba(52,211,153,0.5)]";
      case "failed":
        return "bg-mars-400 shadow-[0_0_8px_rgba(248,113,113,0.5)]";
      case "pending":
        return "bg-solar-400 shadow-[0_0_8px_rgba(251,191,36,0.4)]";
      default:
        return "bg-comet-400 shadow-[0_0_6px_rgba(148,163,184,0.4)]";
    }
  };

  const lines: { x1: number; y1: number; x2: number; y2: number }[] = [];
  nodeMap.forEach((node) => {
    if (node.dependencies) {
      node.dependencies.forEach((depName) => {
        const dep = nodeMap.get(depName);
        if (dep) {
          const layerSize = layers[node.layer].length;
          const depLayerSize = layers[dep.layer].length;
          lines.push({
            x1: getX(dep.layer, dep.index, depLayerSize),
            y1: getY(dep.layer),
            x2: getX(node.layer, node.index, layerSize),
            y2: getY(node.layer),
          });
        }
      });
    }
  });

  return (
    <div className="relative w-full min-h-64 bg-space-900/50 rounded-lg border border-space-700/50 overflow-hidden">
      <svg className="absolute inset-0 w-full h-full pointer-events-none">
        {lines.map((line, i) => (
          <line
            key={i}
            x1={`${line.x1}%`}
            y1={`${line.y1}%`}
            x2={`${line.x2}%`}
            y2={`${line.y2}%`}
            stroke="rgba(148,163,184,0.25)"
            strokeWidth={1.5}
          />
        ))}
      </svg>
      {Array.from(nodeMap.values()).map((node) => {
        const layerSize = layers[node.layer].length;
        const x = getX(node.layer, node.index, layerSize);
        const y = getY(node.layer);
        const isRunning = node.status === "running";
        return (
          <button
            key={node.name}
            onClick={() => onNodeClick?.(node)}
            onMouseEnter={() => setHoveredNode(node.name)}
            onMouseLeave={() => setHoveredNode(null)}
            className="absolute transform -translate-x-1/2 -translate-y-1/2 group"
            style={{ left: `${x}%`, top: `${y}%` }}
          >
            <div
              role="img"
              aria-label={`Node ${node.name}, status ${node.status}`}
              className={cn(
                "w-4 h-4 rounded-full transition-all duration-300",
                orbColor(node.status),
                isRunning && "animate-pulse"
              )}
            />
            {hoveredNode === node.name && (
              <div className="absolute left-1/2 -translate-x-1/2 bottom-full mb-2 px-2 py-1 rounded bg-space-800 border border-space-600 text-xs font-mono text-comet-200 whitespace-nowrap z-10 shadow-lg">
                {node.name}
                <div className="text-[10px] text-comet-500 capitalize">{node.status}</div>
              </div>
            )}
          </button>
        );
      })}
    </div>
  );
}

function PauseResponsePanel({
  reason,
  duration,
  cycles,
  tokens,
  onResume,
  onCancel,
  isPending,
  resumeError,
}: {
  reason: string;
  duration: number;
  cycles: number;
  tokens: number;
  onResume: (humanInput: string) => void;
  onCancel: () => void;
  isPending: boolean;
  resumeError: string | null;
}) {
  const [humanInput, setHumanInput] = useState("");

  return (
    <Panel variant="elevated" padding="lg" className="space-y-4">
      <div className="flex items-center gap-2 text-solar-400">
        <Pause className="w-5 h-5" />
        <h2 className="text-lg font-body font-medium">Workflow Paused</h2>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="rounded-md bg-space-800/50 border border-space-600/50 p-3">
          <div className="text-[10px] text-comet-500 uppercase tracking-wider">Reason</div>
          <div className="text-sm font-medium text-comet-200 mt-1">{reason}</div>
        </div>
        <div className="rounded-md bg-space-800/50 border border-space-600/50 p-3">
          <div className="text-[10px] text-comet-500 uppercase tracking-wider">Duration</div>
          <div className="text-sm font-medium text-comet-200 mt-1">{duration}s</div>
        </div>
        <div className="rounded-md bg-space-800/50 border border-space-600/50 p-3">
          <div className="text-[10px] text-comet-500 uppercase tracking-wider">Cycles</div>
          <div className="text-sm font-medium text-comet-200 mt-1">{cycles}</div>
        </div>
        <div className="rounded-md bg-space-800/50 border border-space-600/50 p-3">
          <div className="text-[10px] text-comet-500 uppercase tracking-wider">Tokens</div>
          <div className="text-sm font-medium text-comet-200 mt-1">{tokens}</div>
        </div>
      </div>

      <div className="space-y-2">
        <label htmlFor="human-input" className="text-sm font-medium text-comet-300">
          Human Response
        </label>
        <textarea
          id="human-input"
          value={humanInput}
          onChange={(e) => setHumanInput(e.target.value)}
          placeholder="Enter response to resume workflow..."
          className="w-full min-h-[100px] rounded-md bg-space-800 border border-space-600 p-3 text-sm text-comet-100 placeholder:text-comet-600 focus:outline-none focus:ring-2 focus:ring-aurora-500/50 focus:border-aurora-500/50 resize-y"
        />
      </div>

      <div className="flex items-center gap-3">
        <Button
          variant="primary"
          size="sm"
          onClick={() => onResume(humanInput)}
          disabled={isPending || !humanInput.trim()}
        >
          <Play className="w-4 h-4" />
          Resume
        </Button>
        <Button
          variant="danger"
          size="sm"
          onClick={onCancel}
          disabled={isPending}
        >
          <Ban className="w-4 h-4" />
          Cancel
        </Button>
      </div>

      {resumeError && (
        <div className="text-sm text-mars-400 bg-mars-500/10 border border-mars-500/20 rounded-md p-3">
          {resumeError}
        </div>
      )}
    </Panel>
  );
}

// --- Enhanced TimelineStrip ---

const LIFECYCLE_EVENT_TYPES = [
  "workflow_submitted",
  "cycle_started",
  "plan_generated",
  "workflow_paused",
  "workflow_resumed",
  "workflow_completed",
  "node_started",
  "node_completed",
  "node_failed",
];

function TimelineStrip({
  events,
}: {
  events: { id: string; event_type: string; timestamp: string }[];
}) {
  const filteredEvents = useMemo(() => {
    return events
      .filter((e) => LIFECYCLE_EVENT_TYPES.includes(e.event_type))
      .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
  }, [events]);

  if (filteredEvents.length === 0) {
    return (
      <Panel className="text-center py-8 text-comet-500 text-sm">
        No lifecycle events recorded
      </Panel>
    );
  }

  const dotColor = (eventType: string): string => {
    if (eventType.startsWith("workflow_") || eventType === "cycle_started" || eventType === "plan_generated") {
      return "bg-comet-400"; // lifecycle = comet
    }
    if (eventType === "node_started") {
      return "bg-aurora-400"; // OPA / start = aurora
    }
    if (eventType === "node_completed") {
      return "bg-nebula-400"; // node completion = nebula
    }
    if (eventType === "node_failed") {
      return "bg-mars-400"; // node failure = mars
    }
    return "bg-comet-400";
  };

  const categoryLabel = (eventType: string): string => {
    if (eventType.startsWith("workflow_") || eventType === "cycle_started" || eventType === "plan_generated") {
      return "lifecycle";
    }
    if (eventType === "node_started") {
      return "opa";
    }
    if (eventType === "node_completed") {
      return "completion";
    }
    if (eventType === "node_failed") {
      return "failure";
    }
    return "other";
  };

  return (
    <div className="relative">
      {/* Horizontal connecting line */}
      <div className="absolute top-[11px] left-0 right-0 h-px bg-space-600/50" />
      <div className="flex gap-6 overflow-x-auto pb-4 pt-1">
        {filteredEvents.map((event) => (
          <div key={event.id} className="flex flex-col items-center min-w-[120px] relative z-10">
            <div
              className={cn(
                "w-3 h-3 rounded-full border-2 border-space-900",
                dotColor(event.event_type)
              )}
              title={categoryLabel(event.event_type)}
            />
            <span className="text-[10px] font-mono text-comet-400 mt-2 text-center capitalize">
              {event.event_type.replace(/_/g, " ")}
            </span>
            <span className="text-[10px] text-comet-600 mt-0.5 text-center">
              {formatTimestamp(event.timestamp)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function WorkflowDetailPage({
  params,
}: {
  params: { id: string };
}) {
  const id = params.id;
  const { data: workflow, isLoading: wfLoading } = useWorkflow(id);
  const { data: status } = useWorkflowStatus(id);
  const { data: metrics } = useWorkflowMetrics(id);
  const { data: events } = useWorkflowEvents(id, { limit: 20 });

  const cancelMutation = useCancelWorkflow();
  const resumeMutation = useResumeWorkflow();
  const { toast } = useToast();
  const { copy } = useCopyToClipboard();

  const [selectedNode, setSelectedNode] = useState<NodeInspectorNode | null>(null);
  const [resumeError, setResumeError] = useState<string | null>(null);

  const handleResume = useCallback(
    (humanInput: string) => {
      setResumeError(null);
      resumeMutation.mutate(
        { id, humanInput },
        {
          onSuccess: () => {
            toast({ message: "Workflow resumed", variant: "success" });
          },
          onError: (err) => {
            const msg = err?.message ?? "Failed to resume workflow";
            setResumeError(msg);
            toast({ message: msg, variant: "error" });
          },
        }
      );
    },
    [id, resumeMutation, toast]
  );

  const handleCancel = useCallback(() => {
    cancelMutation.mutate(id, {
      onSuccess: () => {
        toast({ message: "Workflow cancelled", variant: "success" });
      },
      onError: (err) => {
        toast({
          message: err?.message ?? "Failed to cancel workflow",
          variant: "error",
        });
      },
    });
  }, [id, cancelMutation, toast]);

  const handleNodeClick = useCallback(
    (node: { name: string; status: string }) => {
      setSelectedNode({
        name: node.name,
        status: node.status,
      });
    },
    []
  );

  const handleCloseInspector = useCallback(() => {
    setSelectedNode(null);
  }, []);

  const nodes = status?.nodes || [];
  const workflowEvents = events || [];

  const canCancel = workflow?.status === "running" || workflow?.status === "pending";
  const canResume = workflow?.status === "paused";

  // Page-level shortcuts: copy ID, pause/resume (with confirm).
  useKeyboardShortcuts({
    "Ctrl+Shift+C": () => {
      copy(id, "workflow ID");
    },
    "Ctrl+Shift+P": () => {
      if (canResume) {
        if (typeof window !== "undefined" && window.confirm("Resume this workflow?")) {
          handleResume("");
        }
      } else if (canCancel) {
        if (typeof window !== "undefined" && window.confirm("Cancel this workflow?")) {
          handleCancel();
        }
      } else {
        toast({ message: "No action available for current status", variant: "info" });
      }
    },
  });

  return (
    <Shell>
      <div className="space-y-6">
        {/* Breadcrumb */}
        <div className="flex items-center gap-2 text-sm text-comet-500">
          <Link
            href="/workflows"
            aria-label="Back to workflows list"
            className="flex items-center gap-1 hover:text-aurora-400 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" aria-hidden="true" />
            Workflows
          </Link>
          <span>/</span>
          <CopyButton text={id} />
        </div>

        {wfLoading ? (
          <div className="space-y-4">
            <div className="h-8 w-64 bg-space-700/50 rounded animate-pulse" />
            <div className="h-32 bg-space-700/50 rounded animate-pulse" />
          </div>
        ) : workflow ? (
          <>
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

              {/* Actions */}
              <div className="flex items-center gap-2">
                {canCancel && (
                  <Button
                    variant="danger"
                    size="sm"
                    onClick={handleCancel}
                    disabled={cancelMutation.isPending}
                  >
                    <Ban className="w-4 h-4" />
                    Cancel
                  </Button>
                )}
                {canResume && (
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => handleResume("")}
                    disabled={resumeMutation.isPending}
                  >
                    <Play className="w-4 h-4" />
                    Resume
                  </Button>
                )}
              </div>
            </div>

            {/* Tab navigation */}
            <WorkflowNav activeTab="overview" />

            {/* Pause Response Panel */}
            {workflow.status === "paused" && (
              <PauseResponsePanel
                reason={workflow.pause_reason ?? "Unknown"}
                duration={workflow.pause_duration ?? 0}
                cycles={workflow.pause_cycles ?? 0}
                tokens={workflow.pause_tokens ?? 0}
                onResume={handleResume}
                onCancel={handleCancel}
                isPending={resumeMutation.isPending || cancelMutation.isPending}
                resumeError={resumeError}
              />
            )}

            {/* KPI Strip */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
              <KpiCard
                label="OPA Cycles"
                value={metrics?.cycle_count ?? "—"}
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

            {/* Mini Constellation */}
            <Panel variant="elevated" padding="lg">
              <h2 className="text-lg font-body font-medium text-comet-100 mb-4 flex items-center gap-2">
                <Orbit className="w-5 h-5 text-aurora-400" />
                Mini Constellation
              </h2>
              <MiniConstellation nodes={nodes} onNodeClick={handleNodeClick} />
            </Panel>

            {/* Timeline Strip */}
            <Panel variant="elevated" padding="lg">
              <h2 className="text-lg font-body font-medium text-comet-100 mb-4 flex items-center gap-2">
                <Clock className="w-5 h-5 text-aurora-400" />
                Timeline
              </h2>
              <TimelineStrip events={workflowEvents} />
            </Panel>

            {/* Node Inspector */}
            {selectedNode && (
              <NodeInspector
                node={selectedNode}
                events={workflowEvents}
                isOpen={true}
                onClose={handleCloseInspector}
              />
            )}
          </>
        ) : (
          <Panel className="text-center py-12">
            <p className="text-comet-300 font-display text-lg mb-1">
              Workflow not found
            </p>
            <p className="text-sm text-comet-500 mb-5">
              The workflow you&apos;re looking for doesn&apos;t exist or
              has been removed.
            </p>
            <Button asChild variant="primary" size="default">
              <Link href="/workflows">Back to workflows</Link>
            </Button>
          </Panel>
        )}
      </div>
    </Shell>
  );
}
