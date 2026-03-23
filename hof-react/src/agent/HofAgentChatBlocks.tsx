"use client";

import { ChevronRight, Terminal } from "lucide-react";
import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import { AssistantMarkdown } from "./AssistantMarkdown";
import { FunctionResultDisplay } from "./FunctionResultDisplay";
import {
  CHAT_ASSISTANT_REPLY_BUBBLE_CLASS,
  TOOL_SECTION_LABEL_CLASS,
  assistantUiRole,
  barrierMatchesApprovalBlock,
  confirmationFooterFromOutcomes,
  dropRedundantModelPhaseBeforeAssistant,
  humanizeToolName,
  inferAssistantUiLane,
  isGenericAwaitingConfirmationSummary,
  postToolAssistantBlockIds,
  segmentLiveBlocks,
  showProposedActionsLabel,
  toolCallArgsSnippet,
  toolCallCliLine,
  toolGroupSummaryLine,
} from "./hofAgentChatModel";
import type {
  ApprovalBarrier,
  AssistantStreamSegment,
  BlockSegment,
  LiveBlock,
  MutationPendingBlock,
  ToolCallBlock,
  ToolResultBlock,
} from "./hofAgentChatModel";

export function ToolGroupCard({
  call,
  mutation,
  result,
  showApproval,
  approvalItemsForMutation,
  approvalDecisions,
  setApprovalDecisions,
  busy,
  showBusyFooter,
  anchorId,
  mutationOutcome,
}: {
  call: ToolCallBlock;
  mutation?: MutationPendingBlock;
  result?: ToolResultBlock;
  showApproval: boolean;
  approvalItemsForMutation: { pendingId: string; name: string; cli_line: string }[];
  approvalDecisions: Record<string, boolean | null>;
  setApprovalDecisions: Dispatch<
    SetStateAction<Record<string, boolean | null>>
  >;
  busy: boolean;
  showBusyFooter: boolean;
  anchorId?: string;
  /** `true` approved, `false` rejected, `undefined` unknown / still pending */
  mutationOutcome?: boolean;
}) {
  const title = humanizeToolName(call.name);
  const line = toolCallCliLine(call);
  const argsBlock = toolCallArgsSnippet(call);
  const summaryHint: string | null =
    mutation && mutationOutcome !== undefined
      ? `${title} · ${mutationOutcome ? "Approved" : "Rejected"}`
      : toolGroupSummaryLine(call, mutation, result);
  const cmd = mutation
    ? mutation.cli_line || mutation.arguments_preview || ""
    : "";
  const cmdDupOfLine =
    Boolean(cmd.trim()) && cmd.trim() === line.trim();
  const hideGenericResult =
    Boolean(mutation && result && isGenericAwaitingConfirmationSummary(result.summary));
  const argsNorm = argsBlock?.replace(/\s+/g, "") ?? "";
  const argsRedundantWithLine =
    Boolean(argsBlock && line) &&
    argsNorm.length > 0 &&
    line.replace(/\s+/g, "").includes(argsNorm.slice(0, 48));

  const [detailsOpen, setDetailsOpen] = useState(false);
  useEffect(() => {
    if (showApproval) {
      setDetailsOpen(true);
    }
  }, [showApproval]);

  return (
    <div id={anchorId} className="scroll-mt-4">
      <details
        open={detailsOpen}
        onToggle={(e) => setDetailsOpen(e.currentTarget.open)}
        className="group rounded-lg border border-border bg-surface/40 [&_summary::-webkit-details-marker]:hidden"
      >
        <summary className="flex cursor-pointer list-none items-start gap-2 px-3 py-2.5 text-[12px] leading-snug transition-colors hover:bg-hover/50">
          <ChevronRight
            className={`mt-0.5 size-3.5 shrink-0 text-tertiary transition-transform ${detailsOpen ? "rotate-90" : ""}`}
            aria-hidden
          />
          <div className="min-w-0 flex-1">
            <span className="font-medium text-foreground">{title}</span>
            {mutation ? (
              <span className="ml-2 text-[10px] font-medium uppercase tracking-wide text-[var(--color-accent)]">
                Confirmation
              </span>
            ) : null}
            {summaryHint ? (
              <p className="mt-0.5 line-clamp-2 text-[11px] text-secondary">
                {summaryHint}
              </p>
            ) : null}
            {call.internal_rationale ? (
              <p className="mt-0.5 line-clamp-2 text-[10px] text-tertiary">
                {call.internal_rationale}
              </p>
            ) : null}
          </div>
        </summary>
        <div className="space-y-3 border-t border-border/60 px-3 py-3">
          <div>
            <div className={TOOL_SECTION_LABEL_CLASS}>Input · CLI</div>
            <pre className="max-h-32 overflow-auto whitespace-pre-wrap break-all rounded-lg border border-border/60 bg-background/80 px-2.5 py-2 font-mono text-[10px] leading-snug text-secondary">
              {line}
            </pre>
          </div>
          {argsBlock && !argsRedundantWithLine ? (
            <div>
              <div className={TOOL_SECTION_LABEL_CLASS}>Input · JSON</div>
              <pre className="max-h-28 overflow-auto whitespace-pre-wrap break-all rounded-lg border border-border/60 bg-background/80 px-2.5 py-2 font-mono text-[10px] text-tertiary">
                {argsBlock}
              </pre>
            </div>
          ) : null}
          {mutation ? (
            <div className="rounded-lg border border-[color:color-mix(in_srgb,var(--color-accent)_35%,var(--color-border))] bg-[color:color-mix(in_srgb,var(--color-accent)_6%,transparent)] px-2.5 py-2 text-[11px] leading-snug">
              <div className={TOOL_SECTION_LABEL_CLASS}>Confirmation · status</div>
              {mutationOutcome === true ? (
                <p className="text-[11px] font-semibold text-foreground">
                  You approved this action — it was applied when you continued.
                </p>
              ) : mutationOutcome === false ? (
                <p className="text-[11px] font-medium text-[var(--color-destructive)]">
                  You rejected this action — no data change was made for this
                  step.
                </p>
              ) : (
                <p className="text-[10px] text-secondary">
                  {showApproval
                    ? "Use Approve or Reject below to run or skip this step (assistant mutation gate, not Inbox)."
                    : "No Approve/Reject on this row — the assistant is not paused here anymore, or you already chose on another card. Inbox (Create expense / Leave unlinked) is a separate review flow."}
                </p>
              )}
              {cmd && !cmdDupOfLine ? (
                <div className="mt-2">
                  <div className={TOOL_SECTION_LABEL_CLASS}>
                    Input · CLI (pending step)
                  </div>
                  <pre className="max-h-28 overflow-auto whitespace-pre-wrap break-all rounded-md border border-border/60 bg-background/90 px-2 py-1.5 font-mono text-[10px] text-tertiary">
                    {cmd}
                  </pre>
                </div>
              ) : null}
            </div>
          ) : null}
          {result &&
          (result.data !== undefined || !hideGenericResult) ? (
            <div className="text-[11px] leading-snug">
              <div className={TOOL_SECTION_LABEL_CLASS}>Output · result</div>
              {result.data !== undefined ? (
                <div className="mt-1 rounded-lg border border-border/60 bg-background/80 px-2 py-2">
                  <FunctionResultDisplay value={result.data} />
                </div>
              ) : (
                <p className="text-secondary">{result.summary}</p>
              )}
            </div>
          ) : null}
          {showApproval && approvalItemsForMutation.length > 0 ? (
            <InlineApprovalControls
              items={approvalItemsForMutation}
              approvalDecisions={approvalDecisions}
              setApprovalDecisions={setApprovalDecisions}
              busy={busy}
              showBusyFooter={showBusyFooter}
              omitItemMeta
              embedCompact
            />
          ) : null}
        </div>
      </details>
    </div>
  );
}

