"use client";

import { FileText } from "lucide-react";
import { RunBlocksList } from "./HofAgentChatBlocks";
import {
  CHAT_USER_BUBBLE_CLASS,
  PLAN_EXECUTE_USER_MARKER,
  userMessageDisplayText,
} from "./hofAgentChatModel";
import type { ReactNode } from "react";
import { useMemo } from "react";
import { useHofAgentChat } from "./hofAgentChatContext";
import type { ThreadItem } from "./hofAgentChatModel";
import { HofAgentPlanClarificationCard } from "./HofAgentPlanClarificationCard";
import { HofAgentPlanClarificationCardSkeleton } from "./HofAgentPlanClarificationCardSkeleton";
import { HofAgentPlanCard } from "./HofAgentPlanCard";
import { AgentEarlyThinkingIndicator } from "./HofAgentChatBlocks";
import { PlanSection } from "./PlanSection";
import { computePlanDiscoverUiState } from "./planDiscoverUiReducer";
import { visiblePlanMarkdownPreview } from "./planMarkdownTodos";
import {
  formatDurationMsForUi,
  useThinkingEpisodeElapsed,
} from "./thinkingDuration";

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

/** Where to insert plan / clarification chrome: anchored to the discovery run (or run before ``[plan:execute]``). */
function findPlanRunAnchorIndex(
  thread: readonly ThreadItem[],
  planRunId: string | null,
): number {
  if (planRunId != null) {
    const idx = thread.findIndex(
      (it) => it.kind === "run" && it.id === planRunId,
    );
    if (idx >= 0) {
      return idx;
    }
  }
  const executeMarkerIdx = thread.findIndex(
    (it) =>
      it.kind === "user" &&
      it.content.trim() === PLAN_EXECUTE_USER_MARKER,
  );
  if (executeMarkerIdx > 0) {
    for (let i = executeMarkerIdx - 1; i >= 0; i--) {
      const it = thread[i];
      if (it?.kind === "run") {
        return i;
      }
    }
  }
  return -1;
}

