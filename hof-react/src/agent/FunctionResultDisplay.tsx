"use client";

import type { ReactNode } from "react";

/**
 * Renders @function return values like ``hof fn … --format auto`` / TUI ``render_function_result``
 * (see hof-engine ``hof/cli/result_render.py``): rows+total table, list of row dicts, or key/value dict.
 */

const SAMPLE_ROWS_FOR_KEYS = 50;
const MAX_ROWS_SHOWN = 100;
const MAX_COLUMNS = 8;
const MAX_CELL = 200;

function cellStr(val: unknown, maxCell: number): string {
  if (val === null || val === undefined) {
    return "";
  }
  if (typeof val === "object") {
    const s = JSON.stringify(val);
    return s.length > maxCell ? `${s.slice(0, maxCell - 1)}…` : s;
  }
  const s = String(val);
  return s.length > maxCell ? `${s.slice(0, maxCell - 1)}…` : s;
}

function columnKeyOrder(rows: Record<string, unknown>[]): string[] {
  const keys: string[] = [];
  const seen = new Set<string>();
  for (const row of rows.slice(0, SAMPLE_ROWS_FOR_KEYS)) {
    for (const k of Object.keys(row)) {
      if (!seen.has(k)) {
        seen.add(k);
        keys.push(k);
      }
    }
  }
  return keys;
}

function RowsTableView({
  rows,
  total,
}: {
  rows: Record<string, unknown>[];
  total: unknown;
}) {
  const allKeys = columnKeyOrder(rows);
  const cols = allKeys.slice(0, MAX_COLUMNS);
  const shown = rows.slice(0, MAX_ROWS_SHOWN);
  if (cols.length === 0) {
    return (
      <div className="font-mono text-[10px] text-secondary">
        <span className="italic">(empty rows)</span>
        {total !== undefined && total !== null ? (
          <p className="mt-1">
            <span className="text-tertiary">total</span> = {String(total)}
          </p>
        ) : null}
      </div>
    );
  }
  return (
    <div className="min-w-0 max-w-full space-y-1.5 overflow-x-auto font-mono">
      {allKeys.length > cols.length ? (
        <p className="text-[10px] text-tertiary">
          Showing {cols.length} of {allKeys.length} columns (use{" "}
          <span className="text-secondary">hof fn … --format json</span> for full
          data).
        </p>
      ) : null}
      <table className="w-max max-w-none min-w-0 border-collapse border border-border text-left text-[10px]">
        <thead>
          <tr className="border-b border-border bg-surface/80">
            {cols.map((c) => (
              <th
                key={c}
                className="max-w-[14rem] whitespace-normal break-words px-2 py-1.5 font-semibold text-foreground"
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((row, ri) => (
            <tr key={ri} className="border-b border-border/80 last:border-0">
              {cols.map((c) => (
                <td
                  key={c}
                  className="max-w-[14rem] whitespace-pre-wrap break-words px-2 py-1.5 align-top text-secondary"
                >
                  {cellStr(row[c], MAX_CELL)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > MAX_ROWS_SHOWN ? (
        <p className="text-[10px] text-tertiary">
          … {rows.length - MAX_ROWS_SHOWN} more rows not shown
        </p>
      ) : null}
      {total !== undefined && total !== null ? (
        <p className="text-[10px] text-tertiary">
          <span className="font-medium text-secondary">total</span> = {String(total)}
        </p>
      ) : null}
    </div>
  );
}

function KvTableView({ data }: { data: Record<string, unknown> }) {
  const keys = Object.keys(data).sort((a, b) => String(a).localeCompare(String(b)));
  if (keys.length === 0) {
    return (
      <p className="font-mono text-[10px] italic text-tertiary">(empty)</p>
    );
  }
  return (
    <div className="min-w-0 max-w-full overflow-x-auto">
    <table className="w-full min-w-0 border-collapse border border-border text-left font-mono text-[10px]">
      <thead>
        <tr className="border-b border-border bg-surface/80">
          <th className="w-[32%] px-2 py-1.5 font-semibold text-foreground">key</th>
          <th className="px-2 py-1.5 font-semibold text-foreground">value</th>
        </tr>
      </thead>
      <tbody>
        {keys.map((k) => (
          <tr key={k} className="border-b border-border/80 last:border-0">
            <td className="whitespace-nowrap px-2 py-1.5 align-top text-[var(--color-accent)]">
              {k}
            </td>
            <td className="max-w-[min(100%,24rem)] whitespace-pre-wrap break-words px-2 py-1.5 align-top text-secondary">
              {cellStr(data[k], MAX_CELL)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
    </div>
  );
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
  return (
    "data" in o || "post_apply_review" in o || "status_hint" in o
  );
}

export function FunctionResultDisplay({
  value,
}: {
  value: unknown;
}) {
  const shell = (node: ReactNode) => (
    <div className="min-w-0 max-w-full">{node}</div>
  );

  if (value === null || value === undefined) {
    return null;
  }

  if (isMutationPreviewEnvelope(value)) {
    const pr = value.post_apply_review;
    const prLabel =
      pr && typeof pr === "object" && typeof pr.label === "string"
        ? pr.label.trim()
        : "";
    const inner = value.data;
    const showInner =
      inner != null &&
      typeof inner === "object" &&
      !Array.isArray(inner) &&
      Object.keys(inner as object).length > 0;
    return shell(
      <div className="space-y-2">
        <p className="text-[11px] font-medium leading-snug text-foreground">
          {value.summary}
        </p>
        {showInner ? <FunctionResultDisplay value={inner} /> : null}
        {prLabel ? (
          <p className="text-[10px] leading-snug text-tertiary">
            After apply: <span className="text-secondary">{prLabel}</span>
            {typeof pr?.path === "string" && pr.path.trim() ? (
              <span className="text-tertiary"> ({pr.path.trim()})</span>
            ) : null}
          </p>
        ) : null}
      </div>,
    );
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
          return shell(<RowsTableView rows={dictRows} total={o.total} />);
        }
      }
    }
  }

  if (
    Array.isArray(value) &&
    value.length > 0 &&
    value.every((x) => x !== null && typeof x === "object" && !Array.isArray(x))
  ) {
    return shell(
      <RowsTableView rows={value as Record<string, unknown>[]} total={undefined} />,
    );
  }

  if (typeof value === "object" && value !== null && !Array.isArray(value)) {
    return shell(<KvTableView data={value as Record<string, unknown>} />);
  }

  return shell(
    <pre className="max-w-full overflow-x-auto whitespace-pre-wrap break-words font-mono text-[10px] leading-snug text-secondary">
      {String(value)}
    </pre>,
  );
}
