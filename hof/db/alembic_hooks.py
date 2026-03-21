"""Alembic env.py hooks (autogenerate fixes shared across hof apps)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa


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
