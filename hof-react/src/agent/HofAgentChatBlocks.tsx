"use client";

import {
  Braces,
  Check,
  CheckCircle2,
  ChevronRight,
  X,
  XCircle,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { createPortal } from "react-dom";
import { AssistantMarkdown } from "./AssistantMarkdown";
import { FunctionResultDisplay } from "./FunctionResultDisplay";
import {
  AGENT_CHAT_COLUMN_CLASS,
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
  toolArgumentsAreEffectivelyEmpty,
  toolCallCliLine,
  toolResultUiStatus,
  mergeAdjacentContentSegments,
  mergeAdjacentReasoningSegments,
} from "./hofAgentChatModel";
import type {
  ApprovalBarrier,
  AssistantStreamSegment,
  LiveBlock,
  MutationPendingBlock,
  ToolCallBlock,
  ToolResultBlock,
} from "./hofAgentChatModel";

function formatToolJsonForDialog(raw: string): string {
  const t = raw.trim();
  if (!t) {
    return "";
  }
  try {
    return JSON.stringify(JSON.parse(t) as unknown, null, 2);
  } catch {
    return raw;
  }
}

/** One line: `$` + CLI, braces opens JSON dialog. Used inside the tool card body. */
function ToolTerminalCommandRow({
  cliLine,
  argumentsStr,
  borderBottom = true,
}: {
  cliLine: string;
  argumentsStr?: string;
  /** When false, no bottom rule (e.g. command-only block). */
  borderBottom?: boolean;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const showJsonBtn =
    argumentsStr != null && !toolArgumentsAreEffectivelyEmpty(argumentsStr);
  const formatted = argumentsStr ? formatToolJsonForDialog(argumentsStr) : "";

  return (
    <>
      <div
        className={`flex w-full max-h-32 items-stretch overflow-hidden bg-[color:color-mix(in_srgb,var(--color-foreground)_2.5%,transparent)] ${borderBottom ? "border-b border-border" : ""}`}
      >
        <div
          className={`flex min-h-0 min-w-0 flex-1 items-center py-2 pl-3 ${showJsonBtn ? "pr-0" : "pr-3"}`}
        >
          <span
            className="shrink-0 pr-1 font-mono text-[11px] leading-none text-tertiary select-none"
            aria-hidden
          >
            $
          </span>
          <pre className="min-h-0 min-w-0 flex-1 overflow-auto whitespace-pre-wrap break-all py-0 font-mono text-[11px] leading-snug text-foreground">
            {cliLine}
          </pre>
        </div>
        {showJsonBtn ? (
          <div className="flex shrink-0 self-stretch border-l border-border">
            <button
              type="button"
              className="flex items-center justify-center px-2.5 py-0.5 text-tertiary transition-colors hover:bg-hover hover:text-foreground"
              aria-label="View JSON input"
              onClick={() => dialogRef.current?.showModal()}
            >
              <Braces
                className="size-3.5 shrink-0"
                strokeWidth={2}
                aria-hidden
              />
            </button>
          </div>
        ) : null}
      </div>
      <dialog
        ref={dialogRef}
        className="fixed top-1/2 left-1/2 z-50 w-[min(100vw-2rem,36rem)] max-h-[min(90vh,32rem)] -translate-x-1/2 -translate-y-1/2 rounded-lg border border-border bg-background p-0 font-sans text-foreground shadow-lg backdrop:bg-black/40"
        onMouseDown={(e) => {
          if (e.target === dialogRef.current) {
            dialogRef.current.close();
          }
        }}
      >
        <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
          <span className="text-sm font-medium text-foreground">
            JSON input
          </span>
          <button
            type="button"
            className="rounded-md px-2 py-1 text-xs text-secondary hover:bg-hover hover:text-foreground"
            onClick={() => dialogRef.current?.close()}
          >
            Close
          </button>
        </div>
        <pre className="max-h-[min(70vh,24rem)] overflow-auto whitespace-pre-wrap break-all p-3 font-mono text-[11px] leading-snug text-secondary">
          {formatted}
        </pre>
      </dialog>
    </>
  );
}

function ToolResultStatusStrip({ result }: { result: ToolResultBlock }) {
  const st = toolResultUiStatus(result);
  const colorClass =
    st.tone === "success"
      ? "text-[var(--color-success)]"
      : st.tone === "error"
        ? "text-[var(--color-destructive)]"
        : st.tone === "pending"
          ? "text-[var(--color-accent)]"
          : "text-secondary";
  return (
    <div className="flex items-center justify-between gap-2 bg-surface/30 px-3 py-1.5 font-mono text-[10px]">
      <span className="text-tertiary">Result</span>
      <span className={`shrink-0 font-medium tabular-nums ${colorClass}`}>
        {st.code} <span className="font-normal opacity-90">{st.label}</span>
      </span>
    </div>
  );
}

/** Check / cross in the tool card header: pick when waiting; shows outcome when done. */
function ToolMutationCorner({
  showApproval,
  approvalItemsForMutation,
  approvalDecisions,
  setApprovalDecisions,
  busy,
  mutationOutcome,
}: {
  showApproval: boolean;
  approvalItemsForMutation: {
    pendingId: string;
    name: string;
    cli_line: string;
  }[];
  approvalDecisions: Record<string, boolean | null>;
  setApprovalDecisions: Dispatch<
    SetStateAction<Record<string, boolean | null>>
  >;
  busy: boolean;
  mutationOutcome?: boolean;
}) {
  if (mutationOutcome === true) {
    return (
      <div
        className="flex shrink-0 items-start pt-0.5"
        title="Approved"
        aria-label="Approved"
      >
        <CheckCircle2
          className="size-[1.35rem] text-[var(--color-success)]"
          strokeWidth={2}
          aria-hidden
        />
      </div>
    );
  }
  if (mutationOutcome === false) {
    return (
      <div
        className="flex shrink-0 items-start pt-0.5"
        title="Rejected"
        aria-label="Rejected"
      >
        <XCircle
          className="size-[1.35rem] text-[var(--color-destructive)]"
          strokeWidth={2}
          aria-hidden
        />
      </div>
    );
  }
  if (!showApproval || approvalItemsForMutation.length === 0) {
    return null;
  }
  return (
    <div
      className="flex shrink-0 flex-col items-end gap-1.5 pt-0.5"
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
      }}
    >
      {approvalItemsForMutation.map((it) => {
        const d = approvalDecisions[it.pendingId];
        return (
          <div key={it.pendingId} className="flex items-center gap-1">
            <button
              type="button"
              disabled={busy}
              title="Approve"
              aria-label={`Approve ${it.name}`}
              className={`rounded-md border p-1.5 transition-colors ${
                d === true
                  ? "border-[var(--color-success)] bg-[color:color-mix(in_srgb,var(--color-success)_12%,transparent)] text-foreground"
                  : "border-border bg-background text-secondary hover:bg-hover hover:text-foreground"
              }`}
              onClick={() =>
                setApprovalDecisions((prev) => ({
                  ...prev,
                  [it.pendingId]: true,
                }))
              }
            >
              <Check className="size-4" strokeWidth={2.5} aria-hidden />
            </button>
            <button
              type="button"
              disabled={busy}
              title="Reject"
              aria-label={`Reject ${it.name}`}
              className={`rounded-md border p-1.5 transition-colors ${
                d === false
                  ? "border-[var(--color-destructive)] bg-[color:color-mix(in_srgb,var(--color-destructive)_12%,transparent)] text-foreground"
                  : "border-border bg-background text-secondary hover:bg-hover hover:text-foreground"
              }`}
              onClick={() =>
                setApprovalDecisions((prev) => ({
                  ...prev,
                  [it.pendingId]: false,
                }))
              }
            >
              <X className="size-4" strokeWidth={2.5} aria-hidden />
            </button>
          </div>
        );
      })}
    </div>
  );
}

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
  approvalItemsForMutation: {
    pendingId: string;
    name: string;
    cli_line: string;
  }[];
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
  const cmd = mutation
    ? mutation.cli_line || mutation.arguments_preview || ""
    : "";
  const cmdDupOfLine = Boolean(cmd.trim()) && cmd.trim() === line.trim();
  const hideGenericResult = Boolean(
    mutation && result && isGenericAwaitingConfirmationSummary(result.summary),
  );
  const showResultBlock = Boolean(
    result && (result.data !== undefined || !hideGenericResult),
  );
  /** Tool output inside the expandable card only. */
  const showInnerBody = showResultBlock;
  const mutationHintWhenIdle =
    Boolean(mutation) &&
    !showApproval &&
    mutationOutcome === undefined;
  const showMutationCmdDup = Boolean(
    mutation && cmd && !cmdDupOfLine,
  );
  const showDetailsFooter =
    Boolean(result) ||
    showInnerBody ||
    mutationHintWhenIdle ||
    showMutationCmdDup;

  const [detailsOpen, setDetailsOpen] = useState(false);
  useEffect(() => {
    if (showApproval) {
      setDetailsOpen(true);
    }
  }, [showApproval]);

  return (
    <div
      id={anchorId}
      className={`${AGENT_CHAT_COLUMN_CLASS} scroll-mt-4 space-y-2`}
    >
      <details
        open={detailsOpen}
        onToggle={(e) => setDetailsOpen(e.currentTarget.open)}
        className="group w-full rounded-lg border border-border bg-surface/40 [&_summary::-webkit-details-marker]:hidden"
      >
        <summary className="flex cursor-pointer list-none items-start gap-2 px-3 py-2.5 text-[12px] leading-snug transition-colors hover:bg-hover/50">
          <ChevronRight
            className={`mt-0.5 size-3.5 shrink-0 text-tertiary transition-transform ${detailsOpen ? "rotate-90" : ""}`}
            aria-hidden
          />
          <div className="min-w-0 flex-1">
            <span className="font-medium text-foreground">{title}</span>
            {mutation ? (
              <span
                className={`ml-2 text-[10px] font-medium uppercase tracking-wide ${
                  mutationOutcome === true
                    ? "text-[var(--color-success)]"
                    : mutationOutcome === false
                      ? "text-[var(--color-destructive)]"
                      : "text-[var(--color-accent)]"
                }`}
              >
                Confirmation
              </span>
            ) : null}
          </div>
          {mutation ? (
            <ToolMutationCorner
              showApproval={showApproval}
              approvalItemsForMutation={approvalItemsForMutation}
              approvalDecisions={approvalDecisions}
              setApprovalDecisions={setApprovalDecisions}
              busy={busy}
              mutationOutcome={mutationOutcome}
            />
          ) : null}
        </summary>
        <div className="border-t border-border/60">
          <ToolTerminalCommandRow
            cliLine={line}
            argumentsStr={call.arguments}
            borderBottom={showDetailsFooter}
          />
          {result ? <ToolResultStatusStrip result={result} /> : null}
          {showInnerBody ? (
            <div className="space-y-3 px-3 pb-2 pt-1.5">
              {showResultBlock ? (
                <div>
                  {result!.data !== undefined ? (
                    <FunctionResultDisplay value={result!.data} />
                  ) : (
                    <p className="whitespace-pre-wrap font-mono text-[11px] leading-snug text-secondary">
                      {result!.summary}
                    </p>
                  )}
                </div>
              ) : null}
            </div>
          ) : null}
          {mutationHintWhenIdle ? (
            <div className="px-3 pb-2 text-[10px] text-secondary">
              No Approve/Reject here — you already chose on another card, or
              this step is not paused. Inbox review is separate.
            </div>
          ) : null}
          {showMutationCmdDup ? (
            <div className="px-3 pb-2">
              <div className="flex items-center overflow-hidden rounded-md border border-border/60 bg-[color:color-mix(in_srgb,var(--color-foreground)_2.5%,transparent)]">
                <span
                  className="shrink-0 pl-2 pr-1 py-1 font-mono text-[10px] leading-none text-tertiary select-none"
                  aria-hidden
                >
                  $
                </span>
                <pre className="min-w-0 flex-1 overflow-auto whitespace-pre-wrap break-all py-1 pr-2 font-mono text-[10px] leading-snug text-secondary">
                  {cmd}
                </pre>
              </div>
            </div>
          ) : null}
        </div>
      </details>
      {mutation &&
      showApproval &&
      approvalItemsForMutation.length > 0 &&
      busy &&
      showBusyFooter ? (
        <p className="flex items-center gap-2 text-[11px] text-secondary">
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
                    ? "border-[var(--color-success)] bg-[color:color-mix(in_srgb,var(--color-success)_12%,transparent)] text-foreground"
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
            activeBarrierForRun.items.some((it) => it.pendingId.trim() === pid),
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
          const showBusyFooter = showApproval && seg.key === lastPendingToolKey;
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
          if (activeBarrier) {
            return (
              <div
                key={b.id}
                className="text-[11px] leading-snug text-tertiary"
              >
                <p>
                  The assistant continues after you have chosen Approve or
                  Reject for each pending action above.
                </p>
              </div>
            );
          }
          if (!footerDone) {
            return null;
          }
          return (
            <div
              key={b.id}
              className={`text-[11px] leading-snug ${
                footerDone !== "Confirmation completed."
                  ? "font-medium text-secondary"
                  : "text-tertiary"
              }`}
            >
              <p>{footerDone}</p>
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

function looksLikeJsonOrToolCallLine(t: string): boolean {
  const s = t.trim();
  if (!s) {
    return false;
  }
  if (/^\s*\{\s*"name"\s*:\s*"/.test(s)) {
    return true;
  }
  if (/^\s*"[^"]+"\s*:\s*/.test(s)) {
    return true;
  }
  if (/^\s*[\[{]/.test(s) && /[\]}]\s*,?\s*$/.test(s)) {
    return true;
  }
  return false;
}

/**
 * Strip HTML tags, markdown tables, bullet/numbered lists, headings, code fences,
 * and JSON-like lines (hallucinated tool payloads) — the thinking pane is plain analytical notes only.
 */
function sanitizeReasoningText(raw: string): string {
  let s = raw;
  // Strip HTML details/summary blocks (models sometimes dump these into thinking)
  s = s.replace(/<details\b[^>]*>[\s\S]*?<\/details>/gi, "");
  // Strip HTML tags
  s = s.replace(/<[^>]*>/g, "");
  // Strip markdown headings
  s = s.replace(/^#{1,6}\s+/gm, "");
  // Strip markdown table rows (lines starting with |)
  s = s.replace(/^\|.*\|$/gm, "");
  // Strip horizontal rules / table separators
  s = s.replace(/^[-|:]+$/gm, "");
  // Strip code fences
  s = s.replace(/^```[\s\S]*?^```/gm, "");
  // Strip bullet / numbered list markers (keep the text)
  s = s.replace(/^(\s*[-*+]|\s*\d+[.)]) /gm, "");
  // Strip bold/italic markers
  s = s.replace(/\*{1,2}([^*]+)\*{1,2}/g, "$1");
  const jsonStripped = s
    .split("\n")
    .filter((line) => !looksLikeJsonOrToolCallLine(line))
    .join("\n");
  s = jsonStripped;
  // Collapse blank lines
  s = s.replace(/\n{3,}/g, "\n\n");
  return s.trim();
}

const REASONING_SHIMMER_STYLE_ID = "hof-reasoning-shimmer-kf";

function ensureReasoningShimmerKeyframes(): void {
  if (typeof document === "undefined") {
    return;
  }
  if (document.getElementById(REASONING_SHIMMER_STYLE_ID)) {
    return;
  }
  const s = document.createElement("style");
  s.id = REASONING_SHIMMER_STYLE_ID;
  s.textContent = `@keyframes hof-reasoning-shimmer {
  0% { background-position: 0% 50%; }
  100% { background-position: 100% 50%; }
}`;
  document.head.appendChild(s);
}

/** Matches streaming “Thinking” in {@link ReasoningStreamPeek} (shimmer gradient). */
const REASONING_THINKING_SHIMMER_LABEL_CLASS =
  "text-[11px] font-medium bg-clip-text text-transparent [background-image:linear-gradient(98deg,var(--color-muted-foreground)_0%,var(--color-accent)_42%,var(--color-foreground)_52%,var(--color-accent)_62%,var(--color-muted-foreground)_100%)] bg-[length:220%_100%] [animation:hof-reasoning-shimmer_2.5s_ease-in-out_infinite]";

/**
 * Shown while the agent run is busy but no live blocks exist yet (before first NDJSON row).
 * Replaces the old “Connecting” copy with the same visual “Thinking” treatment.
 */
export function AgentEarlyThinkingIndicator() {
  useEffect(() => {
    ensureReasoningShimmerKeyframes();
  }, []);
  return (
    <div
      className={`${AGENT_CHAT_COLUMN_CLASS} font-sans`}
      aria-busy="true"
      aria-live="polite"
      aria-label="Thinking"
    >
      <span className={REASONING_THINKING_SHIMMER_LABEL_CLASS}>Thinking</span>
    </div>
  );
}

function ReasoningStreamPeek({
  text,
  streaming,
}: {
  text: string;
  streaming: boolean;
}) {
  const [open, setOpen] = useState(false);
  const columnRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const hoverCloseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clean = sanitizeReasoningText(text);
  const popoverId = useId();
  const [popoverBox, setPopoverBox] = useState<{
    top: number;
    left: number;
    width: number;
  } | null>(null);

  useEffect(() => {
    ensureReasoningShimmerKeyframes();
  }, []);

  const cancelScheduledPopoverClose = useCallback(() => {
    if (hoverCloseTimerRef.current != null) {
      window.clearTimeout(hoverCloseTimerRef.current);
      hoverCloseTimerRef.current = null;
    }
  }, []);

  const schedulePopoverCloseAfterLeave = useCallback(() => {
    cancelScheduledPopoverClose();
    hoverCloseTimerRef.current = window.setTimeout(() => {
      setOpen(false);
      hoverCloseTimerRef.current = null;
    }, 200);
  }, [cancelScheduledPopoverClose]);

  useEffect(
    () => () => {
      cancelScheduledPopoverClose();
    },
    [cancelScheduledPopoverClose],
  );

  const updatePopoverPosition = useCallback(() => {
    const col = columnRef.current;
    const btn = triggerRef.current;
    if (!col || !btn) {
      return;
    }
    const cr = col.getBoundingClientRect();
    const br = btn.getBoundingClientRect();
    const vw = window.innerWidth;
    const margin = 12;
    let width = cr.width;
    let left = cr.left;
    if (width > vw - 2 * margin) {
      width = Math.max(vw - 2 * margin, 0);
      left = margin;
    } else {
      if (left + width > vw - margin) {
        left = vw - margin - width;
      }
      if (left < margin) {
        left = margin;
      }
    }
    setPopoverBox({
      top: br.bottom + 8,
      left,
      width,
    });
  }, []);

  useLayoutEffect(() => {
    if (!open) {
      setPopoverBox(null);
      return;
    }
    updatePopoverPosition();
    const onScrollOrResize = () => updatePopoverPosition();
    window.addEventListener("resize", onScrollOrResize);
    document.addEventListener("scroll", onScrollOrResize, true);
    return () => {
      window.removeEventListener("resize", onScrollOrResize);
      document.removeEventListener("scroll", onScrollOrResize, true);
    };
  }, [open, updatePopoverPosition]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
      }
    };
    const onPointerDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (triggerRef.current?.contains(t) || popoverRef.current?.contains(t)) {
        return;
      }
      setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointerDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointerDown);
    };
  }, [open]);

  useLayoutEffect(() => {
    if (!open || !streaming) {
      return;
    }
    const el = popoverRef.current;
    if (!el) {
      return;
    }
    el.scrollTop = el.scrollHeight;
  }, [clean, streaming, open]);

  /**
   * Same shimmer as {@link AgentEarlyThinkingIndicator} so there is no blank beat after the
   * live assistant row mounts but before the first reasoning character.
   */
  if (!text.trim() && !clean) {
    if (streaming) {
      return <AgentEarlyThinkingIndicator />;
    }
    return null;
  }

  const thinkingLabelClass = streaming
    ? REASONING_THINKING_SHIMMER_LABEL_CLASS
    : "text-[11px] font-medium text-tertiary";

  const bodyClass =
    "font-sans text-[12px] leading-relaxed break-words whitespace-pre-wrap text-secondary";

  const popoverContent =
    open && popoverBox ? (
      <div
        ref={popoverRef}
        id={popoverId}
        role="dialog"
        aria-label={
          streaming ? "Reasoning in progress" : "Completed reasoning"
        }
        className={`fixed z-[100] max-h-[min(70vh,20rem)] overflow-y-auto rounded-lg border border-[var(--color-border)] bg-[var(--color-background)] p-3 shadow-lg outline-none ring-1 ring-black/5 dark:ring-white/10 ${bodyClass}`}
        style={{
          top: popoverBox.top,
          left: popoverBox.left,
          width: popoverBox.width,
        }}
        tabIndex={-1}
        aria-live="polite"
        onPointerEnter={cancelScheduledPopoverClose}
        onPointerLeave={schedulePopoverCloseAfterLeave}
      >
        {clean || (streaming ? "\u200b" : null)}
        {streaming ? (
          <span
            className="ml-px inline-block h-[0.9em] w-px animate-pulse bg-foreground/35 align-middle"
            aria-hidden
          />
        ) : null}
      </div>
    ) : null;

  return (
    <>
      <div ref={columnRef} className={`${AGENT_CHAT_COLUMN_CLASS} font-sans`}>
        <button
          ref={triggerRef}
          type="button"
          className="inline-flex max-w-full cursor-pointer items-center gap-1.5 rounded-md p-0 text-left rtl:text-right focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-accent)]"
          aria-expanded={open}
          aria-haspopup="dialog"
          aria-controls={open ? popoverId : undefined}
          onPointerEnter={() => {
            cancelScheduledPopoverClose();
            setOpen(true);
          }}
          onPointerLeave={schedulePopoverCloseAfterLeave}
          onFocus={() => {
            cancelScheduledPopoverClose();
            setOpen(true);
          }}
          onClick={() => setOpen((v) => !v)}
        >
          <span className={thinkingLabelClass} aria-live="polite">
            {streaming ? "Thinking" : "Thought"}
          </span>
        </button>
      </div>
      {typeof document !== "undefined" && popoverContent
        ? createPortal(popoverContent, document.body)
        : null}
    </>
  );
}

