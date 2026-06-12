"use client";

import { useState } from "react";
import { Shell } from "@/components/shell/shell";
import { Panel } from "@/components/ui/panel";
import { Button } from "@/components/ui/button";
import { useAgents } from "@/hooks/useAgents";
import { AgentGrid } from "@/components/agents/agent-grid";
import { RegisterAgentForm } from "@/components/agents/register-agent-form";
import AlertCircle from "lucide-react/dist/esm/icons/alert-circle";
import RefreshCw from "lucide-react/dist/esm/icons/refresh-cw";
import Satellite from "lucide-react/dist/esm/icons/satellite";

/**
 * Agents page (spec §6.12).
 *
 * States per spec §6.14:
 *   - LOADING  : skeleton grid of 6 cards
 *   - EMPTY    : empty-state illustration + expanded register form
 *   - ERROR    : connectivity error banner (with retry) AND register form
 *   - SUCCESS  : agent grid with status
 *   - PARTIAL  : static agent list while heartbeats refetch (use isFetching
 *                for a derived loading flag)
 *
 * Accessibility:
 *   - Page title is Bodoni Moda (`font-display`).
 *   - All interactive elements get a 2px aurora-500 focus ring.
 *   - aria-live region announces "Agent registered" / "Registration failed".
 *   - prefers-reduced-motion: no pulse/spin on orbs or icons
 *     (handled in `StatusOrb` and the form's `motion-safe:` guards).
 */
export default function AgentsPage() {
  const {
    data,
    isLoading,
    isError,
    error,
    isFetching,
    refetch,
  } = useAgents();

  const [liveMessage, setLiveMessage] = useState<string>("");

  const agents = data ?? [];
  const hasAgents = agents.length > 0;

  // PARTIAL: we have data on screen but a background refetch (heartbeat)
  // is in flight. The grid still renders, but we show a small "refreshing"
  // hint so the operator understands the latency.
  const isPartial = !isLoading && hasAgents && isFetching;

  return (
    <Shell>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-end justify-between gap-4 flex-wrap">
          <div>
            <h1
              className="text-4xl font-display tracking-wide text-comet-100"
              style={{ fontFamily: "Bodoni Moda, Georgia, serif" }}
            >
              Agents
            </h1>
            <p className="text-sm text-comet-500 mt-1">
              Environment agents Celeste can reach — register, observe, and
              monitor connectivity.
            </p>
          </div>
          <div className="flex items-center gap-2 text-xs text-comet-500 font-mono">
            <Satellite
              className="w-4 h-4 text-aurora-400"
              aria-hidden="true"
            />
            <span data-testid="agent-count">
              {hasAgents
                ? `${agents.length} registered`
                : "0 registered"}
            </span>
          </div>
        </div>

        {/* Error banner — show alongside the register form so the operator
            can still recover by registering a new agent. */}
        {isError && !isLoading && (
          <Panel
            data-testid="agents-error-banner"
            role="alert"
            className="p-4 flex items-start gap-3 border-mars-500/30 bg-mars-500/10"
          >
            <AlertCircle
              className="w-5 h-5 text-mars-400 shrink-0 mt-0.5"
              aria-hidden="true"
            />
            <div className="flex-1 space-y-1">
              <p className="text-sm text-mars-400 font-medium">
                Could not reach the agents endpoint.
              </p>
              <p className="text-xs text-comet-400">
                {error instanceof Error
                  ? error.message.replace(/^API [45]\d\d:\s*/, "")
                  : "CMC lost contact with Celeste."}
              </p>
            </div>
            <Button
              variant="danger"
              size="sm"
              onClick={() => refetch()}
              aria-label="Retry loading agents"
            >
              <RefreshCw className="w-3.5 h-3.5" aria-hidden="true" />
              Retry
            </Button>
          </Panel>
        )}

        {/* Partially-loaded state: a small "refreshing" hint while a
            background refetch is in flight. */}
        {isPartial && (
          <div
            className="flex items-center gap-2 text-xs text-comet-500 font-mono"
            aria-live="polite"
          >
            <RefreshCw
              className="w-3 h-3 text-aurora-400 motion-safe:animate-spin"
              aria-hidden="true"
            />
            <span>Refreshing agent heartbeats…</span>
          </div>
        )}

        {/* Body */}
        {isLoading ? (
          <AgentGrid
            agents={[]}
            isLoading
            isEmpty={false}
          />
        ) : !hasAgents ? (
          <div className="space-y-6">
            <AgentGrid agents={[]} isEmpty />
            <RegisterAgentForm
              defaultExpanded
              onStatusChange={(status, message) => {
                if (status === "idle") setLiveMessage("");
                else if (message) setLiveMessage(message);
              }}
            />
          </div>
        ) : (
          <div className="space-y-6">
            <AgentGrid agents={agents} />
            <RegisterAgentForm
              onStatusChange={(status, message) => {
                if (status === "idle") setLiveMessage("");
                else if (message) setLiveMessage(message);
              }}
            />
          </div>
        )}

        {/* aria-live region for screen-reader announcements. Visually
            hidden but reachable to AT. */}
        <div
          role="status"
          aria-live="polite"
          aria-atomic="true"
          className="sr-only"
          data-testid="agents-aria-live"
        >
          {liveMessage}
        </div>
      </div>
    </Shell>
  );
}
