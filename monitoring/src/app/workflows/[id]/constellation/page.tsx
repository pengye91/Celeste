"use client";

import { Suspense, use, useState, useCallback, useMemo } from "react";
import Link from "next/link";
import { Shell } from "@/components/shell/shell";
import { Panel } from "@/components/ui/panel";
import { Badge } from "@/components/ui/badge";
import { StatusOrb } from "@/components/ui/status-orb";
import { Button } from "@/components/ui/button";
import { ConstellationView } from "@/components/constellation/constellation-view";
import type { ConstellationNode } from "@/components/constellation/constellation-view";
import { NodeInspector } from "@/components/workflow/node-inspector";
import { WorkflowNav } from "@/components/workflow/workflow-nav";
import type { NodeInspectorNode } from "@/components/workflow/node-inspector";
import {
  useWorkflow,
  useWorkflowStatus,
  useWorkflowMetrics,
} from "@/hooks/useWorkflow";
import { useWorkflowEvents } from "@/hooks/useWorkflowEvents";
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard";
import ArrowLeft from "lucide-react/dist/esm/icons/arrow-left";
import Copy from "lucide-react/dist/esm/icons/copy";
import Orbit from "lucide-react/dist/esm/icons/orbit";
import Check from "lucide-react/dist/esm/icons/check";

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

/* ───────────────────────────────────────────────
   Build ConstellationNode[] from status + dag
   ─────────────────────────────────────────────── */

function buildConstellationNodes(
  statusNodes: { name: string; status: string }[],
  dagDefinition: Record<string, unknown>
): ConstellationNode[] {
  const dagNodes = dagDefinition?.nodes as
    | Array<{
        name?: string;
        dependencies?: string[];
        task_type?: string;
        command?: string;
        arguments?: Record<string, unknown>;
        outputs?: Record<string, unknown>;
      }>
    | undefined;

  const dagMap = new Map<string, {
    dependencies?: string[];
    task_type?: string;
    command?: string;
    arguments?: Record<string, unknown>;
    outputs?: Record<string, unknown>;
  }>();

  if (dagNodes && Array.isArray(dagNodes)) {
    for (const n of dagNodes) {
      if (n.name) {
        dagMap.set(n.name, {
          dependencies: n.dependencies,
          task_type: n.task_type,
          command: n.command,
          arguments: n.arguments,
          outputs: n.outputs,
        });
      }
    }
  }

  return statusNodes.map((sn) => {
    const dag = dagMap.get(sn.name);
    return {
      name: sn.name,
      status: sn.status,
      dependencies: dag?.dependencies,
      task_type: dag?.task_type,
      command: dag?.command,
      arguments: dag?.arguments,
      outputs: dag?.outputs,
    };
  });
}

/* ───────────────────────────────────────────────
   Page
   ─────────────────────────────────────────────── */

export default function ConstellationPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  return (
    <Suspense fallback={<Shell><div className="space-y-4"><div className="h-8 w-64 bg-space-700/50 rounded animate-pulse" /></div></Shell>}>
      <ConstellationPageInner params={params} />
    </Suspense>
  );
}

