"use client";

import { HofAgentComposer } from "./HofAgentComposer";
import { HofAgentMessages } from "./HofAgentMessages";
import {
  HofAgentChatProvider,
  type HofAgentChatProps,
} from "./hofAgentChatContext";

export type {
  HofAgentChatPresignInput,
  HofAgentChatPresignResult,
} from "./hofAgentChatContext";

export type { HofAgentChatProps };

/**
 * Default full-column layout: scrollable messages + bordered composer footer.
 * For custom placement (sidebar, split view), use {@link HofAgentChatProvider} with
 * {@link HofAgentMessages} and {@link HofAgentComposer}.
 */
export function HofAgentChat({
  className = "",
  ...props
}: HofAgentChatProps) {
  return (
    <HofAgentChatProvider {...props}>
      <div
        className={`hof-agent flex min-h-0 min-w-0 w-full flex-1 flex-col font-sans ${className}`.trim()}
      >
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          <HofAgentMessages />
        </div>
        <div className="shrink-0 border-t border-[var(--color-border)]/60 pt-3">
          <HofAgentComposer />
        </div>
      </div>
    </HofAgentChatProvider>
  );
}
