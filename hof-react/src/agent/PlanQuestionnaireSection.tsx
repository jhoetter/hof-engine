"use client";

import type { ReactNode } from "react";

export type PlanQuestionnaireSectionProps = {
  /**
   * Plan-discover row when {@link computePlanDiscoverUiState} has
   * `placement === "above_questionnaire"` — same timer as clarification generation.
   */
  chrome: ReactNode | null;
  children: ReactNode;
};

/**
 * Colocates plan-discover status with the **Questions** card so clarify-phase chrome cannot drift
 * from the questionnaire in the layout tree.
 */
export function PlanQuestionnaireSection({
  chrome,
  children,
}: PlanQuestionnaireSectionProps) {
  return (
    <div
      className="space-y-1 pl-1"
      data-hof-plan-questionnaire-section=""
    >
      {chrome}
      {children}
    </div>
  );
}
