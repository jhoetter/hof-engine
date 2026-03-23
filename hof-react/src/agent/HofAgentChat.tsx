"use client";

import {
  ChevronRight,
  FileText,
  Loader2,
  Paperclip,
  Terminal,
  X,
} from "lucide-react";
import {
  streamHofFunction,
  type HofStreamEvent,
} from "../hooks/streamHofFunction";
import { FunctionResultDisplay } from "./FunctionResultDisplay";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";

type AgentAttachment = {
  object_key: string;
  filename: string;
  content_type: string;
};

type LiveBlock =
  | { kind: "phase"; id: string; round: number; phase: string }
  | {
      kind: "assistant";
      id: string;
      text: string;
      streaming: boolean;
      finishReason?: string;
      /** From NDJSON `phase` before this segment: model round vs confirmation summary round. */
      streamPhase?: "model" | "summary";
      usage?: {
        prompt_tokens?: number;
        completion_tokens?: number;
        total_tokens?: number;
      };
    }
  | {
      kind: "tool_call";
      id: string;
      name: string;
      cli_line: string;
      arguments?: string;
      /** Short technical note from server for the expandable row (not chat prose). */
      internal_rationale?: string;
    }
  | {
      kind: "tool_result";
      id: string;
      name: string;
      summary: string;
      /** Parsed JSON tool return (``hof fn`` / TUI auto-style render). */
      data?: unknown;
    }
  | {
      kind: "mutation_pending";
      id: string;
      pending_id: string;
      name: string;
      cli_line: string;
      arguments_preview?: string;
    }
  | {
      kind: "approval_required";
      id: string;
      run_id: string;
      pending_ids: string[];
    }
  | { kind: "error"; id: string; detail: string };

type ThreadItem =
  | {
      kind: "user";
      id: string;
      content: string;
      attachments?: AgentAttachment[];
    }
  | { kind: "run"; id: string; blocks: LiveBlock[] };

function collectThreadAttachments(items: ThreadItem[]): AgentAttachment[] {
  const seen = new Set<string>();
  const out: AgentAttachment[] = [];
  for (const it of items) {
    if (it.kind !== "user" || !it.attachments?.length) {
      continue;
    }
    for (const a of it.attachments) {
      if (seen.has(a.object_key)) {
        continue;
      }
      seen.add(a.object_key);
      out.push(a);
    }
  }
  return out;
}

function newId(): string {
  return crypto.randomUUID();
}

/**
 * Chat bubbles use Tailwind theme radii from app.css `@theme` (`rounded-lg` → `--radius-lg` →
 * `--hof-radius-*` in the active design-system bundle). Avoid ad-hoc radii so tokens control shape.
 */
const CHAT_USER_BUBBLE_CLASS =
  "max-w-full rounded-lg bg-hover px-4 py-2.5 text-sm leading-relaxed text-foreground";
const CHAT_ASSISTANT_REPLY_BUBBLE_CLASS =
  "max-w-[min(100%,42rem)] rounded-lg bg-hover/70 px-4 py-2.5 text-sm leading-relaxed text-foreground";

const TOOL_SECTION_LABEL_CLASS =
  "mb-1 text-[10px] font-medium uppercase tracking-wide text-tertiary";

/** First name (or email local-part) for welcome line; falls back when profile is minimal. */
/** snake_case API name → readable label */
function humanizeToolName(name: string): string {
  const s = name.trim();
  if (!s) {
    return "Action";
  }
  return s
    .split("_")
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(" ");
}

/** Strip API-only attachment hints; optional auto “I’ve attached…” when chips show files. */
function userMessageDisplayText(
  content: string,
  hasAttachments: boolean,
): string {
  let s = content
    .replace(
      /\n\n\[Attached PDF:[\s\S]*? — keys are in the assistant context\.\]/g,
      "",
    )
    .trim();
  if (
    hasAttachments &&
    /^I've attached \d+ PDF receipts?\.$/i.test(s)
  ) {
    return "";
  }
  return s;
}

/** NDJSON may encode `run_id` as string or number; normalize for comparisons and resume. */
function coerceRunId(value: unknown): string {
  if (typeof value === "string") {
    return value.trim();
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  return "";
}

function toolResultAwaitingUserConfirmation(blocks: LiveBlock[]): boolean {
  return blocks.some(
    (b) =>
      b.kind === "tool_result" &&
      typeof b.summary === "string" &&
      /awaiting your confirmation/i.test(b.summary),
  );
}

/** Pending ids from mutation trace blocks (used if stream omits `pending_ids` on `awaiting_confirmation`). */
function mutationPendingIdsFromBlocks(blocks: LiveBlock[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const b of blocks) {
    if (b.kind !== "mutation_pending") {
      continue;
    }
    const id = b.pending_id?.trim();
    if (!id || seen.has(id)) {
      continue;
    }
    seen.add(id);
    out.push(id);
  }
  return out;
}

/** Assistant blocks after tool output in the same run are answers for the user, not pre-tool planning. */
function postToolAssistantBlockIds(blocks: LiveBlock[]): Set<string> {
  let seenToolResult = false;
  const ids = new Set<string>();
  for (const b of blocks) {
    if (b.kind === "tool_result") {
      seenToolResult = true;
    }
    if (b.kind === "assistant" && seenToolResult) {
      ids.add(b.id);
    }
  }
  return ids;
}

/** Union pending ids: server list first, then any extras (same run, second mutation, etc.). */
function mergePendingIdLists(
  primary: string[],
  ...extras: string[][]
): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of primary) {
    const p = raw.trim();
    if (!p || seen.has(p)) {
      continue;
    }
    seen.add(p);
    out.push(p);
  }
  for (const list of extras) {
    for (const raw of list) {
      const p = raw.trim();
      if (!p || seen.has(p)) {
        continue;
      }
      seen.add(p);
      out.push(p);
    }
  }
  return out;
}

