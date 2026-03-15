"""Tests for hof.cli.commands.add."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

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
        add_cmd,
        "_resolve_artifact",
        lambda: add_cmd.ArtifactResolution(
            "https://example.com/hof-components.tar.gz", None, "test"
        ),
    )
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

        def getmembers(self):
            return []

        def extractall(self, *args, **kwargs):
            raise tarfile.TarError("invalid archive")

    monkeypatch.setattr(add_cmd, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(
        add_cmd,
        "_resolve_artifact",
        lambda: add_cmd.ArtifactResolution(
            "https://example.com/hof-components.tar.gz", None, "test"
        ),
    )
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


def _write_tar(tmp_path: Path, entries: list[tuple[tarfile.TarInfo, bytes]]) -> Path:
    tar_path = tmp_path / "artifact.tar"
    with tarfile.open(tar_path, "w") as tar:
        for member, content in entries:
            if member.isfile():
                tar.addfile(member, io.BytesIO(content))
            else:
                tar.addfile(member)
    return tar_path


def _file_entry(name: str, content: bytes = b"x") -> tuple[tarfile.TarInfo, bytes]:
    member = tarfile.TarInfo(name)
    member.size = len(content)
    return member, content


def test_safe_tar_members_allows_regular_files(tmp_path: Path) -> None:
    tar_path = _write_tar(tmp_path, [_file_entry("module/file.txt", b"ok")])
    destination = tmp_path / "extract"
    destination.mkdir()

    with tarfile.open(tar_path, "r") as tar:
        members = add_cmd._safe_tar_members(tar, destination)

    assert [m.name for m in members] == ["module/file.txt"]


def test_safe_tar_members_rejects_parent_traversal(tmp_path: Path) -> None:
    tar_path = _write_tar(tmp_path, [_file_entry("../evil.txt", b"bad")])
    destination = tmp_path / "extract"
    destination.mkdir()

    with tarfile.open(tar_path, "r") as tar:
        with pytest.raises(tarfile.TarError, match="Unsafe path"):
            add_cmd._safe_tar_members(tar, destination)


def test_safe_tar_members_rejects_absolute_path(tmp_path: Path) -> None:
    tar_path = _write_tar(tmp_path, [_file_entry("/tmp/evil.txt", b"bad")])
    destination = tmp_path / "extract"
    destination.mkdir()

    with tarfile.open(tar_path, "r") as tar:
        with pytest.raises(tarfile.TarError, match="Unsafe path"):
            add_cmd._safe_tar_members(tar, destination)


def test_safe_tar_members_rejects_symlink(tmp_path: Path) -> None:
    symlink = tarfile.TarInfo("module/link")
    symlink.type = tarfile.SYMTYPE
    symlink.linkname = "../outside.txt"
    tar_path = _write_tar(tmp_path, [(symlink, b"")])
    destination = tmp_path / "extract"
    destination.mkdir()

    with tarfile.open(tar_path, "r") as tar:
        with pytest.raises(tarfile.TarError, match="Symlinks are not allowed"):
            add_cmd._safe_tar_members(tar, destination)


def test_safe_tar_members_allows_hard_links(tmp_path: Path) -> None:
    regular = _file_entry("module/original.txt", b"content")
    hardlink = tarfile.TarInfo("module/hardlink.txt")
    hardlink.type = tarfile.LNKTYPE
    hardlink.linkname = "module/original.txt"
    tar_path = _write_tar(tmp_path, [regular, (hardlink, b"")])
    destination = tmp_path / "extract"
    destination.mkdir()

    with tarfile.open(tar_path, "r") as tar:
        safe = add_cmd._safe_tar_members(tar, destination)
        names = [m.name for m in safe]
        assert "module/original.txt" in names
        assert "module/hardlink.txt" in names


def test_resolve_artifact_prefers_env_override(monkeypatch):
    monkeypatch.setenv("HOF_COMPONENTS_URL", "https://example.com/custom.tar.gz")
    resolved = add_cmd._resolve_artifact()
    assert resolved.url == "https://example.com/custom.tar.gz"
    assert resolved.source == "env override"


def test_resolve_artifact_manifest_exact(monkeypatch):
    monkeypatch.delenv("HOF_COMPONENTS_URL", raising=False)
    monkeypatch.setattr(
        add_cmd,
        "_load_components_manifest",
        lambda: {
            "artifacts": [
                {
                    "engine_version": "0.1.0",
                    "artifact_url": "https://example.com/exact.tar.gz",
                    "sha256": "abc123",
                }
            ]
        },
    )
    import hof

    monkeypatch.setattr(hof, "__version__", "0.1.0", raising=False)
    resolved = add_cmd._resolve_artifact()
    assert resolved.url == "https://example.com/exact.tar.gz"
    assert resolved.sha256 == "abc123"
    assert resolved.source == "manifest exact (0.1.0)"


def test_resolve_artifact_manifest_minor_fallback(monkeypatch):
    monkeypatch.delenv("HOF_COMPONENTS_URL", raising=False)
    monkeypatch.setattr(
        add_cmd,
        "_load_components_manifest",
        lambda: {
            "artifacts": [
                {
                    "engine_version": "0.1.0",
                    "artifact_url": "https://example.com/older.tar.gz",
                },
                {
                    "engine_version": "0.1.4",
                    "artifact_url": "https://example.com/newer.tar.gz",
                },
            ]
        },
    )
    import hof

    monkeypatch.setattr(hof, "__version__", "0.1.9", raising=False)
    resolved = add_cmd._resolve_artifact()
    assert resolved.url == "https://example.com/newer.tar.gz"
    assert resolved.source == "manifest compatible (0.1.x)"


def test_resolve_artifact_errors_when_manifest_has_no_compatible_version(monkeypatch):
    monkeypatch.delenv("HOF_COMPONENTS_URL", raising=False)
    monkeypatch.setattr(
        add_cmd,
        "_load_components_manifest",
        lambda: {
            "artifacts": [
                {
                    "engine_version": "0.2.0",
                    "artifact_url": "https://example.com/v020.tar.gz",
                }
            ]
        },
    )
    import hof

    monkeypatch.setattr(hof, "__version__", "0.1.0", raising=False)
    with pytest.raises(add_cmd.typer.Exit):
        add_cmd._resolve_artifact()


def test_resolve_artifact_errors_when_manifest_unavailable(monkeypatch):
    monkeypatch.delenv("HOF_COMPONENTS_URL", raising=False)
    monkeypatch.setattr(add_cmd, "_load_components_manifest", lambda: None)
    import hof

    monkeypatch.setattr(hof, "__version__", "0.1.0", raising=False)
    with pytest.raises(add_cmd.typer.Exit):
        add_cmd._resolve_artifact()


def test_verify_archive_checksum_raises_on_mismatch(tmp_path: Path) -> None:
    archive = tmp_path / "artifact.tar.gz"
    archive.write_bytes(b"data")
    with pytest.raises(ValueError, match="Checksum mismatch"):
        add_cmd._verify_archive_checksum(archive, "deadbeef")
