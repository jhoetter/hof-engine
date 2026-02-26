"""hof table -- interact with tables."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table as RichTable

app = typer.Typer()
console = Console()


def _ensure_discovered() -> None:
    from hof.config import load_config
    from hof.core.discovery import discover_all

    config = load_config(Path.cwd())
    discover_all(Path.cwd(), config.discovery_dirs)


@app.callback(invoke_without_command=True)
def table_root(
    ctx: typer.Context,
    table_name: str = typer.Argument(None, help="Table name."),
    action: str = typer.Argument(None, help="Action: list, get, create, update, delete, count."),
    record_id: str = typer.Argument(None, help="Record ID (for get/update/delete)."),
    filter_str: str = typer.Option(None, "--filter", "-f", help="Filter: key=value,key=value"),
    order_by: str = typer.Option(None, "--order-by", "-o", help="Sort field (prefix - for desc)."),
    limit: int = typer.Option(20, "--limit", "-l", help="Max results."),
    offset: int = typer.Option(0, "--offset", help="Skip N results."),
    input_json: str = typer.Option(None, "--json", "-j", help="JSON input for create/update."),
) -> None:
    """Interact with a table. Usage: hof table <name> <action> [id]"""
    if ctx.invoked_subcommand is not None:
        return
    if table_name is None or action is None:
        console.print("[dim]Usage: hof table <name> <action> [id][/]")
        console.print("[dim]Actions: list, get, create, update, delete, count[/]")
        raise typer.Exit()

    _ensure_discovered()
    from hof.core.registry import registry

    table_cls = registry.get_table(table_name)
    if table_cls is None:
        console.print(f"[red]Table '{table_name}' not found.[/]")
        raise typer.Exit(1)

    filters = _parse_filters(filter_str) if filter_str else {}

    if action == "list":
        records = table_cls.query(
            filters=filters, order_by=order_by, limit=limit, offset=offset
        )
        if not records:
            console.print("[dim]No records found.[/]")
            return
        _print_records(records)

    elif action == "get":
        if not record_id:
            console.print("[red]Record ID required for 'get'.[/]")
            raise typer.Exit(1)
        record = table_cls.get(record_id)
        if record is None:
            console.print(f"[red]Record '{record_id}' not found.[/]")
            raise typer.Exit(1)
        console.print_json(json.dumps(record.to_dict(), default=str))

    elif action == "create":
        data = json.loads(input_json) if input_json else _parse_cli_kwargs(ctx.args)
        record = table_cls.create(**data)
        console.print(f"[green]Created:[/] {record.id}")

    elif action == "update":
        if not record_id:
            console.print("[red]Record ID required for 'update'.[/]")
            raise typer.Exit(1)
        data = json.loads(input_json) if input_json else _parse_cli_kwargs(ctx.args)
        record = table_cls.update(record_id, **data)
        console.print(f"[green]Updated:[/] {record_id}")

    elif action == "delete":
        if not record_id:
            console.print("[red]Record ID required for 'delete'.[/]")
            raise typer.Exit(1)
        table_cls.delete(record_id)
        console.print(f"[yellow]Deleted:[/] {record_id}")

    elif action == "count":
        count = table_cls.count(filters=filters)
        console.print(f"Count: {count}")

    else:
        console.print(f"[red]Unknown action '{action}'. Use: list, get, create, update, delete, count[/]")
        raise typer.Exit(1)


@app.command("list-definitions")
def list_definitions() -> None:
    """List all registered table definitions."""
    _ensure_discovered()
    from hof.core.registry import registry

    table = RichTable(title="Registered Tables")
    table.add_column("Name", style="cyan")
    table.add_column("Columns")

    for name, table_cls in registry.tables.items():
        cols = [c.name for c in table_cls.__table__.columns if c.name != "id"]
        table.add_row(name, ", ".join(cols))

    console.print(table)


def _parse_filters(filter_str: str) -> dict:
    filters = {}
    for pair in filter_str.split(","):
        if "=" in pair:
            key, val = pair.split("=", 1)
            filters[key.strip()] = val.strip()
    return filters


def _parse_cli_kwargs(args: list[str]) -> dict:
    kwargs: dict = {}
    for arg in args:
        if arg.startswith("--") and "=" in arg:
            key, val = arg[2:].split("=", 1)
            kwargs[key.replace("-", "_")] = val
    return kwargs


def _print_records(records: list) -> None:
    if not records:
        return
    first = records[0].to_dict()
    table = RichTable()
    for col in first:
        table.add_column(col)
    for record in records:
        d = record.to_dict()
        table.add_row(*[str(v) for v in d.values()])
    console.print(table)
