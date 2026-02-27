"""hof new -- scaffold new components."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer()
console = Console()

TEMPLATES = {
    "table": (
        "tables/{name}.py",
        '''from hof import Table, Column, types


class {class_name}(Table):
    name = Column(types.String, required=True)
    created_at = Column(types.DateTime, auto_now=True)
''',
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
        '''interface {class_name}Props {{
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
''',
    ),
    "page": (
        "ui/pages/{name}.tsx",
        '''export default function {class_name}Page() {{
  return (
    <div>
      <h1>{class_name}</h1>
      {{/* TODO: Implement page */}}
    </div>
  );
}}
''',
    ),
}

PROJECT_FILES = {
    "pyrightconfig.json": '''{
  "pythonPath": "/opt/anaconda3/bin/python3",
  "typeCheckingMode": "basic",
  "reportMissingImports": "none"
}
''',
    "hof.config.py": '''from hof import Config

config = Config(
    app_name="{name}",
    database_url="${{DATABASE_URL}}",
    redis_url="${{REDIS_URL}}",
    admin_username="admin",
    admin_password="${{HOF_ADMIN_PASSWORD}}",
)
''',
    "pyproject.toml": '''[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "{name}"
version = "0.1.0"
requires-python = ">=3.11"

dependencies = [
    "hof-engine>=0.1.0",
]

[tool.hatch.build.targets.wheel]
packages = ["."]
''',
    "Dockerfile": '''FROM python:3.11-slim

RUN apt-get update && apt-get install -y curl && \\
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \\
    apt-get install -y nodejs && \\
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml .
RUN pip install .

COPY . .
RUN cd ui && npm install && npx vite build

EXPOSE 8000
CMD ["hof", "dev", "--host", "0.0.0.0", "--port", "8000"]
''',
    "docker-compose.yml": '''services:
  app:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      - db
      - redis

  db:
    image: postgres:16
    volumes:
      - pgdata:/var/lib/postgresql/data
    environment:
      POSTGRES_DB: ${{DB_NAME}}
      POSTGRES_PASSWORD: ${{DB_PASSWORD}}

  redis:
    image: redis:7-alpine

  worker:
    build: .
    command: celery -A hof.tasks.worker worker --loglevel=info
    env_file: .env
    depends_on:
      - db
      - redis

volumes:
  pgdata:
''',
    ".github/workflows/deploy.yml": '''name: Deploy

on:
  push:
    branches: ["main"]

jobs:
  deploy:
    name: Deploy to Hetzner
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Deploy via SSH
        uses: appleboy/ssh-action@v1
        with:
          host: ${{{{ secrets.HETZNER_HOST }}}}
          username: ${{{{ secrets.HETZNER_USER }}}}
          key: ${{{{ secrets.HETZNER_SSH_KEY }}}}
          script: |
            cd /opt/{name}
            git pull
            docker compose pull
            docker compose up -d --build
            docker compose exec app hof db migrate
''',
}

PROJECT_DIRS = ["tables", "functions", "flows", "cron", "ui/components", "ui/pages", ".github/workflows"]


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

    for dirname in PROJECT_DIRS:
        (project_dir / dirname).mkdir(parents=True, exist_ok=True)
        parts = dirname.split("/")
        for i in range(len(parts)):
            init_path = project_dir / "/".join(parts[: i + 1]) / "__init__.py"
            non_python = dirname.startswith("ui") or dirname.startswith(".")
            if not init_path.exists() and not non_python:
                init_path.touch()

    for filename, template in PROJECT_FILES.items():
        (project_dir / filename).write_text(template.format(name=name))

    (project_dir / ".env").write_text(
        "# Environment variables\n"
        "DATABASE_URL=postgresql://localhost:5432/{name}\n"
        "REDIS_URL=redis://localhost:6379/0\n"
        "HOF_ADMIN_PASSWORD=changeme\n"
        "DB_NAME={name}\n"
        "DB_PASSWORD=changeme\n".format(name=name)
    )

    console.print(f"[green]Created project:[/] {name}/")
    console.print(f"  cd {name}")
    console.print("  hof db migrate")
    console.print("  hof dev")
    console.print("")
    console.print("[dim]To add modules:  hof add --list[/]")
    console.print("[dim]To deploy:       docker compose up[/]")


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
