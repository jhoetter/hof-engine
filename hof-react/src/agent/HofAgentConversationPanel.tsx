"use client";

import {
  Fragment,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type RefObject,
  type UIEvent,
} from "react";
import { Loader2, MoreHorizontal, Pin } from "lucide-react";

import type { HofAgentConversationOption } from "./HofAgentConversationSelect";

const ROW_MENU_ITEM_CLASS =
  "flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-foreground transition-colors hover:bg-hover";

export type HofAgentConversationSection = {
  heading: string;
  items: HofAgentConversationOption[];
};

export type HofAgentConversationPanelProps = {
  /** Grouped list (time buckets). */
  sections: HofAgentConversationSection[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  className?: string;
  newConversationLabel?: string;
  onTogglePin?: (id: string, nextPinned: boolean) => void;
  onRenameConversation?: (id: string) => void;
  onDeleteConversation?: (id: string) => void;
  deletingConversationId?: string | null;
  pinBusyId?: string | null;
  /** Fires on the scrollable `<ul>` — host loads the next page when the user nears the bottom. */
  onListScroll?: (e: UIEvent<HTMLUListElement>) => void;
  listLoading?: boolean;
  listLoadingMore?: boolean;
};

/**
 * Vertical conversation list with full-width “new” at top, time sections, kebab menu per row.
 */
export function HofAgentConversationPanel({
  sections,
  activeId,
  onSelect,
  onNew,
  className = "",
  newConversationLabel = "New conversation",
  onTogglePin,
  onRenameConversation,
  onDeleteConversation,
  deletingConversationId = null,
  pinBusyId = null,
  onListScroll,
  listLoading = false,
  listLoadingMore = false,
}: HofAgentConversationPanelProps) {
  const [openMenuForId, setOpenMenuForId] = useState<string | null>(null);
  const menuContainerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!openMenuForId) {
      return;
    }
    const onDocDown = (e: MouseEvent) => {
      if (
        menuContainerRef.current &&
        !menuContainerRef.current.contains(e.target as Node)
      ) {
        setOpenMenuForId(null);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpenMenuForId(null);
      }
    };
    document.addEventListener("mousedown", onDocDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [openMenuForId]);

  const closeMenu = useCallback(() => {
    setOpenMenuForId(null);
  }, []);

  return (
    <div
      className={`flex h-full min-h-0 flex-col bg-background ${className}`.trim()}
    >
      <div className="shrink-0 px-2.5 pt-2.5 pb-1">
        <button
          type="button"
          className="w-full rounded-md border-0 bg-transparent px-2 py-2 text-left text-sm font-medium text-secondary transition-colors hover:bg-hover hover:text-foreground"
          onClick={onNew}
        >
          {newConversationLabel}
        </button>
      </div>
      <ul
        className="min-h-0 flex-1 list-none space-y-0.5 overflow-y-auto overscroll-contain p-2"
        aria-label="Conversations"
        onScroll={onListScroll}
      >
        {listLoading && sections.every((s) => s.items.length === 0) ? (
          <li className="px-2 py-4 text-center text-sm text-secondary">
            Loading…
          </li>
        ) : null}
        {!listLoading &&
        sections.every((s) => s.items.length === 0) ? (
          <li className="px-2.5 py-3 text-sm text-secondary">
            No conversations yet.
          </li>
        ) : null}
        {sections.map((section) => (
          <Fragment key={section.heading}>
            {section.items.length > 0 ? (
              <li
                className="px-2.5 pt-3 pb-1 text-[11px] font-medium uppercase tracking-wide text-secondary"
                aria-hidden
              >
                {section.heading}
              </li>
            ) : null}
            {section.items.map((c) => (
              <ConversationRow
                key={c.id}
                option={c}
                activeId={activeId}
                onSelect={onSelect}
                menuOpen={openMenuForId === c.id}
                onMenuOpenChange={(open) =>
                  setOpenMenuForId(open ? c.id : null)
                }
                menuContainerRef={
                  openMenuForId === c.id ? menuContainerRef : undefined
                }
                onTogglePin={onTogglePin}
                onRenameConversation={onRenameConversation}
                onDeleteConversation={onDeleteConversation}
                rowDeleting={deletingConversationId === c.id}
                pinBusy={pinBusyId === c.id}
                closeMenu={closeMenu}
              />
            ))}
          </Fragment>
        ))}
        {listLoadingMore ? (
          <li className="flex justify-center py-2 text-secondary">
            <Loader2 className="size-4 animate-spin" aria-hidden />
          </li>
        ) : null}
      </ul>
    </div>
  );
}

