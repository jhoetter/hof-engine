import type { HofStreamEvent } from "../hooks/streamHofFunction";
import type { AssistantStreamSegment } from "./assistantStreamSegments";
import type {
  PlanClarificationQuestion,
  StructuredPlanProposal,
} from "./conversationTypes";
import { preferPlanTaskListBody } from "./planMarkdownTodos";
import {
  PLAN_TODO_UPDATE_EVENT_TYPE,
  type PlanTodoUpdateEvent,
} from "./planTodoStream";
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

/** Wire shape from NDJSON ``awaiting_inbox_review`` (matches engine ``inbox_watch_to_wire``). */
export type InboxReviewWatchWire = {
  watch_id: string;
  record_type: string;
  record_id: string;
  label?: string;
  url?: string;
  path?: string;
};

export type InboxReviewBarrier = {
  runId: string;
  watches: InboxReviewWatchWire[];
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
      /** Stamped from context on ``assistant_done``: plan-discover phase string for the settled row (e.g. "Generating questions"; UI may show past tense). */
      reasoningLabel?: string;
    }
  | {
      kind: "tool_call";
      id: string;
      name: string;
      cli_line: string;
      arguments?: string;
      /** Short technical note from server for the expandable row (not chat prose). */
      internal_rationale?: string;
      /** Provider tool call id — pairs with {@link tool_result.tool_call_id} (final result after resume). */
      tool_call_id?: string;
      /** From NDJSON ``display_title``: short contextual label for the tool row (optional). */
      displayTitle?: string;
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
      /** Same id as the matching {@link tool_call.tool_call_id} row. */
      tool_call_id?: string;
    }
  | {
      kind: "mutation_pending";
      id: string;
      pending_id: string;
      name: string;
      cli_line: string;
      arguments_preview?: string;
      /** Server-computed preview (JSON) before the mutation runs; same payload as tool placeholder. */
      preview?: unknown;
    }
  | {
      kind: "mutation_applied";
      id: string;
      pending_id: string;
      name: string;
      tool_call_id?: string;
      /** From NDJSON ``mutation_applied`` after the mutation executed (ground-truth review hint). */
      post_apply_review: {
        label: string;
        url?: string;
        path?: string;
      };
    }
  | {
      kind: "continuation_marker";
      id: string;
    }
  | {
      kind: "approval_required";
      id: string;
      run_id: string;
      pending_ids: string[];
    }
  | {
      kind: "inbox_review_required";
      id: string;
      run_id: string;
      watches: InboxReviewWatchWire[];
    }
  | {
      kind: "error";
      id: string;
      detail: string;
      errorCategory?: string;
      retryAfterSeconds?: number;
      retryable?: boolean;
      technicalDetail?: string;
      httpStatus?: number;
    }
  /**
   * One or more plan checklist items completed during ``plan_execute`` (from ``plan_todo_update``).
   * ``done_indices`` is the delta for this row (new indices vs prior ``plan_step_progress`` blocks).
   */
  | {
      kind: "plan_step_progress";
      id: string;
      done_indices: number[];
    };

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

/** Thread marker when the user runs an approved plan (compact UI; plan body is sent as `plan_text`). */
export const PLAN_EXECUTE_USER_MARKER = "[plan:execute]";

/**
 * Plan discovery: approved plan markdown is **not** streamed as ``assistant_delta``. The engine
 * validates ``hof_builtin_present_plan`` tool arguments and emits ``final`` with ``structured_plan``
 * (see ``plan_text_source: structured_tool`` on the wire). The UI fills the plan card from that
 * ``final`` only; pre-final assistant tokens stay in the chat rail.
 */

/** Same horizontal rail as thinking, tool cards, and assistant text (avoids mixed widths). */
export const AGENT_CHAT_COLUMN_CLASS = "w-full max-w-[min(100%,42rem)]";

export const CHAT_ASSISTANT_REPLY_BUBBLE_CLASS = `${AGENT_CHAT_COLUMN_CLASS} text-sm leading-relaxed text-foreground`;

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

/** Wire name for Docker-backed terminal transport (not the domain function). */
export const HOF_BUILTIN_TERMINAL_EXEC = "hof_builtin_terminal_exec";

/**
 * Extract domain `@function` name from a shell snippet inside terminal exec (`hof fn …` or `…/api/functions/<name>`).
 */
export function extractFunctionNameFromShellCommand(cmd: string): string | null {
  const t = cmd.trim();
  if (!t) {
    return null;
  }
  const hofFn = /\bhof\s+fn\s+([a-zA-Z0-9_]+)/.exec(t);
  if (hofFn?.[1]) {
    return hofFn[1].trim();
  }
  const apiFn = /\/api\/functions\/([a-zA-Z0-9_]+)/.exec(t);
  if (apiFn?.[1]) {
    return apiFn[1].trim();
  }
  return null;
}

/**
 * From `hof_builtin_terminal_exec` JSON arguments, resolve the underlying domain function name for UI titles / CLI.
 */
export function underlyingFunctionFromTerminalExecArguments(
  argumentsJson: string | undefined,
): string | null {
  if (!argumentsJson?.trim()) {
    return null;
  }
  let o: Record<string, unknown>;
  try {
    const p = JSON.parse(argumentsJson) as unknown;
    if (!p || typeof p !== "object" || Array.isArray(p)) {
      return null;
    }
    o = p as Record<string, unknown>;
  } catch {
    return null;
  }
  const cmd = typeof o.command === "string" ? o.command : "";
  return extractFunctionNameFromShellCommand(cmd);
}

/**
 * Extract the raw shell command string from terminal exec arguments JSON.
 * Returns null when parsing fails or `command` is missing.
 */
