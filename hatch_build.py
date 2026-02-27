"""Hatch build hook: compile the admin UI before packaging the wheel."""

from __future__ import annotations

import subprocess
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class AdminBuildHook(BuildHookInterface):
    PLUGIN_NAME = "admin-build"

    def initialize(self, version: str, build_data: dict) -> None:
        admin_dir = Path(self.root) / "hof" / "ui" / "admin"
        dist_dir = admin_dir / "dist"

        if dist_dir.exists():
            return

        self.app.display_info("Building admin UI...")
        subprocess.run(["npm", "ci"], cwd=str(admin_dir), check=True)
        subprocess.run(["npm", "run", "build"], cwd=str(admin_dir), check=True)
        self.app.display_success("Admin UI built successfully.")
