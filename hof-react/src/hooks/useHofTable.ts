import { useState, useEffect, useCallback } from "react";

interface UseHofTableOptions {
  filter?: Record<string, unknown>;
  orderBy?: string;
  limit?: number;
  offset?: number;
}

interface UseHofTableResult<T = Record<string, unknown>> {
  data: T[];
  loading: boolean;
  error: Error | null;
  refetch: () => void;
  create: (record: Partial<T>) => Promise<T>;
  update: (id: string, fields: Partial<T>) => Promise<T>;
  remove: (id: string) => Promise<void>;
}

export function useHofTable<T = Record<string, unknown>>(
  tableName: string,
  options: UseHofTableOptions = {}
): UseHofTableResult<T> {
  const [data, setData] = useState<T[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const buildParams = useCallback(() => {
    const params = new URLSearchParams();
    if (options.filter) {
      const filterStr = Object.entries(options.filter)
        .map(([k, v]) => `${k}:${v}`)
        .join(",");
      params.set("filter", filterStr);
    }
    if (options.orderBy) params.set("order_by", options.orderBy);
    if (options.limit) params.set("limit", String(options.limit));
    if (options.offset) params.set("offset", String(options.offset));
    return params.toString();
  }, [options.filter, options.orderBy, options.limit, options.offset]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const token = localStorage.getItem("hof_token");
      const params = buildParams();
      const url = `/api/tables/${tableName}${params ? `?${params}` : ""}`;
      const res = await fetch(url, {
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      });
      if (!res.ok) throw new Error(`Failed to fetch ${tableName}`);
      const json = await res.json();
      setData(json);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setLoading(false);
    }
  }, [tableName, buildParams]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const create = useCallback(
    async (record: Partial<T>): Promise<T> => {
      const token = localStorage.getItem("hof_token");
      const res = await fetch(`/api/tables/${tableName}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(record),
      });
      if (!res.ok) throw new Error("Create failed");
      const created = await res.json();
      setData((prev) => [created, ...prev]);
      return created;
    },
    [tableName]
  );

  const update = useCallback(
    async (id: string, fields: Partial<T>): Promise<T> => {
      const token = localStorage.getItem("hof_token");
      const res = await fetch(`/api/tables/${tableName}/${id}`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(fields),
      });
      if (!res.ok) throw new Error("Update failed");
      const updated = await res.json();
      setData((prev) => prev.map((r: any) => (r.id === id ? updated : r)));
      return updated;
    },
    [tableName]
  );

  const remove = useCallback(
    async (id: string): Promise<void> => {
      const token = localStorage.getItem("hof_token");
      const res = await fetch(`/api/tables/${tableName}/${id}`, {
        method: "DELETE",
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      });
      if (!res.ok) throw new Error("Delete failed");
      setData((prev) => prev.filter((r: any) => r.id !== id));
    },
    [tableName]
  );

  return { data, loading, error, refetch: fetchData, create, update, remove };
}
