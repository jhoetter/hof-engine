"use client";

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { HOF_REACT_I18N_OPTS } from "../reactI18nextStableOpts";
import { formatFunctionResultPlainText } from "./functionResultPlainText";
import {
  RESULT_MAX_CELL,
  RESULT_MAX_COLUMNS,
  RESULT_MAX_ROWS_SHOWN,
  resultCellStr,
  resultColumnKeyOrder,
} from "./functionResultShared";
import { terminalOutputAnsiToHtml } from "./terminalAnsiHtml";
import { parseTerminalExecPayload } from "./terminalExecPayload";

/**
 * Renders @function return values like ``hof fn … --format auto`` / TUI ``render_function_result``
 * (see hof-engine ``hof/cli/result_render.py``): rows+total table, list of row dicts, or key/value dict.
 * Tables use the same monospace scale as the terminal command line (11px) for chat tool output.
 */

/** Shell command line (brighter strip — slightly stronger tint than stdout). */
const TERMINAL_CMD_SURFACE =
  "bg-[color:color-mix(in_srgb,var(--color-foreground)_2.5%,transparent)]";

/**
 * Padding, background, and monospace scale — matches the terminal command row (`px-3 py-2`, `text-[11px]`).
 * Export for standalone terminal blocks in `HofAgentChatBlocks`.
 */
export const TERMINAL_SESSION_INSET = `${TERMINAL_CMD_SURFACE} px-3 py-2 font-mono text-[11px] leading-snug`;

/** Stdout / tool output: dimmer than {@link TERMINAL_SESSION_INSET} so input vs output reads like a TTY. */
export const TERMINAL_STDOUT_SURFACE_CLASS =
  "bg-[color:color-mix(in_srgb,var(--color-foreground)_1.25%,transparent)]";

export const TERMINAL_STDOUT_BODY_CLASS = `${TERMINAL_STDOUT_SURFACE_CLASS} max-h-[min(75vh,40rem)] min-h-0 w-full overflow-auto whitespace-pre-wrap break-words px-3 py-2 font-mono text-[11px] leading-snug text-secondary`;

/** Tables for `hof fn` JSON (rows/total, row lists, key/value dicts) — matches terminal monospace scale. */
const RESULT_TABLE_CLASS =
  "w-full min-w-0 border-collapse border border-border/50 text-left text-[11px] leading-snug";
const RESULT_TABLE_HEAD_CELL =
  "max-w-[14rem] whitespace-normal break-words px-1.5 py-1 font-semibold text-foreground";
const RESULT_TABLE_BODY_CELL =
  "max-w-[14rem] whitespace-pre-wrap break-words px-1.5 py-1 align-top text-secondary";

