"""Vite dev server and build management for user React UI code."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

USER_VITE_PORT = 5175
VITE_BUILD_MAX_OLD_SPACE_MB = 4096


_FAVICON_CANDIDATES = ("favicon.svg", "favicon.ico", "favicon.png", "favicon.webp")
_DESIGN_SYSTEM_IDS = ("default", "playful", "conservative")

_HOF_ENGINE_DEV_ALIASES: list[tuple[str, str]] = [
    ("@hof-engine/web-session-canvas", "@hof-engine/react"),
    (
        "@hof-engine/react/locales/en/hofEngine.json",
        "@hof-engine/react/locales/en/hofEngine.json",
    ),
    (
        "@hof-engine/react/locales/de/hofEngine.json",
        "@hof-engine/react/locales/de/hofEngine.json",
    ),
]

# Fallback list used only when hof-react/package.json cannot be read (e.g. the
# package is not present on disk). The runtime path always prefers the live
# values from hof-react's manifest via ``_hof_react_required_deps()`` so this
# list does not need to be kept in sync with hof-react itself.
_HOF_REACT_REQUIRED_DEPS_FALLBACK: list[str] = [
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


def _hof_react_dir() -> Path:
    """Path to the bundled hof-react package directory (next to this module)."""
    return Path(__file__).resolve().parent.parent.parent / "hof-react"


def _hof_react_required_deps() -> list[str]:
    """Return the npm packages hof-react needs from the host project.

    Derived live from ``hof-react/package.json`` (``peerDependencies`` plus
    ``dependencies``) so adding a new dep to hof-react automatically flows
    through to scaffolded host package.json files without a code change here.

    ``react`` and ``react-dom`` are filtered out — they are added explicitly
    elsewhere with a pinned major version so the fallback never silently
    drifts.
    """
    pkg = _hof_react_dir() / "package.json"
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return list(_HOF_REACT_REQUIRED_DEPS_FALLBACK)

    names: list[str] = []
    seen: set[str] = set()
    for section in ("peerDependencies", "dependencies"):
        for name in (data.get(section) or {}).keys():
            if name in ("react", "react-dom") or name in seen:
                continue
            seen.add(name)
            names.append(name)
    return names or list(_HOF_REACT_REQUIRED_DEPS_FALLBACK)


def _vite_build_env() -> dict[str, str]:
    """Return an environment with enough Node heap for large Vite bundles."""
    env = os.environ.copy()
    node_options = env.get("NODE_OPTIONS", "")
    if "--max-old-space-size" not in node_options:
        build_heap = f"--max-old-space-size={VITE_BUILD_MAX_OLD_SPACE_MB}"
        env["NODE_OPTIONS"] = f"{node_options} {build_heap}".strip()
    return env


def _js_regex_package_name(name: str) -> str:
    """Escape a package name for a JavaScript regex literal delimited by ``/``."""
    return name.replace("/", "\\/")


def _manifest_relative_target(stub_subdir: str, staged_root: str, entry: str | None = None) -> str:
    rel = Path("sister-import-stubs") / stub_subdir / staged_root
    if entry:
        rel /= entry
    return Path(os.path.normpath(rel)).as_posix()


def _sister_import_pre_alias_lines(ui_dir: Path) -> list[str]:
    """Return exact aliases that must run before the host ``@`` alias."""
    for product in _sister_original_roots(ui_dir):
        if product["sourceRoot"] == "mailai/original":
            inbox_target = "mailai/original/app/components/Inbox.tsx"
            return [
                "      { find: /^@\\/components\\/Inbox$/, "
                f'replacement: path.resolve(__dirname, "{inbox_target}") }},'
            ]
    return []


def _sister_import_alias_lines(ui_dir: Path) -> list[str]:
    """Return Vite alias entries derived from sister-import stub metadata.

    The data-app ships ``ui/sister-import-stubs/stub-manifest.json`` so npm can
    install phantom packages.  When present, the same metadata can drive
    build-time aliases and keep ``ViteManager.build()`` aligned with the
    checked-in dev ``vite.config.ts``.
    """
    manifest = ui_dir / "sister-import-stubs" / "stub-manifest.json"
    try:
        entries = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(entries, list):
        return []

    lines: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        subdir = entry.get("path")
        trampoline = entry.get("trampoline")
        if not isinstance(name, str) or not isinstance(subdir, str):
            continue
        if not isinstance(trampoline, dict):
            continue
        kind = trampoline.get("kind")
        staged_root = trampoline.get("stagedRoot")
        if kind not in {"subpath", "entry"} or not isinstance(staged_root, str):
            continue
        escaped_name = _js_regex_package_name(name)
        if kind == "subpath":
            target = _manifest_relative_target(subdir, staged_root, "$1")
            lines.append(
                f"      {{ find: /^{escaped_name}\\/(.*)$/, "
                f"replacement: path.resolve(__dirname, {json.dumps(target)}) }},"
            )
            continue
        entry_file = trampoline.get("entry")
        if not isinstance(entry_file, str):
            continue
        target = _manifest_relative_target(subdir, staged_root, entry_file)
        lines.append(
            f"      {{ find: /^{escaped_name}$/, "
            f"replacement: path.resolve(__dirname, {json.dumps(target)}) }},"
        )
    return lines


def _sister_original_roots(ui_dir: Path) -> list[dict[str, str]]:
    manifest = ui_dir / "sister-import-stubs" / "stub-manifest.json"
    try:
        entries = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(entries, list):
        return []

    products: list[dict[str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        subdir = entry.get("path")
        trampoline = entry.get("trampoline")
        if not isinstance(name, str) or not isinstance(subdir, str):
            continue
        if not name.endswith("/original") or not isinstance(trampoline, dict):
            continue
        staged_root = trampoline.get("stagedRoot")
        if not isinstance(staged_root, str):
            continue
        source_root = _manifest_relative_target(subdir, staged_root)
        alias_root = f"{source_root}/app" if name == "@mailai/original" else source_root
        products.append({"sourceRoot": source_root, "aliasRoot": alias_root})
    return products


def _sister_product_at_alias_plugin_source(ui_dir: Path) -> str:
    products = _sister_original_roots(ui_dir)
    return (
        "function sisterProductAtAliasPlugin() {\n"
        "  const sourceRootsFor = (root) => {\n"
        "    try {\n"
        "      const realRoot = fs.realpathSync(root);\n"
        "      return realRoot === root ? [root] : [root, realRoot];\n"
        "    } catch {\n"
        "      return [root];\n"
        "    }\n"
        "  };\n"
        f"  const products = {json.dumps(products)}.map((product) => {{\n"
        "    const sourceRoot = path.resolve(__dirname, product.sourceRoot);\n"
        "    return {\n"
        "      sourceRoots: sourceRootsFor(sourceRoot),\n"
        "      aliasRoot: path.resolve(__dirname, product.aliasRoot),\n"
        "    };\n"
        "  });\n"
        '  const sourceExts = ["", ".ts", ".tsx", ".js", ".jsx", ".mjs"];\n'
        "  const existingSourceFile = (base) => {\n"
        "    for (const ext of sourceExts) {\n"
        "      const candidate = base + ext;\n"
        "      if (fs.existsSync(candidate)) return candidate;\n"
        "    }\n"
        '    const indexBase = path.join(base, "index");\n'
        "    for (const ext of sourceExts.slice(1)) {\n"
        "      const candidate = indexBase + ext;\n"
        "      if (fs.existsSync(candidate)) return candidate;\n"
        "    }\n"
        "    return null;\n"
        "  };\n"
        "  const pathInRoot = (filePath, root) => {\n"
        "    const withSep = root.endsWith(path.sep) ? root : `${root}${path.sep}`;\n"
        "    return filePath === root || filePath.startsWith(withSep);\n"
        "  };\n"
        "  return {\n"
        '    name: "sister-product-at-alias",\n'
        '    enforce: "pre",\n'
        "    resolveId(source, importer) {\n"
        '      if (!importer || !source.startsWith("@/")) return null;\n'
        "      const importerPath = path.isAbsolute(importer) ? importer : "
        "path.resolve(__dirname, importer);\n"
        "      for (const product of products) {\n"
        "        if (!product.sourceRoots.some((root) => pathInRoot(importerPath, root))) "
        "continue;\n"
        "        const resolved = existingSourceFile("
        "path.join(product.aliasRoot, source.slice(2)));\n"
        "        if (resolved) return resolved;\n"
        "      }\n"
        "      return null;\n"
        "    },\n"
        "  };\n"
        "}\n\n"
    )


def _host_at_alias_plugin_source() -> str:
    return (
        "function hostAtAliasPlugin() {\n"
        '  const sourceExts = ["", ".ts", ".tsx", ".js", ".jsx", ".mjs"];\n'
        "  const existingSourceFile = (base) => {\n"
        "    for (const ext of sourceExts) {\n"
        "      const candidate = base + ext;\n"
        "      if (fs.existsSync(candidate)) return candidate;\n"
        "    }\n"
        '    const indexBase = path.join(base, "index");\n'
        "    for (const ext of sourceExts.slice(1)) {\n"
        "      const candidate = indexBase + ext;\n"
        "      if (fs.existsSync(candidate)) return candidate;\n"
        "    }\n"
        "    return null;\n"
        "  };\n"
        "  return {\n"
        '    name: "host-at-alias",\n'
        '    enforce: "pre",\n'
        "    resolveId(source) {\n"
        '      if (!source.startsWith("@/")) return null;\n'
        "      return existingSourceFile(path.resolve(__dirname, source.slice(2)));\n"
        "    },\n"
        "  };\n"
        "}\n\n"
    )


def _manual_chunks_source() -> str:
    return (
        "function hofChunkName(prefix, raw) {\n"
        '  return `${prefix}-${raw.replace(/^@/, "").replace(/[^A-Za-z0-9_-]+/g, "-")}`;\n'
        "}\n\n"
        "function hofManualChunks(id) {\n"
        '  const normalized = id.split(path.sep).join("/");\n'
        '  const nodeModules = "/node_modules/";\n'
        "  const nodeIndex = normalized.lastIndexOf(nodeModules);\n"
        "  if (nodeIndex >= 0) {\n"
        "    const packagePath = normalized.slice(nodeIndex + nodeModules.length);\n"
        '    const segments = packagePath.split("/");\n'
        '    const packageName = packagePath.startsWith("@")\n'
        '      ? segments.slice(0, 2).join("/")\n'
        "      : segments[0];\n"
        '    if (["react", "react-dom", "scheduler"].includes(packageName)) {\n'
        '      return "vendor-react";\n'
        "    }\n"
        '    if (packageName.startsWith("@vitejs/") || packageName === "vite") {\n'
        '      return "vendor-vite";\n'
        "    }\n"
        '    return hofChunkName("vendor", packageName);\n'
        "  }\n\n"
        "  const sisterMatch = normalized.match(/\\/(mailai|collabai|pagesai|officeai)\\//);\n"
        "  if (sisterMatch) {\n"
        "    return `sister-${sisterMatch[1]}`;\n"
        "  }\n"
        "}\n\n"
    )


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
        if not package_json.exists():
            self._create_package_json(package_json)
            regenerated_pkg = True
            lock = self.ui_dir / "package-lock.json"
            if lock.exists():
                lock.unlink()
            nm = self.ui_dir / "node_modules"
            if nm.is_dir():
                shutil.rmtree(nm, ignore_errors=True)
        elif self._has_broken_file_refs(package_json):
            self._repair_package_json(package_json)
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
        # Production builds run via ``_vite.build.config.ts`` (see
        # ``_build_with_inputs``), so this file is only consulted for ``vite
        # dev`` / ``vite preview``. We keep it valid by detecting broken
        # relative paths and rewriting it from defaults — the user's existing
        # dev server config is the only thing lost, which is acceptable for
        # the typical scaffolded-then-deployed workflow.
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

        # Stream Vite's stdout to /dev/null (its progress lines are noisy
        # and the host shell already prints "User UI on port N"), but
        # keep stderr on the dev terminal so resolve / config / plugin
        # errors are immediately visible. Without this, a Vite startup
        # crash silently leaves the user-vite port unbound and the host
        # FastAPI proxy returns 503 ("App not ready") with no indication
        # of why — costly to debug.
        self.process = subprocess.Popen(
            ["npx", "vite", "--port", str(port), "--strictPort"],
            cwd=str(self.ui_dir),
            env=env,
            stdout=subprocess.DEVNULL,
        )
        return self.process

    def build(self) -> None:
        """Build the UI for production."""
        if not self.ui_dir.is_dir():
            return
        self.ensure_setup()
        self._preflight_check_imports()

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
                env=_vite_build_env(),
            )
        else:
            self._build_with_inputs(inputs)

    def _preflight_check_imports(self) -> None:
        """Fail fast if pages/components import npm packages not in package.json.

        Vite/Rollup will eventually surface this as a "Could not resolve import"
        error after pulling all dependencies and parsing every module — that
        full pipeline takes minutes and the resulting message buries the actual
        cause. Catch the most common case (a top-level package import without a
        matching entry in ``package.json``) up front so the error is fast,
        scoped, and points at the file you need to edit.

        This is best-effort: it only flags clearly missing top-level packages.
        Aliases (``@/foo``), relative imports, and node built-ins are ignored.
        """
        package_json = self.ui_dir / "package.json"
        if not package_json.is_file():
            return
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        declared: set[str] = set()
        for section in ("dependencies", "devDependencies", "peerDependencies"):
            for name in (data.get(section) or {}).keys():
                declared.add(name)

        scan_roots: list[Path] = []
        for sub in ("pages", "components", "lib"):
            d = self.ui_dir / sub
            if d.is_dir():
                scan_roots.append(d)
        for entry in ("_hof_entry.tsx", "_hof_pages_entry.tsx"):
            p = self.ui_dir / entry
            if p.is_file():
                scan_roots.append(p)
        if not scan_roots:
            return

        imports = self._collect_npm_imports(scan_roots)

        # Built-in/aliased identifiers we never expect to find in package.json.
        ignored_prefixes = (
            "@/",
            "node:",
            "virtual:",
            "@hofos/",  # workspace-only packages, resolved by aliases
            "@hof-design-system.css",
        )
        # ``@hof-engine/react`` (and its subpaths) is wired up via the
        # _hof-engine_ Python install + file: ref injection. Treat it as
        # always-available rather than expecting an explicit declaration.
        always_present = {"@hof-engine/react", "@hof-engine/web-session-canvas"}

        missing: dict[str, set[str]] = {}
        for pkg, sources in imports.items():
            if pkg in declared or pkg in always_present:
                continue
            if any(pkg.startswith(p) for p in ignored_prefixes):
                continue
            missing[pkg] = sources

        if not missing:
            return

        lines = ["Missing npm dependencies (declared imports without package.json entry):"]
        for pkg in sorted(missing):
            sources = sorted(missing[pkg])
            shown = sources[:3]
            extra = f" (+{len(sources) - 3} more)" if len(sources) > 3 else ""
            lines.append(f"  - {pkg}\n      imported by: {', '.join(shown)}{extra}")
        lines.append("\nAdd them to ui/package.json under 'dependencies' and re-run the build.")
        raise RuntimeError("\n".join(lines))

    @staticmethod
    def _collect_npm_imports(roots: list[Path]) -> dict[str, set[str]]:
        """Walk *roots* and return ``{pkg: {file, ...}}`` for every top-level import.

        Top-level means: not relative (``./``, ``../``), not an absolute path,
        not a single-letter alias like ``@/``. Scoped packages (``@scope/name``)
        are normalized to ``@scope/name``.
        """
        import re

        files: list[Path] = []
        for root in roots:
            if root.is_file():
                files.append(root)
            else:
                files.extend(root.rglob("*.tsx"))
                files.extend(root.rglob("*.ts"))

        # Match `from "<spec>"` or `from '<spec>'` and bare `import "<spec>"`.
        spec_re = re.compile(
            r"""(?:from|import)\s+(?:[^"';]*?\s+from\s+)?["']([^"']+)["']""",
            re.MULTILINE,
        )
        result: dict[str, set[str]] = {}
        for f in files:
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for m in spec_re.finditer(text):
                spec = m.group(1)
                if not spec or spec.startswith((".", "/")):
                    continue
                if spec.startswith("@"):
                    parts = spec.split("/", 2)
                    if len(parts) < 2:
                        continue
                    pkg = "/".join(parts[:2])
                else:
                    pkg = spec.split("/", 1)[0]
                result.setdefault(pkg, set()).add(str(f))
        return result

    def _build_with_inputs(self, inputs: list[str]) -> None:
        """Run vite build with explicit rollup input entries."""
        input_obj = {Path(p).stem: p for p in inputs}
        if set(inputs) == {"index.html", "_pages.html"} and len(inputs) == 2:
            self._run_vite_build(
                {"index": "index.html"},
                out_dir="dist/iframe",
                base="/user-ui/",
            )
            self._run_vite_build(
                {"_pages": "_pages.html"},
                out_dir="dist/app",
                base="/",
            )
            return

        base = "/user-ui/" if inputs == ["index.html"] else None
        self._run_vite_build(input_obj, base=base)

    def _run_vite_build(
        self,
        input_obj: dict[str, str],
        *,
        out_dir: str | None = None,
        base: str | None = None,
    ) -> None:
        """Run one Vite build with an isolated Rollup input map."""
        import json

        build_config = self.ui_dir / "_vite.build.config.ts"
        ds_css = self._resolve_design_system_css()
        alias_lines = []
        if ds_css:
            ds_name = Path(ds_css).stem
            alias_lines.append(
                '      { find: "@hof-design-system.css", '
                f'replacement: path.resolve(__dirname, "design-systems/{ds_name}.css") }},'
            )
        comp_ts = self.ui_dir.parent / "computation-ts" / "src" / "index.ts"
        if comp_ts.exists():
            alias_lines.append(
                '      { find: "@hofos/computation-formula", '
                'replacement: path.resolve(__dirname, "../computation-ts/src/index.ts") },'
            )
        for dev_alias, target_pkg in _HOF_ENGINE_DEV_ALIASES:
            alias_lines.append(
                f'      {{ find: "{dev_alias}", replacement: path.resolve(__dirname, '
                f'"node_modules/{target_pkg}") }},'
            )
        alias_lines.extend(_sister_import_alias_lines(self.ui_dir))
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

        sister_at_plugin = _sister_product_at_alias_plugin_source(self.ui_dir)
        host_at_plugin = _host_at_alias_plugin_source()
        manual_chunks = _manual_chunks_source()

        cross_module_plugin = (
            "function crossModuleResolve() {\n"
            "  const re = /(?:\\.\\.\\/)+(?:modules\\/)?[^/]+\\/ui\\//;\n"
            "  return {\n"
            '    name: "cross-module-resolve",\n'
            '    enforce: "pre",\n'
            "    resolveId(source, importer) {\n"
            "      if (!importer || !re.test(source)) return null;\n"
            '      const cleaned = "./" + source.replace(re, "");\n'
            '      const fakeImporter = path.resolve(__dirname, "__resolve_anchor__.ts");\n'
            "      return this.resolve(cleaned, fakeImporter, { skipSelf: true });\n"
            "    },\n"
            "  };\n"
            "}\n\n"
        )

        base_line = f"  base: {json.dumps(base)},\n" if base else ""
        out_dir_line = f"    outDir: {json.dumps(out_dir)},\n" if out_dir else ""
        build_config.write_text(
            'import path from "path";\n'
            + 'import { defineConfig } from "vite";\n'
            + 'import react from "@vitejs/plugin-react";\n'
            + 'import tailwindcss from "@tailwindcss/vite";\n'
            + docs_plugin
            + sister_at_plugin
            + host_at_plugin
            + manual_chunks
            + cross_module_plugin
            + "export default defineConfig({\n"
            + base_line
            + "  plugins: [spreadsheetDocsPlugin(), sisterProductAtAliasPlugin(), "
            + "hostAtAliasPlugin(), crossModuleResolve(), react(), tailwindcss()],\n"
            + "  resolve: {\n"
            + "    alias: [\n"
            + f"{alias_block}\n"
            + "    ],\n"
            + f"    dedupe: {json.dumps(['react', 'react-dom'] + _hof_react_required_deps())},\n"
            + "    preserveSymlinks: true,\n"
            + "  },\n"
            + "  build: {\n"
            + out_dir_line
            + "    reportCompressedSize: false,\n"
            + "    sourcemap: false,\n"
            + "    rollupOptions: {\n"
            + f"      input: {json.dumps(input_obj)},\n"
            + "      output: {\n"
            + "        manualChunks: hofManualChunks,\n"
            + '        chunkFileNames: "assets/[name]-[hash].js",\n'
            + '        entryFileNames: "assets/[name]-[hash].js",\n'
            + "      },\n"
            + "    },\n"
            + "  },\n"
            + "});\n"
        )
        try:
            subprocess.run(
                ["npx", "vite", "build", "--config", "_vite.build.config.ts"],
                cwd=str(self.ui_dir),
                check=True,
                env=_vite_build_env(),
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

        registry_entries: list[str] = []

        for f in tsx_files:
            stem = f.stem
            kind = self._component_export_kind(f)
            if kind is None:
                continue
            if kind == "default":
                loader = f'React.lazy(() => import("./components/{stem}"))'
            else:
                loader = (
                    f'React.lazy(() => import("./components/{stem}")'
                    f".then((mod) => ({{ default: mod.{stem} }})))"
                )
            registry_entries.append(f'  "{stem}": {loader},')

        not_found_msg = "Component ${componentName} not found"
        loaded_keys = "Object.keys(components)"

        entry = (
            'import React, { Suspense } from "react";\n'
            'import { createRoot } from "react-dom/client";\n'
            + "\n"
            + "function RouteLoader() {\n"
            + "  return <div style={{ padding: '1rem' }}>Loading...</div>;\n"
            + "}\n\n"
            + "type HofComponent = React.LazyExoticComponent<React.ComponentType<any>>;\n\n"
            + "const components: Record<string, HofComponent> = {\n"
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
            + "    <Suspense fallback={<RouteLoader />}>\n"
            + "      <Component {...props} onComplete={onComplete} />\n"
            + "    </Suspense>\n"
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

        page_loaders: list[str] = []
        route_entries: list[str] = []

        for f in tsx_files:
            stem = f.stem
            var_name = f"Page_{stem.replace('-', '_')}"
            page_loaders.append(f'const {var_name} = React.lazy(() => import("./pages/{stem}"));')
            route_path = "/" if stem == "index" else f"/{stem}"
            route_entries.append(
                f'  {{ path: "{route_path}", component: {var_name} as React.ComponentType }},'
            )

        has_auth_provider = (self.ui_dir / "components" / "AuthProvider.tsx").is_file()
        use_shell = self._has_shell_router()

        if use_shell:
            entry = self._pages_entry_with_shell(page_loaders, route_entries, has_auth_provider)
        else:
            entry = self._pages_entry_bare(page_loaders, route_entries, has_auth_provider)

        entry_path = self.ui_dir / "_hof_pages_entry.tsx"
        existing = entry_path.read_text() if entry_path.exists() else ""
        if existing != entry:
            entry_path.write_text(entry)

    def _pages_entry_with_shell(
        self,
        page_loaders: list[str],
        route_entries: list[str],
        has_auth_provider: bool,
    ) -> str:
        """Generate entry that delegates to ShellRouter + LayoutProvider."""
        imports: list[str] = [
            'import "./app.css";',
            'import React, { Suspense } from "react";',
            'import { createRoot } from "react-dom/client";',
            'import { ShellRouter } from "./ShellRouter";',
            'import { LayoutProvider } from "./components/LayoutContext";',
        ]

        if has_auth_provider:
            imports.append('import { AuthProvider } from "./components/AuthProvider";')

        loaders_block = "\n".join(page_loaders) + "\n"
        routes_block = "const routes = [\n" + "\n".join(route_entries) + "\n];\n"
        fallback = (
            "function RouteLoader() {\n"
            "  return <div style={{ padding: '1rem' }}>Loading...</div>;\n"
            "}\n"
        )

        shell = "<ShellRouter routes={routes} />"
        if has_auth_provider:
            shell = (
                "<AuthProvider>\n          <ShellRouter routes={routes} />\n        </AuthProvider>"
            )

        render_block = (
            'createRoot(document.getElementById("hof-root")!).render(\n'
            "  <React.StrictMode>\n"
            "    <LayoutProvider>\n"
            "      <Suspense fallback={<RouteLoader />}>\n"
            f"        {shell}\n"
            "      </Suspense>\n"
            "    </LayoutProvider>\n"
            "  </React.StrictMode>\n"
            ");\n"
        )

        return (
            "\n".join(imports)
            + "\n\n"
            + loaders_block
            + "\n"
            + routes_block
            + "\n"
            + fallback
            + "\n"
            + render_block
        )

    def _pages_entry_bare(
        self,
        page_loaders: list[str],
        route_entries: list[str],
        has_auth_provider: bool,
    ) -> str:
        """Generate a minimal inline-router entry (no shell layout)."""
        imports: list[str] = [
            'import "./app.css";',
            'import React, { Suspense, useState, useEffect } from "react";',
            'import { createRoot } from "react-dom/client";',
        ]

        if has_auth_provider:
            imports.append('import { AuthProvider } from "./components/AuthProvider";')
            app_mount = "    <AuthProvider>\n      <App />\n    </AuthProvider>"
        else:
            app_mount = "    <App />"

        return (
            "\n".join(imports)
            + "\n\n"
            + "\n".join(page_loaders)
            + "\n\n"
            + "const routes: { path: string; component: React.ComponentType }[] = [\n"
            + "\n".join(route_entries)
            + "\n];\n\n"
            + "function RouteLoader() {\n"
            + "  return <div style={{ padding: '1rem' }}>Loading...</div>;\n"
            + "}\n\n"
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
            + "  return (\n"
            + "    <Suspense fallback={<RouteLoader />}>\n"
            + "      <Page />\n"
            + "    </Suspense>\n"
            + "  );\n"
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
            for pkg in _hof_react_required_deps():
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

    def _repair_package_json(self, path: Path) -> None:
        """Fix broken ``file:`` refs in an existing package.json, preserving all other deps.

        This avoids the destructive full-regeneration path that drops deps the
        project actually needs (e.g. @blocknote/*, @xyflow/react, cmdk, …).
        Only the broken entries are patched; everything else is kept as-is.
        """
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self._create_package_json(path)
            return

        hof_react = self._hof_react_version()

        for section in ("dependencies", "devDependencies"):
            section_data = data.get(section)
            if not section_data or not isinstance(section_data, dict):
                continue
            for pkg, ver in list(section_data.items()):
                if not isinstance(ver, str) or not ver.startswith("file:"):
                    continue
                target = (path.parent / ver[5:]).resolve()
                if target.exists():
                    continue
                if pkg == "@hof-engine/react" and hof_react is not None:
                    section_data[pkg] = hof_react
                else:
                    section_data[pkg] = "*"

        deps = data.setdefault("dependencies", {})
        if "react" not in deps:
            deps["react"] = "^19.0.0"
        if "react-dom" not in deps:
            deps["react-dom"] = "^19.0.0"
        if hof_react is not None:
            if "@hof-engine/react" not in deps:
                deps["@hof-engine/react"] = hof_react
            for pkg in _hof_react_required_deps():
                if pkg not in deps:
                    deps[pkg] = "*"

        for pkg in self._collect_module_npm_deps():
            if pkg not in deps:
                deps[pkg] = "*"
        for pkg in self._collect_css_import_deps():
            if pkg not in deps:
                deps[pkg] = "*"

        path.write_text(json.dumps(data, indent=2))

    def _create_vite_config(self, path: Path) -> None:
        ds_css = self._resolve_design_system_css()
        alias_lines = []
        if ds_css:
            ds_name = Path(ds_css).stem
            alias_lines.append(
                '      { find: "@hof-design-system.css", '
                f'replacement: path.resolve(__dirname, "design-systems/{ds_name}.css") }},'
            )
        comp_ts = self.ui_dir.parent / "computation-ts" / "src" / "index.ts"
        if comp_ts.exists():
            alias_lines.append(
                '      { find: "@hofos/computation-formula", '
                'replacement: path.resolve(__dirname, "../computation-ts/src/index.ts") },'
            )
        for dev_alias, target_pkg in _HOF_ENGINE_DEV_ALIASES:
            alias_lines.append(
                f'      {{ find: "{dev_alias}", replacement: path.resolve(__dirname, '
                f'"node_modules/{target_pkg}") }},'
            )
        alias_lines.extend(_sister_import_alias_lines(self.ui_dir))
        alias_block = "\n".join(alias_lines)
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
            '      const cleaned = "./" + source.replace(re, "");\n'
            '      const fakeImporter = path.resolve(__dirname, "__resolve_anchor__.ts");\n'
            "      return this.resolve(cleaned, fakeImporter, { skipSelf: true });\n"
            "    },\n"
            "  };\n"
            "}\n\n"
        )
        sister_at_plugin = _sister_product_at_alias_plugin_source(self.ui_dir)
        host_at_plugin = _host_at_alias_plugin_source()
        manual_chunks = _manual_chunks_source()

        path.write_text(
            'import path from "path";\n'
            'import { defineConfig } from "vite";\n'
            'import react from "@vitejs/plugin-react";\n'
            'import tailwindcss from "@tailwindcss/vite";\n'
            + docs_fn
            + sister_at_plugin
            + host_at_plugin
            + manual_chunks
            + cross_module_fn
            + "export default defineConfig({\n"
            "  plugins: [spreadsheetDocsPlugin(), sisterProductAtAliasPlugin(), "
            "hostAtAliasPlugin(), crossModuleResolve(), react(), tailwindcss()],\n"
            "  resolve: {\n"
            "    alias: [\n"
            f"{alias_block}\n"
            "    ],\n"
            f"    dedupe: {json.dumps(['react', 'react-dom'] + _hof_react_required_deps())},\n"
            "    preserveSymlinks: true,\n"
            "  },\n"
            "  build: {\n"
            "    reportCompressedSize: false,\n"
            "    sourcemap: false,\n"
            "    rollupOptions: {\n"
            "      output: {\n"
            "        manualChunks: hofManualChunks,\n"
            '        chunkFileNames: "assets/[name]-[hash].js",\n'
            '        entryFileNames: "assets/[name]-[hash].js",\n'
            "      },\n"
            "    },\n"
            "  },\n"
            "  server: {\n"
            f"    port: {USER_VITE_PORT},\n"
            "    hmr: {\n"
            f"      clientPort: {USER_VITE_PORT},\n"
            "    },\n"
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
        hof_react_dir = _hof_react_dir()
        if (hof_react_dir / "dist").exists():
            return f"file:{hof_react_dir}"
        return None

    def _install_dependencies(self) -> None:
        lockfile = self.ui_dir / "package-lock.json"
        cmd = ["npm", "ci"] if lockfile.exists() else ["npm", "install"]
        subprocess.run(cmd, cwd=str(self.ui_dir), check=True)