export function rawShellCommandFromTerminalExecArguments(
  argumentsJson: string | undefined,
): string | null {
  if (!argumentsJson?.trim()) {
    return null;
  }
  try {
    const p = JSON.parse(argumentsJson) as unknown;
    if (!p || typeof p !== "object" || Array.isArray(p)) {
      return null;
    }
    const o = p as Record<string, unknown>;
    const cmd = typeof o.command === "string" ? o.command.trim() : "";
    return cmd || null;
  } catch {
    return null;
  }
}

function looksLikeTerminalTransportCli(line: string): boolean {
  const t = line.trim();
  if (!t) {
    return false;
  }
  if (/curl\s+/i.test(t)) {
    return true;
  }
  if (/\bhof\s+fn\s+hof_builtin_terminal_exec\b/i.test(t)) {
    return true;
  }
  if (t.includes("hof_builtin_terminal_exec")) {
    return true;
  }
  return false;
}

const _TOOL_TITLE_ATTACHMENT_EXT_RE =
  /\.(pdf|png|jpe?g|gif|webp|csv|xlsx?|txt)$/i;

function _toolTitleBasenameKey(key: string): string {
  const k = key.trim().replace(/\\/g, "/");
  const i = k.lastIndexOf("/");
  return (i >= 0 ? k.slice(i + 1) : k).trim();
}

function _toolTitleIdSnippet(v: unknown, maxChars: number): string | null {
  if (typeof v === "number" && Number.isFinite(v)) {
    return String(v);
  }
  if (typeof v === "string" && v.trim()) {
    const s = v.trim();
    return s.length > maxChars ? `${s.slice(0, maxChars)}…` : s;
  }
  return null;
}

/** True when the model title looks like only a file / token (needs the tool name prefix). */
function _looksLikeFilenameOrBareTokenTitle(s: string): boolean {
  const t = s.trim();
  if (!t) {
    return false;
  }
  if (_TOOL_TITLE_ATTACHMENT_EXT_RE.test(t)) {
    return true;
  }
  if (!t.includes(" ") && t.includes(".") && t.length <= 120) {
    return true;
  }
  if (!t.includes(" ") && t.length > 0 && t.length <= 36) {
    return true;
  }
  return false;
}

/** True when the model already wrote a full phrase (keep as-is). */
function _looksLikeRichDisplayTitle(s: string): boolean {
  const t = s.trim();
  if (!t) {
    return false;
  }
  if (/[:—–-]/.test(t)) {
    return true;
  }
  if (/\s#\d+\b/.test(t)) {
    return true;
  }
  const lower = t.toLowerCase();
  const starters = [
    "register",
    "upload",
    "loading",
    "fetch",
    "get ",
    "create",
    "update",
    "delete",
    "list ",
    "remov",
    "approv",
    "reject",
    "saving",
    "deleting",
    "draft",
    "resolv",
  ];
  if (starters.some((x) => lower.startsWith(x))) {
    return true;
  }
  if (t.includes(" · ") || t.includes(" — ")) {
    return true;
  }
  return false;
}

/**
 * Short target hint from tool JSON arguments when ``display_title`` is absent (e.g. ``#3``, basename of
 * ``object_key``, id snippet).
 */
export function toolRowContextFromArguments(
  toolName: string,
  rawArgs: string | undefined,
): string | null {
  if (!rawArgs?.trim()) {
    return null;
  }
  let o: Record<string, unknown>;
  try {
    const p = JSON.parse(rawArgs) as unknown;
    if (!p || typeof p !== "object" || Array.isArray(p)) {
      return null;
    }
    o = p as Record<string, unknown>;
  } catch {
    return null;
  }
  const fn = toolName.trim();
  for (const k of ["file_name", "filename", "attachment_name"]) {
    const v = o[k];
    if (typeof v === "string" && v.trim()) {
      return v.trim().slice(0, 80);
    }
  }
  const nameVal = o.name;
  if (typeof nameVal === "string" && nameVal.trim()) {
    return nameVal.trim().slice(0, 80);
  }
  for (const k of ["object_key", "s3_key", "receipt_object_key"]) {
    const v = o[k];
    if (typeof v === "string" && v.trim()) {
      const b = _toolTitleBasenameKey(v);
      if (b) {
        return b.slice(0, 80);
      }
    }
  }
  const ds = o.display_seq;
  if (typeof ds === "number" && Number.isFinite(ds)) {
    return `#${ds}`;
  }
  if (typeof ds === "string" && /^\d+$/.test(ds.trim())) {
    return `#${ds.trim()}`;
  }
  if (
    fn.startsWith("get_") ||
    fn.startsWith("update_") ||
    fn.startsWith("delete_")
  ) {
    const id = _toolTitleIdSnippet(o.id, 12);
    if (id) {
      return id.length > 10 ? `id ${id}` : id;
    }
  }
  for (const k of [
    "expense_id",
    "revenue_id",
    "budget_id",
    "receipt_document_id",
    "record_id",
  ]) {
    const sn = _toolTitleIdSnippet(o[k], 12);
    if (sn) {
      return sn;
    }
  }
  return null;
}

/**
 * Row heading for tool cards: combines humanized tool name, optional ``display_title``, and argument hints
 * so parallel calls stay distinguishable and bare filenames still show which tool ran.
 */
