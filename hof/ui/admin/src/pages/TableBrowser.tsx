import { useEffect, useState } from "react";
import { api, type TableDef } from "../api";

export function TableBrowser() {
  const [tables, setTables] = useState<TableDef[]>([]);
  const [selectedTable, setSelectedTable] = useState<string | null>(null);
  const [records, setRecords] = useState<Record<string, unknown>[]>([]);

  useEffect(() => {
    api.listTables().then(setTables).catch(console.error);
  }, []);

  useEffect(() => {
    if (selectedTable) {
      api.listRecords(selectedTable).then(setRecords).catch(console.error);
    }
  }, [selectedTable]);

  return (
    <div>
      <div className="page-header">
        <h2>Tables</h2>
      </div>

      <div style={{ display: "flex", gap: 16 }}>
        <div style={{ width: 240 }}>
          <div className="card">
            <h3>Registered Tables</h3>
            {tables.length === 0 ? (
              <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>No tables registered.</p>
            ) : (
              <ul style={{ listStyle: "none" }}>
                {tables.map((t) => (
                  <li key={t.name}>
                    <button
                      onClick={() => setSelectedTable(t.name)}
                      style={{
                        display: "block",
                        width: "100%",
                        padding: "8px 12px",
                        textAlign: "left",
                        background: selectedTable === t.name ? "var(--bg-tertiary)" : "transparent",
                        border: "none",
                        color: "var(--text-primary)",
                        cursor: "pointer",
                        borderRadius: 4,
                        fontSize: 13,
                      }}
                    >
                      {t.name}
                      <span style={{ color: "var(--text-secondary)", marginLeft: 8, fontSize: 11 }}>
                        {t.columns.length} cols
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        <div style={{ flex: 1 }}>
          {selectedTable ? (
            <div className="card">
              <h3>{selectedTable}</h3>
              {records.length === 0 ? (
                <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>No records.</p>
              ) : (
                <div style={{ overflowX: "auto" }}>
                  <table>
                    <thead>
                      <tr>
                        {Object.keys(records[0]).map((col) => (
                          <th key={col}>{col}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {records.map((record, i) => (
                        <tr key={i}>
                          {Object.values(record).map((val, j) => (
                            <td key={j} style={{ maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis" }}>
                              {typeof val === "object" ? JSON.stringify(val) : String(val ?? "-")}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          ) : (
            <div className="card">
              <p style={{ color: "var(--text-secondary)" }}>Select a table to browse records.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
