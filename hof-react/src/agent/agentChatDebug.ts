/**
 * Agent chat tracing (labels, lanes, NDJSON types).
 *
 * **Opt-in only** — does not write to `console` (keeps demos and dev shells quiet).
 * Enable extra work (e.g. `ui_snapshot` effect in {@link ./hofAgentChatContext.tsx}):
 *   `localStorage.setItem("hof:agentChatDebug", "1"); location.reload()`
 *
 * Disable explicitly: `localStorage.setItem("hof:agentChatDebug", "0")`
 * Or URL: `?hofAgentChatDebug=1` (also sets sessionStorage for this tab).
 */

const STORAGE_KEY = "hof:agentChatDebug";
const URL_PARAM = "hofAgentChatDebug";

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

/**
 * Reserved for future hooks (e.g. custom telemetry). Intentionally does not use `console`
 * so assistant pages stay quiet when debug mode is on.
 */
export function agentChatDebugLog(
  _scope: string,
  _payload: Record<string, unknown>,
): void {
  if (!isAgentChatDebugEnabled()) {
    return;
  }
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
  } else if (typ === "awaiting_web_session") {
    payload.session_id = ev.session_id;
    payload.run_id = ev.run_id;
    payload.sse_channel = ev.sse_channel;
  } else if (typ === "awaiting_inbox_review") {
    payload.run_id = ev.run_id;
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
