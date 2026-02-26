import { useState } from "react";
import { useHofTable, useHofFunction } from "@hof-engine/react";

interface Lead {
  id: string;
  name: string;
  email: string | null;
  company: string | null;
  title: string | null;
  source: string | null;
  status: string;
  created_at: string;
}

const STATUS_COLORS: Record<string, string> = {
  new: "#4f8cff",
  enriching: "#a78bfa",
  enriched: "#34d399",
  reviewed: "#2dd4bf",
  rejected: "#f87171",
};

export default function LeadsPage() {
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [search, setSearch] = useState("");

  const { data: leads, loading, refetch } = useHofTable<Lead>("lead", {
    filter: statusFilter ? { status: statusFilter } : undefined,
    orderBy: "-created_at",
    limit: 100,
  });

  const { call: triggerEnrichment, loading: enriching } = useHofFunction("trigger_enrichment");
  const { call: triggerBulk, loading: bulkEnriching } = useHofFunction("trigger_bulk_enrichment");

  const filtered = search
    ? leads.filter(
        (l) =>
          l.name.toLowerCase().includes(search.toLowerCase()) ||
          (l.company || "").toLowerCase().includes(search.toLowerCase()) ||
          (l.email || "").toLowerCase().includes(search.toLowerCase())
      )
    : leads;

  const handleEnrich = async (leadId: string) => {
    await triggerEnrichment({ lead_id: leadId });
    refetch();
  };

  const handleBulkEnrich = async () => {
    await triggerBulk({ filter_status: "new" });
    refetch();
  };

  return (
    <div style={{ padding: 32, fontFamily: "system-ui, sans-serif", maxWidth: 1100, margin: "0 auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
        <h1 style={{ fontSize: 24, margin: 0 }}>Leads</h1>
        <button
          onClick={handleBulkEnrich}
          disabled={bulkEnriching}
          style={{
            padding: "8px 16px",
            borderRadius: 6,
            border: "none",
            background: "#4f8cff",
            color: "white",
            fontWeight: 600,
            fontSize: 13,
            cursor: bulkEnriching ? "wait" : "pointer",
            opacity: bulkEnriching ? 0.6 : 1,
          }}
        >
          {bulkEnriching ? "Enriching..." : "Enrich All New"}
        </button>
      </div>

      <div style={{ display: "flex", gap: 12, marginBottom: 20 }}>
        <input
          placeholder="Search by name, company, or email..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{
            flex: 1,
            padding: "8px 14px",
            borderRadius: 6,
            border: "1px solid #2e3140",
            background: "#1a1d27",
            color: "#e4e6eb",
            fontSize: 13,
          }}
        />
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          style={{
            padding: "8px 14px",
            borderRadius: 6,
            border: "1px solid #2e3140",
            background: "#1a1d27",
            color: "#e4e6eb",
            fontSize: 13,
          }}
        >
          <option value="">All statuses</option>
          <option value="new">New</option>
          <option value="enriching">Enriching</option>
          <option value="enriched">Enriched</option>
          <option value="reviewed">Reviewed</option>
          <option value="rejected">Rejected</option>
        </select>
      </div>

      {loading ? (
        <p>Loading...</p>
      ) : filtered.length === 0 ? (
        <div
          style={{
            padding: 40,
            textAlign: "center",
            color: "#8b8fa3",
            border: "1px solid #2e3140",
            borderRadius: 8,
            background: "#1a1d27",
          }}
        >
          No leads found. Import some using the CLI.
        </div>
      ) : (
        <div style={{ border: "1px solid #2e3140", borderRadius: 8, overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "#1a1d27" }}>
                <th style={thStyle}>Name</th>
                <th style={thStyle}>Company</th>
                <th style={thStyle}>Email</th>
                <th style={thStyle}>Title</th>
                <th style={thStyle}>Status</th>
                <th style={thStyle}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((lead) => (
                <tr key={lead.id} style={{ borderBottom: "1px solid #2e3140" }}>
                  <td style={tdStyle}>{lead.name}</td>
                  <td style={tdStyle}>{lead.company || "—"}</td>
                  <td style={tdStyle}>{lead.email || "—"}</td>
                  <td style={tdStyle}>{lead.title || "—"}</td>
                  <td style={tdStyle}>
                    <span
                      style={{
                        padding: "2px 8px",
                        borderRadius: 4,
                        fontSize: 11,
                        fontWeight: 600,
                        color: STATUS_COLORS[lead.status] || "#8b8fa3",
                        background: `${STATUS_COLORS[lead.status] || "#8b8fa3"}20`,
                      }}
                    >
                      {lead.status}
                    </span>
                  </td>
                  <td style={tdStyle}>
                    {lead.status === "new" && (
                      <button
                        onClick={() => handleEnrich(lead.id)}
                        disabled={enriching}
                        style={{
                          padding: "4px 10px",
                          borderRadius: 4,
                          border: "1px solid #2e3140",
                          background: "#242731",
                          color: "#e4e6eb",
                          fontSize: 12,
                          cursor: "pointer",
                        }}
                      >
                        Enrich
                      </button>
                    )}
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

const thStyle: React.CSSProperties = {
  textAlign: "left",
  padding: "10px 14px",
  fontSize: 11,
  fontWeight: 600,
  textTransform: "uppercase",
  letterSpacing: "0.05em",
  color: "#8b8fa3",
};

const tdStyle: React.CSSProperties = {
  padding: "10px 14px",
  fontSize: 13,
};
