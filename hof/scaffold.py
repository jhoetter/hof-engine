"""Public scaffolding API.

``get_project_files`` is the single source of truth for the file layout of a
new hof project.  It is consumed by:

* ``hof new project`` — writes files to local disk
* hof-os ``project_scaffold_repo`` — pushes files to GitHub via the Trees API

``get_platform_files`` extends ``get_project_files`` by merging the data-app
platform template and optional starter files. It will become the single source
of truth for both the CLI and server-side scaffolding once hof-os adopts it.
"""

from hof.cli.commands.new import get_project_files

__all__ = ["get_project_files", "get_platform_files"]


def get_platform_files(
    name: str, *, slug: str | None = None, starter: str | None = "blank"
) -> dict[str, str]:
    """Return all files for a complete data-app project.

    Combines skeleton files from ``get_project_files`` with the data-app
    platform template and a starter kit (defaults to ``blank``).
    Pass ``starter=None`` to skip the starter.
    """
    import json
    import os
    from pathlib import Path

    files = get_project_files(name, slug=slug)

    from hof.cli.commands.add import (
        CACHE_DIR,
        _should_skip_impl_file,
    )

    local_path = os.getenv("HOF_COMPONENTS_PATH")
    if local_path:
        components_dir = Path(local_path).expanduser().resolve()
    elif CACHE_DIR.exists():
        components_dir = CACHE_DIR
    else:
        return files

    registry_path = components_dir / "registry.json"
    if not registry_path.exists():
        return files

    registry = json.loads(registry_path.read_text())
    templates = registry.get("templates", {})
    if "data-app" not in templates:
        return files

    template_rel = templates["data-app"]["path"]
    template_path = components_dir / template_rel
    if not template_path.is_dir():
        return files

    meta = json.loads((template_path / "template.json").read_text())

    for module_name in meta.get("modules", []):
        modules_section = registry.get("modules", {})
        if module_name not in modules_section:
            continue
        mod_path = components_dir / modules_section[module_name]["path"]
        mod_meta_path = mod_path / "module.json"
        if not mod_meta_path.exists():
            continue
        mod_meta = json.loads(mod_meta_path.read_text())
        file_spec = mod_meta.get("files", {})
        if isinstance(file_spec, dict):
            pairs = list(file_spec.items())
        else:
            pairs = [(f, f) for f in file_spec]
        for dest_rel, src_rel in pairs:
            src = mod_path / src_rel
            if src.exists():
                resolved = src.resolve() if src.is_symlink() else src
                try:
                    files[dest_rel] = resolved.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    pass

    copy_from = meta.get("copy_from")
    if copy_from:
        impl_path = components_dir / copy_from
        if impl_path.is_dir():
            for src_file in impl_path.rglob("*"):
                if not src_file.is_file():
                    continue
                rel = src_file.relative_to(impl_path)
                if _should_skip_impl_file(rel):
                    continue
                resolved = src_file.resolve() if src_file.is_symlink() else src_file
                try:
                    files[rel.as_posix()] = resolved.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    pass

    if starter:
        starters = registry.get("starters", {})
        if starter in starters:
            starter_dir = components_dir / starters[starter]["path"]
            if starter_dir.is_dir():
                skip = {"starter.json", "template.json", "README.md", ".DS_Store"}
                skip_dirs = {"__pycache__", "node_modules"}
                for src_file in sorted(starter_dir.rglob("*")):
                    if not src_file.is_file():
                        continue
                    rel = src_file.relative_to(starter_dir)
                    if rel.name in skip:
                        continue
                    if any(part in skip_dirs for part in rel.parts):
                        continue
                    try:
                        files[rel.as_posix()] = src_file.read_text(encoding="utf-8")
                    except UnicodeDecodeError:
                        pass

    return files
