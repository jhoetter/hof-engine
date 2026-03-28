/**
 * Agent chat tracing (labels, lanes, NDJSON types).
 *
 * **Vite dev:** logging is **on by default** (spreadsheet-app resolves `@hof-engine/react` to src).
 * Disable: `localStorage.setItem("hof:agentChatDebug", "0"); location.reload()`
 *
 * **Production / non-Vite:** enable explicitly:
 *   `localStorage.setItem("hof:agentChatDebug", "1"); location.reload()`
 *
 * Or URL: `?hofAgentChatDebug=1` (also sets sessionStorage for this tab).
 */

const STORAGE_KEY = "hof:agentChatDebug";
const URL_PARAM = "hofAgentChatDebug";

function viteDev(): boolean {
  try {
    const env = (import.meta as unknown as { env?: { DEV?: boolean } }).env;
    return env?.DEV === true;
  } catch {
    return false;
  }
}

function readEnabled(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  try {
    // Explicit opt-out (e.g. noisy during demos)
    if (window.localStorage?.getItem(STORAGE_KEY) === "0") {
      return false;
    }
    if (window.sessionStorage?.getItem(URL_PARAM) === "1") {
      return true;
    }
    if (window.localStorage?.getItem(STORAGE_KEY) === "1") {
      return true;
    }
    // Vite dev: on by default so traces appear without localStorage (spreadsheet-app aliases src).
    if (viteDev()) {
      return true;
    }
    if (typeof window.location?.search === "string") {
      const q = new URLSearchParams(window.location.search);
      if (q.get(URL_PARAM) === "1") {
        try {
          window.sessionStorage.setItem(URL_PARAM, "1");
        } catch {
          /* ignore */
        }
        return true;
      }
    }
  } catch {
    return false;
  }
  return false;
}

let cached = false;
let lastCheck = 0;
const RECHECK_MS = 2000;

export function isAgentChatDebugEnabled(): boolean {
  const now = Date.now();
  if (now - lastCheck > RECHECK_MS) {
    lastCheck = now;
    cached = readEnabled();
  }
  return cached;
}

/** One-line console trace (no PII: no message bodies, tool args trimmed). */
export function agentChatDebugLog(
  scope: string,
  payload: Record<string, unknown>,
): void {
  if (!isAgentChatDebugEnabled()) {
    return;
  }
  // eslint-disable-next-line no-console
  console.info(`[HofAgentChat:${scope}]`, payload);
}

/** NDJSON row from ``agent_chat`` — deltas only log char counts. */
export function agentChatDebugNdjson(
  typ: string,
  ev: Record<string, unknown>,
): void {
  if (!isAgentChatDebugEnabled()) {
    return;
  }
  const payload: Record<string, unknown> = { typ };
  if (typ === "phase") {
    payload.phase = ev.phase;
    payload.discover_phase = ev.discover_phase;
    payload.round = ev.round;
  } else if (typ === "plan_discover") {
    payload.subphase = ev.subphase;
    payload.round = ev.round;
  } else if (typ === "tool_call") {
    payload.name = ev.name;
    payload.tool_call_id = ev.tool_call_id;
  } else if (typ === "assistant_done") {
    payload.finish_reason = ev.finish_reason;
  } else if (typ === "assistant_delta" || typ === "reasoning_delta") {
    const t = typeof ev.text === "string" ? ev.text : "";
    payload.chars = t.length;
  } else if (typ === "run_start" || typ === "resume_start") {
    payload.run_id = ev.run_id;
  } else if (typ === "segment_start") {
    payload.segment = ev.segment;
  } else if (
    typ === "final" ||
    typ === "awaiting_plan_clarification" ||
    typ === "error"
  ) {
    payload.mode = ev.mode;
    payload.detail =
      typeof ev.detail === "string" ? ev.detail.slice(0, 120) : undefined;
  }
  agentChatDebugLog("ndjson", payload);
}
