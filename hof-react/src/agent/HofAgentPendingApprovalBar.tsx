"use client";

/**
 * Approve / Reject controls live on each pending tool row; the provider auto-calls
 * `agent_resume_mutations` once every pending id has a choice. This component is a no-op
 * so existing layouts that still render it need no change.
 */
export function HofAgentPendingApprovalBar(_props: { className?: string }) {
  return null;
}
