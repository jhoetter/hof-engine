"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
  type SetStateAction,
  type Dispatch,
} from "react";
import {
  postHofFunction,
  streamHofFunction,
  type HofStreamEvent,
} from "../hooks/streamHofFunction";
import type {
  AgentConversationStateV1,
  PlanClarificationQuestion,
} from "./conversationTypes";
import type {
  AgentAttachment,
  ApprovalBarrier,
  InboxReviewBarrier,
  InboxReviewWatchWire,
  LiveBlock,
  ThreadItem,
} from "./hofAgentChatModel";
import {
  applyStreamEventWithDedupe,
  barrierMatchesAnyThreadOrLiveBlocks,
  collectThreadAttachments,
  compactBlocksForHistory,
  coerceRunId,
  finalizeLiveBlocksAfterUserStop,
  inboxReviewBarrierFromStreamEvent,
  mergePendingIdLists,
  mutationPendingIdsFromBlocks,
  newId,
  normalizeAgentCliDisplayLine,
  PLAN_EXECUTE_USER_MARKER,
  stripLastAssistantBlockForPlan,
  toolResultAwaitingUserConfirmation,
} from "./hofAgentChatModel";
import {
  parseStructuredPlan,
  preferPlanTaskListBody,
} from "./planMarkdownTodos";
import {
  AssistantMarkdownLinkProvider,
  type AssistantMarkdownLinkClickHandler,
} from "./assistantMarkdownLinkContext";

type PendingDetailsEntry = {
  name: string;
  cli_line: string;
  arguments_json?: string;
  preview?: unknown;
};

function pendingDetailsFromMutationPendingEvent(
  ev: HofStreamEvent,
): PendingDetailsEntry {
  const hasPv = Object.prototype.hasOwnProperty.call(ev, "preview");
  const argsRaw = (ev as { arguments?: unknown }).arguments;
  const arguments_json = typeof argsRaw === "string" ? argsRaw : undefined;
  return {
    name: typeof ev.name === "string" ? ev.name : "",
    cli_line:
      typeof (ev as { cli_line?: unknown }).cli_line === "string"
        ? (ev as { cli_line: string }).cli_line
        : "",
    ...(arguments_json !== undefined ? { arguments_json } : {}),
    ...(hasPv ? { preview: (ev as { preview: unknown }).preview } : {}),
  };
}

function approvalBarrierItemFromDetails(
  pid: string,
  det: PendingDetailsEntry | undefined,
): ApprovalBarrier["items"][number] {
  const name = det?.name || "mutation";
  return {
    pendingId: pid,
    name,
    cli_line: normalizeAgentCliDisplayLine(
      name,
      det?.cli_line,
      det?.arguments_json,
    ),
    ...(det?.preview !== undefined ? { preview: det.preview } : {}),
  };
}

/** Terminal ``processing_status`` for receipt PDF pipeline (matches spreadsheet-app ``_RECEIPT_PROCESSING_TERMINAL``). */
const RECEIPT_PROCESSING_TERMINAL = new Set([
  "ready",
  "needs_review",
  "failed",
]);

/** Default client poll: expense/revenue/receipt row no longer needs Inbox HITL. */
export async function defaultPollInboxReviewWatch(
  w: InboxReviewWatchWire,
): Promise<boolean> {
  const rt = w.record_type.trim().toLowerCase();
  try {
    if (rt === "expense") {
      const row = await postHofFunction<Record<string, unknown>>(
        "get_expense",
        {
          id: w.record_id,
        },
      );
      return String(row?.approval_status ?? "") !== "pending_review";
    }
    if (rt === "revenue") {
      const row = await postHofFunction<Record<string, unknown>>(
        "get_revenue",
        {
          id: w.record_id,
        },
      );
      return String(row?.confirmation_status ?? "") !== "pending_review";
    }
    if (rt === "receipt" || rt === "receipt_document") {
      const row = await postHofFunction<Record<string, unknown>>(
        "get_receipt_document",
        {
          id: w.record_id,
        },
      );
      const ps = String(row?.processing_status ?? "").toLowerCase();
      if (!RECEIPT_PROCESSING_TERMINAL.has(ps)) {
        return false;
      }
      return String(row?.match_review_status ?? "") !== "pending_review";
    }
  } catch {
    return false;
  }
  return false;
}

export type HofAgentChatPresignInput = {
  filename: string;
  content_type: string;
};

export type HofAgentChatPresignResult = {
  upload_url: string;
  object_key: string;
};

/** Latest ``provider_wait`` line from the agent NDJSON stream (rate limit / transient backoff). */
export type ProviderWaitNotice = {
  /** Server-reported wait duration (for reference). */
  seconds: number;
  reason: string;
  /** Wall-clock deadline for a live client-side countdown. */
  deadlineMs: number;
};

function updateProviderWaitFromStreamType(
  typ: string,
  ev: HofStreamEvent,
  setNotice: Dispatch<SetStateAction<ProviderWaitNotice | null>>,
): void {
  if (typ === "error" || typ === "final" || typ === "cancelled") {
    setNotice(null);
    return;
  }
  if (typ === "provider_wait") {
    const raw = (ev as { seconds?: unknown }).seconds;
    const sec =
      typeof raw === "number" && Number.isFinite(raw) ? Math.max(0, raw) : 0;
    const rounded = Math.max(1, Math.round(sec));
    const reasonRaw = (ev as { reason?: unknown }).reason;
    const reason =
      typeof reasonRaw === "string" && reasonRaw.trim()
        ? reasonRaw.trim()
        : "transient_error";
    setNotice({
      seconds: sec,
      reason,
      deadlineMs: Date.now() + rounded * 1000,
    });
    return;
  }
  if (
    typ === "assistant_delta" ||
    typ === "reasoning_delta" ||
    typ === "tool_call"
  ) {
    setNotice(null);
  }
}

export type HofAgentChatProps = {
  welcomeName: string;
  presignUpload: (
    input: HofAgentChatPresignInput,
  ) => Promise<HofAgentChatPresignResult>;
  className?: string;
  initialPersisted?: AgentConversationStateV1 | null;
  onPersist?: (state: AgentConversationStateV1) => void | Promise<void>;
  persistDebounceMs?: number;
  /**
   * Merged into the ``agent_chat`` POST body after ``messages`` / ``attachments``.
   * Use for e.g. ``conversation_id`` + auth token so the server can run side effects per turn.
   */
  prepareAgentChatRequest?: () => Promise<Record<string, unknown>>;
  /** Merged into the ``agent_resume_mutations`` POST body after ``run_id`` / ``resolutions``. */
  prepareAgentResumeRequest?: () => Promise<Record<string, unknown>>;
  /** Merged into ``agent_resume_inbox_reviews`` after ``run_id`` / ``resolutions``. Defaults to ``prepareAgentResumeRequest``. */
  prepareAgentResumeInboxRequest?: () => Promise<Record<string, unknown>>;
  /** Override inbox polling; default uses ``get_expense`` / ``get_revenue`` by ``record_type``. */
  pollInboxReviewWatch?: (w: InboxReviewWatchWire) => Promise<boolean>;
  /**
   * Runs before default link behavior in assistant Markdown. Call ``event.preventDefault()`` to handle
   * the URL in the host (e.g. open same-origin inbox in an iframe).
   */
  onAssistantMarkdownLinkClick?: AssistantMarkdownLinkClickHandler;
  /** Initial chat mode; default ``"instant"``. */
  initialAgentMode?: AgentMode;
  /** Merged into ``agent_resume_plan_clarification`` POST body. Defaults to ``prepareAgentResumeRequest``. */
  prepareAgentResumePlanClarificationRequest?: () => Promise<Record<string, unknown>>;
};

