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
