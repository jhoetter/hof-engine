import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type AdminOverview, type FlowExecution } from "../api";

function statusBadge(status: string) {
  const cls =
    status === "completed" ? "badge-success" :
    status === "running" ? "badge-info" :
    status === "waiting_for_human" ? "badge-warning" :
    status === "failed" ? "badge-danger" :
    "badge-neutral";
  return <span className={`badge ${cls}`}>{status}</span>;
}

export function Dashboard() {
  const [data, setData] = useState<AdminOverview | null>(null);

  useEffect(() => {
    api.overview().then(setData).catch(console.error);
  }, []);

  if (!data) return <p>Loading...</p>;

  return (
    <div>
      <div className="page-header">
        <h2>Dashboard</h2>
      </div>

      <div className="stat-grid">
        <div className="stat-card">
          <div className="label">Tables</div>
          <div className="value">{data.registry.tables}</div>
        </div>
        <div className="stat-card">
          <div className="label">Functions</div>
          <div className="value">{data.registry.functions}</div>
        </div>
        <div className="stat-card">
          <div className="label">Flows</div>
          <div className="value">{data.registry.flows}</div>
        </div>
        <div className="stat-card">
          <div className="label">Cron Jobs</div>
          <div className="value">{data.registry.cron_jobs}</div>
        </div>
      </div>

      <div className="card">
        <h3>Registered Flows</h3>
        {data.flows.length === 0 ? (
          <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>No flows registered.</p>
        ) : (
          <ul style={{ listStyle: "none" }}>
            {data.flows.map((name) => (
              <li key={name} style={{ padding: "6px 0" }}>
                <Link to={`/flows/${name}`}>{name}</Link>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="card">
        <h3>Recent Executions</h3>
        {data.recent_executions.length === 0 ? (
          <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>No executions yet.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Flow</th>
                <th>Status</th>
                <th>Started</th>
                <th>Duration</th>
              </tr>
            </thead>
            <tbody>
              {data.recent_executions.map((ex) => (
                <tr key={ex.id}>
                  <td><code>{ex.id.slice(0, 8)}</code></td>
                  <td><Link to={`/flows/${ex.flow_name}`}>{ex.flow_name}</Link></td>
                  <td>{statusBadge(ex.status)}</td>
                  <td>{ex.started_at ? new Date(ex.started_at).toLocaleString() : "-"}</td>
                  <td>{ex.duration_ms != null ? `${ex.duration_ms}ms` : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