export type AgentMode = "instant" | "plan";
export type AgentPlanPhase =
  | null
  | "generating"
  | "clarifying"
  | "ready"
  | "executing"
  | "done";
export type AgentChatRequestMode = "instant" | "plan" | "plan_execute";

export type PlanClarificationBarrierV1 = {
  runId: string;
  clarificationId: string;
  questions: PlanClarificationQuestion[];
};

export type HofAgentChatProviderProps = Omit<HofAgentChatProps, "className"> & {
  children: ReactNode;
};

export type HofAgentChatContextValue = {
  welcomeName: string;
  thread: ThreadItem[];
  liveBlocks: LiveBlock[];
  busy: boolean;
  input: string;
  setInput: Dispatch<SetStateAction<string>>;
  attachmentQueue: AgentAttachment[];
  setAttachmentQueue: Dispatch<SetStateAction<AgentAttachment[]>>;
  uploadBusy: boolean;
  uploadErr: string | null;
  approvalBarrier: ApprovalBarrier | null;
  /** Paused on engine ``awaiting_inbox_review``; UI polls reads then POSTs inbox resume. */
  inboxReviewBarrier: InboxReviewBarrier | null;
  inboxPollWaiting: boolean;
  inboxResumeError: string | null;
  approvalDecisions: Record<string, boolean | null>;
  setApprovalDecisions: Dispatch<
    SetStateAction<Record<string, boolean | null>>
  >;
  mutationOutcomeByPendingId: Record<string, boolean | undefined>;
  fileInputRef: RefObject<HTMLInputElement | null>;
  onPickFiles: (files: FileList | null) => Promise<void>;
  send: () => void;
  /** Abort the in-flight ``agent_chat``, ``agent_resume_mutations``, or inbox resume stream. */
  stop: () => void;
  /**
   * Clears the mutation-approval gate locally (e.g. stuck UI with no matching tool row).
   * Does not call the API; the next message starts a fresh turn.
   */
  dismissApprovalBarrier: () => void;
  /** Clears the inbox-review gate and polling state without calling inbox resume. */
  dismissInboxReviewBarrier: () => void;
  conversationEmpty: boolean;
  /**
   * Wall-clock start of the current “thinking” episode (model round), for live timers.
   * Reset on ``run_start`` / ``resume_start`` / ``phase: model``; cleared when the request ends.
   */
  thinkingEpisodeStartedAtMs: number | null;
  /** Set when the stream emits ``provider_wait`` (API backoff); cleared when tokens or tools resume. */
  providerWaitNotice: ProviderWaitNotice | null;
  /**
   * Runs ``agent_resume_mutations`` with current choices. Normally the provider resumes
   * automatically once every pending id has approve/reject set; this is for manual triggers.
   */
  confirmPendingMutations: () => void;
  agentMode: AgentMode;
  setAgentMode: Dispatch<SetStateAction<AgentMode>>;
  planPhase: AgentPlanPhase;
  planText: string;
  setPlanText: Dispatch<SetStateAction<string>>;
  planRunId: string | null;
  planClarificationBarrier: PlanClarificationBarrierV1 | null;
  planClarificationSubmittedSummary: readonly {
    prompt: string;
    selectedLabels: string[];
  }[];
  submitPlanClarification: (
    answers: {
      question_id: string;
      selected_option_ids: string[];
      other_text?: string;
    }[],
  ) => void;
  dismissPlanClarificationBarrier: () => void;
  planTodoDoneIndices: readonly number[];
  executePlan: () => void;
};

const HofAgentChatContext = createContext<HofAgentChatContextValue | null>(
  null,
);

export function useHofAgentChat(): HofAgentChatContextValue {
  const v = useContext(HofAgentChatContext);
  if (!v) {
    throw new Error("useHofAgentChat must be used within HofAgentChatProvider");
  }
  return v;
}