export function InlineApprovalControls({
  items,
  approvalDecisions,
  setApprovalDecisions,
  busy,
  showBusyFooter = true,
  omitItemMeta = false,
  embedCompact = false,
}: {
  items: { pendingId: string; name: string; cli_line: string }[];
  approvalDecisions: Record<string, boolean | null>;
  setApprovalDecisions: Dispatch<
    SetStateAction<Record<string, boolean | null>>
  >;
  busy: boolean;
  showBusyFooter?: boolean;
  omitItemMeta?: boolean;
  embedCompact?: boolean;
}) {
  if (items.length === 0) {
    return null;
  }
  const outerClass = embedCompact
    ? "space-y-2 border-t border-border/60 pt-2"
    : "space-y-3 rounded-lg border border-border bg-background p-3";
  return (
    <div className={outerClass}>
      {items.map((it) => {
        const d = approvalDecisions[it.pendingId];
        return (
          <div
            key={it.pendingId}
            className={
              embedCompact
                ? "flex flex-wrap items-center justify-between gap-2"
                : "rounded-md border border-border/80 bg-surface/60 p-2.5"
            }
          >
            {!omitItemMeta ? (
              <>
                <div className="font-mono text-[11px] font-medium text-foreground">
                  {it.name}
                </div>
                <pre className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap break-all font-mono text-[10px] text-tertiary">
                  {it.cli_line}
                </pre>
              </>
            ) : null}
            <div
              className={
                omitItemMeta
                  ? "flex flex-wrap gap-2"
                  : "mt-2.5 flex flex-wrap gap-2"
              }
            >
              <button
                type="button"
                disabled={busy}
                className={`rounded-md border px-3 py-1.5 text-xs font-medium transition-colors ${
                  d === true
                    ? "border-[var(--color-accent)] bg-[color:color-mix(in_srgb,var(--color-accent)_12%,transparent)] text-foreground"
                    : "border-border bg-[var(--color-hover)]/50 text-secondary hover:text-foreground"
                }`}
                onClick={() =>
                  setApprovalDecisions((prev) => ({
                    ...prev,
                    [it.pendingId]: true,
                  }))
                }
              >
                Approve
              </button>
              <button
                type="button"
                disabled={busy}
                className={`rounded-md border px-3 py-1.5 text-xs font-medium transition-colors ${
                  d === false
                    ? "border-[var(--color-destructive)] bg-[color:color-mix(in_srgb,var(--color-destructive)_12%,transparent)] text-foreground"
                    : "border-border bg-[var(--color-hover)]/50 text-secondary hover:text-foreground"
                }`}
                onClick={() =>
                  setApprovalDecisions((prev) => ({
                    ...prev,
                    [it.pendingId]: false,
                  }))
                }
              >
                Reject
              </button>
            </div>
          </div>
        );
      })}
      {busy && showBusyFooter ? (
        <p
          className={`flex items-center gap-2 text-[11px] text-secondary ${embedCompact ? "pt-1" : ""}`}
        >
          <span
            className="inline-block size-1.5 shrink-0 animate-pulse rounded-full bg-[var(--color-accent)]"
            aria-hidden
          />
          Continuing…
        </p>
      ) : null}
    </div>
  );
}

