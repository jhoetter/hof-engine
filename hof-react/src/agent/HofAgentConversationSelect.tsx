"use client";

import { Loader2, Trash2 } from "lucide-react";

export type HofAgentConversationOption = {
  id: string;
  title: string | null;
};

export type HofAgentConversationSelectProps = {
  conversations: HofAgentConversationOption[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  /** When set, shows a delete control for the active conversation (host calls persistence). */
  onDelete?: () => void;
  deleteBusy?: boolean;
  /** Wider label + `text-sm` (full page) vs compact floating panel. */
  variant?: "default" | "compact";
  className?: string;
};

/**
 * Presentational conversation picker + “New”. Persistence and data loading stay in the host app.
 */
export function HofAgentConversationSelect({
  conversations,
  activeId,
  onSelect,
  onNew,
  onDelete,
  deleteBusy = false,
  variant = "default",
  className = "",
}: HofAgentConversationSelectProps) {
  const isCompact = variant === "compact";
  const row = "flex flex-wrap items-center gap-2 border-b border-border px-1 py-2";
  const selectClass = isCompact
    ? "min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground"
    : "min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground";
  const newBtnClass = isCompact
    ? "shrink-0 rounded-md px-2 py-1 text-xs text-secondary hover:bg-hover hover:text-foreground"
    : "shrink-0 rounded-md border border-border bg-hover px-3 py-1.5 text-sm font-medium text-foreground transition-colors hover:bg-[var(--color-hover)]";
  const deleteDisabled = !activeId || deleteBusy;
  const deleteBtnClass = isCompact
    ? "inline-flex shrink-0 items-center justify-center rounded-md border border-border bg-background px-2 py-1.5 text-[var(--color-destructive)] transition-colors hover:bg-hover disabled:cursor-not-allowed disabled:opacity-40"
    : "inline-flex shrink-0 items-center justify-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-sm font-medium text-[var(--color-destructive)] transition-colors hover:bg-hover disabled:cursor-not-allowed disabled:opacity-40";

  return (
    <div className={`${row} ${className}`.trim()}>
      {!isCompact ? (
        <label className="flex min-w-0 flex-1 items-center gap-2 text-sm text-secondary">
          <span className="shrink-0">Conversation</span>
          <select
            className={selectClass}
            value={activeId ?? ""}
            onChange={(e) => onSelect(e.target.value)}
            aria-label="Select conversation"
          >
            <option value="">New…</option>
            {conversations.map((c) => (
              <option key={c.id} value={c.id}>
                {(c.title?.trim() || "Untitled").slice(0, 120)}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <select
          className={selectClass}
          value={activeId ?? ""}
          onChange={(e) => onSelect(e.target.value)}
          aria-label="Select conversation"
        >
          <option value="">New…</option>
          {conversations.map((c) => (
            <option key={c.id} value={c.id}>
              {(c.title?.trim() || "Untitled").slice(0, 80)}
            </option>
          ))}
        </select>
      )}
      <button type="button" className={newBtnClass} onClick={onNew}>
        New
      </button>
      {onDelete ? (
        <button
          type="button"
          className={deleteBtnClass}
          disabled={deleteDisabled}
          onClick={onDelete}
          aria-label="Delete conversation"
          title="Delete conversation"
        >
          {deleteBusy ? (
            <Loader2
              className={`size-4 shrink-0 animate-spin ${isCompact ? "" : "opacity-90"}`}
              aria-hidden
            />
          ) : isCompact ? (
            <Trash2 className="size-4 shrink-0" aria-hidden />
          ) : (
            <>
              <Trash2 className="size-4 shrink-0" aria-hidden />
              Delete
            </>
          )}
        </button>
      ) : null}
    </div>
  );
}
