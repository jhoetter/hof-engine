"use client";

import type { ReactNode } from "react";

export type PlanCardSectionProps = {
  /**
   * Plan-discover row when {@link computePlanDiscoverUiState} has
   * `placement === "above_plan"` — same timer as plan preparation.
   */
  chrome: ReactNode | null;
  children: ReactNode;
};

/**
 * Colocates plan-discover status with the **Plan** card so “Preparing plan” / settlement cannot drift
 * from the plan surface in the layout tree.
 */
export function PlanCardSection({ chrome, children }: PlanCardSectionProps) {
  return (
    <div className="space-y-1 pl-1" data-hof-plan-card-section="">
      {chrome}
      {children}
    </div>
  );
}
