"""Render @function return values for the terminal (``hof fn``).

``--format auto`` uses heuristics (tables for ``{rows, total}``, etc.).
``--format json`` prints JSON for scripting.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from rich.console import Console
from rich.table import Table

FormatLiteral = Literal["auto", "json"]

_MAX_COLUMNS = 12
_MAX_ROWS = 100
_MAX_CELL = 80
_SAMPLE_ROWS_FOR_KEYS = 50


def _cell_str(val: Any, max_cell: int) -> str:
    if val is None:
        return ""
    if isinstance(val, (dict, list)):
        s = json.dumps(val, default=str, ensure_ascii=False)
    else:
        s = str(val)
    if len(s) > max_cell:
        return s[: max_cell - 1] + "…"
    return s


def _column_key_order(rows: list[dict]) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for row in rows[:_SAMPLE_ROWS_FOR_KEYS]:
        for k in row.keys():
            if k not in seen:
                seen.add(k)
                keys.append(k)
    return keys


def _collect_columns(rows: list[dict], max_cols: int) -> list[str]:
    all_keys = _column_key_order(rows)
    return all_keys[:max_cols]


def _per_column_max_width(
    *,
    console_width: int,
    num_cols: int,
    max_cell: int,
    wrap_cells: bool,
) -> int:
    """Width budget per column so the table fits the console (avoids ultra-narrow ellipsis)."""
    if num_cols <= 0:
        return max_cell
    # Borders / padding: rough overhead per column.
    overhead = 3 * num_cols + 4
    usable = max(console_width - overhead, num_cols * 12)
    per = max(12, usable // num_cols)
    if wrap_cells:
        return min(max_cell, max(24, per))
    return min(max_cell, max(10, per))


def _print_rows_table(
    con: Console,
    rows: list[dict],
    total: Any,
    *,
    max_columns: int,
    max_cell: int,
    max_rows: int,
    wrap_cells: bool,
) -> None:
    all_keys = _column_key_order(rows)
    cols = all_keys[:max_columns]
    if not cols:
        con.print("[dim](empty rows)[/]")
        if total is not None:
            con.print(f"[dim]total[/] = {total}")
        return

    if len(all_keys) > len(cols):
        con.print(
            f"[dim]Showing {len(cols)} of {len(all_keys)} columns "
            f"(use [cyan]hof fn … --format json[/] for full data).[/]",
        )

    cw = int(con.width or 120)
    col_w = _per_column_max_width(
        console_width=cw,
        num_cols=len(cols),
        max_cell=max_cell,
        wrap_cells=wrap_cells,
    )
    overflow: Literal["ellipsis", "fold"] = "fold" if wrap_cells else "ellipsis"

    table = Table(show_header=True, header_style="bold")
    for c in cols:
        table.add_column(
            str(c),
            overflow=overflow,
            max_width=col_w,
            no_wrap=not wrap_cells,
        )
    shown = rows[:max_rows]
    for row in shown:
        table.add_row(*(_cell_str(row.get(c), max_cell) for c in cols))
    con.print(table)
    if len(rows) > max_rows:
        con.print(f"[dim]… {len(rows) - max_rows} more rows not shown[/]")
    if total is not None:
        con.print(f"[dim]total[/] = {total}")


def _print_kv_table(con: Console, data: dict[Any, Any], *, max_cell: int) -> None:
    table = Table(show_header=True, header_style="bold")
    table.add_column("key", style="cyan", overflow="ellipsis", max_width=32)
    table.add_column("value", overflow="ellipsis", max_width=max(max_cell + 20, 40))
    for k in sorted(data.keys(), key=lambda x: str(x)):
        table.add_row(str(k), _cell_str(data[k], max_cell))
    con.print(table)


def render_function_result(
    value: Any,
    *,
    fmt: FormatLiteral = "auto",
    console: Console | None = None,
    max_columns: int | None = None,
    max_cell: int | None = None,
    max_rows: int | None = None,
    wrap_cells: bool = False,
) -> None:
    """Print *value* to the console. *fmt* ``json`` matches legacy ``print_json`` behavior.

    *max_columns*, *max_cell*, *max_rows* tune tabular output (defaults match the CLI).
    *wrap_cells* uses multi-line folded cells instead of a single-line ellipsis (e.g. narrow TUIs).
    """
    con = console or Console()

    if fmt == "json":
        print(json.dumps(value, default=str, ensure_ascii=False))
        return

    mc = _MAX_COLUMNS if max_columns is None else max(1, max_columns)
    mcell = _MAX_CELL if max_cell is None else max(16, max_cell)
    mrows = _MAX_ROWS if max_rows is None else max(1, max_rows)

    # --- auto ---
    if isinstance(value, dict) and "rows" in value:
        rows_raw = value.get("rows")
        if isinstance(rows_raw, list):
            dict_rows = [r for r in rows_raw if isinstance(r, dict)]
            # Treat as tabular if every row is a dict, or rows is empty
            if len(dict_rows) == len(rows_raw):
                _print_rows_table(
                    con,
                    dict_rows,
                    value.get("total"),
                    max_columns=mc,
                    max_cell=mcell,
                    max_rows=mrows,
                    wrap_cells=wrap_cells,
                )
                return

    if isinstance(value, list) and value and all(isinstance(x, dict) for x in value):
        _print_rows_table(
            con,
            value,
            None,
            max_columns=mc,
            max_cell=mcell,
            max_rows=mrows,
            wrap_cells=wrap_cells,
        )
        return

    if isinstance(value, dict):
        _print_kv_table(con, value, max_cell=mcell)
        return

    con.print(value)