export function HofAgentMessages({
  className =
    "min-h-0 flex-1 overflow-y-auto overflow-x-hidden [scrollbar-gutter:stable] [overflow-anchor:none]",
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
    streamingReasoningLabel,
    agentMode,
    clarificationGenerationStartedAtMs,
    clarificationVisibleAtMs,
    planPreparationStartedAtMs,
    thinkingEpisodeStartedAtMs,
    planBuiltinLane,
    discoverStreamPhase,
  } = useHofAgentChat();

  const planDraftVisible =
    planPhase === "generating"
      ? visiblePlanMarkdownPreview(planText)
      : planText;
  const planCardPhase:
    | "generating"
    | "ready"
    | "executing"
    | "done"
    | null =
    planPhase === "ready" ||
    planPhase === "executing" ||
    planPhase === "done"
      ? planPhase
      : planPhase === "generating" && planDraftVisible.trim().length > 0
        ? "generating"
        : null;
  const showPlanCard =
    planCardPhase !== null &&
    (planPhase === "generating"
      ? planDraftVisible.trim().length > 0
      : planText.trim().length > 0);

  const hasClarificationActive =
    planPhase === "clarifying" && planClarificationBarrier != null;
  const hasClarificationReview =
    planClarificationSubmittedSummary.length > 0 &&
    !(planPhase === "clarifying" && planClarificationBarrier);
  const hasQuestionnaireCard =
    hasClarificationActive || hasClarificationReview;

  /**
   * Clarify subphase can arrive before ``tool_call``; require tool_call or some assistant output
   * so the skeleton does not mount at the very start of a turn.
   */
  const pendingQuestionnaireGeneration =
    planClarificationBarrier == null &&
    busy &&
    (planBuiltinLane === "clarification" || discoverStreamPhase === "clarify") &&
    (planBuiltinLane === "clarification" || liveBlocks.length > 0);

  const planDiscoverUi = computePlanDiscoverUiState({
    agentMode,
    busy,
    displayLabel: streamingReasoningLabel,
    hasQuestionnaireCard,
    showPlanCard,
    liveBlocksLength: liveBlocks.length,
    pendingQuestionnaireGeneration,
  });

  const questionnaireElapsed = useThinkingEpisodeElapsed(
    busy &&
      planDiscoverUi.placement === "above_questionnaire" &&
      planDiscoverUi.timerKind === "clarification_generation",
    clarificationGenerationStartedAtMs,
  );
  const planCardElapsed = useThinkingEpisodeElapsed(
    busy &&
      planDiscoverUi.placement === "above_plan" &&
      planDiscoverUi.timerKind === "plan_preparation",
    planPreparationStartedAtMs,
  );
  const liveStreamElapsed = useThinkingEpisodeElapsed(
    planDiscoverUi.placement === "above_live_stream" &&
      planDiscoverUi.timerKind === "thinking_episode",
    thinkingEpisodeStartedAtMs,
  );

  /**
   * Wall-clock time from clarification tool start to barrier applied — matches what users expect
   * for “Generated questions” more reliably than the episode hook alone (avoids “0 seconds”).
   */
  const questionnaireDurationFromWallClock =
    clarificationGenerationStartedAtMs != null &&
    clarificationVisibleAtMs != null &&
    clarificationVisibleAtMs >= clarificationGenerationStartedAtMs
      ? formatDurationMsForUi(
          clarificationVisibleAtMs - clarificationGenerationStartedAtMs,
        )
      : null;

  const planDiscoverChromeNode = useMemo(() => {
    if (planDiscoverUi.placement === "none") {
      return null;
    }
    let liveFormatted: string | null | undefined;
    let settledFormatted: string | null | undefined;
    const label = planDiscoverUi.label;
    if (planDiscoverUi.placement === "above_questionnaire") {
      liveFormatted = questionnaireElapsed.liveFormatted;
      settledFormatted =
        questionnaireDurationFromWallClock ??
        questionnaireElapsed.settledFormatted;
    } else if (planDiscoverUi.placement === "above_plan") {
      liveFormatted = planCardElapsed.liveFormatted;
      settledFormatted = planCardElapsed.settledFormatted;
    } else {
      liveFormatted = liveStreamElapsed.liveFormatted;
      settledFormatted = liveStreamElapsed.settledFormatted;
    }
    return (
      <AgentEarlyThinkingIndicator
        label={label ?? undefined}
        liveFormatted={liveFormatted}
        settledFormatted={settledFormatted}
      />
    );
  }, [
    planDiscoverUi,
    questionnaireElapsed.liveFormatted,
    questionnaireElapsed.settledFormatted,
    questionnaireDurationFromWallClock,
    planCardElapsed.liveFormatted,
    planCardElapsed.settledFormatted,
    liveStreamElapsed.liveFormatted,
    liveStreamElapsed.settledFormatted,
  ]);

  const liveStreamChromeEl =
    planDiscoverUi.placement === "above_live_stream"
      ? planDiscoverChromeNode
      : null;
  const questionnaireChromeEl =
    planDiscoverUi.placement === "above_questionnaire"
      ? planDiscoverChromeNode
      : null;
  const planChromeEl =
    planDiscoverUi.placement === "above_plan" ? planDiscoverChromeNode : null;

  /**
   * Single column for live NDJSON stream: plan-discover chrome (when
   * `placement === "above_live_stream"`) sits **directly above** {@link RunBlocksList} with
   * `space-y-1` so it does not float one `space-y-5` step below the run / user row.
   */
  const liveStreamColumnEl = useMemo(() => {
    if (liveStreamChromeEl == null && liveBlocks.length === 0) {
      return null;
    }
    return (
      <div className="space-y-1" data-hof-plan-live-stream-section="">
        <div className="space-y-1 pl-1">
          {liveStreamChromeEl}
          {liveBlocks.length > 0 ? (
            <RunBlocksList
              blocks={liveBlocks}
              barrier={approvalBarrier}
              approvalDecisions={approvalDecisions}
              setApprovalDecisions={setApprovalDecisions}
              busy={busy}
              mutationOutcomeByPendingId={mutationOutcomeByPendingId}
            />
          ) : null}
        </div>
      </div>
    );
  }, [
    liveStreamChromeEl,
    liveBlocks,
    approvalBarrier,
    approvalDecisions,
    setApprovalDecisions,
    busy,
    mutationOutcomeByPendingId,
  ]);

  const planRunAnchorIdx = findPlanRunAnchorIndex(thread, planRunId);
  const hasPlanRunAnchor = planRunAnchorIdx >= 0;

  /**
   * When the plan anchor is the resume-plan-clarification run, the **discover** run sits earlier
   * in the thread. The submitted-choices review card must be inserted between those two runs.
   * ``discoverRunIdx`` is the last ``run`` item **before** ``planRunAnchorIdx``; -1 if none.
   */
  const discoverRunIdx = hasPlanRunAnchor
    ? thread.slice(0, planRunAnchorIdx).reduce(
        (acc, item, idx) => (item.kind === "run" ? idx : acc),
        -1,
      )
    : -1;

  const renderThreadItems = (items: readonly ThreadItem[]) =>
    items.map((item) => {
      if (item.kind === "user") {
        const hasAtt = Boolean(item.attachments?.length);
        const displayBody = userMessageDisplayText(item.content, hasAtt);
        if (item.content.trim() === PLAN_EXECUTE_USER_MARKER) {
          return null;
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

  const planCardEl =
    showPlanCard && planCardPhase !== null ? (
      <PlanSection kind="plan" chrome={planChromeEl}>
        <HofAgentPlanCard
          planText={planText}
          onPlanTextChange={setPlanText}
          planPhase={planCardPhase}
          busy={busy}
          planTodoDoneIndices={planTodoDoneIndices}
          onExecutePlan={executePlan}
        />
      </PlanSection>
    ) : null;

  /** Interactive questionnaire only (barrier present). */
  const clarificationActiveEl =
    planPhase === "clarifying" && planClarificationBarrier ? (
      <PlanSection kind="questionnaire" chrome={questionnaireChromeEl}>
        <HofAgentPlanClarificationCard
          mode="active"
          key={planClarificationBarrier.clarificationId}
          questions={planClarificationBarrier.questions}
          busy={busy}
          onSubmit={submitPlanClarification}
        />
      </PlanSection>
    ) : null;

  /** Builtin running, barrier not yet on wire — chrome + skeleton in questionnaire slot. */
  const clarificationPendingEl =
    pendingQuestionnaireGeneration ? (
      <PlanSection kind="questionnaire" chrome={questionnaireChromeEl}>
        <HofAgentPlanClarificationCardSkeleton />
      </PlanSection>
    ) : null;

  /**
   * Submitted clarification answers are fixed in the timeline **immediately after** persisted
   * thread prefix and **before** the live NDJSON tail. That keeps order identical while streaming,
   * after flush, and on reload — never interleaved below newer assistant deltas.
   */
  const clarificationReviewEl = hasClarificationReview ? (
    <PlanSection kind="questionnaire" chrome={questionnaireChromeEl}>
      <HofAgentPlanClarificationCard
        mode="review"
        submittedSummary={planClarificationSubmittedSummary}
      />
    </PlanSection>
  ) : null;

  /** Plan chrome: pending skeleton, active questionnaire, plan card (submitted-choices review is rendered in ``threadList``). */
  const planOrClarificationChromeEl = hasPlanRunAnchor ? (
    <>
      {clarificationPendingEl}
      {clarificationActiveEl}
      {!(planPhase === "clarifying" && planClarificationBarrier)
        ? planCardEl
        : null}
    </>
  ) : null;

  /**
   * Stable visual order — identical during streaming, after flush, and on reload:
   *
   *   1. Discover run (explore / tools / first thought + reply)
   *   2. Submitted Questions review (when present)
   *   3. Plan-preparation run (second thought + reply)
   *   4. Plan / questionnaire chrome (plan card, active questionnaire, skeleton)
   *   5. Live stream (execution blocks, if any)
   *   6. Remaining thread items (flushed execution run)
   *
   * **Anchored** branch: review card splits at ``discoverRunIdx``; plan card is a
   * stable anchor **above** the execution live stream so it never drifts down.
   *
   * **Unanchored** branch (``planRunId`` null — active during discover/clarify
   * streaming): live stream sits above plan/questionnaire chrome because the plan
   * card and questionnaire only appear once those tools complete.
   */
  const threadList = (
    <>
      {hasPlanRunAnchor ? (
        <>
          {hasClarificationReview && discoverRunIdx >= 0 ? (
            <>
              {renderThreadItems(thread.slice(0, discoverRunIdx + 1))}
              {clarificationReviewEl}
              {renderThreadItems(
                thread.slice(discoverRunIdx + 1, planRunAnchorIdx + 1),
              )}
            </>
          ) : (
            <>
              {renderThreadItems(thread.slice(0, planRunAnchorIdx + 1))}
              {hasClarificationReview ? clarificationReviewEl : null}
            </>
          )}
          {planOrClarificationChromeEl}
          {liveStreamColumnEl}
          {renderThreadItems(thread.slice(planRunAnchorIdx + 1))}
        </>
      ) : (
        <>
          {renderThreadItems(thread)}
          {hasClarificationReview ? clarificationReviewEl : null}
          {/*
            Unanchored: ``planRunId`` is unset until ``final``, so this branch is active during
            discover / clarify / plan-prep streaming. Live stream sits above plan/questionnaire
            chrome because those cards only appear once tool calls resolve.
          */}
          {liveStreamColumnEl}
          {planCardEl}
          {clarificationPendingEl}
          {clarificationActiveEl}
        </>
      )}
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
