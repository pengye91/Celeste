"use client";

import { useEffect, useCallback } from "react";
import { Panel } from "@/components/ui/panel";
import { StatusOrb } from "@/components/ui/status-orb";
import { Button } from "@/components/ui/button";
import { formatTimestamp } from "@/lib/format";
import { cn } from "@/lib/utils";
import X from "lucide-react/dist/esm/icons/x";
import Terminal from "lucide-react/dist/esm/icons/terminal";
import FileOutput from "lucide-react/dist/esm/icons/file-output";
import Activity from "lucide-react/dist/esm/icons/activity";
import type { WorkflowEvent } from "@/lib/types";

export interface NodeInspectorNode {
  name: string;
  status: string;
  task_type?: string;
  command?: string;
  arguments?: Record<string, unknown>;
  outputs?: Record<string, unknown>;
}

export interface NodeInspectorProps {
  node: NodeInspectorNode;
  events: WorkflowEvent[];
  onClose: () => void;
  isOpen: boolean;
}

export function NodeInspector({ node, events, onClose, isOpen }: NodeInspectorProps) {
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    },
    [onClose]
  );

  useEffect(() => {
    if (isOpen) {
      document.addEventListener("keydown", handleKeyDown);
    }
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen, handleKeyDown]);

  if (!isOpen) return null;

  const statusVariant =
    node.status === "running"
      ? "running"
      : node.status === "completed"
      ? "success"
      : node.status === "failed"
      ? "error"
      : "idle";

  const nodeEvents = events.filter(
    (e) =>
      e.event_data &&
      typeof e.event_data === "object" &&
      (e.event_data as Record<string, unknown>).node_name === node.name
  );

  return (
    <>
      {/* Backdrop / click-outside catcher */}
      <div
        className="fixed inset-0 z-40 bg-space-void/60 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Panel */}
      <div
        className={cn(
          "fixed z-50 bg-space-800 border border-space-600 shadow-xl flex flex-col",
          // Desktop: right-side panel
          "md:right-0 md:top-0 md:bottom-0 md:w-96 md:border-l md:border-t-0 md:border-b-0 md:border-r-0",
          // Mobile: bottom sheet
          "bottom-0 left-0 right-0 h-[70vh] md:h-auto rounded-t-xl md:rounded-none"
        )}
        role="dialog"
        aria-modal="true"
        aria-label={`Node inspector: ${node.name}`}
      >
        {/* Header */}
        <div className="flex items-center justify-between gap-3 p-4 border-b border-space-600/50 shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <StatusOrb
              variant={statusVariant}
              size="md"
              pulse={node.status === "running"}
            />
            <div className="min-w-0">
              <h2 className="text-sm font-semibold text-comet-100 truncate">
                {node.name}
              </h2>
              <span className="text-xs text-comet-500 capitalize">
                {node.status}
              </span>
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            aria-label="Close inspector"
          >
            <X className="w-4 h-4" />
          </Button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-4 space-y-5">
          {/* Task type */}
          {node.task_type && (
            <div className="text-xs text-comet-500">
              Type: <span className="text-comet-300 font-mono">{node.task_type}</span>
            </div>
          )}

          {/* Command */}
          <section>
            <h3 className="text-xs font-semibold text-comet-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <Terminal className="w-3.5 h-3.5" />
              Command
            </h3>
            {node.command ? (
              <div className="font-mono text-xs text-comet-200 bg-space-900/80 rounded-md p-3 border border-space-700/50 overflow-x-auto">
                {node.command}
              </div>
            ) : (
              <p className="text-xs text-comet-500 italic">No command recorded</p>
            )}
          </section>

          {/* Arguments */}
          {node.arguments && Object.keys(node.arguments).length > 0 && (
            <section>
              <h3 className="text-xs font-semibold text-comet-400 uppercase tracking-wider mb-2">
                Arguments
              </h3>
              <pre className="font-mono text-[11px] text-comet-200 bg-space-900/80 rounded-md p-3 border border-space-700/50 overflow-x-auto">
                {JSON.stringify(node.arguments, null, 2)}
              </pre>
            </section>
          )}

          {/* Outputs */}
          <section>
            <h3 className="text-xs font-semibold text-comet-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <FileOutput className="w-3.5 h-3.5" />
              Outputs
            </h3>
            {node.outputs && Object.keys(node.outputs).length > 0 ? (
              <pre className="font-mono text-[11px] text-comet-200 bg-space-900/80 rounded-md p-3 border border-space-700/50 overflow-x-auto">
                {JSON.stringify(node.outputs, null, 2)}
              </pre>
            ) : (
              <Panel padding="md" className="text-center text-comet-500 text-xs">
                <FileOutput className="w-4 h-4 mx-auto mb-1 opacity-50" />
                No outputs yet
              </Panel>
            )}
          </section>

          {/* Events */}
          <section>
            <h3 className="text-xs font-semibold text-comet-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <Activity className="w-3.5 h-3.5" />
              Events
              {nodeEvents.length > 0 && (
                <span className="ml-1 text-comet-500">({nodeEvents.length})</span>
              )}
            </h3>
            {nodeEvents.length > 0 ? (
              <div className="space-y-1.5">
                {nodeEvents.map((event) => (
                  <div
                    key={event.id}
                    className="flex items-center gap-3 p-2 rounded bg-space-800/50 border border-space-700/50 text-sm"
                  >
                    <span className="text-xs font-mono text-aurora-400 shrink-0 w-28 truncate">
                      {event.event_type}
                    </span>
                    <div className="flex-1 h-px bg-space-600/50" />
                    <span className="text-xs text-comet-500 shrink-0">
                      {formatTimestamp(event.timestamp)}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <Panel padding="md" className="text-center text-comet-500 text-xs">
                <Activity className="w-4 h-4 mx-auto mb-1 opacity-50" />
                No events for this node
              </Panel>
            )}
          </section>
        </div>
      </div>
    </>
  );
}
