"""Tests for hof.ui.vite — ViteManager file generation."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hof.ui.vite import USER_VITE_PORT, ViteManager


@pytest.fixture
def ui_dir(tmp_path: Path) -> Path:
    """Create a minimal UI directory with a components subfolder."""
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "components").mkdir()
    return ui


@pytest.fixture
def manager(ui_dir: Path) -> ViteManager:
    return ViteManager(ui_dir)


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Create a minimal project root with a design-system icon directory."""
    ds_icon = tmp_path / "design-system" / "assets" / "icon"
    ds_icon.mkdir(parents=True)
    return tmp_path


@pytest.fixture
def manager_with_config(project_root: Path) -> ViteManager:
    ui = project_root / "ui"
    ui.mkdir()
    (ui / "components").mkdir()
    return ViteManager(ui, app_name="Acme Portal", project_root=project_root)


class TestViteManagerConstants:
    def test_user_vite_port_default(self):
        assert USER_VITE_PORT == 5175


class TestGenerateHostPage:
    def test_creates_index_html(self, manager, ui_dir):
        manager._generate_host_page()
        index = ui_dir / "index.html"
        assert index.exists()

    def test_index_html_has_hof_root(self, manager, ui_dir):
        manager._generate_host_page()
        content = (ui_dir / "index.html").read_text()
        assert 'id="hof-root"' in content

    def test_index_html_script_src(self, manager, ui_dir):
        manager._generate_host_page()
        content = (ui_dir / "index.html").read_text()
        assert "/_hof_entry.tsx" in content

    def test_index_html_default_title(self, manager, ui_dir):
        manager._generate_host_page()
        content = (ui_dir / "index.html").read_text()
        assert "<title>hof app</title>" in content

    def test_index_html_uses_app_name(self, manager_with_config, project_root):
        ui_dir = project_root / "ui"
        manager_with_config._generate_host_page()
        content = (ui_dir / "index.html").read_text()
        assert "<title>Acme Portal</title>" in content

    def test_index_html_no_favicon_without_design_system(self, manager, ui_dir):
        manager._generate_host_page()
        content = (ui_dir / "index.html").read_text()
        assert 'rel="icon"' not in content

    def test_index_html_not_rewritten_if_unchanged(self, manager, ui_dir):
        manager._generate_host_page()
        mtime1 = (ui_dir / "index.html").stat().st_mtime
        manager._generate_host_page()
        mtime2 = (ui_dir / "index.html").stat().st_mtime
        assert mtime1 == mtime2


class TestGenerateEntryPoint:
    def test_generates_empty_entry_if_no_components_dir(self, tmp_path):
        ui = tmp_path / "empty_ui"
        ui.mkdir()
        manager = ViteManager(ui)
        manager._generate_entry_point()
        entry = ui / "_hof_entry.tsx"
        assert entry.exists()
        assert "const components" in entry.read_text()

    def test_generates_empty_entry_if_no_tsx_files(self, manager, ui_dir):
        manager._generate_entry_point()
        entry = ui_dir / "_hof_entry.tsx"
        assert entry.exists()
        assert "const components" in entry.read_text()

    def test_creates_entry_with_components(self, manager, ui_dir):
        (ui_dir / "components" / "MyComponent.tsx").write_text(
            "export function MyComponent() { return null; }\n"
        )
        manager._generate_entry_point()
        entry = ui_dir / "_hof_entry.tsx"
        assert entry.exists()

    def test_entry_imports_component(self, manager, ui_dir):
        (ui_dir / "components" / "MyWidget.tsx").write_text(
            "export function MyWidget() { return null; }\n"
        )
        manager._generate_entry_point()
        content = (ui_dir / "_hof_entry.tsx").read_text()
        assert "MyWidget" in content
        assert "./components/MyWidget" in content

    def test_entry_registers_component_in_registry(self, manager, ui_dir):
        (ui_dir / "components" / "ReviewForm.tsx").write_text(
            "export function ReviewForm() { return null; }\n"
        )
        manager._generate_entry_point()
        content = (ui_dir / "_hof_entry.tsx").read_text()
        assert '"ReviewForm": ReviewForm' in content

    def test_entry_has_message_listener(self, manager, ui_dir):
        (ui_dir / "components" / "Comp.tsx").write_text("export function Comp() { return null; }\n")
        manager._generate_entry_point()
        content = (ui_dir / "_hof_entry.tsx").read_text()
        assert "hof:render" in content
        assert "hof:loaded" in content

    def test_entry_has_resize_observer(self, manager, ui_dir):
        (ui_dir / "components" / "Comp.tsx").write_text("export function Comp() { return null; }\n")
        manager._generate_entry_point()
        content = (ui_dir / "_hof_entry.tsx").read_text()
        assert "ResizeObserver" in content

    def test_multiple_components(self, manager, ui_dir):
        for name in ("Alpha", "Beta", "Gamma"):
            (ui_dir / "components" / f"{name}.tsx").write_text(
                f"export function {name}() {{ return null; }}\n"
            )
        manager._generate_entry_point()
        content = (ui_dir / "_hof_entry.tsx").read_text()
        for name in ("Alpha", "Beta", "Gamma"):
            assert name in content

    def test_entry_not_rewritten_if_unchanged(self, manager, ui_dir):
        (ui_dir / "components" / "Stable.tsx").write_text(
            "export function Stable() { return null; }\n"
        )
        manager._generate_entry_point()
        mtime1 = (ui_dir / "_hof_entry.tsx").stat().st_mtime
        manager._generate_entry_point()
        mtime2 = (ui_dir / "_hof_entry.tsx").stat().st_mtime
        assert mtime1 == mtime2


