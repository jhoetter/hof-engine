"""Tests for hof.core.discovery."""

from __future__ import annotations

import sys
from pathlib import Path

from hof.core.discovery import DEFAULT_DIRS, discover_all
from hof.core.registry import registry


class TestDefaultDirs:
    def test_default_dirs_keys(self):
        assert set(DEFAULT_DIRS.keys()) == {"tables", "functions", "flows", "cron"}

    def test_default_dirs_values(self):
        assert DEFAULT_DIRS["tables"] == "tables"
        assert DEFAULT_DIRS["functions"] == "functions"
        assert DEFAULT_DIRS["flows"] == "flows"
        assert DEFAULT_DIRS["cron"] == "cron"


class TestDiscoverAll:
    def test_skips_missing_directories(self, tmp_project: Path):
        # Remove all subdirs — discover_all should not raise
        import shutil

        for d in ("tables", "functions", "flows", "cron"):
            shutil.rmtree(tmp_project / d, ignore_errors=True)
        discover_all(tmp_project)  # should not raise

    def test_adds_project_root_to_sys_path(self, tmp_project: Path):
        discover_all(tmp_project)
        assert str(tmp_project) in sys.path

    def test_imports_python_files(self, tmp_project: Path):
        # Write a module that registers a function
        fn_file = tmp_project / "functions" / "my_fn.py"
        fn_file.write_text(
            "from hof.functions import function\n\n"
            "@function\n"
            "def discovered_fn() -> dict:\n"
            "    return {}\n"
        )
        discover_all(tmp_project)
        assert registry.get_function("discovered_fn") is not None

    def test_skips_underscore_files(self, tmp_project: Path):
        fn_file = tmp_project / "functions" / "_private.py"
        fn_file.write_text(
            "from hof.functions import function\n\n"
            "@function\n"
            "def private_fn() -> dict:\n"
            "    return {}\n"
        )
        discover_all(tmp_project)
        assert registry.get_function("private_fn") is None

    def test_dir_overrides(self, tmp_project: Path):
        custom_dir = tmp_project / "custom_fns"
        custom_dir.mkdir()
        (custom_dir / "override_fn.py").write_text(
            "from hof.functions import function\n\n"
            "@function\n"
            "def override_fn() -> dict:\n"
            "    return {}\n"
        )
        discover_all(tmp_project, dir_overrides={"functions": "custom_fns"})
        assert registry.get_function("override_fn") is not None

    def test_import_error_does_not_crash(self, tmp_project: Path):
        bad_file = tmp_project / "functions" / "bad_module.py"
        bad_file.write_text("raise ValueError('intentional error')\n")
        # Should not raise — errors are logged and swallowed
        discover_all(tmp_project)

    def test_discovers_multiple_files(self, tmp_project: Path):
        for i in range(3):
            (tmp_project / "functions" / f"fn_{i}.py").write_text(
                f"from hof.functions import function\n\n"
                f"@function\n"
                f"def fn_{i}() -> dict:\n"
                f"    return {{}}\n"
            )
        discover_all(tmp_project)
        for i in range(3):
            assert registry.get_function(f"fn_{i}") is not None
