import type { HofStreamEvent } from "../hooks/streamHofFunction";

export type AgentAttachment = {
  object_key: string;
  filename: string;
  content_type: string;
};

export type LiveBlock =
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

export type ThreadItem =
  | {
      kind: "user";
      id: string;
      content: string;
      attachments?: AgentAttachment[];
    }
  | { kind: "run"; id: string; blocks: LiveBlock[] };

export function collectThreadAttachments(items: ThreadItem[]): AgentAttachment[] {
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

export function newId(): string {
  return crypto.randomUUID();
}

/**
 * Chat bubbles use Tailwind theme radii from app.css `@theme` (`rounded-lg` → `--radius-lg` →
 * `--hof-radius-*` in the active design-system bundle). Avoid ad-hoc radii so tokens control shape.
 */
export const CHAT_USER_BUBBLE_CLASS =
  "max-w-full rounded-lg bg-hover px-4 py-2.5 text-sm leading-relaxed text-foreground";
export const CHAT_ASSISTANT_REPLY_BUBBLE_CLASS =
  "max-w-[min(100%,42rem)] rounded-lg bg-hover/70 px-4 py-2.5 text-sm leading-relaxed text-foreground";

export const TOOL_SECTION_LABEL_CLASS =
  "mb-1 text-[10px] font-medium uppercase tracking-wide text-tertiary";

/** First name (or email local-part) for welcome line; falls back when profile is minimal. */
/** snake_case API name → readable label */
export function humanizeToolName(name: string): string {
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
export function userMessageDisplayText(
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
export function coerceRunId(value: unknown): string {
  if (typeof value === "string") {
    return value.trim();
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  return "";
}

export function toolResultAwaitingUserConfirmation(blocks: LiveBlock[]): boolean {
  return blocks.some(
    (b) =>
      b.kind === "tool_result" &&
      typeof b.summary === "string" &&
      /awaiting your confirmation/i.test(b.summary),
  );
}

/** Pending ids from mutation trace blocks (used if stream omits `pending_ids` on `awaiting_confirmation`). */
export function mutationPendingIdsFromBlocks(blocks: LiveBlock[]): string[] {
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
export function postToolAssistantBlockIds(blocks: LiveBlock[]): Set<string> {
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
export function mergePendingIdLists(
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

export function stampStreamPhase(
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

export function applyStreamEvent(
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

export type ToolCallBlock = Extract<LiveBlock, { kind: "tool_call" }>;
export type MutationPendingBlock = Extract<LiveBlock, { kind: "mutation_pending" }>;
export type ToolResultBlock = Extract<LiveBlock, { kind: "tool_result" }>;

export type BlockSegment =
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
export function dropRedundantModelPhaseBeforeAssistant(blocks: LiveBlock[]): LiveBlock[] {
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

export function isEphemeralAssistantShell(b: LiveBlock): boolean {
  if (b.kind !== "assistant") {
    return false;
  }
  if (b.streaming) {
    return false;
  }
  const t = b.text.trim();
  return b.finishReason === "tool_calls" && !t;
}

export function normalizeAssistantTextForDedupe(s: string): string {
  return s.replace(/\s+/g, " ").trim();
}

/**
 * Rare stream / multi-round edge cases can yield two completed assistant rows with the same
 * body; the UI would show duplicate reply bubbles. Collapse consecutive duplicates.
 */
export function dedupeAdjacentDuplicateAssistants(blocks: LiveBlock[]): LiveBlock[] {
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
export function compactBlocksForHistory(blocks: LiveBlock[]): LiveBlock[] {
  const base = dropRedundantModelPhaseBeforeAssistant(blocks).filter(
    (b) => !isEphemeralAssistantShell(b),
  );
  return dedupeAdjacentDuplicateAssistants(base);
}

export function applyStreamEventWithDedupe(
  prev: LiveBlock[],
  ev: HofStreamEvent,
  ctx: AgentApplyStreamCtx,
): LiveBlock[] {
  return dedupeAdjacentDuplicateAssistants(applyStreamEvent(prev, ev, ctx));
}

export function segmentLiveBlocks(blocks: LiveBlock[]): BlockSegment[] {
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

export function toolCallCliLine(b: ToolCallBlock): string {
  return (
    b.cli_line?.trim() ||
    (b.name && b.arguments
      ? `hof fn ${b.name} ${b.arguments.length > 220 ? `${b.arguments.slice(0, 217)}…` : b.arguments}`
      : b.name || "(tool)")
  );
}

export function toolCallArgsSnippet(b: ToolCallBlock): string | null {
  if (!b.arguments || !b.cli_line || b.arguments.length === 0) {
    return null;
  }
  return b.arguments.length > 600 ? `${b.arguments.slice(0, 600)}…` : b.arguments;
}

export function isGenericAwaitingConfirmationSummary(summary: string): boolean {
  return /awaiting your confirmation/i.test(summary.trim());
}

export function toolGroupSummaryLine(
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

export type ApprovalBarrier = {
  runId: string;
  items: { pendingId: string; name: string; cli_line: string }[];
};

export function barrierMatchesApprovalBlock(
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
export function confirmationFooterFromOutcomes(
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

export function assistantUiRole(
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

export function showProposedActionsLabel(
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
