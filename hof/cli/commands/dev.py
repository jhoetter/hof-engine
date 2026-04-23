"""hof dev -- start the development server."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from shutil import which
from typing import Any
from urllib.parse import urlparse

import typer
from rich.console import Console

app = typer.Typer()
console = Console()

ADMIN_UI_DIR = Path(__file__).resolve().parent.parent.parent / "ui" / "admin"
ADMIN_VITE_PORT = 5174

SERVICE_WAIT_TIMEOUT = 120.0
SERVICE_WAIT_INTERVAL = 0.5


def _uvicorn_reload_exclude_args(project_root: Path, ui_dir: str) -> list[str]:
    """Paths for ``uvicorn --reload-exclude``.

    Prevents churn under venv/node_modules from restarting the API.

    The default reload filter watches ``*.py``; without excluding these trees, edits to
    ``site-packages`` or ``node_modules`` (some packages ship ``.py`` files) spam reloads.
    """
    args: list[str] = []
    candidates = (
        project_root / ".venv",
        project_root / "venv",
        project_root / ui_dir / "node_modules",
        project_root / "node_modules",
    )
    for candidate in candidates:
        if candidate.is_dir():
            args.extend(["--reload-exclude", str(candidate.resolve())])
    return args


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


def _compose_file(project_root: Path) -> Path | None:
    for name in ("docker-compose.yml", "compose.yaml", "compose.yml"):
        candidate = project_root / name
        if candidate.is_file():
            return candidate
    return None


def _docker_compose_prefix() -> list[str]:
    try:
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if result.returncode == 0:
            return ["docker", "compose"]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return ["docker-compose"]


def _docker_compose_cmd(project_root: Path, compose_file: Path, *args: str) -> list[str]:
    return [*_docker_compose_prefix(), "-f", str(compose_file), *args]


def _docker_compose_up(project_root: Path) -> bool:
    """Start Docker Compose services if a compose file exists."""
    compose_file = _compose_file(project_root)
    if compose_file is None:
        return False
    console.print("  [cyan]Starting Docker services...[/]")
    prefix_cmd = _docker_compose_cmd(project_root, compose_file, "up", "-d", "--wait")
    result = subprocess.run(
        prefix_cmd,
        cwd=str(project_root),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Older Docker Compose builds may not support --wait.
        fallback = _docker_compose_cmd(project_root, compose_file, "up", "-d")
        result = subprocess.run(
            fallback,
            cwd=str(project_root),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            console.print(f"  [red]Docker Compose failed:[/] {err}")
            raise typer.Exit(1)
    console.print("  [green]Docker services started.[/]")
    return True


def _docker_compose_down(project_root: Path, *, volumes: bool = False) -> None:
    compose_file = _compose_file(project_root)
    if compose_file is None:
        return
    console.print("  [cyan]Stopping Docker services...[/]")
    args = ["down"]
    if volumes:
        args.append("-v")
    cmd = _docker_compose_cmd(project_root, compose_file, *args)
    subprocess.run(cmd, cwd=str(project_root), capture_output=True)


def _parse_host_port(url: str, default_port: int) -> tuple[str, int]:
    """Return (host, port) from a database or redis URL."""
    normalized = url.replace("postgresql+asyncpg", "postgresql")
    parsed = urlparse(normalized)
    host = parsed.hostname or "localhost"
    port = parsed.port or default_port
    return host, port


def _wait_tcp_open(host: str, port: int, *, deadline: float) -> bool:
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2.0):
                return True
        except OSError:
            time.sleep(SERVICE_WAIT_INTERVAL)
    return False


def _wait_for_db_and_redis(config: Any) -> None:
    """Block until Postgres and Redis accept TCP connections (local dev)."""
    db_host, db_port = _parse_host_port(config.database_url, 5432)
    redis_host, redis_port = _parse_host_port(config.redis_url, 6379)

    deadline = time.monotonic() + SERVICE_WAIT_TIMEOUT
    console.print("  [cyan]Waiting for Postgres and Redis...[/]")

    if not _wait_tcp_open(db_host, db_port, deadline=deadline):
        console.print(
            f"  [red]Postgres not reachable at {db_host}:{db_port} "
            f"within {int(SERVICE_WAIT_TIMEOUT)}s.[/]"
        )
        raise typer.Exit(1)

    deadline = time.monotonic() + SERVICE_WAIT_TIMEOUT
    if not _wait_tcp_open(redis_host, redis_port, deadline=deadline):
        console.print(
            f"  [red]Redis not reachable at {redis_host}:{redis_port} "
            f"within {int(SERVICE_WAIT_TIMEOUT)}s.[/]"
        )
        raise typer.Exit(1)

    console.print("  [green]Postgres and Redis are ready.[/]")


def _install_project_dependencies(project_root: Path) -> None:
    """On --fresh, sync Python and UI dependencies when tooling is available."""
    if (project_root / "pyproject.toml").is_file():
        uv_bin = which("uv")
        if uv_bin:
            console.print("  [cyan]Running uv sync...[/]")
            subprocess.run(
                [uv_bin, "sync"],
                cwd=str(project_root),
                check=False,
            )
    ui = project_root / "ui"
    if (ui / "package-lock.json").is_file():
        console.print("  [cyan]Running npm ci in ui/...[/]")
        subprocess.run(
            ["npm", "ci"],
            cwd=str(ui),
            check=False,
        )
    elif (ui / "package.json").is_file():
        console.print("  [cyan]Running npm install in ui/...[/]")
        subprocess.run(
            ["npm", "install"],
            cwd=str(ui),
            check=False,
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
    from hof.config import find_project_root, load_config

    found = find_project_root()
    if found is None:
        console.print(
            "[red]Could not find hof.config.py — run [bold]hof dev[/] from your project "
            "root (or a subdirectory).[/]"
        )
        raise typer.Exit(1)

    project_root = found
    os.chdir(project_root)

    config = load_config(project_root)

    console.print(f"\n[bold green]hof dev[/] starting [bold]{config.app_name}[/]...\n")

    _init_submodules(project_root)

    if fresh:
        _docker_compose_down(project_root, volumes=True)

    compose_started = _docker_compose_up(project_root)

    _wait_for_db_and_redis(config)

    if fresh:
        _install_project_dependencies(project_root)

    has_migrations = (project_root / "migrations" / "env.py").is_file()
    if compose_started or has_migrations:
        console.print("  [cyan]Running migrations...[/]")
        from hof.cli.commands import bootstrap

        bootstrap(project_root)
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
    env = {
        **os.environ,
        "HOF_ADMIN_VITE_PORT": str(ADMIN_VITE_PORT),
        "HOF_PROJECT_ROOT": str(project_root),
    }

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
            # Cap graceful shutdown so a stuck WebSocket can never block a
            # reload (the bare-/ws reconnect storm pattern would otherwise
            # wedge `--reload` indefinitely; observed on hof-os data-app).
            "--timeout-graceful-shutdown",
            "5",
        ]
        if reload:
            uvicorn_cmd.append("--reload")
            uvicorn_cmd.extend(_uvicorn_reload_exclude_args(project_root, config.ui_dir))

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
    # See `hof.ui.vite.ViteManager.start_dev_server` for the rationale:
    # silence stdout (noisy progress) but keep stderr on the dev
    # terminal so resolve / config / plugin errors don't get swallowed
    # and surface as a confusing 503 from the host FastAPI proxy.
    processes.append(
        subprocess.Popen(
            ["npx", "vite", "--port", str(ADMIN_VITE_PORT), "--strictPort"],
            cwd=str(ADMIN_UI_DIR),
            env=env,
            stdout=subprocess.DEVNULL,
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
