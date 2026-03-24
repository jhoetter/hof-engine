import type { HofStreamEvent } from "../hooks/streamHofFunction";
import type { AssistantStreamSegment } from "./assistantStreamSegments";
import {
  appendAssistantStreamSegmentChunk,
  mergeAdjacentContentSegments,
  mergeAdjacentReasoningSegments,
  normalizeAssistantStreamSegments,
} from "./assistantStreamSegments";

export type { AssistantStreamSegment };
export {
  appendAssistantStreamSegmentChunk,
  mergeAdjacentContentSegments,
  mergeAdjacentReasoningSegments,
  normalizeAssistantStreamSegments,
};

export type AgentAttachment = {
  object_key: string;
  filename: string;
  content_type: string;
};

export type LiveBlock =
  | { kind: "phase"; id: string; round: number; phase: string }
  /** Ephemeral: shown from `phase: model` until first token or `tool_call` (models often emit no `assistant_delta` before tools). */
  | { kind: "thinking_skeleton"; id: string }
  | {
      kind: "assistant";
      id: string;
      text: string;
      streaming: boolean;
      finishReason?: string;
      /** From NDJSON `phase` before this segment: model round vs confirmation summary round. */
      streamPhase?: "model" | "summary";
      /**
       * Whether streamed tokens came from NDJSON `reasoning_delta` vs `assistant_delta`.
       * `mixed` if both appear in one segment (rare).
       */
      streamTextRole?: "content" | "reasoning" | "mixed";
      /** When the server emits ``segment_start``, ordered reasoning vs content lanes (preferred over single ``text`` for display). */
      streamSegments?: AssistantStreamSegment[];
      /**
       * Set on `assistant_done`. Drives stable Thinking vs reply presentation (persisted threads
       * without this field infer from `streamPhase` + `finishReason`).
       */
      uiLane?: "thinking" | "reply";
      /**
       * After `tool_call` / approval steps the visible stream has ended, but `assistant_done` may
       * arrive later for usage + `uiLane`. While true, treat as non-streaming in the UI (no caret).
       */
      pendingStreamFinalize?: boolean;
      usage?: {
        prompt_tokens?: number;
        completion_tokens?: number;
        total_tokens?: number;
      };
      /** Set on ``assistant_done`` from episode clock (persists after flush to thread). */
      reasoning_elapsed_ms?: number;
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
      /** Mutation tool: waiting for user approve/reject (NDJSON ``pending_confirmation``). */
      pending_confirmation?: boolean;
      /** Parsed JSON tool return (``hof fn`` / TUI auto-style render). */
      data?: unknown;
      /** From stream: tool runner outcome (HTTP-shaped code for UI only). */
      ok?: boolean;
      status_code?: number;
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

export function collectThreadAttachments(
  items: ThreadItem[],
): AgentAttachment[] {
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
 * User messages: filled bubble. Assistant replies: plain prose wrapper (no bg/border — one style
 * for pre-tool and post-tool). Radii for user bubble come from app `@theme` / design-system.
 */
export const CHAT_USER_BUBBLE_CLASS =
  "max-w-full rounded-lg bg-hover px-4 py-2.5 text-sm leading-relaxed text-foreground";

/** Same horizontal rail as thinking, tool cards, and assistant text (avoids mixed widths). */
export const AGENT_CHAT_COLUMN_CLASS =
  "w-full max-w-[min(100%,42rem)]";

export const CHAT_ASSISTANT_REPLY_BUBBLE_CLASS =
  `${AGENT_CHAT_COLUMN_CLASS} text-sm leading-relaxed text-foreground`;

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

/** User bubble body: raw ``content`` only (attachments render as chips separately). */
export function userMessageDisplayText(
  content: string,
  _hasAttachments: boolean,
): string {
  return content.trim();
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

export function toolResultAwaitingUserConfirmation(
  blocks: LiveBlock[],
): boolean {
  return blocks.some((b) => {
    if (b.kind !== "tool_result") {
      return false;
    }
    if (b.pending_confirmation === true) {
      return true;
    }
    const s = b.summary;
    return typeof s === "string" && /awaiting your confirmation/i.test(s);
  });
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
export type AgentApplyStreamCtx = {
  assistantStreamPhase: "model" | "summary" | null;
  /** Wall time when ``assistant_done`` is applied; used with ``thinkingEpisodeStartedAtMs``. */
  assistantDoneClockMs?: number;
  /** Start of the current thinking episode (from stream consumer). */
  thinkingEpisodeStartedAtMs?: number | null;
};

function reasoningElapsedStamp(
  ctx: AgentApplyStreamCtx,
): { reasoning_elapsed_ms: number } | Record<string, never> {
  const ep = ctx.thinkingEpisodeStartedAtMs;
  const clock = ctx.assistantDoneClockMs;
  if (
    typeof ep === "number" &&
    typeof clock === "number" &&
    Number.isFinite(ep) &&
    Number.isFinite(clock)
  ) {
    return { reasoning_elapsed_ms: Math.max(0, Math.round(clock - ep)) };
  }
  return {};
}

/** Final lane after a model turn completes (streaming path uses reply shell + opacity until this is set). */
export function computeAssistantUiLane(
  streamPhase: "model" | "summary" | undefined,
  finishReason: string | undefined,
): "thinking" | "reply" {
  if (streamPhase === "summary") {
    return "reply";
  }
  if (finishReason === "tool_calls") {
    return "thinking";
  }
  return "reply";
}

function mergeStreamTextRole(
  prior: "content" | "reasoning" | "mixed" | undefined,
  incoming: "content" | "reasoning",
): "content" | "reasoning" | "mixed" {
  // `phase: model` creates an empty streaming row without a role so the first
  // `reasoning_delta` maps to `reasoning` (ReasoningStreamPeek), not `mixed`.
  if (prior === undefined) {
    return incoming;
  }
  if (prior === "mixed") {
    return "mixed";
  }
  if (prior === incoming) {
    return incoming;
  }
  return "mixed";
}

/** Lane when finalizing a streaming assistant block (`assistant_done`). */
function assistantDoneUiLane(
  finishReason: string | undefined,
  streamPhase: "model" | "summary" | undefined,
): "thinking" | "reply" {
  return computeAssistantUiLane(streamPhase, finishReason);
}

export function inferAssistantUiLane(
  b: Extract<LiveBlock, { kind: "assistant" }>,
): "thinking" | "reply" {
  if (b.uiLane === "thinking" || b.uiLane === "reply") {
    // Older clients stamped reasoning-channel + `stop` as `thinking`; that prose is the visible reply.
    if (
      b.uiLane === "thinking" &&
      b.finishReason === "stop" &&
      b.streamPhase !== "summary"
    ) {
      return "reply";
    }
    return b.uiLane;
  }
  return computeAssistantUiLane(b.streamPhase, b.finishReason);
}

function withoutThinkingSkeleton(blocks: LiveBlock[]): LiveBlock[] {
  return blocks.filter((b) => b.kind !== "thinking_skeleton");
}

/** Remove a trailing in-flight assistant row with no text (placeholder for the next model round). */
function dropTrailingEmptyStreamingAssistant(blocks: LiveBlock[]): LiveBlock[] {
  if (blocks.length === 0) {
    return blocks;
  }
  const last = blocks[blocks.length - 1];
  if (last.kind === "assistant" && last.streaming && last.text.trim() === "") {
    return blocks.slice(0, -1);
  }
  return blocks;
}

/** Model moved on to tools / approval — prose is complete even if `assistant_done` is not here yet. */
function finalizeStreamingAssistantBeforeStructuredStep(
  blocks: LiveBlock[],
): LiveBlock[] {
  for (let k = blocks.length - 1; k >= 0; k--) {
    const bl = blocks[k];
    if (bl?.kind === "assistant" && bl.streaming) {
      return [
        ...blocks.slice(0, k),
        {
          ...bl,
          streaming: false,
          pendingStreamFinalize: true,
        },
        ...blocks.slice(k + 1),
      ];
    }
  }
  return blocks;
}

function clearAssistantPendingStreamFinalize(blocks: LiveBlock[]): LiveBlock[] {
  return blocks.map((b) => {
    if (b.kind !== "assistant" || !b.pendingStreamFinalize) {
      return b;
    }
    const { pendingStreamFinalize: _p, ...rest } = b;
    return rest as LiveBlock;
  });
}

function assistantRowMatchesAssistantDone(
  b: LiveBlock,
): b is Extract<LiveBlock, { kind: "assistant" }> {
  return (
    b.kind === "assistant" &&
    Boolean(b.streaming || b.pendingStreamFinalize)
  );
}

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
    // `phase: model` often arrives long before the first `assistant_delta`. Many tool turns emit
    // *no* content deltas (straight to `tool_calls`), so we show `thinking_skeleton` until tokens
    // or `tool_call`. Plain `phase` rows were too easy to miss; empty `liveBlocks` forced only
    // “Connecting…”.
    if (phase === "model") {
      const base = withoutThinkingSkeleton(prev);
      // Always tag model rounds from the wire event. Do not rely on ctx.assistantStreamPhase here:
      // React may run this updater after later events batched ref updates, leaving streamPhase
      // undefined so LiveBlockView skips the model shell and shows the wrong empty state.
      return [
        ...base,
        {
          kind: "assistant",
          id: newId(),
          text: "",
          streaming: true,
          streamPhase: "model",
        },
      ];
    }
    return [...prev, { kind: "phase", id: newId(), round, phase }];
  }
  if (t === "segment_start") {
    const raw = ev.segment;
    const seg = raw === "reasoning" || raw === "content" ? raw : null;
    if (!seg) {
      return prev;
    }
    const base = withoutThinkingSkeleton(prev);
    const last = base[base.length - 1];
    if (last?.kind !== "assistant" || !last.streaming) {
      return prev;
    }
    const segs = [...(last.streamSegments ?? [])];
    segs.push({ kind: seg, text: "" });
    const sp = stampStreamPhase(ctx, last.streamPhase);
    return [
      ...base.slice(0, -1),
      {
        ...last,
        streamSegments: segs,
        ...(sp ? { streamPhase: sp } : {}),
      },
    ];
  }
  if (t === "assistant_delta" || t === "reasoning_delta") {
    const chunk = typeof ev.text === "string" ? ev.text : "";
    const incoming: "content" | "reasoning" =
      t === "reasoning_delta" ? "reasoning" : "content";
    const base = withoutThinkingSkeleton(prev);
    const last = base[base.length - 1];
    if (last?.kind === "assistant" && last.streaming) {
      const sp = stampStreamPhase(ctx, last.streamPhase);
      const nextRole = mergeStreamTextRole(last.streamTextRole, incoming);
      const nextSegs = appendAssistantStreamSegmentChunk(
        last.streamSegments,
        incoming,
        chunk,
      );
      return [
        ...base.slice(0, -1),
        {
          ...last,
          text: last.text + chunk,
          streamTextRole: nextRole,
          streamSegments: nextSegs,
          ...(sp ? { streamPhase: sp } : {}),
        },
      ];
    }
    const spNew = stampStreamPhase(ctx);
    return [
      ...base,
      {
        kind: "assistant",
        id: newId(),
        text: chunk,
        streaming: true,
        streamTextRole: incoming,
        streamSegments: appendAssistantStreamSegmentChunk(
          undefined,
          incoming,
          chunk,
        ),
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
      if (assistantRowMatchesAssistantDone(bl)) {
        streamingIdx = k;
        break;
      }
    }
    if (streamingIdx >= 0) {
      const trimmed = withoutThinkingSkeleton(prev);
      let si = -1;
      for (let k = trimmed.length - 1; k >= 0; k--) {
        const bl = trimmed[k];
        if (assistantRowMatchesAssistantDone(bl)) {
          si = k;
          break;
        }
      }
      if (si < 0) {
        const spFallback = stampStreamPhase(ctx);
        const laneFallback = computeAssistantUiLane(spFallback, fr);
        const fbStamp = reasoningElapsedStamp(ctx);
        return [
          ...trimmed,
          {
            kind: "assistant",
            id: newId(),
            text: "",
            streaming: false,
            finishReason: fr,
            usage: u,
            uiLane: laneFallback,
            ...(spFallback ? { streamPhase: spFallback } : {}),
            ...fbStamp,
          },
        ];
      }
      const last = trimmed[si] as Extract<LiveBlock, { kind: "assistant" }>;
      const { pendingStreamFinalize: _pFin, ...lastWithoutPending } = last;
      const sp = stampStreamPhase(ctx, last.streamPhase);
      const effPhase = sp ?? last.streamPhase;
      const lane = assistantDoneUiLane(fr, effPhase);
      const reasoningStamp = reasoningElapsedStamp(ctx);
      let streamSegmentsOut: AssistantStreamSegment[] | undefined;
      if (last.streamSegments?.length) {
        const n = normalizeAssistantStreamSegments(last.streamSegments);
        // Never wipe segments on a bad normalize edge case (user saw thinking, then it vanished).
        streamSegmentsOut = n.length > 0 ? n : last.streamSegments;
      } else {
        streamSegmentsOut = last.streamSegments;
      }
      return [
        ...trimmed.slice(0, si),
        {
          ...lastWithoutPending,
          streaming: false,
          finishReason: fr,
          usage: u,
          uiLane: lane,
          streamSegments: streamSegmentsOut,
          ...(sp ? { streamPhase: sp } : {}),
          ...reasoningStamp,
        },
        ...trimmed.slice(si + 1),
      ];
    }
    const spFallback = stampStreamPhase(ctx);
    const laneFallback = computeAssistantUiLane(spFallback, fr);
    return [
      ...prev,
      {
        kind: "assistant",
        id: newId(),
        text: "",
        streaming: false,
        finishReason: fr,
        usage: u,
        uiLane: laneFallback,
        ...(spFallback ? { streamPhase: spFallback } : {}),
        ...reasoningElapsedStamp(ctx),
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
    const base = dropTrailingEmptyStreamingAssistant(
      withoutThinkingSkeleton(prev),
    );
    const ready = finalizeStreamingAssistantBeforeStructuredStep(base);
    return [
      ...ready,
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
    const pending =
      ev.pending_confirmation === true ||
      ev.pending_confirmation === "true" ||
      ev.pending_confirmation === 1;
    const okRaw = (ev as { ok?: unknown }).ok;
    const ok = typeof okRaw === "boolean" ? okRaw : undefined;
    const scRaw = (ev as { status_code?: unknown }).status_code;
    const status_code =
      typeof scRaw === "number" && Number.isFinite(scRaw)
        ? scRaw
        : typeof scRaw === "string" && /^\d+$/.test(scRaw.trim())
          ? parseInt(scRaw.trim(), 10)
          : undefined;
    const ready = finalizeStreamingAssistantBeforeStructuredStep(
      withoutThinkingSkeleton(prev),
    );
    return [
      ...ready,
      {
        kind: "tool_result",
        id: newId(),
        name,
        summary,
        ...(pending ? { pending_confirmation: true as const } : {}),
        ...(hasData ? { data } : {}),
        ...(ok !== undefined ? { ok } : {}),
        ...(status_code !== undefined ? { status_code } : {}),
      },
    ];
  }
  if (t === "mutation_pending") {
    const pending_id = typeof ev.pending_id === "string" ? ev.pending_id : "";
    const name = typeof ev.name === "string" ? ev.name : "";
    const cli_line = typeof ev.cli_line === "string" ? ev.cli_line : "";
    const args = typeof ev.arguments === "string" ? ev.arguments : "";
    const ready = finalizeStreamingAssistantBeforeStructuredStep(
      withoutThinkingSkeleton(prev),
    );
    return [
      ...ready,
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
    const ready = finalizeStreamingAssistantBeforeStructuredStep(
      withoutThinkingSkeleton(prev),
    );
    return [
      ...ready,
      { kind: "approval_required", id: newId(), run_id, pending_ids },
    ];
  }
  if (t === "error") {
    const detail = typeof ev.detail === "string" ? ev.detail : "error";
    const ready = finalizeStreamingAssistantBeforeStructuredStep(
      withoutThinkingSkeleton(prev),
    );
    return [...ready, { kind: "error", id: newId(), detail }];
  }
  // Terminal / control events — reply already streamed via assistant_*; do not add UI blocks.
  if (t === "final") {
    return clearAssistantPendingStreamFinalize(prev);
  }
  if (t === "cancelled") {
    return clearAssistantPendingStreamFinalize(prev);
  }
  if (t === "resume_start" || t === "run_start") {
    return prev;
  }
  return prev;
}

export type ToolCallBlock = Extract<LiveBlock, { kind: "tool_call" }>;
export type MutationPendingBlock = Extract<
  LiveBlock,
  { kind: "mutation_pending" }
>;
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
export function dropRedundantModelPhaseBeforeAssistant(
  blocks: LiveBlock[],
): LiveBlock[] {
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
  const segText = b.streamSegments?.some((s) => s.text.trim()) ?? false;
  return b.finishReason === "tool_calls" && !t && !segText;
}

export function normalizeAssistantTextForDedupe(s: string): string {
  return s.replace(/\s+/g, " ").trim();
}

/**
 * Rare stream / multi-round edge cases can yield two completed assistant rows with the same
 * body; the UI would show duplicate reply bubbles. Collapse consecutive duplicates.
 */
function assistantDedupeFingerprint(
  b: Extract<LiveBlock, { kind: "assistant" }>,
): string {
  if (b.streamSegments?.length) {
    return b.streamSegments.map((s) => s.text).join("\n");
  }
  return b.text;
}

export function dedupeAdjacentDuplicateAssistants(
  blocks: LiveBlock[],
): LiveBlock[] {
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
        const a = normalizeAssistantTextForDedupe(
          assistantDedupeFingerprint(pa),
        );
        const c = normalizeAssistantTextForDedupe(
          assistantDedupeFingerprint(cur),
        );
        if (a.length > 0 && a === c) {
          continue;
        }
      }
    }
    out.push(b);
  }
  return out;
}

/**
 * Turn in-flight stream state into storable thread blocks after the user hits Stop
 * (fetch aborted). Finalizes streaming assistant rows, stamps ``cancelled`` when the
 * model never sent ``assistant_done``, then applies the same compaction as a normal run.
 */
export function finalizeLiveBlocksAfterUserStop(blocks: LiveBlock[]): LiveBlock[] {
  const mapped = blocks.map((b) => {
    if (b.kind !== "assistant") {
      return b;
    }
    const a = b as Extract<LiveBlock, { kind: "assistant" }>;
    if (!a.streaming) {
      const { pendingStreamFinalize: _p, ...rest } = a;
      return rest as Extract<LiveBlock, { kind: "assistant" }>;
    }
    const { pendingStreamFinalize: _p, ...rest } = a;
    const hadFinish =
      rest.finishReason !== undefined && rest.finishReason !== null;
    return {
      ...rest,
      streaming: false,
      finishReason: hadFinish ? rest.finishReason : "cancelled",
    } as Extract<LiveBlock, { kind: "assistant" }>;
  });
  const noEmptyCancelledShell = mapped.filter((b) => {
    if (b.kind !== "assistant") {
      return true;
    }
    const a = b as Extract<LiveBlock, { kind: "assistant" }>;
    if (a.finishReason !== "cancelled") {
      return true;
    }
    const t = a.text.trim();
    const hasSegText = a.streamSegments?.some((s) => s.text.trim()) ?? false;
    return t.length > 0 || hasSegText;
  });
  return compactBlocksForHistory(noEmptyCancelledShell);
}

/** Drop noisy rows before persisting a completed run to the thread. */
export function compactBlocksForHistory(blocks: LiveBlock[]): LiveBlock[] {
  const base = dropRedundantModelPhaseBeforeAssistant(blocks).filter((b) => {
    if (b.kind === "assistant" && isEphemeralAssistantShell(b)) {
      return false;
    }
    return b.kind !== "thinking_skeleton";
  });
  const deduped = dedupeAdjacentDuplicateAssistants(base);
  return deduped.map((b) => {
    if (b.kind !== "assistant") {
      return b;
    }
    let out = b as Extract<LiveBlock, { kind: "assistant" }>;
    if (out.pendingStreamFinalize) {
      const { pendingStreamFinalize: _p, ...rest } = out;
      out = rest as Extract<LiveBlock, { kind: "assistant" }>;
    }
    if (out.streaming) {
      out = { ...out, streaming: false };
    }
    return out;
  });
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
    if (b.kind === "thinking_skeleton") {
      out.push({ type: "single", block: b });
      i += 1;
      continue;
    }
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
  return b.arguments.length > 600
    ? `${b.arguments.slice(0, 600)}…`
    : b.arguments;
}

/** True when tool `arguments` is missing, whitespace, or empty `{}` / `[]` (JSON). */
export function toolArgumentsAreEffectivelyEmpty(
  argumentsStr: string | undefined | null,
): boolean {
  if (argumentsStr == null || !argumentsStr.trim()) {
    return true;
  }
  const t = argumentsStr.trim();
  if (t === "{}" || t === "[]") {
    return true;
  }
  try {
    const v = JSON.parse(t) as unknown;
    if (
      v !== null &&
      typeof v === "object" &&
      !Array.isArray(v) &&
      Object.keys(v as object).length === 0
    ) {
      return true;
    }
    if (Array.isArray(v) && v.length === 0) {
      return true;
    }
  } catch {
    /* non-JSON still counts as non-empty for the dialog affordance */
  }
  return false;
}

export function isGenericAwaitingConfirmationSummary(summary: string): boolean {
  return /awaiting your confirmation/i.test(summary.trim());
}

export type ToolResultUiStatus = {
  code: number;
  label: string;
  tone: "success" | "error" | "warning" | "pending";
};

/** Human-readable HTTP-shaped status for the tool row (stream fields + fallbacks). */
export function toolResultUiStatus(
  result: Pick<
    ToolResultBlock,
    "pending_confirmation" | "data" | "summary" | "ok" | "status_code"
  >,
): ToolResultUiStatus {
  if (result.pending_confirmation) {
    return {
      code: result.status_code ?? 202,
      label: "Awaiting confirmation",
      tone: "pending",
    };
  }
  if (
    result.status_code !== undefined &&
    Number.isFinite(result.status_code)
  ) {
    const code = result.status_code;
    const ok = result.ok;
    if (ok === false || code >= 400) {
      const label =
        code === 422
          ? "Validation error"
          : code === 403
            ? "Not allowed"
            : code === 400
              ? "Bad request"
              : code === 501
                ? "Unsupported"
                : code === 499
                  ? "Rejected"
                  : "Error";
      return { code, label, tone: "error" };
    }
    if (ok === true || (code >= 200 && code < 400)) {
      return { code, label: "OK", tone: "success" };
    }
    return { code, label: "OK", tone: "success" };
  }
  const data = result.data;
  if (
    data !== null &&
    typeof data === "object" &&
    !Array.isArray(data) &&
    "error" in data
  ) {
    return { code: 502, label: "Tool error", tone: "error" };
  }
  const s = result.summary?.trim() ?? "";
  if (/^error:/i.test(s)) {
    return { code: 502, label: "Error", tone: "error" };
  }
  return { code: 200, label: "OK", tone: "success" };
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
    if (
      mutation &&
      (result.pending_confirmation === true ||
        isGenericAwaitingConfirmationSummary(s))
    ) {
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

/** After resume; `true` = approved, `false` = rejected. `null` = nothing to say (cards show outcome). */
export function confirmationFooterFromOutcomes(
  pendingIds: string[],
  outcomes: Record<string, boolean | undefined>,
): string | null {
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
    return null;
  }
  if (rejected === 0 || approved === 0) {
    return null;
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
  return inferAssistantUiLane(b) === "thinking" ? "reasoning" : "reply";
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
