"""hof add -- add modules from hof-components into the current project."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer()
console = Console()

COMPONENTS_MANIFEST_RAW_URL = (
    "https://raw.githubusercontent.com/jhoetter/hof-engine/main/hof/components-manifest.json"
)
COMPONENTS_REPO_FALLBACK = "https://github.com/jhoetter/hof-components.git"
CACHE_DIR = Path.home() / ".hof" / "components"
# Look for manifest inside the installed hof package first (ships with the wheel).
MANIFEST_CANDIDATE_PATHS = (Path(__file__).resolve().parents[2] / "components-manifest.json",)


class ArtifactResolution(NamedTuple):
    url: str
    sha256: str | None
    source: str


def _parse_semver(version: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version.strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _read_manifest_from_disk() -> dict | None:
    for path in MANIFEST_CANDIDATE_PATHS:
        if not path.exists():
            continue
        try:
            return json.loads(path.read_text())
        except Exception as exc:
            console.print(f"[yellow]Could not parse components manifest at {path}: {exc}[/]")
            return None
    return None


def _read_manifest_from_url() -> dict | None:
    try:
        with urllib.request.urlopen(COMPONENTS_MANIFEST_RAW_URL) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def _load_components_manifest() -> dict | None:
    return _read_manifest_from_url() or _read_manifest_from_disk()


def _resolve_artifact_from_manifest(
    manifest: dict, engine_version: str
) -> ArtifactResolution | None:
    artifacts = manifest.get("artifacts", [])
    if not isinstance(artifacts, list):
        return None

    # Exact engine version match wins.
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        if artifact.get("engine_version") == engine_version and artifact.get("artifact_url"):
            return ArtifactResolution(
                url=str(artifact["artifact_url"]),
                sha256=artifact.get("sha256"),
                source=f"manifest exact ({engine_version})",
            )

    engine_semver = _parse_semver(engine_version)
    if not engine_semver:
        return None

    # Otherwise use latest artifact from the same major.minor line.
    same_minor: list[tuple[tuple[int, int, int], dict]] = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        artifact_version = artifact.get("engine_version")
        artifact_url = artifact.get("artifact_url")
        if not isinstance(artifact_version, str) or not artifact_url:
            continue
        parsed = _parse_semver(artifact_version)
        if not parsed:
            continue
        if parsed[0] == engine_semver[0] and parsed[1] == engine_semver[1]:
            same_minor.append((parsed, artifact))

    if not same_minor:
        return None

    same_minor.sort(key=lambda item: item[0], reverse=True)
    chosen = same_minor[0][1]
    return ArtifactResolution(
        url=str(chosen["artifact_url"]),
        sha256=chosen.get("sha256"),
        source=f"manifest compatible ({engine_semver[0]}.{engine_semver[1]}.x)",
    )


def _resolve_artifact() -> ArtifactResolution:
    override_url = os.getenv("HOF_COMPONENTS_URL")
    if override_url:
        return ArtifactResolution(url=override_url, sha256=None, source="env override")

    from hof import __version__ as engine_version

    manifest = _load_components_manifest()
    if manifest is not None:
        resolved = _resolve_artifact_from_manifest(manifest, engine_version)
        if resolved:
            return resolved
        console.print(
            f"[red]No compatible components artifact found for hof-engine {engine_version}. "
            "Update hof/components-manifest.json in hof-engine.[/]"
        )
        raise typer.Exit(1)

    console.print(
        "[red]Components manifest unavailable and no HOF_COMPONENTS_URL override was provided.[/]"
    )
    raise typer.Exit(1)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_archive_checksum(path: Path, expected_sha256: str | None) -> None:
    if not expected_sha256:
        return
    actual = _file_sha256(path)
    if actual.lower() != expected_sha256.lower():
        raise ValueError(
            f"Checksum mismatch for components artifact (expected {expected_sha256}, got {actual})"
        )


def _safe_tar_members(tar: tarfile.TarFile, destination: Path) -> list[tarfile.TarInfo]:
    """Filter tar members, rejecting path traversal, absolute paths, and links."""
    safe: list[tarfile.TarInfo] = []
    for member in tar.getmembers():
        if member.issym():
            raise tarfile.TarError(f"Symlinks are not allowed: {member.name}")
        resolved = (destination / member.name).resolve()
        if not str(resolved).startswith(str(destination.resolve())):
            raise tarfile.TarError(f"Unsafe path: {member.name}")
        safe.append(member)
    return safe


def _ensure_cache() -> None:
    """Populate the components cache from a local path, artifact download, or git clone.

    When ``HOF_COMPONENTS_PATH`` is set, the cache is symlinked to that local
    directory — no download, no tarball.  This is the fastest path for local
    development (see ``make dev-components`` in hof-os).
    """
    local_path = os.getenv("HOF_COMPONENTS_PATH")
    if local_path:
        src = Path(local_path).expanduser().resolve()
        if not src.is_dir() or not (src / "registry.json").exists():
            console.print(
                f"[red]HOF_COMPONENTS_PATH={local_path} is not a valid components directory.[/]"
            )
            raise typer.Exit(1)
        if CACHE_DIR.is_symlink() and CACHE_DIR.resolve() == src:
            console.print(f"[dim]Using local components: {src}[/]")
            return
        if CACHE_DIR.exists() or CACHE_DIR.is_symlink():
            if CACHE_DIR.is_symlink():
                CACHE_DIR.unlink()
            else:
                shutil.rmtree(CACHE_DIR)
        CACHE_DIR.parent.mkdir(parents=True, exist_ok=True)
        CACHE_DIR.symlink_to(src)
        console.print(f"[green]Linked components cache → {src}[/]")
        return

    artifact = _resolve_artifact()
    if CACHE_DIR.is_symlink():
        CACHE_DIR.unlink()
    if CACHE_DIR.exists():
        console.print("[dim]Updating hof-components...[/]")
    else:
        console.print("[dim]Downloading hof-components...[/]")
        CACHE_DIR.parent.mkdir(parents=True, exist_ok=True)

    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            tmp_name = tmp.name
        urllib.request.urlretrieve(artifact.url, tmp_name)
        _verify_archive_checksum(Path(tmp_name), artifact.sha256)
        if CACHE_DIR.exists():
            shutil.rmtree(CACHE_DIR)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tmp_name, "r:gz") as tar:
            members = _safe_tar_members(tar, CACHE_DIR)
            tar.extractall(path=CACHE_DIR, members=members)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    except Exception:
        console.print(
            f"[dim]Artifact download from {artifact.source} failed, falling back to git clone...[/]"
        )
        if not CACHE_DIR.exists():
            subprocess.run(["git", "clone", COMPONENTS_REPO_FALLBACK, str(CACHE_DIR)], check=True)
        else:
            subprocess.run(["git", "pull"], cwd=str(CACHE_DIR), check=True)
    finally:
        if tmp_name:
            Path(tmp_name).unlink(missing_ok=True)


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


def _update_modules_json(
    project_root: Path, module_name: str, meta: dict, copied: list[str]
) -> None:
    """Track installed module in hof-modules.json (project root, committed to git).

    Also maintains the legacy .hof/modules.json for backward compatibility with
    older hof-engine versions that read from there.
    """
    npm_deps = meta.get("dependencies", {}).get("npm", [])
    entry = {
        "version": meta.get("version", "unknown"),
        "installed_at": datetime.now(UTC).isoformat(),
        "files": copied,
        "npm_dependencies": npm_deps,
    }

    # Primary: hof-modules.json at project root (committed to git)
    root_file = project_root / "hof-modules.json"
    root_data: dict = {"installed_modules": {}}
    if root_file.exists():
        try:
            root_data = json.loads(root_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    root_data["installed_modules"][module_name] = entry
    root_file.write_text(json.dumps(root_data, indent=2) + "\n")

    # Legacy: .hof/modules.json (gitignored, kept for backward compat)
    hof_dir = project_root / ".hof"
    hof_dir.mkdir(exist_ok=True)
    legacy_file = hof_dir / "modules.json"
    legacy_data: dict = {"installed_modules": {}}
    if legacy_file.exists():
        try:
            legacy_data = json.loads(legacy_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    legacy_data["installed_modules"][module_name] = entry
    legacy_file.write_text(json.dumps(legacy_data, indent=2))


def _install_module(module_name: str, registry: dict, project_root: Path, force: bool) -> None:
    """Copy a module's files into the current project."""
    if module_name not in registry["modules"]:
        console.print(
            f"[red]Module '{module_name}' not found. Use --list to see available modules.[/]"
        )
        raise typer.Exit(1)

    module_rel_path = registry["modules"][module_name]["path"]
    module_path = CACHE_DIR / module_rel_path
    meta = _load_module_meta(module_path)

    # Check module dependencies first
    dep_modules = meta.get("dependencies", {}).get("modules", [])
    if dep_modules:
        installed: set[str] = set()
        for candidate in (
            project_root / "hof-modules.json",
            project_root / ".hof" / "modules.json",
        ):
            if candidate.exists():
                try:
                    installed = set(
                        json.loads(candidate.read_text()).get("installed_modules", {}).keys()
                    )
                except (json.JSONDecodeError, OSError):
                    pass
                break
        missing = [m for m in dep_modules if m not in installed]
        if missing:
            console.print(f"[yellow]Module '{module_name}' requires: {', '.join(missing)}[/]")
            console.print(
                "Install them first with: " + " && ".join(f"hof add {m}" for m in missing)
            )
            raise typer.Exit(1)

    copied: list[str] = []
    skipped: list[str] = []

    files_spec = meta.get("files", {})
    if isinstance(files_spec, dict):
        file_pairs = list(files_spec.items())
    else:
        file_pairs = [(f, f) for f in files_spec]

    for dest_rel, src_rel in file_pairs:
        src = module_path / src_rel
        dst = project_root / dest_rel
        if dst.exists() and not force:
            skipped.append(dest_rel)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(dest_rel)

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

    # npm dependencies — install automatically if ui/ and package.json exist
    npm_deps = meta.get("dependencies", {}).get("npm", [])
    if npm_deps:
        ui_pkg = project_root / "ui" / "package.json"
        if ui_pkg.exists():
            console.print(f"\n[bold]Installing npm dependencies:[/] {', '.join(npm_deps)}")
            subprocess.run(
                ["npm", "install", "--save", *npm_deps],
                cwd=str(project_root / "ui"),
                check=False,
            )
        else:
            console.print("\n[bold]npm dependencies (will be auto-installed at build time):[/]")
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
                desc = var.get("description", var["name"])
                additions.append(f"# {desc}\n{var['name']}=\n")
        if additions:
            with open(env_file, "a") as f:
                f.write("\n" + "\n".join(additions))
            console.print("\n[bold]Added env vars to .env (fill in values):[/]")
            for var in env_vars:
                if var["name"] not in existing_env:
                    req = " (required)" if var.get("required") else ""
                    desc = var.get("description", "")
                    suffix = f" — {desc}" if desc else ""
                    console.print(f"  {var['name']}{req}{suffix}")

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
    list_modules: bool = typer.Option(
        False, "--list", "-l", help="List available modules and templates."
    ),
    template: str = typer.Option(
        None, "--template", "-t", help="Scaffold a project from a template."
    ),
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
        console.print(
            f"[red]Template '{template_name}' not found. Use --list to see available templates.[/]"
        )
        raise typer.Exit(1)

    template_rel_path = registry["templates"][template_name]["path"]
    template_path = CACHE_DIR / template_rel_path
    meta = _load_template_meta(template_path)

    console.print(f"[bold]Installing template:[/] {template_name}")
    if meta.get("description"):
        console.print(f"  {meta['description']}\n")

    # Copy template-level files (GUIDE.md, etc.).
    # hof.config.py is always skipped because the scaffold's version contains
    # project-specific values (app_name, ${DATABASE_URL}) that must be preserved.
    template_skip = {"template.json", "hof.config.py"}
    for src_file in template_path.iterdir():
        if src_file.name in template_skip:
            continue
        if src_file.is_file():
            dst = project_root / src_file.name
            if dst.exists() and not force:
                console.print(f"  [yellow]~ {src_file.name} (exists, skipped)[/]")
            else:
                shutil.copy2(src_file, dst)
                console.print(f"  [green]+ {src_file.name}[/]")

    # Install each module referenced by the template.
    # Always force-overwrite: a template is a deliberate choice of app shape,
    # so module files (e.g. dashboard's index.tsx) must replace scaffold placeholders.
    for module_name in meta.get("modules", []):
        console.print(f"\n[bold]Installing module:[/] {module_name}")
        _install_module(module_name, registry, project_root, force=True)

    # Verify critical files were actually installed.
    index_page = project_root / "ui" / "pages" / "index.tsx"
    if not index_page.exists():
        console.print(
            "\n[red bold]⚠ WARNING: ui/pages/index.tsx was not installed![/]\n"
            "[red]The app will show a 404 at '/'. This likely means the components "
            "artifact is stale. Re-run with a fresh cache or check the manifest.[/]"
        )

    notes = meta.get("post_install_notes")
    if notes:
        console.print(f"\n[bold cyan]Note:[/] {notes}")

    console.print(f"\n[green bold]✓ Template '{template_name}' installed.[/]")
