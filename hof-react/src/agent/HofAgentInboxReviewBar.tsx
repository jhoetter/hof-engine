"use client";

import { Loader2 } from "lucide-react";
import { inboxReviewOpenHref } from "./hofAgentChatModel";
import { useHofAgentChat } from "./hofAgentChatContext";

const BAR_CLASS =
  "scroll-mt-2 border-t border-border bg-surface/95 px-3 py-3 shadow-[0_-4px_12px_-4px_rgba(0,0,0,0.08)] backdrop-blur-sm";

/**
 * Shown when the engine pauses on ``awaiting_inbox_review``: Inbox links + poll/resume (not mutation Approve/Reject).
 *
 * @deprecated Default {@link HofAgentChat} uses streamed assistant copy plus inline “Waiting for Inbox”
 *   in the thread instead of a composer-adjacent bar. Kept for custom layouts that still want this
 *   pattern; may be removed in a future major.
 */
export function HofAgentInboxReviewBar({ className = "" }: { className?: string }) {
  const { inboxReviewBarrier, inboxPollWaiting, inboxResumeError } =
    useHofAgentChat();

  if (!inboxReviewBarrier?.watches.length) {
    return null;
  }

  return (
    <div
      className={`${BAR_CLASS} ${className}`.trim()}
      role="region"
      aria-label="Inbox review required before the assistant continues"
    >
      <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-secondary">
        Inbox review
      </div>
      <p className="text-[12px] leading-snug text-secondary">
        Open Inbox and complete the review. The assistant continues automatically when
        status updates.
      </p>
      <ul className="mt-2 space-y-2">
        {inboxReviewBarrier.watches.map((w) => {
          const href = inboxReviewOpenHref(w);
          const label =
            w.label?.trim() ||
            `${w.record_type} · ${w.record_id.slice(0, 8)}…`;
          return (
            <li
              key={w.watch_id}
              className="flex flex-wrap items-center gap-2 text-[12px]"
            >
              {href ? (
                <a
                  href={href}
                  className="font-medium text-[var(--color-accent)] underline-offset-2 hover:underline"
                  target="_blank"
                  rel="noreferrer"
                >
                  {label}
                </a>
              ) : (
                <span className="font-medium text-foreground">{label}</span>
              )}
            </li>
          );
        })}
      </ul>
      {inboxPollWaiting ? (
        <div className="mt-2 flex items-center gap-2 text-[11px] text-secondary">
          <Loader2 className="size-3.5 shrink-0 animate-spin" aria-hidden />
          Checking Inbox status…
        </div>
      ) : null}
      {inboxResumeError ? (
        <p className="mt-2 text-[11px] leading-snug text-[var(--color-destructive)]">
          {inboxResumeError}
        </p>
      ) : null}
    </div>
  );
}
