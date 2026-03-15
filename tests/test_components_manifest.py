"""Verify the components manifest points to a valid, extractable artifact.

These tests are marked ``integration`` because they download from GitHub.
Run with: ``pytest -m integration tests/test_components_manifest.py``
"""

from __future__ import annotations

import hashlib
import json
import tarfile
import tempfile
import urllib.request
from pathlib import Path

import pytest

MANIFEST_PATH = Path(__file__).resolve().parents[1] / "hof" / "components-manifest.json"


@pytest.fixture(scope="module")
def manifest():
    assert MANIFEST_PATH.exists(), "components-manifest.json not found"
    return json.loads(MANIFEST_PATH.read_text())


def test_manifest_has_artifacts(manifest):
    artifacts = manifest.get("artifacts", [])
    assert len(artifacts) > 0, "Manifest has no artifacts"


def test_all_artifacts_have_required_fields(manifest):
    for entry in manifest["artifacts"]:
        for field in ("engine_version", "artifact_url", "sha256"):
            assert field in entry, f"Artifact missing field '{field}': {entry}"


@pytest.mark.integration
def test_latest_artifact_downloads_and_extracts(manifest):
    """Download the latest artifact and verify it extracts without symlinks."""
    entry = manifest["artifacts"][0]
    url = entry["artifact_url"]
    expected_sha = entry["sha256"]

    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        urllib.request.urlretrieve(url, tmp_path)

        digest = hashlib.sha256()
        with open(tmp_path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        actual_sha = digest.hexdigest()
        assert actual_sha.lower() == expected_sha.lower(), (
            f"SHA256 mismatch: expected {expected_sha}, got {actual_sha}"
        )

        with tarfile.open(tmp_path, "r:gz") as tar:
            names = [m.name for m in tar.getmembers()]
            symlinks = [m.name for m in tar.getmembers() if m.issym() or m.islnk()]
            assert not symlinks, f"Artifact contains symlinks: {symlinks}"

            assert any("registry.json" in n for n in names), "Artifact missing registry.json"
            assert any("modules/" in n for n in names), "Artifact missing modules/ directory"
            assert any("templates/" in n for n in names), "Artifact missing templates/ directory"
            assert any("modules/dashboard/ui/pages/index.tsx" in n for n in names), (
                "Artifact missing modules/dashboard/ui/pages/index.tsx"
            )
    finally:
        Path(tmp_path).unlink(missing_ok=True)
