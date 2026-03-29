"""Sandbox ships /usr/local/bin/hof — same mental model as host ``hof fn``."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_HOF_CLI = Path(__file__).resolve().parents[3] / "hof" / "agent" / "sandbox" / "hof_cli.sh"


def test_hof_cli_script_exists_and_is_valid_bash() -> None:
    assert _HOF_CLI.is_file()
    r = subprocess.run(
        ["bash", "-n", str(_HOF_CLI)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr


def test_hof_fn_list_runs_with_empty_catalog() -> None:
    """Smoke: `hof fn list` exits 0 with empty HOF_AGENT_SKILLS_CATALOG."""
    env = {**os.environ, "HOF_AGENT_SKILLS_CATALOG": ""}
    r = subprocess.run(
        ["bash", str(_HOF_CLI), "fn", "list"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 0
