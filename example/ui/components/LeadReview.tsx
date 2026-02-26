import { useState } from "react";

interface LeadReviewProps {
  lead_id: string;
  name: string;
  company: string;
  company_description: string;
  industry: string;
  company_size: string;
  linkedin_url: string | null;
  recent_news: string[];
  confidence_score: number;
  onComplete: (result: {
    approved: boolean;
    lead_id: string;
    company_description: string;
    industry: string;
    company_size: string;
    linkedin_url: string | null;
    recent_news: string[];
    confidence_score: number;
  }) => void;
}

export function LeadReview({
  lead_id,
  name,
  company,
  company_description,
  industry,
  company_size,
  linkedin_url,
  recent_news,
  confidence_score,
  onComplete,
}: LeadReviewProps) {
  const [fields, setFields] = useState({
    company_description,
    industry,
    company_size,
    linkedin_url: linkedin_url || "",
    recent_news,
    confidence_score,
  });

  const update = (key: string, value: unknown) =>
    setFields((prev) => ({ ...prev, [key]: value }));

  const handleApprove = () =>
    onComplete({
      approved: true,
      lead_id,
      ...fields,
      linkedin_url: fields.linkedin_url || null,
    });

  const handleReject = () =>
    onComplete({
      approved: false,
      lead_id,
      ...fields,
      linkedin_url: fields.linkedin_url || null,
    });

  const confidencePct = Math.round(fields.confidence_score * 100);
  const confidenceColor =
    confidencePct >= 75 ? "#34d399" : confidencePct >= 50 ? "#fbbf24" : "#f87171";

  return (
    <div style={{ maxWidth: 720, margin: "0 auto", fontFamily: "system-ui, sans-serif" }}>
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ margin: 0 }}>Review Enrichment</h2>
        <p style={{ color: "#8b8fa3", marginTop: 4 }}>
          Lead: <strong>{name}</strong>
          {company && <> at <strong>{company}</strong></>}
        </p>
        <p style={{ color: "#8b8fa3", fontSize: 12 }}>ID: {lead_id}</p>
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginBottom: 20,
          padding: "8px 14px",
          borderRadius: 6,
          background: "rgba(79,140,255,0.08)",
        }}
      >
        <span style={{ fontSize: 13 }}>LLM Confidence:</span>
        <span style={{ fontWeight: 700, color: confidenceColor }}>{confidencePct}%</span>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <Field
          label="Industry"
          value={fields.industry}
          onChange={(v) => update("industry", v)}
        />
        <Field
          label="Company Size"
          value={fields.company_size}
          onChange={(v) => update("company_size", v)}
        />
        <Field
          label="LinkedIn URL"
          value={fields.linkedin_url}
          onChange={(v) => update("linkedin_url", v)}
        />
        <div>
          <label style={{ display: "block", fontSize: 12, fontWeight: 600, marginBottom: 4, color: "#8b8fa3" }}>
            Company Description
          </label>
          <textarea
            value={fields.company_description}
            onChange={(e) => update("company_description", e.target.value)}
            rows={4}
            style={{
              width: "100%",
              padding: "8px 12px",
              borderRadius: 6,
              border: "1px solid #2e3140",
              background: "#1a1d27",
              color: "#e4e6eb",
              fontSize: 13,
              resize: "vertical",
            }}
          />
        </div>
        <div>
          <label style={{ display: "block", fontSize: 12, fontWeight: 600, marginBottom: 4, color: "#8b8fa3" }}>
            Recent News
          </label>
          {fields.recent_news.map((item, i) => (
            <div key={i} style={{ display: "flex", gap: 8, marginBottom: 6 }}>
              <input
                value={item}
                onChange={(e) => {
                  const updated = [...fields.recent_news];
                  updated[i] = e.target.value;
                  update("recent_news", updated);
                }}
                style={{
                  flex: 1,
                  padding: "6px 10px",
                  borderRadius: 6,
                  border: "1px solid #2e3140",
                  background: "#1a1d27",
                  color: "#e4e6eb",
                  fontSize: 13,
                }}
              />
              <button
                onClick={() => update("recent_news", fields.recent_news.filter((_, j) => j !== i))}
                style={{
                  padding: "6px 10px",
                  borderRadius: 6,
                  border: "1px solid #2e3140",
                  background: "transparent",
                  color: "#f87171",
                  cursor: "pointer",
                  fontSize: 12,
                }}
              >
                Remove
              </button>
            </div>
          ))}
          <button
            onClick={() => update("recent_news", [...fields.recent_news, ""])}
            style={{
              padding: "6px 12px",
              borderRadius: 6,
              border: "1px solid #2e3140",
              background: "#242731",
              color: "#8b8fa3",
              cursor: "pointer",
              fontSize: 12,
            }}
          >
            + Add news item
          </button>
        </div>
      </div>

      <div style={{ display: "flex", gap: 12, marginTop: 28 }}>
        <button
          onClick={handleApprove}
          style={{
            flex: 1,
            padding: "10px 20px",
            borderRadius: 6,
            border: "none",
            background: "#34d399",
            color: "#0f1117",
            fontWeight: 600,
            fontSize: 14,
            cursor: "pointer",
          }}
        >
          Approve & Store
        </button>
        <button
          onClick={handleReject}
          style={{
            flex: 1,
            padding: "10px 20px",
            borderRadius: 6,
            border: "1px solid #f87171",
            background: "transparent",
            color: "#f87171",
            fontWeight: 600,
            fontSize: 14,
            cursor: "pointer",
          }}
        >
          Reject
        </button>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <label style={{ display: "block", fontSize: 12, fontWeight: 600, marginBottom: 4, color: "#8b8fa3" }}>
        {label}
      </label>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{
          width: "100%",
          padding: "8px 12px",
          borderRadius: 6,
          border: "1px solid #2e3140",
          background: "#1a1d27",
          color: "#e4e6eb",
          fontSize: 13,
        }}
      />
    </div>
  );
}