export function RunBlocksList({
  blocks,
  barrier,
  approvalDecisions,
  setApprovalDecisions,
  busy,
  mutationOutcomeByPendingId,
}: {
  blocks: LiveBlock[];
  barrier: ApprovalBarrier | null;
  approvalDecisions: Record<string, boolean | null>;
  setApprovalDecisions: Dispatch<
    SetStateAction<Record<string, boolean | null>>
  >;
  busy: boolean;
  mutationOutcomeByPendingId: Record<string, boolean | undefined>;
}) {
  const segments = segmentLiveBlocks(
    dropRedundantModelPhaseBeforeAssistant(blocks),
  );
  const approvalBlock = [...blocks]
    .reverse()
    .find(
      (x): x is Extract<LiveBlock, { kind: "approval_required" }> =>
        x.kind === "approval_required",
    );
  const activeBarrierForRun =
    approvalBlock &&
    barrier &&
    barrierMatchesApprovalBlock(
      barrier,
      approvalBlock.run_id,
      approvalBlock.pending_ids,
    )
      ? barrier
      : null;

  let firstPendingToolKey: string | null = null;
  let lastPendingToolKey: string | null = null;
  if (activeBarrierForRun) {
    for (const seg of segments) {
      if (seg.type !== "tool_group" || !seg.mutation) {
        continue;
      }
      const pid = seg.mutation.pending_id.trim();
      if (
        pid &&
        activeBarrierForRun.items.some((it) => it.pendingId.trim() === pid)
      ) {
        if (firstPendingToolKey === null) {
          firstPendingToolKey = seg.key;
        }
        lastPendingToolKey = seg.key;
      }
    }
  }

  const postToolAssistantIds = postToolAssistantBlockIds(blocks);

  return (
    <div className="space-y-3">
      {segments.map((seg, segIdx) => {
        if (seg.type === "tool_group") {
          const pid = seg.mutation?.pending_id?.trim() ?? "";
          const showApproval = Boolean(
            activeBarrierForRun &&
              pid &&
              activeBarrierForRun.items.some(
                (it) => it.pendingId.trim() === pid,
              ),
          );
          const approvalItemsForMutation =
            showApproval && activeBarrierForRun
              ? activeBarrierForRun.items.filter(
                  (it) => it.pendingId.trim() === pid,
                )
              : [];
          const anchorId =
            showApproval && seg.key === firstPendingToolKey
              ? "hof-agent-pending-confirmation"
              : undefined;
          const showBusyFooter =
            showApproval && seg.key === lastPendingToolKey;
          const mutationOutcome =
            pid !== "" ? mutationOutcomeByPendingId[pid] : undefined;
          const proposedLabel = showProposedActionsLabel(
            segments,
            segIdx,
            postToolAssistantIds,
          );

          return (
            <div key={seg.key} className="space-y-2">
              {proposedLabel ? (
                <div className="text-[10px] font-medium uppercase tracking-wide text-tertiary">
                  Proposed actions
                </div>
              ) : null}
              <ToolGroupCard
                call={seg.call}
                mutation={seg.mutation}
                result={seg.result}
                showApproval={showApproval}
                approvalItemsForMutation={approvalItemsForMutation}
                approvalDecisions={approvalDecisions}
                setApprovalDecisions={setApprovalDecisions}
                busy={busy}
                showBusyFooter={showBusyFooter}
                anchorId={anchorId}
                mutationOutcome={mutationOutcome}
              />
            </div>
          );
        }
        const b = seg.block;
        if (b.kind === "approval_required") {
          const activeBarrier =
            barrier &&
            barrierMatchesApprovalBlock(barrier, b.run_id, b.pending_ids)
              ? barrier
              : null;
          const footerDone = confirmationFooterFromOutcomes(
            b.pending_ids,
            mutationOutcomeByPendingId,
          );
          const outcomeKnown =
            !activeBarrier && footerDone !== "Confirmation completed.";
          return (
            <div
              key={b.id}
              className={`text-[11px] leading-snug ${outcomeKnown ? "font-medium text-secondary" : "text-tertiary"}`}
            >
              {activeBarrier ? (
                <p>
                  The assistant continues after you have chosen Approve or Reject
                  for each pending action above.
                </p>
              ) : (
                <p>{footerDone}</p>
              )}
            </div>
          );
        }
        return (
          <LiveBlockView
            key={b.id}
            b={b}
            afterToolResult={postToolAssistantIds.has(b.id)}
          />
        );
      })}
    </div>
  );
}