export function toolCallRowTitle(call: {
  name: string;
  displayTitle?: string;
  arguments?: string;
}): string {
  const effectiveName =
    call.name.trim() === HOF_BUILTIN_TERMINAL_EXEC
      ? (underlyingFunctionFromTerminalExecArguments(call.arguments) ??
        call.name)
      : call.name;
  const base = humanizeToolName(effectiveName);
  const dt = call.displayTitle?.trim();
  const ctx = toolRowContextFromArguments(effectiveName, call.arguments);

  if (dt) {
    if (_looksLikeRichDisplayTitle(dt)) {
      return dt;
    }
    if (_looksLikeFilenameOrBareTokenTitle(dt)) {
      return `${base} · ${dt}`;
    }
    return dt;
  }

  if (ctx) {
    return `${base} · ${ctx}`;
  }
  return base;
}

/** Parse wire ``post_apply_review`` object (label + optional url/path). */
export function postApplyReviewFromWire(
  pr: unknown,
): { href: string; label: string; path?: string } | null {
  if (pr == null || typeof pr !== "object" || Array.isArray(pr)) {
    return null;
  }
  const prO = pr as Record<string, unknown>;
  const label = typeof prO.label === "string" ? prO.label.trim() : "";
  if (!label) {
    return null;
  }
  const url = typeof prO.url === "string" ? prO.url.trim() : "";
  const path = typeof prO.path === "string" ? prO.path.trim() : "";
  if (url) {
    return { href: url, label, ...(path ? { path } : {}) };
  }
  if (path.startsWith("/")) {
    return { href: path, label, path };
  }
  return null;
}

/**
 * Post-apply review hint from a mutation **preview** or pending **tool_result.data** envelope
 * (`post_apply_review`: label + optional url/path).
 */
export function postApplyReviewFromPreview(
  preview: unknown,
): { href: string; label: string; path?: string } | null {
  if (
    preview == null ||
    typeof preview !== "object" ||
    Array.isArray(preview)
  ) {
    return null;
  }
  const o = preview as Record<string, unknown>;
  return postApplyReviewFromWire(o.post_apply_review);
}

