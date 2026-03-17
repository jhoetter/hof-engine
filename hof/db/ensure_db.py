"""Ensure the target database exists before running migrations.

When a Hetzner volume is reattached to a new project, PostgreSQL's pgdata
already exists so the ``POSTGRES_DB`` env var is ignored.  This script
connects to the default ``postgres`` database and creates the target
database if it doesn't exist yet.

Usage (in Dockerfile CMD):
    python -m hof.db.ensure_db && hof db migrate && uvicorn ...

Reads DATABASE_URL from the environment (or hof.config.py) to determine
the target database name, user, and password.
"""

from __future__ import annotations

import logging
import os
import sys
from urllib.parse import urlparse

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("hof.db.ensure_db")


def _parse_database_url() -> tuple[str, str, str, str, int]:
    """Return (host, port, user, password, dbname) from DATABASE_URL."""
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        try:
            from pathlib import Path

            from hof.config import load_config

            config = load_config(Path.cwd(), strict=False)
            url = config.database_url
        except Exception:
            pass

    if not url:
        logger.info("No DATABASE_URL found, skipping ensure_db.")
        sys.exit(0)

    parsed = urlparse(url)
    return (
        parsed.hostname or "localhost",
        parsed.port or 5432,
        parsed.username or "postgres",
        parsed.password or "",
        (parsed.path or "/app").lstrip("/") or "app",
    )


def main() -> None:
    host, port, user, password, dbname = _parse_database_url()

    if dbname == "postgres":
        logger.info("Target database is 'postgres' (default), nothing to ensure.")
        return

    import psycopg2  # type: ignore[import-untyped]

    logger.info("Ensuring database '%s' exists on %s:%s ...", dbname, host, port)

    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname="postgres",
            connect_timeout=10,
        )
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
        if cur.fetchone():
            logger.info("Database '%s' already exists.", dbname)
        else:
            cur.execute(f'CREATE DATABASE "{dbname}"')
            logger.info("Created database '%s'.", dbname)
        cur.close()
        conn.close()
    except Exception as exc:
        logger.warning("ensure_db failed (non-fatal, migrations may still work): %s", exc)


if __name__ == "__main__":
    main()
