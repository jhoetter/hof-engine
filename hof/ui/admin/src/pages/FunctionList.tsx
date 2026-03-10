import { useEffect, useState } from "react";
import { api, type FunctionDef } from "../api";

export function FunctionList() {
  const [functions, setFunctions] = useState<FunctionDef[]>([]);

  useEffect(() => {
    api.listFunctions().then(setFunctions).catch(console.error);
  }, []);

  return (
    <div>
      <div className="page-header">
        <h2>Functions</h2>
      </div>

      {functions.length === 0 ? (
        <div className="card">
          <p style={{ color: "var(--text-secondary)" }}>No functions registered.</p>
        </div>
      ) : (
        <div className="card">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Description</th>
                <th>Parameters</th>
                <th>Tags</th>
                <th>Async</th>
              </tr>
            </thead>
            <tbody>
              {functions.map((fn) => (
                <tr key={fn.name}>
                  <td><code>{fn.name}</code></td>
                  <td style={{ maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis" }}>
                    {fn.description || "-"}
                  </td>
                  <td>
                    {fn.parameters.map((p) => (
                      <span key={p.name} className="badge badge-neutral" style={{ marginRight: 4 }}>
                        {p.name}: {p.type}
                      </span>
                    ))}
                  </td>
                  <td>
                    {fn.tags.map((t) => (
                      <span key={t} className="badge badge-info" style={{ marginRight: 4 }}>{t}</span>
                    ))}
                  </td>
                  <td>{fn.is_async ? "yes" : "no"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
