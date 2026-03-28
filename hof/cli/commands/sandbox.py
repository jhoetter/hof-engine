"""Sandbox / skill-CLI helpers."""

from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer(name="sandbox", help="Terminal sandbox and skill CLI generation.")


@app.command("build-skills")
def build_skills(
    out: Path = typer.Option(
        Path("skills"),
        "--out",
        "-o",
        help="Directory for generated executables",
    ),
    only: str | None = typer.Option(
        None,
        "--only",
        help="Comma-separated function names (default: all registered functions)",
    ),
    project: Path = typer.Option(
        Path.cwd(),
        "--project",
        help="Hof project root (hof.config.py)",
    ),
) -> None:
    """Write curl-based CLI scripts for each ``@function`` (for COPY into skill Docker image)."""
    from hof.config import load_config
    from hof.core.discovery import discover_all

    cfg = load_config(project)
    discover_all(project, cfg.discovery_dirs)
    from hof.agent.sandbox.skill_cli import write_skill_cli_tree

    names: frozenset[str] | None = None
    if only and only.strip():
        names = frozenset(p.strip() for p in only.split(",") if p.strip())
    paths = write_skill_cli_tree(out, names=names)
    typer.echo(f"Wrote {len(paths)} scripts to {out.resolve()}")


@app.command("write-dockerfile-skill-base")
def write_dockerfile_stub(
    out: Path = typer.Option(
        Path("Dockerfile.skill-base"),
        "--out",
        "-o",
    ),
) -> None:
    """Copy the engine's ``hof/agent/sandbox/Dockerfile.skill-base`` to ``out``."""
    src = Path(__file__).resolve().parents[2] / "agent" / "sandbox" / "Dockerfile.skill-base"
    if not src.is_file():
        typer.echo(f"Missing template: {src}", err=True)
        raise typer.Exit(1)
    out.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    typer.echo(f"Wrote {out.resolve()}")


if __name__ == "__main__":
    app()