/** Shared shell for `streamPhase === "model"`: reasoning stream vs content bubble (no mislabeled “Thinking”). */
function AssistantModelStreamShell({
  streamText,
  streamTextRole,
  replyBubbleClass,
  bodyClassName,
  emptyLabel,
  streaming = true,
}: {
  streamText: string;
  streamTextRole: "content" | "reasoning" | "mixed" | undefined;
  replyBubbleClass: string;
  /** Optional override for the streaming markdown wrapper (defaults to ``replyBubbleClass``). */
  bodyClassName?: string;
  emptyLabel: string;
  /** When false, no typing caret (e.g. stream finalized on wire but flag not yet cleared). */
  streaming?: boolean;
}) {
  const hasStreamText = streamText.trim().length > 0;
  if (streamTextRole === "reasoning") {
    return <ReasoningStreamPeek text={streamText} streaming={streaming} />;
  }
  if (!hasStreamText) {
    if (!streaming) {
      return null;
    }
    return <AgentEarlyThinkingIndicator />;
  }
  const bodyClass = bodyClassName ?? replyBubbleClass;
  return (
    <div className={AGENT_CHAT_COLUMN_CLASS}>
      <div className={bodyClass}>
        <AssistantMarkdown source={streamText} />
        {streaming ? (
          <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-[var(--color-accent)] align-middle" />
        ) : null}
      </div>
    </div>
  );
}

