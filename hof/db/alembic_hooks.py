"""Alembic env.py hooks (autogenerate fixes shared across hof apps).

Public API
----------
- ``process_revision_directives`` — combined dispatcher; use this in env.py.
- ``process_revision_directives_postgres_uuid_using`` — legacy single hook
  (kept for backward compatibility with older env.py files).
- ``strip_serial_pk_nullable_ops`` — standalone callable for the SERIAL PK fix.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

# ---------------------------------------------------------------------------
# Hook 1: VARCHAR → UUID USING clause
# ---------------------------------------------------------------------------


def process_revision_directives_postgres_uuid_using(context, revision, directives) -> None:
    """Inject ``postgresql_using`` when autogenerate alters String/VARCHAR → UUID.

    PostgreSQL rejects ``ALTER COLUMN … TYPE uuid`` without an explicit ``USING`` clause
    when the existing type is not assignment-cast compatible.
    """
    cmd = getattr(context.config, "cmd_opts", None)
    if cmd is None or not getattr(cmd, "autogenerate", False):
        return
    if not directives:
        return

    from alembic.operations.ops import AlterColumnOp, OpContainer

    def is_textual(t: Any) -> bool:
        if t is None:
            return False
        if isinstance(t, (sa.String, sa.Text)):
            return True
        vn = getattr(t, "__visit_name__", None)
        return vn in ("string", "text", "unicode")

    def is_uuid_type(t: Any) -> bool:
        if t is None:
            return False
        try:
            return isinstance(t, sa.Uuid)
        except Exception:
            return False

    def walk_ops(ops: Sequence[Any]) -> list[AlterColumnOp]:
        out: list[AlterColumnOp] = []
        for op in ops:
            if isinstance(op, AlterColumnOp):
                out.append(op)
            elif isinstance(op, OpContainer):
                out.extend(walk_ops(op.ops))
        return out

    for directive in directives:
        containers = getattr(directive, "upgrade_ops_list", None) or []
        if not containers and getattr(directive, "upgrade_ops", None) is not None:
            containers = [directive.upgrade_ops]
        for upgrade_ops in containers:
            if upgrade_ops is None:
                continue
            for op in walk_ops(upgrade_ops.ops):
                if op.modify_type is None:
                    continue
                if not is_textual(op.existing_type) or not is_uuid_type(op.modify_type):
                    continue
                col = op.column_name
                op.kw.setdefault(
                    "postgresql_using",
                    f"(CASE WHEN {col} IS NULL OR btrim({col}::text) = '' "
                    f"THEN NULL ELSE {col}::uuid END)",
                )


# ---------------------------------------------------------------------------
# Hook 2: Strip spurious ALTER COLUMN id nullable ops (SERIAL PK drift)
# ---------------------------------------------------------------------------


def strip_serial_pk_nullable_ops(directives) -> None:
    """Drop ``ALTER COLUMN … id DROP NOT NULL`` that autogenerate emits for SERIAL PKs.

    PostgreSQL reflects SERIAL ``id`` as nullable in some introspection paths;
    applying the resulting migration fails with:
    ``column "id" is in a primary key``.
    """
    if not directives:
        return

    from alembic.operations.ops import AlterColumnOp, OpContainer

    def _walk_and_strip(ops: list) -> list:
        out: list = []
        for op in ops:
            if isinstance(op, AlterColumnOp):
                if op.column_name == "id" and (
                    op.modify_nullable is True
                    or op.kw.get("nullable") is True
                    or getattr(op, "nullable", None) is True
                ):
                    continue
                out.append(op)
            elif isinstance(op, OpContainer):
                nested = _walk_and_strip(list(op.ops))
                if nested:
                    op.ops = nested
                    out.append(op)
            else:
                out.append(op)
        return out

    for directive in directives:
        containers = getattr(directive, "upgrade_ops_list", None) or []
        if not containers and getattr(directive, "upgrade_ops", None) is not None:
            containers = [directive.upgrade_ops]
        for upgrade_ops in containers:
            if upgrade_ops is None:
                continue
            upgrade_ops.ops = _walk_and_strip(list(upgrade_ops.ops))


# ---------------------------------------------------------------------------
# Hook 3: Suppress empty revisions
# ---------------------------------------------------------------------------


def _suppress_empty_revision(directives) -> None:
    """Clear *directives* when autogenerate finds nothing to change."""
    if not directives:
        return
    script = directives[0]
    ops_list = getattr(script, "upgrade_ops_list", None)
    if ops_list and all(op.is_empty() for op in ops_list):
        directives.clear()


# ---------------------------------------------------------------------------
# Combined dispatcher — use this in env.py
# ---------------------------------------------------------------------------


def process_revision_directives(context, revision, directives) -> None:
    """Combined ``process_revision_directives`` for all hof autogenerate fixes.

    Chains (in order):
    1. VARCHAR → UUID ``postgresql_using`` injection
    2. SERIAL PK nullable-drift stripping
    3. Empty-revision suppression
    """
    process_revision_directives_postgres_uuid_using(context, revision, directives)
    strip_serial_pk_nullable_ops(directives)
    _suppress_empty_revision(directives)
