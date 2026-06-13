"use client";

import { Suspense, useState, useCallback, useMemo, useRef, useEffect } from "react";
import { Shell } from "@/components/shell/shell";
import { Panel } from "@/components/ui/panel";
import { Badge } from "@/components/ui/badge";
import { StatusOrb } from "@/components/ui/status-orb";
import { Button } from "@/components/ui/button";
import {
  useWorkflow,
  useCancelWorkflow,
  useResumeWorkflow,
} from "@/hooks/useWorkflow";
import { useWorkflowWorkflowEvents } from "@/hooks/useWorkflowEvents";
import { useToast } from "@/hooks/useToast";
import { formatTimestamp, formatDuration } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { WorkflowEvent, WorkflowWorkflowEvent } from "@/lib/types";
import ArrowLeft from "lucide-react/dist/esm/icons/arrow-left";
import Hand from "lucide-react/dist/esm/icons/hand";
import Pause from "lucide-react/dist/esm/icons/pause";
import Ban from "lucide-react/dist/esm/icons/ban";
import Clock from "lucide-react/dist/esm/icons/clock";
import RotateCcw from "lucide-react/dist/esm/icons/rotate-ccw";
import MessageSquare from "lucide-react/dist/esm/icons/message-square";
import AlertTriangle from "lucide-react/dist/esm/icons/alert-triangle";
import Send from "lucide-react/dist/esm/icons/send";
import Eye from "lucide-react/dist/esm/icons/eye";
import EyeOff from "lucide-react/dist/esm/icons/eye-off";
import Link from "next/link";
import { WorkflowNav } from "@/components/workflow/workflow-nav";

const ESCALATION_EVENT_TYPES = [
  "ESCALATE",
  "WORKFLOW_PAUSED",
  "HUMAN_INPUT_RECEIVED",
  "WORKFLOW_RESUMED",
];

// ------------------------------------------------------------------
// Helpers
// ------------------------------------------------------------------

function isEscalationEvent(event: { event_type: string }): boolean {
  return ESCALATION_EVENT_TYPES.includes(event.event_type);
}

function eventTypeLabel(eventType: string): string {
  switch (eventType) {
    case "ESCALATE":
      return "Escalated";
    case "WORKFLOW_PAUSED":
      return "Paused";
    case "HUMAN_INPUT_RECEIVED":
      return "Human Input";
    case "WORKFLOW_RESUMED":
      return "Resumed";
    default:
      return eventType.replace(/_/g, " ");
  }
}

function eventTypeColor(eventType: string): string {
  switch (eventType) {
    case "ESCALATE":
      return "text-mars-400 bg-mars-500/10 border-mars-500/30";
    case "WORKFLOW_PAUSED":
      return "text-solar-400 bg-solar-500/10 border-solar-500/30";
    case "HUMAN_INPUT_RECEIVED":
      return "text-aurora-400 bg-aurora-500/10 border-aurora-500/30";
    case "WORKFLOW_RESUMED":
      return "text-nebula-400 bg-nebula-500/10 border-nebula-500/30";
    default:
      return "text-comet-400 bg-comet-500/10 border-comet-500/30";
  }
}

function eventTypeOrbVariant(
  eventType: string
): "idle" | "running" | "success" | "warning" | "error" | "info" {
  switch (eventType) {
    case "ESCALATE":
      return "error";
    case "WORKFLOW_PAUSED":
      return "warning";
    case "HUMAN_INPUT_RECEIVED":
      return "info";
    case "WORKFLOW_RESUMED":
      return "success";
    default:
      return "idle";
  }
}

