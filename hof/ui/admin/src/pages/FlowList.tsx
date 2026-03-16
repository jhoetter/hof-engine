import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type FlowDef } from "../api";

export function FlowList() {
  const [flows, setFlows] = useState<FlowDef[]>([]);

  useEffect(() => {
    api.listFlows().then(setFlows).catch(console.error);
  }, []);

  return (
    <div>
      <div className="page-header">
        <h2>Flows</h2>
      </div>

      {flows.length === 0 ? (
        <div className="card">
          <p style={{ color: "var(--text-secondary)" }}>No flows registered.</p>
        </div>
      ) : (
        <div className="card">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Nodes</th>
                <th>DAG Waves</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {flows.map((flow) => (
                <tr key={flow.name}>
                  <td>
                    <Link to={`/flows/${flow.name}`}>{flow.name}</Link>
                  </td>
                  <td>{Object.keys(flow.nodes).length}</td>
                  <td>{flow.execution_order.length}</td>
                  <td>
                    <Link to={`/flows/${flow.name}`} className="btn">
                      View DAG
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
