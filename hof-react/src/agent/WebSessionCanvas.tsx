"use client";

import { useEffect, useState } from "react";

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

/**
 * Full-page canvas: live Browser Use Cloud iframe + step timeline.
 * Polls ``GET /api/web-sessions/:id/messages`` and optionally listens to ``/api/sse/:channel``.
 */
export function WebSessionCanvas({
  sessionId,
  liveUrl,
  sseChannel,
  apiPrefix = "",
}: WebSessionCanvasProps) {
  const [messages, setMessages] = useState<WireMessage[]>([]);
  const base = apiPrefix.replace(/\/$/, "");
  const pollUrl = `${base}/api/web-sessions/${encodeURIComponent(sessionId)}/messages`;

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
    };
    return () => es.close();
  }, [sseChannel, pollUrl, base]);

  return (
    <div className="flex h-full min-h-[480px] w-full flex-col gap-3 md:flex-row">
      <div className="min-h-[280px] flex-1 overflow-hidden rounded-lg border border-border bg-background">
        {liveUrl ? (
          <iframe
            title="Browser session"
            src={liveUrl}
            className="h-full min-h-[280px] w-full border-0"
            allow="autoplay"
          />
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-secondary">
            No live preview URL
          </div>
        )}
      </div>
      <div className="flex max-h-[70vh] w-full flex-col gap-1 overflow-y-auto rounded-lg border border-border bg-surface/30 p-2 text-[12px] md:w-[360px]">
        <div className="sticky top-0 bg-surface/80 pb-1 text-[10px] font-medium uppercase tracking-wide text-tertiary">
          Activity
        </div>
        {messages.map((m, i) => (
          <div
            key={`${sessionId}-m-${i}`}
            className="rounded border border-border/50 bg-background/50 px-2 py-1.5"
          >
            <span className="text-tertiary">{String(m.role ?? "")}</span>{" "}
            <span className="text-secondary">
              {String(m.summary ?? m.data ?? m.type ?? "")}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