export function HofAgentChatProvider({
  welcomeName,
  presignUpload,
  initialPersisted = null,
  onPersist,
  persistDebounceMs = 1200,
  prepareAgentChatRequest,
  prepareAgentResumeRequest,
  prepareAgentResumeInboxRequest,
  pollInboxReviewWatch,
  onAssistantMarkdownLinkClick,
  initialAgentMode = "instant",
  prepareAgentResumePlanClarificationRequest,
  children,
}: HofAgentChatProviderProps) {
  const [thread, setThread] = useState<ThreadItem[]>([]);
  const [liveBlocks, setLiveBlocks] = useState<LiveBlock[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [thinkingEpisodeStartedAtMs, setThinkingEpisodeStartedAtMs] = useState<
    number | null
  >(null);
  const thinkingEpisodeStartedAtRef = useRef<number | null>(null);
  const updateThinkingEpisodeStart = useCallback((ms: number | null) => {
    thinkingEpisodeStartedAtRef.current = ms;
    setThinkingEpisodeStartedAtMs(ms);
  }, []);
  const [attachmentQueue, setAttachmentQueue] = useState<AgentAttachment[]>([]);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploadErr, setUploadErr] = useState<string | null>(null);
  const [approvalBarrier, setApprovalBarrier] =
    useState<ApprovalBarrier | null>(null);
  const [approvalDecisions, setApprovalDecisions] = useState<
    Record<string, boolean | null>
  >({});
  const [mutationOutcomeByPendingId, setMutationOutcomeByPendingId] = useState<
    Record<string, boolean | undefined>
  >({});
  const [inboxReviewBarrier, setInboxReviewBarrier] =
    useState<InboxReviewBarrier | null>(null);
  const [inboxPollWaiting, setInboxPollWaiting] = useState(false);
  const [inboxResumeError, setInboxResumeError] = useState<string | null>(null);
  const [providerWaitNotice, setProviderWaitNotice] =
    useState<ProviderWaitNotice | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const threadRef = useRef<ThreadItem[]>([]);
  const sendingRef = useRef(false);
  const reqIdRef = useRef(0);
  const runResumeRef = useRef<() => Promise<void>>(async () => {});
  /** Prevents duplicate auto-resume (e.g. React Strict Mode double effect). */
  const approvalAutoResumeLockRef = useRef(false);
  const runInboxResumeRef = useRef<(b: InboxReviewBarrier) => Promise<void>>(
    async () => {},
  );
  const inboxReviewBarrierRef = useRef<InboxReviewBarrier | null>(null);
  const pollInboxWatchRef = useRef(
    pollInboxReviewWatch ?? defaultPollInboxReviewWatch,
  );
  const resumeMergeContinuationRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  const liveBlocksRef = useRef<LiveBlock[]>([]);
  const pendingDetailsRef = useRef(new Map<string, PendingDetailsEntry>());
  const mutationPendingIdsThisRunRef = useRef<string[]>([]);
  const currentAgentRunIdRef = useRef("");
  const assistantStreamPhaseRef = useRef<"model" | "summary" | null>(null);
  const skipNextPersistRef = useRef(true);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const lastTerminalStreamEventRef = useRef<any>(null);

  const [agentMode, setAgentMode] = useState<AgentMode>(initialAgentMode);
  const [planPhase, setPlanPhase] = useState<AgentPlanPhase>(null);
  const [planText, setPlanText] = useState("");
  const [planRunId, setPlanRunId] = useState<string | null>(null);
  const [planClarificationBarrier, setPlanClarificationBarrier] =
    useState<PlanClarificationBarrierV1 | null>(null);
  const [planClarificationSubmittedSummary, setPlanClarificationSubmittedSummary] =
    useState<{ prompt: string; selectedLabels: string[] }[]>([]);
  const [planTodoDoneIndices, setPlanTodoDoneIndices] = useState<number[]>([]);
  const planTextRef = useRef("");
  const planDraftStreamingActiveRef = useRef(false);
  const planDraftBufferRef = useRef("");
  const chatRequestModeRef = useRef<AgentChatRequestMode>(
    initialAgentMode === "plan" ? "plan" : "instant",
  );
  /** True after Execute plan until stream ends with ``final`` or ``error`` (survives ``awaiting_confirmation``). */
  const planExecuteActiveRef = useRef(false);

  useEffect(() => {
    planTextRef.current = planText;
  }, [planText]);

  useEffect(() => {
    chatRequestModeRef.current =
      agentMode === "plan" ? "plan" : "instant";
  }, [agentMode]);

  useEffect(() => {
    inboxReviewBarrierRef.current = inboxReviewBarrier;
  }, [inboxReviewBarrier]);

  useEffect(() => {
    pollInboxWatchRef.current =
      pollInboxReviewWatch ?? defaultPollInboxReviewWatch;
  }, [pollInboxReviewWatch]);

  useLayoutEffect(() => {
    skipNextPersistRef.current = true;
    const snap = initialPersisted;
    if (!snap || snap.version !== 1) {
      return;
    }
    if (Array.isArray(snap.thread)) {
      setThread(snap.thread as ThreadItem[]);
    }
    const mo = snap.mutationOutcomes;
    if (mo && typeof mo === "object") {
      const nextMo: Record<string, boolean | undefined> = {};
      for (const [k, v] of Object.entries(mo)) {
        if (v === true || v === false) {
          nextMo[k] = v;
        }
      }
      setMutationOutcomeByPendingId(nextMo);
    } else {
      setMutationOutcomeByPendingId({});
    }
    const d = snap.draft;
    if (d?.liveBlocks && Array.isArray(d.liveBlocks)) {
      const lb = d.liveBlocks as LiveBlock[];
      const th = (
        Array.isArray(snap.thread) ? snap.thread : []
      ) as ThreadItem[];
      const last = th.length > 0 ? th[th.length - 1] : undefined;
      // Saved state sometimes had both a final ``run`` on the thread and the same blocks still
      // in ``draft.liveBlocks`` (persist race). That paints the whole turn twice after reload/fetch.
      const draftInbox = (
        d as { inboxReviewBarrier?: { runId?: string } | null }
      ).inboxReviewBarrier;
      const discardDraftLive =
        lb.length > 0 &&
        !d.approvalBarrier?.runId &&
        !draftInbox?.runId &&
        last?.kind === "run";
      if (discardDraftLive) {
        liveBlocksRef.current = [];
        setLiveBlocks([]);
      } else {
        liveBlocksRef.current = lb;
        setLiveBlocks(lb);
      }
      if (d.approvalBarrier?.runId) {
        setApprovalBarrier(d.approvalBarrier as ApprovalBarrier);
      } else {
        setApprovalBarrier(null);
      }
      const ib = (d as { inboxReviewBarrier?: InboxReviewBarrier | null })
        .inboxReviewBarrier;
      if (ib?.runId && Array.isArray(ib.watches) && ib.watches.length > 0) {
        setInboxReviewBarrier(ib);
      } else {
        setInboxReviewBarrier(null);
      }
      setApprovalDecisions(
        d.approvalDecisions && typeof d.approvalDecisions === "object"
          ? { ...d.approvalDecisions }
          : {},
      );
    } else {
      liveBlocksRef.current = [];
      setLiveBlocks([]);
      setApprovalBarrier(null);
      setInboxReviewBarrier(null);
      setApprovalDecisions({});
    }
    setAttachmentQueue([]);
    setInput("");
    setUploadErr(null);
    const p = snap.plan;
    if (p && typeof p === "object") {
      if (p.phase) {
        setPlanPhase(p.phase);
      }
      if (typeof p.text === "string") {
        setPlanText(p.text);
      }
      if (typeof p.runId === "string" || p.runId === null) {
        setPlanRunId(p.runId);
      }
      if (p.clarificationBarrier) {
        setPlanClarificationBarrier(
          p.clarificationBarrier as PlanClarificationBarrierV1,
        );
      }
      if (Array.isArray(p.planTodoDoneIndices)) {
        setPlanTodoDoneIndices(p.planTodoDoneIndices as number[]);
      }
      const cs = (p as { clarificationSummary?: unknown }).clarificationSummary;
      if (Array.isArray(cs)) {
        const rows: { prompt: string; selectedLabels: string[] }[] = [];
        for (const row of cs) {
          if (row && typeof row === "object") {
            const o = row as Record<string, unknown>;
            const prompt = typeof o.prompt === "string" ? o.prompt : "";
            const labelsRaw = o.selectedLabels;
            const selectedLabels = Array.isArray(labelsRaw)
              ? labelsRaw.map((x) => String(x))
              : [];
            rows.push({ prompt, selectedLabels });
          }
        }
        if (rows.length > 0) {
          setPlanClarificationSubmittedSummary(rows);
        }
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional: hydrate only from initial mount props; parent uses ``key`` to switch conversations
  }, []);

  useEffect(() => {
    if (!onPersist) {
      return;
    }
    if (skipNextPersistRef.current) {
      skipNextPersistRef.current = false;
      return;
    }
    const ms = persistDebounceMs;
    const t = window.setTimeout(() => {
      const outcomes: Record<string, boolean> = {};
      for (const [k, v] of Object.entries(mutationOutcomeByPendingId)) {
        if (v === true || v === false) {
          outcomes[k] = v;
        }
      }
      const lastForDraft =
        thread.length > 0 ? thread[thread.length - 1] : undefined;
      const draftLiveStale =
        !busy &&
        !approvalBarrier &&
        !inboxReviewBarrier &&
        lastForDraft?.kind === "run" &&
        liveBlocks.length > 0;
      const draftLiveBlocks = draftLiveStale ? [] : liveBlocks;
      const hasDraft =
        draftLiveBlocks.length > 0 ||
        approvalBarrier !== null ||
        inboxReviewBarrier !== null ||
        busy;
      const hasPlan =
        planPhase !== null ||
        planText.length > 0 ||
        planRunId !== null ||
        planClarificationBarrier !== null;
      const state: AgentConversationStateV1 = {
        version: 1,
        thread: structuredClone(thread) as unknown[],
        mutationOutcomes: outcomes,
        draft: hasDraft
          ? {
              liveBlocks: structuredClone(draftLiveBlocks) as unknown[],
              approvalBarrier,
              inboxReviewBarrier,
              approvalDecisions: { ...approvalDecisions },
            }
          : undefined,
        plan: hasPlan
          ? {
              phase: planPhase ?? "generating",
              text: planText,
              runId: planRunId,
              clarificationBarrier: planClarificationBarrier,
              ...(planClarificationSubmittedSummary.length > 0
                ? {
                    clarificationSummary: [...planClarificationSubmittedSummary],
                  }
                : {}),
              planTodoDoneIndices,
            }
          : undefined,
      };
      void onPersist(state);
    }, ms);
    return () => window.clearTimeout(t);
  }, [
    thread,
    liveBlocks,
    mutationOutcomeByPendingId,
    approvalBarrier,
    inboxReviewBarrier,
    approvalDecisions,
    busy,
    onPersist,
    persistDebounceMs,
    planPhase,
    planText,
    planRunId,
    planClarificationBarrier,
    planClarificationSubmittedSummary,
    planTodoDoneIndices,
  ]);

  useEffect(() => {
    threadRef.current = thread;
  }, [thread]);

  /** Drop ``liveBlocks`` when they are leftover from a turn already stored as the last ``run`` row. */
  useEffect(() => {
    if (busy || approvalBarrier || inboxReviewBarrier) {
      return;
    }
    if (liveBlocks.length === 0) {
      return;
    }
    const last = thread[thread.length - 1];
    if (last?.kind !== "run") {
      return;
    }
    liveBlocksRef.current = [];
    setLiveBlocks([]);
  }, [thread, liveBlocks, busy, approvalBarrier, inboxReviewBarrier]);

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

  const flushLiveToThread = useCallback(
    (
      blocks: LiveBlock[],
      options?: {
        mergeContinuation?: boolean;
        presetRunId?: string;
      },
    ) => {
      if (blocks.length === 0) {
        return;
      }
      const cleaned = compactBlocksForHistory(blocks);
      const toStore = cleaned.length > 0 ? cleaned : blocks;
      const mergeContinuation = options?.mergeContinuation === true;
      const presetRunId = options?.presetRunId;
      setThread((t) => {
        if (
          mergeContinuation &&
          t.length > 0 &&
          t[t.length - 1].kind === "run"
        ) {
          const last = t[t.length - 1];
          if (last.kind !== "run") {
            return [
              ...t,
              {
                kind: "run",
                id: presetRunId ?? newId(),
                blocks: structuredClone(toStore),
              },
            ];
          }
          const merged: LiveBlock[] = [
            ...last.blocks,
            { kind: "continuation_marker", id: newId() },
            ...structuredClone(toStore),
          ];
          return [...t.slice(0, -1), { ...last, blocks: merged }];
        }
        return [
          ...t,
          {
            kind: "run",
            id: presetRunId ?? newId(),
            blocks: structuredClone(toStore),
          },
        ];
      });
    },
    [],
  );

  /** When a plan_execute stream ends with ``final`` or ``error``, update phase and todo state. */
  const applyPlanExecuteStreamCompletion = useCallback((termTyp: string) => {
    if (!planExecuteActiveRef.current) {
      return;
    }
    if (termTyp === "final" || termTyp === "error") {
      planExecuteActiveRef.current = false;
    }
    if (termTyp === "final") {
      const n = parseStructuredPlan(planTextRef.current.trim()).todos.length;
      if (n > 0) {
        setPlanTodoDoneIndices(Array.from({ length: n }, (_, i) => i));
      }
      setPlanPhase("done");
    }
  }, []);

  const runAgent = useCallback(
    async (
      items: ThreadItem[],
      requestModeOverride?: AgentChatRequestMode,
      planExecuteTextOverride?: string,
    ) => {
      const effectiveMode =
        requestModeOverride ?? chatRequestModeRef.current;
      const myId = ++reqIdRef.current;
      abortRef.current?.abort();
      abortRef.current = new AbortController();
      setBusy(true);
      updateThinkingEpisodeStart(Date.now());
      liveBlocksRef.current = [];
      setLiveBlocks([]);
      currentAgentRunIdRef.current = "";
      if (effectiveMode === "plan") {
        planDraftStreamingActiveRef.current = true;
        planDraftBufferRef.current = "";
        setPlanText("");
        setPlanPhase("generating");
      } else {
        planDraftStreamingActiveRef.current = false;
      }
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
        if (prepareAgentChatRequest) {
          const extra = await prepareAgentChatRequest();
          Object.assign(body, extra);
        }
        const apiMode =
          effectiveMode === "plan" ? "plan_discover" : effectiveMode;
        if (apiMode !== "instant") {
          body.mode = apiMode;
        }
        if (apiMode === "plan_execute") {
          const pt = (planExecuteTextOverride ?? "").trim();
          if (pt) {
            body.plan_text = pt;
          }
        }
        lastTerminalStreamEventRef.current = null;
        await streamHofFunction("agent_chat", body, {
          signal: abortRef.current.signal,
          onEvent: (ev) => {
            if (myId !== reqIdRef.current) {
              return;
            }
            const typ = typeof ev.type === "string" ? ev.type : "";
            if (
              typ === "final" ||
              typ === "awaiting_confirmation" ||
              typ === "awaiting_inbox_review" ||
              typ === "awaiting_plan_clarification" ||
              typ === "error"
            ) {
              lastTerminalStreamEventRef.current = ev;
            }
            if (typ === "plan_todo_update") {
              const di = (ev as { done_indices?: unknown }).done_indices;
              if (Array.isArray(di)) {
                setPlanTodoDoneIndices((prev) => {
                  const s = new Set(prev);
                  for (const x of di) {
                    const n = Number(x);
                    if (Number.isFinite(n)) {
                      s.add(n);
                    }
                  }
                  return Array.from(s).sort((a, b) => a - b);
                });
              }
            }
            if (typ === "run_start") {
              assistantStreamPhaseRef.current = null;
              pendingDetailsRef.current.clear();
              mutationPendingIdsThisRunRef.current = [];
              currentAgentRunIdRef.current = coerceRunId(ev.run_id);
              setApprovalBarrier(null);
              setApprovalDecisions({});
              setInboxReviewBarrier(null);
              setInboxResumeError(null);
              setProviderWaitNotice(null);
              updateThinkingEpisodeStart(Date.now());
            }
            if (effectiveMode === "plan" && typ === "tool_call") {
              planDraftBufferRef.current = "";
              setPlanText("");
            }
            if (
              planDraftStreamingActiveRef.current &&
              typ === "assistant_delta"
            ) {
              const chunk =
                typeof (ev as { text?: unknown }).text === "string"
                  ? (ev as { text: string }).text
                  : "";
              if (chunk) {
                planDraftBufferRef.current += chunk;
                setPlanText(planDraftBufferRef.current);
              }
            }
            if (
              typ === "final" ||
              typ === "awaiting_plan_clarification" ||
              typ === "error"
            ) {
              planDraftStreamingActiveRef.current = false;
            }
            updateProviderWaitFromStreamType(typ, ev, setProviderWaitNotice);
            if (typ === "phase") {
              const ph = typeof ev.phase === "string" ? ev.phase : "";
              if (ph === "model") {
                updateThinkingEpisodeStart(Date.now());
              }
              if (ph === "model" || ph === "summary") {
                assistantStreamPhaseRef.current = ph;
              }
            }
            if (typ === "mutation_pending") {
              const pid =
                typeof ev.pending_id === "string" ? ev.pending_id : "";
              if (pid) {
                pendingDetailsRef.current.set(
                  pid,
                  pendingDetailsFromMutationPendingEvent(ev),
                );
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
                ? (ev.pending_ids as unknown[])
                    .map((x) => String(x))
                    .filter(Boolean)
                : [];
              const pids = mergePendingIdLists(
                fromEvent,
                mutationPendingIdsThisRunRef.current,
                mutationPendingIdsFromBlocks(liveBlocksRef.current),
              );
              const itemsBarrier = pids.map((pid) =>
                approvalBarrierItemFromDetails(
                  pid,
                  pendingDetailsRef.current.get(pid),
                ),
              );
              setApprovalBarrier({ runId: rid, items: itemsBarrier });
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
            if (typ === "awaiting_inbox_review") {
              const parsed = inboxReviewBarrierFromStreamEvent(ev);
              if (parsed) {
                setInboxReviewBarrier(parsed);
                setInboxResumeError(null);
                setApprovalBarrier(null);
                setApprovalDecisions({});
              }
            }
            setLiveBlocks((prev) => {
              const et =
                typeof evForBlocks.type === "string"
                  ? evForBlocks.type
                  : "";
              const next = applyStreamEventWithDedupe(prev, evForBlocks, {
                assistantStreamPhase: assistantStreamPhaseRef.current,
                thinkingEpisodeStartedAtMs:
                  thinkingEpisodeStartedAtRef.current,
                ...(et === "assistant_done"
                  ? { assistantDoneClockMs: Date.now() }
                  : {}),
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
          const itemsSynth = synthPids.map((pid) =>
            approvalBarrierItemFromDetails(
              pid,
              pendingDetailsRef.current.get(pid),
            ),
          );
          setApprovalBarrier({ runId: ridForSynth, items: itemsSynth });
          setApprovalDecisions(
            Object.fromEntries(synthPids.map((p) => [p, null])) as Record<
              string,
              boolean | null
            >,
          );
        }
        const term = lastTerminalStreamEventRef.current;
        const termTyp =
          term && typeof term.type === "string" ? String(term.type) : "";
        const termMode =
          term && typeof term.mode === "string" ? String(term.mode) : "";
        if (
          termTyp === "final" &&
          termMode === "plan" &&
          effectiveMode === "plan"
        ) {
          const replyRaw = term?.reply;
          const reply =
            typeof replyRaw === "string" ? replyRaw.trim() : "";
          const planRid = newId();
          setPlanRunId(planRid);
          const toFlush = stripLastAssistantBlockForPlan(doneBlocks);
          if (toFlush.length > 0) {
            flushLiveToThread(structuredClone(toFlush), {
              presetRunId: planRid,
            });
          }
          setPlanText(preferPlanTaskListBody(reply));
          setPlanPhase("ready");
          setPlanClarificationBarrier(null);
        } else if (doneBlocks.length > 0) {
          flushLiveToThread(structuredClone(doneBlocks));
        }
        if (termTyp === "awaiting_plan_clarification" && term) {
          const rid = coerceRunId(term.run_id);
          const clarificationId = String(term.clarification_id ?? "").trim();
          const qs = term.questions;
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
          if (rid && clarificationId && questions.length > 0) {
            setPlanClarificationSubmittedSummary([]);
            setPlanClarificationBarrier({
              runId: rid,
              clarificationId,
              questions,
            });
            setPlanPhase("clarifying");
          }
          if (doneBlocks.length > 0) {
            flushLiveToThread(structuredClone(doneBlocks));
          }
        }
        liveBlocksRef.current = [];
        setLiveBlocks([]);
        if (effectiveMode === "plan") {
          setPlanPhase((prev) => {
            if (prev === "generating" && termTyp === "error") {
              return null;
            }
            return prev;
          });
        }
        applyPlanExecuteStreamCompletion(termTyp);
      } catch (e) {
        if (myId !== reqIdRef.current) {
          return;
        }
        if (e instanceof Error && e.name === "AbortError") {
          const raw = liveBlocksRef.current;
          if (raw.length > 0) {
            const frozen = finalizeLiveBlocksAfterUserStop(
              structuredClone(raw),
            );
            if (frozen.length > 0) {
              flushLiveToThread(structuredClone(frozen));
            }
          }
          liveBlocksRef.current = [];
          setLiveBlocks([]);
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
          updateThinkingEpisodeStart(null);
          sendingRef.current = false;
          setProviderWaitNotice(null);
        }
      }
    },
    [
      applyPlanExecuteStreamCompletion,
      flushLiveToThread,
      finalizeLiveBlocksAfterUserStop,
      prepareAgentChatRequest,
      threadToApiMessages,
      updateThinkingEpisodeStart,
    ],
  );

  const submitPlanClarification = useCallback(
    async (
      answers: {
        question_id: string;
        selected_option_ids: string[];
        other_text?: string;
      }[],
    ) => {
      const barrier = planClarificationBarrier;
      if (!barrier || busy) {
        return;
      }
      const summary = barrier.questions.map((q) => {
        const a = answers.find((x) => x.question_id === q.id);
        const labels = (a?.selected_option_ids ?? []).map((oid) => {
          const opt = q.options.find((o) => o.id === oid);
          return opt?.label ?? oid;
        });
        if (a?.other_text) {
          labels.push(a.other_text);
        }
        return { prompt: q.prompt, selectedLabels: labels };
      });
      setPlanClarificationSubmittedSummary(summary);
      setPlanClarificationBarrier(null);
      setPlanPhase("generating");
      planDraftStreamingActiveRef.current = true;
      planDraftBufferRef.current = "";
      setPlanText("");
      const myId = ++reqIdRef.current;
      abortRef.current?.abort();
      abortRef.current = new AbortController();
      setBusy(true);
      updateThinkingEpisodeStart(Date.now());
      liveBlocksRef.current = [];
      setLiveBlocks([]);
      currentAgentRunIdRef.current = "";
      lastTerminalStreamEventRef.current = null;
      try {
        const body: Record<string, unknown> = {
          run_id: barrier.runId,
          clarification_id: barrier.clarificationId,
          answers,
        };
        const prep =
          prepareAgentResumePlanClarificationRequest ?? prepareAgentResumeRequest;
        if (prep) {
          Object.assign(body, await prep());
        }
        await streamHofFunction("agent_resume_plan_clarification", body, {
          signal: abortRef.current.signal,
          onEvent: (ev) => {
            if (myId !== reqIdRef.current) {
              return;
            }
            const typ = typeof ev.type === "string" ? ev.type : "";
            if (
              typ === "final" ||
              typ === "awaiting_plan_clarification" ||
              typ === "error"
            ) {
              lastTerminalStreamEventRef.current = ev;
              planDraftStreamingActiveRef.current = false;
            }
            if (typ === "plan_todo_update") {
              const di = (ev as { done_indices?: unknown }).done_indices;
              if (Array.isArray(di)) {
                setPlanTodoDoneIndices((prev) => {
                  const s = new Set(prev);
                  for (const x of di) {
                    const n = Number(x);
                    if (Number.isFinite(n)) {
                      s.add(n);
                    }
                  }
                  return Array.from(s).sort((a, b) => a - b);
                });
              }
            }
            updateProviderWaitFromStreamType(typ, ev, setProviderWaitNotice);
            if (typ === "phase") {
              const ph = typeof ev.phase === "string" ? ev.phase : "";
              if (ph === "model") {
                updateThinkingEpisodeStart(Date.now());
              }
              if (ph === "model" || ph === "summary") {
                assistantStreamPhaseRef.current = ph;
              }
            }
            if (typ === "run_start" || typ === "resume_start") {
              currentAgentRunIdRef.current = coerceRunId(ev.run_id);
              updateThinkingEpisodeStart(Date.now());
            }
            if (typ === "tool_call") {
              planDraftBufferRef.current = "";
              setPlanText("");
            }
            if (
              planDraftStreamingActiveRef.current &&
              typ === "assistant_delta"
            ) {
              const chunk =
                typeof (ev as { text?: unknown }).text === "string"
                  ? (ev as { text: string }).text
                  : "";
              if (chunk) {
                planDraftBufferRef.current += chunk;
                setPlanText(planDraftBufferRef.current);
              }
            }
            setLiveBlocks((prev) => {
              const et =
                typeof ev.type === "string" ? ev.type : "";
              const next = applyStreamEventWithDedupe(prev, ev, {
                assistantStreamPhase: assistantStreamPhaseRef.current,
                thinkingEpisodeStartedAtMs:
                  thinkingEpisodeStartedAtRef.current,
                ...(et === "assistant_done"
                  ? { assistantDoneClockMs: Date.now() }
                  : {}),
              });
              liveBlocksRef.current = next;
              return next;
            });
          },
        });
        if (myId !== reqIdRef.current) {
          return;
        }
        const term = lastTerminalStreamEventRef.current;
        const termTyp =
          term && typeof term.type === "string" ? String(term.type) : "";
        const termMode =
          term && typeof term.mode === "string" ? String(term.mode) : "";
        const doneBlocks = liveBlocksRef.current;
        if (termTyp === "final" && termMode === "plan" && term) {
          const replyRaw = term.reply;
          const reply =
            typeof replyRaw === "string" ? replyRaw.trim() : "";
          const planRid = newId();
          setPlanRunId(planRid);
          const toFlush = stripLastAssistantBlockForPlan(doneBlocks);
          if (toFlush.length > 0) {
            flushLiveToThread(structuredClone(toFlush), {
              presetRunId: planRid,
            });
          }
          setPlanText(preferPlanTaskListBody(reply));
          setPlanPhase("ready");
          setPlanClarificationBarrier(null);
        } else if (termTyp === "awaiting_plan_clarification" && term) {
          const rid = coerceRunId(term.run_id);
          const clarificationId = String(
            term.clarification_id ?? "",
          ).trim();
          const qs = term.questions;
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
          if (rid && clarificationId && questions.length > 0) {
            setPlanClarificationSubmittedSummary([]);
            setPlanClarificationBarrier({
              runId: rid,
              clarificationId,
              questions,
            });
            setPlanPhase("clarifying");
          }
          if (doneBlocks.length > 0) {
            flushLiveToThread(structuredClone(doneBlocks));
          }
        } else if (doneBlocks.length > 0) {
          flushLiveToThread(structuredClone(doneBlocks));
        }
        liveBlocksRef.current = [];
        setLiveBlocks([]);
      } catch (e) {
        if (myId !== reqIdRef.current) {
          return;
        }
        if (e instanceof Error && e.name === "AbortError") {
          liveBlocksRef.current = [];
          setLiveBlocks([]);
          return;
        }
        const msg = e instanceof Error ? e.message : String(e);
        liveBlocksRef.current = [];
        setLiveBlocks([
          { kind: "error", id: newId(), detail: msg } as LiveBlock,
        ]);
      } finally {
        if (myId === reqIdRef.current) {
          setBusy(false);
          updateThinkingEpisodeStart(null);
          setProviderWaitNotice(null);
        }
      }
    },
    [
      busy,
      planClarificationBarrier,
      prepareAgentResumePlanClarificationRequest,
      prepareAgentResumeRequest,
      flushLiveToThread,
      updateThinkingEpisodeStart,
    ],
  );

  const dismissPlanClarificationBarrier = useCallback(() => {
    setPlanClarificationBarrier(null);
    setPlanPhase(null);
  }, []);

  const executePlan = useCallback(() => {
    if (planPhase !== "ready" || busy) {
      return;
    }
    setPlanPhase("executing");
    setPlanTodoDoneIndices([]);
    planExecuteActiveRef.current = true;
    const next = [
      ...threadRef.current,
      {
        kind: "user" as const,
        id: newId(),
        content: PLAN_EXECUTE_USER_MARKER,
        attachments: [],
      },
    ];
    setThread(next);
    threadRef.current = next;
    void runAgent(next, "plan_execute", planText);
  }, [planPhase, busy, planText, runAgent]);

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
    updateThinkingEpisodeStart(Date.now());
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
      const resumeBody: Record<string, unknown> = { run_id: rid, resolutions };
      if (prepareAgentResumeRequest) {
        const extra = await prepareAgentResumeRequest();
        Object.assign(resumeBody, extra);
      }
      await streamHofFunction("agent_resume_mutations", resumeBody, {
        signal: abortRef.current.signal,
        onEvent: (ev) => {
          if (myId !== reqIdRef.current) {
            return;
          }
          const rtyp = typeof ev.type === "string" ? ev.type : "";
          if (
            rtyp === "final" ||
            rtyp === "awaiting_confirmation" ||
            rtyp === "awaiting_inbox_review" ||
            rtyp === "awaiting_plan_clarification" ||
            rtyp === "error"
          ) {
            lastTerminalStreamEventRef.current = ev;
          }
          if (rtyp === "plan_todo_update") {
            const di = (ev as { done_indices?: unknown }).done_indices;
            if (Array.isArray(di)) {
              setPlanTodoDoneIndices((prev) => {
                const s = new Set(prev);
                for (const x of di) {
                  const n = Number(x);
                  if (Number.isFinite(n)) {
                    s.add(n);
                  }
                }
                return Array.from(s).sort((a, b) => a - b);
              });
            }
          }
          if (rtyp === "resume_start") {
            resumeMergeContinuationRef.current =
              (ev as { continuation?: unknown }).continuation === true;
            assistantStreamPhaseRef.current = null;
            currentAgentRunIdRef.current = coerceRunId(ev.run_id);
            pendingDetailsRef.current.clear();
            mutationPendingIdsThisRunRef.current = [];
            setInboxReviewBarrier(null);
            setInboxResumeError(null);
            setProviderWaitNotice(null);
            updateThinkingEpisodeStart(Date.now());
          }
          updateProviderWaitFromStreamType(rtyp, ev, setProviderWaitNotice);
          if (rtyp === "phase") {
            const ph = typeof ev.phase === "string" ? ev.phase : "";
            if (ph === "model") {
              updateThinkingEpisodeStart(Date.now());
            }
            if (ph === "model" || ph === "summary") {
              assistantStreamPhaseRef.current = ph;
            }
          }
          if (rtyp === "mutation_pending") {
            const pid = typeof ev.pending_id === "string" ? ev.pending_id : "";
            if (pid) {
              pendingDetailsRef.current.set(
                pid,
                pendingDetailsFromMutationPendingEvent(ev),
              );
              const acc = mutationPendingIdsThisRunRef.current;
              if (!acc.includes(pid)) {
                acc.push(pid);
              }
            }
          }
          let evForBlocks: HofStreamEvent = ev;
          if (rtyp === "awaiting_confirmation") {
            const awRid =
              coerceRunId(ev.run_id) || currentAgentRunIdRef.current.trim();
            const fromEvent = Array.isArray(ev.pending_ids)
              ? (ev.pending_ids as unknown[])
                  .map((x) => String(x))
                  .filter(Boolean)
              : [];
            const pids = mergePendingIdLists(
              fromEvent,
              mutationPendingIdsThisRunRef.current,
              mutationPendingIdsFromBlocks(liveBlocksRef.current),
            );
            const itemsBarrier = pids.map((pid) =>
              approvalBarrierItemFromDetails(
                pid,
                pendingDetailsRef.current.get(pid),
              ),
            );
            setApprovalBarrier({ runId: awRid, items: itemsBarrier });
            const dec: Record<string, boolean | null> = {};
            for (const p of pids) {
              dec[p] = null;
            }
            setApprovalDecisions(dec);
            evForBlocks =
              pids.length > 0
                ? ({
                    ...ev,
                    run_id: awRid,
                    pending_ids: pids,
                  } as HofStreamEvent)
                : ev;
          }
          if (rtyp === "awaiting_inbox_review") {
            const parsed = inboxReviewBarrierFromStreamEvent(ev);
            if (parsed) {
              setInboxReviewBarrier(parsed);
              setInboxResumeError(null);
              setApprovalBarrier(null);
              setApprovalDecisions({});
            }
          }
          setLiveBlocks((prev) => {
            const rt =
              typeof evForBlocks.type === "string" ? evForBlocks.type : "";
            const next = applyStreamEventWithDedupe(prev, evForBlocks, {
              assistantStreamPhase: assistantStreamPhaseRef.current,
              thinkingEpisodeStartedAtMs: thinkingEpisodeStartedAtRef.current,
              ...(rt === "assistant_done"
                ? { assistantDoneClockMs: Date.now() }
                : {}),
            });
            liveBlocksRef.current = next;
            return next;
          });
        },
      });
      if (myId !== reqIdRef.current) {
        return;
      }
      {
        const term = lastTerminalStreamEventRef.current;
        const termTyp =
          term && typeof term.type === "string" ? String(term.type) : "";
        applyPlanExecuteStreamCompletion(termTyp);
      }
      setMutationOutcomeByPendingId((prev) => {
        const next = { ...prev };
        for (const row of outcomeSnapshot) {
          next[row.pendingId] = row.approved;
        }
        return next;
      });
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
        const itemsSynth = synthPids.map((pid) =>
          approvalBarrierItemFromDetails(
            pid,
            pendingDetailsRef.current.get(pid),
          ),
        );
        setApprovalBarrier({ runId: ridForSynth, items: itemsSynth });
        setApprovalDecisions(
          Object.fromEntries(synthPids.map((p) => [p, null])) as Record<
            string,
            boolean | null
          >,
        );
      } else if (!hasApprovalBlock && synthPids.length === 0) {
        setApprovalBarrier(null);
        setApprovalDecisions({});
        pendingDetailsRef.current.clear();
      }
      const mergeCont = resumeMergeContinuationRef.current;
      resumeMergeContinuationRef.current = false;
      if (doneBlocks.length > 0) {
        flushLiveToThread(structuredClone(doneBlocks), {
          mergeContinuation: mergeCont,
        });
      }
      liveBlocksRef.current = [];
      setLiveBlocks([]);
    } catch (e) {
      if (myId !== reqIdRef.current) {
        return;
      }
      if (e instanceof Error && e.name === "AbortError") {
        const raw = liveBlocksRef.current;
        if (raw.length > 0) {
          const frozen = finalizeLiveBlocksAfterUserStop(structuredClone(raw));
          if (frozen.length > 0) {
            flushLiveToThread(structuredClone(frozen));
          }
        }
        liveBlocksRef.current = [];
        setLiveBlocks([]);
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
        updateThinkingEpisodeStart(null);
        setProviderWaitNotice(null);
      }
    }
  }, [
    applyPlanExecuteStreamCompletion,
    approvalBarrier,
    approvalDecisions,
    flushLiveToThread,
    finalizeLiveBlocksAfterUserStop,
    prepareAgentResumeRequest,
    updateThinkingEpisodeStart,
  ]);

  const runInboxResume = useCallback(
    async (barrier: InboxReviewBarrier) => {
      const myId = ++reqIdRef.current;
      abortRef.current?.abort();
      abortRef.current = new AbortController();
      setBusy(true);
      setInboxResumeError(null);
      updateThinkingEpisodeStart(Date.now());
      liveBlocksRef.current = [];
      setLiveBlocks([]);
      mutationPendingIdsThisRunRef.current = [];
      const resolutions = barrier.watches.map((w) => ({
        watch_id: w.watch_id,
      }));
      const rid = barrier.runId;
      try {
        const resumeBody: Record<string, unknown> = {
          run_id: rid,
          resolutions,
        };
        const prep =
          prepareAgentResumeInboxRequest ?? prepareAgentResumeRequest;
        if (prep) {
          const extra = await prep();
          Object.assign(resumeBody, extra);
        }
        await streamHofFunction("agent_resume_inbox_reviews", resumeBody, {
          signal: abortRef.current.signal,
          onEvent: (ev) => {
            if (myId !== reqIdRef.current) {
              return;
            }
            const rtyp = typeof ev.type === "string" ? ev.type : "";
            if (
              rtyp === "final" ||
              rtyp === "awaiting_confirmation" ||
              rtyp === "awaiting_inbox_review" ||
              rtyp === "awaiting_plan_clarification" ||
              rtyp === "error"
            ) {
              lastTerminalStreamEventRef.current = ev;
            }
            if (rtyp === "plan_todo_update") {
              const di = (ev as { done_indices?: unknown }).done_indices;
              if (Array.isArray(di)) {
                setPlanTodoDoneIndices((prev) => {
                  const s = new Set(prev);
                  for (const x of di) {
                    const n = Number(x);
                    if (Number.isFinite(n)) {
                      s.add(n);
                    }
                  }
                  return Array.from(s).sort((a, b) => a - b);
                });
              }
            }
            if (rtyp === "error") {
              const detail =
                typeof ev.detail === "string" ? ev.detail : "error";
              setInboxResumeError(detail);
            }
            if (rtyp === "resume_start") {
              resumeMergeContinuationRef.current =
                (ev as { continuation?: unknown }).continuation === true;
              assistantStreamPhaseRef.current = null;
              currentAgentRunIdRef.current = coerceRunId(ev.run_id);
              pendingDetailsRef.current.clear();
              mutationPendingIdsThisRunRef.current = [];
              setInboxReviewBarrier(null);
              setInboxResumeError(null);
              setProviderWaitNotice(null);
              updateThinkingEpisodeStart(Date.now());
            }
            updateProviderWaitFromStreamType(rtyp, ev, setProviderWaitNotice);
            if (rtyp === "phase") {
              const ph = typeof ev.phase === "string" ? ev.phase : "";
              if (ph === "model") {
                updateThinkingEpisodeStart(Date.now());
              }
              if (ph === "model" || ph === "summary") {
                assistantStreamPhaseRef.current = ph;
              }
            }
            if (rtyp === "mutation_pending") {
              const pid =
                typeof ev.pending_id === "string" ? ev.pending_id : "";
              if (pid) {
                pendingDetailsRef.current.set(
                  pid,
                  pendingDetailsFromMutationPendingEvent(ev),
                );
                const acc = mutationPendingIdsThisRunRef.current;
                if (!acc.includes(pid)) {
                  acc.push(pid);
                }
              }
            }
            let evForBlocks: HofStreamEvent = ev;
            if (rtyp === "awaiting_confirmation") {
              const awRid =
                coerceRunId(ev.run_id) || currentAgentRunIdRef.current.trim();
              const fromEvent = Array.isArray(ev.pending_ids)
                ? (ev.pending_ids as unknown[])
                    .map((x) => String(x))
                    .filter(Boolean)
                : [];
              const pids = mergePendingIdLists(
                fromEvent,
                mutationPendingIdsThisRunRef.current,
                mutationPendingIdsFromBlocks(liveBlocksRef.current),
              );
              const itemsBarrier = pids.map((pid) =>
                approvalBarrierItemFromDetails(
                  pid,
                  pendingDetailsRef.current.get(pid),
                ),
              );
              setApprovalBarrier({ runId: awRid, items: itemsBarrier });
              const dec: Record<string, boolean | null> = {};
              for (const p of pids) {
                dec[p] = null;
              }
              setApprovalDecisions(dec);
              evForBlocks =
                pids.length > 0
                  ? ({
                      ...ev,
                      run_id: awRid,
                      pending_ids: pids,
                    } as HofStreamEvent)
                  : ev;
            }
            if (rtyp === "awaiting_inbox_review") {
              const parsed = inboxReviewBarrierFromStreamEvent(ev);
              if (parsed) {
                setInboxReviewBarrier(parsed);
                setInboxResumeError(null);
                setApprovalBarrier(null);
                setApprovalDecisions({});
              }
            }
            setLiveBlocks((prev) => {
              const rt =
                typeof evForBlocks.type === "string" ? evForBlocks.type : "";
              const next = applyStreamEventWithDedupe(prev, evForBlocks, {
                assistantStreamPhase: assistantStreamPhaseRef.current,
                thinkingEpisodeStartedAtMs: thinkingEpisodeStartedAtRef.current,
                ...(rt === "assistant_done"
                  ? { assistantDoneClockMs: Date.now() }
                  : {}),
              });
              liveBlocksRef.current = next;
              return next;
            });
          },
        });
        if (myId !== reqIdRef.current) {
          return;
        }
        {
          const term = lastTerminalStreamEventRef.current;
          const termTyp =
            term && typeof term.type === "string" ? String(term.type) : "";
          applyPlanExecuteStreamCompletion(termTyp);
        }
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
          const itemsSynth = synthPids.map((pid) =>
            approvalBarrierItemFromDetails(
              pid,
              pendingDetailsRef.current.get(pid),
            ),
          );
          setApprovalBarrier({ runId: ridForSynth, items: itemsSynth });
          setApprovalDecisions(
            Object.fromEntries(synthPids.map((p) => [p, null])) as Record<
              string,
              boolean | null
            >,
          );
        } else if (!hasApprovalBlock && synthPids.length === 0) {
          setApprovalBarrier(null);
          setApprovalDecisions({});
          pendingDetailsRef.current.clear();
        }
        const mergeCont = resumeMergeContinuationRef.current;
        resumeMergeContinuationRef.current = false;
        if (doneBlocks.length > 0) {
          flushLiveToThread(structuredClone(doneBlocks), {
            mergeContinuation: mergeCont,
          });
        }
        liveBlocksRef.current = [];
        setLiveBlocks([]);
      } catch (e) {
        if (myId !== reqIdRef.current) {
          return;
        }
        if (e instanceof Error && e.name === "AbortError") {
          const raw = liveBlocksRef.current;
          if (raw.length > 0) {
            const frozen = finalizeLiveBlocksAfterUserStop(
              structuredClone(raw),
            );
            if (frozen.length > 0) {
              flushLiveToThread(structuredClone(frozen));
            }
          }
          liveBlocksRef.current = [];
          setLiveBlocks([]);
          return;
        }
        const msg = e instanceof Error ? e.message : String(e);
        setInboxResumeError(msg);
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
          updateThinkingEpisodeStart(null);
          setProviderWaitNotice(null);
        }
      }
    },
    [
      applyPlanExecuteStreamCompletion,
      flushLiveToThread,
      finalizeLiveBlocksAfterUserStop,
      prepareAgentResumeInboxRequest,
      prepareAgentResumeRequest,
      updateThinkingEpisodeStart,
    ],
  );

  runResumeRef.current = runResume;
  runInboxResumeRef.current = runInboxResume;

  useEffect(() => {
    if (!approvalBarrier?.items.length || busy) {
      return;
    }
    if (
      barrierMatchesAnyThreadOrLiveBlocks(approvalBarrier, thread, liveBlocks)
    ) {
      return;
    }
    setApprovalBarrier(null);
    setApprovalDecisions({});
  }, [approvalBarrier, thread, liveBlocks, busy]);

  useEffect(() => {
    if (!approvalBarrier?.items.length) {
      approvalAutoResumeLockRef.current = false;
      return;
    }
    if (busy) {
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
    if (approvalAutoResumeLockRef.current) {
      return;
    }
    approvalAutoResumeLockRef.current = true;
    void (async () => {
      try {
        await runResumeRef.current();
      } finally {
        approvalAutoResumeLockRef.current = false;
      }
    })();
  }, [approvalBarrier, approvalDecisions, busy]);

  const inboxBarrierPollKey = useMemo(() => {
    if (!inboxReviewBarrier?.runId || !inboxReviewBarrier.watches.length) {
      return "";
    }
    const ids = inboxReviewBarrier.watches.map((w) => w.watch_id).sort();
    return `${inboxReviewBarrier.runId}:${ids.join(",")}`;
  }, [inboxReviewBarrier]);

  useEffect(() => {
    if (!inboxBarrierPollKey || busy) {
      return;
    }
    let cancelled = false;
    let delayMs = 2000;

    void (async () => {
      while (!cancelled) {
        const b = inboxReviewBarrierRef.current;
        if (!b || !b.watches.length) {
          return;
        }
        setInboxPollWaiting(true);
        let allDone = false;
        try {
          const results = await Promise.all(
            b.watches.map((w) => pollInboxWatchRef.current(w)),
          );
          allDone = results.every(Boolean);
        } finally {
          setInboxPollWaiting(false);
        }
        if (cancelled) {
          return;
        }
        if (allDone) {
          await runInboxResumeRef.current(b);
          return;
        }
        await new Promise((r) => setTimeout(r, delayMs));
        delayMs = Math.min(Math.round(delayMs * 1.35), 60_000);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [inboxBarrierPollKey, busy]);

  const confirmPendingMutations = useCallback(() => {
    void runResumeRef.current();
  }, []);

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
    if (approvalBarrier || inboxReviewBarrier) {
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
    updateThinkingEpisodeStart(Date.now());
    setInput("");
    abortRef.current?.abort();
    const baseThread = threadRef.current;
    // Do not merge ``liveBlocks`` into ``thread`` here. Completed turns are appended only via
    // ``flushLiveToThread`` inside ``runAgent`` / ``runResume`` / error handling. Re-archiving
    // stale ``liveBlocksRef`` on send duplicated the whole run (thread already had it + live area).
    liveBlocksRef.current = [];
    setLiveBlocks([]);
    const afterFlush = baseThread;
    const snap = [...attachmentQueue];
    const content = t;
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
  }, [
    approvalBarrier,
    inboxReviewBarrier,
    attachmentQueue,
    busy,
    input,
    runAgent,
    uploadBusy,
    updateThinkingEpisodeStart,
  ]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const dismissApprovalBarrier = useCallback(() => {
    abortRef.current?.abort();
    setApprovalBarrier(null);
    setApprovalDecisions({});
  }, []);

  const dismissInboxReviewBarrier = useCallback(() => {
    abortRef.current?.abort();
    setInboxReviewBarrier(null);
    setInboxResumeError(null);
    setInboxPollWaiting(false);
  }, []);

  const conversationEmpty = thread.length === 0 && liveBlocks.length === 0;

  const value = useMemo<HofAgentChatContextValue>(
    () => ({
      welcomeName,
      thread,
      liveBlocks,
      busy,
      input,
      setInput,
      attachmentQueue,
      setAttachmentQueue,
      uploadBusy,
      uploadErr,
      approvalBarrier,
      inboxReviewBarrier,
      inboxPollWaiting,
      inboxResumeError,
      approvalDecisions,
      setApprovalDecisions,
      mutationOutcomeByPendingId,
      fileInputRef,
      onPickFiles,
      send,
      stop,
      dismissApprovalBarrier,
      dismissInboxReviewBarrier,
      conversationEmpty,
      thinkingEpisodeStartedAtMs,
      providerWaitNotice,
      confirmPendingMutations,
      agentMode,
      setAgentMode,
      planPhase,
      planText,
      setPlanText,
      planRunId,
      planClarificationBarrier,
      planClarificationSubmittedSummary,
      submitPlanClarification,
      dismissPlanClarificationBarrier,
      planTodoDoneIndices,
      executePlan,
    }),
    [
      welcomeName,
      thread,
      liveBlocks,
      busy,
      input,
      attachmentQueue,
      uploadBusy,
      uploadErr,
      approvalBarrier,
      inboxReviewBarrier,
      inboxPollWaiting,
      inboxResumeError,
      approvalDecisions,
      mutationOutcomeByPendingId,
      onPickFiles,
      send,
      stop,
      dismissApprovalBarrier,
      dismissInboxReviewBarrier,
      conversationEmpty,
      thinkingEpisodeStartedAtMs,
      providerWaitNotice,
      confirmPendingMutations,
      agentMode,
      planPhase,
      planText,
      planRunId,
      planClarificationBarrier,
      planClarificationSubmittedSummary,
      submitPlanClarification,
      dismissPlanClarificationBarrier,
      planTodoDoneIndices,
      executePlan,
    ],
  );

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  return (
    <AssistantMarkdownLinkProvider
      onAssistantMarkdownLinkClick={onAssistantMarkdownLinkClick}
    >
      <HofAgentChatContext.Provider value={value}>
        {children}
      </HofAgentChatContext.Provider>
    </AssistantMarkdownLinkProvider>
  );
}