function ConstellationPageInner({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);

  const { data: workflow, isLoading: wfLoading, error: wfError } = useWorkflow(id);
  const { data: status } = useWorkflowStatus(id);
  const { data: metrics } = useWorkflowMetrics(id);
  const { data: events } = useWorkflowEvents(id, { limit: 100 });

  const [selectedNode, setSelectedNode] = useState<ConstellationNode | null>(null);

  const nodes = useMemo(() => {
    const statusNodes = status?.nodes ?? [];
    const dag = workflow?.dag_definition ?? {};
    return buildConstellationNodes(statusNodes, dag);
  }, [status?.nodes, workflow?.dag_definition]);

  const activeNodeName = useMemo(() => {
    return status?.nodes?.find((n) => n.status === "running")?.name;
  }, [status?.nodes]);

  const handleNodeSelect = useCallback((node: ConstellationNode | undefined) => {
    setSelectedNode(node ?? null);
  }, []);

  const handleCloseInspector = useCallback(() => {
    setSelectedNode(null);
  }, []);

  // Convert ConstellationNode to NodeInspectorNode for the side panel
  const inspectorNode: NodeInspectorNode | null = selectedNode
    ? {
        name: selectedNode.name,
        status: selectedNode.status,
        task_type: selectedNode.task_type,
        command: selectedNode.command,
        arguments: selectedNode.arguments,
        outputs: selectedNode.outputs,
      }
    : null;

  const workflowEvents = events ?? [];

  return (
    <Shell>
      <div className="flex flex-col h-full">
        {/* ── Header ── */}
        <div className="shrink-0 space-y-4 pb-4">
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
            <CopyButton text={id} />
          </div>

          {wfLoading ? (
            <div className="space-y-3">
              <div className="h-8 w-64 bg-space-700/50 rounded animate-pulse" />
              <div className="h-6 w-48 bg-space-700/50 rounded animate-pulse" />
            </div>
          ) : workflow ? (
            <>
              {/* Title row */}
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

                {/* KPI mini-strip */}
                <div className="flex items-center gap-3">
                  {metrics && (
                    <>
                      <div className="text-xs font-mono text-comet-400">
                        <span className="text-comet-500">Nodes:</span>{" "}
                        {metrics.total_nodes}
                      </div>
                      <div className="text-xs font-mono text-comet-400">
                        <span className="text-comet-500">Cycles:</span>{" "}
                        {metrics.cycle_count}
                      </div>
                      <div className="text-xs font-mono text-comet-400">
                        <span className="text-comet-500">Done:</span>{" "}
                        {Math.round(metrics.completed_percent)}%
                      </div>
                    </>
                  )}
                </div>
              </div>

              {/* Tab navigation */}
              <WorkflowNav activeTab="constellation" />
            </>
          ) : null}
        </div>

        {/* ── Main content ── */}
        <div className="flex-1 min-h-0 relative">
          {wfLoading ? (
            <Panel className="h-full flex flex-col items-center justify-center gap-4">
              <div className="w-16 h-16 rounded-full bg-space-700/50 animate-pulse" />
              <div className="h-4 w-48 bg-space-700/50 rounded animate-pulse" />
              <div className="h-3 w-32 bg-space-700/50 rounded animate-pulse" />
            </Panel>
          ) : wfError || !workflow ? (
            <Panel className="h-full flex flex-col items-center justify-center gap-3">
              <Orbit className="w-8 h-8 text-comet-500 opacity-50" />
              <p className="text-comet-400 font-medium">Workflow not found</p>
              <p className="text-comet-500 text-sm">
                The workflow ID may be invalid or the workflow has been removed.
              </p>
              <Button variant="default" size="sm" asChild>
                <Link href="/workflows">
                  <ArrowLeft className="w-4 h-4" />
                  Back to workflows
                </Link>
              </Button>
            </Panel>
          ) : (
            <div className="flex h-full gap-4">
              {/* Constellation canvas */}
              <div className="flex-1 min-h-0">
                <Panel
                  padding="none"
                  className="h-full overflow-hidden border border-space-600/50"
                >
                  <ConstellationView
                    nodes={nodes}
                    selectedNode={selectedNode}
                    onNodeSelect={handleNodeSelect}
                    activeNodeName={activeNodeName}
                  />
                </Panel>
              </div>

              {/* Desktop side panel: NodeInspector */}
              {inspectorNode && (
                <div className="hidden md:block w-96 shrink-0">
                  <Panel
                    padding="none"
                    className="h-full overflow-hidden border border-space-600/50"
                  >
                    <NodeInspector
                      node={inspectorNode}
                      events={workflowEvents}
                      isOpen={true}
                      onClose={handleCloseInspector}
                    />
                  </Panel>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Mobile bottom sheet: NodeInspector */}
      {inspectorNode && (
        <div className="md:hidden">
          <NodeInspector
            node={inspectorNode}
            events={workflowEvents}
            isOpen={true}
            onClose={handleCloseInspector}
          />
        </div>
      )}
    </Shell>
  );
}
