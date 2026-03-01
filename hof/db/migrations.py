"""Alembic integration for automatic migrations."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from alembic import command
from alembic.config import Config as AlembicConfig

if TYPE_CHECKING:
    from hof.config import Config


def _get_alembic_config(project_root: Path, config: Config) -> AlembicConfig:
    """Build an Alembic config pointing at the project's migrations directory."""
    migrations_dir = project_root / "migrations"
    migrations_dir.mkdir(exist_ok=True)

    versions_dir = migrations_dir / "versions"
    versions_dir.mkdir(exist_ok=True)

    alembic_cfg = AlembicConfig()
    alembic_cfg.set_main_option("script_location", str(migrations_dir))
    alembic_cfg.set_main_option("sqlalchemy.url", config.database_url)

    env_py = migrations_dir / "env.py"
    if not env_py.exists():
        _create_env_py(env_py)

    script_py = migrations_dir / "script.py.mako"
    if not script_py.exists():
        _create_script_mako(script_py)

    return alembic_cfg


def run_migrations(project_root: Path, config: Config, *, dry_run: bool = False) -> None:
    """Apply pending migrations, then autogenerate new ones if models changed."""
    alembic_cfg = _get_alembic_config(project_root, config)

    command.upgrade(alembic_cfg, "head")

    command.revision(
        alembic_cfg,
        message="auto-generated",
        autogenerate=True,
    )

    if not dry_run:
        command.upgrade(alembic_cfg, "head")


def rollback_migrations(project_root: Path, config: Config, *, steps: int = 1) -> None:
    """Rollback migrations by N steps."""
    alembic_cfg = _get_alembic_config(project_root, config)
    command.downgrade(alembic_cfg, f"-{steps}")


def get_migration_history(project_root: Path, config: Config) -> list[str]:
    """Get migration history as a list of revision strings."""
    alembic_cfg = _get_alembic_config(project_root, config)
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(alembic_cfg)
    revisions = []
    for rev in script.walk_revisions():
        revisions.append(f"{rev.revision[:12]} - {rev.doc}")
    return revisions


def get_current_revision(project_root: Path, config: Config) -> str | None:
    """Get the current applied revision."""
    from sqlalchemy import create_engine, text

    engine = create_engine(config.database_url)
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version_num FROM alembic_version"))
            row = result.fetchone()
            return row[0] if row else None
    except Exception:
        return None
    finally:
        engine.dispose()


def _create_env_py(path: Path) -> None:
    """Create the Alembic env.py for auto-generated migrations."""
    path.write_text("""\
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

config = context.config

from hof.db.engine import Base
import hof.flows.models  # noqa: F401 — register flow execution tables
target_metadata = Base.metadata


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
""")


def _create_script_mako(path: Path) -> None:
    """Create the Alembic script.py.mako template."""
    path.write_text('''\
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
''')