/** Renders ``streamSegments`` from NDJSON ``segment_start`` + deltas (llm-markdown agentic contract). */
function AssistantSegmentedBody({
  segments,
  streaming,
  replyBubbleClass,
  contentBubbleClass,
  emptyLabel,
  assistantUiLane,
}: {
  segments: AssistantStreamSegment[];
  streaming: boolean;
  replyBubbleClass: string;
  /** CSS class for ``content`` segments; defaults to ``replyBubbleClass``. */
  contentBubbleClass?: string;
  emptyLabel: string;
  /** Finalized lane: when ``reply`` and segments are reasoning-only, render as chat bubble (not peek). */
  assistantUiLane: "thinking" | "reply";
}) {
  const contentClass = contentBubbleClass ?? replyBubbleClass;
  const merged = mergeAdjacentContentSegments(
    mergeAdjacentReasoningSegments(segments),
  );
  const onlyReasoning =
    merged.length > 0 && merged.every((s) => s.kind === "reasoning");
  const reasoningAsReplyBubble =
    onlyReasoning && assistantUiLane === "reply" && !streaming;
  return (
    <div className={`${AGENT_CHAT_COLUMN_CLASS} space-y-3`}>
      {merged.map((s, i) => {
        const isLast = i === merged.length - 1;
        const pulse = streaming && isLast;
        if (s.kind === "reasoning") {
          if (reasoningAsReplyBubble) {
            return (
              <div key={`seg-r-${i}`} className={contentClass}>
                <AssistantMarkdown source={s.text} />
                {pulse ? (
                  <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-[var(--color-accent)] align-middle" />
                ) : null}
              </div>
            );
          }
          if (!s.text.trim()) {
            return pulse ? (
              <AgentEarlyThinkingIndicator key={`seg-r-${i}`} />
            ) : null;
          }
          return (
            <ReasoningStreamPeek
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
              className={`${AGENT_CHAT_COLUMN_CLASS} flex items-center gap-1.5 py-0.5`}
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
          <div key={`seg-c-${i}`} className={contentClass}>
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
    return null;
  }
  if (b.kind === "phase") {
    if (b.phase === "summary") {
      return null;
    }
    if (b.phase === "tools") {
      return null;
    }
    if (b.phase === "model") {
      return null;
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
    const streamActive = b.streaming && b.pendingStreamFinalize !== true;
    /** Summary often stays `streaming` on the wire until `assistant_done`; hide the caret once any text exists. */
    const streamCaretActive =
      streamActive &&
      !(isSummary && (anySegText || b.text.trim().length > 0));

    if (afterToolResult || isSummary) {
      if (streamActive) {
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
                streaming={streamCaretActive}
                replyBubbleClass={replyBubbleClass}
                contentBubbleClass={replyBubbleClass}
                assistantUiLane={lane}
                emptyLabel=""
              />
            );
          }
          if (!hasStreamText) {
            return (
              <div
                className={`${AGENT_CHAT_COLUMN_CLASS} flex items-center gap-1.5 py-0.5`}
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
              {streamCaretActive ? (
                <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-[var(--color-accent)] align-middle" />
              ) : null}
            </div>
          );
        }
        if (streamSegs) {
          return (
            <AssistantSegmentedBody
              segments={streamSegs}
              streaming={streamCaretActive}
              replyBubbleClass={replyBubbleClass}
              contentBubbleClass={replyBubbleClass}
              assistantUiLane={lane}
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
            streaming={streamCaretActive}
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
            contentBubbleClass={replyBubbleClass}
            assistantUiLane={lane}
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

    if (isModel && streamActive) {
      if (streamSegs) {
        return (
          <AssistantSegmentedBody
            segments={streamSegs}
            streaming={streamActive}
            replyBubbleClass={replyBubbleClass}
            contentBubbleClass={replyBubbleClass}
            assistantUiLane={lane}
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
          streaming={streamActive}
        />
      );
    }

    if (isModel && !b.streaming && lane === "thinking") {
      if (streamSegs) {
        if (!anySegText) {
          return (
            <div
              className={`${AGENT_CHAT_COLUMN_CLASS} border-l-2 border-border pl-3 text-[11px] leading-snug text-tertiary`}
            >
              No visible plan text before tools (normal for many models). See
              tool steps below.
            </div>
          );
        }
        return (
          <AssistantSegmentedBody
            segments={streamSegs}
            streaming={false}
            replyBubbleClass={replyBubbleClass}
            contentBubbleClass={replyBubbleClass}
            assistantUiLane={lane}
            emptyLabel=""
          />
        );
      }
      const t = b.text.trim();
      if (!t) {
        return (
          <div
            className={`${AGENT_CHAT_COLUMN_CLASS} border-l-2 border-border pl-3 text-[11px] leading-snug text-tertiary`}
          >
            No visible plan text before tools (normal for many models). See tool
            steps below.
          </div>
        );
      }
      return <ReasoningStreamPeek text={b.text} streaming={false} />;
    }

    if (isModel && !b.streaming && lane === "reply") {
      if (streamSegs && anySegText) {
        return (
          <AssistantSegmentedBody
            segments={streamSegs}
            streaming={false}
            replyBubbleClass={replyBubbleClass}
            contentBubbleClass={replyBubbleClass}
            assistantUiLane={lane}
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
            contentBubbleClass={replyBubbleClass}
            assistantUiLane={lane}
            emptyLabel=""
          />
        );
      }
      return <ReasoningStreamPeek text={b.text} streaming={false} />;
    }

    if (streamActive) {
      if (streamSegs) {
        return (
          <AssistantSegmentedBody
            segments={streamSegs}
            streaming={streamActive}
            replyBubbleClass={replyBubbleClass}
            contentBubbleClass={replyBubbleClass}
            assistantUiLane={lane}
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
          streaming={streamActive}
        />
      );
    }

    if (streamSegs && anySegText) {
      return (
        <AssistantSegmentedBody
          segments={streamSegs}
          streaming={false}
          replyBubbleClass={replyBubbleClass}
          contentBubbleClass={replyBubbleClass}
          assistantUiLane={lane}
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
    return (
      <div className={`${AGENT_CHAT_COLUMN_CLASS}`}>
        <div className="rounded-lg border border-border bg-surface/40 px-3 py-2.5 text-[12px] leading-snug">
          <span className="font-medium text-foreground">{title}</span>
        </div>
      </div>
    );
  }
  if (b.kind === "tool_result") {
    const title = humanizeToolName(b.name);
    return (
      <div
        className={`${AGENT_CHAT_COLUMN_CLASS} flex gap-2.5 pl-0.5 text-[12px] leading-snug`}
      >
        <span
          className="mt-1.5 size-1.5 shrink-0 rounded-full bg-[var(--color-accent)] opacity-70"
          aria-hidden
        />
        <div className="min-w-0 flex-1">
          <span className="font-medium text-foreground">{title}</span>
          <div className="mt-1.5">
            <ToolResultStatusStrip result={b} />
          </div>
          <div className="mt-1">
            <div className={TOOL_SECTION_LABEL_CLASS}>Output · result</div>
            {b.data !== undefined ? (
              <div className="mt-1 rounded-lg border border-border/60 bg-background/80 px-2 py-2">
                <FunctionResultDisplay value={b.data} />
              </div>
            ) : (
              <p className="whitespace-pre-wrap font-mono text-[11px] leading-snug text-secondary">
                {b.summary}
              </p>
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
      <div
        className={`${AGENT_CHAT_COLUMN_CLASS} rounded-xl border border-[color:color-mix(in_srgb,var(--color-accent)_35%,var(--color-border))] bg-[color:color-mix(in_srgb,var(--color-accent)_6%,transparent)] px-3 py-2.5 text-[12px] leading-snug`}
      >
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
