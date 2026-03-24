"use client";

import { Loader2, Paperclip, Plus, X } from "lucide-react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";
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
              aria-label="Attach"
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
      {!conversationEmpty ? (
        <p className={disclaimerClassName}>
          AI can make mistakes. Please review the output carefully.
        </p>
      ) : null}
    </div>
  );
}
