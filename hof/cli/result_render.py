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


def _cell_str(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, (dict, list)):
        s = json.dumps(val, default=str, ensure_ascii=False)
    else:
        s = str(val)
    if len(s) > _MAX_CELL:
        return s[: _MAX_CELL - 1] + "…"
    return s


def _collect_columns(rows: list[dict], max_cols: int) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for row in rows[:_SAMPLE_ROWS_FOR_KEYS]:
        for k in row.keys():
            if k not in seen:
                seen.add(k)
                keys.append(k)
            if len(keys) >= max_cols:
                return keys
    return keys


def _print_rows_table(con: Console, rows: list[dict], total: Any) -> None:
    cols = _collect_columns(rows, _MAX_COLUMNS)
    if not cols:
        con.print("[dim](empty rows)[/]")
        if total is not None:
            con.print(f"[dim]total[/] = {total}")
        return

    table = Table(show_header=True, header_style="bold")
    for c in cols:
        table.add_column(str(c), overflow="ellipsis", max_width=_MAX_CELL)
    shown = rows[:_MAX_ROWS]
    for row in shown:
        table.add_row(*(_cell_str(row.get(c)) for c in cols))
    con.print(table)
    if len(rows) > _MAX_ROWS:
        con.print(f"[dim]… {len(rows) - _MAX_ROWS} more rows not shown[/]")
    if total is not None:
        con.print(f"[dim]total[/] = {total}")


def _print_kv_table(con: Console, data: dict[Any, Any]) -> None:
    table = Table(show_header=True, header_style="bold")
    table.add_column("key", style="cyan", overflow="ellipsis", max_width=32)
    table.add_column("value", overflow="ellipsis", max_width=_MAX_CELL + 20)
    for k in sorted(data.keys(), key=lambda x: str(x)):
        table.add_row(str(k), _cell_str(data[k]))
    con.print(table)


def render_function_result(
    value: Any,
    *,
    fmt: FormatLiteral = "auto",
    console: Console | None = None,
) -> None:
    """Print *value* to the console. *fmt* ``json`` matches legacy ``print_json`` behavior."""
    con = console or Console()

    if fmt == "json":
        con.print_json(data=value, default=str)
        return

    # --- auto ---
    if isinstance(value, dict) and "rows" in value:
        rows_raw = value.get("rows")
        if isinstance(rows_raw, list):
            dict_rows = [r for r in rows_raw if isinstance(r, dict)]
            # Treat as tabular if every row is a dict, or rows is empty
            if len(dict_rows) == len(rows_raw):
                _print_rows_table(con, dict_rows, value.get("total"))
                return

    if isinstance(value, list) and value and all(isinstance(x, dict) for x in value):
        _print_rows_table(con, value, None)
        return

    if isinstance(value, dict):
        _print_kv_table(con, value)
        return

    con.print(value)
