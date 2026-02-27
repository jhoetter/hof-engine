"""hof fn -- call and manage functions.

Usage:
    hof fn list                          List all registered functions
    hof fn schema <name>                 Show function schema
    hof fn <name>                        Call a function (no args)
    hof fn <name> --json '{"key": ...}'  Call a function with JSON input
"""

from __future__ import annotations

import asyncio
import json

import click
from rich.console import Console
from rich.table import Table as RichTable

from hof.cli.commands import bootstrap

console = Console()


class FnGroup(click.Group):
    """Custom Click group that treats unknown commands as function names."""

    def resolve_command(self, ctx: click.Context, args: list[str]):
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError:
            return args[0], args[0], args[1:]

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        cmd = super().get_command(ctx, cmd_name)
        if cmd is not None:
            return cmd
        return _make_call_command(cmd_name)


def _make_call_command(function_name: str) -> click.Command:
    @click.command(name=function_name, hidden=True)
    @click.option("--json", "-j", "input_json", default=None, help="JSON input.")
    def call_fn(input_json: str | None) -> None:
        _call_function(function_name, input_json)

    return call_fn


def _call_function(function_name: str, input_json: str | None) -> None:
    from hof.cli.api_client import get_client

    kwargs = json.loads(input_json) if input_json else {}
    client = get_client()

    if client:
        try:
            data = client.call_function(function_name, kwargs)
            console.print_json(json.dumps(data.get("result", data), default=str))
            return
        except Exception as exc:
            console.print(f"[red]API error: {exc}[/]")
            raise SystemExit(1)

    bootstrap()
    from hof.core.registry import registry

    meta = registry.get_function(function_name)
    if meta is None:
        console.print(f"[red]Function '{function_name}' not found.[/]")
        raise SystemExit(1)

    if meta.is_async:
        result = asyncio.run(meta.fn(**kwargs))
    else:
        result = meta.fn(**kwargs)

    console.print_json(json.dumps(result, default=str))


@click.group("fn", cls=FnGroup)
def app() -> None:
    """Call and manage functions."""


@app.command("list")
def list_functions() -> None:
    """List all registered functions."""
    from hof.cli.api_client import get_client

    client = get_client()
    if client:
        functions = client.list_functions()
    else:
        bootstrap()
        from hof.core.registry import registry
        functions = [meta.to_dict() for meta in registry.functions.values()]

    table = RichTable(title="Registered Functions")
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Tags")
    table.add_column("Async")

    for fn_def in functions:
        desc = fn_def.get("description", "")
        table.add_row(
            fn_def["name"],
            desc[:60] + "..." if len(desc) > 60 else desc,
            ", ".join(fn_def.get("tags", [])) or "-",
            "yes" if fn_def.get("is_async") else "no",
        )

    console.print(table)


@app.command("schema")
@click.argument("function_name")
def show_schema(function_name: str) -> None:
    """Show the input/output schema of a function."""
    from hof.cli.api_client import get_client

    client = get_client()
    if client:
        data = client.function_schema(function_name)
    else:
        bootstrap()
        from hof.core.registry import registry
        meta = registry.get_function(function_name)
        if meta is None:
            console.print(f"[red]Function '{function_name}' not found.[/]")
            raise SystemExit(1)
        data = meta.to_dict()

    console.print_json(json.dumps(data, default=str))