/** Shared shell for `streamPhase === "model"`: optional Thinking chrome + streaming markdown. */
function AssistantModelStreamShell({
  streamText,
  streamTextRole,
  replyBubbleClass,
  emptyLabel,
}: {
  streamText: string;
  streamTextRole: "content" | "reasoning" | "mixed" | undefined;
  replyBubbleClass: string;
  emptyLabel: string;
}) {
  const hasStreamText = streamText.trim().length > 0;
  if (streamTextRole === "reasoning") {
    return (
      <ReasoningCollapsible text={streamText} streaming={true} />
    );
  }
  if (!hasStreamText) {
    return (
      <div
        className="max-w-[min(100%,42rem)] flex items-center gap-1.5 py-0.5"
        aria-busy="true"
        aria-label={emptyLabel || "Assistant is working"}
      >
        <span
          className="inline-block size-1.5 shrink-0 animate-pulse rounded-full bg-[var(--color-accent)]"
          aria-hidden
        />
        <span className="inline-block h-4 w-0.5 animate-pulse bg-[var(--color-accent)] align-middle" />
      </div>
    );
  }
  return (
    <div className="max-w-[min(100%,42rem)] space-y-1.5">
      <div
        className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide text-tertiary"
        aria-live="polite"
      >
        <span
          className="inline-block size-1.5 shrink-0 animate-pulse rounded-full bg-[var(--color-accent)]"
          aria-hidden
        />
        Thinking
      </div>
      <div
        className={`${replyBubbleClass} transition-opacity duration-200 opacity-[0.88]`}
      >
        <AssistantMarkdown source={streamText} />
        <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-[var(--color-accent)] align-middle" />
      </div>
    </div>
  );
}

