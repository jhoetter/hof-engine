"""hof new -- scaffold new components.

The ``get_project_files`` function is the **single source of truth** for the
file layout of a new hof project.  It is used by both the ``hof new project``
CLI command (writes to local disk) and by hof-os (pushes to GitHub via the
Trees API).  Importable from ``hof.scaffold``.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer()
console = Console()

TEMPLATES = {
    "table": (
        "tables/{name}.py",
        """from hof import Table, Column, types


class {class_name}(Table):
    name = Column(types.String, required=True)
    created_at = Column(types.DateTime, auto_now=True)
""",
    ),
    "function": (
        "functions/{name}.py",
        '''from hof import function


@function
def {name}() -> dict:
    """TODO: Add description."""
    return {{"ok": True}}
''',
    ),
    "flow": (
        "flows/{name}.py",
        '''from hof import Flow

{name} = Flow("{name}")


@{name}.node
def first_step(input_data: str) -> dict:
    """TODO: Implement first step."""
    return {{"result": input_data}}
''',
    ),
    "cron": (
        "cron/{name}.py",
        '''from hof import cron


@cron("0 * * * *")
def {name}():
    """TODO: Implement scheduled task. Runs every hour."""
    pass
''',
    ),
    "component": (
        "ui/components/{class_name}.tsx",
        """interface {class_name}Props {{
  onComplete?: (result: unknown) => void;
}}

export function {class_name}({{ onComplete }}: {class_name}Props) {{
  return (
    <div>
      <h2>{class_name}</h2>
      {{/* TODO: Implement component */}}
    </div>
  );
}}
""",
    ),
    "page": (
        "ui/pages/{name}.tsx",
        """export default function {class_name}Page() {{
  return (
    <div>
      <h1>{class_name}</h1>
      {{/* TODO: Implement page */}}
    </div>
  );
}}
""",
    ),
}

_PROJECT_FILES = {
    ".dockerignore": """__pycache__
*.pyc
.git
ui/node_modules
celerybeat-schedule.db
.env.local
.env.*.local
""",
    "pyrightconfig.json": """{
  "pythonPath": "/opt/anaconda3/bin/python3",
  "typeCheckingMode": "basic",
  "reportMissingImports": "none"
}
""",
    "hof.config.py": """from hof import Config

