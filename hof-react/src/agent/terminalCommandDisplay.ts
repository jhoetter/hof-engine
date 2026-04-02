/**
 * Display-only parsing for shell commands in the agent terminal UI.
 * Does not affect execution.
 *
 * Heredocs are split for parsing; the UI shows {@link displayShellInvocationFromOpener} + body only
 * (no `<<` / closing delimiter).
 */

export type ParsedTerminalCommand =
  | { kind: "single"; text: string }
  | {
      kind: "heredoc";
      shellOpener: string;
      body: string;
      closingLine?: string;
    };

/**
 * Parse a trimmed shell snippet. If the first line is a heredoc opener (`<<` / `<<-`),
 * returns structured parts; otherwise a single block (e.g. `hof fn …`).
 */
export function parseTerminalCommandForDisplay(raw: string): ParsedTerminalCommand {
  const t0 = raw.trim();
  if (!t0) {
    return { kind: "single", text: "" };
  }
  const normalized = t0.replace(/\r\n/g, "\n");
  const lines = normalized.split("\n");
  const firstLine = (lines[0] ?? "").trimEnd();
  const openerMatch = /^(.+?)<<-?\s*(['"]?)(\w+)\2\s*$/.exec(firstLine);
  if (!openerMatch) {
    return { kind: "single", text: t0 };
  }

  const delim = openerMatch[3];
  const shellOpener = firstLine;
  const restLines = lines.slice(1);
  if (restLines.length === 0) {
    return { kind: "heredoc", shellOpener, body: "", closingLine: undefined };
  }

  const lastRaw = restLines[restLines.length - 1] ?? "";
  if (lastRaw.trim() === delim) {
    const body = restLines.slice(0, -1).join("\n").trim();
    return {
      kind: "heredoc",
      shellOpener,
      body,
      closingLine: delim,
    };
  }

  const body = restLines.join("\n").trim();
  return { kind: "heredoc", shellOpener, body, closingLine: undefined };
}

/**
 * First line shown for a heredoc opener: strips `<< 'DELIM'` / `<<- DELIM`, then shortens a lone
 * path to its basename (`/usr/bin/python3` → `python3`). Multi-token lines stay as-is (`env python3`).
 */
export function displayShellInvocationFromOpener(shellOpenerLine: string): string {
  const stripped = shellOpenerLine
    .replace(/\s*<<-?\s*(['"]?)(\w+)\1\s*$/, "")
    .trim();
  const line =
    stripped.length > 0
      ? stripped
      : (() => {
          const first = shellOpenerLine.trim().split(/\s+/)[0] ?? "";
          if (!first) {
            return "";
          }
          return first.includes("/") ? (first.split("/").pop() ?? first) : first;
        })();
  const tokens = line.split(/\s+/).filter(Boolean);
  if (tokens.length === 1) {
    const w = tokens[0]!;
    return w.includes("/") ? (w.split("/").pop() ?? w) : w;
  }
  return line;
}
