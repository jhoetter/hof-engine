"""Vite dev server and build management for user React code."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


USER_VITE_PORT = 5175


class ViteManager:
    """Manages the Vite dev server for user-defined React components."""

    def __init__(self, ui_dir: Path) -> None:
        self.ui_dir = ui_dir
        self.process: subprocess.Popen | None = None

    def ensure_setup(self) -> None:
        """Ensure the UI directory has package.json, node_modules, and entry point."""
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

        self._generate_host_page()
        self._generate_entry_point()

    def start_dev_server(
        self,
        port: int = USER_VITE_PORT,
        env: dict[str, str] | None = None,
    ) -> subprocess.Popen | None:
        """Start the Vite dev server for user components."""
        if not self.ui_dir.is_dir():
            return None

        self.ensure_setup()

        self.process = subprocess.Popen(
            ["npx", "vite", "--port", str(port), "--strictPort"],
            cwd=str(self.ui_dir),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
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

    def _generate_entry_point(self) -> None:
        """Auto-generate _hof_entry.tsx that registers all components."""
        components_dir = self.ui_dir / "components"
        if not components_dir.is_dir():
            return

        tsx_files = sorted(components_dir.glob("*.tsx"))
        if not tsx_files:
            return

        imports: list[str] = []
        registry_entries: list[str] = []

        for f in tsx_files:
            stem = f.stem
            imports.append(f'import {{ {stem} }} from "./components/{stem}";')
            registry_entries.append(f'  "{stem}": {stem},')

        entry = (
            'import React from "react";\n'
            'import { createRoot } from "react-dom/client";\n'
            + "\n".join(imports)
            + "\n\n"
            + "const components: Record<string, React.ComponentType<any>> = {\n"
            + "\n".join(registry_entries)
            + "\n};\n\n"
            + "// Listen for render requests from the parent (admin UI)\n"
            + "window.addEventListener('message', (event) => {\n"
            + "  const { type, componentName, props } = event.data || {};\n"
            + "  if (type !== 'hof:render') return;\n"
            + "\n"
            + "  const Component = components[componentName];\n"
            + "  const target = document.getElementById('hof-root');\n"
            + "  if (!Component || !target) {\n"
            + "    window.parent.postMessage({ type: 'hof:error', error: `Component ${componentName} not found` }, '*');\n"
            + "    return;\n"
            + "  }\n"
            + "\n"
            + "  const onComplete = (data: any) => {\n"
            + "    window.parent.postMessage({ type: 'hof:complete', data }, '*');\n"
            + "  };\n"
            + "\n"
            + "  createRoot(target).render(\n"
            + "    React.createElement(Component, { ...props, onComplete })\n"
            + "  );\n"
            + "\n"
            + "  window.parent.postMessage({ type: 'hof:ready' }, '*');\n"
            + "});\n\n"
            + "// Auto-resize iframe to match content height\n"
            + "const observer = new ResizeObserver(() => {\n"
            + "  const h = document.body.scrollHeight;\n"
            + "  window.parent.postMessage({ type: 'hof:resize', height: h + 40 }, '*');\n"
            + "});\n"
            + "observer.observe(document.body);\n\n"
            + "// Signal that the entry script has loaded\n"
            + "window.parent.postMessage({ type: 'hof:loaded', components: Object.keys(components) }, '*');\n"
        )

        entry_path = self.ui_dir / "_hof_entry.tsx"
        existing = entry_path.read_text() if entry_path.exists() else ""
        if existing != entry:
            entry_path.write_text(entry)

    def _generate_host_page(self) -> None:
        """Generate index.html that loads the entry point."""
        html = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>hof component</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: system-ui, -apple-system, sans-serif;
      background: #0f1117;
      color: #e4e6eb;
      padding: 20px;
    }
  </style>
</head>
<body>
  <div id="hof-root"></div>
  <script type="module" src="/_hof_entry.tsx"></script>
</body>
</html>
"""
        index_path = self.ui_dir / "index.html"
        existing = index_path.read_text() if index_path.exists() else ""
        if existing != html:
            index_path.write_text(html)

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
                "@hof-engine/react": "^0.1.0",
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
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
