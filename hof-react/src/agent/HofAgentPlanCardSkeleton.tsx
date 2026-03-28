"use client";

/**
 * Placeholder while `hof_builtin_present_plan` runs (plan text not yet streaming).
 * Matches the shell of {@link HofAgentPlanCard} so the card doesn't pop in from nothing.
 */
export function HofAgentPlanCardSkeleton() {
  return (
    <div
      className="rounded-lg border border-border bg-surface p-3 shadow-sm"
      data-hof-plan-card=""
      data-hof-plan-card-mode="pending"
      aria-busy="true"
      aria-label="Preparing plan"
    >
      <div className="mb-3 flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <span className="rounded bg-[var(--color-accent)]/10 px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-[var(--color-accent)]">
              Plan
            </span>
            <span className="h-3 w-16 animate-pulse rounded bg-hover" aria-hidden />
          </div>
          <div className="h-4 w-[60%] max-w-[14rem] animate-pulse rounded bg-hover" />
        </div>
      </div>
      <div className="space-y-2.5">
        <div className="flex items-start gap-2">
          <div className="mt-0.5 size-4 shrink-0 animate-pulse rounded-full bg-hover" />
          <div className="h-3 w-[80%] max-w-[20rem] animate-pulse rounded bg-hover" />
        </div>
        <div className="flex items-start gap-2">
          <div className="mt-0.5 size-4 shrink-0 animate-pulse rounded-full bg-hover" />
          <div className="h-3 w-[65%] max-w-[16rem] animate-pulse rounded bg-hover" />
        </div>
        <div className="flex items-start gap-2">
          <div className="mt-0.5 size-4 shrink-0 animate-pulse rounded-full bg-hover" />
          <div className="h-3 w-[72%] max-w-[18rem] animate-pulse rounded bg-hover" />
        </div>
      </div>
    </div>
  );
}
