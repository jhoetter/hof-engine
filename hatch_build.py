"""Hatch build hook: compile frontend assets before packaging the wheel."""

from __future__ import annotations

import subprocess
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


def _ensure_npm_build(root: Path, subdir: str, label: str, app) -> None:
    """Run npm install + build in *subdir* if dist/ is missing."""
    pkg_dir = root / subdir
    if (pkg_dir / "dist").exists():
        return
    if not (pkg_dir / "package.json").exists():
        return

    app.display_info(f"Building {label}...")
    lock_file = pkg_dir / "package-lock.json"
    install_cmd = ["npm", "ci"] if lock_file.exists() else ["npm", "install"]
    subprocess.run(install_cmd, cwd=str(pkg_dir), check=True)
    subprocess.run(["npm", "run", "build"], cwd=str(pkg_dir), check=True)
    app.display_success(f"{label} built successfully.")


class AdminBuildHook(BuildHookInterface):
    PLUGIN_NAME = "admin-build"

    def initialize(self, version: str, build_data: dict) -> None:
        root = Path(self.root)
        _ensure_npm_build(root, "hof/ui/admin", "Admin UI", self.app)
        _ensure_npm_build(root, "hof-react", "@hof-engine/react", self.app)
