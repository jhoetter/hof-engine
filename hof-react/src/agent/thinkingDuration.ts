import type { TFunction } from "i18next";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

function formatDurationMsEnglish(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  if (s < 60) {
    return s === 1 ? "1 second" : `${s} seconds`;
  }
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const parts: string[] = [];
  if (h > 0) {
    parts.push(h === 1 ? "1 hour" : `${h} hours`);
  }
  if (m > 0) {
    parts.push(m === 1 ? "1 minute" : `${m} minutes`);
  }
  if (sec > 0) {
    parts.push(sec === 1 ? "1 second" : `${sec} seconds`);
  }
  return parts.join(" ");
}

/**
 * Human-readable duration for thinking timers (whole seconds).
 * Pass ``t`` from ``useTranslation("hofEngine", …)`` for localized units; omit in tests.
 */
export function formatDurationMs(ms: number, t?: TFunction): string {
  if (!t) {
    return formatDurationMsEnglish(ms);
  }
  const s = Math.max(0, Math.floor(ms / 1000));
  if (s < 60) {
    return t("thinking.durationSecond", { count: s });
  }
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const parts: string[] = [];
  if (h > 0) {
    parts.push(t("thinking.durationHour", { count: h }));
  }
  if (m > 0) {
    parts.push(t("thinking.durationMinute", { count: m }));
  }
  if (sec > 0) {
    parts.push(t("thinking.durationSecond", { count: sec }));
  }
  return parts.join(" ");
}

/**
 * Same as {@link formatDurationMs} but returns ``null`` when the duration is under one second,
 * so the UI does not show a useless “(0 seconds)”.
 */
export function formatDurationMsForUi(ms: number, t?: TFunction): string | null {
  const s = Math.max(0, Math.floor(ms / 1000));
  if (s < 1) {
    return null;
  }
  return formatDurationMs(ms, t);
}

export type ThinkingEpisodeElapsed = {
  /** Non-null while ``streaming`` and a start time is known. */
  liveFormatted: string | null;
  /** Set once when ``streaming`` becomes false (frozen duration). */
  settledFormatted: string | null;
};

/**
 * Live tick + settled duration for a thinking episode. While ``streaming``, updates about once per second.
 */
export function useThinkingEpisodeElapsed(
  streaming: boolean,
  episodeStartMs: number | null,
  t?: TFunction,
): ThinkingEpisodeElapsed {
  const startRef = useRef<number | null>(null);
  const settledMsRef = useRef<number | null>(null);
  const [tick, setTick] = useState(0);
  const [settledFormatted, setSettledFormatted] = useState<string | null>(null);

  useLayoutEffect(() => {
    if (!streaming) {
      return;
    }
    setSettledFormatted(null);
    settledMsRef.current = null;
    if (episodeStartMs != null) {
      startRef.current = episodeStartMs;
    } else {
      startRef.current = null;
    }
    setTick((x) => x + 1);
  }, [streaming, episodeStartMs]);

  /** Freeze wall-clock duration when an episode ends (do not depend on `t` — language switches only re-label). */
  useLayoutEffect(() => {
    if (streaming) {
      return;
    }
    const start = startRef.current;
    if (start != null) {
      const ms = Date.now() - start;
      settledMsRef.current = ms;
      setSettledFormatted(formatDurationMsForUi(ms, t));
    } else {
      settledMsRef.current = null;
      setSettledFormatted(null);
    }
    // `t` omitted: recalculation on locale change is handled by the following effect (frozen ms).
  }, [streaming]);

  useLayoutEffect(() => {
    if (streaming || settledMsRef.current == null) {
      return;
    }
    setSettledFormatted(formatDurationMsForUi(settledMsRef.current, t));
  }, [t, streaming]);

  useEffect(() => {
    if (!streaming) {
      return;
    }
    const id = window.setInterval(() => setTick((x) => x + 1), 1000);
    return () => window.clearInterval(id);
  }, [streaming]);

  let liveFormatted: string | null = null;
  if (streaming && startRef.current != null) {
    liveFormatted = formatDurationMsForUi(Date.now() - startRef.current, t);
  }

  return { liveFormatted, settledFormatted };
}
