"use client";

import {
  Loader2,
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
import { useHofAgentChat } from "./hofAgentChatContext";

export type HofAgentComposerProps = {
  /** Wraps attachment chips, errors, and the composer shell. */
  className?: string;
  /** Bottom row: square + menu and Send (`justify-between`). */
  controlsRowClassName?: string;
  /** Bordered shell around the two-row composer (`flex flex-col`). */
  inputShellClassName?: string;
  disclaimerClassName?: string;
  /** Max height of the message field before it scrolls (px). */
  textareaMaxHeightPx?: number;
};

/** Square ghost icon control (plus / attach menu trigger). */
const squareIconBtnClass =
  "inline-flex size-9 shrink-0 items-center justify-center rounded-md border-0 bg-transparent text-secondary transition-colors hover:bg-hover hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40";
/** Matches {@link HofAgentConversationSelect} “New” button (outline + text-sm sizing). */
const sendBtnClass =
  "shrink-0 rounded-md border border-border bg-hover px-3 py-1.5 text-sm font-medium text-foreground transition-colors hover:bg-[var(--color-hover)] disabled:cursor-not-allowed disabled:opacity-40";

const MENU_ITEM_CLASS =
  "flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-foreground transition-colors hover:bg-hover";

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
}: HofAgentComposerProps) {
  const {
    input,
    setInput,
    send,
    stop,
    busy,
    uploadBusy,
    approvalBarrier,
    attachmentQueue,
    setAttachmentQueue,
    uploadErr,
    fileInputRef,
    onPickFiles,
    conversationEmpty,
  } = useHofAgentChat();

  const [attachMenuOpen, setAttachMenuOpen] = useState(false);
  const attachMenuRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
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
    el.style.height = "0px";
    const next = Math.min(el.scrollHeight, textareaMaxHeightPx);
    el.style.height = `${Math.max(next, 36)}px`;
  }, [textareaMaxHeightPx]);

  useLayoutEffect(() => {
    syncTextareaHeight();
  }, [input, syncTextareaHeight]);

  useEffect(() => {
    if (!attachMenuOpen) {
      return;
    }
    const onDocDown = (e: MouseEvent) => {
      if (
        attachMenuRef.current &&
        !attachMenuRef.current.contains(e.target as Node)
      ) {
        setAttachMenuOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setAttachMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", onDocDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [attachMenuOpen]);

  const openAttachPicker = () => {
    fileInputRef.current?.click();
    setAttachMenuOpen(false);
  };

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

  const disabled = busy || uploadBusy || Boolean(approvalBarrier);

  const composerBody = (
    <>
      <textarea
        ref={textareaRef}
        value={input}
        rows={1}
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
        placeholder="How can I help you?"
        disabled={disabled}
        className="min-h-9 min-w-0 w-full resize-none overflow-y-auto rounded-md border-0 bg-transparent px-1 py-0.5 text-sm leading-snug text-foreground shadow-none placeholder:text-secondary outline-none ring-0 transition-[height] focus:outline-none focus:ring-0 disabled:opacity-60"
        style={{ maxHeight: textareaMaxHeightPx } satisfies CSSProperties}
      />
      <div className={controlsRowClassName}>
        <div ref={attachMenuRef} className="relative shrink-0">
          <button
            type="button"
            disabled={disabled}
            className={squareIconBtnClass}
            aria-label="Add to message"
            aria-expanded={attachMenuOpen}
            aria-haspopup="menu"
            onClick={() => setAttachMenuOpen((o) => !o)}
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
                disabled={disabled}
                onClick={openAttachPicker}
              >
                <Paperclip
                  className="size-4 shrink-0 text-secondary"
                  strokeWidth={2}
                  aria-hidden
                />
                <span>Attach PDF</span>
              </button>
              <button
                type="button"
                role="menuitem"
                className={MENU_ITEM_CLASS}
                disabled={disabled}
                onClick={openSkillsDialog}
              >
                <Terminal
                  className="size-4 shrink-0 text-secondary"
                  strokeWidth={2}
                  aria-hidden
                />
                <span>Show skills</span>
              </button>
            </div>
          ) : null}
        </div>
        {busy && !approvalBarrier ? (
          <button type="button" onClick={stop} className={sendBtnClass}>
            Stop
          </button>
        ) : (
          <button
            type="button"
            onClick={send}
            disabled={
              disabled || (!input.trim() && attachmentQueue.length === 0)
            }
            className={sendBtnClass}
          >
            {uploadBusy ? "Uploading…" : "Send"}
          </button>
        )}
      </div>
    </>
  );

  return (
    <div className={className}>
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
      <div className={inputShellClassName}>{composerBody}</div>
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
                <Loader2 className="size-4 shrink-0 animate-spin" aria-hidden />
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
