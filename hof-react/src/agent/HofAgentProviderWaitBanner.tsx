"use client";

import { useEffect, useState } from "react";
import { useHofAgentChat } from "./hofAgentChatContext";

function waitBannerLine(remainingSec: number, reason: string): string {
  const rate = reason === "rate_limit";
  const head = rate ? "Usage limit" : "Service busy";
  if (remainingSec > 0) {
    return `${head} — I'll retry automatically in ${remainingSec}s…`;
  }
  return `${head} — retrying now…`;
}

/**
 * Shown when the stream emits ``provider_wait`` (e.g. rate limit backoff before retry).
 * Counts down seconds using a client-side deadline so the UI updates while the server sleeps.
 */
export function HofAgentProviderWaitBanner() {
  const { providerWaitNotice } = useHofAgentChat();
  const [, setTick] = useState(0);

  useEffect(() => {
    if (!providerWaitNotice) {
      return;
    }
    const id = window.setInterval(() => {
      setTick((t) => t + 1);
    }, 250);
    return () => window.clearInterval(id);
  }, [providerWaitNotice]);

  if (!providerWaitNotice) {
    return null;
  }

  const rawRemaining = Math.ceil(
    (providerWaitNotice.deadlineMs - Date.now()) / 1000,
  );
  const remainingSec = Math.max(0, rawRemaining);
  const line = waitBannerLine(remainingSec, providerWaitNotice.reason);

  return (
    <div
      role="status"
      aria-live="polite"
      className="shrink-0 border-b border-[var(--color-border)]/70 bg-[var(--color-muted)]/25 px-3 py-2 text-center text-[13px] text-[var(--color-muted-foreground)]"
    >
      {line}
    </div>
  );
}
