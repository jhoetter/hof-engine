import { useState, useCallback } from "react";

interface HofNodeContext {
  input: Record<string, unknown>;
  onComplete: (result: Record<string, unknown>) => Promise<void>;
  execution: {
    id: string;
    flow_name: string;
    node_name: string;
  };
  submitting: boolean;
  submitted: boolean;
  error: Error | null;
}

/**
 * Hook for human-in-the-loop components.
 *
 * Provides the node's input data and a submission handler. The component
 * receives these from the framework when rendered inside a human node.
 *
 * Usage:
 *   const { input, onComplete, submitting } = useHofNode();
 */
export function useHofNode(): HofNodeContext {
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  // In production, these are injected by the framework's rendering context.
  // For now, read from the global window context or URL params.
  const params = new URLSearchParams(window.location.search);
  const executionId = params.get("execution_id") || "";
  const flowName = params.get("flow_name") || "";
  const nodeName = params.get("node_name") || "";

  const inputData = (window as any).__HOF_NODE_INPUT__ || {};

  const onComplete = useCallback(
    async (result: Record<string, unknown>) => {
      setSubmitting(true);
      setError(null);
      try {
        const token = localStorage.getItem("hof_token");
        const res = await fetch(
          `/api/flows/executions/${executionId}/nodes/${nodeName}/submit`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
            body: JSON.stringify(result),
          }
        );
        if (!res.ok) throw new Error("Submission failed");
        setSubmitted(true);
      } catch (err) {
        setError(err instanceof Error ? err : new Error(String(err)));
        throw err;
      } finally {
        setSubmitting(false);
      }
    },
    [executionId, nodeName]
  );

  return {
    input: inputData,
    onComplete,
    execution: { id: executionId, flow_name: flowName, node_name: nodeName },
    submitting,
    submitted,
    error,
  };
}
