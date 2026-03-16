import { useState, useEffect, useCallback } from "react";

interface FlowExecution {
  id: string;
  flow_name: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  node_states: Array<{
    node_name: string;
    status: string;
    duration_ms: number | null;
  }>;
}

interface UseHofFlowResult {
  run: (input: Record<string, unknown>) => Promise<FlowExecution>;
  executions: FlowExecution[];
  loading: boolean;
  error: Error | null;
  refetch: () => void;
}

export function useHofFlow(flowName: string): UseHofFlowResult {
  const [executions, setExecutions] = useState<FlowExecution[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchExecutions = useCallback(async () => {
    setLoading(true);
    try {
      const token = localStorage.getItem("hof_token");
      const res = await fetch(`/api/flows/${flowName}/executions`, {
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      });
      if (!res.ok) throw new Error("Failed to fetch executions");
      const json = await res.json();
      setExecutions(json);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setLoading(false);
    }
  }, [flowName]);

  useEffect(() => {
    fetchExecutions();
  }, [fetchExecutions]);

  const run = useCallback(
    async (input: Record<string, unknown>): Promise<FlowExecution> => {
      const token = localStorage.getItem("hof_token");
      const res = await fetch(`/api/flows/${flowName}/run`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(input),
      });
      if (!res.ok) throw new Error("Failed to run flow");
      const execution = await res.json();
      setExecutions((prev) => [execution, ...prev]);
      return execution;
    },
    [flowName]
  );

  return { run, executions, loading, error, refetch: fetchExecutions };
}
