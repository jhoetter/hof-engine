"use client";

import { Loader2, Paperclip, Plus, Sparkles, X } from "lucide-react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { AssistantMarkdown } from "./AssistantMarkdown";
import { fetchAgentTools, type AgentToolsResponse } from "./fetchAgentTools";
import {
  isGuidanceRedundantInDescription,
  prepareSkillMarkdownField,
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
  "m-0 max-h-none w-auto max-w-none border-0 bg-transparent p-0 shadow-none backdrop:bg-black/40";

const SKILLS_DIALOG_PANEL_CLASS =
  "fixed left-1/2 top-1/2 z-[200] flex w-[min(100vw-1.5rem,56rem)] max-h-[min(100vh-1.5rem,52rem)] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-lg border border-border bg-background font-sans text-foreground shadow-lg";

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
    };
    el.addEventListener("close", onDialogClose);
    return () => {
      el.removeEventListener("close", onDialogClose);
    };
  }, []);

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
                <Sparkles
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
          closeSkillsDialog();
        }}
      >
        <div
          className={SKILLS_DIALOG_PANEL_CLASS}
          onMouseDown={(e) => e.stopPropagation()}
        >
          <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border px-4 py-3">
            <span className="text-base font-medium text-foreground">Agent skills</span>
            <button
              type="button"
              className="rounded-md px-2 py-1 text-xs text-secondary hover:bg-hover hover:text-foreground"
              onClick={closeSkillsDialog}
            >
              Close
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-4 text-sm">
          {skillsLoading ? (
            <div className="flex items-center gap-2 text-secondary">
              <Loader2 className="size-4 shrink-0 animate-spin" aria-hidden />
              <span>Loading…</span>
            </div>
          ) : null}
          {!skillsLoading && skillsErr ? (
            <p className="text-[13px] text-[var(--color-destructive)]">{skillsErr}</p>
          ) : null}
          {!skillsLoading && !skillsErr && skillsData && !skillsData.configured ? (
            <p className="text-secondary">
              Agent is not configured on this server.
            </p>
          ) : null}
          {!skillsLoading &&
          !skillsErr &&
          skillsData &&
          skillsData.configured &&
          skillsData.tools.length === 0 ? (
            <p className="text-secondary">No tools in the agent allowlist.</p>
          ) : null}
          {!skillsLoading && !skillsErr && skillsData && skillsData.tools.length > 0 ? (
            <ul className="flex flex-col gap-4">
              {skillsData.tools.map((t) => {
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
                return (
                <li
                  key={t.name}
                  className="rounded-lg border border-border bg-surface/60 px-4 py-3"
                >
                  <div className="flex flex-wrap items-center gap-2 gap-y-1">
                    <span className="text-[15px] font-semibold text-foreground">
                      {humanizeToolName(t.name)}
                    </span>
                    <span className="font-mono text-[11px] text-tertiary">{t.name}</span>
                    {t.mutation ? (
                      <span className="rounded bg-hover px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-secondary">
                        Mutation
                      </span>
                    ) : null}
                  </div>
                  <div className="mt-3 space-y-4 border-t border-border/70 pt-3">
                    <SkillSection label="Summary" source={t.tool_summary} />
                    <SkillSection label="Description" source={t.description} />
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
                </li>
                );
              })}
            </ul>
          ) : null}
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
