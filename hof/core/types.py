"""Column type system mapping Python types to SQLAlchemy / PostgreSQL types."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


class _TypeNamespace:
    """Namespace providing column type constructors.

    Usage:
        from hof import types
        Column(types.String, required=True)
        Column(types.Enum("a", "b", "c"), default="a")
    """

    String = sa.String(255)
    Text = sa.Text()
    Integer = sa.Integer()
    Float = sa.Float()
    Boolean = sa.Boolean()
    DateTime = sa.DateTime(timezone=True)
    Date = sa.Date()
    JSON = postgresql.JSONB()
    UUID = sa.Uuid()
    File = sa.String(1024)

    @staticmethod
    def Enum(*values: str) -> sa.String:  # noqa: N802
        """Validated string column constrained to a set of allowed values.

        Stored as VARCHAR with a CHECK constraint generated at migration time.
        """
        col_type = sa.String(255)
        col_type._hof_enum_values = tuple(values)  # type: ignore[attr-defined]
        return col_type

    @staticmethod
    def String_(length: int = 255) -> sa.String:  # noqa: N802
        """String with custom max length."""
        return sa.String(length)


types = _TypeNamespace()