class TestCreateViteConfig:
    def test_creates_vite_config(self, manager, ui_dir):
        config_path = ui_dir / "vite.config.ts"
        manager._create_vite_config(config_path)
        assert config_path.exists()

    def test_vite_config_has_react_plugin(self, manager, ui_dir):
        config_path = ui_dir / "vite.config.ts"
        manager._create_vite_config(config_path)
        content = config_path.read_text()
        assert "react" in content.lower()

    def test_vite_config_no_base(self, manager, ui_dir):
        config_path = ui_dir / "vite.config.ts"
        manager._create_vite_config(config_path)
        content = config_path.read_text()
        # Should NOT have base: "/user-ui/" (that was the bug we fixed)
        assert 'base: "/user-ui/"' not in content


class TestBuildWithInputs:
    def test_temp_build_config_includes_at_alias(self, manager, ui_dir):
        from unittest.mock import patch

        captured: dict[str, str] = {}

        def mock_run(cmd, **kwargs):
            assert cmd == ["npx", "vite", "build", "--config", "_vite.build.config.ts"]
            assert kwargs["cwd"] == str(ui_dir)
            assert kwargs["check"] is True
            build_config_path = ui_dir / "_vite.build.config.ts"
            captured["content"] = build_config_path.read_text()
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=mock_run):
            manager._build_with_inputs(["index.html", "_pages.html"])

        content = captured["content"]
        assert 'import path from "path";' in content
        assert "resolve:" in content
        assert "alias:" in content
        assert '"@": path.resolve(__dirname, ".")' in content
        assert not (ui_dir / "_vite.build.config.ts").exists()


class TestCreatePackageJson:
    def test_creates_package_json(self, manager, ui_dir):
        pkg_path = ui_dir / "package.json"
        manager._create_package_json(pkg_path)
        assert pkg_path.exists()

    def test_package_json_valid_json(self, manager, ui_dir):
        pkg_path = ui_dir / "package.json"
        manager._create_package_json(pkg_path)
        data = json.loads(pkg_path.read_text())
        assert "name" in data
        assert "dependencies" in data
        assert "devDependencies" in data

    def test_package_json_has_react(self, manager, ui_dir):
        pkg_path = ui_dir / "package.json"
        manager._create_package_json(pkg_path)
        data = json.loads(pkg_path.read_text())
        assert "react" in data["dependencies"]
        assert "react-dom" in data["dependencies"]


