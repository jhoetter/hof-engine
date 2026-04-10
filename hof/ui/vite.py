"""Vite dev server and build management for user React UI code."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

USER_VITE_PORT = 5175


_FAVICON_CANDIDATES = ("favicon.svg", "favicon.ico", "favicon.png", "favicon.webp")
_DESIGN_SYSTEM_IDS = ("default", "playful", "conservative")

_HOF_ENGINE_DEV_ALIASES: list[tuple[str, str]] = [
    ("@hof-engine/web-session-canvas", "@hof-engine/react"),
]

_HOF_REACT_REQUIRED_DEPS: list[str] = [
    "lucide-react",
    "i18next",
    "react-i18next",
    "ansi_up",
    "react-markdown",
    "remark-gfm",
    "remark-math",
    "rehype-katex",
    "rehype-highlight",
    "katex",
    "lowlight",
    "hast-util-to-jsx-runtime",
]


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

    def _resolve_design_system_css(self) -> str | None:
        """Return the absolute path to the active design-system CSS bundle, or None."""
        import os

        ds_dir = self.ui_dir / "design-systems"
        if not ds_dir.is_dir():
            return None
        raw = (
            (os.environ.get("VITE_DESIGN_SYSTEM") or os.environ.get("DESIGN_SYSTEM") or "default")
            .strip()
            .lower()
        )
        ds_id = raw if raw in _DESIGN_SYSTEM_IDS else "default"
        candidate = ds_dir / f"{ds_id}.css"
        return str(candidate) if candidate.exists() else None

    def has_pages(self) -> bool:
        """Return True if the project has at least one page in ui/pages/."""
        pages_dir = self.ui_dir / "pages"
        if not pages_dir.is_dir():
            return False
        return any(pages_dir.glob("*.tsx"))

    def _has_components(self) -> bool:
        """Return True if the project has at least one component in ui/components/."""
        components_dir = self.ui_dir / "components"
        if not components_dir.is_dir():
            return False
        return any(components_dir.glob("*.tsx"))

    def _has_broken_file_refs(self, package_json: Path) -> bool:
        """Return True if package.json contains ``file:`` deps pointing nowhere."""
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return True
        for section in ("dependencies", "devDependencies"):
            for _pkg, ver in (data.get(section) or {}).items():
                if isinstance(ver, str) and ver.startswith("file:"):
                    target = (package_json.parent / ver[5:]).resolve()
                    if not target.exists():
                        return True
        return False

    def _has_broken_vite_config(self, vite_config: Path) -> bool:
        """Return True if vite.config.ts references paths that do not exist."""
        try:
            text = vite_config.read_text(encoding="utf-8")
        except OSError:
            return True
        if "../../modules" in text:
            modules_dir = (vite_config.parent / "../../modules").resolve()
            if not modules_dir.is_dir():
                return True
        if "../../../../../hof-engine" in text:
            hof_engine_dir = (vite_config.parent / "../../../../../hof-engine").resolve()
            if not hof_engine_dir.is_dir():
                return True
        return False

    def ensure_setup(self) -> None:
        """Ensure the UI directory has package.json, node_modules, and entry point."""
        if not self.ui_dir.is_dir():
            return

        package_json = self.ui_dir / "package.json"
        regenerated_pkg = False
        if not package_json.exists() or self._has_broken_file_refs(package_json):
            self._create_package_json(package_json)
            regenerated_pkg = True
            lock = self.ui_dir / "package-lock.json"
            if lock.exists():
                lock.unlink()
            nm = self.ui_dir / "node_modules"
            if nm.is_dir():
                shutil.rmtree(nm, ignore_errors=True)

        node_modules = self.ui_dir / "node_modules"
        if not node_modules.is_dir() or regenerated_pkg:
            self._install_dependencies()

        vite_config = self.ui_dir / "vite.config.ts"
        if not vite_config.exists() or self._has_broken_vite_config(vite_config):
            self._create_vite_config(vite_config)

        tsconfig = self.ui_dir / "tsconfig.json"
        if not tsconfig.exists():
            self._create_tsconfig(tsconfig)

        has_components = self._has_components()
        if has_components:
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

        inputs: list[str] = []
        if self._has_components():
            inputs.append("index.html")
        if self.has_pages():
            inputs.append("_pages.html")
        if not inputs:
            return

        if len(inputs) == 1 and inputs[0] == "index.html":
            subprocess.run(
                ["npx", "vite", "build"],
                cwd=str(self.ui_dir),
                check=True,
            )
        else:
            self._build_with_inputs(inputs)

    def _build_with_inputs(self, inputs: list[str]) -> None:
        """Run vite build with explicit rollup input entries."""
        import json

        input_obj = {Path(p).stem: p for p in inputs}
        build_config = self.ui_dir / "_vite.build.config.ts"
        ds_css = self._resolve_design_system_css()
        alias_lines = ['      "@": path.resolve(__dirname, "."),']
        if ds_css:
            ds_name = Path(ds_css).stem
            alias_lines.append(
                '      "@hof-design-system.css": '
                f'path.resolve(__dirname, "design-systems/{ds_name}.css"),'
            )
        comp_ts = self.ui_dir.parent / "computation-ts" / "src" / "index.ts"
        if comp_ts.exists():
            alias_lines.append(
                '      "@hofos/computation-formula": '
                'path.resolve(__dirname, "../computation-ts/src/index.ts"),'
            )
        for dev_alias, target_pkg in _HOF_ENGINE_DEV_ALIASES:
            alias_lines.append(
                f'      "{dev_alias}": path.resolve(__dirname, "node_modules/{target_pkg}"),'
            )
        alias_block = "\n".join(alias_lines)

        docs_plugin = (
            'import fs from "node:fs";\n'
            "function spreadsheetDocsPlugin() {\n"
            '  const enDir = path.resolve(__dirname, "../docs");\n'
            '  const deDir = path.resolve(__dirname, "../docs/de");\n'
            "  const readMd = (d) => {\n"
            "    const o = {};\n"
            "    if (!fs.existsSync(d)) return o;\n"
            "    for (const n of fs.readdirSync(d))\n"
            '      if (n.endsWith(".md")) o[n] = fs.readFileSync(d+"/"+n,"utf8");\n'
            "    return o;\n"
            "  };\n"
            "  return {\n"
            '    name: "spreadsheet-docs",\n'
            "    resolveId(id) {\n"
            '      if (id==="virtual:spreadsheet-docs-en") return "\\0"+id;\n'
            '      if (id==="virtual:spreadsheet-docs-de") return "\\0"+id;\n'
            "    },\n"
            "    load(id) {\n"
            '      if (id==="\\0virtual:spreadsheet-docs-en")\n'
            "        return `export default ${JSON.stringify(readMd(enDir))}`;\n"
            '      if (id==="\\0virtual:spreadsheet-docs-de")\n'
            "        return `export default ${JSON.stringify(readMd(deDir))}`;\n"
            "    },\n"
            "  };\n"
            "}\n\n"
        )

        cross_module_plugin = (
            "function crossModuleResolve() {\n"
            "  const re = /(?:\\.\\.\\/)+(?:modules\\/)?[^/]+\\/ui\\//;\n"
            "  return {\n"
            '    name: "cross-module-resolve",\n'
            '    enforce: "pre",\n'
            "    resolveId(source, importer) {\n"
            "      if (!importer || !re.test(source)) return null;\n"
            '      return this.resolve(source.replace(re, "./"), '
            "importer, { skipSelf: true });\n"
            "    },\n"
            "  };\n"
            "}\n\n"
        )

        build_config.write_text(
            'import path from "path";\n'
            'import { defineConfig } from "vite";\n'
            'import react from "@vitejs/plugin-react";\n'
            'import tailwindcss from "@tailwindcss/vite";\n'
            + docs_plugin
            + cross_module_plugin
            + "export default defineConfig({\n"
            "  plugins: [spreadsheetDocsPlugin(), crossModuleResolve(), react(), tailwindcss()],\n"
            "  resolve: {\n"
            "    alias: {\n"
            f"{alias_block}\n"
            "    },\n"
            '    dedupe: ["react", "react-dom", "lucide-react", '
            '"i18next", "react-i18next"],\n'
            "  },\n"
            "  build: {\n"
            f"    rollupOptions: {{ input: {json.dumps(input_obj)} }},\n"
            "  },\n"
            "});\n"
        )
        try:
            subprocess.run(
                ["npx", "vite", "build", "--config", "_vite.build.config.ts"],
                cwd=str(self.ui_dir),
                check=True,
            )
        finally:
            build_config.unlink(missing_ok=True)

    def stop(self) -> None:
        """Stop the Vite dev server."""
        if self.process:
            self.process.terminate()
            self.process.wait(timeout=5)
            self.process = None

    @staticmethod
    def _component_export_kind(path: Path) -> str | None:
        """Detect whether *path* has a named export matching its stem or a default export.

        Returns ``"named"``, ``"default"``, or ``None`` (skip this file).
        """
        import re

        stem = path.stem
        if not stem.isidentifier():
            return None
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        if re.search(rf"export\s+(?:function|const|class)\s+{re.escape(stem)}\b", text):
            return "named"
        if re.search(r"export\s+default\s", text):
            return "default"
        return None

    def _generate_entry_point(self) -> None:
        """Auto-generate _hof_entry.tsx that registers all components."""
        components_dir = self.ui_dir / "components"
        tsx_files = sorted(components_dir.glob("*.tsx")) if components_dir.is_dir() else []

        imports: list[str] = []
        registry_entries: list[str] = []

        for f in tsx_files:
            stem = f.stem
            kind = self._component_export_kind(f)
            if kind is None:
                continue
            if kind == "default":
                imports.append(f'import {stem} from "./components/{stem}";')
            else:
                imports.append(f'import {{ {stem} }} from "./components/{stem}";')
            registry_entries.append(f'  "{stem}": {stem},')

        imports_block = "\n".join(imports) + "\n" if imports else ""

        not_found_msg = "Component ${componentName} not found"
        loaded_keys = "Object.keys(components)"

        entry = (
            'import React from "react";\n'
            'import { createRoot } from "react-dom/client";\n'
            + imports_block
            + "\n"
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
            + "    window.parent.postMessage(\n"
            + f"      {{ type: 'hof:error', error: `{not_found_msg}` }},\n"
            + "      '*',\n"
            + "    );\n"
            + "    return;\n"
            + "  }\n"
            + "\n"
            + "  const onComplete = (data: any) => {\n"
            + "    window.parent.postMessage("
            + "{ type: 'hof:complete', data }, '*');\n"
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
            + "  window.parent.postMessage("
            + "{ type: 'hof:resize', height: h + 40 }, '*');\n"
            + "});\n"
            + "observer.observe(document.body);\n\n"
            + "// Signal that the entry script has loaded\n"
            + "window.parent.postMessage(\n"
            + f"  {{ type: 'hof:loaded', components: {loaded_keys} }},\n"
            + "  '*',\n"
            + ");\n"
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

    def _has_shell_router(self) -> bool:
        """Return True if the project has a ShellRouter + LayoutContext."""
        return (self.ui_dir / "ShellRouter.tsx").is_file() and (
            self.ui_dir / "components" / "LayoutContext.tsx"
        ).is_file()

    def _generate_pages_entry(self) -> None:
        """Auto-generate _hof_pages_entry.tsx with file-system routing for pages.

        When the project provides ShellRouter.tsx + LayoutContext.tsx, the
        generated entry delegates routing to ShellRouter (which wraps pages in
        the app-shell layout with sidebar, header, etc.).  Otherwise a minimal
        inline router is generated as a fallback.
        """
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

        has_auth_provider = (self.ui_dir / "components" / "AuthProvider.tsx").is_file()
        use_shell = self._has_shell_router()

        if use_shell:
            entry = self._pages_entry_with_shell(imports, route_entries, has_auth_provider)
        else:
            entry = self._pages_entry_bare(imports, route_entries, has_auth_provider)

        entry_path = self.ui_dir / "_hof_pages_entry.tsx"
        existing = entry_path.read_text() if entry_path.exists() else ""
        if existing != entry:
            entry_path.write_text(entry)

    def _pages_entry_with_shell(
        self,
        page_imports: list[str],
        route_entries: list[str],
        has_auth_provider: bool,
    ) -> str:
        """Generate entry that delegates to ShellRouter + LayoutProvider."""
        imports: list[str] = [
            'import "./app.css";',
            'import React from "react";',
            'import { createRoot } from "react-dom/client";',
            'import { ShellRouter } from "./ShellRouter";',
            'import { LayoutProvider } from "./components/LayoutContext";',
        ]
        imports.extend(page_imports)

        if has_auth_provider:
            imports.append('import { AuthProvider } from "./components/AuthProvider";')

        routes_block = "const routes = [\n" + "\n".join(route_entries) + "\n];\n"

        inner = "      <ShellRouter routes={routes} />"
        if has_auth_provider:
            inner = (
                "      <AuthProvider>\n"
                "        <ShellRouter routes={routes} />\n"
                "      </AuthProvider>"
            )

        render_block = (
            'createRoot(document.getElementById("hof-root")!).render(\n'
            "  <React.StrictMode>\n"
            "    <LayoutProvider>\n" + inner + "\n"
            "    </LayoutProvider>\n"
            "  </React.StrictMode>\n"
            ");\n"
        )

        return "\n".join(imports) + "\n\n" + routes_block + "\n" + render_block

    def _pages_entry_bare(
        self,
        page_imports: list[str],
        route_entries: list[str],
        has_auth_provider: bool,
    ) -> str:
        """Generate a minimal inline-router entry (no shell layout)."""
        imports: list[str] = [
            'import "./app.css";',
            'import React, { useState, useEffect } from "react";',
            'import { createRoot } from "react-dom/client";',
        ]
        imports.extend(page_imports)

        if has_auth_provider:
            imports.append('import { AuthProvider } from "./components/AuthProvider";')
            app_mount = "    <AuthProvider>\n      <App />\n    </AuthProvider>"
        else:
            app_mount = "    <App />"

        return (
            "\n".join(imports)
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
            + app_mount
            + "\n"
            + "  </React.StrictMode>\n"
            + ");\n"
        )

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
  <style>
    body {{ margin: 0; background: #ffffff; }}
    @media (prefers-color-scheme: dark) {{
      body {{ background: #191919; }}
    }}
  </style>
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

    def _collect_css_import_deps(self) -> list[str]:
        """Scan ``app.css`` for ``@import`` of npm packages and return their names."""
        import re

        app_css = self.ui_dir / "app.css"
        if not app_css.exists():
            return []
        try:
            text = app_css.read_text(encoding="utf-8")
        except OSError:
            return []
        deps: list[str] = []
        for m in re.finditer(r'@import\s+"([^"]+)"', text):
            spec = m.group(1)
            if spec.startswith(".") or spec.startswith("/"):
                continue
            if spec == "tailwindcss":
                continue
            if spec.startswith("@hof-design-system"):
                continue
            if spec.startswith("@"):
                parts = spec.split("/")
                pkg = "/".join(parts[:2])
            else:
                pkg = spec.split("/")[0]
            if pkg not in deps:
                deps.append(pkg)
        return deps

    def _collect_module_npm_deps(self) -> list[str]:
        """Return all npm dependencies from installed hof modules.

        Reads hof-modules.json at the project root (committed to git).
        Falls back to the legacy .hof/modules.json for older projects.
        """
        if self.project_root is None:
            return []
        data: dict = {}
        for candidate in (
            self.project_root / "hof-modules.json",
            self.project_root / ".hof" / "modules.json",
        ):
            if candidate.exists():
                try:
                    data = json.loads(candidate.read_text())
                except (json.JSONDecodeError, OSError):
                    continue
                break
        deps: list[str] = []
        for _name, info in data.get("installed_modules", {}).items():
            for dep in info.get("npm_dependencies", []):
                if dep not in deps:
                    deps.append(dep)
        return deps

    def _create_package_json(self, path: Path) -> None:
        deps: dict[str, str] = {
            "react": "^19.0.0",
            "react-dom": "^19.0.0",
        }
        hof_react = self._hof_react_version()
        if hof_react is not None:
            deps["@hof-engine/react"] = hof_react
            for pkg in _HOF_REACT_REQUIRED_DEPS:
                if pkg not in deps:
                    deps[pkg] = "*"

        for pkg in self._collect_module_npm_deps():
            if pkg not in deps:
                deps[pkg] = "*"

        for pkg in self._collect_css_import_deps():
            if pkg not in deps:
                deps[pkg] = "*"

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
                "@tailwindcss/vite": "^4.0.0",
                "@types/react": "^19.0.0",
                "@types/react-dom": "^19.0.0",
                "@vitejs/plugin-react": "^4.0.0",
                "tailwindcss": "^4.0.0",
                "typescript": "^5.0.0",
                "vite": "^6.0.0",
            },
        }
        path.write_text(json.dumps(package, indent=2))

    def _create_vite_config(self, path: Path) -> None:
        ds_css = self._resolve_design_system_css()
        ds_alias = ""
        if ds_css:
            ds_name = Path(ds_css).stem
            ds_alias = (
                '      "@hof-design-system.css": '
                f'path.resolve(__dirname, "design-systems/{ds_name}.css"),\n'
            )
        comp_ts = self.ui_dir.parent / "computation-ts" / "src" / "index.ts"
        comp_alias = ""
        if comp_ts.exists():
            comp_alias = (
                '      "@hofos/computation-formula": '
                'path.resolve(__dirname, "../computation-ts/src/index.ts"),\n'
            )
        dev_alias_block = ""
        for dev_alias, target_pkg in _HOF_ENGINE_DEV_ALIASES:
            dev_alias_block += (
                f'      "{dev_alias}": path.resolve(__dirname, "node_modules/{target_pkg}"),\n'
            )
        docs_fn = (
            'import fs from "node:fs";\n'
            "function spreadsheetDocsPlugin() {\n"
            '  const enDir = path.resolve(__dirname, "../docs");\n'
            '  const deDir = path.resolve(__dirname, "../docs/de");\n'
            "  const readMd = (d) => {\n"
            "    const o = {};\n"
            "    if (!fs.existsSync(d)) return o;\n"
            "    for (const n of fs.readdirSync(d))\n"
            '      if (n.endsWith(".md")) o[n] = fs.readFileSync(d+"/"+n,"utf8");\n'
            "    return o;\n"
            "  };\n"
            "  return {\n"
            '    name: "spreadsheet-docs",\n'
            "    resolveId(id) {\n"
            '      if (id==="virtual:spreadsheet-docs-en") return "\\0"+id;\n'
            '      if (id==="virtual:spreadsheet-docs-de") return "\\0"+id;\n'
            "    },\n"
            "    load(id) {\n"
            '      if (id==="\\0virtual:spreadsheet-docs-en")\n'
            "        return `export default ${JSON.stringify(readMd(enDir))}`;\n"
            '      if (id==="\\0virtual:spreadsheet-docs-de")\n'
            "        return `export default ${JSON.stringify(readMd(deDir))}`;\n"
            "    },\n"
            "  };\n"
            "}\n\n"
        )
        cross_module_fn = (
            "function crossModuleResolve() {\n"
            "  const re = /(?:\\.\\.\\/)+(?:modules\\/)?[^/]+\\/ui\\//;\n"
            "  return {\n"
            '    name: "cross-module-resolve",\n'
            '    enforce: "pre",\n'
            "    resolveId(source, importer) {\n"
            "      if (!importer || !re.test(source)) return null;\n"
            '      return this.resolve(source.replace(re, "./"), '
            "importer, { skipSelf: true });\n"
            "    },\n"
            "  };\n"
            "}\n\n"
        )
        path.write_text(
            'import path from "path";\n'
            'import { defineConfig } from "vite";\n'
            'import react from "@vitejs/plugin-react";\n'
            'import tailwindcss from "@tailwindcss/vite";\n'
            + docs_fn
            + cross_module_fn
            + "export default defineConfig({\n"
            "  plugins: [spreadsheetDocsPlugin(), crossModuleResolve(), react(), tailwindcss()],\n"
            "  resolve: {\n"
            "    alias: {\n"
            '      "@": path.resolve(__dirname, "."),\n'
            + ds_alias
            + comp_alias
            + dev_alias_block
            + "    },\n"
            '    dedupe: ["react", "react-dom", "lucide-react", '
            '"i18next", "react-i18next"],\n'
            "  },\n"
            "  server: {\n"
            "    proxy: {\n"
            '      "/api": "http://localhost:8001",\n'
            "    },\n"
            "    fs: {\n"
            '      allow: [".."],\n'
            "    },\n"
            "  },\n"
            "});\n"
        )

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
                "baseUrl": ".",
                "paths": {"@/*": ["./*"]},
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