/** Passed into `applyStreamEvent` so assistant rows match stream `phase` (model vs summary). */
type AgentApplyStreamCtx = {
  assistantStreamPhase: "model" | "summary" | null;
};

function stampStreamPhase(
  ctx: AgentApplyStreamCtx,
  existing?: "model" | "summary",
): "model" | "summary" | undefined {
  if (existing === "model" || existing === "summary") {
    return existing;
  }
  const p = ctx.assistantStreamPhase;
  if (p === "model" || p === "summary") {
    return p;
  }
  return undefined;
}

function applyStreamEvent(
  prev: LiveBlock[],
  ev: HofStreamEvent,
  ctx: AgentApplyStreamCtx,
): LiveBlock[] {
  const t = typeof ev.type === "string" ? ev.type : "";
  if (t === "phase") {
    const round = typeof ev.round === "number" ? ev.round : 0;
    const phase = typeof ev.phase === "string" ? ev.phase : "";
    return [...prev, { kind: "phase", id: newId(), round, phase }];
  }
  if (t === "assistant_delta") {
    const chunk = typeof ev.text === "string" ? ev.text : "";
    const last = prev[prev.length - 1];
    if (last?.kind === "assistant" && last.streaming) {
      const sp = stampStreamPhase(ctx, last.streamPhase);
      return [
        ...prev.slice(0, -1),
        {
          ...last,
          text: last.text + chunk,
          ...(sp ? { streamPhase: sp } : {}),
        },
      ];
    }
    const spNew = stampStreamPhase(ctx);
    return [
      ...prev,
      {
        kind: "assistant",
        id: newId(),
        text: chunk,
        streaming: true,
        ...(spNew ? { streamPhase: spNew } : {}),
      },
    ];
  }
  if (t === "assistant_done") {
    const u = ev.usage as
      | {
          prompt_tokens?: number;
          completion_tokens?: number;
          total_tokens?: number;
        }
      | undefined;
    const fr =
      typeof ev.finish_reason === "string" ? ev.finish_reason : undefined;
    let streamingIdx = -1;
    for (let k = prev.length - 1; k >= 0; k--) {
      const bl = prev[k];
      if (bl?.kind === "assistant" && bl.streaming) {
        streamingIdx = k;
        break;
      }
    }
    if (streamingIdx >= 0) {
      const last = prev[streamingIdx] as Extract<
        LiveBlock,
        { kind: "assistant" }
      >;
      const sp = stampStreamPhase(ctx, last.streamPhase);
      return [
        ...prev.slice(0, streamingIdx),
        {
          ...last,
          streaming: false,
          finishReason: fr,
          usage: u,
          ...(sp ? { streamPhase: sp } : {}),
        },
        ...prev.slice(streamingIdx + 1),
      ];
    }
    const spFallback = stampStreamPhase(ctx);
    return [
      ...prev,
      {
        kind: "assistant",
        id: newId(),
        text: "",
        streaming: false,
        finishReason: fr,
        usage: u,
        ...(spFallback ? { streamPhase: spFallback } : {}),
      },
    ];
  }
  if (t === "tool_call") {
    const name = typeof ev.name === "string" ? ev.name : "";
    const args = typeof ev.arguments === "string" ? ev.arguments : "";
    const cli = typeof ev.cli_line === "string" ? ev.cli_line : "";
    const iraw = ev.internal_rationale;
    const internal_rationale =
      typeof iraw === "string" && iraw.trim() ? iraw.trim() : undefined;
    return [
      ...prev,
      {
        kind: "tool_call",
        id: newId(),
        name,
        cli_line: cli,
        arguments: args || undefined,
        internal_rationale,
      },
    ];
  }
  if (t === "tool_result") {
    const name = typeof ev.name === "string" ? ev.name : "";
    const summary = typeof ev.summary === "string" ? ev.summary : "";
    const hasData = Object.prototype.hasOwnProperty.call(ev, "data");
    const data = hasData ? (ev as { data: unknown }).data : undefined;
    return [
      ...prev,
      {
        kind: "tool_result",
        id: newId(),
        name,
        summary,
        ...(hasData ? { data } : {}),
      },
    ];
  }
  if (t === "mutation_pending") {
    const pending_id = typeof ev.pending_id === "string" ? ev.pending_id : "";
    const name = typeof ev.name === "string" ? ev.name : "";
    const cli_line = typeof ev.cli_line === "string" ? ev.cli_line : "";
    const args = typeof ev.arguments === "string" ? ev.arguments : "";
    return [
      ...prev,
      {
        kind: "mutation_pending",
        id: newId(),
        pending_id,
        name,
        cli_line,
        arguments_preview: args || undefined,
      },
    ];
  }
  if (t === "awaiting_confirmation") {
    const run_id = coerceRunId(ev.run_id);
    const pending_ids = Array.isArray(ev.pending_ids)
      ? (ev.pending_ids as unknown[]).map((x) => String(x)).filter(Boolean)
      : [];
    return [
      ...prev,
      { kind: "approval_required", id: newId(), run_id, pending_ids },
    ];
  }
  if (t === "error") {
    const detail = typeof ev.detail === "string" ? ev.detail : "error";
    return [...prev, { kind: "error", id: newId(), detail }];
  }
  // Terminal / control events — reply already streamed via assistant_*; do not add UI blocks.
  if (t === "final" || t === "resume_start" || t === "run_start") {
    return prev;
  }
  return prev;
}

