"""Tests for hof.cli.commands.add."""

from __future__ import annotations

import tarfile
from pathlib import Path
from unittest.mock import MagicMock

from hof.cli.commands import add as add_cmd


class _FakeNamedTemporaryFile:
    def __init__(self, path: Path):
        self.name = str(path)

    def __enter__(self):
        Path(self.name).write_bytes(b"")
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_ensure_cache_cleans_tempfile_on_urlretrieve_failure(tmp_path, monkeypatch):
    tmp_archive = tmp_path / "failed-download.tar.gz"
    cache_dir = tmp_path / "cache"
    mock_run = MagicMock()

    monkeypatch.setattr(add_cmd, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(
        add_cmd.tempfile,
        "NamedTemporaryFile",
        lambda *args, **kwargs: _FakeNamedTemporaryFile(tmp_archive),
    )
    monkeypatch.setattr(
        add_cmd.urllib.request,
        "urlretrieve",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("download failed")),
    )
    monkeypatch.setattr(add_cmd.subprocess, "run", mock_run)

    add_cmd._ensure_cache()

    assert not tmp_archive.exists()
    mock_run.assert_called_once()
    assert mock_run.call_args.args[0][:2] == ["git", "clone"]
    assert mock_run.call_args.kwargs["check"] is True


def test_ensure_cache_cleans_tempfile_on_extractall_failure(tmp_path, monkeypatch):
    tmp_archive = tmp_path / "failed-extract.tar.gz"
    cache_dir = tmp_path / "cache"
    mock_run = MagicMock()

    class _FailingTar:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extractall(self, path):
            raise tarfile.TarError("invalid archive")

    monkeypatch.setattr(add_cmd, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(
        add_cmd.tempfile,
        "NamedTemporaryFile",
        lambda *args, **kwargs: _FakeNamedTemporaryFile(tmp_archive),
    )
    monkeypatch.setattr(
        add_cmd.urllib.request,
        "urlretrieve",
        lambda _url, filename: Path(filename).write_bytes(b"fake-archive"),
    )
    monkeypatch.setattr(add_cmd.tarfile, "open", lambda *_args, **_kwargs: _FailingTar())
    monkeypatch.setattr(add_cmd.subprocess, "run", mock_run)

    add_cmd._ensure_cache()

    assert not tmp_archive.exists()
    mock_run.assert_called_once()
    assert mock_run.call_args.args[0] == ["git", "pull"]
    assert mock_run.call_args.kwargs["cwd"] == str(cache_dir)
    assert mock_run.call_args.kwargs["check"] is True
