"use client";

import {
  AlertTriangle,
  List,
  Loader2,
  Mic,
  Paperclip,
  Plus,
  Search,
  Sparkles,
  Terminal,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { AssistantMarkdown } from "./AssistantMarkdown";
import {
  fetchAgentTools,
  type AgentToolInfo,
  type AgentToolsResponse,
} from "./fetchAgentTools";
import {
  isGuidanceRedundantInDescription,
  prepareSkillMarkdownField,
  stripGuidanceParagraphsForStructuredSections,
} from "./prepareSkillFieldForMarkdown";
import { humanizeToolName } from "./hofAgentChatModel";
import { AGENT_CHAT_ATTACHMENT_ACCEPT } from "./agentAttachmentUpload";
import { useHofAgentChat } from "./hofAgentChatContext";
import {
  useAgentVoiceTranscription,
  type AgentVoiceTranscriptionState,
} from "./useAgentVoiceTranscription";
import { useMenuDismiss } from "./useMenuDismiss";

const DEFAULT_TRANSCRIBE_PROMPT =
  "Transcribe exactly what is said verbatim. Do not translate.";

function readViteEnvString(key: string): string | undefined {
  try {
    const env = (import.meta as unknown as { env?: Record<string, string> })
      .env;
    const v = env?.[key];
    return typeof v === "string" && v.trim() ? v.trim() : undefined;
  } catch {
    return undefined;
  }
}

export type HofAgentComposerVoiceTranscription = {
  /** When `false`, hides the microphone control. Default: on. */
  enabled?: boolean;
  /** POST target for the SDP offer (default `/api/transcribe/session`). */
  sessionPath?: string;
  /** BCP-47 language for the transcription model (default `de`). */
  language?: string;
  /** Passed to the Realtime session `transcription.prompt`. */
  transcriptionPrompt?: string;
};

export type HofAgentComposerProps = {
  /** Wraps attachment chips, errors, and the composer shell. */
  className?: string;
  /** Bottom row: + menu left; mic + Send/Stop right (`justify-between`). */
  controlsRowClassName?: string;
  /** Bordered shell around the two-row composer (`flex flex-col`). */
  inputShellClassName?: string;
  disclaimerClassName?: string;
  /** Max height of the message field before it scrolls (px). */
  textareaMaxHeightPx?: number;
  /**
   * In Instant mode, show a “Try Plan mode” chip when the draft is longer than this many characters.
   * Set to `0` to disable. Default `80`.
   */
  planModePromptMinChars?: number;
  /** Streaming speech-to-text (OpenAI Realtime); optional Vite: `VITE_AGENT_TRANSCRIBE_*`. */
  voiceTranscription?: HofAgentComposerVoiceTranscription;
  /** Optional extra rows for the `+` composer menu. */
  extraAttachMenuItems?: (context: {
    closeMenu: () => void;
    inputLocked: boolean;
    busy: boolean;
  }) => ReactNode;
};

/** Square ghost icon control (plus / attach menu trigger). */
const squareIconBtnClass =
  "inline-flex size-9 shrink-0 items-center justify-center rounded-md border-0 bg-transparent text-secondary transition-colors hover:bg-hover hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40";
/** Matches {@link HofAgentConversationSelect} “New” button (outline + text-sm sizing). */
const sendBtnClass =
  "shrink-0 rounded-md border border-border bg-hover px-3 py-1.5 text-sm font-medium text-foreground transition-colors hover:bg-[var(--color-hover)] disabled:cursor-not-allowed disabled:opacity-40";

const MENU_ITEM_CLASS =
  "flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-foreground transition-colors hover:bg-hover";

/** Ghost control aligned with {@link squareIconBtnClass}: transparent, hover surface. */
const agentModeTriggerClass =
  "inline-flex h-9 min-w-[6.5rem] shrink-0 items-center gap-2 rounded-md border-0 bg-transparent px-2 text-[11px] font-medium text-secondary transition-colors hover:bg-hover hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40";

/**
 * Do not put `flex` / `block` on `<dialog>`: Tailwind would override UA `display:none` when closed,
 * leaving the shell visible (empty, mispositioned, Close ineffective until `[open]` matches).
 */
const SKILLS_DIALOG_SHELL_CLASS =
  "m-0 max-h-none w-full max-w-none border-0 bg-transparent p-0 shadow-none backdrop:bg-black/40";

/**
 * Full-viewport hit layer inside the modal top layer (backdrop does not receive DOM clicks).
 * Center the panel; mousedown on the scrim itself (not the panel) closes the dialog.
 */
const SKILLS_DIALOG_SCRIM_CLASS =
  "fixed inset-0 z-0 box-border flex items-center justify-center bg-transparent p-3";

/** Fixed height so nested `flex-1 min-h-0 overflow-y-auto` regions can scroll (max-h alone is not enough). */
const SKILLS_DIALOG_PANEL_CLASS =
  "relative z-[1] flex h-[min(calc(100vh-1.5rem),52rem)] w-[min(100vw-1.5rem,56rem)] max-w-full flex-col overflow-hidden rounded-lg border border-border bg-background font-sans text-foreground shadow-lg";

const REQUIRES_APPROVAL_LABEL = "Requires approval";

type VoiceBannerVariant = "setup" | "connecting" | "live";

function voiceBannerContent(
  state: AgentVoiceTranscriptionState,
): { title: string; body: string; variant: VoiceBannerVariant } | null {
  switch (state) {
    case "preparing_mic":
      return {
        title: "Allow the microphone",
        body: "If your browser shows a prompt, choose Allow. Audio is only used to fill this message.",
        variant: "setup",
      };
    case "linking_session":
      return {
        title: "Almost ready",
        body: "Connecting to live transcription. This often takes a few seconds.",
        variant: "connecting",
      };
    case "listening":
      return {
        title: "Listening",
        body: "Speak at a normal volume. Text appears after a short pause. Tap the mic again when you're done.",
        variant: "live",
      };
    case "finalizing":
      return {
        title: "Finishing transcription",
        body: "Your microphone is off. We are sending the last audio so nothing is cut off.",
        variant: "connecting",
      };
    default:
      return null;
  }
}

function voiceBannerShellClass(variant: VoiceBannerVariant): string {
  switch (variant) {
    case "setup":
      return "border-border bg-surface";
    case "connecting":
      return "border-[var(--color-accent)]/35 bg-[var(--color-accent)]/10";
    case "live":
      return "border-[var(--color-destructive)]/28 bg-[var(--color-destructive)]/8";
  }
}

function SkillSection({ label, source }: { label: string; source: string }) {
  const prepared = prepareSkillMarkdownField(source);
  if (!prepared) {
    return null;
  }
  return (
    <div>
      <h4 className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-tertiary">
        {label}
      </h4>
      <div className="text-[13px] leading-relaxed text-secondary [&_.hof-agent-md]:text-[13px] [&_.hof-agent-md]:leading-relaxed">
        <AssistantMarkdown source={prepared} />
      </div>
    </div>
  );
}

function toolParameterSummary(parameters: unknown): string {
  if (!parameters || typeof parameters !== "object") {
    return "";
  }
  const p = parameters as {
    properties?: Record<string, unknown>;
    required?: unknown;
  };
  const keys = Object.keys(p.properties ?? {});
  if (keys.length === 0) {
    return "No parameters.";
  }
  const reqRaw = p.required;
  const required = new Set(
    Array.isArray(reqRaw)
      ? reqRaw.filter((x): x is string => typeof x === "string")
      : [],
  );
  return keys
    .map((k) => `${k}${required.has(k) ? " (required)" : " (optional)"}`)
    .join(", ");
}

function skillSearchHaystack(t: AgentToolInfo): string {
  const parts = [
    t.name,
    humanizeToolName(t.name),
    t.tool_summary,
    t.description,
    t.when_to_use,
    t.when_not_to_use,
    ...t.related_tools,
    toolParameterSummary(t.parameters),
  ];
  return parts.join("\n").toLowerCase();
}

function filterToolsBySearchQuery(
  tools: AgentToolInfo[],
  query: string,
): AgentToolInfo[] {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) {
    return tools;
  }
  return tools.filter((t) => {
    const hay = skillSearchHaystack(t);
    return words.every((w) => hay.includes(w));
  });
}

