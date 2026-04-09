"use client";

import { Loader2, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { HOF_REACT_I18N_OPTS } from "../reactI18nextStableOpts";

export type HofAgentConversationOption = {
  id: string;
  title: string | null;
  updated_at?: string | null;
  /** Pinned conversations sort first within a time bucket. */
  pinned?: boolean;
};

/** Shared by {@link HofAgentConversationSelect} and {@link HofAgentConversationPanel} — host owns data + persistence. */
export type HofAgentConversationPickerCoreProps = {
  conversations: HofAgentConversationOption[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  /** When set, shows a delete control for the active conversation (host calls persistence). */
  onDelete?: () => void;
  deleteBusy?: boolean;
};

export type HofAgentConversationSelectProps = HofAgentConversationPickerCoreProps & {
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
  const { t } = useTranslation("hofEngine", HOF_REACT_I18N_OPTS);
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
          <span className="shrink-0">{t("conversationSelect.label")}</span>
          <select
            className={selectClass}
            value={activeId ?? ""}
            onChange={(e) => onSelect(e.target.value)}
            aria-label={t("conversationSelect.selectAria")}
          >
            <option value="">{t("conversationSelect.newOption")}</option>
            {conversations.map((c) => (
              <option key={c.id} value={c.id}>
                {(c.title?.trim() || t("conversation.untitled")).slice(0, 56)}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <select
          className={selectClass}
          value={activeId ?? ""}
          onChange={(e) => onSelect(e.target.value)}
          aria-label={t("conversationSelect.selectAria")}
        >
          <option value="">{t("conversationSelect.newOption")}</option>
          {conversations.map((c) => (
            <option key={c.id} value={c.id}>
              {(c.title?.trim() || t("conversation.untitled")).slice(0, 56)}
            </option>
          ))}
        </select>
      )}
      <button type="button" className={newBtnClass} onClick={onNew}>
        {t("conversationSelect.newButton")}
      </button>
      {onDelete ? (
        <button
          type="button"
          className={deleteBtnClass}
          disabled={deleteDisabled}
          onClick={onDelete}
          aria-label={t("conversationSelect.deleteAria")}
          title={t("conversationSelect.deleteTitle")}
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
              {t("conversationSelect.delete")}
            </>
          )}
        </button>
      ) : null}
    </div>
  );
}
