"""Structured logging configuration for hof-engine.

Sets up a consistent log format across the server, CLI, and Celery workers.
Call ``configure_logging()`` once at process startup.

Format:
  - Development (debug=True):  human-readable with colours via rich
  - Production (debug=False):  JSON-structured lines for log aggregators
"""

from __future__ import annotations

import logging
import logging.config
from datetime import UTC
from typing import Any


def configure_logging(*, debug: bool = False, app_name: str = "hof") -> None:
    """Configure the root logger and hof-specific loggers.

    Args:
        debug:    When True, use a verbose human-readable format.
        app_name: Included in every log record as ``app`` field.
    """
    level = logging.DEBUG if debug else logging.INFO

    if debug:
        _configure_dev_logging(level, app_name)
    else:
        _configure_prod_logging(level, app_name)

    # Silence noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO if debug else logging.WARNING)
    logging.getLogger("celery").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Dev: rich-formatted, human-readable
# ---------------------------------------------------------------------------


def _configure_dev_logging(level: int, app_name: str) -> None:
    fmt = f"%(asctime)s [{app_name}] %(levelname)-8s %(name)s — %(message)s"
    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt="%H:%M:%S",
        force=True,
    )


# ---------------------------------------------------------------------------
# Prod: JSON-structured for log aggregators (Datadog, CloudWatch, etc.)
# ---------------------------------------------------------------------------


class _JsonFormatter(logging.Formatter):
    """Emit each log record as a single JSON line."""

    def __init__(self, app_name: str) -> None:
        super().__init__()
        self._app_name = app_name

    def format(self, record: logging.LogRecord) -> str:
        import json
        from datetime import datetime

        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "app": self._app_name,
            "msg": record.getMessage(),
        }

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        extra_skip = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
            "taskName",
        }
        for key, val in record.__dict__.items():
            if key not in extra_skip:
                payload[key] = val

        return json.dumps(payload, default=str)


def _configure_prod_logging(level: int, app_name: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter(app_name))

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)
