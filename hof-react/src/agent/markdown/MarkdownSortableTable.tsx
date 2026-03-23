"use client";

import type { Element } from "hast";
import { useMemo, useState, type ReactNode } from "react";
import { hastTableToMatrix } from "./hastTable";

function compareCells(a: string, b: string, dir: "asc" | "desc"): number {
  const sign = dir === "asc" ? 1 : -1;
  const ta = a.trim();
  const tb = b.trim();
  const na = Number.parseFloat(ta.replace(/,/g, ""));
  const nb = Number.parseFloat(tb.replace(/,/g, ""));
  const num =
    /^-?\d/.test(ta) &&
    /^-?\d/.test(tb) &&
    !Number.isNaN(na) &&
    !Number.isNaN(nb);
  if (num) {
    return sign * (na - nb);
  }
  return (
    sign *
    ta.localeCompare(tb, undefined, { numeric: true, sensitivity: "base" })
  );
}

export function MarkdownSortableTable({
  node,
  children,
}: {
  node?: Element | undefined;
  children?: ReactNode;
}) {
  const matrix = useMemo(() => {
    if (!node || node.tagName !== "table") {
      return null;
    }
    return hastTableToMatrix(node);
  }, [node]);

  const [sortCol, setSortCol] = useState(0);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  if (!matrix) {
    return (
      <div className="mb-2 max-w-full overflow-x-auto last:mb-0">
        <table className="w-full border-collapse text-left text-[12px] text-foreground">
          {children}
        </table>
      </div>
    );
  }

  const header = matrix[0]!;
  const colCount = header.length;

  const body = useMemo(() => matrix.slice(1), [matrix]);

  const sortedBody = useMemo(() => {
    if (body.length === 0) {
      return body;
    }
    const col = Math.min(sortCol, colCount - 1);
    return [...body].sort((ra, rb) =>
      compareCells(ra[col] ?? "", rb[col] ?? "", sortDir),
    );
  }, [body, sortCol, sortDir, colCount]);

  const onHeaderClick = (col: number) => {
    if (col === sortCol) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortCol(col);
      setSortDir("asc");
    }
  };

  return (
    <div className="mb-2 max-w-full overflow-x-auto last:mb-0">
      <table className="w-full border-collapse overflow-hidden rounded-lg border border-border text-left text-sm text-foreground">
        <thead>
          <tr className="border-b border-border bg-surface/40">
            {header.map((label, i) => (
              <th key={i} className="px-3 py-2.5 align-middle">
                <button
                  type="button"
                  className="flex w-full items-center gap-1 text-left text-xs font-medium text-secondary transition-colors hover:text-foreground"
                  onClick={() => onHeaderClick(i)}
                  aria-sort={
                    sortCol === i
                      ? sortDir === "asc"
                        ? "ascending"
                        : "descending"
                      : "none"
                  }
                >
                  <span className="min-w-0 flex-1 truncate">{label}</span>
                  {sortCol === i ? (
                    <span className="shrink-0 text-[10px] text-tertiary">
                      {sortDir === "asc" ? "▲" : "▼"}
                    </span>
                  ) : (
                    <span className="shrink-0 text-[10px] text-tertiary opacity-40">
                      ↕
                    </span>
                  )}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sortedBody.length === 0 ? (
            <tr>
              <td
                colSpan={colCount}
                className="px-4 py-6 text-center text-xs text-secondary"
              >
                No rows
              </td>
            </tr>
          ) : (
            sortedBody.map((row, ri) => (
              <tr
                key={ri}
                className="border-b border-border/60 bg-background transition-colors last:border-b-0 hover:bg-hover/80"
              >
                {row.map((cell, ci) => (
                  <td
                    key={ci}
                    className="px-3 py-2.5 align-top text-xs text-secondary"
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
