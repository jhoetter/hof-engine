"""hof flow -- manage and run flows."""

from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table as RichTable

from hof.cli.commands import bootstrap

app = typer.Typer()
console = Console()


@app.command("run")
def run_flow(
    flow_name: str = typer.Argument(help="Name of the flow to run."),
    input_json: str = typer.Option("{}", "--input", "-i", help="JSON input for the flow."),
) -> None:
    """Trigger a new flow execution."""
    bootstrap()
    from hof.core.registry import registry

    flow = registry.get_flow(flow_name)
    if flow is None:
        console.print(f"[red]Flow '{flow_name}' not found.[/]")
        raise typer.Exit(1)

    input_data = json.loads(input_json)
    execution = flow.run(**input_data)
    console.print(f"[green]Started execution:[/] {execution.id}")
    console.print(f"  Flow: {flow_name}")
    console.print(f"  Status: {execution.status}")


@app.command("list")
def list_executions(
    flow_name: str = typer.Argument(None, help="Flow name (omit for all flows)."),
    status: str = typer.Option(None, "--status", "-s", help="Filter by status."),
    limit: int = typer.Option(20, "--limit", "-l", help="Max results."),
) -> None:
    """List flow executions."""
    bootstrap()
    from hof.flows.state import ExecutionStore

    store = ExecutionStore()
    executions = store.list_executions(flow_name=flow_name, status=status, limit=limit)

    table = RichTable(title="Flow Executions")
    table.add_column("ID", style="cyan")
    table.add_column("Flow")
    table.add_column("Status")
    table.add_column("Started")
    table.add_column("Duration")

    for ex in executions:
        table.add_row(
            str(ex.id)[:8],
            ex.flow_name,
            ex.status,
            str(ex.started_at) if ex.started_at else "-",
            f"{ex.duration_ms}ms" if ex.duration_ms else "-",
        )

    console.print(table)


@app.command("get")
def get_execution(
    execution_id: str = typer.Argument(help="Execution ID."),
    nodes: bool = typer.Option(False, "--nodes", "-n", help="Show per-node details."),
    logs: bool = typer.Option(False, "--logs", help="Show execution logs."),
) -> None:
    """Get details of a flow execution."""
    bootstrap()
    from hof.flows.state import ExecutionStore

    store = ExecutionStore()
    execution = store.get_execution(execution_id)

    if execution is None:
        console.print(f"[red]Execution '{execution_id}' not found.[/]")
        raise typer.Exit(1)

    console.print(f"[bold]Execution {execution.id}[/]")
    console.print(f"  Flow: {execution.flow_name}")
    console.print(f"  Status: {execution.status}")
    console.print(f"  Started: {execution.started_at}")
    console.print(f"  Duration: {execution.duration_ms}ms" if execution.duration_ms else "")

    if nodes and execution.node_states:
        table = RichTable(title="Node States")
        table.add_column("Node")
        table.add_column("Status")
        table.add_column("Duration")
        for ns in execution.node_states:
            table.add_row(ns.node_name, ns.status, f"{ns.duration_ms}ms" if ns.duration_ms else "-")
        console.print(table)


@app.command("cancel")
def cancel_execution(
    execution_id: str = typer.Argument(help="Execution ID to cancel."),
) -> None:
    """Cancel a running flow execution."""
    from hof.flows.state import ExecutionStore

    store = ExecutionStore()
    store.update_status(execution_id, "cancelled")
    console.print(f"[yellow]Cancelled execution {execution_id}[/]")


@app.command("list-definitions")
def list_definitions() -> None:
    """List all registered flow definitions."""
    bootstrap()
    from hof.core.registry import registry

    table = RichTable(title="Registered Flows")
    table.add_column("Name", style="cyan")
    table.add_column("Nodes")
    table.add_column("Entry Nodes")

    for name, flow in registry.flows.items():
        entry_nodes = [n.name for n in flow.nodes.values() if not n.depends_on]
        table.add_row(name, str(len(flow.nodes)), ", ".join(entry_nodes))

    console.print(table)
