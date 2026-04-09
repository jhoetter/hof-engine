"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { HOF_REACT_I18N_OPTS } from "../reactI18nextStableOpts";
import { useHofAgentChat } from "./hofAgentChatContext";

/**
 * Shown when the stream emits ``provider_wait`` (e.g. rate limit backoff before retry).
 * Counts down seconds using a client-side deadline so the UI updates while the server sleeps.
 */
export function HofAgentProviderWaitBanner() {
  const { t } = useTranslation("hofEngine", HOF_REACT_I18N_OPTS);
  const { providerWaitNotice } = useHofAgentChat();
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!providerWaitNotice) {
      return;
    }
    const id = window.setInterval(() => {
      setTick((k) => k + 1);
    }, 250);
    return () => window.clearInterval(id);
  }, [providerWaitNotice]);

  const line = useMemo(() => {
    if (!providerWaitNotice) {
      return "";
    }
    const rawRemaining = Math.ceil(
      (providerWaitNotice.deadlineMs - Date.now()) / 1000,
    );
    const remainingSec = Math.max(0, rawRemaining);
    const rate = providerWaitNotice.reason === "rate_limit";
    const head = rate
      ? t("providerWait.usageLimit")
      : t("providerWait.serviceBusy");
    if (remainingSec > 0) {
      return t("providerWait.retryIn", { head, seconds: remainingSec });
    }
    return t("providerWait.retryNow", { head });
  }, [providerWaitNotice, t, tick]);

  if (!providerWaitNotice) {
    return null;
  }

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
