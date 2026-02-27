"""hof dev -- start the development server."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer()
console = Console()

ADMIN_UI_DIR = Path(__file__).resolve().parent.parent.parent / "ui" / "admin"
ADMIN_VITE_PORT = 5174


@app.callback(invoke_without_command=True)
def dev(
    port: int = typer.Option(8001, "--port", "-p", help="Server port."),
    host: str = typer.Option("0.0.0.0", "--host", help="Server host."),
    no_worker: bool = typer.Option(False, "--no-worker", help="Skip Celery worker."),
    no_ui: bool = typer.Option(False, "--no-ui", help="Skip Vite dev server."),
    reload: bool = typer.Option(True, "--reload/--no-reload", help="Auto-reload on changes."),
) -> None:
    """Start all development services: FastAPI, Celery worker, Vite."""
    from hof.config import load_config

    project_root = Path.cwd()
    config = load_config(project_root)

    console.print(f"\n[bold green]hof dev[/] starting [bold]{config.app_name}[/]...\n")

    processes: list[subprocess.Popen] = []
    env = {**os.environ, "HOF_ADMIN_VITE_PORT": str(ADMIN_VITE_PORT)}

    try:
        # Admin UI Vite dev server
        _start_admin_vite(processes, env)

        # User UI Vite dev server
        user_vite_port = 0
        if not no_ui:
            user_vite_port = _start_user_vite(project_root, config, processes, env)
            if user_vite_port:
                env["HOF_USER_VITE_PORT"] = str(user_vite_port)

        # FastAPI server
        uvicorn_cmd = [
            sys.executable, "-m", "uvicorn",
            "hof.api.server:create_app",
            "--factory",
            "--host", host,
            "--port", str(port),
        ]
        if reload:
            uvicorn_cmd.append("--reload")

        processes.append(subprocess.Popen(uvicorn_cmd, cwd=str(project_root), env=env))

        # Celery worker
        if not no_worker:
            celery_cmd = [
                sys.executable, "-m", "celery",
                "-A", "hof.tasks.celery_app:celery",
                "worker",
                "--loglevel=info",
                f"--concurrency={config.celery_concurrency}",
            ]
            processes.append(subprocess.Popen(celery_cmd, cwd=str(project_root), env=env))

            # Celery Beat for cron jobs
            beat_cmd = [
                sys.executable, "-m", "celery",
                "-A", "hof.tasks.celery_app:celery",
                "beat",
                "--loglevel=info",
            ]
            processes.append(subprocess.Popen(beat_cmd, cwd=str(project_root), env=env))

        display_host = "localhost" if host == "0.0.0.0" else host
        console.print()
        console.print("[bold green]All services started.[/] Press Ctrl+C to stop.\n")
        console.print(f"  [bold]API[/]        http://{display_host}:{port}/api/health")
        console.print(f"  [bold]Admin UI[/]   http://{display_host}:{port}/admin/")
        console.print(f"  [bold]API docs[/]   http://{display_host}:{port}/docs")
        if config.admin_username:
            console.print(
                f"\n  [dim]Admin credentials: {config.admin_username} / ****[/]"
            )
        console.print()

        for p in processes:
            p.wait()

    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down...[/]")
        for p in processes:
            p.send_signal(signal.SIGTERM)
        for p in processes:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        console.print("[green]Stopped.[/]")


def _start_admin_vite(
    processes: list[subprocess.Popen],
    env: dict[str, str],
) -> None:
    """Install deps if needed and start the admin UI Vite dev server."""
    if not ADMIN_UI_DIR.is_dir():
        console.print("  [dim]Admin UI directory not found, skipping[/]")
        return

    node_modules = ADMIN_UI_DIR / "node_modules"
    if not node_modules.is_dir():
        console.print("  [cyan]Installing admin UI dependencies...[/]")
        subprocess.run(
            ["npm", "install"],
            cwd=str(ADMIN_UI_DIR),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    console.print(f"  [cyan]Admin UI[/] (Vite) on port {ADMIN_VITE_PORT}")
    processes.append(
        subprocess.Popen(
            ["npx", "vite", "--port", str(ADMIN_VITE_PORT), "--strictPort"],
            cwd=str(ADMIN_UI_DIR),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    )


def _start_user_vite(
    project_root: Path,
    config: "Any",
    processes: list[subprocess.Popen],
    env: dict[str, str],
) -> int:
    """Start the user UI Vite dev server. Returns the port, or 0 if skipped."""
    from hof.ui.vite import ViteManager, USER_VITE_PORT

    ui_dir = project_root / config.ui_dir
    components_dir = ui_dir / "components"

    if not components_dir.is_dir():
        console.print("  [dim]No ui/components/ directory, skipping user UI[/]")
        return 0

    manager = ViteManager(ui_dir)
    console.print(f"  [cyan]User UI[/]  (Vite) on port {USER_VITE_PORT}")
    proc = manager.start_dev_server(port=USER_VITE_PORT, env=env)
    if proc:
        processes.append(proc)
    return USER_VITE_PORT
