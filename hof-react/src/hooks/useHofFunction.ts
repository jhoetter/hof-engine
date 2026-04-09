import { useState, useCallback, useMemo } from "react";

interface UseHofFunctionResult<TResult = unknown> {
  call: (params: Record<string, unknown>) => Promise<TResult>;
  loading: boolean;
  error: Error | null;
  result: TResult | null;
}

export function useHofFunction<TResult = unknown>(
  functionName: string
): UseHofFunctionResult<TResult> {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [result, setResult] = useState<TResult | null>(null);

  const call = useCallback(
    async (params: Record<string, unknown>): Promise<TResult> => {
      setLoading(true);
      setError(null);
      try {
        const token = localStorage.getItem("hof_token");
        const res = await fetch(`/api/functions/${functionName}`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify(params),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: res.statusText }));
          throw new Error(err.detail || res.statusText);
        }
        const json = await res.json();
        const fnResult = json.result as TResult;
        setResult(fnResult);
        return fnResult;
      } catch (err) {
        const error = err instanceof Error ? err : new Error(String(err));
        setError(error);
        throw error;
      } finally {
        setLoading(false);
      }
    },
    [functionName]
  );

  return useMemo(
    (): UseHofFunctionResult<TResult> => ({ call, loading, error, result }),
    [call, loading, error, result],
  );
}
