"use client";

import { Loader2, Paperclip, X } from "lucide-react";
import { useHofAgentChat } from "./hofAgentChatContext";

export type HofAgentComposerProps = {
  /** Wraps attachment chips, errors, and the input row shell. */
  className?: string;
  /** Row: attach + text field + send. */
  rowClassName?: string;
  /** Inner padded shell around the input row (default bordered `bg-background` strip). */
  inputShellClassName?: string;
  disclaimerClassName?: string;
};

export function HofAgentComposer({
  className = "w-full",
  rowClassName = "flex items-stretch gap-1.5 sm:gap-2",
  /** One surface + outer border; inner controls stay flush (no nested white-on-gray band). */
  inputShellClassName = "rounded-xl border border-border bg-background p-1 sm:p-1.5",
  disclaimerClassName =
    "mt-2.5 mb-3 text-center text-[11px] leading-snug text-tertiary",
}: HofAgentComposerProps) {
  const {
    input,
    setInput,
    send,
    busy,
    uploadBusy,
    approvalBarrier,
    attachmentQueue,
    setAttachmentQueue,
    uploadErr,
    fileInputRef,
    onPickFiles,
  } = useHofAgentChat();

  const composerRow = (
    <div className={rowClassName}>
      <button
        type="button"
        disabled={busy || uploadBusy || Boolean(approvalBarrier)}
        className="flex h-11 w-11 shrink-0 items-center justify-center self-center rounded-lg bg-hover text-secondary transition-colors hover:bg-[color:color-mix(in_srgb,var(--color-foreground)_6%,var(--color-hover))] hover:text-foreground disabled:opacity-50"
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
        className="min-h-11 min-w-0 flex-1 self-stretch rounded-md border-0 bg-transparent px-2 py-2 text-sm leading-snug text-foreground shadow-none placeholder:text-secondary outline-none ring-0 transition-[box-shadow] focus:ring-2 focus:ring-[color:color-mix(in_srgb,var(--color-accent)_35%,transparent)] focus:ring-offset-0 disabled:opacity-60"
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
        className="flex h-11 shrink-0 items-center justify-center self-center rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground transition-opacity disabled:cursor-not-allowed disabled:opacity-40"
      >
        {uploadBusy ? "Uploading…" : "Send"}
      </button>
    </div>
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
      <div className={inputShellClassName}>{composerRow}</div>
      <p className={disclaimerClassName}>
        The assistant can make mistakes. Data changes only run after you approve
        them.
      </p>
    </div>
  );
}
