import { useHofTable } from "@hof-engine/react";

interface Lead {
  id: string;
  name: string;
  email: string | null;
  company: string | null;
  status: string;
}

export default function DashboardPage() {
  const { data: allLeads, loading } = useHofTable<Lead>("lead", { limit: 1000 });

  if (loading) return <p style={{ padding: 32 }}>Loading...</p>;

  const counts = {
    total: allLeads.length,
    new: allLeads.filter((l) => l.status === "new").length,
    enriching: allLeads.filter((l) => l.status === "enriching").length,
    enriched: allLeads.filter((l) => l.status === "enriched").length,
    reviewed: allLeads.filter((l) => l.status === "reviewed").length,
    rejected: allLeads.filter((l) => l.status === "rejected").length,
  };

  return (
    <div style={{ padding: 32, fontFamily: "system-ui, sans-serif", maxWidth: 900, margin: "0 auto" }}>
      <h1 style={{ fontSize: 24, marginBottom: 8 }}>Lead Enrichment Dashboard</h1>
      <p style={{ color: "#8b8fa3", marginBottom: 28 }}>
        Overview of your lead pipeline
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 16 }}>
        <StatCard label="Total Leads" value={counts.total} />
        <StatCard label="New" value={counts.new} color="#4f8cff" />
        <StatCard label="Enriching" value={counts.enriching} color="#a78bfa" />
        <StatCard label="Enriched" value={counts.enriched} color="#34d399" />
        <StatCard label="Reviewed" value={counts.reviewed} color="#2dd4bf" />
        <StatCard label="Rejected" value={counts.rejected} color="#f87171" />
      </div>

      <div
        style={{
          marginTop: 32,
          padding: 20,
          borderRadius: 8,
          border: "1px solid #2e3140",
          background: "#1a1d27",
        }}
      >
        <h3 style={{ fontSize: 14, color: "#8b8fa3", marginBottom: 12 }}>Quick Actions</h3>
        <p style={{ fontSize: 13, color: "#e4e6eb" }}>
          Use the CLI to import leads and trigger enrichment:
        </p>
        <pre
          style={{
            marginTop: 12,
            padding: 14,
            borderRadius: 6,
            background: "#0f1117",
            fontSize: 12,
            lineHeight: 1.7,
            overflow: "auto",
          }}
        >
{`# Import leads from JSON
hof fn import_leads --json '{"leads_json": "[{\\"name\\": \\"Alice\\", \\"company\\": \\"Acme\\"}]"}'

# Enrich all new leads
hof fn trigger_bulk_enrichment --json '{"filter_status": "new"}'

# Enrich a single lead
hof fn trigger_enrichment --json '{"lead_id": "<uuid>"}'`}
        </pre>
      </div>
    </div>
  );
}

function StatCard({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <div
      style={{
        padding: "16px 20px",
        borderRadius: 8,
        border: "1px solid #2e3140",
        background: "#1a1d27",
      }}
    >
      <div style={{ fontSize: 11, color: "#8b8fa3", textTransform: "uppercase", letterSpacing: "0.05em" }}>
        {label}
      </div>
      <div style={{ fontSize: 28, fontWeight: 700, marginTop: 4, color: color || "#e4e6eb" }}>
        {value}
      </div>
    </div>
  );
}