/** One-line preview for the condensed list (no markdown rendering). */
function skillListPreviewLine(t: AgentToolInfo): string {
  const summary = t.tool_summary.trim();
  if (summary) {
    return summary.length <= 140 ? summary : `${summary.slice(0, 137)}…`;
  }
  const d = prepareSkillMarkdownField(t.description);
  const firstLine = d.split("\n").find((l) => l.trim()) ?? "";
  const plain = firstLine
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .trim();
  if (!plain) {
    return "";
  }
  return plain.length <= 120 ? plain : `${plain.slice(0, 117)}…`;
}

function SkillDetailPanel({
  tool: t,
  onBack,
}: {
  tool: AgentToolInfo;
  onBack: () => void;
}) {
  const descPrepared = prepareSkillMarkdownField(t.description);
  const whenPrepared = prepareSkillMarkdownField(t.when_to_use);
  const whenNotPrepared = prepareSkillMarkdownField(t.when_not_to_use);
  const whenSource = isGuidanceRedundantInDescription(
    descPrepared,
    whenPrepared,
  )
    ? ""
    : t.when_to_use;
  const whenNotSource = isGuidanceRedundantInDescription(
    descPrepared,
    whenNotPrepared,
  )
    ? ""
    : t.when_not_to_use;

  const descForDisplay = stripGuidanceParagraphsForStructuredSections(
    descPrepared,
    {
      showStructuredWhen: Boolean(whenSource.trim()),
      showStructuredWhenNot: Boolean(whenNotSource.trim()),
    },
  );

  return (
    <>
      <div className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2.5">
        <button
          type="button"
          className="inline-flex size-8 shrink-0 items-center justify-center rounded-md text-secondary hover:bg-hover hover:text-foreground"
          aria-label="Close details"
          onClick={onBack}
        >
          <X className="size-5" strokeWidth={2} aria-hidden />
        </button>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold text-foreground">
            {humanizeToolName(t.name)}
          </div>
        </div>
        {t.mutation ? (
          <span className="max-w-[9rem] shrink-0 rounded bg-hover px-1.5 py-0.5 text-center text-[10px] font-medium leading-tight text-secondary sm:max-w-none">
            {REQUIRES_APPROVAL_LABEL}
          </span>
        ) : null}
      </div>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        <SkillSection label="Summary" source={t.tool_summary} />
        <SkillSection label="Description" source={descForDisplay} />
        <SkillSection label="When to use" source={whenSource} />
        <SkillSection label="When not to use" source={whenNotSource} />
        {t.related_tools.length > 0 ? (
          <div>
            <h4 className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-tertiary">
              Typical next steps
            </h4>
            <div className="flex flex-wrap gap-1.5">
              {t.related_tools.map((r) => (
                <span
                  key={r}
                  className="rounded-md border border-border bg-background px-2 py-0.5 font-mono text-[11px] text-foreground"
                >
                  {r}
                </span>
              ))}
            </div>
          </div>
        ) : null}
        <div>
          <h4 className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-tertiary">
            Parameters
          </h4>
          <p className="text-[12px] leading-relaxed text-secondary">
            {toolParameterSummary(t.parameters)}
          </p>
        </div>
      </div>
    </>
  );
}

