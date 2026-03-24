"use client";

import type { Element } from "hast";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import { ExpandTableButton } from "./ExpandTableButton";
import { hastTableToMatrix } from "./hastTable";

/** Match HofAgentComposer skills dialog — no flex on `<dialog>` (breaks UA `display:none`). */
const TABLE_EXPAND_DIALOG_SHELL_CLASS =
  "m-0 max-h-none w-full max-w-none border-0 bg-transparent p-0 shadow-none backdrop:bg-black/40";

const TABLE_EXPAND_SCRIM_CLASS =
  "fixed inset-0 z-0 box-border flex items-center justify-center bg-transparent p-3";

const TABLE_EXPAND_PANEL_CLASS =
  "relative z-[1] max-h-[min(calc(100vh-1.5rem),52rem)] w-[min(100vw-1.5rem,72rem)] max-w-full overflow-auto rounded-lg border border-border bg-background p-4 pt-10 shadow-lg";

/** Top-right — matches code-block copy control placement. */
const hoverOverlayClass =
  "absolute right-1.5 top-1.5 z-10 opacity-0 transition-opacity pointer-events-none group-hover/table:pointer-events-auto group-hover/table:opacity-100 group-focus-within/table:pointer-events-auto group-focus-within/table:opacity-100";

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
  const [expanded, setExpanded] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const d = dialogRef.current;
    if (!d) {
      return;
    }
    if (expanded) {
      d.showModal();
    } else if (d.open) {
      d.close();
    }
  }, [expanded]);

  const sortableData = useMemo(() => {
    if (!matrix) {
      return null;
    }
    const header = matrix[0]!;
    const colCount = header.length;
    const body = matrix.slice(1);
    return { header, colCount, body };
  }, [matrix]);

  const sortedBody = useMemo(() => {
    if (!sortableData || sortableData.body.length === 0) {
      return sortableData?.body ?? [];
    }
    const col = Math.min(sortCol, sortableData.colCount - 1);
    return [...sortableData.body].sort((ra, rb) =>
      compareCells(ra[col] ?? "", rb[col] ?? "", sortDir),
    );
  }, [sortableData, sortCol, sortDir]);

  if (!matrix) {
    return (
      <MarkdownTableFallback
        expanded={expanded}
        onExpand={() => setExpanded(true)}
        onClose={() => setExpanded(false)}
        dialogRef={dialogRef}
      >
        {children}
      </MarkdownTableFallback>
    );
  }

  const header = sortableData!.header;
  const colCount = sortableData!.colCount;

  const onHeaderClick = (col: number) => {
    if (col === sortCol) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortCol(col);
      setSortDir("asc");
    }
  };

  const renderSortableTable = () => (
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
              className="border-b border-border/60 bg-transparent transition-colors last:border-b-0 hover:bg-hover/55"
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
  );

  return (
    <>
      <div className="group/table relative mb-2 max-w-full last:mb-0">
        <div className={hoverOverlayClass}>
          <ExpandTableButton
            onClick={() => setExpanded(true)}
            className="!p-1 shadow-none"
          />
        </div>
        <div className="max-w-full overflow-x-auto">{renderSortableTable()}</div>
      </div>
      <dialog
        ref={dialogRef}
        className={TABLE_EXPAND_DIALOG_SHELL_CLASS}
        onClose={() => setExpanded(false)}
        onCancel={(e) => {
          e.preventDefault();
          setExpanded(false);
        }}
      >
        {expanded ? (
          <div
            className={TABLE_EXPAND_SCRIM_CLASS}
            onMouseDown={(e) => {
              if (e.target === e.currentTarget) {
                setExpanded(false);
              }
            }}
          >
            <div
              className={TABLE_EXPAND_PANEL_CLASS}
              onMouseDown={(e) => e.stopPropagation()}
            >
              <div className="absolute right-3 top-3 z-10">
                <button
                  type="button"
                  className="rounded-md px-2 py-1 text-xs text-secondary hover:bg-hover hover:text-foreground"
                  onClick={() => setExpanded(false)}
                >
                  Close
                </button>
              </div>
              {renderSortableTable()}
            </div>
          </div>
        ) : null}
      </dialog>
    </>
  );
}

function MarkdownTableFallback({
  children,
  expanded,
  onExpand,
  onClose,
  dialogRef,
}: {
  children?: ReactNode;
  expanded: boolean;
  onExpand: () => void;
  onClose: () => void;
  dialogRef: RefObject<HTMLDialogElement | null>;
}) {
  const tableEl = (
    <table className="w-full border-collapse text-left text-[12px] text-foreground">
      {children}
    </table>
  );

  return (
    <>
      {!expanded ? (
        <div className="group/table relative mb-2 max-w-full last:mb-0">
          <div className={hoverOverlayClass}>
            <ExpandTableButton
              onClick={onExpand}
              className="!p-1 shadow-none"
            />
          </div>
          <div className="max-w-full overflow-x-auto last:mb-0">{tableEl}</div>
        </div>
      ) : null}
      <dialog
        ref={dialogRef}
        className={TABLE_EXPAND_DIALOG_SHELL_CLASS}
        onClose={onClose}
        onCancel={(e) => {
          e.preventDefault();
          onClose();
        }}
      >
        {expanded ? (
          <div
            className={TABLE_EXPAND_SCRIM_CLASS}
            onMouseDown={(e) => {
              if (e.target === e.currentTarget) {
                onClose();
              }
            }}
          >
            <div
              className={TABLE_EXPAND_PANEL_CLASS}
              onMouseDown={(e) => e.stopPropagation()}
            >
              <div className="absolute right-3 top-3 z-10">
                <button
                  type="button"
                  className="rounded-md px-2 py-1 text-xs text-secondary hover:bg-hover hover:text-foreground"
                  onClick={onClose}
                >
                  Close
                </button>
              </div>
              {tableEl}
            </div>
          </div>
        ) : null}
      </dialog>
    </>
  );
}