function ConversationRow({
  option: c,
  activeId,
  onSelect,
  menuOpen,
  onMenuOpenChange,
  menuContainerRef,
  onTogglePin,
  onRenameConversation,
  onDeleteConversation,
  rowDeleting,
  pinBusy,
  closeMenu,
}: {
  option: HofAgentConversationOption;
  activeId: string | null;
  onSelect: (id: string) => void;
  menuOpen: boolean;
  onMenuOpenChange: (open: boolean) => void;
  menuContainerRef?: RefObject<HTMLDivElement | null>;
  onTogglePin?: (id: string, nextPinned: boolean) => void;
  onRenameConversation?: (id: string) => void;
  onDeleteConversation?: (id: string) => void;
  rowDeleting: boolean;
  pinBusy: boolean;
  closeMenu: () => void;
}) {
  const baseId = useId();
  const menuId = `${baseId}-menu`;
  const isActive = c.id === activeId;
  const label = (c.title?.trim() || "Untitled").slice(0, 200);
  const pinned = Boolean(c.pinned);
  const showMenu =
    onTogglePin != null ||
    onRenameConversation != null ||
    onDeleteConversation != null;

  return (
    <li>
      <div
        className={`flex min-w-0 items-center gap-0.5 rounded-md ${
          isActive ? "bg-hover" : ""
        }`}
      >
        <button
          type="button"
          onClick={() => onSelect(c.id)}
          className={`flex min-w-0 flex-1 items-center gap-1.5 px-2.5 py-2 text-left text-sm transition-colors ${
            isActive
              ? "font-medium text-foreground"
              : "text-foreground"
          } rounded-md`}
        >
          {pinned ? (
            <Pin
              className="size-3.5 shrink-0 text-secondary"
              strokeWidth={2}
              aria-hidden
            />
          ) : null}
          <span className="min-w-0 truncate">{label}</span>
        </button>
        {showMenu ? (
          <div
            ref={menuContainerRef}
            className="relative shrink-0"
          >
            <button
              type="button"
              className="flex items-center justify-center rounded-md border-0 bg-transparent p-1.5 text-secondary transition-colors hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
              aria-label={`More actions for ${label.slice(0, 60)}`}
              aria-expanded={menuOpen}
              aria-haspopup="menu"
              aria-controls={menuOpen ? menuId : undefined}
              disabled={rowDeleting}
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                onMenuOpenChange(!menuOpen);
              }}
            >
              {rowDeleting ? (
                <Loader2 className="size-4 shrink-0 animate-spin" aria-hidden />
              ) : (
                <MoreHorizontal className="size-4 shrink-0" aria-hidden />
              )}
            </button>
            {menuOpen ? (
              <div
                id={menuId}
                className="absolute right-0 top-full z-50 mt-0.5 min-w-[10.5rem] rounded-lg border border-border bg-background py-1 font-sans shadow-lg"
                role="menu"
                aria-label="Conversation actions"
              >
                {onTogglePin ? (
                  <button
                    type="button"
                    role="menuitem"
                    className={ROW_MENU_ITEM_CLASS}
                    disabled={pinBusy}
                    onClick={() => {
                      onTogglePin(c.id, !pinned);
                      closeMenu();
                    }}
                  >
                    {pinned ? "Unpin" : "Pin"}
                  </button>
                ) : null}
                {onRenameConversation ? (
                  <button
                    type="button"
                    role="menuitem"
                    className={ROW_MENU_ITEM_CLASS}
                    onClick={() => {
                      onRenameConversation(c.id);
                      closeMenu();
                    }}
                  >
                    Rename
                  </button>
                ) : null}
                {onDeleteConversation ? (
                  <button
                    type="button"
                    role="menuitem"
                    className={`${ROW_MENU_ITEM_CLASS} text-[var(--color-destructive)]`}
                    disabled={rowDeleting}
                    onClick={() => {
                      onDeleteConversation(c.id);
                      closeMenu();
                    }}
                  >
                    Delete
                  </button>
                ) : null}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </li>
  );
}