config = Config(
    app_name="{name}",
    database_url="${DATABASE_URL}",
    redis_url="${REDIS_URL}",
    admin_username="admin",
    admin_password="${HOF_ADMIN_PASSWORD}",
)
""",
    "pyproject.toml": """[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "{slug}"
version = "0.1.0"
requires-python = ">=3.11"

dependencies = [
    "hof-engine>=0.1.0",
]

[tool.hatch.build.targets.wheel]
packages = ["."]
""",
    "Dockerfile": """FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl git && \\
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \\
    apt-get install -y nodejs && \\
    rm -rf /var/lib/apt/lists/*

ARG GITHUB_TOKEN
RUN pip install "hof-engine @ git+https://${GITHUB_TOKEN}@github.com/jhoetter/hof-engine.git"

WORKDIR /app
COPY pyproject.toml .
RUN pip install .

COPY . .
RUN python -c "from pathlib import Path; from hof.config import load_config; \\
    from hof.ui.vite import ViteManager; c = load_config(Path('.'), strict=False); \\
    ViteManager(Path(c.ui_dir), app_name=c.app_name, project_root=Path('.')).build()"

EXPOSE 8001
CMD ["sh", "-c", "hof db migrate && \\
    python -m uvicorn hof.api.server:create_app \\
    --factory --host 0.0.0.0 --port 8001"]
""",
    "docker-compose.yml": """# Local development — start Postgres + Redis,
# then run "hof dev" on the host.
# Production deployment is handled by hof-os (generates its own compose file).
# Ports are offset from hof-os (5432/6379) to avoid conflicts.
services:
  db:
    image: postgres:16
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5433:5432"
    environment:
      POSTGRES_DB: ${DB_NAME}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 2s
      timeout: 5s
      retries: 10

  redis:
    image: redis:7-alpine
    ports:
      - "6380:6379"

volumes:
  pgdata:
""",
}

_PROJECT_DIRS = ["tables", "functions", "flows", "cron", "ui/components", "ui/pages"]

_APP_CSS = """\
@import "tailwindcss";

body {
  color: var(--foreground);
  background-color: var(--background);
  font-family: var(--font-sans);
  -webkit-font-smoothing: antialiased;
  line-height: 1.6;
}
"""

_ENV_TEMPLATE = (
    "# Environment variables — used for local dev outside Docker.\n"
    "# Inside Docker, DATABASE_URL and REDIS_URL are overridden by docker-compose.yml.\n"
    "# Ports offset from hof-os (5432/6379) so both can run simultaneously.\n"
    "DATABASE_URL=postgresql://postgres:changeme@localhost:5433/{slug}\n"
    "REDIS_URL=redis://localhost:6380/0\n"
    "HOF_ADMIN_PASSWORD=changeme\n"
    "DB_NAME={slug}\n"
    "DB_PASSWORD=changeme\n"
)


# ---------------------------------------------------------------------------
# Public API — single source of truth for project file layout
# ---------------------------------------------------------------------------


def _to_slug(name: str) -> str:
    """Convert a project name to a valid Python package / DB-safe slug."""
    import re

    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def get_project_files(name: str, *, slug: str | None = None) -> dict[str, str]:
    """Return ``{relative_path: content}`` for a new hof project.

    *name* is the human-readable project name (used in hof.config.py and the
    index page heading).  *slug* is the machine-safe identifier used for the
    Python package name, database name, and env vars.  If omitted it is derived
    from *name*.

    This is the **single source of truth** for the file structure of a hof
    project.  Used by ``hof new project`` (local) and by hof-os (remote push
    via the GitHub Trees API).
    """
    if slug is None:
        slug = _to_slug(name)

    files: dict[str, str] = {}

    for filename, template in _PROJECT_FILES.items():
        files[filename] = template.replace("{name}", name).replace("{slug}", slug)

    files[".env"] = _ENV_TEMPLATE.replace("{slug}", slug)
    files["ui/app.css"] = _APP_CSS

    for dirname in _PROJECT_DIRS:
        parts = dirname.split("/")
        for i in range(len(parts)):
            sub = "/".join(parts[: i + 1])
            non_python = sub.startswith("ui") or sub.startswith(".")
            if not non_python:
                files[f"{sub}/__init__.py"] = ""
        if dirname.startswith("ui"):
            files[f"{dirname}/.gitkeep"] = ""

    return files


@app.command("project")
def new_project(
    name: str = typer.Argument(help="Project name."),
) -> None:
    """Create a new hof project."""
    project_dir = Path.cwd() / name

    if project_dir.exists():
        console.print(f"[red]Directory '{name}' already exists.[/]")
        raise typer.Exit(1)

    project_dir.mkdir(parents=True)

    for rel_path, content in get_project_files(name).items():
        full_path = project_dir / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)

    console.print(f"[green]Created project:[/] {name}/")
    console.print(f"  cd {name}")
    console.print("  hof db migrate")
    console.print("  hof dev")
    console.print("")
    console.print("[dim]To add modules:        hof add --list[/]")
    console.print(
        "[dim]To add design system:  (via hof-os) add git submodule at ./design-system/[/]"
    )
    console.print("[dim]Local dev:             docker compose up[/]")


@app.command("table")
def new_table(name: str = typer.Argument(help="Table name.")) -> None:
    """Scaffold a new table."""
    _scaffold("table", name)


@app.command("function")
def new_function(name: str = typer.Argument(help="Function name.")) -> None:
    """Scaffold a new function."""
    _scaffold("function", name)


@app.command("flow")
def new_flow(name: str = typer.Argument(help="Flow name.")) -> None:
    """Scaffold a new flow."""
    _scaffold("flow", name)


@app.command("cron")
def new_cron(name: str = typer.Argument(help="Cron job name.")) -> None:
    """Scaffold a new cron job."""
    _scaffold("cron", name)


@app.command("component")
def new_component(name: str = typer.Argument(help="Component name.")) -> None:
    """Scaffold a new React component."""
    _scaffold("component", name)


@app.command("page")
def new_page(name: str = typer.Argument(help="Page name.")) -> None:
    """Scaffold a new React page."""
    _scaffold("page", name)


def _scaffold(kind: str, name: str) -> None:
    path_template, content_template = TEMPLATES[kind]
    class_name = name.replace("_", " ").title().replace(" ", "")

    rel_path = path_template.format(name=name, class_name=class_name)
    full_path = Path.cwd() / rel_path

    if full_path.exists():
        console.print(f"[red]File already exists: {rel_path}[/]")
        raise typer.Exit(1)

    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content_template.format(name=name, class_name=class_name))
    console.print(f"[green]Created:[/] {rel_path}")
