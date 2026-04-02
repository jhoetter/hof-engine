/**
 * Normalize ``hof_builtin_terminal_exec`` tool JSON for UI (status + stdout rendering).
 * Handles stringified payloads, numeric ``exit_code`` as string, and nested
 * ``{ result: … }`` / ``{ data: … }`` / string ``result`` (HTTP / proxy wrappers).
 */

export type TerminalExecPayload = {
  exit_code: number;
  output: string;
};

function _coerceExitCode(raw: unknown): number {
  if (typeof raw === "number" && Number.isFinite(raw)) {
    return raw;
  }
  if (typeof raw === "string" && /^-?\d+$/.test(raw.trim())) {
    return parseInt(raw.trim(), 10);
  }
  return NaN;
}

/**
 * Walk ``result`` / ``data`` / JSON-string ``result`` until we find ``exit_code`` + ``output``.
 */
function peelTerminalRecord(o: Record<string, unknown>): Record<string, unknown> | null {
  let cur: unknown = o;
  for (let depth = 0; depth < 8; depth++) {
    if (cur === null || typeof cur !== "object" || Array.isArray(cur)) {
      return null;
    }
    const rec = cur as Record<string, unknown>;
    if ("exit_code" in rec && "output" in rec) {
      return rec;
    }
    let next: unknown = undefined;
    if ("result" in rec) {
      const r = rec.result;
      if (typeof r === "string") {
        const t = r.trim();
        if (t.startsWith("{")) {
          try {
            next = JSON.parse(t) as unknown;
          } catch {
            next = undefined;
          }
        }
      } else if (r !== null && typeof r === "object" && !Array.isArray(r)) {
        next = r;
      }
    }
    if (next === undefined && "data" in rec) {
      const d = rec.data;
      if (d !== null && typeof d === "object" && !Array.isArray(d)) {
        next = d;
      }
    }
    if (next !== undefined) {
      cur = next;
      continue;
    }
    return null;
  }
  return null;
}

/**
 * Parse sandbox terminal-exec shape, or ``null`` if ``value`` is not terminal output.
 */
export function parseTerminalExecPayload(value: unknown): TerminalExecPayload | null {
  let v = value;
  if (typeof v === "string") {
    const t = v.trim();
    if (!t.startsWith("{")) {
      return null;
    }
    try {
      v = JSON.parse(t) as unknown;
    } catch {
      return null;
    }
  }
  if (v === null || typeof v !== "object" || Array.isArray(v)) {
    return null;
  }
  const peeled = peelTerminalRecord(v as Record<string, unknown>);
  if (peeled === null) {
    return null;
  }
  const exit_code = _coerceExitCode(peeled.exit_code);
  if (!Number.isFinite(exit_code)) {
    return null;
  }
  const outRaw = peeled.output;
  let output: string;
  if (typeof outRaw === "string") {
    output = outRaw;
  } else if (outRaw === undefined || outRaw === null) {
    output = "";
  } else {
    output = JSON.stringify(outRaw);
  }
  return { exit_code, output };
}

/** Type guard for parsed terminal payloads (after {@link parseTerminalExecPayload}). */
export function isTerminalExecPayload(
  value: unknown,
): value is TerminalExecPayload {
  return parseTerminalExecPayload(value) !== null;
}
