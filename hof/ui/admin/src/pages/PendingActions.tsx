import { useEffect, useState } from "react";
import { api, type PendingAction } from "../api";

export function PendingActions() {
  const [actions, setActions] = useState<PendingAction[]>([]);

  useEffect(() => {
    api.pendingActions().then(setActions).catch(console.error);
  }, []);

  return (
    <div>
      <div className="page-header">
        <h2>Pending Actions</h2>
      </div>

      {actions.length === 0 ? (
        <div className="card">
          <p style={{ color: "var(--text-secondary)" }}>
            No pending human-in-the-loop actions.
          </p>
        </div>
      ) : (
        <div>
          {actions.map((action) => (
            <div key={`${action.execution_id}-${action.node_name}`} className="card">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <h3 style={{ color: "var(--text-primary)", fontSize: 15 }}>
                    {action.flow_name} / {action.node_name}
                  </h3>
                  <p style={{ color: "var(--text-secondary)", fontSize: 12, marginTop: 4 }}>
                    Execution: <code>{action.execution_id.slice(0, 8)}</code>
                    {action.started_at && (
                      <> &middot; Waiting since {new Date(action.started_at).toLocaleString()}</>
                    )}
                  </p>
                </div>
                <span className="badge badge-warning">Waiting for input</span>
              </div>

              {action.ui_component && (
                <p style={{ marginTop: 12, fontSize: 13 }}>
                  UI Component: <code>{action.ui_component}</code>
                </p>
              )}

              <details style={{ marginTop: 12 }}>
                <summary style={{ cursor: "pointer", fontSize: 13, color: "var(--text-secondary)" }}>
                  Input Data
                </summary>
                <pre style={{
                  marginTop: 8,
                  padding: 12,
                  background: "var(--bg-primary)",
                  borderRadius: 6,
                  fontSize: 12,
                  overflow: "auto",
                  maxHeight: 300,
                }}>
                  {JSON.stringify(action.input_data, null, 2)}
                </pre>
              </details>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
