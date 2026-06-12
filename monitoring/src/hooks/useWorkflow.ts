import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  listWorkflows,
  getWorkflow,
  getWorkflowStatus,
  getWorkflowEvents,
  getWorkflowWorkflowEvents,
  getWorkflowMetrics,
  getWorkflowNodes,
  cancelWorkflow,
  resumeWorkflow,
} from "@/lib/api";
import type { WorkflowStatus } from "@/lib/types";

const RUNNING_STATUSES: WorkflowStatus[] = ["pending", "running"];

export function useWorkflows(opts?: {
  limit?: number;
  offset?: number;
  status?: string;
  created_after?: string;
}) {
  return useQuery({
    queryKey: ["workflows", opts],
    queryFn: () => listWorkflows(opts),
  });
}

export function useWorkflow(id: string) {
  return useQuery({
    queryKey: ["workflow", id],
    queryFn: () => getWorkflow(id),
    enabled: !!id,
  });
}

export function useWorkflowStatus(id: string) {
  return useQuery({
    queryKey: ["workflow-status", id],
    queryFn: () => getWorkflowStatus(id),
    enabled: !!id,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && RUNNING_STATUSES.includes(status) ? 1500 : false;
    },
  });
}

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

export function useWorkflowMetrics(id: string) {
  return useQuery({
    queryKey: ["workflow-metrics", id],
    queryFn: () => getWorkflowMetrics(id),
    enabled: !!id,
  });
}

export function useWorkflowNodes(id: string) {
  return useQuery({
    queryKey: ["workflow-nodes", id],
    queryFn: () => getWorkflowNodes(id),
    enabled: !!id,
  });
}

export function useCancelWorkflow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: cancelWorkflow,
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: ["workflow", id] });
      queryClient.invalidateQueries({ queryKey: ["workflow-status", id] });
      queryClient.invalidateQueries({ queryKey: ["workflows"] });
    },
  });
}

export function useResumeWorkflow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, humanInput }: { id: string; humanInput?: string }) =>
      resumeWorkflow(id, humanInput),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: ["workflow", id] });
      queryClient.invalidateQueries({ queryKey: ["workflow-status", id] });
      queryClient.invalidateQueries({ queryKey: ["workflows"] });
    },
  });
}
