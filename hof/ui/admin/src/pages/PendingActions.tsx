import { useCallback, useEffect, useState } from "react";
import { api, type PendingAction } from "../api";
import { UserComponent } from "../components/UserComponent";

export function PendingActions() {
  const [actions, setActions] = useState<PendingAction[]>([]);
  const [submitting, setSubmitting] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState<Set<string>>(new Set());

  const refreshActions = useCallback(() => {
    api.pendingActions().then(setActions).catch(console.error);
  }, []);

  useEffect(() => {
    refreshActions();
    const interval = setInterval(refreshActions, 5000);
    return () => clearInterval(interval);
  }, [refreshActions]);

  const handleComplete = async (action: PendingAction, data: Record<string, unknown>) => {
    const key = `${action.execution_id}-${action.node_name}`;
    setSubmitting(key);
    try {
      await api.submitHumanInput(action.execution_id, action.node_name, data);
      setSubmitted((prev) => new Set(prev).add(key));
      setActions((prev) => prev.filter((a) => `${a.execution_id}-${a.node_name}` !== key));
    } catch (err) {
      console.error("Submit failed:", err);
      alert(`Submit failed: ${err instanceof Error ? err.message : err}`);
    } finally {
      setSubmitting(null);
    }
  };

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
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {actions.map((action) => {
            const key = `${action.execution_id}-${action.node_name}`;
            const isSubmitting = submitting === key;

            return (
              <div key={key} className="card">
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
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
                  <span className="badge badge-warning">
                    {isSubmitting ? "Submitting..." : "Waiting for input"}
                  </span>
                </div>

                {action.ui_component ? (
                  <UserComponent
                    componentName={action.ui_component}
                    props={action.input_data}
                    onComplete={(data) => handleComplete(action, data)}
                  />
                ) : (
                  <div>
                    <p style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 8 }}>
                      No UI component specified for this node. Submit raw JSON:
                    </p>
                    <JsonSubmitForm
                      inputData={action.input_data}
                      onSubmit={(data) => handleComplete(action, data)}
                      disabled={isSubmitting}
                    />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function JsonSubmitForm({
  inputData,
  onSubmit,
  disabled,
}: {
  inputData: Record<string, unknown>;
  onSubmit: (data: Record<string, unknown>) => void;
  disabled: boolean;
}) {
  const [json, setJson] = useState("{}");

  return (
    <div>
      <details style={{ marginBottom: 12 }}>
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
          {JSON.stringify(inputData, null, 2)}
        </pre>
      </details>
      <textarea
        value={json}
        onChange={(e) => setJson(e.target.value)}
        rows={4}
        style={{
          width: "100%",
          padding: "8px 12px",
          borderRadius: 6,
          border: "1px solid var(--border)",
          background: "var(--bg-primary)",
          color: "var(--text-primary)",
          fontSize: 13,
          fontFamily: "monospace",
          resize: "vertical",
          marginBottom: 8,
        }}
      />
      <button
        onClick={() => {
          try {
            onSubmit(JSON.parse(json));
          } catch {
            alert("Invalid JSON");
          }
        }}
        disabled={disabled}
        className="btn btn-primary"
      >
        Submit
      </button>
    </div>
  );
}
