"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { HOF_REACT_I18N_OPTS } from "../reactI18nextStableOpts";

export type WebSessionCanvasProps = {
  sessionId: string;
  liveUrl: string;
  sseChannel: string;
  /** Prepended to API paths (e.g. empty for same-origin ``/api/...``). */
  apiPrefix?: string;
};

type WireMessage = {
  role?: string;
  summary?: string;
  data?: string;
  type?: string;
};

type SessionDetail = {
  phase?: string;
  status_label?: string;
  status_detail?: string | null;
  checkpoint_last?: string | null;
  checkpoint_count?: number;
  cloud_step_count?: number | null;
  output?: string | null;
};

const TERMINAL_PHASES = new Set([
  "succeeded",
  "failed",
  "cancelled",
  "timed_out",
]);

function phaseBadgeClass(phase: string): string {
  switch (phase) {
    case "running":
      return "bg-[var(--color-accent,#2383E2)]/12 text-[var(--color-accent,#2383E2)]";
    case "waiting_for_user":
      return "bg-[var(--bit-orange,#F4A51C)]/12 text-[var(--bit-orange,#F4A51C)]";
    case "succeeded":
      return "bg-[var(--hof-green,#2F7D59)]/12 text-[var(--hof-green,#2F7D59)]";
    case "failed":
    case "timed_out":
      return "bg-[var(--error,#D84B3E)]/10 text-[var(--error,#D84B3E)]";
    case "cancelled":
      return "bg-[var(--color-hover,#F7F7F5)] text-[var(--color-secondary,#787774)]";
    default:
      return "bg-[var(--color-hover,#F7F7F5)] text-[var(--color-secondary,#787774)]";
  }
}

function phaseDotClass(phase: string): string {
  switch (phase) {
    case "running":
      return "bg-[var(--color-accent,#2383E2)]";
    case "waiting_for_user":
      return "bg-[var(--bit-orange,#F4A51C)]";
    case "succeeded":
      return "bg-[var(--hof-green,#2F7D59)]";
    case "failed":
    case "timed_out":
      return "bg-[var(--error,#D84B3E)]";
    default:
      return "bg-[var(--color-tertiary,#C3C2C1)]";
  }
}

function lastStepSummary(messages: WireMessage[]): string | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    const text = (m.summary ?? m.data ?? "").trim();
    if (text) {
      return text.length > 140 ? text.slice(0, 137) + "…" : text;
    }
  }
  return null;
}

/**
 * Full-page canvas: live Browser Use Cloud iframe + compact status bar.
 * Polls session detail + messages; optionally listens to ``/api/sse/:channel``.
 */
