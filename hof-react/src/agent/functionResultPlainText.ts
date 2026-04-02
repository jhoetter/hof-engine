/**
 * Plain-text rendering of @function / ``hof fn`` JSON results, aligned with
 * ``hof/cli/result_render.py`` (rows+total, list of dicts, flat dict) for terminal-style chat output.
 * Caps match {@link RESULT_MAX_COLUMNS} / {@link RESULT_MAX_CELL} in `./functionResultShared`.
 */

import {
  RESULT_MAX_CELL,
  RESULT_MAX_COLUMNS,
  RESULT_MAX_ROWS_SHOWN,
  resultCellStr,
  resultColumnKeyOrder,
} from "./functionResultShared";

function padEnd(s: string, w: number): string {
  if (s.length >= w) {
    return s;
  }
  return s + " ".repeat(w - s.length);
}

function formatRowsPlain(
  rows: Record<string, unknown>[],
  total: unknown,
): string {
  const allKeys = resultColumnKeyOrder(rows);
  const cols = allKeys.slice(0, RESULT_MAX_COLUMNS);
  const shown = rows.slice(0, RESULT_MAX_ROWS_SHOWN);
  const lines: string[] = [];

  if (cols.length === 0) {
    lines.push("(empty rows)");
    if (total !== undefined && total !== null) {
      lines.push(`total = ${String(total)}`);
    }
    return lines.join("\n");
  }

  if (allKeys.length > cols.length) {
    lines.push(
      `Showing ${cols.length} of ${allKeys.length} columns (use hof fn … --format json for full data).`,
    );
  }

  const colWidths = cols.map((c) => {
    let w = c.length;
    for (const row of shown) {
      const cell = resultCellStr(row[c], RESULT_MAX_CELL);
      w = Math.max(w, cell.length);
    }
    return Math.min(w, RESULT_MAX_CELL);
  });

  lines.push(cols.map((c, i) => padEnd(c, colWidths[i]!)).join("  "));
  for (const row of shown) {
    lines.push(
      cols
        .map((c, i) =>
          padEnd(resultCellStr(row[c], RESULT_MAX_CELL), colWidths[i]!),
        )
        .join("  "),
    );
  }

  if (rows.length > RESULT_MAX_ROWS_SHOWN) {
    lines.push(`… ${rows.length - RESULT_MAX_ROWS_SHOWN} more rows not shown`);
  }
  if (total !== undefined && total !== null) {
    lines.push(`total = ${String(total)}`);
  }
  return lines.join("\n");
}

function formatKvPlain(data: Record<string, unknown>): string {
  const keys = Object.keys(data).sort((a, b) => String(a).localeCompare(String(b)));
  if (keys.length === 0) {
    return "(empty)";
  }
  const lines: string[] = [];
  const keyW = Math.max(3, ...keys.map((k) => k.length));
  for (const k of keys) {
    const v = resultCellStr(data[k], RESULT_MAX_CELL);
    lines.push(`${padEnd(k, keyW)}  ${v}`);
  }
  return lines.join("\n");
}

function isMutationPreviewEnvelope(
  v: unknown,
): v is {
  summary: string;
  data?: unknown;
  post_apply_review?: { label?: string; url?: string; path?: string };
} {
  if (v === null || typeof v !== "object" || Array.isArray(v)) {
    return false;
  }
  const o = v as Record<string, unknown>;
  if (typeof o.summary !== "string" || !o.summary.trim()) {
    return false;
  }
  return "data" in o || "post_apply_review" in o || "status_hint" in o;
}

/**
 * Format a structured function result as monospace-friendly plain text (no HTML tables).
 */
export function formatFunctionResultPlainText(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }

  if (isMutationPreviewEnvelope(value)) {
    const inner = value.data;
    if (
      inner == null ||
      typeof inner !== "object" ||
      Array.isArray(inner) ||
      Object.keys(inner as object).length === 0
    ) {
      return "";
    }
    return formatFunctionResultPlainText(inner);
  }

  if (typeof value === "object" && !Array.isArray(value) && value !== null) {
    const o = value as Record<string, unknown>;
    if ("rows" in o) {
      const rowsRaw = o.rows;
      if (Array.isArray(rowsRaw)) {
        const dictRows = rowsRaw.filter(
          (r): r is Record<string, unknown> =>
            r !== null && typeof r === "object" && !Array.isArray(r),
        );
        if (dictRows.length === rowsRaw.length) {
          return formatRowsPlain(dictRows, o.total);
        }
      }
    }
  }

  if (
    Array.isArray(value) &&
    value.length > 0 &&
    value.every((x) => x !== null && typeof x === "object" && !Array.isArray(x))
  ) {
    return formatRowsPlain(value as Record<string, unknown>[], undefined);
  }

  if (typeof value === "object" && value !== null && !Array.isArray(value)) {
    return formatKvPlain(value as Record<string, unknown>);
  }

  return String(value);
}
