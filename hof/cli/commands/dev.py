"""hof dev -- start the development server."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

app = typer.Typer()
console = Console()

ADMIN_UI_DIR = Path(__file__).resolve().parent.parent.parent / "ui" / "admin"
ADMIN_VITE_PORT = 5174


def _init_submodules(project_root: Path) -> None:
    """Initialize git submodules if a .gitmodules file exists.

    A no-op for projects without submodules. Ensures the design-system
    submodule (and any others) are populated before Vite tries to import them.
    """
    if not (project_root / ".gitmodules").is_file():
        return
    result = subprocess.run(
        ["git", "submodule", "update", "--init"],
        cwd=str(project_root),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        console.print(f"  [yellow]Warning: git submodule init failed:[/] {result.stderr.strip()}")


def _kill_port(port: int) -> None:
    """Kill any process currently listening on the given port.

    Uses lsof to find the PID(s) and sends SIGTERM. Silently skips if
    lsof is unavailable or no process is found.
    """
    result = subprocess.run(
        ["lsof", "-ti", f":{port}"],
        capture_output=True,
        text=True,
    )
    pids = result.stdout.strip()
    if not pids:
        return
    for pid_str in pids.splitlines():
        try:
            os.kill(int(pid_str), signal.SIGTERM)
        except (ProcessLookupError, ValueError):
            pass


def _docker_compose_up(project_root: Path) -> bool:
    """Start Docker Compose services if a docker-compose.yml exists.

    Returns True if compose was started, False if no compose file found.
    """
    compose_file = project_root / "docker-compose.yml"
    if not compose_file.is_file():
        return False
    console.print("  [cyan]Starting Docker services...[/]")
    result = subprocess.run(
        ["docker", "compose", "up", "-d", "--wait"],
        cwd=str(project_root),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        console.print(f"  [red]Docker Compose failed:[/] {result.stderr.strip()}")
        raise typer.Exit(1)
    console.print("  [green]Docker services ready.[/]")
    return True


def _docker_compose_down(project_root: Path) -> None:
    """Stop Docker Compose services if a docker-compose.yml exists."""
    compose_file = project_root / "docker-compose.yml"
    if not compose_file.is_file():
        return
    console.print("  [cyan]Stopping Docker services...[/]")
    subprocess.run(
        ["docker", "compose", "down"],
        cwd=str(project_root),
        capture_output=True,
    )


@app.callback(invoke_without_command=True)
def dev(
    port: int = typer.Option(8001, "--port", "-p", help="Server port."),
    host: str = typer.Option("0.0.0.0", "--host", help="Server host."),
    no_worker: bool = typer.Option(False, "--no-worker", help="Skip Celery worker."),
    no_ui: bool = typer.Option(False, "--no-ui", help="Skip Vite dev server."),
    reload: bool = typer.Option(True, "--reload/--no-reload", help="Auto-reload on changes."),
    fresh: bool = typer.Option(
        False, "--fresh", help="Wipe Docker volumes and start with a clean database."
    ),
) -> None:
    """Start all development services: FastAPI, Celery worker, Vite."""
    from hof.config import load_config

    project_root = Path.cwd()
    config = load_config(project_root)

    console.print(f"\n[bold green]hof dev[/] starting [bold]{config.app_name}[/]...\n")

    _init_submodules(project_root)

    if fresh:
        compose_file = project_root / "docker-compose.yml"
        if compose_file.is_file():
            console.print("  [yellow]Wiping Docker volumes for a fresh start...[/]")
            subprocess.run(
                ["docker", "compose", "down", "-v"],
                cwd=str(project_root),
                capture_output=True,
            )

    compose_started = _docker_compose_up(project_root)

    if compose_started:
        console.print("  [cyan]Running migrations...[/]")
        from hof.cli.commands import bootstrap

        bootstrap()
        from hof.config import get_config
        from hof.db.migrations import run_migrations

        run_migrations(project_root, get_config())
        console.print("  [green]Migrations complete.[/]")

    # Free up ports before starting — avoids "address already in use" errors
    # when restarting hof dev without a clean shutdown.
    from hof.ui.vite import USER_VITE_PORT

    for _port in (port, ADMIN_VITE_PORT, USER_VITE_PORT):
        _kill_port(_port)

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
            sys.executable,
            "-m",
            "uvicorn",
            "hof.api.server:create_app",
            "--factory",
            "--host",
            host,
            "--port",
            str(port),
        ]
        if reload:
            uvicorn_cmd.append("--reload")

        processes.append(subprocess.Popen(uvicorn_cmd, cwd=str(project_root), env=env))

        # Celery worker
        if not no_worker:
            celery_cmd = [
                sys.executable,
                "-m",
                "celery",
                "-A",
                "hof.tasks.celery_app:celery",
                "worker",
                "--loglevel=info",
                f"--concurrency={config.celery_concurrency}",
            ]
            processes.append(subprocess.Popen(celery_cmd, cwd=str(project_root), env=env))

            # Celery Beat for cron jobs
            beat_cmd = [
                sys.executable,
                "-m",
                "celery",
                "-A",
                "hof.tasks.celery_app:celery",
                "beat",
                "--loglevel=info",
            ]
            processes.append(subprocess.Popen(beat_cmd, cwd=str(project_root), env=env))

        display_host = "localhost" if host == "0.0.0.0" else host
        console.print()
        console.print("[bold green]All services started.[/] Press Ctrl+C to stop.\n")
        console.print(f"  [bold]App[/]        http://{display_host}:{port}/")
        console.print(f"  [bold]Admin UI[/]   http://{display_host}:{port}/admin/")
        console.print(f"  [bold]API docs[/]   http://{display_host}:{port}/docs")
        if user_vite_port:
            console.print(f"  [bold]User UI[/]    http://{display_host}:{port}/user-ui/")
        if config.admin_username:
            console.print(f"\n  [dim]Admin credentials: {config.admin_username} / ****[/]")
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
        if compose_started:
            _docker_compose_down(project_root)
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
    config: Any,
    processes: list[subprocess.Popen],
    env: dict[str, str],
) -> int:
    """Start the user UI Vite dev server. Returns the port, or 0 if skipped."""
    from hof.ui.vite import USER_VITE_PORT, ViteManager

    ui_dir = project_root / config.ui_dir
    has_components = (ui_dir / "components").is_dir()
    has_pages = any((ui_dir / "pages").glob("*.tsx")) if (ui_dir / "pages").is_dir() else False

    if not has_components and not has_pages:
        console.print("  [dim]No ui/components/ or ui/pages/, skipping user UI[/]")
        return 0

    manager = ViteManager(ui_dir, app_name=config.app_name, project_root=project_root)
    console.print(f"  [cyan]User UI[/]  (Vite) on port {USER_VITE_PORT}")
    proc = manager.start_dev_server(port=USER_VITE_PORT, env=env)
    if proc:
        processes.append(proc)
    return USER_VITE_PORT