function RowsTableView({
  rows,
  total,
}: {
  rows: Record<string, unknown>[];
  total: unknown;
}) {
  const { t } = useTranslation("hofEngine", HOF_REACT_I18N_OPTS);
  const allKeys = resultColumnKeyOrder(rows);
  const cols = allKeys.slice(0, RESULT_MAX_COLUMNS);
  const shown = rows.slice(0, RESULT_MAX_ROWS_SHOWN);
  if (cols.length === 0) {
    return (
      <div className="font-mono text-[11px] leading-snug text-secondary">
        <span className="italic">{t("functionResult.emptyRows")}</span>
        {total !== undefined && total !== null ? (
          <p className="mt-1">
            <span className="text-tertiary">{t("functionResult.total")}</span> ={" "}
            {String(total)}
          </p>
        ) : null}
      </div>
    );
  }
  return (
    <div className="min-w-0 max-w-full space-y-1.5 overflow-x-auto font-mono text-[11px] leading-snug">
      {allKeys.length > cols.length ? (
        <p className="text-tertiary">
          {t("functionResult.columnsTruncated", {
            shown: cols.length,
            total: allKeys.length,
          })}
        </p>
      ) : null}
      <table className={`${RESULT_TABLE_CLASS} w-max max-w-none`}>
        <thead>
          <tr className="border-b border-border/60 bg-surface/50">
            {cols.map((c) => (
              <th key={c} className={RESULT_TABLE_HEAD_CELL}>
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((row, ri) => (
            <tr key={ri} className="border-b border-border/40 last:border-0">
              {cols.map((c) => (
                <td key={c} className={RESULT_TABLE_BODY_CELL}>
                  {resultCellStr(row[c], RESULT_MAX_CELL)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > RESULT_MAX_ROWS_SHOWN ? (
        <p className="text-tertiary">
          {t("functionResult.moreRowsHidden", {
            count: rows.length - RESULT_MAX_ROWS_SHOWN,
          })}
        </p>
      ) : null}
      {total !== undefined && total !== null ? (
        <p className="text-tertiary">
          <span className="font-medium text-secondary">
            {t("functionResult.total")}
          </span>{" "}
          = {String(total)}
        </p>
      ) : null}
    </div>
  );
}

export { isTerminalExecPayload } from "./terminalExecPayload";

/** Curl / ``hof fn`` stdout often wraps API JSON in ``{ "result": … }`` — unwrap for table view. */
function tryUnwrapApiFunctionStdout(output: string): unknown | null {
  const t = output.trim();
  if (!t || t[0] !== "{") {
    return null;
  }
  try {
    const o = JSON.parse(t) as unknown;
    if (o === null || typeof o !== "object" || Array.isArray(o)) {
      return null;
    }
    const rec = o as Record<string, unknown>;
    if ("result" in rec && rec.result !== undefined) {
      return rec.result;
    }
    return o;
  } catch {
    return null;
  }
}

/** Sandbox ``hof_builtin_terminal_exec`` return shape — TTY-like stdout (no exit line in UI). */
function TerminalExecResultView({
  exitCode: _exitCode,
  output,
}: {
  exitCode: number;
  output: string;
}) {
  const { t } = useTranslation("hofEngine", HOF_REACT_I18N_OPTS);
  const structured = tryUnwrapApiFunctionStdout(output);
  if (structured !== null) {
    const body = formatFunctionResultPlainText(structured);
    return (
      <div
        className="min-w-0 max-w-full"
        aria-label={t("chatBlocks.terminalOutputAria")}
      >
        <pre className={`min-w-0 max-w-full ${TERMINAL_STDOUT_BODY_CLASS}`}>
          {body.length === 0 ? (
            <span className="italic text-tertiary">
              {t("functionResult.noOutput")}
            </span>
          ) : (
            body
          )}
        </pre>
      </div>
    );
  }
  if (output.length === 0) {
    return (
      <div
        className="min-w-0 max-w-full"
        aria-label={t("chatBlocks.terminalOutputAria")}
      >
        <pre className={`min-w-0 max-w-full ${TERMINAL_STDOUT_BODY_CLASS}`}>
          <span className="italic text-tertiary">
            {t("functionResult.noOutput")}
          </span>
        </pre>
      </div>
    );
  }
  const html = terminalOutputAnsiToHtml(output);
  return (
    <div
      className="min-w-0 max-w-full"
      aria-label={t("chatBlocks.terminalOutputAria")}
    >
      <div
        className={`hof-terminal-ansi min-w-0 max-w-full ${TERMINAL_STDOUT_BODY_CLASS}`}
        /* eslint-disable-next-line react/no-danger -- ansi_up escapes HTML; colors are SGR only */
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  );
}

function KvTableView({ data }: { data: Record<string, unknown> }) {
  const { t } = useTranslation("hofEngine", HOF_REACT_I18N_OPTS);
  const keys = Object.keys(data).sort((a, b) => String(a).localeCompare(String(b)));
  if (keys.length === 0) {
    return (
      <p className="font-mono text-[11px] italic leading-snug text-tertiary">
        {t("functionResult.empty")}
      </p>
    );
  }
  return (
    <div className="min-w-0 max-w-full overflow-x-auto font-mono text-[11px] leading-snug">
      <table className={RESULT_TABLE_CLASS}>
        <thead>
          <tr className="border-b border-border/60 bg-surface/50">
            <th className={`${RESULT_TABLE_HEAD_CELL} w-[32%]`}>
              {t("functionResult.keyColumn")}
            </th>
            <th className={RESULT_TABLE_HEAD_CELL}>
              {t("functionResult.valueColumn")}
            </th>
          </tr>
        </thead>
        <tbody>
          {keys.map((k) => (
            <tr key={k} className="border-b border-border/40 last:border-0">
              <td className="whitespace-nowrap px-1.5 py-1 align-top text-[var(--color-accent)]">
                {k}
              </td>
              <td className="max-w-[min(100%,24rem)] whitespace-pre-wrap break-words px-1.5 py-1 align-top text-secondary">
                {resultCellStr(data[k], RESULT_MAX_CELL)}
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

export type FunctionResultDisplayVariant = "tables" | "terminalPlain";

export function FunctionResultDisplay({
  value,
  variant = "tables",
}: {
  value: unknown;
  /** `terminalPlain`: monospace text (and ANSI when wrapped in terminal exec), no HTML tables — chat tool cards. */
  variant?: FunctionResultDisplayVariant;
}) {
  const { t } = useTranslation("hofEngine", HOF_REACT_I18N_OPTS);
  const shell = (node: ReactNode) => (
    <div className="min-w-0 max-w-full">{node}</div>
  );

  if (value === null || value === undefined) {
    return null;
  }

  if (isMutationPreviewEnvelope(value)) {
    const inner = value.data;
    if (
      inner == null ||
      typeof inner !== "object" ||
      Array.isArray(inner) ||
      Object.keys(inner as object).length === 0
    ) {
      return null;
    }
    return shell(
      <FunctionResultDisplay value={inner} variant={variant} />,
    );
  }

  const terminalPayload = parseTerminalExecPayload(value);
  if (terminalPayload !== null) {
    return shell(
      <TerminalExecResultView
        exitCode={terminalPayload.exit_code}
        output={terminalPayload.output}
      />,
    );
  }

  if (variant === "terminalPlain") {
    const body = formatFunctionResultPlainText(value);
    const text = body.length > 0 ? body : String(value);
    return shell(
      <pre
        className={`min-w-0 max-w-full ${TERMINAL_STDOUT_BODY_CLASS}`}
        aria-label={t("chatBlocks.toolOutputAria")}
      >
        {text}
      </pre>,
    );
  }

  if (typeof value === "object" && !Array.isArray(value) && value !== null) {
    const o = value as Record<string, unknown>;
    if ("_cli_display" in o && o._cli_display != null) {
      return shell(
        <FunctionResultDisplay value={o._cli_display} variant={variant} />,
      );
    }
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
    <pre className="max-w-full overflow-x-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-snug text-secondary">
      {String(value)}
    </pre>,
  );
}