class TestCollectModuleNpmDeps:
    def test_returns_empty_without_project_root(self, ui_dir):
        manager = ViteManager(ui_dir)
        assert manager._collect_module_npm_deps() == []

    def test_returns_empty_without_modules_json(self, tmp_path):
        ui = tmp_path / "ui"
        ui.mkdir()
        manager = ViteManager(ui, project_root=tmp_path)
        assert manager._collect_module_npm_deps() == []

    def test_returns_empty_with_invalid_json(self, tmp_path):
        ui = tmp_path / "ui"
        ui.mkdir()
        hof_dir = tmp_path / ".hof"
        hof_dir.mkdir()
        (hof_dir / "modules.json").write_text("not json")
        manager = ViteManager(ui, project_root=tmp_path)
        assert manager._collect_module_npm_deps() == []

    def test_collects_deps_from_modules(self, tmp_path):
        ui = tmp_path / "ui"
        ui.mkdir()
        hof_dir = tmp_path / ".hof"
        hof_dir.mkdir()
        (hof_dir / "modules.json").write_text(
            json.dumps(
                {
                    "installed_modules": {
                        "schema-view": {
                            "version": "0.1.0",
                            "files": [],
                            "npm_dependencies": ["lucide-react"],
                        },
                        "data-import": {
                            "version": "0.1.0",
                            "files": [],
                            "npm_dependencies": ["xlsx"],
                        },
                    }
                }
            )
        )
        manager = ViteManager(ui, project_root=tmp_path)
        deps = manager._collect_module_npm_deps()
        assert "lucide-react" in deps
        assert "xlsx" in deps

    def test_deduplicates_deps(self, tmp_path):
        ui = tmp_path / "ui"
        ui.mkdir()
        hof_dir = tmp_path / ".hof"
        hof_dir.mkdir()
        (hof_dir / "modules.json").write_text(
            json.dumps(
                {
                    "installed_modules": {
                        "mod-a": {
                            "version": "0.1.0",
                            "files": [],
                            "npm_dependencies": ["lucide-react"],
                        },
                        "mod-b": {
                            "version": "0.1.0",
                            "files": [],
                            "npm_dependencies": ["lucide-react", "xlsx"],
                        },
                    }
                }
            )
        )
        manager = ViteManager(ui, project_root=tmp_path)
        deps = manager._collect_module_npm_deps()
        assert deps.count("lucide-react") == 1
        assert "xlsx" in deps

    def test_handles_modules_without_npm_deps(self, tmp_path):
        ui = tmp_path / "ui"
        ui.mkdir()
        hof_dir = tmp_path / ".hof"
        hof_dir.mkdir()
        (hof_dir / "modules.json").write_text(
            json.dumps(
                {
                    "installed_modules": {
                        "auth": {
                            "version": "0.1.0",
                            "files": [],
                        },
                    }
                }
            )
        )
        manager = ViteManager(ui, project_root=tmp_path)
        assert manager._collect_module_npm_deps() == []


class TestPackageJsonIncludesModuleDeps:
    def test_includes_module_npm_deps(self, tmp_path):
        ui = tmp_path / "ui"
        ui.mkdir()
        hof_dir = tmp_path / ".hof"
        hof_dir.mkdir()
        (hof_dir / "modules.json").write_text(
            json.dumps(
                {
                    "installed_modules": {
                        "schema-view": {
                            "version": "0.1.0",
                            "files": [],
                            "npm_dependencies": ["lucide-react"],
                        },
                    }
                }
            )
        )
        manager = ViteManager(ui, project_root=tmp_path)
        pkg_path = ui / "package.json"
        manager._create_package_json(pkg_path)
        data = json.loads(pkg_path.read_text())
        assert "lucide-react" in data["dependencies"]
        assert data["dependencies"]["lucide-react"] == "*"

    def test_does_not_override_core_deps(self, tmp_path):
        ui = tmp_path / "ui"
        ui.mkdir()
        hof_dir = tmp_path / ".hof"
        hof_dir.mkdir()
        (hof_dir / "modules.json").write_text(
            json.dumps(
                {
                    "installed_modules": {
                        "evil-mod": {
                            "version": "0.1.0",
                            "files": [],
                            "npm_dependencies": ["react"],
                        },
                    }
                }
            )
        )
        manager = ViteManager(ui, project_root=tmp_path)
        pkg_path = ui / "package.json"
        manager._create_package_json(pkg_path)
        data = json.loads(pkg_path.read_text())
        assert data["dependencies"]["react"] == "^19.0.0"


class TestCreateTsconfig:
    def test_creates_tsconfig(self, manager, ui_dir):
        ts_path = ui_dir / "tsconfig.json"
        manager._create_tsconfig(ts_path)
        assert ts_path.exists()

    def test_tsconfig_valid_json(self, manager, ui_dir):
        ts_path = ui_dir / "tsconfig.json"
        manager._create_tsconfig(ts_path)
        data = json.loads(ts_path.read_text())
        assert "compilerOptions" in data

    def test_tsconfig_jsx_react(self, manager, ui_dir):
        ts_path = ui_dir / "tsconfig.json"
        manager._create_tsconfig(ts_path)
        data = json.loads(ts_path.read_text())
        assert "react" in data["compilerOptions"]["jsx"].lower()