export function ReasoningCollapsible({
  text,
  streaming,
}: {
  text: string;
  streaming: boolean;
}) {
  const [open, setOpen] = useState(
    () => streaming || text.trim().length > 0,
  );

  useEffect(() => {
    if (streaming) {
      setOpen(true);
    }
  }, [streaming]);

  if (!text.trim() && !streaming) {
    return null;
  }

  return (
    <details
      className="max-w-[min(100%,42rem)] [&[open]>summary_svg]:rotate-90"
      open={open}
      onToggle={(e) => setOpen(e.currentTarget.open)}
    >
      <summary className="flex cursor-pointer list-none items-center gap-1 py-0.5 text-[10px] text-tertiary marker:content-none [&::-webkit-details-marker]:hidden">
        <ChevronRight
          className="size-3 shrink-0 text-tertiary transition-transform duration-150"
          aria-hidden
        />
        <span className="font-medium uppercase tracking-wide">Thinking</span>
      </summary>
      <div className="border-l border-border/70 pl-2.5 pt-1 pb-0.5 text-[11px] leading-snug text-secondary">
        {text.trim() ? <AssistantMarkdown source={text} /> : null}
        {streaming ? (
          <span className="ml-0.5 inline-block h-3 w-px animate-pulse bg-[var(--color-accent)] align-middle" />
        ) : null}
      </div>
    </details>
  );
}

