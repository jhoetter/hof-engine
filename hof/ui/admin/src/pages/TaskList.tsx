import { useEffect, useState } from "react";
import { api, type FlowDef, type FlowExecution } from "../api";

function statusBadge(status: string) {
  const cls =
    status === "completed" ? "badge-success" :
    status === "running" ? "badge-info" :
    status === "waiting_for_human" ? "badge-warning" :
    status === "failed" ? "badge-danger" :
    "badge-neutral";
  return <span className={`badge ${cls}`}>{status}</span>;
}

export function TaskList() {
  const [flows, setFlows] = useState<FlowDef[]>([]);
  const [executions, setExecutions] = useState<FlowExecution[]>([]);
  const [selectedFlow, setSelectedFlow] = useState<string>("");

  useEffect(() => {
    api.listFlows().then(setFlows).catch(console.error);
  }, []);

  useEffect(() => {
    if (selectedFlow) {
      api.listExecutions(selectedFlow).then(setExecutions).catch(console.error);
    }
  }, [selectedFlow]);

  return (
    <div>
      <div className="page-header">
        <h2>Executions</h2>
        <select
          value={selectedFlow}
          onChange={(e) => setSelectedFlow(e.target.value)}
          style={{
            padding: "8px 12px",
            background: "var(--bg-tertiary)",
            border: "1px solid var(--border)",
            borderRadius: 6,
            color: "var(--text-primary)",
            fontSize: 13,
          }}
        >
          <option value="">Select a flow...</option>
          {flows.map((f) => (
            <option key={f.name} value={f.name}>{f.name}</option>
          ))}
        </select>
      </div>

      <div className="card">
        {!selectedFlow ? (
          <p style={{ color: "var(--text-secondary)" }}>Select a flow to view executions.</p>
        ) : executions.length === 0 ? (
          <p style={{ color: "var(--text-secondary)" }}>No executions for this flow.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Status</th>
                <th>Nodes</th>
                <th>Started</th>
                <th>Duration</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody>
              {executions.map((ex) => (
                <tr key={ex.id}>
                  <td><code>{ex.id.slice(0, 8)}</code></td>
                  <td>{statusBadge(ex.status)}</td>
                  <td>
                    {ex.node_states.filter((n) => n.status === "completed").length}/
                    {ex.node_states.length}
                  </td>
                  <td>{ex.started_at ? new Date(ex.started_at).toLocaleString() : "-"}</td>
                  <td>{ex.duration_ms != null ? `${ex.duration_ms}ms` : "-"}</td>
                  <td style={{ color: "var(--danger)", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis" }}>
                    {ex.error || "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
