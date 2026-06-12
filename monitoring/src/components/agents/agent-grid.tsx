"use client";

import { AgentCard } from "./agent-card";
import { AgentSkeleton } from "./agent-skeleton";
import { EmptyAgentsIllustration } from "./empty-agents-illustration";
import { EmptyState } from "@/components/ui/empty-state";
import { Panel } from "@/components/ui/panel";
import type { AgentListItem } from "@/lib/types";

export interface AgentGridProps {
  agents: AgentListItem[];
  /**
   * When true, render the empty-state panel and illustration instead of
   * the grid. The caller is expected to provide the register form below
   * (the empty state is a feature, not a dead end).
   */
  isEmpty?: boolean;
  /**
   * When true, render a 6-card skeleton grid. The caller decides when to
   * use it (initial load vs. partial-heartbeat refetch).
   */
  isLoading?: boolean;
  /**
   * Number of skeleton placeholders to render when `isLoading` is true.
   * Defaults to 6 per spec §6.14.
   */
  skeletonCount?: number;
}

/**
 * Renders the agent grid in its various states (loading, empty, populated).
 * The caller is responsible for the "ERROR" banner and for the PARTIAL
 * orchestration (showing the grid while a derived heartbeat refetch is
 * in flight).
 */
export function AgentGrid({
  agents,
  isEmpty = false,
  isLoading = false,
  skeletonCount = 6,
}: AgentGridProps) {
  if (isLoading) {
    return (
      <div
        className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4"
        data-testid="agent-grid-skeleton"
        role="status"
        aria-label="Loading agents"
      >
        {Array.from({ length: skeletonCount }).map((_, i) => (
          <AgentSkeleton key={i} />
        ))}
      </div>
    );
  }

  if (isEmpty) {
    return (
      <div
        data-testid="agents-empty-state"
      >
        <Panel>
          <EmptyState
            icon={<EmptyAgentsIllustration />}
            title="No agents registered"
            description="Agents are environment services Celeste can reach. Register one below to begin wiring an agent into the fleet."
          />
        </Panel>
      </div>
    );
  }

  return (
    <div
      data-testid="agent-grid"
      className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4"
    >
      {agents.map((agent) => (
        <AgentCard key={agent.agent_id} agent={agent} />
      ))}
    </div>
  );
}
