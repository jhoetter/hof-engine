"""hof fn -- call and manage functions."""

from __future__ import annotations

import asyncio
import json

import typer
from rich.console import Console
from rich.table import Table as RichTable

from hof.cli.commands import bootstrap

app = typer.Typer()
console = Console()


@app.command("call")
def call_function(
    function_name: str = typer.Argument(help="Function name to call."),
    input_json: str = typer.Option(None, "--json", "-j", help="JSON input."),
) -> None:
    """Call a function by name. Pass arguments as --json '{...}'."""
    bootstrap()
    from hof.core.registry import registry

    meta = registry.get_function(function_name)
    if meta is None:
        console.print(f"[red]Function '{function_name}' not found.[/]")
        raise typer.Exit(1)

    kwargs = json.loads(input_json) if input_json else {}

    if meta.is_async:
        result = asyncio.run(meta.fn(**kwargs))
    else:
        result = meta.fn(**kwargs)

    console.print_json(json.dumps(result, default=str))


@app.command("list")
def list_functions() -> None:
    """List all registered functions."""
    bootstrap()
    from hof.core.registry import registry

    table = RichTable(title="Registered Functions")
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Tags")
    table.add_column("Async")

    for name, meta in registry.functions.items():
        table.add_row(
            name,
            meta.description[:60] + "..." if len(meta.description) > 60 else meta.description,
            ", ".join(meta.tags) if meta.tags else "-",
            "yes" if meta.is_async else "no",
        )

    console.print(table)


@app.command("schema")
def show_schema(
    function_name: str = typer.Argument(help="Function name."),
) -> None:
    """Show the input/output schema of a function."""
    bootstrap()
    from hof.core.registry import registry

    meta = registry.get_function(function_name)
    if meta is None:
        console.print(f"[red]Function '{function_name}' not found.[/]")
        raise typer.Exit(1)

    console.print_json(json.dumps(meta.to_dict(), default=str))


