"use client";

import type { ReactNode } from "react";

export type PlanSectionProps = {
  /** `"questionnaire"` or `"plan"` — used for the data attribute only. */
  kind: "questionnaire" | "plan";
  /**
   * Plan-discover chrome row when {@link computePlanDiscoverUiState} places the status
   * indicator above this section (same timer as clarification generation or plan preparation).
   */
  chrome: ReactNode | null;
  children: ReactNode;
};

/**
 * Colocates plan-discover status chrome with its card so the status row cannot drift from
 * the questionnaire or plan card in the layout tree.
 */
export function PlanSection({ kind, chrome, children }: PlanSectionProps) {
  return (
    <div className="space-y-1 pl-1" data-hof-plan-section={kind}>
      {chrome}
      {children}
    </div>
  );
}
