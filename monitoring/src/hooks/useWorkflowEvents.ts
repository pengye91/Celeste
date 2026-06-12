import { useQuery } from "@tanstack/react-query";
import { getWorkflowEvents, getWorkflowWorkflowEvents } from "@/lib/api";

export function useWorkflowEvents(
  id: string,
  opts?: { event_type?: string; since_id?: string; limit?: number }
) {
  return useQuery({
    queryKey: ["workflow-events", id, opts],
    queryFn: () => getWorkflowEvents(id, opts),
    enabled: !!id,
  });
}

export function useWorkflowWorkflowEvents(
  id: string,
  opts?: { event_type?: string; since_id?: string; limit?: number }
) {
  return useQuery({
    queryKey: ["workflow-workflow-events", id, opts],
    queryFn: () => getWorkflowWorkflowEvents(id, opts),
    enabled: !!id,
  });
}