type ToolCallBlock = Extract<LiveBlock, { kind: "tool_call" }>;
type MutationPendingBlock = Extract<LiveBlock, { kind: "mutation_pending" }>;
type ToolResultBlock = Extract<LiveBlock, { kind: "tool_result" }>;

type BlockSegment =
  | { type: "single"; block: LiveBlock }
  | {
      type: "tool_group";
      key: string;
      call: ToolCallBlock;
      mutation?: MutationPendingBlock;
      result?: ToolResultBlock;
    };

/**
 * Backend emits `phase: model` before `assistant_*` for each round. The assistant bubble
 * already represents model activity, so keeping both looks like a second stuck "Reasoning…" row.
 */
function dropRedundantModelPhaseBeforeAssistant(blocks: LiveBlock[]): LiveBlock[] {
  const out: LiveBlock[] = [];
  for (let i = 0; i < blocks.length; i++) {
    const b = blocks[i];
    const next = blocks[i + 1];
    if (
      b.kind === "phase" &&
      b.phase === "model" &&
      next?.kind === "assistant"
    ) {
      continue;
    }
    out.push(b);
  }
  return out;
}

function isEphemeralAssistantShell(b: LiveBlock): boolean {
  if (b.kind !== "assistant") {
    return false;
  }
  if (b.streaming) {
    return false;
  }
  const t = b.text.trim();
  return b.finishReason === "tool_calls" && !t;
}

function normalizeAssistantTextForDedupe(s: string): string {
  return s.replace(/\s+/g, " ").trim();
}

/**
 * Rare stream / multi-round edge cases can yield two completed assistant rows with the same
 * body; the UI would show duplicate reply bubbles. Collapse consecutive duplicates.
 */
function dedupeAdjacentDuplicateAssistants(blocks: LiveBlock[]): LiveBlock[] {
  const out: LiveBlock[] = [];
  for (const b of blocks) {
    if (b.kind !== "assistant") {
      out.push(b);
      continue;
    }
    const cur = b as Extract<LiveBlock, { kind: "assistant" }>;
    const prev = out[out.length - 1];
    if (prev?.kind === "assistant") {
      const pa = prev as Extract<LiveBlock, { kind: "assistant" }>;
      if (!pa.streaming && !cur.streaming) {
        const a = normalizeAssistantTextForDedupe(pa.text);
        const c = normalizeAssistantTextForDedupe(cur.text);
        if (a.length > 0 && a === c) {
          continue;
        }
      }
    }
    out.push(b);
  }
  return out;
}

/** Drop noisy rows before persisting a completed run to the thread. */
function compactBlocksForHistory(blocks: LiveBlock[]): LiveBlock[] {
  const base = dropRedundantModelPhaseBeforeAssistant(blocks).filter(
    (b) => !isEphemeralAssistantShell(b),
  );
  return dedupeAdjacentDuplicateAssistants(base);
}

function applyStreamEventWithDedupe(
  prev: LiveBlock[],
  ev: HofStreamEvent,
  ctx: AgentApplyStreamCtx,
): LiveBlock[] {
  return dedupeAdjacentDuplicateAssistants(applyStreamEvent(prev, ev, ctx));
}

function segmentLiveBlocks(blocks: LiveBlock[]): BlockSegment[] {
  const out: BlockSegment[] = [];
  let i = 0;
  while (i < blocks.length) {
    const b = blocks[i];
    if (b.kind === "assistant") {
      out.push({ type: "single", block: b });
      i += 1;
      continue;
    }
    if (b.kind === "tool_call") {
      const call = b;
      i += 1;
      let mutation: MutationPendingBlock | undefined;
      let result: ToolResultBlock | undefined;
      if (i < blocks.length && blocks[i].kind === "mutation_pending") {
        mutation = blocks[i] as MutationPendingBlock;
        i += 1;
      }
      if (i < blocks.length && blocks[i].kind === "tool_result") {
        result = blocks[i] as ToolResultBlock;
        i += 1;
      }
      out.push({
        type: "tool_group",
        key: call.id,
        call,
        mutation,
        result,
      });
      continue;
    }
    out.push({ type: "single", block: b });
    i += 1;
  }
  return out;
}

function toolCallCliLine(b: ToolCallBlock): string {
  return (
    b.cli_line?.trim() ||
    (b.name && b.arguments
      ? `hof fn ${b.name} ${b.arguments.length > 220 ? `${b.arguments.slice(0, 217)}…` : b.arguments}`
      : b.name || "(tool)")
  );
}

function toolCallArgsSnippet(b: ToolCallBlock): string | null {
  if (!b.arguments || !b.cli_line || b.arguments.length === 0) {
    return null;
  }
  return b.arguments.length > 600 ? `${b.arguments.slice(0, 600)}…` : b.arguments;
}

function isGenericAwaitingConfirmationSummary(summary: string): boolean {
  return /awaiting your confirmation/i.test(summary.trim());
}

function toolGroupSummaryLine(
  call: ToolCallBlock,
  mutation: MutationPendingBlock | undefined,
  result: ToolResultBlock | undefined,
): string | null {
  const title = humanizeToolName(call.name);
  if (mutation && !result) {
    return null;
  }
  if (result?.summary) {
    const s = result.summary.trim();
    if (mutation && isGenericAwaitingConfirmationSummary(s)) {
      return null;
    }
    if (s.length > 72) {
      return `${title} · ${s.slice(0, 69)}…`;
    }
    return `${title} · ${s}`;
  }
  return `${title} · in progress`;
}

