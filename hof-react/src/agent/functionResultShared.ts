/**
 * Shared limits and cell/column helpers for {@link FunctionResultDisplay} HTML tables and
 * {@link formatFunctionResultPlainText} so truncation and column order stay aligned.
 */

export const RESULT_SAMPLE_ROWS_FOR_KEYS = 50;
export const RESULT_MAX_ROWS_SHOWN = 100;
export const RESULT_MAX_COLUMNS = 8;
export const RESULT_MAX_CELL = 200;

export function resultCellStr(val: unknown, maxCell: number): string {
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

export function resultColumnKeyOrder(rows: Record<string, unknown>[]): string[] {
  const keys: string[] = [];
  const seen = new Set<string>();
  for (const row of rows.slice(0, RESULT_SAMPLE_ROWS_FOR_KEYS)) {
    for (const k of Object.keys(row)) {
      if (!seen.has(k)) {
        seen.add(k);
        keys.push(k);
      }
    }
  }
  return keys;
}
