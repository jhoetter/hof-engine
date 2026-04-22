"use client";

import {
  AlertCircle,
  Ban,
  CheckCircle2,
  Clock,
  Loader2,
  XCircle,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { HOF_REACT_I18N_OPTS } from "../reactI18nextStableOpts";

/**
 * Reasoning popovers must portal here (not directly under `document.body`) so their z-index
 * competes with the composer inside the same root; otherwise `fixed` + high z on a body child
 * paints above the entire React app.
 */
function getAgentUiPortalRoot(): HTMLElement {
  return (
    document.getElementById("root") ??
    document.getElementById("hof-root") ??
    document.getElementById("__next") ??
    document.body
  );
}
import { AssistantMarkdown } from "./AssistantMarkdown";
import {
  AssistantMarkdownTableProvider,
  type AssistantMarkdownTableRenderer,
} from "./assistantMarkdownTableContext";
import {
  FunctionResultDisplay,
  TERMINAL_SESSION_INSET,
  TERMINAL_STDOUT_SURFACE_CLASS,
} from "./FunctionResultDisplay";
import { parseTerminalExecPayload } from "./terminalExecPayload";
import {
  AGENT_CHAT_COLUMN_CLASS,
  CHAT_ASSISTANT_REPLY_BUBBLE_CLASS,
  HOF_BUILTIN_TERMINAL_EXEC,
  assistantUiRole,
  barrierMatchesApprovalBlock,
  confirmationFooterIconsFromOutcomes,
  type ConfirmationFooterIconKind,
  dropRedundantModelPhaseBeforeAssistant,
  humanizeToolName,
  inferAssistantUiLane,
  toolCallRowTitle,
  isGenericAwaitingConfirmationSummary,
  postToolAssistantBlockIds,
  postToolAssistantToolInfo,
  type PostToolInfo,
  segmentLiveBlocks,
  showProposedActionsLabel,
  toolCallCliLine,
  toolGroupAggregatedStatus,
  mergeAdjacentContentSegments,
  mergeAdjacentReasoningSegments,
  normalizeAgentCliDisplayLine,
  type BlockSegment,
} from "./hofAgentChatModel";
import { TerminalInvocationHighlight } from "./terminalCommandHighlight";
import { reasoningPhaseTickingLive } from "./assistantStreamSegments";
import { useHofAgentChat } from "./hofAgentChatContext";
import type {
  ApprovalBarrier,
  AssistantStreamSegment,
  LiveBlock,
  MutationAppliedBlock,
  MutationPendingBlock,
  ToolCallBlock,
  ToolResultBlock,
} from "./hofAgentChatModel";

/** Context for optional action buttons rendered alongside a tool result. */
export type ToolResultActionsContext = {
  call?: { name: string; arguments?: Record<string, unknown> };
  result: { data?: unknown; summary?: string; name?: string };
};

export type ToolResultActionsRenderer = (
  ctx: ToolResultActionsContext,
) => ReactNode;

/** Context for replacing default {@link FunctionResultDisplay} for a tool result. */
export type ToolResultRendererContext = {
  name: string;
  data: unknown;
  call?: { arguments?: Record<string, unknown> };
};

export type ToolResultRendererFn = (
  ctx: ToolResultRendererContext,
) => ReactNode | null;

/**
 * Called for assistant blocks that follow a tool result.
 * Return a table renderer function to upgrade GFM pipe tables in markdown, or null.
 */
export type AfterToolTableRendererFn = (
  tool: {
    name: string;
    arguments?: Record<string, unknown>;
    resultData?: unknown;
  },
) => AssistantMarkdownTableRenderer | null;

function parsePostToolInfo(
  info: PostToolInfo,
): {
  name: string;
  arguments?: Record<string, unknown>;
  resultData?: unknown;
} {
  let args: Record<string, unknown> | undefined;
  if (info.arguments) {
    try {
      const parsed: unknown = JSON.parse(info.arguments);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        args = parsed as Record<string, unknown>;
      }
    } catch {
      // ignore
    }
  }
  return { name: info.name, arguments: args, resultData: info.resultData };
}

export function parseToolCallArguments(
  call: ToolCallBlock,
): Record<string, unknown> | undefined {
  const raw = call.arguments;
  if (!raw || typeof raw !== "string") {
    return undefined;
  }
  try {
    const parsed: unknown = JSON.parse(raw);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
  } catch {
    // ignore invalid JSON
  }
  return undefined;
}
import {
  formatDurationMs,
  useThinkingEpisodeElapsed,
} from "./thinkingDuration";
import { parseStructuredPlan } from "./planMarkdownTodos";
import {
  isLiveStreamLabel,
  isPlanCardLabel,
  isQuestionnaireLabel,
  settleLiveLabel,
} from "./planDiscoverStatusLabel";

/** Max height for inline terminal command/output in the tool card (scroll inside `<pre>`). */
const TERMINAL_INLINE_MAX_H = "max-h-[min(75vh,40rem)]";

/**
 * Prefer same-origin `path` when `url` points at another host (e.g. API default vs SPA dev server).
 */