/** Renders ``streamSegments`` from NDJSON ``segment_start`` + deltas (llm-markdown agentic contract). */
function AssistantSegmentedBody({
  segments,
  streaming,
  replyBubbleClass,
  emptyLabel,
}: {
  segments: AssistantStreamSegment[];
  streaming: boolean;
  replyBubbleClass: string;
  emptyLabel: string;
}) {
  return (
    <div className="max-w-[min(100%,42rem)] space-y-3">
      {segments.map((s, i) => {
        const isLast = i === segments.length - 1;
        const pulse = streaming && isLast;
        if (s.kind === "reasoning") {
          return (
            <ReasoningCollapsible
              key={`seg-r-${i}`}
              text={s.text}
              streaming={pulse}
            />
          );
        }
        if (!s.text.trim() && !pulse) {
          return null;
        }
        if (!s.text.trim() && pulse) {
          return (
            <div
              key={`seg-c-${i}`}
              className="max-w-[min(100%,42rem)] flex items-center gap-1.5 py-0.5"
              aria-busy="true"
              aria-label={emptyLabel || "Assistant is drafting"}
            >
              <span
                className="inline-block size-1.5 shrink-0 animate-pulse rounded-full bg-[var(--color-accent)]"
                aria-hidden
              />
              <span className="inline-block h-4 w-0.5 animate-pulse bg-[var(--color-accent)] align-middle" />
            </div>
          );
        }
        return (
          <div key={`seg-c-${i}`} className={replyBubbleClass}>
            <AssistantMarkdown source={s.text} />
            {pulse ? (
              <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-[var(--color-accent)] align-middle" />
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

export function LiveBlockView({
  b,
  afterToolResult = false,
}: {
  b: LiveBlock;
  afterToolResult?: boolean;
}) {
  if (b.kind === "thinking_skeleton") {
    const replyBubbleClass = CHAT_ASSISTANT_REPLY_BUBBLE_CLASS;
    return (
      <div
        className="max-w-[min(100%,42rem)] space-y-1.5"
        aria-busy="true"
        aria-label="Assistant is thinking"
      >
        <div className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide text-tertiary">
          <span
            className="inline-block size-1.5 shrink-0 animate-pulse rounded-full bg-[var(--color-accent)]"
            aria-hidden
          />
          Thinking
        </div>
        <div
          className={`${replyBubbleClass} transition-opacity duration-200 opacity-[0.88]`}
        >
          <span className="text-[11px] leading-snug text-secondary">
            Working through your request…
          </span>
          <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-[var(--color-accent)] align-middle" />
        </div>
      </div>
    );
  }
  if (b.kind === "phase") {
    if (b.phase === "summary") {
      return null;
    }
    if (b.phase === "tools") {
      return (
        <div
          className="flex items-center gap-1.5 border-l-2 border-border pl-3 text-[11px] leading-snug text-tertiary"
          aria-busy="true"
          aria-label="Running tools"
        >
          <span
            className="inline-block size-1.5 shrink-0 animate-pulse rounded-full bg-[var(--color-accent)]"
            aria-hidden
          />
          Running tools…
        </div>
      );
    }
    if (b.phase === "model") {
      return (
        <div className="border-l-2 border-border pl-3 text-[11px] italic leading-snug text-tertiary">
          Thinking…
        </div>
      );
    }
    return (
      <div className="flex items-start gap-2 border-l-2 border-border pl-3 text-[12px] leading-snug text-secondary">
        <span className="italic text-tertiary">{b.phase}</span>
      </div>
    );
  }
  if (b.kind === "assistant") {
    const replyBubbleClass = CHAT_ASSISTANT_REPLY_BUBBLE_CLASS;
    const lane = inferAssistantUiLane(b);
    const isSummary = b.streamPhase === "summary";
    const isModel = b.streamPhase === "model";
    const streamSegs = b.streamSegments?.length ? b.streamSegments : null;
    const anySegText = streamSegs?.some((s) => s.text.trim()) ?? false;

    if (afterToolResult || isSummary) {
      if (b.streaming) {
        const streamText = b.text;
        const hasStreamText = streamText.trim().length > 0;
        // Logs: first model round often has zero assistant_delta before tool_calls; post-tool
        // rounds stream text into the same assistant block. Use Thinking shell for model-phase
        // streaming so tokens are visible like pre-tool; summary round stays a plain bubble.
        if (b.streamPhase === "summary") {
          if (streamSegs) {
            return (
              <AssistantSegmentedBody
                segments={streamSegs}
                streaming
                replyBubbleClass={replyBubbleClass}
                emptyLabel=""
              />
            );
          }
          if (!hasStreamText) {
            return (
              <div
                className="max-w-[min(100%,42rem)] flex items-center gap-1.5 py-0.5"
                aria-busy="true"
                aria-label="Assistant is drafting"
              >
                <span
                  className="inline-block size-1.5 shrink-0 animate-pulse rounded-full bg-[var(--color-accent)]"
                  aria-hidden
                />
                <span className="inline-block h-4 w-0.5 animate-pulse bg-[var(--color-accent)] align-middle" />
              </div>
            );
          }
          return (
            <div className={replyBubbleClass}>
              <AssistantMarkdown source={streamText} />
              <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-[var(--color-accent)] align-middle" />
            </div>
          );
        }
        if (streamSegs) {
          return (
            <AssistantSegmentedBody
              segments={streamSegs}
              streaming
              replyBubbleClass={replyBubbleClass}
              emptyLabel="Drafting the answer…"
            />
          );
        }
        return (
          <AssistantModelStreamShell
            streamText={streamText}
            streamTextRole={b.streamTextRole}
            replyBubbleClass={replyBubbleClass}
            emptyLabel="Drafting the answer…"
          />
        );
      }
      if (streamSegs) {
        if (!anySegText) {
          return null;
        }
        return (
          <AssistantSegmentedBody
            segments={streamSegs}
            streaming={false}
            replyBubbleClass={replyBubbleClass}
            emptyLabel=""
          />
        );
      }
      const text = b.text.trim();
      if (!text) {
        return null;
      }
      return (
        <div className={replyBubbleClass}>
          <AssistantMarkdown source={b.text} />
        </div>
      );
    }

    if (isModel && b.streaming) {
      if (streamSegs) {
        return (
          <AssistantSegmentedBody
            segments={streamSegs}
            streaming
            replyBubbleClass={replyBubbleClass}
            emptyLabel="Tools may run before any reply text appears."
          />
        );
      }
      return (
        <AssistantModelStreamShell
          streamText={b.text}
          streamTextRole={b.streamTextRole}
          replyBubbleClass={replyBubbleClass}
          emptyLabel="Tools may run before any reply text appears."
        />
      );
    }

    if (isModel && !b.streaming && lane === "thinking") {
      if (streamSegs) {
        if (!anySegText) {
          return (
            <div className="max-w-[min(100%,42rem)] border-l-2 border-border pl-3 text-[11px] leading-snug text-tertiary">
              No visible plan text before tools (normal for many models). See tool steps below.
            </div>
          );
        }
        return (
          <AssistantSegmentedBody
            segments={streamSegs}
            streaming={false}
            replyBubbleClass={replyBubbleClass}
            emptyLabel=""
          />
        );
      }
      const t = b.text.trim();
      if (!t) {
        return (
          <div className="max-w-[min(100%,42rem)] border-l-2 border-border pl-3 text-[11px] leading-snug text-tertiary">
            No visible plan text before tools (normal for many models). See tool steps below.
          </div>
        );
      }
      return <ReasoningCollapsible text={b.text} streaming={false} />;
    }

    if (isModel && !b.streaming && lane === "reply") {
      if (streamSegs && anySegText) {
        return (
          <AssistantSegmentedBody
            segments={streamSegs}
            streaming={false}
            replyBubbleClass={replyBubbleClass}
            emptyLabel=""
          />
        );
      }
      const text = b.text.trim();
      if (!text) {
        return null;
      }
      return (
        <div className={replyBubbleClass}>
          <AssistantMarkdown source={b.text} />
        </div>
      );
    }

    const role = assistantUiRole(b, { afterToolResult });
    if (role === "reasoning" && !b.streaming) {
      if (streamSegs && anySegText) {
        return (
          <AssistantSegmentedBody
            segments={streamSegs}
            streaming={false}
            replyBubbleClass={replyBubbleClass}
            emptyLabel=""
          />
        );
      }
      return <ReasoningCollapsible text={b.text} streaming={false} />;
    }

    if (b.streaming) {
      if (streamSegs) {
        return (
          <AssistantSegmentedBody
            segments={streamSegs}
            streaming
            replyBubbleClass={replyBubbleClass}
            emptyLabel="Waiting for the model…"
          />
        );
      }
      return (
        <AssistantModelStreamShell
          streamText={b.text}
          streamTextRole={b.streamTextRole}
          replyBubbleClass={replyBubbleClass}
          emptyLabel="Waiting for the model…"
        />
      );
    }

    if (streamSegs && anySegText) {
      return (
        <AssistantSegmentedBody
          segments={streamSegs}
          streaming={false}
          replyBubbleClass={replyBubbleClass}
          emptyLabel=""
        />
      );
    }

    const text = b.text.trim();
    if (!text) {
      return null;
    }

    return (
      <div className={replyBubbleClass}>
        <AssistantMarkdown source={b.text} />
      </div>
    );
  }
  if (b.kind === "tool_call") {
    const title = humanizeToolName(b.name);
    const line = toolCallCliLine(b);
    const argsBlock = toolCallArgsSnippet(b);
    return (
      <div className="flex gap-2.5 text-[12px] leading-snug">
        <Terminal
          className="mt-0.5 size-3.5 shrink-0 text-[var(--color-accent)] opacity-80"
          aria-hidden
        />
        <div className="min-w-0 flex-1 space-y-2">
          <div className="font-medium text-foreground">{title}</div>
          <div>
            <div className={TOOL_SECTION_LABEL_CLASS}>Input · CLI</div>
            <pre className="max-h-32 overflow-auto whitespace-pre-wrap break-all rounded-lg border border-border/60 bg-background/80 px-2.5 py-2 font-mono text-[10px] leading-snug text-secondary">
              {line}
            </pre>
          </div>
          {argsBlock ? (
            <div>
              <div className={TOOL_SECTION_LABEL_CLASS}>Input · JSON</div>
              <pre className="max-h-28 overflow-auto whitespace-pre-wrap break-all rounded-lg border border-border/60 bg-background/80 px-2.5 py-2 font-mono text-[10px] text-tertiary">
                {argsBlock}
              </pre>
            </div>
          ) : null}
        </div>
      </div>
    );
  }
  if (b.kind === "tool_result") {
    const title = humanizeToolName(b.name);
    return (
      <div className="flex gap-2.5 pl-0.5 text-[12px] leading-snug">
        <span
          className="mt-1.5 size-1.5 shrink-0 rounded-full bg-[var(--color-accent)] opacity-70"
          aria-hidden
        />
        <div className="min-w-0">
          <span className="font-medium text-foreground">{title}</span>
          <div className="mt-1">
            <div className={TOOL_SECTION_LABEL_CLASS}>Output · result</div>
            {b.data !== undefined ? (
              <div className="mt-1 rounded-lg border border-border/60 bg-background/80 px-2 py-2">
                <FunctionResultDisplay value={b.data} />
              </div>
            ) : (
              <p className="text-[11px] text-secondary">{b.summary}</p>
            )}
          </div>
        </div>
      </div>
    );
  }
  if (b.kind === "mutation_pending") {
    const title = humanizeToolName(b.name);
    const cmd = b.cli_line || b.arguments_preview || "";
    return (
      <div className="rounded-xl border border-[color:color-mix(in_srgb,var(--color-accent)_35%,var(--color-border))] bg-[color:color-mix(in_srgb,var(--color-accent)_6%,transparent)] px-3 py-2.5 text-[12px] leading-snug">
        <div className="font-medium text-foreground">
          Awaiting your approval · {title}
        </div>
        <div className="mt-1">
          <div className={TOOL_SECTION_LABEL_CLASS}>Confirmation · status</div>
          <p className="text-[11px] text-secondary">
            When this step is grouped in the tool card above, use Approve or
            Reject inside that expanded row.
          </p>
        </div>
        {cmd ? (
          <div className="mt-2">
            <div className={TOOL_SECTION_LABEL_CLASS}>Input · CLI</div>
            <pre className="max-h-32 overflow-auto whitespace-pre-wrap break-all rounded-lg border border-border/60 bg-background/90 px-2.5 py-2 font-mono text-[10px] text-tertiary">
              {cmd}
            </pre>
          </div>
        ) : null}
      </div>
    );
  }
  if (b.kind === "approval_required") {
    return null;
  }
  return (
    <div className="text-[12px] text-[var(--color-destructive)]">
      {b.detail}
    </div>
  );
}
