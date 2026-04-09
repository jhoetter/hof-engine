"use client";

import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, ChevronDown, ChevronUp, Circle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { HOF_REACT_I18N_OPTS } from "../reactI18nextStableOpts";
import {
  parseStructuredPlan,
  visiblePlanMarkdownPreview,
} from "./planMarkdownTodos";

export type HofAgentPlanCardProps = {
  planText: string;
  onPlanTextChange: (next: string) => void;
  planPhase: "generating" | "ready" | "executing" | "done";
  busy: boolean;
  planTodoDoneIndices: readonly number[];
  onExecutePlan: () => void;
};

export function HofAgentPlanCard({
  planText,
  onPlanTextChange,
  planPhase,
  busy,
  planTodoDoneIndices,
  onExecutePlan,
}: HofAgentPlanCardProps) {
  const { t } = useTranslation("hofEngine", HOF_REACT_I18N_OPTS);
  const [viewRawOpen, setViewRawOpen] = useState(false);
  const planForStructure = useMemo(() => {
    if (planPhase === "generating") {
      return visiblePlanMarkdownPreview(planText);
    }
    return planText;
  }, [planPhase, planText]);
  const parsed = useMemo(
    () => parseStructuredPlan(planForStructure),
    [planForStructure],
  );
  const generating = planPhase === "generating";
  const executing = planPhase === "executing";
  const completed = planPhase === "done";

  useEffect(() => {
    if (executing) {
      setViewRawOpen(false);
    }
  }, [executing]);

  const doneCount = useMemo(() => {
    if (parsed.todos.length === 0) {
      return 0;
    }
    if (completed) {
      return parsed.todos.length;
    }
    return parsed.todos.filter((todo) => planTodoDoneIndices.includes(todo.index))
      .length;
  }, [parsed.todos, planTodoDoneIndices, completed]);

  return (
    <div className="rounded-lg border border-border bg-surface p-3 shadow-sm">
      <div className="mb-3 flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <span className="rounded bg-[var(--color-accent)]/10 px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-[var(--color-accent)]">
              {t("planCard.badge")}
            </span>
            {generating ? (
              <span className="text-[11px] text-tertiary">
                {t("planCard.drafting")}
              </span>
            ) : completed ? (
              <span className="text-[11px] text-tertiary">
                {t("planCard.completed")}
              </span>
            ) : executing ? (
              <span className="text-[11px] text-tertiary">
                {t("planCard.executingProgress", {
                  done: doneCount,
                  total: parsed.todos.length,
                  stepsLabel:
                    parsed.todos.length === 1
                      ? t("planCard.stepSingular")
                      : t("planCard.stepPlural"),
                })}
              </span>
            ) : null}
          </div>
          <h3 className="text-[15px] font-semibold leading-snug text-foreground">
            {parsed.title || t("planCard.fallbackTitle")}
          </h3>
        </div>
      </div>
      {!executing && !generating && parsed.description ? (
        <p className="mb-3 text-[13px] leading-relaxed text-secondary">
          {parsed.description}
        </p>
      ) : null}
      <div
        className={
          executing
            ? "mb-0 rounded-md border border-border bg-background px-2 py-2"
            : "mb-3 rounded-md border border-border bg-background px-2 py-2"
        }
      >
        <p className="mb-2 text-[11px] font-medium text-secondary">
          {generating
            ? t("planCard.buildingChecklist")
            : completed
              ? t("planCard.progress", {
                  done: doneCount,
                  total: parsed.todos.length,
                })
              : executing
                ? t("planCard.progress", {
                    done: doneCount,
                    total: parsed.todos.length,
                  })
                : parsed.todos.length === 1
                  ? t("planCard.todosOne")
                  : t("planCard.todos", { count: parsed.todos.length })}
        </p>
        {parsed.todos.length > 0 ? (
          <ul className="space-y-2">
            {parsed.todos.map((todo) => {
              const done =
                completed || planTodoDoneIndices.includes(todo.index);
              return (
                <li key={todo.index} className="flex items-start gap-2 text-[13px]">
                  {done ? (
                    <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-[var(--color-accent)]" />
                  ) : (
                    <Circle className="mt-0.5 size-4 shrink-0 text-tertiary" />
                  )}
                  <span
                    className={
                      done
                        ? "text-secondary line-through"
                        : "text-foreground"
                    }
                  >
                    {todo.label}
                  </span>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="text-[12px] text-tertiary">{t("planCard.noChecklist")}</p>
        )}
      </div>
      {!executing && !generating ? (
        <>
          <button
            type="button"
            onClick={() => setViewRawOpen((v) => !v)}
            className="mb-3 flex items-center gap-1 text-[12px] font-medium text-[var(--color-accent)] underline decoration-[var(--color-accent)]/40 underline-offset-2"
          >
            {viewRawOpen ? (
              <>
                <ChevronUp className="size-3.5" aria-hidden />
                {t("planCard.hidePlan")}
              </>
            ) : (
              <>
                <ChevronDown className="size-3.5" aria-hidden />
                {t("planCard.viewPlan")}
              </>
            )}
          </button>
          {viewRawOpen ? (
            <textarea
              value={planForStructure}
              onChange={(e) => onPlanTextChange(e.target.value)}
              disabled={busy || completed}
              className="mb-3 min-h-[160px] w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-[13px] text-foreground outline-none ring-0 focus:ring-2 focus:ring-[var(--color-accent)]/40 disabled:opacity-60"
              spellCheck={false}
            />
          ) : null}
        </>
      ) : null}
      {planPhase === "ready" ? (
        <div className="flex justify-end">
          <button
            type="button"
            onClick={onExecutePlan}
            disabled={busy}
            className="rounded-md bg-foreground px-4 py-2 text-[13px] font-medium text-background transition-colors hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {t("planCard.executePlan")}
          </button>
        </div>
      ) : null}
    </div>
  );
}
