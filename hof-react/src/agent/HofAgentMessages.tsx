"use client";

import { FileText } from "lucide-react";
import {
  AgentEarlyThinkingIndicator,
  RunBlocksList,
} from "./HofAgentChatBlocks";
import {
  CHAT_USER_BUBBLE_CLASS,
  PLAN_EXECUTE_USER_MARKER,
  userMessageDisplayText,
} from "./hofAgentChatModel";
import type { ReactNode } from "react";
import { useHofAgentChat } from "./hofAgentChatContext";
import type { ThreadItem } from "./hofAgentChatModel";
import { HofAgentPlanClarificationCard } from "./HofAgentPlanClarificationCard";
import { HofAgentPlanCard } from "./HofAgentPlanCard";

export type HofAgentMessagesProps = {
  /** Outer scroll container (flex child, overflow). */
  className?: string;
  /** Inner content column (padding, max-width). */
  contentClassName?: string;
  /**
   * Shown under the welcome line when the thread is empty (e.g. {@link HofAgentComposer})
   * so the input sits with the greeting instead of a distant footer.
   */
  emptyStateFooter?: ReactNode;
};

function HofAgentAnswerSummaryCard({
  rows,
}: {
  rows: readonly { prompt: string; selectedLabels: string[] }[];
}) {
  return (
    <div className="pl-1">
      <div className="rounded-lg border border-border bg-surface p-3 shadow-sm">
        <p className="mb-2 text-[11px] font-medium text-secondary">Answer</p>
        <ul className="space-y-3">
          {rows.map((row, i) => (
            <li key={i}>
              <p className="text-[12px] text-secondary">{row.prompt}</p>
              <p className="text-[13px] font-medium leading-snug text-foreground">
                {row.selectedLabels.length > 0
                  ? row.selectedLabels.join(", ")
                  : "—"}
              </p>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export function HofAgentMessages({
  className = "min-h-0 flex-1 overflow-y-auto overflow-x-hidden [scrollbar-gutter:stable]",
  contentClassName = "mx-auto flex min-h-full w-full flex-col px-5 py-6 sm:px-6 sm:py-8",
  emptyStateFooter,
}: HofAgentMessagesProps) {
  const {
    welcomeName,
    thread,
    liveBlocks,
    busy,
    approvalBarrier,
    approvalDecisions,
    setApprovalDecisions,
    mutationOutcomeByPendingId,
    conversationEmpty,
    planPhase,
    planText,
    setPlanText,
    planClarificationBarrier,
    planClarificationSubmittedSummary,
    submitPlanClarification,
    planTodoDoneIndices,
    executePlan,
    planRunId,
  } = useHofAgentChat();

  const planCardPhase =
    planPhase === "ready" ||
    planPhase === "executing" ||
    planPhase === "done"
      ? planPhase
      : null;
  const showPlanCard =
    planCardPhase !== null && planText.trim().length > 0;
  const showAnswerSummary = planClarificationSubmittedSummary.length > 0;

  const liveBlocksEl =
    liveBlocks.length > 0 ? (
      <div className="pl-1">
        <RunBlocksList
          blocks={liveBlocks}
          barrier={approvalBarrier}
          approvalDecisions={approvalDecisions}
          setApprovalDecisions={setApprovalDecisions}
          busy={busy}
          mutationOutcomeByPendingId={mutationOutcomeByPendingId}
        />
      </div>
    ) : null;

  const planRunAnchorIdx =
    planRunId != null
      ? thread.findIndex(
          (it) => it.kind === "run" && it.id === planRunId,
        )
      : -1;
  const hasPlanRunAnchor = planRunAnchorIdx >= 0;

  const renderThreadItems = (items: readonly ThreadItem[]) =>
    items.map((item) => {
      if (item.kind === "user") {
        const hasAtt = Boolean(item.attachments?.length);
        const displayBody = userMessageDisplayText(item.content, hasAtt);
        if (item.content.trim() === PLAN_EXECUTE_USER_MARKER) {
          return (
            <div key={item.id} className="flex justify-center py-1">
              <span className="rounded-full border border-border bg-surface px-3 py-1 text-[11px] font-medium text-secondary">
                Plan execution started
              </span>
            </div>
          );
        }
        return (
          <div key={item.id} className="flex justify-end">
            <div className="max-w-[min(100%,min(28rem,90%))] space-y-2">
              {displayBody ? (
                <div className={CHAT_USER_BUBBLE_CLASS}>
                  <span className="whitespace-pre-wrap break-words">
                    {displayBody}
                  </span>
                </div>
              ) : null}
              {item.attachments && item.attachments.length > 0 ? (
                <div className="flex flex-col items-end gap-1.5">
                  {item.attachments.map((a) => (
                    <div
                      key={a.object_key}
                      className="inline-flex max-w-full items-center gap-2 rounded-xl border border-border bg-surface px-3 py-2 text-left"
                      title={a.object_key}
                    >
                      <FileText
                        className="size-4 shrink-0 text-[var(--color-accent)] opacity-90"
                        aria-hidden
                      />
                      <span className="min-w-0 truncate text-[13px] font-medium text-foreground">
                        {a.filename}
                      </span>
                      <span className="shrink-0 text-[10px] uppercase tracking-wide text-tertiary">
                        PDF
                      </span>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        );
      }
      return (
        <div key={item.id} className="pl-1">
          <RunBlocksList
            blocks={item.blocks}
            barrier={approvalBarrier}
            approvalDecisions={approvalDecisions}
            setApprovalDecisions={setApprovalDecisions}
            busy={busy}
            mutationOutcomeByPendingId={mutationOutcomeByPendingId}
          />
        </div>
      );
    });

  const answerSummaryEl = showAnswerSummary ? (
    <HofAgentAnswerSummaryCard rows={planClarificationSubmittedSummary} />
  ) : null;

  const planCardEl =
    showPlanCard && planCardPhase !== null ? (
      <div className="pl-1">
        <HofAgentPlanCard
          planText={planText}
          onPlanTextChange={setPlanText}
          planPhase={planCardPhase}
          busy={busy}
          planTodoDoneIndices={planTodoDoneIndices}
          onExecutePlan={executePlan}
        />
      </div>
    ) : null;

  const clarificationCardEl =
    planPhase === "clarifying" && planClarificationBarrier ? (
      <div className="pl-1">
        <HofAgentPlanClarificationCard
          questions={planClarificationBarrier.questions}
          busy={busy}
          onSubmit={submitPlanClarification}
        />
      </div>
    ) : null;

  const inlineChromeEl = hasPlanRunAnchor ? (
    <>
      {showAnswerSummary ? answerSummaryEl : null}
      {planPhase === "clarifying" && planClarificationBarrier
        ? clarificationCardEl
        : planCardEl}
    </>
  ) : null;

  const threadList = (
    <>
      {hasPlanRunAnchor ? (
        <>
          {renderThreadItems(thread.slice(0, planRunAnchorIdx))}
          {inlineChromeEl}
          {renderThreadItems(thread.slice(planRunAnchorIdx))}
        </>
      ) : (
        <>
          {renderThreadItems(thread)}
          {answerSummaryEl}
        </>
      )}
      {planPhase === "clarifying" && planClarificationBarrier && !hasPlanRunAnchor ? (
        <>
          {liveBlocksEl}
          <div className="pl-1">
            <HofAgentPlanClarificationCard
              questions={planClarificationBarrier.questions}
              busy={busy}
              onSubmit={submitPlanClarification}
            />
          </div>
        </>
      ) : (
        <>
          {!hasPlanRunAnchor ? planCardEl : null}
          {liveBlocksEl}
        </>
      )}
      {liveBlocks.length === 0 && busy ? (
        <div className="pl-1">
          <AgentEarlyThinkingIndicator />
        </div>
      ) : null}
    </>
  );

  const rootClass = conversationEmpty
    ? `${className} flex min-h-0 min-w-0 flex-1 flex-col`.trim()
    : className;

  return (
    <div className={rootClass}>
      {conversationEmpty ? (
        <div
          className={`${contentClassName} flex min-h-0 flex-1 flex-col justify-center !py-0`.trim()}
        >
          <div className="flex w-full flex-col items-center gap-4 font-sans">
            <p className="text-center text-xl font-semibold tracking-tight text-foreground sm:text-2xl">
              Welcome, {welcomeName}
            </p>
            {emptyStateFooter ? (
              <div className="w-full shrink-0">{emptyStateFooter}</div>
            ) : null}
          </div>
        </div>
      ) : (
        <div className={contentClassName}>
          <div className="min-h-0 flex-1 space-y-5">{threadList}</div>
        </div>
      )}
    </div>
  );
}
