import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  listAgents,
  registerAgent,
  getGlobalEvents,
} from "@/lib/api";
import type {
  AgentListItem,
  RegisterAgentRequest,
  RegisterAgentResponse,
  GlobalEvent,
} from "@/lib/types";

/**
 * Lists all registered agents.
 *
 * Mirrors the pattern used by useWorkflows in useWorkflow.ts.
 */
export function useAgents() {
  return useQuery<AgentListItem[]>({
    queryKey: ["agents"],
    queryFn: () => listAgents(),
  });
}

/**
 * Registers a new agent. On success, invalidates the ["agents"] query so the
 * agents list refetches.
 */
export function useRegisterAgent() {
  const queryClient = useQueryClient();
  return useMutation<RegisterAgentResponse, Error, RegisterAgentRequest>({
    mutationFn: (body) => registerAgent(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agents"] });
    },
  });
}

/**
 * Live ticker of global events. Refetches every 3 seconds so the observatory
 * stream stays in sync with Celeste. This is intentionally always-on; the
 * spec treats 3s polling as the "live ticker" cadence even when no workflow
 * is currently running.
 */
export function useGlobalEvents(opts?: {
  limit?: number;
  offset?: number;
  event_type?: string;
}) {
  return useQuery<GlobalEvent[]>({
    queryKey: ["global-events", opts],
    queryFn: () => getGlobalEvents(opts),
    refetchInterval: 3000,
  });
}
