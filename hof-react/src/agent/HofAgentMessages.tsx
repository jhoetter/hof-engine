"use client";

import { FileText } from "lucide-react";
import {
  AgentEarlyThinkingIndicator,
  RunBlocksList,
} from "./HofAgentChatBlocks";
import {
  CHAT_USER_BUBBLE_CLASS,
  userMessageDisplayText,
} from "./hofAgentChatModel";
import { useHofAgentChat } from "./hofAgentChatContext";

export type HofAgentMessagesProps = {
  /** Outer scroll container (flex child, overflow). */
  className?: string;
  /** Inner content column (padding, max-width). */
  contentClassName?: string;
};

export function HofAgentMessages({
  className = "min-h-0 flex-1 overflow-y-auto overflow-x-hidden [scrollbar-gutter:stable]",
  contentClassName = "mx-auto flex min-h-full w-full flex-col px-5 py-6 sm:px-6 sm:py-8",
}: HofAgentMessagesProps) {
  const {
    welcomeName,
    thread,
    liveBlocks,
    busy,
    approvalBarrier,
    approvalDecisions,
    setApprovalDecisions,
    mutationOutcomeByPendingId,
    conversationEmpty,
  } = useHofAgentChat();

  const threadList = (
    <>
      {thread.map((item) => {
        if (item.kind === "user") {
          const hasAtt = Boolean(item.attachments?.length);
          const displayBody = userMessageDisplayText(
            item.content,
            hasAtt,
          );
          return (
            <div key={item.id} className="flex justify-end">
              <div className="max-w-[min(100%,min(28rem,90%))] space-y-2">
                {displayBody ? (
                  <div className={CHAT_USER_BUBBLE_CLASS}>
                    <span className="whitespace-pre-wrap break-words">
                      {displayBody}
                    </span>
                  </div>
                ) : null}
                {item.attachments && item.attachments.length > 0 ? (
                  <div className="flex flex-col items-end gap-1.5">
                    {item.attachments.map((a) => (
                      <div
                        key={a.object_key}
                        className="inline-flex max-w-full items-center gap-2 rounded-xl border border-border bg-surface px-3 py-2 text-left"
                        title={a.object_key}
                      >
                        <FileText
                          className="size-4 shrink-0 text-[var(--color-accent)] opacity-90"
                          aria-hidden
                        />
                        <span className="min-w-0 truncate text-[13px] font-medium text-foreground">
                          {a.filename}
                        </span>
                        <span className="shrink-0 text-[10px] uppercase tracking-wide text-tertiary">
                          PDF
                        </span>
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>
          );
        }
        return (
          <div key={item.id} className="pl-1">
            <RunBlocksList
              blocks={item.blocks}
              barrier={approvalBarrier}
              approvalDecisions={approvalDecisions}
              setApprovalDecisions={setApprovalDecisions}
              busy={busy}
              mutationOutcomeByPendingId={mutationOutcomeByPendingId}
            />
          </div>
        );
      })}
      {liveBlocks.length > 0 ? (
        <div className="pl-1">
          <RunBlocksList
            blocks={liveBlocks}
            barrier={approvalBarrier}
            approvalDecisions={approvalDecisions}
            setApprovalDecisions={setApprovalDecisions}
            busy={busy}
            mutationOutcomeByPendingId={mutationOutcomeByPendingId}
          />
        </div>
      ) : busy ? (
        <div className="pl-1">
          <AgentEarlyThinkingIndicator />
        </div>
      ) : null}
    </>
  );

  /** Use flex-1 + min-h-0 (not min-h-full) so empty state centers inside flex/scroll parents. */
  const rootClass = conversationEmpty
    ? `${className} flex min-h-0 min-w-0 flex-1 flex-col`.trim()
    : className;

  return (
    <div className={rootClass}>
      {conversationEmpty ? (
        <div
          className={`${contentClassName} flex min-h-0 flex-1 flex-col justify-center !py-0`.trim()}
        >
          <header className="flex flex-col items-center text-center font-sans">
            <p className="text-xl font-semibold tracking-tight text-foreground sm:text-2xl">
              Welcome, {welcomeName}
            </p>
            <p className="mt-2 max-w-sm text-[13px] leading-relaxed text-secondary">
              This is your assistant inbox. New replies show up here. Use the
              field below to write a message or attach a PDF.
            </p>
          </header>
        </div>
      ) : (
        <div className={contentClassName}>
          <div className="min-h-0 flex-1 space-y-5">{threadList}</div>
        </div>
      )}
    </div>
  );
}
