"use client";

import {
  useCallback,
  useMemo,
  useState,
  type KeyboardEvent,
  type ReactElement,
} from "react";
import type { PlanClarificationQuestion } from "./conversationTypes";

function optionIdLooksOther(optionId: string): boolean {
  return optionId.toLowerCase().includes("other");
}

function letterLabel(index: number): string {
  if (index < 0 || index > 25) {
    return "?";
  }
  return String.fromCharCode(65 + index);
}

export type PlanClarificationAnswerWire = {
  question_id: string;
  selected_option_ids: string[];
  other_text?: string;
};

export type HofAgentPlanClarificationCardProps = {
  questions: PlanClarificationQuestion[];
  busy: boolean;
  onSubmit: (answers: PlanClarificationAnswerWire[]) => void;
  /** Optional: e.g. dismiss or submit empty — host decides. */
  onSkip?: () => void;
};

export function HofAgentPlanClarificationCard({
  questions,
  busy,
  onSubmit,
  onSkip,
}: HofAgentPlanClarificationCardProps): ReactElement | null {
  const initial = useMemo(() => {
    const m = new Map<string, Set<string>>();
    for (const q of questions) {
      m.set(q.id, new Set());
    }
    return m;
  }, [questions]);

  const [selected, setSelected] = useState(() => initial);
  const [otherTexts, setOtherTexts] = useState<Record<string, string>>({});
  const [page, setPage] = useState(0);

  const setOtherTextForQuestion = useCallback((qid: string, text: string) => {
    setOtherTexts((prev) => ({ ...prev, [qid]: text }));
  }, []);

  const toggleOption = useCallback(
    (qid: string, oid: string, allowMultiple: boolean) => {
      setSelected((prev) => {
        const next = new Map(prev);
        const cur = new Set(next.get(qid) ?? []);
        if (allowMultiple) {
          if (cur.has(oid)) {
            cur.delete(oid);
          } else {
            cur.add(oid);
          }
        } else {
          cur.clear();
          cur.add(oid);
        }
        next.set(qid, cur);
        return next;
      });
    },
    [],
  );

  const totalPages = Math.max(1, questions.length);
  const safePage = Math.min(page, Math.max(0, questions.length - 1));
  const q = questions[safePage];
  const showPager = questions.length > 1;

  const allAnswered = useMemo(() => {
    for (const qu of questions) {
      const s = selected.get(qu.id);
      if (!s || s.size < 1) {
        return false;
      }
      const hasOtherSelected = [...s].some((oid) => optionIdLooksOther(oid));
      if (hasOtherSelected) {
        const t = (otherTexts[qu.id] ?? "").trim();
        if (!t) {
          return false;
        }
      }
    }
    return questions.length > 0;
  }, [questions, selected, otherTexts]);

  const currentQuestionAnswered = useMemo(() => {
    if (!q) {
      return false;
    }
    const s = selected.get(q.id);
    if (!s || s.size < 1) {
      return false;
    }
    const hasOtherSelected = [...s].some((oid) => optionIdLooksOther(oid));
    if (hasOtherSelected) {
      const t = (otherTexts[q.id] ?? "").trim();
      if (!t) {
        return false;
      }
    }
    return true;
  }, [q, selected, otherTexts]);

  const handleSubmit = () => {
    if (!allAnswered || busy) {
      return;
    }
    const answers: PlanClarificationAnswerWire[] = questions.map((qu) => {
      const sel = Array.from(selected.get(qu.id) ?? []);
      const hasOtherSelected = sel.some((oid) => optionIdLooksOther(oid));
      const ot = (otherTexts[qu.id] ?? "").trim();
      const base: PlanClarificationAnswerWire = {
        question_id: qu.id,
        selected_option_ids: sel,
      };
      if (hasOtherSelected && ot) {
        base.other_text = ot;
      }
      return base;
    });
    onSubmit(answers);
  };

  const onContinue = () => {
    if (busy) {
      return;
    }
    if (safePage < questions.length - 1) {
      if (!currentQuestionAnswered) {
        return;
      }
      setPage((p) => Math.min(questions.length - 1, p + 1));
      return;
    }
    handleSubmit();
  };

  const continueDisabled =
    busy ||
    (safePage < questions.length - 1
      ? !currentQuestionAnswered
      : !allAnswered);

  const continueLabel =
    safePage >= questions.length - 1 ? "Finish" : "Continue";

  const onFieldsetKeyDown = (e: KeyboardEvent<HTMLFieldSetElement>) => {
    if (e.key !== "Enter" || e.shiftKey || e.ctrlKey || e.metaKey) {
      return;
    }
    const t = e.target as HTMLElement;
    if (t.tagName === "TEXTAREA") {
      return;
    }
    e.preventDefault();
    if (!continueDisabled) {
      onContinue();
    }
  };

  if (!q) {
    return null;
  }

  const allow = Boolean(q.allow_multiple);
  const qSelected = selected.get(q.id) ?? new Set();
  const hasOtherSelected = [...qSelected].some((oid) =>
    optionIdLooksOther(oid),
  );
  const questionHasOtherOption = q.options.some((o) =>
    optionIdLooksOther(o.id),
  );

  return (
    <div className="rounded-lg border border-border bg-surface p-3 shadow-sm">
      <div className="mb-3 flex items-center justify-between gap-2">
        <p className="text-[13px] font-semibold text-foreground">Questions</p>
        {showPager ? (
          <span className="text-[11px] text-tertiary">
            {safePage + 1} of {totalPages}
          </span>
        ) : (
          <span className="text-[11px] text-tertiary">1 of 1</span>
        )}
      </div>
      <fieldset
        className="space-y-3 border-0 p-0"
        onKeyDown={onFieldsetKeyDown}
      >
        <legend className="mb-2 text-sm font-medium text-foreground">
          {questions.length > 1 ? `${safePage + 1}. ` : ""}
          {q.prompt}
        </legend>
        <div className="flex flex-col gap-2">
          {q.options.map((o, optIdx) => {
            const on = qSelected.has(o.id);
            const id = `clarify-${q.id}-${o.id}`;
            const letter = letterLabel(optIdx);
            return (
              <label
                key={o.id}
                htmlFor={id}
                className="flex cursor-pointer items-start gap-3 rounded-md border border-transparent px-2 py-2 hover:border-border hover:bg-hover"
              >
                <input
                  id={id}
                  className="sr-only"
                  type={allow ? "checkbox" : "radio"}
                  name={allow ? undefined : `clarify-${q.id}`}
                  checked={on}
                  disabled={busy}
                  onChange={() => toggleOption(q.id, o.id, allow)}
                />
                <span
                  className={`flex size-7 shrink-0 items-center justify-center rounded border text-[12px] font-semibold ${
                    on
                      ? "border-[var(--color-accent)] bg-[var(--color-accent)]/15 text-[var(--color-accent)]"
                      : "border-border bg-background text-secondary"
                  }`}
                  aria-hidden
                >
                  {letter}
                </span>
                <span className="pt-0.5 text-[13px] leading-snug text-foreground">
                  {o.label}
                </span>
              </label>
            );
          })}
        </div>
        {questionHasOtherOption && hasOtherSelected ? (
          <div className="mt-1 pl-10">
            <label
              htmlFor={`clarify-${q.id}-other-text`}
              className="mb-1 block text-[11px] font-medium text-secondary"
            >
              Please specify
            </label>
            <input
              id={`clarify-${q.id}-other-text`}
              type="text"
              value={otherTexts[q.id] ?? ""}
              disabled={busy}
              onChange={(e) =>
                setOtherTextForQuestion(q.id, e.target.value)
              }
              placeholder="Your answer…"
              className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-[13px] text-foreground outline-none ring-0 focus:ring-2 focus:ring-[var(--color-accent)]/40 disabled:opacity-60"
            />
          </div>
        ) : null}
      </fieldset>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3">
        {showPager ? (
          <button
            type="button"
            disabled={busy || safePage <= 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            className="rounded-md border border-border px-3 py-1.5 text-[12px] text-secondary disabled:opacity-40"
          >
            Back
          </button>
        ) : onSkip ? (
          <span />
        ) : (
          <span />
        )}
        <div className="ml-auto flex items-center gap-2">
          {onSkip ? (
            <button
              type="button"
              onClick={onSkip}
              disabled={busy}
              className="rounded-md px-2 py-1.5 text-[13px] text-secondary hover:text-foreground disabled:opacity-40"
            >
              Skip
            </button>
          ) : null}
          <button
            type="button"
            onClick={onContinue}
            disabled={continueDisabled}
            className="rounded-md bg-foreground px-4 py-1.5 text-[13px] font-medium text-background transition-colors hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {continueLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