class TestFindFavicon:
    def test_returns_none_without_project_root(self, manager):
        assert manager._find_favicon() is None

    def test_returns_none_when_icon_dir_missing(self, tmp_path):
        ui = tmp_path / "ui"
        ui.mkdir()
        m = ViteManager(ui, project_root=tmp_path)
        assert m._find_favicon() is None

    def test_finds_svg_favicon(self, project_root):
        (project_root / "design-system" / "assets" / "icon" / "favicon.svg").write_text("<svg/>")
        ui = project_root / "ui"
        ui.mkdir()
        m = ViteManager(ui, project_root=project_root)
        assert m._find_favicon() == "/design-system/assets/icon/favicon.svg"

    def test_finds_ico_favicon(self, project_root):
        (project_root / "design-system" / "assets" / "icon" / "favicon.ico").write_bytes(b"")
        ui = project_root / "ui"
        ui.mkdir()
        m = ViteManager(ui, project_root=project_root)
        assert m._find_favicon() == "/design-system/assets/icon/favicon.ico"

    def test_prefers_svg_over_ico(self, project_root):
        icon_dir = project_root / "design-system" / "assets" / "icon"
        (icon_dir / "favicon.svg").write_text("<svg/>")
        (icon_dir / "favicon.ico").write_bytes(b"")
        ui = project_root / "ui"
        ui.mkdir()
        m = ViteManager(ui, project_root=project_root)
        assert m._find_favicon() == "/design-system/assets/icon/favicon.svg"


class TestGeneratePagesHostPage:
    def test_creates_pages_html(self, manager, ui_dir):
        (ui_dir / "pages").mkdir()
        manager._generate_pages_host_page()
        assert (ui_dir / "_pages.html").exists()

    def test_pages_html_default_title(self, manager, ui_dir):
        (ui_dir / "pages").mkdir()
        manager._generate_pages_host_page()
        content = (ui_dir / "_pages.html").read_text()
        assert "<title>hof app</title>" in content

    def test_pages_html_uses_app_name(self, manager_with_config, project_root):
        ui_dir = project_root / "ui"
        (ui_dir / "pages").mkdir(exist_ok=True)
        manager_with_config._generate_pages_host_page()
        content = (ui_dir / "_pages.html").read_text()
        assert "<title>Acme Portal</title>" in content

    def test_pages_html_includes_favicon_when_present(self, project_root):
        icon_dir = project_root / "design-system" / "assets" / "icon"
        (icon_dir / "favicon.svg").write_text("<svg/>")
        ui = project_root / "ui"
        ui.mkdir()
        (ui / "pages").mkdir()
        m = ViteManager(ui, app_name="My App", project_root=project_root)
        m._generate_pages_host_page()
        content = (ui / "_pages.html").read_text()
        assert 'rel="icon"' in content
        assert "/design-system/assets/icon/favicon.svg" in content

    def test_pages_html_no_favicon_without_design_system(self, manager, ui_dir):
        (ui_dir / "pages").mkdir()
        manager._generate_pages_host_page()
        content = (ui_dir / "_pages.html").read_text()
        assert 'rel="icon"' not in content

    def test_pages_html_not_rewritten_if_unchanged(self, manager, ui_dir):
        (ui_dir / "pages").mkdir()
        manager._generate_pages_host_page()
        mtime1 = (ui_dir / "_pages.html").stat().st_mtime
        manager._generate_pages_host_page()
        mtime2 = (ui_dir / "_pages.html").stat().st_mtime
        assert mtime1 == mtime2


class TestHasShellRouter:
    def test_false_without_shell_router(self, manager, ui_dir):
        assert manager._has_shell_router() is False

    def test_false_with_only_shell_router(self, manager, ui_dir):
        (ui_dir / "ShellRouter.tsx").write_text("export function ShellRouter() {}")
        assert manager._has_shell_router() is False

    def test_false_with_only_layout_context(self, manager, ui_dir):
        (ui_dir / "components" / "LayoutContext.tsx").write_text("export {}")
        assert manager._has_shell_router() is False

    def test_true_with_both(self, manager, ui_dir):
        (ui_dir / "ShellRouter.tsx").write_text("export function ShellRouter() {}")
        (ui_dir / "components" / "LayoutContext.tsx").write_text("export {}")
        assert manager._has_shell_router() is True


