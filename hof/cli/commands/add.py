"""hof add -- add modules from hof-components into the current project."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer()
console = Console()

COMPONENTS_REPO = "git@github.com:jhoetter/hof-components.git"
CACHE_DIR = Path.home() / ".hof" / "components"


def _ensure_cache() -> None:
    """Clone or update the hof-components repo in the local cache."""
    if not CACHE_DIR.exists():
        console.print("[dim]Cloning hof-components...[/]")
        CACHE_DIR.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", COMPONENTS_REPO, str(CACHE_DIR)], check=True)
    else:
        console.print("[dim]Updating hof-components...[/]")
        subprocess.run(["git", "pull"], cwd=str(CACHE_DIR), check=True)


def _load_registry() -> dict:
    registry_path = CACHE_DIR / "registry.json"
    if not registry_path.exists():
        console.print("[red]registry.json not found in hof-components cache.[/]")
        raise typer.Exit(1)
    return json.loads(registry_path.read_text())


def _load_module_meta(module_path: Path) -> dict:
    meta_path = module_path / "module.json"
    if not meta_path.exists():
        console.print(f"[red]module.json not found at {module_path}[/]")
        raise typer.Exit(1)
    return json.loads(meta_path.read_text())


def _load_template_meta(template_path: Path) -> dict:
    meta_path = template_path / "template.json"
    if not meta_path.exists():
        console.print(f"[red]template.json not found at {template_path}[/]")
        raise typer.Exit(1)
    return json.loads(meta_path.read_text())


def _update_modules_json(project_root: Path, module_name: str, meta: dict, copied: list[str]) -> None:
    """Track installed module in .hof/modules.json."""
    hof_dir = project_root / ".hof"
    hof_dir.mkdir(exist_ok=True)

    modules_file = hof_dir / "modules.json"
    data: dict = {"installed_modules": {}}
    if modules_file.exists():
        data = json.loads(modules_file.read_text())

    data["installed_modules"][module_name] = {
        "version": meta.get("version", "unknown"),
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "files": copied,
    }

    modules_file.write_text(json.dumps(data, indent=2))


def _install_module(module_name: str, registry: dict, project_root: Path, force: bool) -> None:
    """Copy a module's files into the current project."""
    if module_name not in registry["modules"]:
        console.print(f"[red]Module '{module_name}' not found. Use --list to see available modules.[/]")
        raise typer.Exit(1)

    module_rel_path = registry["modules"][module_name]["path"]
    module_path = CACHE_DIR / module_rel_path
    meta = _load_module_meta(module_path)

    # Check module dependencies first
    dep_modules = meta.get("dependencies", {}).get("modules", [])
    if dep_modules:
        modules_file = project_root / ".hof" / "modules.json"
        installed: set[str] = set()
        if modules_file.exists():
            installed = set(json.loads(modules_file.read_text()).get("installed_modules", {}).keys())
        missing = [m for m in dep_modules if m not in installed]
        if missing:
            console.print(f"[yellow]Module '{module_name}' requires: {', '.join(missing)}[/]")
            console.print("Install them first with: " + " && ".join(f"hof add {m}" for m in missing))
            raise typer.Exit(1)

    copied: list[str] = []
    skipped: list[str] = []

    for dest_dir, files in meta.get("files", {}).items():
        for file_rel in files:
            src = module_path / file_rel
            dst = project_root / file_rel
            if dst.exists() and not force:
                skipped.append(file_rel)
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied.append(file_rel)

            # Ensure __init__.py exists for Python package dirs
            if dst.suffix == ".py":
                init = dst.parent / "__init__.py"
                if not init.exists():
                    init.touch()

    for f in copied:
        console.print(f"  [green]+ {f}[/]")
    for f in skipped:
        console.print(f"  [yellow]~ {f} (exists, skipped — use --force to overwrite)[/]")

    if not copied and not skipped:
        console.print("[yellow]No files to install.[/]")

    # Pip dependencies
    pip_deps = meta.get("dependencies", {}).get("pip", [])
    if pip_deps:
        console.print("\n[bold]Add to pyproject.toml dependencies:[/]")
        for dep in pip_deps:
            console.print(f"  {dep}")

    # npm dependencies
    npm_deps = meta.get("dependencies", {}).get("npm", [])
    if npm_deps:
        console.print("\n[bold]Add to ui/package.json dependencies:[/]")
        for dep in npm_deps:
            console.print(f"  {dep}")

    # Env vars
    env_vars = meta.get("env_vars", [])
    if env_vars:
        env_file = project_root / ".env"
        existing_env = env_file.read_text() if env_file.exists() else ""
        additions: list[str] = []
        for var in env_vars:
            if var["name"] not in existing_env:
                additions.append(f'# {var["description"]}\n{var["name"]}=\n')
        if additions:
            with open(env_file, "a") as f:
                f.write("\n" + "\n".join(additions))
            console.print("\n[bold]Added env vars to .env (fill in values):[/]")
            for var in env_vars:
                if var["name"] not in existing_env:
                    req = " (required)" if var.get("required") else ""
                    console.print(f"  {var['name']}{req} — {var['description']}")

    # Track in .hof/modules.json
    all_files = copied + skipped
    if all_files:
        _update_modules_json(project_root, module_name, meta, all_files)

    # Post-install notes
    notes = meta.get("post_install_notes")
    if notes:
        console.print(f"\n[bold cyan]Note:[/] {notes}")

    console.print(f"\n[green bold]✓ Module '{module_name}' installed.[/]")


