"use client";

import { CheckCircle2, XCircle } from "lucide-react";
import { useEffect } from "react";
import {
  formatPendingPreviewLine,
  humanizeToolName,
  postApplyReviewFromPreview,
} from "./hofAgentChatModel";
import { useHofAgentChat } from "./hofAgentChatContext";

const BTN_BASE =
  "inline-flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-[12px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40";

/**
 * Sticky pending-mutations strip: primary Approve / Reject + explicit Apply (no auto-submit).
 */
export function HofAgentPendingApprovalBar({
  className = "",
}: {
  className?: string;
}) {
  const {
    approvalBarrier,
    approvalDecisions,
    setApprovalDecisions,
    confirmPendingMutations,
    busy,
  } = useHofAgentChat();

  useEffect(() => {
    if (!approvalBarrier?.items.length) {
      return;
    }
    const id = window.requestAnimationFrame(() => {
      document
        .getElementById("hof-agent-pending-approval-bar")
        ?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
    return () => window.cancelAnimationFrame(id);
  }, [approvalBarrier]);

  if (!approvalBarrier?.items.length) {
    return null;
  }

  const allChosen = approvalBarrier.items.every(
    (it) =>
      approvalDecisions[it.pendingId] === true ||
      approvalDecisions[it.pendingId] === false,
  );

  return (
    <div
      id="hof-agent-pending-approval-bar"
      className={`scroll-mt-2 border-t border-border bg-surface/95 px-3 py-3 shadow-[0_-4px_12px_-4px_rgba(0,0,0,0.08)] backdrop-blur-sm ${className}`.trim()}
      role="region"
      aria-label="Pending actions requiring your approval"
    >
      <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-secondary">
        Pending actions
      </div>
      <ul className="space-y-2.5">
        {approvalBarrier.items.map((it) => {
          const title = humanizeToolName(it.name);
          const line = formatPendingPreviewLine(it.preview);
          const review = postApplyReviewFromPreview(it.preview);
          const d = approvalDecisions[it.pendingId];
          return (
            <li
              key={it.pendingId}
              className="flex flex-col gap-2 rounded-lg border border-border/80 bg-background/80 px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="min-w-0 flex-1">
                <div className="text-[13px] font-medium text-foreground">
                  {title}
                </div>
                {line ? (
                  <div className="mt-0.5 text-[11px] leading-snug text-secondary">
                    {line}
                  </div>
                ) : null}
                {review ? (
                  <div className="mt-1.5 flex flex-wrap items-center gap-2">
                    <span className="inline-flex rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-secondary ring-1 ring-border/80">
                      {review.label}
                    </span>
                    <a
                      href={review.href}
                      className="text-[11px] font-medium text-[var(--color-accent)] underline-offset-2 hover:underline"
                    >
                      Open
                    </a>
                  </div>
                ) : null}
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <button
                  type="button"
                  disabled={busy}
                  title="Approve"
                  aria-label={`Approve ${title}`}
                  className={`${BTN_BASE} ${
                    d === true
                      ? "bg-[var(--color-success-bg)] text-foreground"
                      : "bg-hover text-secondary hover:bg-hover/80"
                  }`}
                  onClick={() =>
                    setApprovalDecisions((prev) => ({
                      ...prev,
                      [it.pendingId]: true,
                    }))
                  }
                >
                  <CheckCircle2 className="size-4" strokeWidth={2} aria-hidden />
                  Approve
                </button>
                <button
                  type="button"
                  disabled={busy}
                  title="Reject"
                  aria-label={`Reject ${title}`}
                  className={`${BTN_BASE} ${
                    d === false
                      ? "bg-[var(--color-destructive-bg)] text-foreground"
                      : "bg-hover text-secondary hover:bg-hover/80"
                  }`}
                  onClick={() =>
                    setApprovalDecisions((prev) => ({
                      ...prev,
                      [it.pendingId]: false,
                    }))
                  }
                >
                  <XCircle className="size-4" strokeWidth={2} aria-hidden />
                  Reject
                </button>
              </div>
            </li>
          );
        })}
      </ul>
      <div className="mt-3 flex justify-end">
        <button
          type="button"
          disabled={busy || !allChosen}
          className={`${BTN_BASE} bg-foreground text-background hover:opacity-90`}
          onClick={() => {
            void confirmPendingMutations();
          }}
        >
          Apply choices
        </button>
      </div>
    </div>
  );
}
