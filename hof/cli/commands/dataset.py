"""hof dataset — SQL catalog and compiled grid queries (HTTP API).

Requires a running app server (``hof dev``). Calls the spreadsheet-app functions
``get_dataset_schema`` and ``get_dataset_list_sql`` — same JSON as ``POST /api/functions/<name>``.

Usage:
    hof dataset schema [--json]
    hof dataset sql <dataset> [--page 1] [--page-size 25]
"""

from __future__ import annotations

import json

import httpx
import typer
from rich.console import Console
from rich.syntax import Syntax

app = typer.Typer(no_args_is_help=True)
console = Console()


def _api_client():
    from hof.cli.api_client import get_client

    return get_client()


@app.command("schema")
def schema_cmd(
    as_json: bool = typer.Option(False, "--json", help="Print raw JSON only."),
) -> None:
    """Fetch dataset catalog + SQL Lab schema hint (``get_dataset_schema``)."""
    client = _api_client()
    if not client:
        console.print("[red]API server not reachable. Start `hof dev` first.[/]")
        raise typer.Exit(1)
    try:
        data = client.call_function("get_dataset_schema", {})
    except httpx.HTTPStatusError as exc:
        console.print(f"[red]API error: {exc.response.status_code} {exc.response.text[:200]}[/]")
        raise typer.Exit(1) from exc
    if as_json:
        console.print(json.dumps(data, indent=2, default=str))
        return
    ds = data.get("datasets") or []
    console.print("[bold]Datasets[/bold] (id → list_function / get_sql_function)")
    for row in ds:
        console.print(
            f"  [cyan]{row.get('id')}[/] → {row.get('list_function')} / "
            f"{row.get('get_sql_function')} (default sort: {row.get('default_sort_by')} "
            f"{row.get('default_sort_dir')})",
        )
    note = data.get("note")
    if note:
        console.print(f"\n[dim]{note}[/]")
    hint = data.get("sql_lab_schema_hint") or ""
    if hint.strip():
        console.print("\n[bold]sql_lab_schema_hint[/bold]")
        console.print(Syntax(hint.strip(), "text", theme="monokai", word_wrap=True))


@app.command("sql")
def sql_cmd(
    dataset: str = typer.Argument(
        ...,
        help="Dataset id: expenses | expense_overview | revenues | budgets | receipt_documents",
    ),
    page: int = typer.Option(1, "--page", "-p", help="1-based page."),
    page_size: int = typer.Option(
        25,
        "--page-size",
        "-n",
        help="Rows per page (cap in app if large).",
    ),
    as_json: bool = typer.Option(False, "--json", help="Print raw JSON (sql + note)."),
) -> None:
    """Fetch compiled SQL for a named dataset (``get_dataset_list_sql``)."""
    client = _api_client()
    if not client:
        console.print("[red]API server not reachable. Start `hof dev` first.[/]")
        raise typer.Exit(1)
    body = {
        "dataset": dataset.strip().lower(),
        "page": page,
        "page_size": page_size,
    }
    try:
        data = client.call_function("get_dataset_list_sql", body)
    except Exception as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    if as_json:
        console.print(json.dumps(data, indent=2, default=str))
        return
    sql = (data.get("sql") or "").strip()
    note = (data.get("note") or "").strip()
    if sql:
        console.print(Syntax(sql, "sql", theme="monokai", word_wrap=True))
    if note:
        console.print(f"\n[dim]{note}[/]")