class TestGeneratePagesEntry:
    def test_noop_without_pages_dir(self, manager, ui_dir):
        manager._generate_pages_entry()
        assert not (ui_dir / "_hof_pages_entry.tsx").exists()

    def test_noop_with_empty_pages_dir(self, manager, ui_dir):
        (ui_dir / "pages").mkdir()
        manager._generate_pages_entry()
        assert not (ui_dir / "_hof_pages_entry.tsx").exists()

    def test_bare_entry_without_shell(self, manager, ui_dir):
        pages = ui_dir / "pages"
        pages.mkdir()
        (pages / "index.tsx").write_text("export default function Index() {}")
        (pages / "about.tsx").write_text("export default function About() {}")
        manager._generate_pages_entry()
        content = (ui_dir / "_hof_pages_entry.tsx").read_text()
        assert "function App()" in content
        assert 'path: "/"' in content
        assert 'path: "/about"' in content
        assert "ShellRouter" not in content
        assert "LayoutProvider" not in content

    def test_bare_entry_wraps_auth_provider(self, manager, ui_dir):
        pages = ui_dir / "pages"
        pages.mkdir()
        (pages / "index.tsx").write_text("export default function Index() {}")
        (ui_dir / "components" / "AuthProvider.tsx").write_text("export function AuthProvider() {}")
        manager._generate_pages_entry()
        content = (ui_dir / "_hof_pages_entry.tsx").read_text()
        assert "AuthProvider" in content
        assert "function App()" in content

    def test_shell_entry_with_shell_router(self, manager, ui_dir):
        pages = ui_dir / "pages"
        pages.mkdir()
        (pages / "index.tsx").write_text("export default function Index() {}")
        (pages / "settings.tsx").write_text("export default function Settings() {}")
        (ui_dir / "ShellRouter.tsx").write_text("export function ShellRouter() {}")
        layout_ctx = ui_dir / "components" / "LayoutContext.tsx"
        layout_ctx.write_text("export function LayoutProvider() {}")
        manager._generate_pages_entry()
        content = (ui_dir / "_hof_pages_entry.tsx").read_text()
        assert "ShellRouter" in content
        assert "LayoutProvider" in content
        assert 'path: "/"' in content
        assert 'path: "/settings"' in content
        assert "function App()" not in content

    def test_shell_entry_wraps_auth_provider(self, manager, ui_dir):
        pages = ui_dir / "pages"
        pages.mkdir()
        (pages / "index.tsx").write_text("export default function Index() {}")
        (ui_dir / "ShellRouter.tsx").write_text("export function ShellRouter() {}")
        layout_ctx = ui_dir / "components" / "LayoutContext.tsx"
        layout_ctx.write_text("export function LayoutProvider() {}")
        auth = ui_dir / "components" / "AuthProvider.tsx"
        auth.write_text("export function AuthProvider() {}")
        manager._generate_pages_entry()
        content = (ui_dir / "_hof_pages_entry.tsx").read_text()
        assert "AuthProvider" in content
        assert "ShellRouter" in content
        assert "LayoutProvider" in content

    def test_not_rewritten_if_unchanged(self, manager, ui_dir):
        pages = ui_dir / "pages"
        pages.mkdir()
        (pages / "index.tsx").write_text("export default function Index() {}")
        manager._generate_pages_entry()
        mtime1 = (ui_dir / "_hof_pages_entry.tsx").stat().st_mtime
        manager._generate_pages_entry()
        mtime2 = (ui_dir / "_hof_pages_entry.tsx").stat().st_mtime
        assert mtime1 == mtime2


class TestEnsureSetup:
    def test_ensure_setup_skips_missing_dir(self, tmp_path):
        manager = ViteManager(tmp_path / "nonexistent")
        manager.ensure_setup()  # should not raise

    def test_ensure_setup_creates_files(self, ui_dir):
        manager = ViteManager(ui_dir)
        (ui_dir / "components" / "TestComp.tsx").write_text(
            "export function TestComp() { return null; }\n"
        )
        # Mock npm install to avoid running it
        import subprocess

        original_run = subprocess.run

        def mock_run(cmd, **kwargs):
            if "npm" in cmd:
                return MagicMock(returncode=0)
            return original_run(cmd, **kwargs)

        from unittest.mock import patch

        with patch("subprocess.run", side_effect=mock_run):
            with patch.object(manager, "_install_dependencies"):
                manager.ensure_setup()

        assert (ui_dir / "package.json").exists()
        assert (ui_dir / "vite.config.ts").exists()
        assert (ui_dir / "tsconfig.json").exists()
        assert (ui_dir / "index.html").exists()
        assert (ui_dir / "_hof_entry.tsx").exists()
