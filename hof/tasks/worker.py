"""Celery worker management utilities."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from hof.config import get_config


def start_worker(project_root: Path | None = None) -> subprocess.Popen:
    """Start a Celery worker process."""
    config = get_config()

    cmd = [
        sys.executable, "-m", "celery",
        "-A", "hof.tasks.celery_app:celery",
        "worker",
        "--loglevel=info",
        f"--concurrency={config.celery_concurrency}",
    ]

    return subprocess.Popen(
        cmd,
        cwd=str(project_root or Path.cwd()),
    )


def start_beat(project_root: Path | None = None) -> subprocess.Popen:
    """Start the Celery Beat scheduler for cron jobs."""
    cmd = [
        sys.executable, "-m", "celery",
        "-A", "hof.tasks.celery_app:celery",
        "beat",
        "--loglevel=info",
    ]

    return subprocess.Popen(
        cmd,
        cwd=str(project_root or Path.cwd()),
    )
