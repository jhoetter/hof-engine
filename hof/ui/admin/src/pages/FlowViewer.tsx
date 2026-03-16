import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, type FlowDag, type FlowExecution } from "../api";
import { FlowGraph } from "../components/FlowGraph";

function statusBadge(status: string) {
  const cls =
    status === "completed" ? "badge-success" :
    status === "running" ? "badge-info" :
    status === "waiting_for_human" ? "badge-warning" :
    status === "failed" ? "badge-danger" :
    "badge-neutral";
  return <span className={`badge ${cls}`}>{status}</span>;
}

export function FlowViewer() {
  const { name } = useParams<{ name: string }>();
  const [dag, setDag] = useState<FlowDag | null>(null);
  const [executions, setExecutions] = useState<FlowExecution[]>([]);
  const [selectedExecution, setSelectedExecution] = useState<FlowExecution | null>(null);

  const refreshExecutions = () => {
    if (name) api.listExecutions(name).then(setExecutions).catch(console.error);
  };

  useEffect(() => {
    if (!name) return;
    api.flowDag(name).then(setDag).catch(console.error);
    refreshExecutions();
    const interval = setInterval(refreshExecutions, 3000);
    return () => clearInterval(interval);
  }, [name]);

  if (!dag) return <p>Loading...</p>;

  const nodeStates: Record<string, string> = {};
  if (selectedExecution) {
    for (const ns of selectedExecution.node_states) {
      nodeStates[ns.node_name] = ns.status;
    }
  }

  return (
    <div>
      <div className="page-header">
        <h2>Flow: {name}</h2>
        <button
          className="btn btn-primary"
          onClick={() => {
            if (name) {
              api.runFlow(name, {}).then((ex) => {
                setExecutions((prev) => [ex, ...prev]);
                setSelectedExecution(ex);
              });
            }
          }}
        >
          Run Flow
        </button>
      </div>

      <FlowGraph
        nodes={dag.nodes}
        edges={dag.edges}
        executionOrder={dag.execution_order}
        nodeStates={nodeStates}
      />

      <div className="card" style={{ marginTop: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h3>Executions</h3>
          <button className="btn" onClick={refreshExecutions}>Refresh</button>
        </div>
        {executions.length === 0 ? (
          <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>No executions yet.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Status</th>
                <th>Started</th>
                <th>Duration</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {executions.map((ex) => (
                <tr
                  key={ex.id}
                  style={{
                    background: selectedExecution?.id === ex.id ? "var(--bg-tertiary)" : undefined,
                    cursor: "pointer",
                  }}
                  onClick={() => setSelectedExecution(ex)}
                >
                  <td><code>{ex.id.slice(0, 8)}</code></td>
                  <td>{statusBadge(ex.status)}</td>
                  <td>{ex.started_at ? new Date(ex.started_at).toLocaleString() : "-"}</td>
                  <td>{ex.duration_ms != null ? `${ex.duration_ms}ms` : "-"}</td>
                  <td>
                    <button className="btn" onClick={() => setSelectedExecution(ex)}>
                      View
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {selectedExecution && (
        <div className="card">
          <h3>Node Details - Execution {selectedExecution.id.slice(0, 8)}</h3>
          <table>
            <thead>
              <tr>
                <th>Node</th>
                <th>Status</th>
                <th>Duration</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody>
              {selectedExecution.node_states.map((ns) => (
                <tr key={ns.node_name}>
                  <td>{ns.node_name}</td>
                  <td>{statusBadge(ns.status)}</td>
                  <td>{ns.duration_ms != null ? `${ns.duration_ms}ms` : "-"}</td>
                  <td style={{ color: "var(--danger)" }}>{ns.error || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
