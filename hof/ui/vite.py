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

    def _has_docs(self) -> bool:
        """Return True if the project has a non-empty docs/ directory."""
        from hof.config import get_config

        try:
            config = get_config()
            docs_dir = self.project_root / config.docs_dir if self.project_root else None
        except Exception:
            docs_dir = None
        if docs_dir is None and self.project_root:
            docs_dir = self.project_root / "docs"
        if docs_dir is None:
            return False
        return docs_dir.is_dir() and any(docs_dir.rglob("*.md"))

    def _has_components(self) -> bool:
        """Return True if the project has at least one component in ui/components/."""
        components_dir = self.ui_dir / "components"
        if not components_dir.is_dir():
            return False
        return any(components_dir.glob("*.tsx"))

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

        has_components = self._has_components()
        if has_components:
            self._generate_host_page()
            self._generate_entry_point()
        if self._has_docs():
            self._generate_docs_page()
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
        build_config.write_text(
            'import path from "path";\n'
            'import { defineConfig } from "vite";\n'
            'import react from "@vitejs/plugin-react";\n'
            'import tailwindcss from "@tailwindcss/vite";\n'
            "export default defineConfig({\n"
            "  plugins: [react(), tailwindcss()],\n"
            "  resolve: {\n"
            "    alias: {\n"
            '      "@": path.resolve(__dirname, "."),\n'
            "    },\n"
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

    def _generate_entry_point(self) -> None:
        """Auto-generate _hof_entry.tsx that registers all components."""
        components_dir = self.ui_dir / "components"
        tsx_files = sorted(components_dir.glob("*.tsx")) if components_dir.is_dir() else []

        imports: list[str] = []
        registry_entries: list[str] = []

        for f in tsx_files:
            stem = f.stem
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

        # If the project provides an AuthProvider component, wrap page rendering
        # with it so pages using useAuth() don't crash in development.
        has_auth_provider = (self.ui_dir / "components" / "AuthProvider.tsx").is_file()
        if has_auth_provider:
            imports.append('import { AuthProvider } from "./components/AuthProvider";')
            app_mount = "    <AuthProvider>\n      <App />\n    </AuthProvider>"
        else:
            app_mount = "    <App />"

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
            + app_mount
            + "\n"
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

    def _generate_docs_page(self) -> None:
        """Auto-generate ui/pages/docs.tsx — a public end-user documentation page.

        This page is only generated when a ``docs/`` directory with at least
        one ``.md`` file exists.  It is a normal user-SPA page served at ``/docs``
        with no authentication required.  The content is fetched from
        ``GET /api/docs`` and ``GET /api/docs/{path}`` which are public endpoints.

        If the project already has a hand-written ``ui/pages/docs.tsx`` this
        method does nothing — the generated file is never written when an
        explicit one exists alongside it.
        """
        docs_page = self.ui_dir / "pages" / "docs.tsx"
        if docs_page.exists() and not docs_page.read_text().startswith("// hof:generated"):
            # Respect hand-written docs page
            return

        # Ensure pages/ directory exists
        (self.ui_dir / "pages").mkdir(parents=True, exist_ok=True)

        page = """\
// hof:generated — auto-generated by hof-engine. Delete this file to replace with your own.
import { useEffect, useRef, useState } from "react";

declare global {
  interface Window {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    marked: any;
  }
}

interface DocEntry {
  path: string;
  title: string;
  section: string;
  order: number;
}

interface NavSection {
  name: string;
  entries: DocEntry[];
}

function buildSections(entries: DocEntry[]): NavSection[] {
  const map = new Map<string, DocEntry[]>();
  for (const e of entries) {
    const key = e.section || "";
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(e);
  }
  return Array.from(map.entries()).map(([name, items]) => ({ name, entries: items }));
}

async function fetchTree(): Promise<DocEntry[]> {
  const res = await fetch("/api/docs");
  if (!res.ok) return [];
  return res.json();
}

async function fetchDoc(path: string): Promise<string> {
  const res = await fetch(`/api/docs/${path}`);
  if (!res.ok) throw new Error(res.statusText);
  return res.text();
}

function loadMarked(): Promise<void> {
  return new Promise((resolve) => {
    if (window.marked) { resolve(); return; }
    const s = document.createElement("script");
    s.src = "https://cdn.jsdelivr.net/npm/marked/marked.min.js";
    s.onload = () => resolve();
    document.head.appendChild(s);
  });
}

function renderMarkdown(raw: string): string {
  // Strip YAML frontmatter before rendering
  const body = raw.replace(/^---[\\s\\S]*?---\\n?/, "");
  if (!window.marked) return `<pre>${body}</pre>`;
  return window.marked.parse(body) as string;
}

const STYLES = `
  :root {
    --docs-bg: #0f1117;
    --docs-sidebar-bg: #161b22;
    --docs-border: #30363d;
    --docs-text: #e6edf3;
    --docs-muted: #8b949e;
    --docs-active-bg: rgba(99,102,241,0.15);
    --docs-active-border: #6366f1;
    --docs-active-text: #c7d2fe;
    --docs-hover-bg: rgba(255,255,255,0.04);
    --docs-code-bg: #161b22;
    --docs-pre-bg: #161b22;
    --docs-link: #79c0ff;
    --docs-heading: #f0f6fc;
    --docs-topbar-bg: #0d1117;
    --docs-topbar-border: #21262d;
  }
  @media (prefers-color-scheme: light) {
    :root {
      --docs-bg: #ffffff;
      --docs-sidebar-bg: #f6f8fa;
      --docs-border: #d0d7de;
      --docs-text: #1f2328;
      --docs-muted: #57606a;
      --docs-active-bg: rgba(99,102,241,0.08);
      --docs-active-border: #6366f1;
      --docs-active-text: #4f46e5;
      --docs-hover-bg: rgba(0,0,0,0.04);
      --docs-code-bg: #f6f8fa;
      --docs-pre-bg: #f6f8fa;
      --docs-link: #0969da;
      --docs-heading: #1f2328;
      --docs-topbar-bg: #ffffff;
      --docs-topbar-border: #d0d7de;
    }
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body, #hof-root { height: 100%; }
  body {
    background: var(--docs-bg); color: var(--docs-text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
  .docs-layout { display: flex; flex-direction: column; height: 100vh; }
  .docs-topbar {
    display: flex; align-items: center; gap: 12px;
    padding: 0 20px; height: 48px; flex-shrink: 0;
    background: var(--docs-topbar-bg);
    border-bottom: 1px solid var(--docs-topbar-border);
  }
  .docs-back-btn {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 5px 12px; border-radius: 6px; border: 1px solid var(--docs-border);
    background: transparent; color: var(--docs-muted); font-size: 13px; cursor: pointer;
    text-decoration: none; transition: color .15s, border-color .15s, background .15s;
  }
  .docs-back-btn:hover {
    color: var(--docs-text); border-color: var(--docs-text);
    background: var(--docs-hover-bg);
  }
  .docs-topbar-title { font-size: 14px; font-weight: 600; color: var(--docs-text); }
  .docs-body { display: flex; flex: 1; overflow: hidden; }
  .docs-sidebar {
    width: 240px; flex-shrink: 0; overflow-y: auto;
    background: var(--docs-sidebar-bg);
    border-right: 1px solid var(--docs-border);
    padding: 16px 0;
  }
  .docs-section-label {
    padding: 12px 16px 4px; font-size: 11px; font-weight: 600;
    text-transform: uppercase; letter-spacing: .06em; color: var(--docs-muted);
  }
  .docs-nav-btn {
    display: block; width: 100%; text-align: left; padding: 7px 16px 7px 19px;
    font-size: 13.5px; border: none; border-left: 3px solid transparent;
    background: transparent; cursor: pointer; color: var(--docs-muted);
    transition: color .12s, background .12s, border-color .12s;
  }
  .docs-nav-btn:hover { background: var(--docs-hover-bg); color: var(--docs-text); }
  .docs-nav-btn.active {
    background: var(--docs-active-bg); border-left-color: var(--docs-active-border);
    color: var(--docs-active-text); font-weight: 500; padding-left: 16px;
  }
  .docs-content-wrap { flex: 1; overflow-y: auto; }
  .docs-content {
    max-width: 760px; margin: 0 auto; padding: 40px 48px 80px;
    line-height: 1.7; font-size: 15px; color: var(--docs-text);
  }
  .docs-content h1 {
    font-size: 28px; font-weight: 700; color: var(--docs-heading);
    margin: 0 0 24px; padding-bottom: 12px;
    border-bottom: 1px solid var(--docs-border);
  }
  .docs-content h2 {
    font-size: 20px; font-weight: 600; color: var(--docs-heading);
    margin: 40px 0 12px; padding-bottom: 8px;
    border-bottom: 1px solid var(--docs-border);
  }
  .docs-content h3 {
    font-size: 16px; font-weight: 600; color: var(--docs-heading);
    margin: 28px 0 8px;
  }
  .docs-content h4 {
    font-size: 14px; font-weight: 600; color: var(--docs-heading);
    margin: 20px 0 6px;
  }
  .docs-content p { margin: 0 0 16px; }
  .docs-content a { color: var(--docs-link); text-decoration: none; }
  .docs-content a:hover { text-decoration: underline; }
  .docs-content code {
    font-family: "SFMono-Regular", Consolas, monospace; font-size: 13px;
    background: var(--docs-code-bg); border: 1px solid var(--docs-border);
    border-radius: 4px; padding: 2px 6px;
  }
  .docs-content pre {
    background: var(--docs-pre-bg); border: 1px solid var(--docs-border);
    border-radius: 8px; padding: 16px 20px; overflow-x: auto; margin: 0 0 20px;
  }
  .docs-content pre code {
    background: none; border: none; padding: 0; font-size: 13px; line-height: 1.6;
  }
  .docs-content ul, .docs-content ol { margin: 0 0 16px 24px; }
  .docs-content li { margin: 4px 0; }
  .docs-content blockquote {
    border-left: 3px solid var(--docs-active-border);
    padding: 8px 16px; margin: 0 0 16px; color: var(--docs-muted);
    background: var(--docs-active-bg); border-radius: 0 6px 6px 0;
  }
  .docs-content hr { border: none; border-top: 1px solid var(--docs-border); margin: 28px 0; }
  .docs-content table { width: 100%; border-collapse: collapse; margin: 0 0 20px; font-size: 14px; }
  .docs-content th, .docs-content td {
    text-align: left; padding: 8px 12px; border: 1px solid var(--docs-border);
  }
  .docs-content th { background: var(--docs-sidebar-bg); font-weight: 600; }
  .docs-content img { max-width: 100%; border-radius: 6px; }
  .docs-loading { padding: 40px 48px; color: var(--docs-muted); font-size: 14px; }
  .docs-empty { padding: 40px 48px; color: var(--docs-muted); font-size: 14px; }
  .docs-error { padding: 40px 48px; color: #f85149; font-size: 14px; }
`;

export default function DocsPage() {
  const [tree, setTree] = useState<DocEntry[]>([]);
  const [activePath, setActivePath] = useState<string | null>(null);
  const [markdown, setMarkdown] = useState("");
  const [markedReady, setMarkedReady] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    loadMarked().then(() => {
      setMarkedReady(true);
      fetchTree().then((entries) => {
        setTree(entries);
        if (entries.length > 0) setActivePath(entries[0].path);
      });
    });
  }, []);

  useEffect(() => {
    if (!activePath || !markedReady) return;
    setLoading(true);
    setError(null);
    fetchDoc(activePath)
      .then(setMarkdown)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
    contentRef.current?.scrollTo({ top: 0 });
  }, [activePath, markedReady]);

  const sections = buildSections(tree);
  const rendered = markdown && markedReady ? renderMarkdown(markdown) : "";

  return (
    <>
      <style>{STYLES}</style>
      <div className="docs-layout">
        {/* Top bar */}
        <div className="docs-topbar">
          <a href="/" className="docs-back-btn">
            ← Back to app
          </a>
          <span className="docs-topbar-title">Documentation</span>
        </div>

        <div className="docs-body">
          {/* Sidebar */}
          <nav className="docs-sidebar">
            {sections.length === 0 && (
              <div className="docs-section-label">No docs found</div>
            )}
            {sections.map((sec) => (
              <div key={sec.name}>
                {sec.name && (
                  <div className="docs-section-label">{sec.name}</div>
                )}
                {sec.entries.map((e) => (
                  <button
                    key={e.path}
                    className={`docs-nav-btn${activePath === e.path ? " active" : ""}`}
                    onClick={() => setActivePath(e.path)}
                  >
                    {e.title}
                  </button>
                ))}
              </div>
            ))}
          </nav>

          {/* Content */}
          <div className="docs-content-wrap" ref={contentRef}>
            {loading && <div className="docs-loading">Loading…</div>}
            {error && <div className="docs-error">{error}</div>}
            {!loading && !error && rendered && (
              <div
                className="docs-content"
                dangerouslySetInnerHTML={{ __html: rendered }}
              />
            )}
            {!loading && !error && !rendered && tree.length === 0 && (
              <div className="docs-empty">
                No documentation found. Add Markdown files to your project's{" "}
                <code>docs/</code> directory.
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
"""
        existing = docs_page.read_text() if docs_page.exists() else ""
        if existing != page:
            docs_page.write_text(page)

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
        path.write_text("""\
import path from "path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
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
