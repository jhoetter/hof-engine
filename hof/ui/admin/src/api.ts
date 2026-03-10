const BASE_URL = "/api";

let _authHeader: string | null = sessionStorage.getItem("hof_auth");

export function setAuth(username: string, password: string) {
  _authHeader = "Basic " + btoa(`${username}:${password}`);
  sessionStorage.setItem("hof_auth", _authHeader);
}

export function clearAuth() {
  _authHeader = null;
  sessionStorage.removeItem("hof_auth");
}

export function isAuthenticated(): boolean {
  return _authHeader !== null;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (_authHeader) {
    headers["Authorization"] = _authHeader;
  }
  const res = await fetch(`${BASE_URL}${path}`, {
    headers,
    ...options,
  });
  if (res.status === 401) {
    clearAuth();
    window.location.reload();
    throw new Error("Unauthorized");
  }
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || res.statusText);
  }
  return res.json();
}

export const api = {
  // Auth check
  checkAuth: () => request<{ status: string }>("/health"),

  // Admin
  overview: () => request<AdminOverview>("/admin/overview"),
  flowDag: (name: string) => request<FlowDag>(`/admin/flows/${name}/dag`),
  pendingActions: () => request<PendingAction[]>("/admin/pending-actions"),

  // Tables
  listTables: () => request<TableDef[]>("/tables"),
  listRecords: (table: string, params?: string) =>
    request<Record<string, unknown>[]>(`/tables/${table}${params ? `?${params}` : ""}`),

  // Functions
  listFunctions: () => request<FunctionDef[]>("/functions"),
  callFunction: (name: string, body: Record<string, unknown>) =>
    request<{ result: unknown; duration_ms: number }>(`/functions/${name}`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // Flows
  listFlows: () => request<FlowDef[]>("/flows"),
  runFlow: (name: string, input: Record<string, unknown>) =>
    request<FlowExecution>(`/flows/${name}/run`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  listExecutions: (name: string) =>
    request<FlowExecution[]>(`/flows/${name}/executions`),
  getExecution: (id: string) => request<FlowExecution>(`/flows/executions/${id}`),
  submitHumanInput: (executionId: string, nodeName: string, data: Record<string, unknown>) =>
    request<FlowExecution>(`/flows/executions/${executionId}/nodes/${nodeName}/submit`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
};

// Types
export interface AdminOverview {
  registry: { tables: number; functions: number; flows: number; cron_jobs: number };
  tables: string[];
  functions: string[];
  flows: string[];
  cron_jobs: string[];
  recent_executions: FlowExecution[];
}

export interface FlowDag {
  name: string;
  nodes: DagNode[];
  edges: DagEdge[];
  execution_order: string[][];
}

export interface DagNode {
  id: string;
  label: string;
  description: string;
  is_human: boolean;
  human_ui: string | null;
  tags: string[];
}

export interface DagEdge {
  source: string;
  target: string;
}

export interface PendingAction {
  execution_id: string;
  flow_name: string;
  node_name: string;
  ui_component: string | null;
  input_data: Record<string, unknown>;
  started_at: string | null;
}

export interface TableDef {
  name: string;
  columns: { name: string; type: string }[];
}

export interface FunctionDef {
  name: string;
  description: string;
  tags: string[];
  is_async: boolean;
  parameters: { name: string; type: string; required: boolean }[];
}

export interface FlowDef {
  name: string;
  nodes: Record<string, unknown>;
  execution_order: string[][];
}

export interface FlowExecution {
  id: string;
  flow_name: string;
  status: string;
  input_data: Record<string, unknown>;
  output_data: Record<string, unknown>;
  node_states: NodeState[];
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  error: string | null;
}

export interface NodeState {
  node_name: string;
  status: string;
  input_data: Record<string, unknown>;
  output_data: Record<string, unknown>;
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
}