/** One-line summary for pending-mutation preview in the approval bar (engine `MutationPreviewResult.summary`). */
export function formatPendingPreviewLine(preview: unknown): string {
  if (preview == null) {
    return "";
  }
  if (typeof preview === "string") {
    return preview.length > 140 ? `${preview.slice(0, 137)}…` : preview;
  }
  if (typeof preview === "object" && preview !== null) {
    const o = preview as Record<string, unknown>;
    const sum = o.summary;
    if (typeof sum === "string" && sum.trim()) {
      const t = sum.trim();
      return t.length > 140 ? `${t.slice(0, 137)}…` : t;
    }
    if (typeof o.note === "string" && o.note.trim()) {
      const n = o.note.trim();
      return n.length > 140 ? `${n.slice(0, 137)}…` : n;
    }
    try {
      const s = JSON.stringify(preview);
      return s.length > 160 ? `${s.slice(0, 157)}…` : s;
    } catch {
      return "";
    }
  }
  return String(preview);
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

/**
 * Parse a ``awaiting_plan_clarification`` terminal stream event into a typed barrier,
 * or return ``null`` if the event is malformed.
 */
export function parsePlanClarificationBarrierFromTerm(
  term: unknown,
): {
  runId: string;
  clarificationId: string;
  questions: PlanClarificationQuestion[];
} | null {
  if (!term || typeof term !== "object") {
    return null;
  }
  const t = term as Record<string, unknown>;
  const runId = coerceRunId(t.run_id);
  const clarificationId = String(t.clarification_id ?? "").trim();
  const qs = t.questions;
  const questions: PlanClarificationQuestion[] = [];
  if (Array.isArray(qs)) {
    for (const raw of qs) {
      if (raw && typeof raw === "object") {
        const o = raw as Record<string, unknown>;
        const id = String(o.id ?? "").trim();
        const prompt = String(o.prompt ?? "").trim();
        const optsRaw = o.options;
        const options: { id: string; label: string }[] = [];
        if (Array.isArray(optsRaw)) {
          for (const op of optsRaw) {
            if (op && typeof op === "object") {
              const ox = op as Record<string, unknown>;
              const oid = String(ox.id ?? "").trim();
              const lab = String(ox.label ?? "").trim();
              if (oid && lab) {
                options.push({ id: oid, label: lab });
              }
            }
          }
        }
        if (id && prompt && options.length >= 2) {
          questions.push({
            id,
            prompt,
            options,
            allow_multiple: Boolean(o.allow_multiple),
          });
        }
      }
    }
  }
  if (!runId || !clarificationId || questions.length === 0) {
    return null;
  }
  return { runId, clarificationId, questions };
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

/** Parse NDJSON ``awaiting_inbox_review`` for context + ``applyStreamEvent``. */
export function inboxReviewBarrierFromStreamEvent(
  ev: HofStreamEvent,
): InboxReviewBarrier | null {
  if (typeof ev.type !== "string" || ev.type !== "awaiting_inbox_review") {
    return null;
  }
  const runId = coerceRunId(ev.run_id);
  const rawW = Array.isArray((ev as { watches?: unknown }).watches)
    ? ((ev as { watches: unknown[] }).watches as unknown[])
    : [];
  const watches: InboxReviewWatchWire[] = [];
  for (const x of rawW) {
    if (x == null || typeof x !== "object" || Array.isArray(x)) {
      continue;
    }
    const o = x as Record<string, unknown>;
    const watch_id = String(o.watch_id ?? "").trim();
    const record_type = String(o.record_type ?? "").trim();
    const record_id = String(o.record_id ?? "").trim();
    if (!watch_id || !record_type || !record_id) {
      continue;
    }
    const label = typeof o.label === "string" ? o.label.trim() : undefined;
    const url = typeof o.url === "string" ? o.url.trim() : undefined;
    const path = typeof o.path === "string" ? o.path.trim() : undefined;
    watches.push({
      watch_id,
      record_type,
      record_id,
      ...(label ? { label } : {}),
      ...(url ? { url } : {}),
      ...(path ? { path } : {}),
    });
  }
  if (!runId || watches.length === 0) {
    return null;
  }
  return { runId, watches };
}

export function inboxReviewOpenHref(w: InboxReviewWatchWire): string | null {
  const u = w.url?.trim();
  if (u) {
    return u;
  }
  const p = w.path?.trim();
  if (p?.startsWith("/")) {
    return p;
  }
  return null;
}

/** Passed into `applyStreamEvent` so assistant rows match stream `phase` (model vs summary). */
export type AgentApplyStreamCtx = {
  assistantStreamPhase: "model" | "summary" | null;
  /** Wall time when ``assistant_done`` is applied; used with ``thinkingEpisodeStartedAtMs``. */
  assistantDoneClockMs?: number;
  /** Start of the current thinking episode (from stream consumer). */
  thinkingEpisodeStartedAtMs?: number | null;
  /** Stamped onto the assistant block on ``assistant_done`` for settled reasoning label (plan-discover phase string). */
  reasoningLabel?: string | null;
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
    // `finishReason === "tool_calls"` is stamped as `thinking`, but the visible stream is often
    // user-facing prose (assistant_delta) before the next tool — not internal reasoning. Show as
    // reply so it is not labeled "Thought" (plan_discover clarify → questions is the main case).
    if (
      b.uiLane === "thinking" &&
      b.finishReason === "tool_calls" &&
      b.streamPhase === "model"
    ) {
      if (b.streamTextRole === "content" || b.streamTextRole === "mixed") {
        return "reply";
      }
      if (
        b.streamSegments?.some((s) => s.kind === "content" && s.text.trim())
      ) {
        return "reply";
      }
      if (
        b.streamTextRole === "reasoning" &&
        !b.streamSegments?.length &&
        b.text.trim().length >= 80
      ) {
        return "reply";
      }
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
function unionPlanProgressDoneIndices(blocks: LiveBlock[]): Set<number> {
  const s = new Set<number>();
  for (const b of blocks) {
    if (b.kind === "plan_step_progress") {
      for (const x of b.done_indices) {
        s.add(x);
      }
    }
  }
  return s;
}

/** New indices in ``incoming`` vs prior ``plan_step_progress`` rows (handles cumulative or delta wire payloads). */
function deltaPlanTodoIndicesForBlock(
  prev: LiveBlock[],
  incoming: number[],
): number[] {
  const seen = unionPlanProgressDoneIndices(prev);
  return incoming
    .map((x) => Number(x))
    .filter((n) => Number.isFinite(n) && n >= 0 && !seen.has(n))
    .sort((a, b) => a - b);
}

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
    b.kind === "assistant" && Boolean(b.streaming || b.pendingStreamFinalize)
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
    if (phase === "model" || phase === "inbox_review_summary") {
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
      const labelStamp =
        typeof ctx.reasoningLabel === "string" && ctx.reasoningLabel.trim()
          ? { reasoningLabel: ctx.reasoningLabel.trim() }
          : {};
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
          ...labelStamp,
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
    if ((ev as { internal?: unknown }).internal === true) {
      return prev;
    }
    const name = typeof ev.name === "string" ? ev.name : "";
    const args = typeof ev.arguments === "string" ? ev.arguments : "";
    const cli = typeof ev.cli_line === "string" ? ev.cli_line : "";
    const iraw = ev.internal_rationale;
    const internal_rationale =
      typeof iraw === "string" && iraw.trim() ? iraw.trim() : undefined;
    const tcidRaw = (ev as { tool_call_id?: unknown }).tool_call_id;
    const tool_call_id =
      typeof tcidRaw === "string" && tcidRaw.trim()
        ? tcidRaw.trim()
        : undefined;
    const dtraw = (ev as { display_title?: unknown }).display_title;
    const displayTitle =
      typeof dtraw === "string" && dtraw.trim() ? dtraw.trim() : undefined;
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
        ...(tool_call_id ? { tool_call_id } : {}),
        ...(displayTitle ? { displayTitle } : {}),
      },
    ];
  }
  if (t === "tool_result") {
    if ((ev as { internal?: unknown }).internal === true) {
      return prev;
    }
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
    const tcidRaw = (ev as { tool_call_id?: unknown }).tool_call_id;
    const tool_call_id =
      typeof tcidRaw === "string" && tcidRaw.trim()
        ? tcidRaw.trim()
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
        ...(tool_call_id ? { tool_call_id } : {}),
      },
    ];
  }
  if (t === "mutation_pending") {
    const pending_id = typeof ev.pending_id === "string" ? ev.pending_id : "";
    const name = typeof ev.name === "string" ? ev.name : "";
    const cli_line = typeof ev.cli_line === "string" ? ev.cli_line : "";
    const args = typeof ev.arguments === "string" ? ev.arguments : "";
    const hasPreview = Object.prototype.hasOwnProperty.call(ev, "preview");
    const preview = hasPreview
      ? (ev as { preview: unknown }).preview
      : undefined;
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
        ...(hasPreview ? { preview } : {}),
      },
    ];
  }
  if (t === "mutation_applied") {
    const pending_id = typeof ev.pending_id === "string" ? ev.pending_id : "";
    const name = typeof ev.name === "string" ? ev.name : "";
    const tidRaw = (ev as { tool_call_id?: unknown }).tool_call_id;
    const tool_call_id =
      typeof tidRaw === "string" && tidRaw.trim() ? tidRaw.trim() : undefined;
    const prRaw = (ev as { post_apply_review?: unknown }).post_apply_review;
    if (
      prRaw == null ||
      typeof prRaw !== "object" ||
      Array.isArray(prRaw) ||
      !pending_id ||
      !name
    ) {
      return prev;
    }
    const prO = prRaw as Record<string, unknown>;
    const label = typeof prO.label === "string" ? prO.label.trim() : "";
    if (!label) {
      return prev;
    }
    const url = typeof prO.url === "string" ? prO.url.trim() : undefined;
    const path = typeof prO.path === "string" ? prO.path.trim() : undefined;
    const ready = finalizeStreamingAssistantBeforeStructuredStep(
      withoutThinkingSkeleton(prev),
    );
    return [
      ...ready,
      {
        kind: "mutation_applied",
        id: newId(),
        pending_id,
        name,
        ...(tool_call_id ? { tool_call_id } : {}),
        post_apply_review: {
          label,
          ...(url ? { url } : {}),
          ...(path ? { path } : {}),
        },
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
  if (t === "awaiting_inbox_review") {
    const parsed = inboxReviewBarrierFromStreamEvent(ev);
    const ready = finalizeStreamingAssistantBeforeStructuredStep(
      withoutThinkingSkeleton(prev),
    );
    if (!parsed) {
      return ready;
    }
    return [
      ...ready,
      {
        kind: "inbox_review_required",
        id: newId(),
        run_id: parsed.runId,
        watches: parsed.watches,
      },
    ];
  }
  if (t === PLAN_TODO_UPDATE_EVENT_TYPE) {
    const di = (ev as PlanTodoUpdateEvent).done_indices;
    const raw = Array.isArray(di)
      ? di
          .map((x) => Number(x))
          .filter((n) => Number.isFinite(n) && n >= 0)
      : [];
    const delta = deltaPlanTodoIndicesForBlock(prev, raw);
    if (delta.length === 0) {
      return prev;
    }
    const ready = finalizeStreamingAssistantBeforeStructuredStep(
      withoutThinkingSkeleton(prev),
    );
    return [
      ...ready,
      {
        kind: "plan_step_progress",
        id: newId(),
        done_indices: delta,
      },
    ];
  }
  if (t === "error") {
    const detail = typeof ev.detail === "string" ? ev.detail : "error";
    const ready = finalizeStreamingAssistantBeforeStructuredStep(
      withoutThinkingSkeleton(prev),
    );
    const errorCategory =
      typeof (ev as { error_category?: unknown }).error_category === "string"
        ? String((ev as { error_category: string }).error_category).trim()
        : undefined;
    const rawRetry = (ev as { retry_after_seconds?: unknown })
      .retry_after_seconds;
    const retryAfterSeconds =
      typeof rawRetry === "number" && Number.isFinite(rawRetry)
        ? rawRetry
        : undefined;
    const rawHttp = (ev as { http_status?: unknown }).http_status;
    const httpStatus =
      typeof rawHttp === "number" && Number.isFinite(rawHttp)
        ? rawHttp
        : undefined;
    const technicalDetail =
      typeof (ev as { technical_detail?: unknown }).technical_detail ===
      "string"
        ? String((ev as { technical_detail: string }).technical_detail).trim()
        : undefined;
    const retryable =
      typeof (ev as { retryable?: unknown }).retryable === "boolean"
        ? (ev as { retryable: boolean }).retryable
        : undefined;
    return [
      ...ready,
      {
        kind: "error",
        id: newId(),
        detail,
        ...(errorCategory ? { errorCategory } : {}),
        ...(retryAfterSeconds !== undefined ? { retryAfterSeconds } : {}),
        ...(httpStatus !== undefined ? { httpStatus } : {}),
        ...(retryable !== undefined ? { retryable } : {}),
        ...(technicalDetail ? { technicalDetail } : {}),
      },
    ];
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
export type MutationAppliedBlock = Extract<
  LiveBlock,
  { kind: "mutation_applied" }
>;

export type BlockSegment =
  | { type: "single"; block: LiveBlock }
  | {
      type: "tool_group";
      key: string;
      call: ToolCallBlock;
      mutation?: MutationPendingBlock;
      result?: ToolResultBlock;
      /** When ``mutation_applied`` stream event matches this group's ``pending_id`` (same run). */
      mutationApplied?: MutationAppliedBlock;
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

/**
 * Remove the trailing assistant block before persisting a plan_discover run to the thread.
 * The same prose is shown in the plan card from `final.reply`, so it must not duplicate inline.
 */
export function stripLastAssistantBlockForPlan(blocks: LiveBlock[]): LiveBlock[] {
  if (blocks.length === 0) {
    return blocks;
  }
  const last = blocks[blocks.length - 1]!;
  if (last.kind === "assistant") {
    return blocks.slice(0, -1);
  }
  return blocks;
}

/**
 * Build deterministic plan markdown from a server-validated structured plan.
 * Matches the Python ``plan_proposal_to_markdown`` output exactly.
 */
function structuredPlanToMarkdown(sp: StructuredPlanProposal): string {
  const parts = [`# ${sp.title}`];
  if (sp.description) {
    parts.push("", sp.description);
  }
  parts.push("");
  for (const step of sp.steps) {
    parts.push(`- [ ] ${step.label}`);
  }
  return parts.join("\n");
}

/**
 * Extract plan-ready data from a ``final`` terminal event with ``mode: "plan"``.
 * Prefers ``structured_plan`` (tool-based path) over free-form ``reply`` parsing.
 */
export function finalizePlanFromTerminalEvent(
  term: Record<string, unknown>,
  doneBlocks: LiveBlock[],
): {
  planRunId: string;
  planText: string;
  blocksToFlush: LiveBlock[];
} {
  const rawPlanRun = term.plan_run_id;
  const planRunId =
    typeof rawPlanRun === "string" && rawPlanRun.trim().length > 0
      ? rawPlanRun.trim()
      : newId();
  const blocksToFlush = stripLastAssistantBlockForPlan(doneBlocks);

  const sp = term.structured_plan;
  if (
    sp &&
    typeof sp === "object" &&
    "title" in sp &&
    "steps" in sp &&
    Array.isArray((sp as StructuredPlanProposal).steps)
  ) {
    return {
      planRunId,
      planText: structuredPlanToMarkdown(sp as StructuredPlanProposal),
      blocksToFlush,
    };
  }

  const replyRaw = term.reply;
  const reply = typeof replyRaw === "string" ? replyRaw.trim() : "";
  return {
    planRunId,
    planText: preferPlanTaskListBody(reply),
    blocksToFlush,
  };
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
export function finalizeLiveBlocksAfterUserStop(
  blocks: LiveBlock[],
): LiveBlock[] {
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
    if (b.kind === "inbox_review_required") {
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

/** Last ``tool_result`` per provider ``tool_call_id`` (file order — final row wins after resume). */
function latestToolResultByWireCallId(
  blocks: LiveBlock[],
): Map<string, ToolResultBlock> {
  const m = new Map<string, ToolResultBlock>();
  for (const b of blocks) {
    if (b.kind !== "tool_result") {
      continue;
    }
    const tr = b as ToolResultBlock;
    const w = tr.tool_call_id?.trim();
    if (!w) {
      continue;
    }
    m.set(w, tr);
  }
  return m;
}

export function segmentLiveBlocks(blocks: LiveBlock[]): BlockSegment[] {
  const byWire = latestToolResultByWireCallId(blocks);
  const mergedToolResultIds = new Set<string>();
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
    if (b.kind === "tool_result" && mergedToolResultIds.has(b.id)) {
      i += 1;
      continue;
    }
    if (b.kind === "tool_call") {
      const call = b as ToolCallBlock;
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
        while (
          i < blocks.length &&
          blocks[i].kind === "tool_result" &&
          (blocks[i] as ToolResultBlock).name === call.name
        ) {
          result = blocks[i] as ToolResultBlock;
          i += 1;
        }
      }
      const wireId = call.tool_call_id?.trim() ?? "";
      if (wireId) {
        const latest = byWire.get(wireId);
        if (latest) {
          if (!result || latest.id !== result.id) {
            mergedToolResultIds.add(latest.id);
          }
          result = latest;
        }
      }
      let mutationApplied: MutationAppliedBlock | undefined;
      if (
        i < blocks.length &&
        blocks[i].kind === "mutation_applied" &&
        mutation &&
        (blocks[i] as MutationAppliedBlock).pending_id === mutation.pending_id
      ) {
        mutationApplied = blocks[i] as MutationAppliedBlock;
        i += 1;
      }
      out.push({
        type: "tool_group",
        key: call.id,
        call,
        mutation,
        result,
        ...(mutationApplied ? { mutationApplied } : {}),
      });
      continue;
    }
    out.push({ type: "single", block: b });
    i += 1;
  }
  return out;
}

/** Legacy streams used ``POST /api/functions/<name> …`` for nested JSON; normalize to ``hof fn`` for UI. */
function cliLineLooksLikeHttpFunctionPost(line: string): boolean {
  return /^POST\s+\/api\/functions\/\S+/i.test(line.trim());
}

function shlexQuotePseudo(s: string): string {
  if (!/[\s'"\\]/.test(s)) {
    return s;
  }
  return `'${s.replace(/'/g, "'\\''")}'`;
}

/**
 * Mirror server ``hof.agent.tooling._hof_fn_shell_to_pseudo_cli``: turn
 * ``hof fn &lt;name&gt; '&lt;json&gt;'`` into ``hof fn &lt;name&gt; --k v`` for flat objects.
 */
export function pseudoHofFnCliFromShellCommand(
  cmd: string,
  maxChars: number,
): string | null {
  const m = /\bhof\s+fn\s+([a-zA-Z0-9_]+)\s*/.exec(cmd);
  if (!m) {
    return null;
  }
  const fnName = m[1];
  if (fnName === "list" || fnName === "describe" || fnName === "help") {
    return null;
  }
  let rest = cmd.slice(m.index + m[0].length).trim();
  if (!rest) {
    return `hof fn ${fnName}`;
  }
  if (
    (rest.startsWith("'") && rest.endsWith("'")) ||
    (rest.startsWith('"') && rest.endsWith('"'))
  ) {
    rest = rest.slice(1, -1);
  }
  let body: unknown;
  try {
    body = JSON.parse(rest);
  } catch {
    return null;
  }
  if (body === null || typeof body !== "object") {
    const compact = JSON.stringify(body);
    const line = `hof fn ${fnName} ${compact}`;
    return line.length > maxChars ? `${line.slice(0, maxChars - 1)}…` : line;
  }
  if (Array.isArray(body)) {
    const compact = JSON.stringify(body);
    const line = `hof fn ${fnName} ${compact}`;
    return line.length > maxChars ? `${line.slice(0, maxChars - 1)}…` : line;
  }
  const o = body as Record<string, unknown>;
  let nested = false;
  for (const v of Object.values(o)) {
    if (v !== null && typeof v === "object") {
      nested = true;
      break;
    }
  }
  if (nested) {
    const compact = JSON.stringify(o);
    const line = `hof fn ${fnName} ${compact}`;
    return line.length > maxChars ? `${line.slice(0, maxChars - 1)}…` : line;
  }
  const keys = Object.keys(o).sort((a, b) => a.localeCompare(b));
  const parts: string[] = ["hof", "fn", fnName];
  for (const k of keys) {
    const v = o[k];
    if (v === true) {
      parts.push(`--${k}`);
    } else if (v === false) {
      parts.push(`--${k}`, "false");
    } else if (v === null) {
      parts.push(`--${k}`, "null");
    } else {
      parts.push(`--${k}`, shlexQuotePseudo(String(v)));
    }
  }
  const line = parts.join(" ");
  return line.length > maxChars ? `${line.slice(0, maxChars - 1)}…` : line;
}

/**
 * Single source of truth for pseudo-CLI lines in the assistant (tool card, pending rows, barrier).
 * Prefer server ``cli_line`` unless it is the old HTTP-style line and ``argumentsJson`` can replace it.
 * For ``hof_builtin_terminal_exec``, prefer ``hof fn <underlying_domain_fn>`` when the command is transport (curl / wrapper).
 */
export function normalizeAgentCliDisplayLine(
  name: string,
  cliLine: string | undefined,
  argumentsJson: string | undefined,
): string {
  const raw = cliLine?.trim();
  const isTerminal = name.trim() === HOF_BUILTIN_TERMINAL_EXEC;
  const underlying = isTerminal
    ? underlyingFunctionFromTerminalExecArguments(argumentsJson)
    : null;

  if (isTerminal && !underlying) {
    const shellCmd = rawShellCommandFromTerminalExecArguments(argumentsJson);
    if (shellCmd) {
      const pseudo = pseudoHofFnCliFromShellCommand(shellCmd, 8000);
      if (pseudo) {
        return pseudo;
      }
      return shellCmd;
    }
    if (!raw) {
      return "(terminal)";
    }
    if (looksLikeTerminalTransportCli(raw)) {
      return "(terminal)";
    }
    return raw;
  }

  if (isTerminal && underlying) {
    const shellCmd = rawShellCommandFromTerminalExecArguments(argumentsJson);
    if (shellCmd) {
      const pseudo = pseudoHofFnCliFromShellCommand(shellCmd, 8000);
      if (pseudo) {
        return pseudo;
      }
    }
    const synthetic = `hof fn ${underlying}`;
    if (!raw) {
      return synthetic;
    }
    if (cliLineLooksLikeHttpFunctionPost(raw)) {
      return synthetic;
    }
    if (looksLikeTerminalTransportCli(raw)) {
      return synthetic;
    }
    if (raw.length > 160 && /\{[\s\S]*"[^"]+"\s*:/.test(raw)) {
      return synthetic;
    }
    return raw;
  }

  const args = argumentsJson?.trim() ?? "";
  const fallback =
    name && args
      ? `hof fn ${name} ${args.length > 220 ? `${args.slice(0, 217)}…` : args}`
      : name || "(tool)";

  if (!raw) {
    return fallback;
  }
  if (cliLineLooksLikeHttpFunctionPost(raw)) {
    return fallback;
  }
  return raw;
}

export function toolCallCliLine(b: ToolCallBlock): string {
  return normalizeAgentCliDisplayLine(b.name, b.cli_line, b.arguments);
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
  /** Short, user-visible state (Succeeded / Failed / Waiting …). */
  headline: string;
  /** Extra line when pending_confirmation is easy to confuse with a post-apply review step. */
  detail?: string;
};

/** Pending mutation `tool_result.data` is a preview envelope; true when a post-apply review step is declared. */
export function toolResultDataHasPostApplyReview(data: unknown): boolean {
  return postApplyReviewFromPreview(data) != null;
}

function _postApplyReviewLabel(data: unknown): string | null {
  return postApplyReviewFromPreview(data)?.label ?? null;
}

/** Human-readable HTTP-shaped status for the tool row (stream fields + fallbacks). */
export function toolResultUiStatus(
  result: Pick<
    ToolResultBlock,
    "pending_confirmation" | "data" | "summary" | "ok" | "status_code"
  >,
): ToolResultUiStatus {
  if (result.pending_confirmation) {
    const code = result.status_code ?? 202;
    const postApplyLabel = _postApplyReviewLabel(result.data);
    if (postApplyLabel) {
      return {
        code,
        label: "Confirm in chat first",
        tone: "pending",
        headline: "Waiting for your approval",
        detail: `This is not “${postApplyLabel}” in chat. Use Approve or Reject on the pending tool row first; the run continues once all choices are set. “${postApplyLabel}” is the step after that — open the link when shown.`,
      };
    }
    return {
      code,
      label: "Confirm below to apply",
      tone: "pending",
      headline: "Waiting for your approval",
      detail:
        "The mutation has not run yet. Approve or reject on the pending tool row; the assistant continues when every pending action has a choice.",
    };
  }
  if (result.status_code !== undefined && Number.isFinite(result.status_code)) {
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
      const headline = code === 499 ? "You rejected this action" : "Failed";
      return { code, label, tone: "error", headline };
    }
    if (ok === true || (code >= 200 && code < 400)) {
      return {
        code,
        label: "OK",
        tone: "success",
        headline: "Succeeded",
      };
    }
    return {
      code,
      label: "OK",
      tone: "success",
      headline: "Succeeded",
    };
  }
  const data = result.data;
  if (
    data !== null &&
    typeof data === "object" &&
    !Array.isArray(data) &&
    "error" in data
  ) {
    return {
      code: 502,
      label: "Tool error",
      tone: "error",
      headline: "Failed",
    };
  }
  const s = result.summary?.trim() ?? "";
  if (/^error:/i.test(s)) {
    return { code: 502, label: "Error", tone: "error", headline: "Failed" };
  }
  return {
    code: 200,
    label: "OK",
    tone: "success",
    headline: "Succeeded",
  };
}

/** Compact tool row label for the card header (next to the humanized function name). */
export type ToolAggregateTone = "success" | "error" | "pending" | "running";

export function toolGroupAggregatedStatus(
  result: ToolResultBlock | undefined,
  busy: boolean,
  /** When set, overrides stale ``pending_confirmation`` on the block (persisted approve without updated row). */
  mutationOutcome?: boolean,
): { label: string; tone: ToolAggregateTone } {
  if (mutationOutcome === false) {
    return { label: "rejected", tone: "error" };
  }
  if (mutationOutcome === true) {
    if (result && !result.pending_confirmation) {
      const st = toolResultUiStatus(result);
      if (st.tone === "error") {
        return { label: "failed", tone: "error" };
      }
      return { label: "done", tone: "success" };
    }
    return { label: "done", tone: "success" };
  }
  if (!result) {
    if (busy) {
      return { label: "running", tone: "running" };
    }
    return { label: "error", tone: "error" };
  }
  if (result.pending_confirmation) {
    return { label: "pending", tone: "pending" };
  }
  const st = toolResultUiStatus(result);
  if (st.tone === "error") {
    if (result.status_code === 499) {
      return { label: "rejected", tone: "error" };
    }
    return { label: "failed", tone: "error" };
  }
  return { label: "done", tone: "success" };
}

export function toolGroupSummaryLine(
  call: ToolCallBlock,
  mutation: MutationPendingBlock | undefined,
  result: ToolResultBlock | undefined,
): string | null {
  const title = toolCallRowTitle(call);
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
  items: {
    pendingId: string;
    name: string;
    cli_line: string;
    preview?: unknown;
  }[];
};

/**
 * True if any tool group (or orphan {@link LiveBlock} `mutation_pending`) in these blocks
 * matches a pending id on the barrier — i.e. the UI can show Approve/Reject on a card.
 */
export function barrierHasRenderablePendingMutations(
  barrier: ApprovalBarrier | null,
  blocks: LiveBlock[],
): boolean {
  if (!barrier?.items.length) {
    return false;
  }
  const wanted = new Set(
    barrier.items.map((i) => i.pendingId.trim()).filter(Boolean),
  );
  if (wanted.size === 0) {
    return false;
  }
  for (const b of blocks) {
    if (b.kind === "mutation_pending") {
      const pid = String(b.pending_id ?? "").trim();
      if (pid && wanted.has(pid)) {
        return true;
      }
    }
  }
  const segs = segmentLiveBlocks(
    dropRedundantModelPhaseBeforeAssistant(blocks),
  );
  for (const seg of segs) {
    if (seg.type !== "tool_group" || !seg.mutation) {
      continue;
    }
    const pid = String(seg.mutation.pending_id ?? "").trim();
    if (pid && wanted.has(pid)) {
      return true;
    }
  }
  return false;
}

/**
 * Whether the thread + live area still contain mutation rows that match the approval barrier.
 * If not, the barrier is stale (e.g. persisted draft) and should be cleared.
 */
export function barrierMatchesAnyThreadOrLiveBlocks(
  barrier: ApprovalBarrier | null,
  thread: ThreadItem[],
  liveBlocks: LiveBlock[],
): boolean {
  if (barrierHasRenderablePendingMutations(barrier, liveBlocks)) {
    return true;
  }
  for (const item of thread) {
    if (
      item.kind === "run" &&
      barrierHasRenderablePendingMutations(barrier, item.blocks)
    ) {
      return true;
    }
  }
  return false;
}

export function barrierMatchesApprovalBlock(
  barrier: ApprovalBarrier,
  blockRunId: string,
  blockPendingIds: string[],
): boolean {
  const br = barrier.runId.trim();
  const tr = blockRunId.trim();
  if (br !== "" && tr !== "" && br !== tr) {
    return false;
  }
  if (br !== "" && tr !== "" && br === tr) {
    return true;
  }
  if (blockPendingIds.length === 0 || barrier.items.length === 0) {
    return false;
  }
  const ps = new Set(blockPendingIds.map((x) => x.trim()).filter(Boolean));
  const bs = new Set(barrier.items.map((it) => it.pendingId.trim()));
  if (ps.size === bs.size) {
    for (const p of ps) {
      if (!bs.has(p)) {
        return false;
      }
    }
    return true;
  }
  // Subset case: `approval_required` may still list every mutation from the original
  // `awaiting_confirmation`, while the live `approvalBarrier` was rebuilt with only
  // the ids still open (e.g. new `run_start` + merge). Every active barrier id must
  // appear in this block's pending_ids so we do not attach the wrong run's barrier.
  for (const b of bs) {
    if (!ps.has(b)) {
      return false;
    }
  }
  return true;
}

/** Status glyphs for the compact confirmation row (matches tool-card mutation icons). */
export type ConfirmationFooterIconKind = "approved" | "rejected" | "pending";

/**
 * After resume, a compact status row (no prose). Empty `pending_ids` means the run used a
 * synthetic barrier — show a single approved glyph. Otherwise one glyph per id (success /
 * reject / pending), matching tool-card mutation icons in the UI.
 */
export function confirmationFooterIconsFromOutcomes(
  pendingIds: string[],
  outcomes: Record<string, boolean | undefined>,
): ConfirmationFooterIconKind[] {
  const norm = pendingIds.map((p) => p.trim()).filter(Boolean);
  if (norm.length === 0) {
    return ["approved"];
  }
  const allResolved = norm.every(
    (id) => outcomes[id] === true || outcomes[id] === false,
  );
  if (allResolved) {
    return [];
  }
  return norm.map((id) => {
    const o = outcomes[id];
    if (o === true) {
      return "approved";
    }
    if (o === false) {
      return "rejected";
    }
    return "pending";
  });
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