function useMarkdownPreview(text: string): string {
  return useMemo(() => {
    if (!text.trim()) return "";
    // Minimal client-side markdown: bold, italic, code, paragraphs, line breaks
    const html = text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/```([\s\S]*?)```/g, "<pre class='bg-space-800 p-2 rounded text-xs font-mono overflow-x-auto my-2'><code>$1</code></pre>")
      .replace(/`([^`]+)`/g, "<code class='bg-space-700 px-1 rounded text-xs font-mono'>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong class='text-comet-100'>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em class='text-comet-300'>$1</em>")
      .replace(/^(#{1,6})\s+(.+)$/gm, (_match, hashes, content) => {
        const level = Math.min(hashes.length, 6);
        const sizes = ["text-lg", "text-base", "text-sm", "text-sm", "text-xs", "text-xs"];
        return `<h${level} class='${sizes[level - 1]} font-medium text-comet-100 mt-3 mb-1'>${content}</h${level}>`;
      })
      .replace(/\n/g, "<br/>");
    return html;
  }, [text]);
}

// ------------------------------------------------------------------
// Pause State Panel
// ------------------------------------------------------------------

function PauseStatePanel({
  reason,
  durationSeconds,
  cycles,
  tokens,
}: {
  reason: string;
  durationSeconds: number;
  cycles: number;
  tokens: number;
}) {
  return (
    <Panel variant="elevated" padding="lg" className="space-y-4">
      <div className="flex items-center gap-2 text-solar-400">
        <Pause className="w-5 h-5" aria-hidden="true" />
        <h2 className="text-lg font-body font-medium">Workflow Paused</h2>
        <Badge variant="warning">Awaiting Human Input</Badge>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="rounded-md bg-space-800/50 border border-space-600/50 p-3">
          <div className="text-[10px] text-comet-500 uppercase tracking-wider">
            Reason
          </div>
          <div className="text-sm font-medium text-comet-200 mt-1">{reason}</div>
        </div>
        <div className="rounded-md bg-space-800/50 border border-space-600/50 p-3">
          <div className="text-[10px] text-comet-500 uppercase tracking-wider">
            Duration
          </div>
          <div className="text-sm font-medium text-comet-200 mt-1">
            {formatDuration(durationSeconds * 1000)}
          </div>
        </div>
        <div className="rounded-md bg-space-800/50 border border-space-600/50 p-3">
          <div className="text-[10px] text-comet-500 uppercase tracking-wider">
            Cycles
          </div>
          <div className="text-sm font-medium text-comet-200 mt-1">{cycles}</div>
        </div>
        <div className="rounded-md bg-space-800/50 border border-space-600/50 p-3">
          <div className="text-[10px] text-comet-500 uppercase tracking-wider">
            Tokens
          </div>
          <div className="text-sm font-medium text-comet-200 mt-1">
            {tokens.toLocaleString()}
          </div>
        </div>
      </div>
    </Panel>
  );
}

// ------------------------------------------------------------------
// Human Input Editor
// ------------------------------------------------------------------

function HumanInputEditor({
  onSubmit,
  isPending,
  disabled,
}: {
  onSubmit: (humanInput: string) => void;
  isPending: boolean;
  disabled: boolean;
}) {
  const [humanInput, setHumanInput] = useState("");
  const [showPreview, setShowPreview] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const previewHtml = useMarkdownPreview(humanInput);

  // Auto-focus textarea when enabled
  useEffect(() => {
    if (!disabled && textareaRef.current) {
      textareaRef.current.focus();
    }
  }, [disabled]);

  const handleSubmit = useCallback(() => {
    const trimmed = humanInput.trim();
    if (!trimmed) return;
    onSubmit(trimmed);
    setHumanInput("");
  }, [humanInput, onSubmit]);

  return (
    <Panel variant="elevated" padding="lg" className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-aurora-400">
          <MessageSquare className="w-5 h-5" aria-hidden="true" />
          <h2 className="text-lg font-body font-medium">Human Response</h2>
        </div>
        <Button
          variant="subtle"
          size="sm"
          onClick={() => setShowPreview((s) => !s)}
          disabled={!humanInput.trim()}
          aria-label={showPreview ? "Hide preview" : "Show preview"}
        >
          {showPreview ? (
            <>
              <EyeOff className="w-4 h-4" /> Hide Preview
            </>
          ) : (
            <>
              <Eye className="w-4 h-4" /> Preview
            </>
          )}
        </Button>
      </div>

      <div className="space-y-2">
        <label htmlFor="human-input" className="text-sm font-medium text-comet-300 sr-only">
          Human Response
        </label>
        <textarea
          id="human-input"
          ref={textareaRef}
          value={humanInput}
          onChange={(e) => setHumanInput(e.target.value)}
          placeholder="Enter your response to resume the workflow..."
          disabled={disabled || isPending}
          className={cn(
            "w-full min-h-[140px] rounded-md bg-space-800 border border-space-600 p-3 text-sm text-comet-100 placeholder:text-comet-600 focus:outline-none focus:ring-2 focus:ring-aurora-500/50 focus:border-aurora-500/50 resize-y",
            (disabled || isPending) && "opacity-50 cursor-not-allowed"
          )}
          aria-describedby="human-input-help"
        />
        <p id="human-input-help" className="text-xs text-comet-500">
          Markdown supported: **bold**, *italic*, `code`, ```code blocks```
        </p>
      </div>

      {showPreview && humanInput.trim() && (
        <div
          className="rounded-md bg-space-800/50 border border-space-600/50 p-4 text-sm text-comet-200"
          aria-label="Markdown preview"
          dangerouslySetInnerHTML={{ __html: previewHtml }}
        />
      )}

      <div className="flex items-center gap-3">
        <Button
          variant="primary"
          size="sm"
          onClick={handleSubmit}
          disabled={disabled || isPending || !humanInput.trim()}
          aria-live="polite"
        >
          <Send className="w-4 h-4" />
          {isPending ? "Submitting..." : "Submit & Resume"}
        </Button>
      </div>
    </Panel>
  );
}

// ------------------------------------------------------------------
// Cancel Button
// ------------------------------------------------------------------

function CancelButton({
  onCancel,
  isPending,
  disabled,
}: {
  onCancel: () => void;
  isPending: boolean;
  disabled: boolean;
}) {
  const [confirming, setConfirming] = useState(false);

  const handleClick = useCallback(() => {
    if (!confirming) {
      setConfirming(true);
      return;
    }
    onCancel();
    setConfirming(false);
  }, [confirming, onCancel]);

  const handleCancelConfirm = useCallback(() => {
    setConfirming(false);
  }, []);

  return (
    <div className="flex items-center gap-3">
      <Button
        variant="danger"
        size="sm"
        onClick={handleClick}
        disabled={disabled || isPending}
        aria-live="polite"
        aria-label={confirming ? "Confirm cancel workflow" : "Cancel workflow"}
      >
        <Ban className="w-4 h-4" aria-hidden="true" />
        {confirming ? "Confirm Cancel" : "Cancel Workflow"}
      </Button>
      {confirming && (
        <Button variant="subtle" size="sm" onClick={handleCancelConfirm}>
          Never mind
        </Button>
      )}
    </div>
  );
}

// ------------------------------------------------------------------
// Escalation Timeline
// ------------------------------------------------------------------

function EscalationTimeline({
  events,
}: {
  events: (WorkflowWorkflowEvent | WorkflowEvent)[];
}) {
  const sorted = useMemo(() => {
    return [...events].sort(
      (a, b) =>
        new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
    );
  }, [events]);

  if (sorted.length === 0) {
    return (
      <Panel className="text-center py-10">
        <div className="flex flex-col items-center gap-3">
          <Hand className="w-8 h-8 text-comet-600" aria-hidden="true" />
          <p className="text-comet-400 text-sm">No escalation events recorded</p>
          <p className="text-comet-600 text-xs">
            Escalation events appear when a workflow pauses for human input or is
            resumed.
          </p>
        </div>
      </Panel>
    );
  }

  return (
    <Panel variant="elevated" padding="lg" className="space-y-4">
      <div className="flex items-center gap-2 text-comet-100">
        <Clock className="w-5 h-5 text-aurora-400" aria-hidden="true" />
        <h2 className="text-lg font-body font-medium">Escalation History</h2>
        <span className="text-xs text-comet-500 ml-auto">
          {sorted.length} event{sorted.length !== 1 ? "s" : ""}
        </span>
      </div>

      <div className="relative space-y-0">
        {/* Vertical line */}
        <div className="absolute left-[19px] top-2 bottom-2 w-px bg-space-600/50" aria-hidden="true" />

        <ul className="space-y-4" role="list">
          {sorted.map((event) => {
            const label = eventTypeLabel(event.event_type);
            const colorClass = eventTypeColor(event.event_type);
            const orbVariant = eventTypeOrbVariant(event.event_type);

            // Extract human input from event_data if present
            const humanInput =
              event.event_data && typeof event.event_data === "object"
                ? (event.event_data as Record<string, unknown>).human_input
                : undefined;

            return (
              <li key={event.id} className="relative flex items-start gap-4">
                <div className="relative z-10 mt-1">
                  <StatusOrb variant={orbVariant} size="md" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span
                      className={cn(
                        "inline-flex items-center px-2 py-0.5 text-xs font-mono font-medium rounded-sm border",
                        colorClass
                      )}
                    >
                      {label}
                    </span>
                    <span className="text-xs text-comet-500 font-mono">
                      {formatTimestamp(event.timestamp)}
                    </span>
                  </div>
                  {typeof humanInput === "string" && humanInput && (
                    <div className="mt-2 rounded-md bg-space-800/50 border border-space-600/30 p-2">
                      <p className="text-xs text-comet-500 uppercase tracking-wider mb-1">
                        Input
                      </p>
                      <p className="text-sm text-comet-200 whitespace-pre-wrap">
                        {humanInput}
                      </p>
                    </div>
                  )}
                  {event.event_data &&
                    typeof (event.event_data as Record<string, unknown>).reason ===
                      "string" && (
                      <p className="mt-1 text-xs text-comet-400">
                        Reason:{" "}
                        {String(
                          (event.event_data as Record<string, unknown>).reason
                        )}
                      </p>
                    )}
                </div>
              </li>
            );
          })}
        </ul>
      </div>
    </Panel>
  );
}

// ------------------------------------------------------------------
// Status Panel (when not paused)
// ------------------------------------------------------------------

function StatusPanel({
  status,
  reason,
}: {
  status: string;
  reason?: string;
}) {
  const statusConfig: Record<
    string,
    { color: string; icon: React.ReactNode; message: string }
  > = {
    running: {
      color: "text-aurora-400",
      icon: <RotateCcw className="w-5 h-5 animate-spin" aria-hidden="true" />,
      message: "Workflow is running. No human intervention required.",
    },
    completed: {
      color: "text-nebula-400",
      icon: <StatusOrb variant="success" size="md" />,
      message: "Workflow completed successfully.",
    },
    failed: {
      color: "text-mars-400",
      icon: <AlertTriangle className="w-5 h-5" aria-hidden="true" />,
      message: "Workflow failed. Check the overview or event ledger for details.",
    },
    cancelled: {
      color: "text-comet-400",
      icon: <Ban className="w-5 h-5" aria-hidden="true" />,
      message: "Workflow was cancelled.",
    },
    pending: {
      color: "text-solar-400",
      icon: <Clock className="w-5 h-5" aria-hidden="true" />,
      message: "Workflow is pending. It will start automatically.",
    },
  };

  const config = statusConfig[status] || {
    color: "text-comet-400",
    icon: <StatusOrb variant="idle" size="md" />,
    message: `Workflow status: ${status}`,
  };

  return (
    <Panel variant="elevated" padding="lg" className="space-y-3">
      <div className={cn("flex items-center gap-2", config.color)}>
        {config.icon}
        <h2 className="text-lg font-body font-medium capitalize">{status}</h2>
      </div>
      <p className="text-sm text-comet-300">{config.message}</p>
      {reason && (
        <p className="text-xs text-comet-500">Last pause reason: {reason}</p>
      )}
    </Panel>
  );
}

// ------------------------------------------------------------------
// Main Page
// ------------------------------------------------------------------

export default function EscalationPage({
  params,
}: {
  params: { id: string };
}) {
  return (
    <Suspense fallback={<Shell><div className="space-y-4"><div className="h-8 w-64 bg-space-700/50 rounded animate-pulse" /></div></Shell>}>
      <EscalationPageInner params={params} />
    </Suspense>
  );
}

function EscalationPageInner({
  params,
}: {
  params: { id: string };
}) {
  const id = params.id;
  const {
    data: workflow,
    isLoading: wfLoading,
    error: wfError,
  } = useWorkflow(id);
  const {
    data: workflowEvents,
    isLoading: eventsLoading,
    error: eventsError,
  } = useWorkflowWorkflowEvents(id, { limit: 200 });

  const cancelMutation = useCancelWorkflow();
  const resumeMutation = useResumeWorkflow();
  const { toast } = useToast();

  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);
  const liveRegionRef = useRef<HTMLDivElement>(null);

  // Clear action messages after 5 seconds
  useEffect(() => {
    if (actionSuccess || actionError) {
      const timer = setTimeout(() => {
        setActionSuccess(null);
        setActionError(null);
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [actionSuccess, actionError]);

  // Filter escalation events from workflow-events, fallback to empty
  const escalationEvents = useMemo(() => {
    const source = workflowEvents || [];
    const filtered = source.filter(isEscalationEvent);
    return filtered;
  }, [workflowEvents]);

  const isPaused = workflow?.status === "paused";
  const canCancel =
    workflow?.status === "running" ||
    workflow?.status === "pending" ||
    workflow?.status === "paused";
  const canResume = isPaused;

  const handleResume = useCallback(
    (humanInput: string) => {
      setActionError(null);
      setActionSuccess(null);
      resumeMutation.mutate(
        { id, humanInput },
        {
          onSuccess: () => {
            setActionSuccess("Workflow resumed successfully.");
            toast({ message: "Workflow resumed", variant: "success" });
          },
          onError: (err) => {
            const msg = err?.message ?? "Failed to resume workflow";
            setActionError(msg);
            toast({ message: msg, variant: "error" });
          },
        }
      );
    },
    [id, resumeMutation, toast]
  );

  const handleCancel = useCallback(() => {
    setActionError(null);
    setActionSuccess(null);
    cancelMutation.mutate(id, {
      onSuccess: () => {
        setActionSuccess("Workflow cancelled.");
        toast({ message: "Workflow cancelled", variant: "success" });
      },
      onError: (err) => {
        const msg = err?.message ?? "Failed to cancel workflow";
        setActionError(msg);
        toast({ message: msg, variant: "error" });
      },
    });
  }, [id, cancelMutation, toast]);

  const isPending = resumeMutation.isPending || cancelMutation.isPending;
  // isPending is used for future accessibility/tooltip logic
  void isPending;

  return (
    <Shell>
      <div className="space-y-6">
        {/* Breadcrumb */}
        <div className="flex items-center gap-2 text-sm text-comet-500">
          <Link
            href="/workflows"
            className="flex items-center gap-1 hover:text-aurora-400 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" aria-hidden="true" />
            Workflows
          </Link>
          <span aria-hidden="true">/</span>
          <Link
            href={`/workflows/${id}`}
            className="hover:text-aurora-400 transition-colors"
          >
            {id.slice(0, 8)}
          </Link>
          <span aria-hidden="true">/</span>
          <span className="text-comet-300">Escalation</span>
        </div>

        {/* Header */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex items-start gap-4">
            <StatusOrb
              variant={
                workflow?.status === "running"
                  ? "running"
                  : workflow?.status === "completed"
                  ? "success"
                  : workflow?.status === "failed"
                  ? "error"
                  : workflow?.status === "paused"
                  ? "warning"
                  : "idle"
              }
              size="lg"
              pulse={workflow?.status === "running"}
            />
            <div>
              <h1 className="text-3xl font-display text-comet-100">
                {workflow?.name ?? "Workflow"}
              </h1>
              <div className="flex items-center gap-3 mt-2 flex-wrap">
                {workflow && (
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
                )}
                <span className="text-xs font-mono text-comet-500">{id}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Tab navigation */}
        <WorkflowNav activeTab="escalation" />

        {/* Aria-live region for action outcomes */}
        <div
          ref={liveRegionRef}
          className="sr-only"
          aria-live="polite"
          aria-atomic="true"
        >
          {actionSuccess || actionError || ""}
        </div>

        {/* Loading state */}
        {wfLoading && (
          <div className="space-y-4">
            <div className="h-32 bg-space-700/50 rounded animate-pulse" />
            <div className="h-48 bg-space-700/50 rounded animate-pulse" />
            <div className="h-64 bg-space-700/50 rounded animate-pulse" />
          </div>
        )}

        {/* Error state */}
        {wfError && !wfLoading && (
          <Panel className="text-center py-10">
            <div className="flex flex-col items-center gap-3">
              <AlertTriangle className="w-8 h-8 text-mars-400" aria-hidden="true" />
              <p className="text-mars-400 text-sm">
                Failed to load workflow details
              </p>
              <p className="text-comet-500 text-xs">
                {wfError instanceof Error ? wfError.message : "Unknown error"}
              </p>
            </div>
          </Panel>
        )}

        {/* Main content */}
        {!wfLoading && !wfError && workflow && (
          <>
            {/* Pause State Panel — prominent when paused */}
            {isPaused && (
              <PauseStatePanel
                reason={workflow.pause_reason ?? "Unknown"}
                durationSeconds={workflow.pause_duration ?? 0}
                cycles={workflow.pause_cycles ?? 0}
                tokens={workflow.pause_tokens ?? 0}
              />
            )}

            {/* Status panel when not paused */}
            {!isPaused && <StatusPanel status={workflow.status} reason={workflow.pause_reason} />}

            {/* Human Input Editor — only when paused */}
            {canResume && (
              <HumanInputEditor
                onSubmit={handleResume}
                isPending={resumeMutation.isPending}
                disabled={!canResume}
              />
            )}

            {/* Action buttons */}
            <div className="flex items-center gap-3">
              {canCancel && (
                <CancelButton
                  onCancel={handleCancel}
                  isPending={cancelMutation.isPending}
                  disabled={!canCancel}
                />
              )}
            </div>

            {/* Inline action error */}
            {actionError && (
              <div
                className="rounded-md bg-mars-500/10 border border-mars-500/20 p-3 text-sm text-mars-400"
                role="alert"
              >
                {actionError}
              </div>
            )}

            {/* Inline action success */}
            {actionSuccess && (
              <div
                className="rounded-md bg-nebula-500/10 border border-nebula-500/20 p-3 text-sm text-nebula-400"
                role="status"
              >
                {actionSuccess}
              </div>
            )}

            {/* Escalation History */}
            {eventsLoading ? (
              <div className="h-64 bg-space-700/50 rounded animate-pulse" />
            ) : eventsError ? (
              <Panel className="text-center py-10">
                <div className="flex flex-col items-center gap-3">
                  <AlertTriangle
                    className="w-8 h-8 text-mars-400"
                    aria-hidden="true"
                  />
                  <p className="text-mars-400 text-sm">
                    Failed to load escalation events
                  </p>
                  <p className="text-comet-500 text-xs">
                    {eventsError instanceof Error
                      ? eventsError.message
                      : "Unknown error"}
                  </p>
                </div>
              </Panel>
            ) : (
              <EscalationTimeline events={escalationEvents} />
            )}
          </>
        )}
      </div>
    </Shell>
  );
}
