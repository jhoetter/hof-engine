"""Vite dev server and build management for user React code."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


USER_VITE_PORT = 5175


_FAVICON_CANDIDATES = ("favicon.svg", "favicon.ico", "favicon.png", "favicon.webp")


class ViteManager:
    """Manages the Vite dev server for user-defined React components and pages."""

    def __init__(
        self,
        ui_dir: Path,
        *,
        app_name: str = "hof app",
        project_root: Path | None = None,
    ) -> None:
        self.ui_dir = ui_dir
        self.app_name = app_name
        self.project_root = project_root
        self.process: subprocess.Popen | None = None

    def _find_favicon(self) -> str | None:
        """Return the web path to a favicon in the design-system assets, or None.

        Checks design-system/assets/icon/ for common favicon filenames and
        returns the first match as a root-relative path (e.g.
        /design-system/assets/icon/favicon.svg).
        """
        if self.project_root is None:
            return None
        icon_dir = self.project_root / "design-system" / "assets" / "icon"
        if not icon_dir.is_dir():
            return None
        for name in _FAVICON_CANDIDATES:
            if (icon_dir / name).exists():
                return f"/design-system/assets/icon/{name}"
        return None

    def has_pages(self) -> bool:
        """Return True if the project has at least one page in ui/pages/."""
        pages_dir = self.ui_dir / "pages"
        if not pages_dir.is_dir():
            return False
        return any(pages_dir.glob("*.tsx"))

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
        if self.has_pages():
            self._generate_pages_entry()
            self._generate_pages_host_page()

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
        favicon = self._find_favicon()
        favicon_tag = f'\n  <link rel="icon" href="{favicon}" />' if favicon else ""
        html = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />{favicon_tag}
  <title>{self.app_name}</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      font-family: system-ui, -apple-system, sans-serif;
      background: #0f1117;
      color: #e4e6eb;
      padding: 20px;
    }}
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

    def _generate_pages_entry(self) -> None:
        """Auto-generate _hof_pages_entry.tsx with file-system routing for pages."""
        pages_dir = self.ui_dir / "pages"
        if not pages_dir.is_dir():
            return

        tsx_files = sorted(pages_dir.glob("*.tsx"))
        if not tsx_files:
            return

        imports: list[str] = []
        route_entries: list[str] = []

        for f in tsx_files:
            stem = f.stem
            var_name = f"Page_{stem.replace('-', '_')}"
            imports.append(f'import {var_name} from "./pages/{stem}";')
            route_path = "/" if stem == "index" else f"/{stem}"
            route_entries.append(f'  {{ path: "{route_path}", component: {var_name} }},')

        entry = (
            'import "./app.css";\n'
            'import React, { useState, useEffect } from "react";\n'
            'import { createRoot } from "react-dom/client";\n'
            + "\n".join(imports)
            + "\n\n"
            + "const routes: { path: string; component: React.ComponentType }[] = [\n"
            + "\n".join(route_entries)
            + "\n];\n\n"
            + "function App() {\n"
            + "  const [path, setPath] = useState(window.location.pathname);\n"
            + "\n"
            + "  useEffect(() => {\n"
            + "    const onPop = () => setPath(window.location.pathname);\n"
            + '    window.addEventListener("popstate", onPop);\n'
            + '    return () => window.removeEventListener("popstate", onPop);\n'
            + "  }, []);\n"
            + "\n"
            + "  const match = routes.find((r) => r.path === path);\n"
            + "  if (!match) {\n"
            + "    return (\n"
            + "      <div style={{ textAlign: 'center', padding: '4rem' }}>\n"
            + "        <h1>404</h1>\n"
            + "        <p>Page not found</p>\n"
            + "      </div>\n"
            + "    );\n"
            + "  }\n"
            + "\n"
            + "  const Page = match.component;\n"
            + "  return <Page />;\n"
            + "}\n\n"
            + 'createRoot(document.getElementById("hof-root")!).render(\n'
            + "  <React.StrictMode>\n"
            + "    <App />\n"
            + "  </React.StrictMode>\n"
            + ");\n"
        )

        entry_path = self.ui_dir / "_hof_pages_entry.tsx"
        existing = entry_path.read_text() if entry_path.exists() else ""
        if existing != entry:
            entry_path.write_text(entry)

    def _generate_pages_host_page(self) -> None:
        """Generate _pages.html that loads the pages entry point."""
        favicon = self._find_favicon()
        favicon_tag = f'\n  <link rel="icon" href="{favicon}" />' if favicon else ""
        html = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />{favicon_tag}
  <title>{self.app_name}</title>
</head>
<body>
  <div id="hof-root"></div>
  <script type="module" src="/_hof_pages_entry.tsx"></script>
</body>
</html>
"""
        pages_html_path = self.ui_dir / "_pages.html"
        existing = pages_html_path.read_text() if pages_html_path.exists() else ""
        if existing != html:
            pages_html_path.write_text(html)

    def _create_package_json(self, path: Path) -> None:
        deps: dict[str, str] = {
            "react": "^19.0.0",
            "react-dom": "^19.0.0",
        }
        hof_react = self._hof_react_version()
        if hof_react is not None:
            deps["@hof-engine/react"] = hof_react

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
            "dependencies": deps,
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
      "/api": "http://localhost:8001",
    },
    fs: {
      // Allow serving files from the project root (one level above ui/)
      // so that /design-system/assets/icon/ is accessible for favicons etc.
      allow: [".."],
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

    def _hof_react_version(self) -> str | None:
        """Return the @hof-engine/react version spec, or None if unavailable.

        Uses a local file: path when the package exists locally (i.e. the
        dist/ directory exists next to the hof-react source in the repo).
        Returns None when running from a pip-installed package (e.g. inside
        Docker) where the hof-react directory isn't present — the package
        is not published to npm so we can't fall back to a registry version.
        """
        hof_react_dir = Path(__file__).resolve().parent.parent.parent / "hof-react"
        if (hof_react_dir / "dist").exists():
            return f"file:{hof_react_dir}"
        return None

    def _install_dependencies(self) -> None:
        subprocess.run(
            ["npm", "install"],
            cwd=str(self.ui_dir),
            check=True,
        )
