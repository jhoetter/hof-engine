"""Tests for hof.cli.commands.add cache bootstrap behavior."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


def _load_add_module():
    module_path = Path(__file__).resolve().parents[1] / "hof" / "cli" / "commands" / "add.py"
    spec = importlib.util.spec_from_file_location("add_cmd_under_test", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ensure_cache_clones_when_missing(tmp_path, monkeypatch):
    add_cmd = _load_add_module()
    cache_dir = tmp_path / "components"
    monkeypatch.setattr(add_cmd, "CACHE_DIR", cache_dir)

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(add_cmd.subprocess, "run", fake_run)
    add_cmd._ensure_cache()

    assert calls == [["git", "clone", add_cmd.COMPONENTS_REPO, str(cache_dir)]]


def test_ensure_cache_pulls_when_cache_is_git_repo(tmp_path, monkeypatch):
    add_cmd = _load_add_module()
    cache_dir = tmp_path / "components"
    cache_dir.mkdir(parents=True)
    monkeypatch.setattr(add_cmd, "CACHE_DIR", cache_dir)

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:3] == ["git", "rev-parse", "--is-inside-work-tree"]:
            return SimpleNamespace(returncode=0)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(add_cmd.subprocess, "run", fake_run)
    add_cmd._ensure_cache()

    assert ["git", "rev-parse", "--is-inside-work-tree"] in calls
    assert ["git", "pull"] in calls
    assert not any(cmd[:2] == ["git", "clone"] for cmd in calls)


def test_ensure_cache_reclones_when_existing_cache_is_not_git_repo(tmp_path, monkeypatch):
    add_cmd = _load_add_module()
    cache_dir = tmp_path / "components"
    cache_dir.mkdir(parents=True)
    (cache_dir / "registry.json").write_text("{}")
    monkeypatch.setattr(add_cmd, "CACHE_DIR", cache_dir)

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:3] == ["git", "rev-parse", "--is-inside-work-tree"]:
            return SimpleNamespace(returncode=1)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(add_cmd.subprocess, "run", fake_run)
    add_cmd._ensure_cache()

    assert ["git", "rev-parse", "--is-inside-work-tree"] in calls
    assert any(cmd[:2] == ["git", "clone"] for cmd in calls)
    assert not any(cmd == ["git", "pull"] for cmd in calls)
