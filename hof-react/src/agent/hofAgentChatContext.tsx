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
  streamHofFunction,
  type HofStreamEvent,
} from "../hooks/streamHofFunction";
import type { AgentConversationStateV1 } from "./conversationTypes";
import type {
  AgentAttachment,
  ApprovalBarrier,
  LiveBlock,
  ThreadItem,
} from "./hofAgentChatModel";
import {
  applyStreamEventWithDedupe,
  collectThreadAttachments,
  compactBlocksForHistory,
  coerceRunId,
  mergePendingIdLists,
  mutationPendingIdsFromBlocks,
  newId,
  toolResultAwaitingUserConfirmation,
} from "./hofAgentChatModel";

export type HofAgentChatPresignInput = {
  filename: string;
  content_type: string;
};

export type HofAgentChatPresignResult = {
  upload_url: string;
  object_key: string;
};

export type HofAgentChatProps = {
  welcomeName: string;
  presignUpload: (
    input: HofAgentChatPresignInput,
  ) => Promise<HofAgentChatPresignResult>;
  className?: string;
  initialPersisted?: AgentConversationStateV1 | null;
  onPersist?: (state: AgentConversationStateV1) => void | Promise<void>;
  persistDebounceMs?: number;
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
  approvalDecisions: Record<string, boolean | null>;
  setApprovalDecisions: Dispatch<
    SetStateAction<Record<string, boolean | null>>
  >;
  mutationOutcomeByPendingId: Record<string, boolean | undefined>;
  fileInputRef: RefObject<HTMLInputElement | null>;
  onPickFiles: (files: FileList | null) => Promise<void>;
  send: () => void;
  conversationEmpty: boolean;
};

const HofAgentChatContext = createContext<HofAgentChatContextValue | null>(
  null,
);

export function useHofAgentChat(): HofAgentChatContextValue {
  const v = useContext(HofAgentChatContext);
  if (!v) {
    throw new Error(
      "useHofAgentChat must be used within HofAgentChatProvider",
    );
  }
  return v;
}

export function HofAgentChatProvider({
  welcomeName,
  presignUpload,
  initialPersisted = null,
  onPersist,
  persistDebounceMs = 1200,
  children,
}: HofAgentChatProviderProps) {
  const [thread, setThread] = useState<ThreadItem[]>([]);
  const [liveBlocks, setLiveBlocks] = useState<LiveBlock[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [attachmentQueue, setAttachmentQueue] = useState<AgentAttachment[]>(
    [],
  );
  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploadErr, setUploadErr] = useState<string | null>(null);
  const [approvalBarrier, setApprovalBarrier] =
    useState<ApprovalBarrier | null>(null);
  const [approvalDecisions, setApprovalDecisions] = useState<
    Record<string, boolean | null>
  >({});
  const [mutationOutcomeByPendingId, setMutationOutcomeByPendingId] =
    useState<Record<string, boolean | undefined>>({});
  const fileInputRef = useRef<HTMLInputElement>(null);
  const threadRef = useRef<ThreadItem[]>([]);
  const sendingRef = useRef(false);
  const reqIdRef = useRef(0);
  const runResumeRef = useRef<() => Promise<void>>(async () => {});
  const autoResumeSentForRunRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const liveBlocksRef = useRef<LiveBlock[]>([]);
  const pendingDetailsRef = useRef(
    new Map<string, { name: string; cli_line: string }>(),
  );
  const mutationPendingIdsThisRunRef = useRef<string[]>([]);
  const currentAgentRunIdRef = useRef("");
  const assistantStreamPhaseRef = useRef<"model" | "summary" | null>(null);
  const skipNextPersistRef = useRef(true);

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
      const th = (Array.isArray(snap.thread) ? snap.thread : []) as ThreadItem[];
      const last = th.length > 0 ? th[th.length - 1] : undefined;
      // Saved state sometimes had both a final ``run`` on the thread and the same blocks still
      // in ``draft.liveBlocks`` (persist race). That paints the whole turn twice after reload/fetch.
      const discardDraftLive =
        lb.length > 0 &&
        !d.approvalBarrier?.runId &&
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
      setApprovalDecisions(
        d.approvalDecisions && typeof d.approvalDecisions === "object"
          ? { ...d.approvalDecisions }
          : {},
      );
    } else {
      liveBlocksRef.current = [];
      setLiveBlocks([]);
      setApprovalBarrier(null);
      setApprovalDecisions({});
    }
    setAttachmentQueue([]);
    setInput("");
    setUploadErr(null);
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
        lastForDraft?.kind === "run" &&
        liveBlocks.length > 0;
      const draftLiveBlocks = draftLiveStale ? [] : liveBlocks;
      const hasDraft =
        draftLiveBlocks.length > 0 || approvalBarrier !== null || busy;
      const state: AgentConversationStateV1 = {
        version: 1,
        thread: structuredClone(thread) as unknown[],
        mutationOutcomes: outcomes,
        draft: hasDraft
          ? {
              liveBlocks: structuredClone(draftLiveBlocks) as unknown[],
              approvalBarrier,
              approvalDecisions: { ...approvalDecisions },
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
    approvalDecisions,
    busy,
    onPersist,
    persistDebounceMs,
  ]);

  useEffect(() => {
    threadRef.current = thread;
  }, [thread]);

  /** Drop ``liveBlocks`` when they are leftover from a turn already stored as the last ``run`` row. */
  useEffect(() => {
    if (busy || approvalBarrier) {
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
  }, [thread, liveBlocks, busy, approvalBarrier]);

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
                ? (ev.pending_ids as unknown[])
                    .map((x) => String(x))
                    .filter(Boolean)
                : [];
              const pids = mergePendingIdLists(
                fromEvent,
                mutationPendingIdsThisRunRef.current,
                mutationPendingIdsFromBlocks(liveBlocksRef.current),
              );
              const itemsBarrier = pids.map((pid) => ({
                pendingId: pid,
                name: pendingDetailsRef.current.get(pid)?.name || "mutation",
                cli_line: pendingDetailsRef.current.get(pid)?.cli_line || "",
              }));
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
          const itemsSynth = synthPids.map((pid) => ({
            pendingId: pid,
            name: pendingDetailsRef.current.get(pid)?.name || "mutation",
            cli_line: pendingDetailsRef.current.get(pid)?.cli_line || "",
          }));
          setApprovalBarrier({ runId: ridForSynth, items: itemsSynth });
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
  }, [approvalBarrier, attachmentQueue, busy, input, runAgent, uploadBusy]);

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
      approvalDecisions,
      setApprovalDecisions,
      mutationOutcomeByPendingId,
      fileInputRef,
      onPickFiles,
      send,
      conversationEmpty,
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
      approvalDecisions,
      mutationOutcomeByPendingId,
      onPickFiles,
      send,
      conversationEmpty,
    ],
  );

  return (
    <HofAgentChatContext.Provider value={value}>
      {children}
    </HofAgentChatContext.Provider>
  );
}
