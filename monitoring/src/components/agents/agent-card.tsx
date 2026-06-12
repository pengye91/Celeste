import { Panel } from "@/components/ui/panel";
import { StatusOrb } from "@/components/ui/status-orb";
import { cn } from "@/lib/utils";
import Activity from "lucide-react/dist/esm/icons/activity";
import CircleCheck from "lucide-react/dist/esm/icons/circle-check";
import CircleX from "lucide-react/dist/esm/icons/circle-x";
import HelpCircle from "lucide-react/dist/esm/icons/help-circle";
import Radio from "lucide-react/dist/esm/icons/radio";
import type { ReactNode } from "react";
import type { AgentListItem } from "@/lib/types";
import { formatRelativeTime } from "@/lib/format";

type Variant = "success" | "warning" | "error" | "idle";

interface StatusPresentation {
  variant: Variant;
  label: string;
  icon: ReactNode;
}

/**
 * Map a free-text agent.status (anything Celeste reports) to a UI variant.
 * Defaults to `idle` / "Unknown" so the UI is never color-only and never
 * shows an unrecognized verb without a fallback.
 */
export function resolveStatus(status: string): StatusPresentation {
  const normalized = status.toLowerCase();
  if (
    normalized === "connected" ||
    normalized === "online" ||
    normalized === "active" ||
    normalized === "ready" ||
    normalized === "running"
  ) {
    return {
      variant: "success",
      label: "Connected",
      icon: <CircleCheck className="w-3.5 h-3.5" aria-hidden="true" />,
    };
  }
  if (
    normalized === "disconnected" ||
    normalized === "offline" ||
    normalized === "unreachable" ||
    normalized === "failed"
  ) {
    return {
      variant: "error",
      label: "Disconnected",
      icon: <CircleX className="w-3.5 h-3.5" aria-hidden="true" />,
    };
  }
  if (
    normalized === "pending" ||
    normalized === "registering" ||
    normalized === "connecting" ||
    normalized === "warning"
  ) {
    return {
      variant: "warning",
      label: "Connecting",
      icon: <Activity className="w-3.5 h-3.5" aria-hidden="true" />,
    };
  }
  return {
    variant: "idle",
    label: "Unknown",
    icon: <HelpCircle className="w-3.5 h-3.5" aria-hidden="true" />,
  };
}

export interface AgentCardProps {
  agent: AgentListItem;
}

/**
 * Single agent card. Asymmetric composition per DESIGN.md §6.6:
 * status orb + label on the top line, URL on its own line,
 * last-seen timestamp, and a wrap of metadata tags. No colored
 * left-border — status is orb + icon + text, never color-only.
 */
export function AgentCard({ agent }: AgentCardProps) {
  const status = resolveStatus(agent.status);
  const metadataEntries = Object.entries(agent.metadata ?? {}).filter(
    ([, v]) => v !== null && v !== undefined && v !== "",
  );

  return (
    <Panel
      data-testid="agent-card"
      data-agent-id={agent.agent_id}
      className="p-4 space-y-3 transition-all duration-200 hover:border-aurora-500/30 focus-within:ring-2 focus-within:ring-aurora-500/50"
    >
      {/* Status row */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <StatusOrb
            variant={status.variant}
            size="md"
            pulse={status.variant === "success"}
          />
          <span
            className={cn(
              "inline-flex items-center gap-1 text-sm font-medium",
              status.variant === "success" && "text-nebula-400",
              status.variant === "warning" && "text-solar-400",
              status.variant === "error" && "text-mars-400",
              status.variant === "idle" && "text-comet-400",
            )}
          >
            {status.icon}
            {status.label}
          </span>
        </div>
        <span className="text-[10px] font-mono text-comet-600 truncate">
          {agent.agent_id}
        </span>
      </div>

      {/* URL */}
      <div className="flex items-center gap-2 min-w-0">
        <Radio className="w-3.5 h-3.5 text-aurora-400 shrink-0" aria-hidden="true" />
        <span
          className="font-mono text-sm text-comet-200 truncate"
          title={agent.url}
        >
          {agent.url}
        </span>
      </div>

      {/* Last seen */}
      <div className="text-[11px] text-comet-500 font-mono">
        Last seen {formatRelativeTime(agent.registered_at)}
      </div>

      {/* Metadata tags */}
      {metadataEntries.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pt-1">
          {metadataEntries.map(([key, value]) => (
            <span
              key={key}
              className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-mono rounded-sm border bg-space-800 text-comet-400 border-space-600"
            >
              <span className="text-comet-500">{key}:</span>
              <span className="text-comet-200">
                {typeof value === "string" ? value : JSON.stringify(value)}
              </span>
            </span>
          ))}
        </div>
      )}
    </Panel>
  );
}
