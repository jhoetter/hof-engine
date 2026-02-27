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
    from hof.cli.api_client import get_client

    input_data = json.loads(input_json)
    client = get_client()

    if client:
        data = client.run_flow(flow_name, input_data)
        console.print(f"[green]Started execution:[/] {data.get('id', 'unknown')}")
        console.print(f"  Flow: {flow_name}")
        console.print(f"  Status: {data.get('status', 'unknown')}")
        return

    bootstrap()
    from hof.core.registry import registry

    flow = registry.get_flow(flow_name)
    if flow is None:
        console.print(f"[red]Flow '{flow_name}' not found.[/]")
        raise typer.Exit(1)

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
    from hof.cli.api_client import get_client

    client = get_client()

    if client and flow_name:
        executions = client.list_executions(flow_name, status=status, limit=limit)
        _print_executions_table(executions)
        return

    bootstrap()
    from hof.flows.state import execution_store

    execs = execution_store.list_executions(flow_name=flow_name, status=status, limit=limit)
    _print_executions_table([e.to_dict() for e in execs])


@app.command("get")
def get_execution(
    execution_id: str = typer.Argument(help="Execution ID."),
    nodes: bool = typer.Option(False, "--nodes", "-n", help="Show per-node details."),
) -> None:
    """Get details of a flow execution."""
    from hof.cli.api_client import get_client

    client = get_client()

    if client:
        data = client.get_execution(execution_id)
    else:
        bootstrap()
        from hof.flows.state import execution_store
        ex = execution_store.get_execution(execution_id)
        if ex is None:
            console.print(f"[red]Execution '{execution_id}' not found.[/]")
            raise typer.Exit(1)
        data = ex.to_dict()

    console.print(f"[bold]Execution {data['id']}[/]")
    console.print(f"  Flow: {data['flow_name']}")
    console.print(f"  Status: {data['status']}")
    console.print(f"  Started: {data.get('started_at', '-')}")
    if data.get("duration_ms"):
        console.print(f"  Duration: {data['duration_ms']}ms")

    if nodes and data.get("node_states"):
        table = RichTable(title="Node States")
        table.add_column("Node")
        table.add_column("Status")
        table.add_column("Duration")
        for ns in data["node_states"]:
            dur = f"{ns['duration_ms']}ms" if ns.get("duration_ms") else "-"
            table.add_row(ns["node_name"], ns["status"], dur)
        console.print(table)


@app.command("cancel")
def cancel_execution(
    execution_id: str = typer.Argument(help="Execution ID to cancel."),
) -> None:
    """Cancel a running flow execution."""
    from hof.flows.state import execution_store

    execution_store.update_status(execution_id, "cancelled")
    console.print(f"[yellow]Cancelled execution {execution_id}[/]")


@app.command("list-definitions")
def list_definitions() -> None:
    """List all registered flow definitions."""
    from hof.cli.api_client import get_client

    client = get_client()
    if client:
        flows = client.list_flows()
        table = RichTable(title="Registered Flows")
        table.add_column("Name", style="cyan")
        table.add_column("Nodes")
        for f in flows:
            table.add_row(f["name"], str(len(f.get("nodes", {}))))
        console.print(table)
        return

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


def _print_executions_table(executions: list[dict]) -> None:
    table = RichTable(title="Flow Executions")
    table.add_column("ID", style="cyan")
    table.add_column("Flow")
    table.add_column("Status")
    table.add_column("Started")
    table.add_column("Duration")

    for ex in executions:
        table.add_row(
            str(ex.get("id", ""))[:8],
            ex.get("flow_name", ""),
            ex.get("status", ""),
            str(ex.get("started_at", "-")),
            f"{ex['duration_ms']}ms" if ex.get("duration_ms") else "-",
        )

    console.print(table)