@app.callback(invoke_without_command=True)
def add(
    ctx: typer.Context,
    module_name: str = typer.Argument(None, help="Module name to add."),
    list_modules: bool = typer.Option(False, "--list", "-l", help="List available modules and templates."),
    template: str = typer.Option(None, "--template", "-t", help="Scaffold a project from a template."),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing files."),
) -> None:
    """Add modules or templates from hof-components into the current project."""
    if ctx.invoked_subcommand is not None:
        return

    _ensure_cache()
    registry = _load_registry()

    if list_modules:
        _print_list(registry)
        return

    if template:
        _install_template(template, registry, Path.cwd(), force)
        return

    if not module_name:
        console.print("[red]Provide a module name, --list, or --template <name>.[/]")
        raise typer.Exit(1)

    _install_module(module_name, registry, Path.cwd(), force)


def _print_list(registry: dict) -> None:
    """Print all available modules and templates."""
    modules = registry.get("modules", {})
    templates = registry.get("templates", {})

    if modules:
        t = Table(title="Available Modules", show_header=True, header_style="bold")
        t.add_column("Name", style="cyan")
        t.add_column("Description")
        for name, info in modules.items():
            t.add_row(name, info.get("description", ""))
        console.print(t)

    if templates:
        t = Table(title="Available Templates", show_header=True, header_style="bold")
        t.add_column("Name", style="cyan")
        t.add_column("Description")
        for name, info in templates.items():
            t.add_row(name, info.get("description", ""))
        console.print(t)

    if not modules and not templates:
        console.print("[yellow]No modules or templates found in registry.[/]")


def _install_template(template_name: str, registry: dict, project_root: Path, force: bool) -> None:
    """Scaffold a project from a template (installs all its modules)."""
    if template_name not in registry.get("templates", {}):
        console.print(f"[red]Template '{template_name}' not found. Use --list to see available templates.[/]")
        raise typer.Exit(1)

    template_rel_path = registry["templates"][template_name]["path"]
    template_path = CACHE_DIR / template_rel_path
    meta = _load_template_meta(template_path)

    console.print(f"[bold]Installing template:[/] {template_name}")
    if meta.get("description"):
        console.print(f"  {meta['description']}\n")

    # Copy any template-level files (hof.config.py, etc.)
    for src_file in template_path.iterdir():
        if src_file.name in ("template.json",):
            continue
        if src_file.is_file():
            dst = project_root / src_file.name
            if dst.exists() and not force:
                console.print(f"  [yellow]~ {src_file.name} (exists, skipped)[/]")
            else:
                shutil.copy2(src_file, dst)
                console.print(f"  [green]+ {src_file.name}[/]")

    # Install each module referenced by the template
    for module_name in meta.get("modules", []):
        console.print(f"\n[bold]Installing module:[/] {module_name}")
        _install_module(module_name, registry, project_root, force)

    notes = meta.get("post_install_notes")
    if notes:
        console.print(f"\n[bold cyan]Note:[/] {notes}")

    console.print(f"\n[green bold]✓ Template '{template_name}' installed.[/]")
