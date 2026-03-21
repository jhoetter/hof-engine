"""Tests for hof.config.find_project_root."""

from __future__ import annotations

from pathlib import Path

from hof.config import find_project_root, load_config


def test_find_project_root_finds_parent(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "hof.config.py").write_text(
        "from hof import Config\nconfig = Config(app_name='t')\n",
        encoding="utf-8",
    )
    sub = root / "nested" / "a"
    sub.mkdir(parents=True)

    found = find_project_root(sub)
    assert found == root.resolve()


def test_find_project_root_returns_none_when_missing(tmp_path: Path) -> None:
    assert find_project_root(tmp_path) is None


def test_load_config_uses_hof_project_root_env(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "hof.config.py").write_text(
        "from hof import Config\nconfig = Config(app_name='fromfile')\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOF_PROJECT_ROOT", str(tmp_path))
    cfg = load_config()
    assert cfg.app_name == "fromfile"
