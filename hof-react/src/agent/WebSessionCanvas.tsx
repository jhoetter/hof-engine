"use client";

import { useCallback, useEffect, useState } from "react";

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
};

const TERMINAL_PHASES = new Set([
  "succeeded",
  "failed",
  "cancelled",
  "timed_out",
]);

/**
 * Full-page canvas: live Browser Use Cloud iframe + step timeline.
 * Polls session detail + messages; optionally listens to ``/api/sse/:channel``.
 */
export function WebSessionCanvas({
  sessionId,
  liveUrl,
  sseChannel,
  apiPrefix = "",
}: WebSessionCanvasProps) {
  const [messages, setMessages] = useState<WireMessage[]>([]);
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [stopBusy, setStopBusy] = useState(false);
  const [stopError, setStopError] = useState<string | null>(null);
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
  const showStop = detail === null || !TERMINAL_PHASES.has(phase);

  async function onStop() {
    setStopError(null);
    setStopBusy(true);
    try {
      const r = await fetch(
        `${base}/api/web-sessions/${encodeURIComponent(sessionId)}/stop`,
        { method: "POST" },
      );
      if (!r.ok) {
        const t = await r.text();
        setStopError(t || `Stop failed (${r.status})`);
        return;
      }
      await refreshDetail();
    } catch (e) {
      setStopError(e instanceof Error ? e.message : String(e));
    } finally {
      setStopBusy(false);
    }
  }

  const badgeClass =
    phase === "waiting_for_user"
      ? "bg-[var(--bit-orange)]/20 text-foreground"
      : phase === "failed" || phase === "timed_out"
        ? "bg-destructive/10 text-destructive"
        : "bg-muted text-secondary";

  return (
    <div className="flex h-full min-h-[480px] w-full flex-col gap-3">
      {detail ? (
        <div className="flex flex-col gap-2 rounded-lg border border-border bg-card px-3 py-2 text-[13px] md:flex-row md:items-start md:justify-between">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={`inline-flex rounded px-2 py-0.5 text-[11px] font-medium ${badgeClass}`}
              >
                {detail.status_label ?? phase}
              </span>
              {typeof detail.checkpoint_count === "number" &&
              detail.checkpoint_count > 0 ? (
                <span className="text-tertiary text-[11px]">
                  {detail.checkpoint_count} step
                  {detail.checkpoint_count === 1 ? "" : "s"}
                  {detail.checkpoint_last ? (
                    <span className="text-secondary">
                      {" "}
                      · {detail.checkpoint_last}
                    </span>
                  ) : null}
                </span>
              ) : null}
            </div>
            {detail.status_detail ? (
              <p className="text-secondary mt-1 text-[12px] leading-snug">
                {detail.status_detail}
              </p>
            ) : null}
          </div>
          {showStop ? (
            <div className="flex shrink-0 flex-col items-end gap-1">
              <button
                type="button"
                className="bg-muted text-foreground hover:bg-hover rounded-md px-3 py-1.5 text-[12px] font-medium disabled:opacity-50"
                disabled={stopBusy}
                onClick={() => void onStop()}
              >
                {stopBusy ? "Stopping…" : "Stop"}
              </button>
              {stopError ? (
                <span className="text-destructive max-w-[240px] text-[11px]">
                  {stopError}
                </span>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
      <div className="flex min-h-0 flex-1 flex-col gap-3 md:flex-row">
        <div className="min-h-[280px] flex-1 overflow-hidden rounded-lg border border-border bg-background">
          {liveUrl ? (
            <iframe
              title="Browser session"
              src={liveUrl}
              className="h-full min-h-[280px] w-full border-0"
              allow="autoplay"
            />
          ) : (
            <div className="text-secondary flex h-full items-center justify-center text-sm">
              No live preview URL
            </div>
          )}
        </div>
        <div className="border-border bg-surface/30 flex max-h-[70vh] w-full flex-col gap-1 overflow-y-auto rounded-lg border p-2 text-[12px] md:w-[360px]">
          <div className="bg-surface/80 text-tertiary sticky top-0 pb-1 text-[10px] font-medium uppercase tracking-wide">
            Activity
          </div>
          {messages.map((m, i) => (
            <div
              key={`${sessionId}-m-${i}`}
              className="border-border/50 bg-background/50 rounded border px-2 py-1.5"
            >
              <span className="text-tertiary">{String(m.role ?? "")}</span>{" "}
              <span className="text-secondary">
                {String(m.summary ?? m.data ?? m.type ?? "")}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