function ToolGroupCard({
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

type ApprovalBarrier = {
  runId: string;
  items: { pendingId: string; name: string; cli_line: string }[];
};

function barrierMatchesApprovalBlock(
  barrier: ApprovalBarrier,
  blockRunId: string,
  blockPendingIds: string[],
): boolean {
  const br = barrier.runId.trim();
  const tr = blockRunId.trim();
  if (br !== "" && tr !== "" && br === tr) {
    return true;
  }
  if (blockPendingIds.length === 0 || barrier.items.length === 0) {
    return false;
  }
  const ps = new Set(blockPendingIds.map((x) => x.trim()).filter(Boolean));
  const bs = new Set(barrier.items.map((it) => it.pendingId.trim()));
  if (ps.size !== bs.size) {
    return false;
  }
  for (const p of ps) {
    if (!bs.has(p)) {
      return false;
    }
  }
  return true;
}

/** After resume; `true` = approved, `false` = rejected. */
function confirmationFooterFromOutcomes(
  pendingIds: string[],
  outcomes: Record<string, boolean | undefined>,
): string {
  const norm = pendingIds.map((p) => p.trim()).filter(Boolean);
  if (norm.length === 0) {
    return "Confirmation completed.";
  }
  let approved = 0;
  let rejected = 0;
  let unknown = 0;
  for (const pid of norm) {
    const v = outcomes[pid];
    if (v === true) {
      approved += 1;
    } else if (v === false) {
      rejected += 1;
    } else {
      unknown += 1;
    }
  }
  if (unknown > 0) {
    return "Waiting for Approve or Reject on each pending action above.";
  }
  if (rejected === 0) {
    return approved === 1
      ? "Choice recorded — see each action card for details."
      : "Choices recorded — see each action card for details.";
  }
  if (approved === 0) {
    return rejected === 1
      ? "Choice recorded — see each action card for details."
      : "Choices recorded — see each action card for details.";
  }
  return `Recorded: ${approved} approved, ${rejected} rejected — see cards above.`;
}

function InlineApprovalControls({
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

function assistantUiRole(
  b: Extract<LiveBlock, { kind: "assistant" }>,
  opts?: { afterToolResult?: boolean },
): "reasoning" | "reply" {
  if (opts?.afterToolResult) {
    return "reply";
  }
  if (b.streamPhase === "summary") {
    return "reply";
  }
  if (b.streamPhase === "model") {
    if (b.streaming) {
      return "reasoning";
    }
    if (b.finishReason === "tool_calls") {
      return "reasoning";
    }
    return "reply";
  }
  if (b.streaming) {
    return "reasoning";
  }
  if (b.finishReason === "tool_calls" && b.text.trim()) {
    return "reasoning";
  }
  return "reply";
}

function showProposedActionsLabel(
  segments: BlockSegment[],
  idx: number,
  postToolAssistantIds: Set<string>,
): boolean {
  if (idx <= 0) {
    return false;
  }
  const seg = segments[idx];
  if (seg.type !== "tool_group") {
    return false;
  }
  const prev = segments[idx - 1];
  if (prev.type !== "single" || prev.block.kind !== "assistant") {
    return false;
  }
  return (
    assistantUiRole(prev.block, {
      afterToolResult: postToolAssistantIds.has(prev.block.id),
    }) === "reasoning"
  );
}

function RunBlocksList({
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

function ReasoningCollapsible({
  text,
  streaming,
}: {
  text: string;
  streaming: boolean;
}) {
  const [open, setOpen] = useState(streaming);

  useEffect(() => {
    if (streaming) {
      setOpen(true);
    }
  }, [streaming]);

  const body = text || (streaming ? "…" : "");
  if (!body.trim() && !streaming) {
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
        <span className="font-medium uppercase tracking-wide">Reasoning</span>
      </summary>
      <div className="border-l border-border/70 pl-2.5 pt-1 pb-0.5 text-[11px] leading-snug text-secondary">
        <span className="whitespace-pre-wrap break-words">{body}</span>
        {streaming ? (
          <span className="ml-0.5 inline-block h-3 w-px animate-pulse bg-[var(--color-accent)] align-middle" />
        ) : null}
      </div>
    </details>
  );
}

function LiveBlockView({
  b,
  afterToolResult = false,
}: {
  b: LiveBlock;
  afterToolResult?: boolean;
}) {
  if (b.kind === "phase") {
    if (b.phase === "summary" || b.phase === "tools") {
      return null;
    }
    if (b.phase === "model") {
      return (
        <div className="border-l-2 border-border pl-3 text-[11px] italic leading-snug text-tertiary">
          Working…
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
    const role = assistantUiRole(b, { afterToolResult });
    const replyBubbleClass = CHAT_ASSISTANT_REPLY_BUBBLE_CLASS;

    if (role === "reasoning") {
      return (
        <ReasoningCollapsible text={b.text} streaming={b.streaming} />
      );
    }

    if (b.streaming) {
      return (
        <div className={replyBubbleClass}>
          <span className="whitespace-pre-wrap break-words">
            {b.text || "…"}
          </span>
          <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-[var(--color-accent)] align-middle" />
        </div>
      );
    }

    const text = b.text.trim();
    if (!text) {
      return null;
    }

    return (
      <div className={replyBubbleClass}>
        <span className="whitespace-pre-wrap break-words">{b.text}</span>
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

export type HofAgentChatPresignInput = {
  filename: string;
  content_type: string;
};

export type HofAgentChatPresignResult = {
  upload_url: string;
  object_key: string;
};

export type HofAgentChatProps = {
  /** Shown in the empty-state welcome line (e.g. first name from your auth profile). */
  welcomeName: string;
  /** Presign + upload pipeline for PDF attachments (e.g. wrap ``useHofFunction("presign_…")``). */
  presignUpload: (
    input: HofAgentChatPresignInput,
  ) => Promise<HofAgentChatPresignResult>;
  /** Extra classes on the conversation root (host owns width, border, page chrome). */
  className?: string;
  /** Override loading copy under the message list. */
  connectingLabel?: string;
};

export function HofAgentChat({
  welcomeName,
  presignUpload,
  className = "",
  connectingLabel = "Connecting…",
}: HofAgentChatProps) {
  const [thread, setThread] = useState<ThreadItem[]>([]);
  const [liveBlocks, setLiveBlocks] = useState<LiveBlock[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [attachmentQueue, setAttachmentQueue] = useState<AgentAttachment[]>([]);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploadErr, setUploadErr] = useState<string | null>(null);
  const [approvalBarrier, setApprovalBarrier] =
    useState<ApprovalBarrier | null>(null);
  const [approvalDecisions, setApprovalDecisions] = useState<
    Record<string, boolean | null>
  >({});
  /** Persisted after successful `agent_resume_mutations`: pending_id → approved? */
  const [mutationOutcomeByPendingId, setMutationOutcomeByPendingId] =
    useState<Record<string, boolean | undefined>>({});
  const fileInputRef = useRef<HTMLInputElement>(null);
  const threadRef = useRef<ThreadItem[]>([]);
  const sendingRef = useRef(false);
  const reqIdRef = useRef(0);
  const runResumeRef = useRef<() => Promise<void>>(async () => {});
  /** Prevents scheduling repeated auto-resume for the same barrier (e.g. after a failed resume). */
  const autoResumeSentForRunRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  /** Mirrors liveBlocks; used to flush after stream without side effects inside setState (Strict Mode double-invokes updaters). */
  const liveBlocksRef = useRef<LiveBlock[]>([]);
  const pendingDetailsRef = useRef(
    new Map<string, { name: string; cli_line: string }>(),
  );
  /** Mutation `pending_id`s seen this run (sync); `liveBlocksRef` can lag same-tick stream events. */
  const mutationPendingIdsThisRunRef = useRef<string[]>([]);
  /** Latest `run_id` from `run_start` (stream control event is not stored as a LiveBlock). */
  const currentAgentRunIdRef = useRef("");
  /** Last `phase: model|summary` before assistant deltas (NDJSON stream). */
  const assistantStreamPhaseRef = useRef<"model" | "summary" | null>(null);

  useEffect(() => {
    threadRef.current = thread;
  }, [thread]);

  /** Rebuild OpenAI message list from thread (user lines + last assistant segment per completed run). */
  const threadToApiMessages = useCallback((items: ThreadItem[]) => {
    const out: { role: "user" | "assistant"; content: string }[] = [];
    for (const it of items) {
      if (it.kind === "user") {
        out.push({ role: "user", content: it.content });
      } else {
        const texts = it.blocks
          .filter(
            (b): b is Extract<LiveBlock, { kind: "assistant" }> =>
              b.kind === "assistant",
          )
          .map((b) => b.text.trim())
          .filter(Boolean);
        const reply = texts.length ? texts[texts.length - 1] : "";
        if (reply) {
          out.push({ role: "assistant", content: reply });
        }
      }
    }
    return out;
  }, []);

  const flushLiveToThread = useCallback((blocks: LiveBlock[]) => {
    if (blocks.length === 0) {
      return;
    }
    const cleaned = compactBlocksForHistory(blocks);
    const toStore = cleaned.length > 0 ? cleaned : blocks;
    setThread((t) => [
      ...t,
      { kind: "run", id: newId(), blocks: structuredClone(toStore) },
    ]);
  }, []);

  const runAgent = useCallback(
    async (items: ThreadItem[]) => {
      const myId = ++reqIdRef.current;
      abortRef.current?.abort();
      abortRef.current = new AbortController();
      setBusy(true);
      liveBlocksRef.current = [];
      setLiveBlocks([]);
      currentAgentRunIdRef.current = "";
      const msgs = threadToApiMessages(items);
      const attachments = collectThreadAttachments(items);
      try {
        const body: Record<string, unknown> = { messages: msgs };
        if (attachments.length > 0) {
          body.attachments = attachments.map((a) => ({
            object_key: a.object_key,
            filename: a.filename,
            content_type: a.content_type,
          }));
        }
        // NDJSON stream contract: packages/hof-components/implementations/spreadsheet-app/docs/agent-chat-stream.md
        await streamHofFunction("agent_chat", body, {
          signal: abortRef.current.signal,
          onEvent: (ev) => {
            if (myId !== reqIdRef.current) {
              return;
            }
            const typ = typeof ev.type === "string" ? ev.type : "";
            if (typ === "run_start") {
              assistantStreamPhaseRef.current = null;
              pendingDetailsRef.current.clear();
              mutationPendingIdsThisRunRef.current = [];
              currentAgentRunIdRef.current = coerceRunId(ev.run_id);
              setApprovalBarrier(null);
              setApprovalDecisions({});
            }
            if (typ === "phase") {
              const ph = typeof ev.phase === "string" ? ev.phase : "";
              if (ph === "model" || ph === "summary") {
                assistantStreamPhaseRef.current = ph;
              }
            }
            if (typ === "mutation_pending") {
              const pid =
                typeof ev.pending_id === "string" ? ev.pending_id : "";
              if (pid) {
                pendingDetailsRef.current.set(pid, {
                  name: typeof ev.name === "string" ? ev.name : "",
                  cli_line: typeof ev.cli_line === "string" ? ev.cli_line : "",
                });
                const acc = mutationPendingIdsThisRunRef.current;
                if (!acc.includes(pid)) {
                  acc.push(pid);
                }
              }
            }
            let evForBlocks: HofStreamEvent = ev;
            if (typ === "awaiting_confirmation") {
              const rid =
                coerceRunId(ev.run_id) || currentAgentRunIdRef.current.trim();
              const fromEvent = Array.isArray(ev.pending_ids)
                ? (ev.pending_ids as unknown[]).map((x) => String(x)).filter(Boolean)
                : [];
              const pids = mergePendingIdLists(
                fromEvent,
                mutationPendingIdsThisRunRef.current,
                mutationPendingIdsFromBlocks(liveBlocksRef.current),
              );
              const items = pids.map((pid) => ({
                pendingId: pid,
                name: pendingDetailsRef.current.get(pid)?.name || "mutation",
                cli_line: pendingDetailsRef.current.get(pid)?.cli_line || "",
              }));
              setApprovalBarrier({ runId: rid, items });
              const dec: Record<string, boolean | null> = {};
              for (const p of pids) {
                dec[p] = null;
              }
              setApprovalDecisions(dec);
              evForBlocks =
                pids.length > 0
                  ? ({
                      ...ev,
                      run_id: rid,
                      pending_ids: pids,
                    } as HofStreamEvent)
                  : ev;
            }
            setLiveBlocks((prev) => {
              const next = applyStreamEventWithDedupe(prev, evForBlocks, {
                assistantStreamPhase: assistantStreamPhaseRef.current,
              });
              liveBlocksRef.current = next;
              return next;
            });
          },
        });
        if (myId !== reqIdRef.current) {
          return;
        }
        setAttachmentQueue([]);
        let doneBlocks = liveBlocksRef.current;
        const ridForSynth = currentAgentRunIdRef.current.trim();
        const hasApprovalBlock = doneBlocks.some(
          (b) => b.kind === "approval_required",
        );
        const synthPids = mergePendingIdLists(
          mutationPendingIdsFromBlocks(doneBlocks),
          mutationPendingIdsThisRunRef.current,
        );
        if (
          !hasApprovalBlock &&
          synthPids.length > 0 &&
          toolResultAwaitingUserConfirmation(doneBlocks) &&
          ridForSynth
        ) {
          doneBlocks = [
            ...doneBlocks,
            {
              kind: "approval_required",
              id: newId(),
              run_id: ridForSynth,
              pending_ids: synthPids,
            },
          ];
          liveBlocksRef.current = doneBlocks;
          const items = synthPids.map((pid) => ({
            pendingId: pid,
            name: pendingDetailsRef.current.get(pid)?.name || "mutation",
            cli_line: pendingDetailsRef.current.get(pid)?.cli_line || "",
          }));
          setApprovalBarrier({ runId: ridForSynth, items });
          setApprovalDecisions(
            Object.fromEntries(synthPids.map((p) => [p, null])) as Record<
              string,
              boolean | null
            >,
          );
        }
        if (doneBlocks.length > 0) {
          flushLiveToThread(structuredClone(doneBlocks));
        }
        liveBlocksRef.current = [];
        setLiveBlocks([]);
      } catch (e) {
        if (myId !== reqIdRef.current) {
          return;
        }
        if (e instanceof Error && e.name === "AbortError") {
          return;
        }
        const msg = e instanceof Error ? e.message : String(e);
        const merged = [
          ...liveBlocksRef.current,
          { kind: "error", id: newId(), detail: msg } as LiveBlock,
        ];
        if (merged.length > 0) {
          flushLiveToThread(structuredClone(merged));
        }
        liveBlocksRef.current = [];
        setLiveBlocks([]);
      } finally {
        if (myId === reqIdRef.current) {
          setBusy(false);
          sendingRef.current = false;
        }
      }
    },
    [flushLiveToThread, threadToApiMessages],
  );

  const runResume = useCallback(async () => {
    if (!approvalBarrier) {
      return;
    }
    const allChosen = approvalBarrier.items.every(
      (it) =>
        approvalDecisions[it.pendingId] === true ||
        approvalDecisions[it.pendingId] === false,
    );
    if (!allChosen) {
      return;
    }
    const myId = ++reqIdRef.current;
    abortRef.current?.abort();
    abortRef.current = new AbortController();
    setBusy(true);
    liveBlocksRef.current = [];
    setLiveBlocks([]);
    mutationPendingIdsThisRunRef.current = [];
    const resolutions = approvalBarrier.items.map((it) => ({
      pending_id: it.pendingId,
      confirm: approvalDecisions[it.pendingId] === true,
    }));
    const outcomeSnapshot = approvalBarrier.items.map((it) => ({
      pendingId: it.pendingId,
      approved: approvalDecisions[it.pendingId] === true,
    }));
    const rid = approvalBarrier.runId;
    try {
      await streamHofFunction(
        "agent_resume_mutations",
        { run_id: rid, resolutions },
        {
          signal: abortRef.current.signal,
          onEvent: (ev) => {
            if (myId !== reqIdRef.current) {
              return;
            }
            const rtyp = typeof ev.type === "string" ? ev.type : "";
            if (rtyp === "resume_start") {
              assistantStreamPhaseRef.current = null;
            }
            if (rtyp === "phase") {
              const ph = typeof ev.phase === "string" ? ev.phase : "";
              if (ph === "model" || ph === "summary") {
                assistantStreamPhaseRef.current = ph;
              }
            }
            setLiveBlocks((prev) => {
              const next = applyStreamEventWithDedupe(prev, ev, {
                assistantStreamPhase: assistantStreamPhaseRef.current,
              });
              liveBlocksRef.current = next;
              return next;
            });
          },
        },
      );
      if (myId !== reqIdRef.current) {
        return;
      }
      setMutationOutcomeByPendingId((prev) => {
        const next = { ...prev };
        for (const row of outcomeSnapshot) {
          next[row.pendingId] = row.approved;
        }
        return next;
      });
      setApprovalBarrier(null);
      setApprovalDecisions({});
      pendingDetailsRef.current.clear();
      const doneBlocks = liveBlocksRef.current;
      if (doneBlocks.length > 0) {
        flushLiveToThread(structuredClone(doneBlocks));
      }
      liveBlocksRef.current = [];
      setLiveBlocks([]);
    } catch (e) {
      if (myId !== reqIdRef.current) {
        return;
      }
      if (e instanceof Error && e.name === "AbortError") {
        return;
      }
      const msg = e instanceof Error ? e.message : String(e);
      const merged = [
        ...liveBlocksRef.current,
        { kind: "error", id: newId(), detail: msg } as LiveBlock,
      ];
      if (merged.length > 0) {
        flushLiveToThread(structuredClone(merged));
      }
      liveBlocksRef.current = [];
      setLiveBlocks([]);
    } finally {
      if (myId === reqIdRef.current) {
        setBusy(false);
      }
    }
  }, [approvalBarrier, approvalDecisions, flushLiveToThread]);

  runResumeRef.current = runResume;

  useEffect(() => {
    autoResumeSentForRunRef.current = null;
  }, [approvalDecisions]);

  useEffect(() => {
    if (!approvalBarrier?.items.length) {
      return;
    }
    const id = window.requestAnimationFrame(() => {
      document
        .getElementById("hof-agent-pending-confirmation")
        ?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
    return () => window.cancelAnimationFrame(id);
  }, [approvalBarrier]);

  useEffect(() => {
    if (!approvalBarrier) {
      autoResumeSentForRunRef.current = null;
      return;
    }
    if (busy) {
      return;
    }
    const rid = approvalBarrier.runId;
    const allChosen = approvalBarrier.items.every(
      (it) =>
        approvalDecisions[it.pendingId] === true ||
        approvalDecisions[it.pendingId] === false,
    );
    if (!allChosen) {
      return;
    }
    if (autoResumeSentForRunRef.current === rid) {
      return;
    }
    const t = window.setTimeout(() => {
      autoResumeSentForRunRef.current = rid;
      void runResumeRef.current();
    }, 280);
    return () => window.clearTimeout(t);
  }, [approvalBarrier, approvalDecisions, busy]);

  const onPickFiles = useCallback(
    async (files: FileList | null) => {
      if (!files?.length) {
        return;
      }
      setUploadErr(null);
      const list = Array.from(files).filter(
        (f) =>
          f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf"),
      );
      if (list.length === 0) {
        setUploadErr("Only PDF files are supported.");
        return;
      }
      setUploadBusy(true);
      try {
        for (const file of list) {
          const pr = await presignUpload({
            filename: file.name,
            content_type: "application/pdf",
          });
          const put = await fetch(pr.upload_url, {
            method: "PUT",
            body: file,
            headers: { "Content-Type": "application/pdf" },
          });
          if (!put.ok) {
            throw new Error(`Upload failed (${put.status})`);
          }
          setAttachmentQueue((q) => [
            ...q,
            {
              object_key: pr.object_key,
              filename: file.name,
              content_type: "application/pdf",
            },
          ]);
        }
      } catch (e) {
        setUploadErr(e instanceof Error ? e.message : String(e));
      } finally {
        setUploadBusy(false);
        if (fileInputRef.current) {
          fileInputRef.current.value = "";
        }
      }
    },
    [presignUpload],
  );

  const send = useCallback(() => {
    const t = input.trim();
    if (approvalBarrier) {
      return;
    }
    if (
      (!t && attachmentQueue.length === 0) ||
      busy ||
      sendingRef.current ||
      uploadBusy
    ) {
      return;
    }
    sendingRef.current = true;
    setBusy(true);
    setInput("");
    abortRef.current?.abort();
    const pending = liveBlocksRef.current;
    const baseThread = threadRef.current;
    const pendingCompact =
      pending.length > 0 ? compactBlocksForHistory(pending) : [];
    const blocksToArchive =
      pending.length > 0 && pendingCompact.length === 0
        ? pending
        : pendingCompact;
    const afterFlush =
      blocksToArchive.length > 0
        ? [
            ...baseThread,
            {
              kind: "run" as const,
              id: newId(),
              blocks: structuredClone(blocksToArchive),
            },
          ]
        : baseThread;
    liveBlocksRef.current = [];
    setLiveBlocks([]);
    const snap = [...attachmentQueue];
    const names = snap.map((a) => a.filename).filter(Boolean);
    const attachNote =
      snap.length > 0
        ? `\n\n[Attached PDF: ${names.join(", ")} — keys are in the assistant context.]`
        : "";
    const content =
      (t ||
        (snap.length
          ? `I've attached ${snap.length} PDF receipt${snap.length > 1 ? "s" : ""}.${attachNote}`
          : "")) + (t && snap.length > 0 ? attachNote : "");
    const userItem: ThreadItem = {
      kind: "user",
      id: newId(),

      content,
      attachments: snap.length > 0 ? snap : undefined,
    };
    const nextThread = [...afterFlush, userItem];
    threadRef.current = nextThread;
    setThread(nextThread);
    setAttachmentQueue([]);
    void runAgent(nextThread);
  }, [approvalBarrier, attachmentQueue, busy, input, runAgent, uploadBusy]);

  const conversationEmpty = thread.length === 0 && liveBlocks.length === 0;

  const messagesBlock = (
    <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden [scrollbar-gutter:stable]">
      <div className="mx-auto flex min-h-full w-full flex-col px-5 py-6 sm:px-6 sm:py-8">
        {conversationEmpty ? (
          <header className="mb-10 flex flex-col items-center text-center font-sans sm:mb-12">
            <p className="text-xl font-semibold tracking-tight text-foreground sm:text-2xl">
              Welcome, {welcomeName}
            </p>
            <p className="mt-2 max-w-sm text-[13px] leading-relaxed text-secondary">
              This is your assistant inbox. New replies show up here. Use the
              field below to write a message or attach a PDF.
            </p>
          </header>
        ) : null}
        <div className="min-h-0 flex-1 space-y-5">
          {thread.map((item) => {
            if (item.kind === "user") {
              const hasAtt = Boolean(item.attachments?.length);
              const displayBody = userMessageDisplayText(
                item.content,
                hasAtt,
              );
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
          })}
          {liveBlocks.length > 0 ? (
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
          ) : null}
          {busy && liveBlocks.length === 0 ? (
            <div className="flex items-center justify-center gap-2 py-2 text-[13px] text-secondary">
              <Loader2
                className="size-4 shrink-0 animate-spin text-[var(--color-accent)]"
                aria-hidden
              />
              <span>{connectingLabel}</span>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );

  const composerRow = (
    <div className="flex gap-2">
      <button
        type="button"
        disabled={busy || uploadBusy || Boolean(approvalBarrier)}
        className="flex shrink-0 items-center justify-center rounded-lg border border-border bg-surface px-2.5 text-secondary transition-colors hover:bg-hover hover:text-foreground disabled:opacity-50"
        onClick={() => fileInputRef.current?.click()}
        aria-label="Attach PDF"
      >
        {uploadBusy ? (
          <Loader2 className="size-5 animate-spin" />
        ) : (
          <Paperclip className="size-5" />
        )}
      </button>
      <input
        type="text"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && e.repeat) {
            return;
          }
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            e.stopPropagation();
            send();
          }
        }}
        placeholder="Message…"
        disabled={busy || uploadBusy || Boolean(approvalBarrier)}
        className="min-w-0 flex-1 rounded-lg border border-border bg-background px-3 py-2.5 text-sm text-foreground placeholder:text-secondary outline-none transition-[box-shadow] focus:ring-2 focus:ring-[color:color-mix(in_srgb,var(--color-accent)_35%,transparent)] disabled:opacity-60"
      />
      <button
        type="button"
        onClick={send}
        disabled={
          busy ||
          uploadBusy ||
          Boolean(approvalBarrier) ||
          (!input.trim() && attachmentQueue.length === 0)
        }
        className="shrink-0 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground transition-opacity disabled:cursor-not-allowed disabled:opacity-40"
      >
        {uploadBusy ? "Uploading…" : "Send"}
      </button>
    </div>
  );

  const composer = (
    <div className="w-full">
      <input
        ref={fileInputRef}
        type="file"
        accept="application/pdf,.pdf"
        multiple
        className="hidden"
        onChange={(e) => void onPickFiles(e.target.files)}
      />
      {attachmentQueue.length > 0 ? (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {attachmentQueue.map((a) => (
            <span
              key={a.object_key}
              className="inline-flex max-w-full items-center gap-1 rounded-md border border-border bg-surface px-2 py-0.5 text-[11px] text-secondary"
            >
              <span className="truncate">{a.filename}</span>
              <button
                type="button"
                className="shrink-0 rounded p-0.5 text-secondary hover:bg-hover hover:text-foreground"
                onClick={() =>
                  setAttachmentQueue((q) =>
                    q.filter((x) => x.object_key !== a.object_key),
                  )
                }
                aria-label={`Remove ${a.filename}`}
              >
                <X className="size-3.5" />
              </button>
            </span>
          ))}
        </div>
      ) : null}
      {uploadErr ? (
        <p className="mb-2 text-[12px] text-[var(--color-destructive)]">
          {uploadErr}
        </p>
      ) : null}
      <div className="rounded-xl bg-hover/40 p-2 sm:p-2.5">{composerRow}</div>
      <p className="mt-2.5 text-center text-[11px] leading-snug text-tertiary">
        The assistant can make mistakes. Data changes only run after you approve them.
      </p>
    </div>
  );

  return (
    <div
      className={`hof-agent flex min-h-0 min-w-0 w-full flex-1 flex-col font-sans ${className}`.trim()}
    >
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        {messagesBlock}
      </div>
      <div className="shrink-0 border-t border-[var(--color-border)]/60 pt-3">
        {composer}
      </div>
    </div>
  );
}