export function WebSessionCanvas({
  sessionId,
  liveUrl,
  sseChannel,
  apiPrefix = "",
}: WebSessionCanvasProps) {
  const { t } = useTranslation("hofEngine", HOF_REACT_I18N_OPTS);
  const [messages, setMessages] = useState<WireMessage[]>([]);
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [stopBusy, setStopBusy] = useState(false);
  const [stopError, setStopError] = useState<string | null>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const base = apiPrefix.replace(/\/$/, "");
  const pollUrl = `${base}/api/web-sessions/${encodeURIComponent(sessionId)}/messages`;
  const sessionUrl = `${base}/api/web-sessions/${encodeURIComponent(sessionId)}`;

  const refreshDetail = useCallback(async () => {
    try {
      const r = await fetch(sessionUrl);
      if (!r.ok) {
        return;
      }
      const j = (await r.json()) as SessionDetail;
      setDetail(j);
    } catch {
      /* ignore */
    }
  }, [sessionUrl]);

  useEffect(() => {
    let cancelled = false;
    async function tick() {
      try {
        const r = await fetch(pollUrl);
        if (!r.ok || cancelled) {
          return;
        }
        const j = (await r.json()) as { messages?: unknown };
        const m = j.messages;
        if (Array.isArray(m)) {
          setMessages(m as WireMessage[]);
        }
      } catch {
        /* ignore */
      }
    }
    void tick();
    const id = setInterval(() => void tick(), 2500);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [pollUrl]);

  useEffect(() => {
    void refreshDetail();
    const id = setInterval(() => void refreshDetail(), 2500);
    return () => clearInterval(id);
  }, [refreshDetail]);

  useEffect(() => {
    if (!sseChannel || typeof window === "undefined") {
      return;
    }
    const url = `${base}/api/sse/${encodeURIComponent(sseChannel)}`;
    const es = new EventSource(url);
    es.onmessage = () => {
      void fetch(pollUrl)
        .then((r) => r.json())
        .then((j: { messages?: unknown }) => {
          const m = j.messages;
          if (Array.isArray(m)) {
            setMessages(m as WireMessage[]);
          }
        })
        .catch(() => {});
      void refreshDetail();
    };
    return () => es.close();
  }, [sseChannel, pollUrl, base, refreshDetail]);

  const phase = detail?.phase ?? "";
  const isTerminal = TERMINAL_PHASES.has(phase);
  const showStop = detail === null || !isTerminal;
  const stepCount =
    detail?.cloud_step_count ??
    detail?.checkpoint_count ??
    messages.length;
  const lastStep = lastStepSummary(messages);

  async function onStop() {
    setStopError(null);
    setStopBusy(true);
    try {
      const r = await fetch(
        `${base}/api/web-sessions/${encodeURIComponent(sessionId)}/stop`,
        { method: "POST" },
      );
      if (!r.ok) {
        const errText = await r.text();
        setStopError(
          errText ||
            t("webSession.stopFailed", { status: String(r.status) }),
        );
        return;
      }
      await refreshDetail();
    } catch (e) {
      setStopError(e instanceof Error ? e.message : String(e));
    } finally {
      setStopBusy(false);
    }
  }

  return (
    <div className="flex h-full min-h-[480px] w-full flex-col">
      {/* ── Status bar ── */}
      <div className="flex items-center gap-2.5 border-b border-[var(--color-border,#E9E9E7)] bg-[var(--color-surface,#FBFBFA)] px-3 py-2">
        {/* Phase badge */}
        {detail ? (
          <span
            className={`inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-[11px] font-medium ${phaseBadgeClass(phase)}`}
          >
            {phase === "running" ? (
              <span
                className={`inline-block h-1.5 w-1.5 rounded-full ${phaseDotClass(phase)} animate-pulse`}
              />
            ) : (
              <span
                className={`inline-block h-1.5 w-1.5 rounded-full ${phaseDotClass(phase)}`}
              />
            )}
            {detail.status_label ?? phase}
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 rounded bg-[var(--color-hover,#F7F7F5)] px-2 py-0.5 text-[11px] font-medium text-[var(--color-tertiary,#C3C2C1)]">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--color-tertiary,#C3C2C1)] animate-pulse" />
            {t("webSession.loading")}
          </span>
        )}

        {/* Step counter + last step */}
        {stepCount > 0 ? (
          <span className="flex min-w-0 items-center gap-1.5 text-[11px] text-[var(--color-secondary,#787774)]">
            <span className="shrink-0 tabular-nums">
              {stepCount === 1
                ? t("webSession.stepCount", { count: stepCount })
                : t("webSession.stepCountPlural", { count: stepCount })}
            </span>
            {lastStep ? (
              <>
                <span className="text-[var(--color-tertiary,#C3C2C1)]">·</span>
                <span className="min-w-0 truncate text-[var(--color-secondary,#787774)]">
                  {lastStep}
                </span>
              </>
            ) : null}
          </span>
        ) : null}

        {/* Spacer */}
        <div className="flex-1" />

        {/* Stop / error */}
        {showStop ? (
          <>
            <button
              type="button"
              className="rounded-md bg-[var(--color-hover,#F7F7F5)] px-2.5 py-1 text-[11px] font-medium text-[var(--color-foreground,#37352F)] transition-colors hover:bg-[var(--color-divider,#E9E9E7)]"
              disabled={stopBusy}
              onClick={() => void onStop()}
            >
              {stopBusy ? t("webSession.stopping") : t("webSession.stop")}
            </button>
            {stopError ? (
              <span className="max-w-[200px] truncate text-[11px] text-[var(--error,#D84B3E)]">
                {stopError}
              </span>
            ) : null}
          </>
        ) : null}

        {detail?.status_detail && isTerminal ? (
          <span className="text-[11px] text-[var(--color-secondary,#787774)]">
            {detail.status_detail}
          </span>
        ) : null}
      </div>

      {/* ── Main area: iframe ── */}
      <div className="relative min-h-0 flex-1 bg-[var(--color-background,#FFFFFF)]">
        {liveUrl ? (
          <iframe
            ref={iframeRef}
            title={t("webSession.iframeTitle")}
            src={liveUrl}
            className="absolute inset-0 h-full w-full border-0"
            allow="autoplay"
          />
        ) : (
          <div className="flex h-full items-center justify-center text-[13px] text-[var(--color-tertiary,#C3C2C1)]">
            {t("webSession.noLivePreview")}
          </div>
        )}

        {/* Terminal overlay */}
        {isTerminal && !liveUrl ? null : null}
      </div>
    </div>
  );
}
