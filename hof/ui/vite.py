"""Vite dev server and build management for user React code."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


class ViteManager:
    """Manages the Vite dev server for user-defined React components."""

    def __init__(self, ui_dir: Path) -> None:
        self.ui_dir = ui_dir
        self.process: subprocess.Popen | None = None

    def ensure_setup(self) -> None:
        """Ensure the UI directory has package.json and node_modules."""
        if not self.ui_dir.is_dir():
            return

        package_json = self.ui_dir / "package.json"
        if not package_json.exists():
            self._create_package_json(package_json)

        node_modules = self.ui_dir / "node_modules"
        if not node_modules.is_dir():
            self._install_dependencies()

        vite_config = self.ui_dir / "vite.config.ts"
        if not vite_config.exists():
            self._create_vite_config(vite_config)

        tsconfig = self.ui_dir / "tsconfig.json"
        if not tsconfig.exists():
            self._create_tsconfig(tsconfig)

    def start_dev_server(self, port: int = 5173) -> subprocess.Popen | None:
        """Start the Vite dev server."""
        if not self.ui_dir.is_dir():
            return None

        self.ensure_setup()

        self.process = subprocess.Popen(
            ["npx", "vite", "--port", str(port)],
            cwd=str(self.ui_dir),
        )
        return self.process

    def build(self) -> None:
        """Build the UI for production."""
        if not self.ui_dir.is_dir():
            return

        self.ensure_setup()
        subprocess.run(
            ["npx", "vite", "build"],
            cwd=str(self.ui_dir),
            check=True,
        )

    def stop(self) -> None:
        """Stop the Vite dev server."""
        if self.process:
            self.process.terminate()
            self.process.wait(timeout=5)
            self.process = None

    def _create_package_json(self, path: Path) -> None:
        package = {
            "name": "hof-ui",
            "private": True,
            "version": "0.0.0",
            "type": "module",
            "scripts": {
                "dev": "vite",
                "build": "vite build",
                "preview": "vite preview",
            },
            "dependencies": {
                "react": "^19.0.0",
                "react-dom": "^19.0.0",
                "@hof-engine/react": "file:../hof-react",
            },
            "devDependencies": {
                "@types/react": "^19.0.0",
                "@types/react-dom": "^19.0.0",
                "@vitejs/plugin-react": "^4.0.0",
                "typescript": "^5.0.0",
                "vite": "^6.0.0",
            },
        }
        path.write_text(json.dumps(package, indent=2))

    def _create_vite_config(self, path: Path) -> None:
        path.write_text("""\
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
});
""")

    def _create_tsconfig(self, path: Path) -> None:
        tsconfig = {
            "compilerOptions": {
                "target": "ES2020",
                "useDefineForClassFields": True,
                "lib": ["ES2020", "DOM", "DOM.Iterable"],
                "module": "ESNext",
                "skipLibCheck": True,
                "moduleResolution": "bundler",
                "allowImportingTsExtensions": True,
                "isolatedModules": True,
                "moduleDetection": "force",
                "noEmit": True,
                "jsx": "react-jsx",
                "strict": True,
            },
            "include": ["**/*.ts", "**/*.tsx"],
        }
        path.write_text(json.dumps(tsconfig, indent=2))

    def _install_dependencies(self) -> None:
        subprocess.run(
            ["npm", "install"],
            cwd=str(self.ui_dir),
            check=True,
        )
