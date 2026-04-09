"use client";

import { useTranslation } from "react-i18next";
import { HOF_REACT_I18N_OPTS } from "../reactI18nextStableOpts";

/**
 * Placeholder while `hof_builtin_present_plan_clarification` runs (barrier not yet applied).
 * Matches the shell of {@link HofAgentPlanClarificationCard} review/active layout.
 */
export function HofAgentPlanClarificationCardSkeleton() {
  const { t } = useTranslation("hofEngine", HOF_REACT_I18N_OPTS);
  return (
    <div
      className="scroll-my-4 rounded-lg border border-border bg-surface p-3 shadow-sm [overflow-anchor:none] contain-layout"
      data-hof-plan-clarification-card=""
      data-hof-plan-clarification-mode="pending"
      aria-busy="true"
      aria-label={t("planDiscover.generatingQuestions")}
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <p className="text-[13px] font-semibold text-foreground">
          {t("clarification.questions")}
        </p>
        <span className="h-3 w-14 animate-pulse rounded bg-hover" aria-hidden />
      </div>
      <div className="space-y-3">
        <div className="space-y-2">
          <div className="h-3 max-w-[18rem] w-[85%] animate-pulse rounded bg-hover" />
          <div className="h-9 w-full animate-pulse rounded-md bg-hover" />
        </div>
        <div className="space-y-2">
          <div className="h-3 max-w-[14rem] w-[70%] animate-pulse rounded bg-hover" />
          <div className="h-9 w-full animate-pulse rounded-md bg-hover" />
        </div>
      </div>
    </div>
  );
}