export function HofAgentComposer({
  className = "w-full",
  controlsRowClassName = "flex w-full items-center justify-between gap-2",
  inputShellClassName = "flex flex-col gap-2 rounded-md border border-border bg-background p-2",
  disclaimerClassName = "mt-2.5 mb-3 text-center text-[11px] leading-snug text-tertiary",
  textareaMaxHeightPx = 200,
  planModePromptMinChars = 80,
  voiceTranscription: voiceTranscriptionProp,
  extraAttachMenuItems,
}: HofAgentComposerProps) {
  const {
    input,
    setInput,
    send,
    stop,
    busy,
    uploadBusy,
    approvalBarrier,
    inboxReviewBarrier,
    dismissApprovalBarrier,
    dismissInboxReviewBarrier,
    attachmentQueue,
    setAttachmentQueue,
    uploadErr,
    fileInputRef,
    onPickFiles,
    conversationEmpty,
    providerWaitNotice,
    agentMode,
    setAgentMode,
    registerComposerTextarea,
  } = useHofAgentChat();

  const [providerWaitComposerTick, setProviderWaitComposerTick] = useState(0);
  useEffect(() => {
    if (!providerWaitNotice) {
      return;
    }
    const id = window.setInterval(() => {
      setProviderWaitComposerTick((t) => t + 1);
    }, 400);
    return () => window.clearInterval(id);
  }, [providerWaitNotice]);

  const providerWaitComposerHint = useMemo(() => {
    if (!providerWaitNotice) {
      return null;
    }
    const rem = Math.max(
      0,
      Math.ceil((providerWaitNotice.deadlineMs - Date.now()) / 1000),
    );
    return rem > 0
      ? `Temporary issue reaching the AI service — retrying automatically in ${rem}s. Nothing for you to do.`
      : "Temporary issue reaching the AI service — retrying now. Nothing for you to do.";
  }, [providerWaitNotice, providerWaitComposerTick]); // tick drives countdown refresh

  const voiceCfg = voiceTranscriptionProp ?? {};
  const voiceFeatureEnabled = voiceCfg.enabled !== false;
  const transcribeSessionPath =
    voiceCfg.sessionPath ??
    readViteEnvString("VITE_AGENT_TRANSCRIBE_SESSION_PATH") ??
    "/api/transcribe/session";
  const transcribeLanguage =
    voiceCfg.language ??
    readViteEnvString("VITE_AGENT_TRANSCRIBE_LANGUAGE") ??
    "de";
  const transcribePrompt =
    voiceCfg.transcriptionPrompt ?? DEFAULT_TRANSCRIBE_PROMPT;

  const {
    state: voiceState,
    interim: voiceInterim,
    error: voiceError,
    clearError: clearVoiceError,
    start: startVoice,
    stop: stopVoice,
  } = useAgentVoiceTranscription({
    sessionPath: transcribeSessionPath,
    language: transcribeLanguage,
    transcriptionPrompt: transcribePrompt,
  });

  const voiceSessionActive =
    voiceState === "preparing_mic" ||
    voiceState === "linking_session" ||
    voiceState === "listening" ||
    voiceState === "finalizing";
  const voiceIsLive = voiceState === "listening";
  const voiceConnecting =
    voiceState === "preparing_mic" ||
    voiceState === "linking_session" ||
    voiceState === "finalizing";
  const voiceBanner = voiceFeatureEnabled
    ? voiceBannerContent(voiceState)
    : null;
  const showVoiceButton = voiceFeatureEnabled && voiceState !== "unsupported";

  const [attachMenuOpen, setAttachMenuOpen] = useState(false);
  const attachMenuRef = useRef<HTMLDivElement>(null);
  const [modeMenuOpen, setModeMenuOpen] = useState(false);
  const modeMenuRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    registerComposerTextarea(textareaRef.current);
    return () => registerComposerTextarea(null);
  }, [registerComposerTextarea]);
  const skillsDialogRef = useRef<HTMLDialogElement>(null);
  const [skillsLoading, setSkillsLoading] = useState(false);
  const [skillsErr, setSkillsErr] = useState<string | null>(null);
  const [skillsData, setSkillsData] = useState<AgentToolsResponse | null>(null);
  const [skillsSearchQuery, setSkillsSearchQuery] = useState("");
  const [skillsSelectedTool, setSkillsSelectedTool] =
    useState<AgentToolInfo | null>(null);
  const [skillPanelEntered, setSkillPanelEntered] = useState(false);

  const syncTextareaHeight = useCallback(() => {
    const el = textareaRef.current;
    if (!el) {
      return;
    }
    // Reset to intrinsic height, reflow, then cap — required so scrollHeight drops
    // when lines are removed. (Do not add CSS height transitions here: they can
    // keep the used height from updating before this measurement runs.)
    el.style.height = "auto";
    void el.offsetHeight;
    const next = Math.min(el.scrollHeight, textareaMaxHeightPx);
    el.style.height = `${Math.max(next, 36)}px`;
  }, [textareaMaxHeightPx]);

  useLayoutEffect(() => {
    syncTextareaHeight();
  }, [input, voiceInterim, syncTextareaHeight]);

  useMenuDismiss(attachMenuOpen, setAttachMenuOpen, attachMenuRef);
  useMenuDismiss(modeMenuOpen, setModeMenuOpen, modeMenuRef);

  useEffect(() => {
    if (!modeMenuOpen) {
      return;
    }
    const onDocDown = (e: MouseEvent) => {
      if (
        modeMenuRef.current &&
        !modeMenuRef.current.contains(e.target as Node)
      ) {
        setModeMenuOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setModeMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", onDocDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [modeMenuOpen]);

  const openAttachPicker = () => {
    fileInputRef.current?.click();
    setAttachMenuOpen(false);
  };
  const closeAttachMenu = useCallback(() => {
    setAttachMenuOpen(false);
  }, []);

  const openSkillsDialog = () => {
    setAttachMenuOpen(false);
    setSkillsErr(null);
    setSkillsData(null);
    setSkillsSearchQuery("");
    setSkillsSelectedTool(null);
    setSkillPanelEntered(false);
    setSkillsLoading(true);
    skillsDialogRef.current?.showModal();
    void fetchAgentTools()
      .then((d) => {
        setSkillsData(d);
      })
      .catch((e: unknown) => {
        setSkillsErr(e instanceof Error ? e.message : "Request failed");
      })
      .finally(() => {
        setSkillsLoading(false);
      });
  };

  const closeSkillsDialog = useCallback(() => {
    skillsDialogRef.current?.close();
  }, []);

  useEffect(() => {
    const el = skillsDialogRef.current;
    if (!el) {
      return;
    }
    const onDialogClose = () => {
      setSkillsLoading(false);
      setSkillsErr(null);
      setSkillsData(null);
      setSkillsSearchQuery("");
      setSkillsSelectedTool(null);
      setSkillPanelEntered(false);
    };
    el.addEventListener("close", onDialogClose);
    return () => {
      el.removeEventListener("close", onDialogClose);
    };
  }, []);

  const filteredSkills = useMemo(() => {
    if (!skillsData?.tools?.length) {
      return [];
    }
    return filterToolsBySearchQuery(skillsData.tools, skillsSearchQuery);
  }, [skillsData, skillsSearchQuery]);

  useEffect(() => {
    if (!skillsSelectedTool) {
      return;
    }
    const stillVisible = filteredSkills.some(
      (x) => x.name === skillsSelectedTool.name,
    );
    if (!stillVisible) {
      setSkillsSelectedTool(null);
      setSkillPanelEntered(false);
    }
  }, [filteredSkills, skillsSelectedTool]);

  useLayoutEffect(() => {
    if (!skillsSelectedTool) {
      setSkillPanelEntered(false);
      return;
    }
    setSkillPanelEntered(false);
    const id = requestAnimationFrame(() => {
      setSkillPanelEntered(true);
    });
    return () => {
      cancelAnimationFrame(id);
    };
  }, [skillsSelectedTool]);

  /** Lock input only while a request or upload is in flight — not while waiting on approve/inbox gates. */
  const inputLocked = busy || uploadBusy;
  const sendDisabled =
    inputLocked ||
    Boolean(approvalBarrier) ||
    Boolean(inboxReviewBarrier) ||
    (!input.trim() && attachmentQueue.length === 0);

  const draftText = voiceSessionActive ? input + voiceInterim : input;
  const showPlanModePrompt =
    planModePromptMinChars > 0 &&
    agentMode === "instant" &&
    draftText.length > planModePromptMinChars;

  const onVoiceToggle = () => {
    clearVoiceError();
    if (voiceState === "finalizing") {
      return;
    }
    if (voiceSessionActive) {
      stopVoice({
        flushPartial: (t) => {
          setInput((p) => p + t);
        },
      });
      return;
    }
    startVoice((text) => {
      setInput((p) => p + text);
    });
  };

  const composerBody = (
    <>
      {voiceSessionActive && voiceBanner ? (
        <div
          role="status"
          aria-live="polite"
          aria-atomic="true"
          className={`flex gap-2.5 rounded-lg border px-2.5 py-2 ${voiceBannerShellClass(
            voiceBanner.variant,
          )}`}
        >
          <div className="flex w-7 shrink-0 justify-center" aria-hidden>
            {voiceIsLive ? (
              <span className="relative mt-0.5 flex size-3 shrink-0">
                <span className="absolute inline-flex size-full animate-ping rounded-full bg-[var(--color-destructive)] opacity-50" />
                <span className="relative inline-flex size-3 rounded-full bg-[var(--color-destructive)]" />
              </span>
            ) : (
              <Loader2
                className={`mt-0.5 size-4 shrink-0 animate-spin ${
                  voiceBanner.variant === "connecting"
                    ? "text-[var(--color-accent)]"
                    : "text-secondary"
                }`}
              />
            )}
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-[13px] font-semibold leading-snug tracking-tight text-foreground">
              {voiceBanner.title}
            </p>
            <p className="mt-1 text-[12px] leading-relaxed text-secondary">
              {voiceBanner.body}
            </p>
          </div>
        </div>
      ) : null}
      <textarea
        ref={textareaRef}
        value={voiceSessionActive ? input + voiceInterim : input}
        rows={1}
        onChange={(e) => setInput(e.target.value)}
        readOnly={voiceSessionActive}
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
        placeholder={
          voiceState === "finalizing"
            ? "Wrapping up the last words…"
            : voiceIsLive
              ? "Transcript appears here while you speak…"
              : voiceConnecting
                ? "Preparing voice input…"
                : "How can I help you?"
        }
        disabled={inputLocked}
        className="min-h-9 min-w-0 w-full resize-none overflow-y-auto rounded-md border-0 bg-transparent px-1 py-0.5 text-sm leading-snug text-foreground shadow-none placeholder:text-secondary outline-none ring-0 focus:outline-none focus:ring-0 disabled:opacity-60 read-only:opacity-100"
        style={{ maxHeight: textareaMaxHeightPx } satisfies CSSProperties}
      />
      {voiceFeatureEnabled && voiceError ? (
        <p className="px-1 text-[12px] text-[var(--color-destructive)]">
          {voiceError}
        </p>
      ) : null}
      {showPlanModePrompt ? (
        <div className="flex shrink-0 justify-end px-1">
          <button
            type="button"
            disabled={busy}
            className="rounded-md border border-border bg-surface px-2 py-0.5 text-[11px] font-medium text-secondary transition-colors hover:bg-hover hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
            aria-label="Switch to Plan mode"
            onClick={() => {
              setAgentMode("plan");
              setModeMenuOpen(false);
            }}
          >
            Try Plan mode
          </button>
        </div>
      ) : null}
      <div className={controlsRowClassName}>
        <div className="flex shrink-0 items-center gap-1">
          <div ref={attachMenuRef} className="relative shrink-0">
            <button
              type="button"
              disabled={inputLocked}
              className={squareIconBtnClass}
              aria-label="Add to message"
              aria-expanded={attachMenuOpen}
              aria-haspopup="menu"
              onClick={() => {
                setModeMenuOpen(false);
                setAttachMenuOpen((o) => !o);
              }}
            >
            {uploadBusy ? (
              <Loader2 className="size-4 shrink-0 animate-spin" aria-hidden />
            ) : (
              <Plus className="size-4 shrink-0" strokeWidth={2} aria-hidden />
            )}
          </button>
          {attachMenuOpen ? (
            <div
              className="absolute bottom-full left-0 z-50 mb-1 min-w-[13rem] rounded-lg border border-border bg-background py-1 font-sans shadow-lg"
              role="menu"
              aria-label="Composer actions"
            >
              <button
                type="button"
                role="menuitem"
                className={MENU_ITEM_CLASS}
                disabled={inputLocked}
                onClick={openAttachPicker}
              >
                <Paperclip
                  className="size-4 shrink-0 text-secondary"
                  strokeWidth={2}
                  aria-hidden
                />
                <span>Attach document</span>
              </button>
              <button
                type="button"
                role="menuitem"
                className={MENU_ITEM_CLASS}
                disabled={inputLocked}
                onClick={openSkillsDialog}
              >
                <Terminal
                  className="size-4 shrink-0 text-secondary"
                  strokeWidth={2}
                  aria-hidden
                />
                <span>Show skills</span>
              </button>
              {extraAttachMenuItems
                ? extraAttachMenuItems({
                    closeMenu: closeAttachMenu,
                    inputLocked,
                    busy,
                  })
                : null}
            </div>
          ) : null}
          </div>
          <div ref={modeMenuRef} className="relative shrink-0">
            <button
              type="button"
              disabled={busy}
              aria-label="Agent mode"
              aria-haspopup="menu"
              aria-expanded={modeMenuOpen}
              className={`${agentModeTriggerClass} ${modeMenuOpen ? "bg-hover text-foreground" : ""}`}
              onClick={() => {
                setAttachMenuOpen(false);
                setModeMenuOpen((o) => !o);
              }}
            >
              {agentMode === "instant" ? (
                <Sparkles className="size-3 shrink-0" strokeWidth={2} aria-hidden />
              ) : (
                <List className="size-3 shrink-0" strokeWidth={2} aria-hidden />
              )}
              <span className="min-w-0 flex-1 text-left">
                {agentMode === "instant" ? "Instant" : "Plan"}
              </span>
            </button>
            {modeMenuOpen ? (
              <div
                className="absolute bottom-full left-0 z-50 mb-1 min-w-[13rem] rounded-lg border border-border bg-background py-1 font-sans shadow-lg"
                role="menu"
                aria-label="Agent mode"
              >
                <button
                  type="button"
                  role="menuitemradio"
                  aria-checked={agentMode === "instant"}
                  className={`${MENU_ITEM_CLASS} ${agentMode === "instant" ? "bg-hover" : ""}`}
                  onClick={() => {
                    setAgentMode("instant");
                    setModeMenuOpen(false);
                  }}
                >
                  <Sparkles
                    className="size-4 shrink-0 text-secondary"
                    strokeWidth={2}
                    aria-hidden
                  />
                  <span>Instant</span>
                </button>
                <button
                  type="button"
                  role="menuitemradio"
                  aria-checked={agentMode === "plan"}
                  className={`${MENU_ITEM_CLASS} ${agentMode === "plan" ? "bg-hover" : ""}`}
                  onClick={() => {
                    setAgentMode("plan");
                    setModeMenuOpen(false);
                  }}
                >
                  <List
                    className="size-4 shrink-0 text-secondary"
                    strokeWidth={2}
                    aria-hidden
                  />
                  <span>Plan</span>
                </button>
              </div>
            ) : null}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {showVoiceButton ? (
            <button
              type="button"
              disabled={inputLocked || voiceState === "finalizing"}
              className={`${squareIconBtnClass} relative ${
                voiceIsLive
                  ? "ring-2 ring-[var(--color-destructive)]/50 bg-[var(--color-destructive)]/10 text-[var(--color-destructive)]"
                  : ""
              } ${voiceConnecting ? "text-[var(--color-accent)]" : ""}`}
              aria-label={
                voiceState === "finalizing"
                  ? "Finishing transcription"
                  : voiceSessionActive
                    ? "Stop voice input"
                    : "Start voice input"
              }
              aria-pressed={voiceSessionActive && voiceState !== "finalizing"}
              onClick={onVoiceToggle}
            >
              {voiceConnecting ? (
                <Loader2 className="size-4 shrink-0 animate-spin" aria-hidden />
              ) : (
                <Mic className="size-4 shrink-0" strokeWidth={2} aria-hidden />
              )}
              {voiceIsLive ? (
                <span
                  className="absolute -right-0.5 -top-0.5 size-2 rounded-full bg-[var(--color-destructive)] ring-2 ring-background"
                  aria-hidden
                />
              ) : null}
            </button>
          ) : null}
          {approvalBarrier ? (
            <button
              type="button"
              onClick={dismissApprovalBarrier}
              className={sendBtnClass}
            >
              Cancel approvals
            </button>
          ) : inboxReviewBarrier ? (
            <button
              type="button"
              onClick={dismissInboxReviewBarrier}
              className={sendBtnClass}
            >
              Skip inbox wait
            </button>
          ) : busy ? (
            <button type="button" onClick={stop} className={sendBtnClass}>
              Stop
            </button>
          ) : (
            <button
              type="button"
              onClick={send}
              disabled={sendDisabled}
              className={sendBtnClass}
            >
              {uploadBusy ? "Uploading…" : "Send"}
            </button>
          )}
        </div>
      </div>
    </>
  );

  return (
    <div className={`relative z-[50] ${className}`}>
      <input
        ref={fileInputRef}
        type="file"
        accept={AGENT_CHAT_ATTACHMENT_ACCEPT}
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
      {providerWaitComposerHint ? (
        <div
          role="status"
          aria-live="polite"
          className="mb-2 flex w-full items-start gap-2 rounded-md border border-[color:color-mix(in_srgb,var(--bit-orange,#F4A51C)_42%,transparent)] bg-[color:color-mix(in_srgb,var(--bit-orange,#F4A51C)_11%,transparent)] px-2.5 py-2"
        >
          <AlertTriangle
            className="mt-0.5 size-4 shrink-0 text-[var(--bit-orange,#F4A51C)]"
            strokeWidth={2}
            aria-hidden
          />
          <p className="min-w-0 flex-1 text-[13px] font-medium leading-snug text-foreground">
            {providerWaitComposerHint}
          </p>
        </div>
      ) : null}
      <div
        className={`${inputShellClassName}${
          voiceSessionActive
            ? " ring-2 ring-inset ring-[var(--color-accent)]/40"
            : " transition-shadow duration-150 focus-within:ring-2 focus-within:ring-inset focus-within:ring-[var(--color-accent)]/40"
        }`}
      >
        {composerBody}
      </div>
      <dialog
        ref={skillsDialogRef}
        className={SKILLS_DIALOG_SHELL_CLASS}
        onCancel={(e) => {
          e.preventDefault();
          if (skillsSelectedTool) {
            setSkillsSelectedTool(null);
            setSkillPanelEntered(false);
          } else {
            closeSkillsDialog();
          }
        }}
      >
        <div
          className={SKILLS_DIALOG_SCRIM_CLASS}
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) {
              closeSkillsDialog();
            }
          }}
        >
          <div
            className={SKILLS_DIALOG_PANEL_CLASS}
            onMouseDown={(e) => e.stopPropagation()}
          >
            <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border px-4 py-3">
              <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <span className="text-base font-medium text-foreground">
                  Agent skills
                </span>
                {!skillsLoading &&
                !skillsErr &&
                skillsData?.configured &&
                skillsData.tools.length > 0 ? (
                  <span className="tabular-nums text-sm font-normal text-secondary">
                    {skillsSearchQuery.trim()
                      ? `${filteredSkills.length} of ${skillsData.tools.length}`
                      : skillsData.tools.length}
                  </span>
                ) : null}
              </div>
              <button
                type="button"
                className="rounded-md px-2 py-1 text-xs text-secondary hover:bg-hover hover:text-foreground"
                onClick={closeSkillsDialog}
              >
                Close
              </button>
            </div>
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden text-sm">
              {skillsLoading ? (
                <div className="flex shrink-0 items-center gap-2 p-4 text-secondary">
                  <Loader2
                    className="size-4 shrink-0 animate-spin"
                    aria-hidden
                  />
                  <span>Loading…</span>
                </div>
              ) : null}
              {!skillsLoading && skillsErr ? (
                <p className="shrink-0 px-4 py-3 text-[13px] text-[var(--color-destructive)]">
                  {skillsErr}
                </p>
              ) : null}
              {!skillsLoading &&
              !skillsErr &&
              skillsData &&
              !skillsData.configured ? (
                <p className="shrink-0 px-4 py-3 text-secondary">
                  Agent is not configured on this server.
                </p>
              ) : null}
              {!skillsLoading &&
              !skillsErr &&
              skillsData &&
              skillsData.configured &&
              skillsData.tools.length === 0 ? (
                <p className="shrink-0 px-4 py-3 text-secondary">
                  No tools in the agent allowlist.
                </p>
              ) : null}
              {!skillsLoading &&
              !skillsErr &&
              skillsData &&
              skillsData.tools.length > 0 ? (
                <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
                  <div className="shrink-0 border-b border-border px-3 py-2">
                    <div className="relative">
                      <Search
                        className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-tertiary"
                        strokeWidth={2}
                        aria-hidden
                      />
                      <input
                        type="search"
                        value={skillsSearchQuery}
                        onChange={(e) => setSkillsSearchQuery(e.target.value)}
                        placeholder="Search skills…"
                        aria-label="Search skills"
                        className="w-full rounded-md border border-border bg-surface py-1.5 pl-8 pr-2 text-sm text-foreground placeholder:text-tertiary outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]/35"
                      />
                    </div>
                  </div>
                  <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
                    {filteredSkills.length === 0 ? (
                      <p className="p-4 text-[13px] text-secondary">
                        No skills match your search.
                      </p>
                    ) : (
                      <ul
                        className="min-h-0 flex-1 list-none space-y-0.5 overflow-y-auto overflow-x-hidden overscroll-contain p-2 [scrollbar-gutter:stable]"
                        role="listbox"
                      >
                        {filteredSkills.map((t) => {
                          const preview = skillListPreviewLine(t);
                          const selected = skillsSelectedTool?.name === t.name;
                          return (
                            <li key={t.name}>
                              <button
                                type="button"
                                role="option"
                                aria-selected={selected}
                                onClick={() => setSkillsSelectedTool(t)}
                                className={`flex w-full flex-col gap-1 rounded-md border px-2.5 py-2 text-left transition-colors ${
                                  selected
                                    ? "border-[var(--color-accent)]/40 bg-[var(--color-accent)]/8"
                                    : "border-transparent hover:bg-hover"
                                }`}
                              >
                                <div className="flex min-w-0 items-start justify-between gap-2">
                                  <span className="min-w-0 flex-1 text-sm font-medium leading-snug text-foreground">
                                    {humanizeToolName(t.name)}
                                  </span>
                                  {t.mutation ? (
                                    <span className="shrink-0 rounded bg-hover px-1.5 py-0.5 text-[10px] font-medium leading-tight text-secondary">
                                      {REQUIRES_APPROVAL_LABEL}
                                    </span>
                                  ) : null}
                                </div>
                                {preview ? (
                                  <span className="line-clamp-3 text-[11px] leading-snug text-secondary">
                                    {preview}
                                  </span>
                                ) : null}
                              </button>
                            </li>
                          );
                        })}
                      </ul>
                    )}
                    {skillsSelectedTool ? (
                      <>
                        <button
                          type="button"
                          aria-label="Close skill details"
                          className="absolute inset-0 z-[1] bg-foreground/10 transition-opacity"
                          onClick={() => {
                            setSkillsSelectedTool(null);
                            setSkillPanelEntered(false);
                          }}
                        />
                        <div
                          className={`absolute inset-y-0 right-0 z-[2] flex min-h-0 w-full max-w-[min(100%,22rem)] flex-col border-l border-border bg-background shadow-xl transition-transform duration-200 ease-out sm:max-w-[26rem] ${
                            skillPanelEntered
                              ? "translate-x-0"
                              : "translate-x-full"
                          }`}
                          onMouseDown={(e) => e.stopPropagation()}
                        >
                          <SkillDetailPanel
                            tool={skillsSelectedTool}
                            onBack={() => {
                              setSkillsSelectedTool(null);
                              setSkillPanelEntered(false);
                            }}
                          />
                        </div>
                      </>
                    ) : null}
                  </div>
                </div>
              ) : null}
            </div>
          </div>
        </div>
      </dialog>
      {!conversationEmpty ? (
        <p className={disclaimerClassName}>
          AI can make mistakes. Please review the output carefully.
        </p>
      ) : null}
    </div>
  );
}