function postApplyReviewHref(postApplyReview: {
  url?: string;
  path?: string;
}): { href: string; openInNewTab: boolean } {
  const p = postApplyReview.path?.trim() ?? "";
  const u = postApplyReview.url?.trim() ?? "";
  if (typeof window === "undefined") {
    const href = (u || p).trim();
    return { href, openInNewTab: /^https?:\/\//i.test(u) };
  }
  if (p.startsWith("/") && u) {
    try {
      const parsed = new URL(u);
      if (parsed.origin !== window.location.origin) {
        return { href: p, openInNewTab: false };
      }
    } catch {
      /* fall through */
    }
  }
  const href = (u || p).trim();
  if (!href) {
    return { href: "", openInNewTab: false };
  }
  try {
    const parsed = new URL(href, window.location.href);
    return {
      href,
      openInNewTab: parsed.origin !== window.location.origin,
    };
  } catch {
    return { href, openInNewTab: /^https?:\/\//i.test(href) };
  }
}

/**
 * Optional inbox hint (label + link) from `mutation_applied` / preview payloads.
 * The default assistant rail does not render this — the model usually includes the link in prose.
 * Export for custom shells that want a dedicated inbox row.
 */
export function PostApplyReviewHint({
  postApplyReview,
}: {
  postApplyReview: MutationAppliedBlock["post_apply_review"];
}) {
  const { t } = useTranslation("hofEngine", HOF_REACT_I18N_OPTS);
  const { label, url, path } = postApplyReview;
  const { href, openInNewTab } = postApplyReviewHref({ url, path });
  return (
    <div
      className="border-t border-border/60 px-3 py-2.5"
      role="status"
      aria-label={t("chatBlocks.postApplyReviewHintAria")}
    >
      <p className="text-[10px] font-medium uppercase tracking-wide text-tertiary">
        {t("chatBlocks.reviewInbox")}
      </p>
      <p className="mt-1 text-[11px] leading-snug text-secondary">
        {href ? (
          <a
            href={href}
            className="font-medium text-[var(--color-accent)] underline underline-offset-2 hover:opacity-90"
            target={openInNewTab ? "_blank" : undefined}
            rel={openInNewTab ? "noopener noreferrer" : undefined}
          >
            {label}
          </a>
        ) : (
          <span className="text-foreground">{label}</span>
        )}
      </p>
    </div>
  );
}


function TerminalToolCallInlineStandalone({ b }: { b: ToolCallBlock }) {
  const { t } = useTranslation("hofEngine", HOF_REACT_I18N_OPTS);
  const title = toolCallRowTitle(b);
  const terminalLine = toolCallCliLine(b).trim();
  return (
    <div className={AGENT_CHAT_COLUMN_CLASS}>
      <div className="rounded-lg border border-border bg-surface/40 px-3 py-2.5 text-[12px] leading-snug">
        <span className="block min-w-0 truncate font-medium text-foreground">
          {title}
        </span>
        {terminalLine ? (
          <div
            className="mt-2 overflow-hidden rounded-md border border-border/60 bg-surface/30"
            aria-label={t("chatBlocks.terminalCommandAria")}
          >
            <pre
              className={`${TERMINAL_INLINE_MAX_H} overflow-auto whitespace-pre-wrap break-all ${TERMINAL_SESSION_INSET}`}
            >
            <span className="text-tertiary select-none" aria-hidden>
                {"$ "}
              </span>
              <TerminalInvocationHighlight
                code={terminalLine}
                variant="inline"
                className="min-w-0 break-all"
              />
            </pre>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function TerminalToolResultInlineStandalone({
  b,
}: {
  b: ToolResultBlock & {
    data: { exit_code: number; output: string };
  };
}) {
  const { t } = useTranslation("hofEngine", HOF_REACT_I18N_OPTS);
  const d = b.data;
  return (
    <div className={AGENT_CHAT_COLUMN_CLASS}>
      <div className="rounded-lg border border-border bg-surface/40 px-3 py-2 text-[12px] leading-snug">
        <div
          className="overflow-hidden rounded-md border border-border/60 bg-surface/30"
          aria-label={t("chatBlocks.terminalOutputAria")}
        >
          <FunctionResultDisplay value={d} variant="terminalPlain" />
        </div>
      </div>
    </div>
  );
}

/** Terminal-style command row (`$` + line); outer shell reads as input without a visible section title. */
function ToolTerminalCommandRow({ cliLine }: { cliLine: string }) {
  const { t } = useTranslation("hofEngine", HOF_REACT_I18N_OPTS);
  const displayLine = cliLine.trim();

  return (
    <div
      className="overflow-hidden bg-surface/30"
      aria-label={t("chatBlocks.toolCommandAria")}
    >
      <div
        className={`flex w-full min-h-0 ${TERMINAL_INLINE_MAX_H} items-start overflow-hidden bg-[color:color-mix(in_srgb,var(--color-foreground)_2.5%,transparent)]`}
      >
        <div className="flex min-h-0 min-w-0 flex-1 items-start py-2 pl-3 pr-3">
          <span
            className="shrink-0 self-start pr-1 font-mono text-[11px] leading-snug text-tertiary select-none"
            aria-hidden
          >
            $
          </span>
          <pre className="min-h-0 min-w-0 max-w-full flex-1 overflow-auto whitespace-pre-wrap break-all py-0 font-mono text-[11px] leading-snug">
            <TerminalInvocationHighlight code={displayLine} />
          </pre>
        </div>
      </div>
    </div>
  );
}

/** Single glyph for tool lifecycle (replaces chevron + text badge on the card header). */
function ToolAggregatedStatusGlyph({
  result,
  busy,
  mutationOutcome,
}: {
  result: ToolResultBlock | undefined;
  busy: boolean;
  mutationOutcome?: boolean;
}) {
  const { label } = toolGroupAggregatedStatus(result, busy, mutationOutcome);
  const base = "size-4 shrink-0";
  const aria = `Tool status: ${label}`;
  switch (label) {
    case "running":
      return (
        <Loader2
          className={`${base} animate-spin text-[var(--color-accent)]`}
          aria-label={aria}
          strokeWidth={2}
        />
      );
    case "pending":
      return (
        <Clock
          className={`${base} text-[var(--color-accent)]`}
          aria-label={aria}
          strokeWidth={2}
        />
      );
    case "done":
      return (
        <CheckCircle2
          className={`${base} text-[var(--color-success)]`}
          aria-label={aria}
          strokeWidth={2}
        />
      );
    case "rejected":
      return (
        <Ban
          className={`${base} text-[var(--color-destructive)]`}
          aria-label={aria}
          strokeWidth={2}
        />
      );
    case "failed":
      return (
        <XCircle
          className={`${base} text-[var(--color-destructive)]`}
          aria-label={aria}
          strokeWidth={2}
        />
      );
    case "error":
      return (
        <AlertCircle
          className={`${base} text-[var(--color-destructive)]`}
          aria-label={aria}
          strokeWidth={2}
        />
      );
    default:
      return (
        <AlertCircle
          className={`${base} text-tertiary`}
          aria-label={aria}
          strokeWidth={2}
        />
      );
  }
}

function ConfirmationFooterGlyph({ kind }: { kind: ConfirmationFooterIconKind }) {
  const base = "size-4 shrink-0";
  switch (kind) {
    case "approved":
      return (
        <CheckCircle2
          className={`${base} text-[var(--color-success)]`}
          strokeWidth={2}
          aria-hidden
        />
      );
    case "rejected":
      return (
        <XCircle
          className={`${base} text-[var(--color-destructive)]`}
          strokeWidth={2}
          aria-hidden
        />
      );
    case "pending":
      return (
        <Clock
          className={`${base} text-[var(--color-accent)]`}
          strokeWidth={2}
          aria-hidden
        />
      );
  }
}

/** Labeled Approve / Reject on the tool card (matches PendingApprovalBar button styling). */
const INLINE_APPROVAL_CHOICE_BTN_CLASS =
  "inline-flex shrink-0 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-[12px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40";

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
  const { t } = useTranslation("hofEngine", HOF_REACT_I18N_OPTS);
  if (mutationOutcome === true || mutationOutcome === false) {
    return null;
  }
  if (!showApproval || approvalItemsForMutation.length === 0) {
    return null;
  }
  return (
    <div
      className="flex shrink-0 flex-col items-end gap-2"
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
      }}
    >
      {approvalItemsForMutation.map((it) => {
        const d = approvalDecisions[it.pendingId];
        return (
          <div
            key={it.pendingId}
            className="flex flex-wrap items-center justify-end gap-2"
          >
            <button
              type="button"
              disabled={busy}
              title={t("chatBlocks.approve")}
              aria-label={t("chatBlocks.approveNamed", { name: it.name })}
              className={`${INLINE_APPROVAL_CHOICE_BTN_CLASS} ${
                d === true
                  ? "bg-[var(--color-success-bg)] text-foreground"
                  : "bg-hover text-secondary hover:bg-hover/80"
              }`}
              onClick={() =>
                setApprovalDecisions((prev) => ({
                  ...prev,
                  [it.pendingId]: true,
                }))
              }
            >
              <CheckCircle2 className="size-4" strokeWidth={2} aria-hidden />
              {t("chatBlocks.approve")}
            </button>
            <button
              type="button"
              disabled={busy}
              title={t("chatBlocks.reject")}
              aria-label={t("chatBlocks.rejectNamed", { name: it.name })}
              className={`${INLINE_APPROVAL_CHOICE_BTN_CLASS} ${
                d === false
                  ? "bg-[var(--color-destructive-bg)] text-foreground"
                  : "bg-hover text-secondary hover:bg-hover/80"
              }`}
              onClick={() =>
                setApprovalDecisions((prev) => ({
                  ...prev,
                  [it.pendingId]: false,
                }))
              }
            >
              <XCircle className="size-4" strokeWidth={2} aria-hidden />
              {t("chatBlocks.reject")}
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
  anchorId,
  mutationOutcome,
  toolResultActions,
  toolResultRenderer,
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
  anchorId?: string;
  /** `true` approved, `false` rejected, `undefined` unknown / still pending */
  mutationOutcome?: boolean;
  toolResultActions?: ToolResultActionsRenderer;
  toolResultRenderer?: ToolResultRendererFn;
}) {
  const { t } = useTranslation("hofEngine", HOF_REACT_I18N_OPTS);
  const title = toolCallRowTitle(call);
  const line = toolCallCliLine(call);
  const hideGenericResult = Boolean(
    mutation && result && isGenericAwaitingConfirmationSummary(result.summary),
  );
  const showStructuredData = Boolean(result && result.data !== undefined);
  const showResultBlock = Boolean(
    result && (showStructuredData || !hideGenericResult),
  );
  /** Preview / summary inside the card (no placeholder copy while awaiting approval). */
  const showInnerBody = showResultBlock;
  const [detailsOpen, setDetailsOpen] = useState(false);
  useEffect(() => {
    if (showApproval && mutation) {
      setDetailsOpen(true);
    }
  }, [showApproval, mutation?.pending_id]);

  return (
    <div
      id={anchorId}
      className={`${AGENT_CHAT_COLUMN_CLASS} min-w-0 scroll-mt-4 space-y-2`}
    >
      <details
        open={detailsOpen}
        onToggle={(e) => setDetailsOpen(e.currentTarget.open)}
        className="group min-w-0 w-full max-w-full overflow-hidden rounded-lg border border-border bg-surface/40 [&_summary::-webkit-details-marker]:hidden"
      >
        <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2.5 px-3 py-2.5 text-[12px] leading-snug transition-colors hover:bg-hover/50">
          <ToolAggregatedStatusGlyph
            result={result}
            busy={busy}
            mutationOutcome={mutationOutcome}
          />
          <div className="min-w-0 flex-1">
            <span className="min-w-0 truncate font-medium text-foreground">
              {title}
            </span>
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
        <div className="min-w-0 max-w-full border-t border-border/60">
          <ToolTerminalCommandRow cliLine={line} />
          {showInnerBody && result ? (
            <>
              <div
                className={`min-w-0 max-w-full overflow-x-auto ${TERMINAL_STDOUT_SURFACE_CLASS}`}
                aria-label={t("chatBlocks.toolOutputAria")}
              >
                {(() => {
                  const parsedArgs = parseToolCallArguments(call);
                  const custom = toolResultRenderer?.({
                    name: result.name,
                    data: result.data,
                    call: { arguments: parsedArgs },
                  });
                  if (custom != null) {
                    return custom;
                  }
                  if (result.data !== undefined) {
                    return (
                      <FunctionResultDisplay
                        value={result.data}
                        variant="terminalPlain"
                      />
                    );
                  }
                  return (
                    <p
                      className={`whitespace-pre-wrap break-words text-secondary ${TERMINAL_SESSION_INSET}`}
                    >
                      {result.summary}
                    </p>
                  );
                })()}
              </div>
              {toolResultActions
                ? (() => {
                    const actions = toolResultActions({
                      call: {
                        name: call.name,
                        arguments: parseToolCallArguments(call),
                      },
                      result: {
                        data: result.data,
                        summary: result.summary,
                        name: result.name,
                      },
                    });
                    return actions ? (
                      <div className="border-t border-border/60 px-3 py-2">
                        {actions}
                      </div>
                    ) : null;
                  })()
                : null}
            </>
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
  omitItemMeta = false,
  embedCompact = false,
}: {
  items: { pendingId: string; name: string; cli_line: string }[];
  approvalDecisions: Record<string, boolean | null>;
  setApprovalDecisions: Dispatch<
    SetStateAction<Record<string, boolean | null>>
  >;
  busy: boolean;
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
    </div>
  );
}

function isCompactTerminalToolPair(
  segments: BlockSegment[],
  segIdx: number,
): boolean {
  if (segIdx === 0) {
    return false;
  }
  const cur = segments[segIdx];
  const prev = segments[segIdx - 1];
  if (!cur || !prev) {
    return false;
  }
  if (cur.type !== "single" || prev.type !== "single") {
    return false;
  }
  const c = cur.block;
  const p = prev.block;
  if (c.kind !== "tool_result" || p.kind !== "tool_call") {
    return false;
  }
  return (
    c.name === HOF_BUILTIN_TERMINAL_EXEC && p.name === HOF_BUILTIN_TERMINAL_EXEC
  );
}

export function RunBlocksList({
  blocks,
  barrier,
  approvalDecisions,
  setApprovalDecisions,
  busy,
  mutationOutcomeByPendingId,
  toolResultActions,
  toolResultRenderer,
  afterToolTableRenderer,
  silentToolNames,
}: {
  blocks: LiveBlock[];
  barrier: ApprovalBarrier | null;
  approvalDecisions: Record<string, boolean | null>;
  setApprovalDecisions: Dispatch<
    SetStateAction<Record<string, boolean | null>>
  >;
  busy: boolean;
  mutationOutcomeByPendingId: Record<string, boolean | undefined>;
  toolResultActions?: ToolResultActionsRenderer;
  toolResultRenderer?: ToolResultRendererFn;
  afterToolTableRenderer?: AfterToolTableRendererFn;
  /**
   * Tool wire names whose tool_call / tool_result cards should be
   * skipped at render time (mechanically necessary "wait/poll" calls
   * that would otherwise show a misleading loading banner). The model
   * still calls them; we just don't paint a card.
   */
  silentToolNames?: ReadonlySet<string>;
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

  const postToolAssistantIds = postToolAssistantBlockIds(blocks);
  const postToolInfoMap = afterToolTableRenderer
    ? postToolAssistantToolInfo(blocks)
    : null;

  return (
    <div className="space-y-3">
      {segments.map((seg, segIdx) => {
        if (seg.type === "tool_group") {
          if (silentToolNames?.has(seg.call.name)) {
            return null;
          }
          const pid = seg.mutation?.pending_id?.trim() ?? "";
          let showApproval = false;
          let approvalItemsForMutation: {
            pendingId: string;
            name: string;
            cli_line: string;
          }[] = [];
          if (
            barrier &&
            approvalBlock &&
            seg.mutation &&
            pid !== "" &&
            barrierMatchesApprovalBlock(
              barrier,
              approvalBlock.run_id,
              approvalBlock.pending_ids,
            )
          ) {
            const forPid = barrier.items.filter(
              (it) => it.pendingId.trim() === pid,
            );
            if (forPid.length > 0) {
              showApproval = true;
              approvalItemsForMutation = forPid.map((it) => ({
                pendingId: it.pendingId,
                name: it.name,
                cli_line: it.cli_line,
              }));
            }
          }
          const anchorId = undefined;
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
                anchorId={anchorId}
                mutationOutcome={mutationOutcome}
                toolResultActions={toolResultActions}
                toolResultRenderer={toolResultRenderer}
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
          const footerIcons = confirmationFooterIconsFromOutcomes(
            b.pending_ids,
            mutationOutcomeByPendingId,
          );
          if (activeBarrier) {
            return null;
          }
          if (footerIcons.length === 0) {
            return null;
          }
          const ariaParts = footerIcons.map((k) =>
            k === "approved" ? "approved" : k === "rejected" ? "rejected" : "pending",
          );
          return (
            <div
              key={b.id}
              className="flex items-center gap-1.5"
              role="status"
              aria-label={`Confirmations: ${ariaParts.join(", ")}`}
            >
              {footerIcons.map((kind, i) => (
                <ConfirmationFooterGlyph key={`${b.id}-cf-${i}`} kind={kind} />
              ))}
            </div>
          );
        }
        if (b.kind === "inbox_review_required") {
          return null;
        }
        if (b.kind === "web_session") {
          return null;
        }
        if (
          (b.kind === "tool_call" || b.kind === "tool_result") &&
          silentToolNames?.has(b.name)
        ) {
          return null;
        }
        const precedingTool = postToolInfoMap?.get(b.id);
        const parsedToolInfo = precedingTool
          ? parsePostToolInfo(precedingTool)
          : null;
        const blockTableRenderer =
          b.kind === "assistant" &&
          parsedToolInfo &&
          afterToolTableRenderer
            ? afterToolTableRenderer(parsedToolInfo)
            : null;
        const blockView = (
          <LiveBlockView
            b={b}
            afterToolResult={postToolAssistantIds.has(b.id)}
            busy={busy}
            toolResultActions={toolResultActions}
            toolResultRenderer={toolResultRenderer}
          />
        );
        return (
          <div
            key={b.id}
            className={
              isCompactTerminalToolPair(segments, segIdx) ? "!mt-1" : undefined
            }
          >
            {blockTableRenderer ? (
              <AssistantMarkdownTableProvider renderer={blockTableRenderer}>
                {blockView}
              </AssistantMarkdownTableProvider>
            ) : (
              blockView
            )}
          </div>
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

/**
 * When the model streams prose on the **content** channel (no ``reasoning_delta``), the popover
 * can still show the opening of the reply — usually lines before the first markdown table.
 */
function popoverMarkdownFromConsolidatedReply(markdown: string): string {
  const raw = markdown.trim();
  if (!raw) {
    return "";
  }
  const lines = raw.split("\n");
  const kept: string[] = [];
  for (const line of lines) {
    if (line.trimStart().startsWith("|")) {
      break;
    }
    kept.push(line);
    if (kept.join("\n").length >= 6000) {
      break;
    }
  }
  let slice = kept.join("\n").trim();
  if (!slice) {
    slice = raw.length > 4000 ? `${raw.slice(0, 4000)}…` : raw;
  }
  return slice;
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

export type AgentEarlyThinkingIndicatorProps = {
  /**
   * When set, shown as the live duration (parent owns {@link useThinkingEpisodeElapsed}).
   * Omit to compute elapsed locally from {@link HofAgentChatContext}.
   */
  liveFormatted?: string | null;
  /**
   * Frozen duration after the episode ends (parent-owned); shown when {@link liveFormatted} is null.
   */
  settledFormatted?: string | null;
  /** Shimmer label (default ``Thinking``). Use e.g. ``Preparing plan`` during plan draft. */
  label?: string;
};

/**
 * Shown while the agent run is busy but no live blocks exist yet (before first NDJSON row).
 * Replaces the old “Connecting” copy with the same visual “Thinking” treatment.
 */
export function AgentEarlyThinkingIndicator({
  liveFormatted: liveFormattedFromParent,
  settledFormatted: settledFormattedFromParent,
  label: labelProp,
}: AgentEarlyThinkingIndicatorProps = {}) {
  const { t } = useTranslation("hofEngine", HOF_REACT_I18N_OPTS);
  const label = labelProp ?? t("thinking.thinking");
  useEffect(() => {
    ensureReasoningShimmerKeyframes();
  }, []);
  const { thinkingEpisodeStartedAtMs } = useHofAgentChat();
  const useInternalElapsed =
    liveFormattedFromParent === undefined &&
    settledFormattedFromParent === undefined;
  const internalElapsed = useThinkingEpisodeElapsed(
    useInternalElapsed,
    thinkingEpisodeStartedAtMs,
    t,
  );
  const liveFormatted = useInternalElapsed
    ? internalElapsed.liveFormatted
    : liveFormattedFromParent;
  const settledFormatted = useInternalElapsed
    ? internalElapsed.settledFormatted
    : settledFormattedFromParent;
  const durationFormatted = liveFormatted ?? settledFormatted ?? null;
  const settledOnly = liveFormatted == null && settledFormatted != null;
  const ariaThinking =
    durationFormatted != null ? `${label} (${durationFormatted})` : label;
  return (
    <div
      className={`${AGENT_CHAT_COLUMN_CLASS} font-sans`}
      aria-busy="true"
      aria-live="polite"
      aria-label={ariaThinking}
    >
      <span
        className={
          settledOnly
            ? "text-[11px] font-medium text-tertiary"
            : REASONING_THINKING_SHIMMER_LABEL_CLASS
        }
      >
        {label}
      </span>
      {durationFormatted != null ? (
        <span className="text-[11px] font-medium text-tertiary">
          {" "}
          ({durationFormatted})
        </span>
      ) : null}
    </div>
  );
}

function ReasoningStreamPeek({
  text,
  streaming,
  reasoningElapsedMs,
  consolidatedContentForPopover,
  reasoningLabel: reasoningLabelProp,
  assistantStreamOpen = false,
}: {
  text: string;
  streaming: boolean;
  /** From persisted assistant block after ``assistant_done`` (survives flush to thread). */
  reasoningElapsedMs?: number;
  /**
   * Empty reasoning segment + content on the wire: same markdown as the following reply so the
   * popover can show the model output (often streamed as ``assistant_delta`` only).
   */
  consolidatedContentForPopover?: string;
  /** Stamped label from the block (persists after flush). Overrides default "Thought" for settled rows. */
  reasoningLabel?: string;
  /**
   * True while the parent assistant HTTP stream is still open. When reasoning is no longer
   * “live” but the block is not finalized yet, fall back to context ``streamingReasoningLabel``
   * so plan-discover rows do not flash “Thought” before ``assistant_done`` stamps the block.
   */
  assistantStreamOpen?: boolean;
}) {
  const { t } = useTranslation("hofEngine", HOF_REACT_I18N_OPTS);
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
  const { thinkingEpisodeStartedAtMs, streamingReasoningLabel, agentMode, busy } =
    useHofAgentChat();
  /** Plan-discover copy is owned by {@link AgentEarlyThinkingIndicator} via {@link HofAgentMessages}; peek stays generic in plan mode. */
  const peekPlanDiscoverLabel =
    agentMode === "plan" ? null : streamingReasoningLabel;
  const { liveFormatted, settledFormatted } = useThinkingEpisodeElapsed(
    streaming,
    thinkingEpisodeStartedAtMs,
    t,
  );
  const persistedFormatted =
    reasoningElapsedMs != null ? formatDurationMs(reasoningElapsedMs, t) : null;
  const effectiveSettled = persistedFormatted ?? settledFormatted;

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
  }, [clean, text, streaming, open]);

  /** Shimmer “Thinking” label matches {@link AgentEarlyThinkingIndicator} (used where no popover is needed). */
  if (!text.trim() && !clean) {
    if (!streaming) {
      const allowEmptyReasoningRow =
        reasoningElapsedMs != null ||
        thinkingEpisodeStartedAtMs != null ||
        Boolean(consolidatedContentForPopover?.trim());
      if (!allowEmptyReasoningRow) {
        return null;
      }
    } else if (
      agentMode === "plan" &&
      busy &&
      !consolidatedContentForPopover?.trim()
    ) {
      /** Plan mode: {@link HofAgentMessages} owns live discover labels; drop duplicate “Thinking” rows. */
      return null;
    }
    // Streaming + empty (instant mode): keep button + popover (live text appears as tokens arrive).
  }

  /** Empty primary reasoning text: duration row and/or consolidated reply popover. */
  const primaryEmptyReasoning = !streaming && !text.trim();
  const consolidatedPopoverMd =
    primaryEmptyReasoning && consolidatedContentForPopover?.trim()
      ? popoverMarkdownFromConsolidatedReply(consolidatedContentForPopover)
      : "";

  /** Prefer sanitized text; while streaming, raw ``text`` if sanitizer cleared partial output. */
  const streamingPopoverMarkdown =
    !primaryEmptyReasoning && streaming
      ? clean.trim()
        ? clean
        : text.trim()
      : "";
  const settledPopoverMarkdown =
    !primaryEmptyReasoning && !streaming
      ? clean.trim() || text.trim()
      : "";

  const thinkingLabelClass = streaming
    ? REASONING_THINKING_SHIMMER_LABEL_CLASS
    : "text-[11px] font-medium text-tertiary";

  /** Plan mode: always “Thinking” in the reasoning lane; status lives on {@link HofAgentMessages}. */
  const streamingThinkingWord =
    peekPlanDiscoverLabel ?? t("thinking.thinking");

  const stampedTrimmed = reasoningLabelProp?.trim();
  const stampForPlanDiscoverChecks = stampedTrimmed ?? "";
  const stampedIsPlanDiscover =
    stampForPlanDiscoverChecks.length > 0 &&
    (isQuestionnaireLabel(stampForPlanDiscoverChecks, t) ||
      isPlanCardLabel(stampForPlanDiscoverChecks, t) ||
      isLiveStreamLabel(stampForPlanDiscoverChecks, t));

  const settledButtonLabel =
    agentMode === "plan"
      ? stampedTrimmed && !stampedIsPlanDiscover
        ? settleLiveLabel(stampedTrimmed, t)
        : t("thinking.thought")
      : stampedTrimmed
        ? settleLiveLabel(stampedTrimmed, t)
        : assistantStreamOpen && peekPlanDiscoverLabel
          ? settleLiveLabel(peekPlanDiscoverLabel, t)
          : t("thinking.thought");

  const bodyClass =
    "font-sans text-[12px] leading-relaxed break-words whitespace-pre-wrap text-secondary";

  const popoverReasoningAria = streaming
    ? liveFormatted != null
      ? t("thinking.inProgressWithDuration", {
          label: streamingThinkingWord,
          duration: liveFormatted,
        })
      : t("thinking.inProgress", { label: streamingThinkingWord })
    : effectiveSettled != null
      ? t("thinking.completedReasoningAfter", {
          duration: effectiveSettled,
        })
      : t("thinking.completedReasoning");

  const popoverContent =
    open && popoverBox ? (
      <div
        ref={popoverRef}
        id={popoverId}
        role="dialog"
        aria-label={popoverReasoningAria}
        className={`fixed z-[40] max-h-[min(70vh,20rem)] overflow-y-auto rounded-lg border border-[var(--color-border)] bg-[var(--color-background)] p-3 shadow-lg outline-none ring-1 ring-black/5 dark:ring-white/10 ${bodyClass}`}
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
        {primaryEmptyReasoning ? (
          consolidatedPopoverMd.trim() ? (
            <AssistantMarkdown source={consolidatedPopoverMd} />
          ) : consolidatedContentForPopover?.trim() ? (
            <AssistantMarkdown source={consolidatedContentForPopover.trim()} />
          ) : effectiveSettled != null ? (
            <p className="text-[12px] text-secondary">
              {t("thinking.separateReasoningPhase", {
                duration: effectiveSettled,
              })}
            </p>
          ) : null
        ) : streaming ? (
          streamingPopoverMarkdown ? (
            <AssistantMarkdown source={streamingPopoverMarkdown} />
          ) : (
            <>
              {liveFormatted != null ? (
                <p className="text-[11px] text-tertiary">
                  {streamingThinkingWord} ({liveFormatted})
                </p>
              ) : (
                <p className="text-[11px] text-tertiary">
                  {streamingThinkingWord}…
                </p>
              )}
              {"\u200b"}
            </>
          )
        ) : settledPopoverMarkdown ? (
          <AssistantMarkdown source={settledPopoverMarkdown} />
        ) : null}
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
          <span
            className="inline-flex max-w-full flex-wrap items-baseline gap-x-1"
            aria-live="polite"
          >
            {streaming ? (
              <>
                <span className={thinkingLabelClass}>
                  {streamingThinkingWord}
                </span>
                {liveFormatted != null ? (
                  <span className="text-[11px] font-medium text-tertiary">
                    ({liveFormatted})
                  </span>
                ) : null}
              </>
            ) : (
              <>
                <span className={thinkingLabelClass}>
                  {settledButtonLabel}
                </span>
                {effectiveSettled != null ? (
                  <span className="text-[11px] font-medium text-tertiary">
                    {t("thinking.durationConnector", {
                      duration: effectiveSettled,
                    })}
                  </span>
                ) : null}
              </>
            )}
          </span>
        </button>
      </div>
      {typeof document !== "undefined" && popoverContent
        ? createPortal(popoverContent, getAgentUiPortalRoot())
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
  wireStreaming = true,
  caretVisible,
  reasoningElapsedMs,
  reasoningLabel,
}: {
  streamText: string;
  streamTextRole: "content" | "reasoning" | "mixed" | undefined;
  replyBubbleClass: string;
  /** Optional override for the streaming markdown wrapper (defaults to ``replyBubbleClass``). */
  bodyClassName?: string;
  emptyLabel: string;
  /** HTTP stream still open (Thinking / live reasoning). */
  wireStreaming?: boolean;
  /** Typing caret in content bubble; defaults to ``wireStreaming``. */
  caretVisible?: boolean;
  reasoningElapsedMs?: number;
  reasoningLabel?: string;
}) {
  const showCaret = caretVisible ?? wireStreaming;
  const hasStreamText = streamText.trim().length > 0;
  if (streamTextRole === "reasoning") {
    return (
      <ReasoningStreamPeek
        text={streamText}
        streaming={wireStreaming}
        reasoningElapsedMs={reasoningElapsedMs}
        reasoningLabel={reasoningLabel}
        assistantStreamOpen={wireStreaming}
      />
    );
  }
  if (!hasStreamText) {
    if (!wireStreaming) {
      return null;
    }
    return (
      <ReasoningStreamPeek
        text=""
        streaming={true}
        reasoningElapsedMs={reasoningElapsedMs}
        reasoningLabel={reasoningLabel}
        assistantStreamOpen={wireStreaming}
      />
    );
  }
  const bodyClass = bodyClassName ?? replyBubbleClass;
  return (
    <div className={AGENT_CHAT_COLUMN_CLASS}>
      <div className={bodyClass}>
        <AssistantMarkdown source={streamText} />
        {showCaret ? (
          <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-[var(--color-accent)] align-middle" />
        ) : null}
      </div>
    </div>
  );
}

/** Renders ``streamSegments`` from NDJSON ``segment_start`` + deltas (llm-markdown agentic contract). */
function AssistantSegmentedBody({
  segments,
  wireStreaming,
  caretVisible,
  replyBubbleClass,
  contentBubbleClass,
  emptyLabel,
  assistantUiLane,
  persistedReasoningElapsedMs,
  afterToolResult,
  reasoningLabel,
}: {
  segments: AssistantStreamSegment[];
  /** HTTP stream still open (Thinking label, live reasoning). */
  wireStreaming: boolean;
  /** Caret on the last content segment; defaults to ``wireStreaming``. Summary round hides caret once text exists while wire stays open. */
  caretVisible?: boolean;
  replyBubbleClass: string;
  /** CSS class for ``content`` segments; defaults to ``replyBubbleClass``. */
  contentBubbleClass?: string;
  emptyLabel: string;
  /** Finalized lane: when ``reply`` and segments are reasoning-only, render as chat bubble (not peek). */
  assistantUiLane: "thinking" | "reply";
  /** Shown on the last reasoning peek after ``assistant_done`` (thread / persisted). */
  persistedReasoningElapsedMs?: number;
  /**
   * When true (assistant row after tool output), keep reasoning in {@link ReasoningStreamPeek}
   * so later model rounds still show “Thought for …” like the first turn.
   */
  afterToolResult?: boolean;
  reasoningLabel?: string;
}) {
  const { t } = useTranslation("hofEngine", HOF_REACT_I18N_OPTS);
  const contentClass = contentBubbleClass ?? replyBubbleClass;
  const showCaret = caretVisible ?? wireStreaming;
  const merged = mergeAdjacentContentSegments(
    mergeAdjacentReasoningSegments(segments),
  );
  const onlyReasoning =
    merged.length > 0 && merged.every((s) => s.kind === "reasoning");
  const reasoningAsReplyBubble =
    onlyReasoning &&
    assistantUiLane === "reply" &&
    !wireStreaming &&
    !afterToolResult;
  const lastReasoningIndex = merged.reduce(
    (acc, seg, idx) => (seg.kind === "reasoning" ? idx : acc),
    -1,
  );

  const { thinkingEpisodeStartedAtMs } = useHofAgentChat();
  const reasoningPhaseEndedAtRef = useRef<number | null>(null);
  const reasoningPhaseWasLiveRef = useRef(false);
  const anyReasoningLive = merged.some((_, idx) =>
    reasoningPhaseTickingLive(merged, idx, lastReasoningIndex, wireStreaming),
  );
  if (anyReasoningLive) {
    reasoningPhaseWasLiveRef.current = true;
    reasoningPhaseEndedAtRef.current = null;
  } else if (
    reasoningPhaseWasLiveRef.current &&
    reasoningPhaseEndedAtRef.current == null
  ) {
    reasoningPhaseEndedAtRef.current = Date.now();
  }
  if (!wireStreaming) {
    reasoningPhaseWasLiveRef.current = false;
  }
  const capturedReasoningElapsedMs =
    reasoningPhaseEndedAtRef.current != null &&
    thinkingEpisodeStartedAtMs != null
      ? reasoningPhaseEndedAtRef.current - thinkingEpisodeStartedAtMs
      : undefined;

  const children: ReactNode[] = [];
  for (let i = 0; i < merged.length; i++) {
    const s = merged[i]!;
    const isLast = i === merged.length - 1;
    const reasoningTicking = reasoningPhaseTickingLive(
      merged,
      i,
      lastReasoningIndex,
      wireStreaming,
    );
    const reasoningPeekLive = s.kind === "reasoning" && reasoningTicking;
    const emptyReasoningPulse =
      s.kind === "reasoning" && reasoningTicking && !s.text.trim();

    if (s.kind === "reasoning") {
      if (reasoningAsReplyBubble) {
        children.push(
          <div key={`seg-r-${i}`} className={contentClass}>
            <AssistantMarkdown source={s.text} />
            {showCaret && isLast ? (
              <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-[var(--color-accent)] align-middle" />
            ) : null}
          </div>,
        );
        continue;
      }
      if (!s.text.trim()) {
        if (emptyReasoningPulse) {
          children.push(
            <ReasoningStreamPeek
              key={`seg-r-${i}`}
              text=""
              streaming={true}
              reasoningLabel={reasoningLabel}
              assistantStreamOpen={wireStreaming}
            />,
          );
          continue;
        }
        const nextEmptyReasoning = merged[i + 1];
        if (
          nextEmptyReasoning?.kind === "content" &&
          nextEmptyReasoning.text.trim()
        ) {
          const nextIsLast = i + 1 === merged.length - 1;
          const contentPulse = showCaret && nextIsLast;
          const elapsedForConsolidated = !wireStreaming
            ? persistedReasoningElapsedMs
            : capturedReasoningElapsedMs;
          children.push(
            <div key={`seg-rc-${i}`} className={contentClass}>
              <div className="mb-2">
                <ReasoningStreamPeek
                  text=""
                  streaming={false}
                  reasoningElapsedMs={elapsedForConsolidated}
                  consolidatedContentForPopover={nextEmptyReasoning.text}
                  reasoningLabel={reasoningLabel}
                  assistantStreamOpen={wireStreaming}
                />
              </div>
              <AssistantMarkdown source={nextEmptyReasoning.text} />
              {contentPulse ? (
                <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-[var(--color-accent)] align-middle" />
              ) : null}
            </div>,
          );
          i += 1;
          continue;
        }
        if (
          !wireStreaming &&
          i === lastReasoningIndex &&
          persistedReasoningElapsedMs != null
        ) {
          children.push(
            <ReasoningStreamPeek
              key={`seg-r-${i}`}
              text=""
              streaming={false}
              reasoningElapsedMs={persistedReasoningElapsedMs}
              reasoningLabel={reasoningLabel}
              assistantStreamOpen={wireStreaming}
            />,
          );
          continue;
        }
        continue;
      }
      const durationProp =
        !wireStreaming &&
        i === lastReasoningIndex &&
        persistedReasoningElapsedMs != null
          ? persistedReasoningElapsedMs
          : undefined;
      children.push(
        <ReasoningStreamPeek
          key={`seg-r-${i}`}
          text={s.text}
          streaming={reasoningPeekLive}
          reasoningElapsedMs={durationProp}
          reasoningLabel={reasoningLabel}
          assistantStreamOpen={wireStreaming}
        />,
      );
      continue;
    }

    const contentPulse = showCaret && isLast;
    if (!s.text.trim() && !contentPulse) {
      continue;
    }
    if (!s.text.trim() && contentPulse) {
      children.push(
        <div
          key={`seg-c-${i}`}
          className={`${AGENT_CHAT_COLUMN_CLASS} flex items-center py-0.5`}
          aria-busy="true"
          aria-label={emptyLabel || t("chatBlocks.assistantDraftingAria")}
        >
          <span className="inline-block h-4 w-0.5 animate-pulse bg-[var(--color-accent)] align-middle" />
        </div>,
      );
      continue;
    }
    children.push(
      <div key={`seg-c-${i}`} className={contentClass}>
        <AssistantMarkdown source={s.text} />
        {contentPulse ? (
          <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-[var(--color-accent)] align-middle" />
        ) : null}
      </div>,
    );
  }

  return (
    <div className={`${AGENT_CHAT_COLUMN_CLASS} space-y-3`}>{children}</div>
  );
}

/** Inline plan checklist completion — one tool-style badge per completed to-do (never one blob for many). */
function PlanStepProgressRow({
  block,
}: {
  block: Extract<LiveBlock, { kind: "plan_step_progress" }>;
}) {
  const { t } = useTranslation("hofEngine", HOF_REACT_I18N_OPTS);
  const { planText } = useHofAgentChat();
  const entries = useMemo(() => {
    const parsed = parseStructuredPlan(planText);
    return block.done_indices.map((idx) => {
      const todo = parsed.todos.find((x) => x.index === idx);
      return {
        idx,
        label:
          todo?.label.trim() ??
          t("chatBlocks.planStepFallback", { n: idx + 1 }),
      };
    });
  }, [planText, block.done_indices, t]);
  if (entries.length === 0) {
    return null;
  }
  return (
    <div
      className={`${AGENT_CHAT_COLUMN_CLASS} min-w-0 space-y-1.5 pl-1`}
      role="status"
      aria-live="polite"
    >
      {entries.map(({ idx, label }) => (
        <div
          key={`${block.id}-todo-${idx}`}
          className="flex min-w-0 items-center gap-2.5 rounded-lg border border-border bg-surface/40 px-3 py-2 text-[12px] leading-snug"
        >
          <CheckCircle2
            className="size-4 shrink-0 text-[var(--color-accent)]"
            strokeWidth={2}
            aria-hidden
          />
          <span className="min-w-0 flex-1 truncate font-medium text-secondary line-through">
            {label}
          </span>
        </div>
      ))}
    </div>
  );
}

export function LiveBlockView({
  b,
  afterToolResult = false,
  busy = false,
  toolResultActions,
  toolResultRenderer,
}: {
  b: LiveBlock;
  afterToolResult?: boolean;
  /**
   * When false, assistant rows never show the streaming caret — fixes stale `streaming: true`
   * on persisted thread blocks after the HTTP stream has already ended.
   */
  busy?: boolean;
  toolResultActions?: ToolResultActionsRenderer;
  toolResultRenderer?: ToolResultRendererFn;
}) {
  const { t } = useTranslation("hofEngine", HOF_REACT_I18N_OPTS);
  const { agentMode, planBuiltinLane, planClarificationBarrier } =
    useHofAgentChat();
  if (b.kind === "thinking_skeleton") {
    return null;
  }
  if (b.kind === "continuation_marker") {
    return null;
  }
  if (b.kind === "plan_step_progress") {
    return <PlanStepProgressRow block={b} />;
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
    const wireStreaming = b.streaming && b.pendingStreamFinalize !== true;
    /** Require an in-flight agent request so hydrated/persisted `streaming: true` does not stick a caret. */
    const streamActive = busy && wireStreaming;
    /** Summary often stays `streaming` on the wire until `assistant_done`; hide the caret once any text exists. */
    const suppressAssistCaretWhileClarifyBuiltin =
      agentMode === "plan" &&
      busy &&
      planBuiltinLane === "clarification" &&
      planClarificationBarrier == null;
    const streamCaretActive =
      streamActive &&
      !(isSummary && (anySegText || b.text.trim().length > 0)) &&
      !suppressAssistCaretWhileClarifyBuiltin;
    const persistedReasoningMs = b.reasoning_elapsed_ms;

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
                wireStreaming={streamActive}
                caretVisible={streamCaretActive}
                replyBubbleClass={replyBubbleClass}
                contentBubbleClass={replyBubbleClass}
                afterToolResult={afterToolResult}
                assistantUiLane={lane}
                emptyLabel=""
                reasoningLabel={b.reasoningLabel}
              />
            );
          }
          if (!hasStreamText) {
            return (
              <div
                className={`${AGENT_CHAT_COLUMN_CLASS} flex items-center py-0.5`}
                aria-busy="true"
                aria-label={t("chatBlocks.assistantDraftingAria")}
              >
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
              wireStreaming={streamActive}
              caretVisible={streamCaretActive}
              replyBubbleClass={replyBubbleClass}
              contentBubbleClass={replyBubbleClass}
              afterToolResult={afterToolResult}
              assistantUiLane={lane}
              emptyLabel={t("chatBlocks.draftingAnswer")}
              reasoningLabel={b.reasoningLabel}
            />
          );
        }
        return (
          <AssistantModelStreamShell
            streamText={streamText}
            streamTextRole={b.streamTextRole}
            replyBubbleClass={replyBubbleClass}
            emptyLabel={t("chatBlocks.draftingAnswer")}
            wireStreaming={streamActive}
            caretVisible={streamCaretActive}
            reasoningLabel={b.reasoningLabel}
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
            wireStreaming={false}
            replyBubbleClass={replyBubbleClass}
            contentBubbleClass={replyBubbleClass}
            afterToolResult={afterToolResult}
            assistantUiLane={lane}
            emptyLabel=""
            persistedReasoningElapsedMs={persistedReasoningMs}
            reasoningLabel={b.reasoningLabel}
          />
        );
      }
      const text = b.text.trim();
      if (!text) {
        return null;
      }
      if (
        afterToolResult &&
        b.streamPhase === "model" &&
        lane === "thinking" &&
        (b.streamTextRole === "reasoning" ||
          b.streamTextRole === "mixed" ||
          (b.streamTextRole === undefined && lane === "thinking"))
      ) {
        const sr = b.streamTextRole;
        return (
          <AssistantModelStreamShell
            streamText={b.text}
            streamTextRole={
              sr === "mixed" || sr === "reasoning" ? sr : "reasoning"
            }
            replyBubbleClass={replyBubbleClass}
            emptyLabel=""
            wireStreaming={false}
            caretVisible={false}
            reasoningElapsedMs={persistedReasoningMs}
            reasoningLabel={b.reasoningLabel}
          />
        );
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
            wireStreaming={streamActive}
            caretVisible={streamActive}
            replyBubbleClass={replyBubbleClass}
            contentBubbleClass={replyBubbleClass}
            afterToolResult={afterToolResult}
            assistantUiLane={lane}
            emptyLabel={t("chatBlocks.toolsBeforeReply")}
            reasoningLabel={b.reasoningLabel}
          />
        );
      }
      return (
        <AssistantModelStreamShell
          streamText={b.text}
          streamTextRole={b.streamTextRole}
          replyBubbleClass={replyBubbleClass}
          emptyLabel={t("chatBlocks.toolsBeforeReply")}
          wireStreaming={streamActive}
          caretVisible={streamActive}
          reasoningLabel={b.reasoningLabel}
        />
      );
    }

    if (isModel && !streamActive && lane === "thinking") {
      if (streamSegs) {
        if (!anySegText) {
          return null;
        }
        return (
          <AssistantSegmentedBody
            segments={streamSegs}
            wireStreaming={false}
            replyBubbleClass={replyBubbleClass}
            contentBubbleClass={replyBubbleClass}
            afterToolResult={afterToolResult}
            assistantUiLane={lane}
            emptyLabel=""
            persistedReasoningElapsedMs={persistedReasoningMs}
            reasoningLabel={b.reasoningLabel}
          />
        );
      }
      const t = b.text.trim();
      if (!t) {
        return null;
      }
      return (
        <ReasoningStreamPeek
          text={b.text}
          streaming={false}
          reasoningElapsedMs={persistedReasoningMs}
          reasoningLabel={b.reasoningLabel}
        />
      );
    }

    if (isModel && !streamActive && lane === "reply") {
      if (streamSegs && anySegText) {
        return (
          <AssistantSegmentedBody
            segments={streamSegs}
            wireStreaming={false}
            replyBubbleClass={replyBubbleClass}
            contentBubbleClass={replyBubbleClass}
            afterToolResult={afterToolResult}
            assistantUiLane={lane}
            emptyLabel=""
            persistedReasoningElapsedMs={persistedReasoningMs}
            reasoningLabel={b.reasoningLabel}
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
    if (role === "reasoning" && !streamActive) {
      if (streamSegs && anySegText) {
        return (
          <AssistantSegmentedBody
            segments={streamSegs}
            wireStreaming={false}
            replyBubbleClass={replyBubbleClass}
            contentBubbleClass={replyBubbleClass}
            afterToolResult={afterToolResult}
            assistantUiLane={lane}
            emptyLabel=""
            persistedReasoningElapsedMs={persistedReasoningMs}
            reasoningLabel={b.reasoningLabel}
          />
        );
      }
      return (
        <ReasoningStreamPeek
          text={b.text}
          streaming={false}
          reasoningElapsedMs={persistedReasoningMs}
          reasoningLabel={b.reasoningLabel}
        />
      );
    }

    if (streamActive) {
      if (streamSegs) {
        return (
          <AssistantSegmentedBody
            segments={streamSegs}
            wireStreaming={streamActive}
            caretVisible={streamCaretActive}
            replyBubbleClass={replyBubbleClass}
            contentBubbleClass={replyBubbleClass}
            afterToolResult={afterToolResult}
            assistantUiLane={lane}
            emptyLabel={t("chatBlocks.waitingForModel")}
            reasoningLabel={b.reasoningLabel}
          />
        );
      }
      return (
        <AssistantModelStreamShell
          streamText={b.text}
          streamTextRole={b.streamTextRole}
          replyBubbleClass={replyBubbleClass}
          emptyLabel={t("chatBlocks.waitingForModel")}
          wireStreaming={streamActive}
          caretVisible={streamCaretActive}
          reasoningLabel={b.reasoningLabel}
        />
      );
    }

    if (streamSegs && anySegText) {
      return (
        <AssistantSegmentedBody
          segments={streamSegs}
          wireStreaming={false}
          replyBubbleClass={replyBubbleClass}
          contentBubbleClass={replyBubbleClass}
          afterToolResult={afterToolResult}
          assistantUiLane={lane}
          emptyLabel=""
          persistedReasoningElapsedMs={persistedReasoningMs}
          reasoningLabel={b.reasoningLabel}
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
    if (b.name === HOF_BUILTIN_TERMINAL_EXEC) {
      return <TerminalToolCallInlineStandalone b={b} />;
    }
    const title = toolCallRowTitle(b);
    return (
      <div className={`${AGENT_CHAT_COLUMN_CLASS}`}>
        <div className="rounded-lg border border-border bg-surface/40 px-3 py-2.5 text-[12px] leading-snug">
          <span className="block min-w-0 truncate font-medium text-foreground">
            {title}
          </span>
        </div>
      </div>
    );
  }
  if (b.kind === "tool_result") {
    const termData =
      b.name === HOF_BUILTIN_TERMINAL_EXEC && b.data !== undefined
        ? parseTerminalExecPayload(b.data)
        : null;
    if (termData !== null) {
      return (
        <TerminalToolResultInlineStandalone
          b={
            {
              ...b,
              data: termData,
            } as ToolResultBlock & {
              data: { exit_code: number; output: string };
            }
          }
        />
      );
    }
    const title = humanizeToolName(b.name);
    const customOutput = toolResultRenderer?.({
      name: b.name,
      data: b.data,
      call: undefined,
    });
    const actionsNode = toolResultActions
      ? toolResultActions({
          call: undefined,
          result: {
            data: b.data,
            summary: b.summary,
            name: b.name,
          },
        })
      : null;
    return (
      <div
        className={`${AGENT_CHAT_COLUMN_CLASS} flex min-w-0 gap-2.5 pl-0.5 text-[12px] leading-snug`}
      >
        <span className="mt-0.5 shrink-0">
          <ToolAggregatedStatusGlyph result={b} busy={false} />
        </span>
        <div className="min-w-0 flex-1">
          <span className="font-medium text-foreground">{title}</span>
          <div
            className="mt-2 min-w-0 max-w-full overflow-x-auto"
            aria-label={t("chatBlocks.toolOutputAria")}
          >
            {customOutput != null ? (
              customOutput
            ) : b.data !== undefined ? (
              <FunctionResultDisplay
                value={b.data}
                variant="terminalPlain"
              />
            ) : (
              <p className="whitespace-pre-wrap break-words font-mono text-[11px] leading-snug text-secondary">
                {b.summary}
              </p>
            )}
          </div>
          {actionsNode ? (
            <div className="mt-2 border-t border-border/60 pt-2">{actionsNode}</div>
          ) : null}
        </div>
      </div>
    );
  }
  if (b.kind === "mutation_applied") {
    /* post_apply_review is surfaced in assistant prose; no separate inbox card */
    return null;
  }
  if (b.kind === "mutation_pending") {
    const title = humanizeToolName(b.name);
    const cmd = normalizeAgentCliDisplayLine(
      b.name,
      b.cli_line,
      b.arguments_preview,
    );
    return (
      <div
        className={`${AGENT_CHAT_COLUMN_CLASS} rounded-xl border border-[color:color-mix(in_srgb,var(--color-accent)_35%,var(--color-border))] bg-[color:color-mix(in_srgb,var(--color-accent)_6%,transparent)] px-3 py-2.5 text-[12px] leading-snug`}
      >
        <div className="font-medium text-foreground">
          {t("chatBlocks.mutationAwaiting", { title })}
        </div>
        {cmd ? (
          <div
            className="mt-2 overflow-hidden rounded-md border border-border/60 bg-surface/30"
            aria-label={t("chatBlocks.toolCommandLineAria")}
          >
            <pre
              className={`max-h-32 overflow-auto whitespace-pre-wrap break-all ${TERMINAL_SESSION_INSET} text-foreground`}
            >
              <span className="text-tertiary select-none" aria-hidden>
                {"$ "}
              </span>
              <TerminalInvocationHighlight
                code={cmd.trim()}
                variant="inline"
                className="min-w-0 break-all"
              />
            </pre>
          </div>
        ) : null}
      </div>
    );
  }
  if (b.kind === "approval_required") {
    return null;
  }
  if (b.kind === "inbox_review_required") {
    return null;
  }
  if (b.kind === "web_session_barrier") {
    return null;
  }
  if (b.kind === "web_session") {
    return null;
  }
  if (b.kind === "error") {
    const rate = b.errorCategory === "rate_limit";
    const title = rate
      ? t("chatBlocks.errorUsageLimit")
      : b.errorCategory === "server" || b.errorCategory === "overloaded"
        ? t("chatBlocks.errorServer")
        : b.errorCategory === "timeout"
          ? t("chatBlocks.errorTimeout")
          : b.errorCategory === "auth"
            ? t("chatBlocks.errorAuth")
            : b.errorCategory === "bad_request"
              ? t("chatBlocks.errorBadRequest")
              : t("chatBlocks.errorGeneric");
    return (
      <div className={`${AGENT_CHAT_COLUMN_CLASS}`}>
        <div
          role="alert"
          className="rounded-lg border border-[color:color-mix(in_srgb,var(--color-destructive)_25%,var(--color-border))] bg-[color:color-mix(in_srgb,var(--color-destructive)_6%,transparent)] px-3 py-2.5 text-[12px] leading-snug"
        >
          <div className="font-medium text-foreground">{title}</div>
          <p className="mt-1.5 text-secondary">{b.detail}</p>
        </div>
      </div>
    );
  }
  return null;
}
