"use client";

import type { ReactNode } from "react";

export type PlanSectionProps = {
  /** `"questionnaire"` or `"plan"` — used for the data attribute only. */
  kind: "questionnaire" | "plan";
  /**
   * Status indicator row (e.g. "Generating questions (3 s)") placed above the card by
   * {@link computePlanDiscoverUiState}. Only one is visible at a time across all sections.
   */
  statusRow: ReactNode | null;
  children: ReactNode;
};

/**
 * Colocates a plan-discover status row with its card so the indicator cannot drift from
 * the questionnaire or plan card in the layout tree.
 */
export function PlanSection({ kind, statusRow, children }: PlanSectionProps) {
  return (
    <div className="space-y-1 pl-1" data-hof-plan-section={kind}>
      {statusRow}
      {children}
    </div>
  );
}
