"""Table and Column base classes for schema-as-code."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator

import sqlalchemy as sa
from sqlalchemy import func
from sqlalchemy.orm import Mapped, Session, mapped_column

from hof.core.registry import registry
from hof.db.engine import Base, get_session


class Column:
    """Declarative column descriptor for hof tables.

    Collects metadata at class definition time; the actual SQLAlchemy column is
    created by the TableMeta metaclass.
    """

    def __init__(
        self,
        type_: Any,
        *,
        required: bool = False,
        nullable: bool = True,
        default: Any = None,
        unique: bool = False,
        index: bool = False,
        primary_key: bool = False,
        auto_now: bool = False,
        auto_now_update: bool = False,
    ):
        self.type_ = type_
        self.required = required
        self.nullable = not required if nullable is True else nullable
        self.default = default
        self.unique = unique
        self.index = index
        self.primary_key = primary_key
        self.auto_now = auto_now
        self.auto_now_update = auto_now_update
        self.name: str = ""  # Set by metaclass


class ForeignKey:
    """Declarative foreign key descriptor."""

    def __init__(
        self,
        target: type,
        *,
        nullable: bool = False,
        on_delete: str = "CASCADE",
    ):
        self.target = target
        self.nullable = nullable
        self.on_delete = on_delete
        self.name: str = ""  # Set by metaclass


class TableMeta(type(Base)):  # type: ignore[misc]
    """Metaclass that converts Column/ForeignKey descriptors into SQLAlchemy mapped columns."""

    def __new__(mcs, name: str, bases: tuple, namespace: dict, **kwargs: Any) -> Any:
        if name == "Table":
            return super().__new__(mcs, name, bases, namespace, **kwargs)

        hof_columns: dict[str, Column] = {}
        hof_fks: dict[str, ForeignKey] = {}

        for attr_name, attr_value in list(namespace.items()):
            if isinstance(attr_value, Column):
                attr_value.name = attr_name
                hof_columns[attr_name] = attr_value
            elif isinstance(attr_value, ForeignKey):
                attr_value.name = attr_name
                hof_fks[attr_name] = attr_value

        table_name = namespace.get("__tablename__", name.lower())
        namespace["__tablename__"] = table_name

        if "id" not in namespace and "id" not in hof_columns:
            namespace["id"] = mapped_column(
                sa.Uuid(),
                primary_key=True,
                default=uuid.uuid4,
            )

        has_created_at = "created_at" in hof_columns
        has_updated_at = "updated_at" in hof_columns

        for attr_name, col in hof_columns.items():
            sa_kwargs: dict[str, Any] = {
                "nullable": col.nullable,
                "unique": col.unique,
                "index": col.index,
            }

            if col.primary_key:
                sa_kwargs["primary_key"] = True

            if col.auto_now:
                sa_kwargs["server_default"] = func.now()
                sa_kwargs["default"] = lambda: datetime.now(timezone.utc)
            elif col.auto_now_update:
                sa_kwargs["server_default"] = func.now()
                sa_kwargs["onupdate"] = func.now()
                sa_kwargs["default"] = lambda: datetime.now(timezone.utc)
            elif col.default is not None:
                sa_kwargs["default"] = col.default

            namespace[attr_name] = mapped_column(col.type_, **sa_kwargs)

        for attr_name, fk in hof_fks.items():
            target_table = fk.target.__tablename__ if hasattr(fk.target, "__tablename__") else fk.target.__name__.lower()
            namespace[attr_name] = mapped_column(
                sa.Uuid(),
                sa.ForeignKey(f"{target_table}.id", ondelete=fk.on_delete),
                nullable=fk.nullable,
            )

        if not has_created_at:
            namespace["created_at"] = mapped_column(
                sa.DateTime(timezone=True),
                server_default=func.now(),
                default=lambda: datetime.now(timezone.utc),
            )

        if not has_updated_at:
            namespace["updated_at"] = mapped_column(
                sa.DateTime(timezone=True),
                server_default=func.now(),
                onupdate=func.now(),
                default=lambda: datetime.now(timezone.utc),
            )

        cls = super().__new__(mcs, name, bases, namespace, **kwargs)
        registry.register_table(cls)
        return cls


class Table(Base, metaclass=TableMeta):
    """Base class for user-defined tables.

    Subclass this and define columns using Column() descriptors:

        class Document(Table):
            name = Column(types.String, required=True)
            status = Column(types.String, default="pending")

    All class methods accept an optional ``session`` keyword argument.  When
    provided, the operation runs inside the caller's session (enabling
    multi-table transactions).  When omitted, a new auto-committed session is
    opened for that call.

    Example — multi-table transaction:
        with get_session() as session:
            lead = Lead.create(name="Alice", session=session)
            EnrichmentResult.create(lead_id=lead.id, session=session)
            # both committed together when the `with` block exits
    """

    __abstract__ = True

    # ------------------------------------------------------------------
    # Session helper
    # ------------------------------------------------------------------

    @classmethod
    @contextmanager
    def _session_scope(
        cls, session: Session | None
    ) -> Generator[Session, None, None]:
        """Yield the provided session, or open a new auto-commit one."""
        if session is not None:
            yield session
        else:
            with get_session() as s:
                yield s

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize the record to a dictionary."""
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    @classmethod
    def create(cls, *, session: Session | None = None, **kwargs: Any) -> "Table":
        """Create and persist a new record.

        Args:
            session: Optional external session for multi-table transactions.
            **kwargs: Column values for the new record.
        """
        if "id" not in kwargs:
            kwargs["id"] = uuid.uuid4()
        instance = cls(**kwargs)
        with cls._session_scope(session) as s:
            s.add(instance)
            s.flush()
            s.refresh(instance)
        return instance

    @classmethod
    def get(cls, record_id: Any, *, session: Session | None = None) -> "Table | None":
        """Get a record by primary key."""
        with cls._session_scope(session) as s:
            return s.get(cls, record_id)

    @classmethod
    def query(
        cls,
        *,
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
        limit: int = 100,
        offset: int = 0,
        session: Session | None = None,
    ) -> list["Table"]:
        """Query records with optional filtering, sorting, and pagination."""
        with cls._session_scope(session) as s:
            stmt = sa.select(cls)

            if filters:
                for key, value in filters.items():
                    if "__" in key:
                        field_name, op = key.rsplit("__", 1)
                        col = getattr(cls, field_name, None)
                        if col is not None:
                            if op == "lt":
                                stmt = stmt.where(col < value)
                            elif op == "gt":
                                stmt = stmt.where(col > value)
                            elif op == "lte":
                                stmt = stmt.where(col <= value)
                            elif op == "gte":
                                stmt = stmt.where(col >= value)
                            elif op == "ne":
                                stmt = stmt.where(col != value)
                            elif op == "in":
                                stmt = stmt.where(col.in_(value))
                    else:
                        col = getattr(cls, key, None)
                        if col is not None:
                            stmt = stmt.where(col == value)

            if order_by:
                desc = order_by.startswith("-")
                field_name = order_by.lstrip("-")
                col = getattr(cls, field_name, None)
                if col is not None:
                    stmt = stmt.order_by(col.desc() if desc else col.asc())

            stmt = stmt.limit(limit).offset(offset)
            return list(s.scalars(stmt).all())

    @classmethod
    def update(
        cls,
        record_id: Any,
        *,
        session: Session | None = None,
        **kwargs: Any,
    ) -> "Table | None":
        """Update a record by primary key."""
        with cls._session_scope(session) as s:
            instance = s.get(cls, record_id)
            if instance is None:
                return None
            for key, value in kwargs.items():
                setattr(instance, key, value)
            s.flush()
            s.refresh(instance)
            return instance

    @classmethod
    def delete(
        cls, record_id: Any, *, session: Session | None = None
    ) -> bool:
        """Delete a record by primary key."""
        with cls._session_scope(session) as s:
            instance = s.get(cls, record_id)
            if instance is None:
                return False
            s.delete(instance)
            return True

    @classmethod
    def count(
        cls,
        *,
        filters: dict[str, Any] | None = None,
        session: Session | None = None,
    ) -> int:
        """Count records with optional filtering."""
        with cls._session_scope(session) as s:
            stmt = sa.select(func.count()).select_from(cls)
            if filters:
                for key, value in filters.items():
                    col = getattr(cls, key, None)
                    if col is not None:
                        stmt = stmt.where(col == value)
            return s.scalar(stmt) or 0

    @classmethod
    def bulk_create(
        cls,
        records: list[dict[str, Any]],
        *,
        session: Session | None = None,
    ) -> list["Table"]:
        """Create multiple records at once."""
        instances = []
        with cls._session_scope(session) as s:
            for data in records:
                if "id" not in data:
                    data["id"] = uuid.uuid4()
                instance = cls(**data)
                s.add(instance)
                instances.append(instance)
            s.flush()
            for inst in instances:
                s.refresh(inst)
        return instances

    @classmethod
    def bulk_delete(
        cls,
        *,
        filters: dict[str, Any],
        session: Session | None = None,
    ) -> int:
        """Delete multiple records matching filters. Returns count deleted."""
        with cls._session_scope(session) as s:
            stmt = sa.delete(cls)
            for key, value in filters.items():
                if "__" in key:
                    field_name, op = key.rsplit("__", 1)
                    col = getattr(cls, field_name, None)
                    if col is not None and op == "lt":
                        stmt = stmt.where(col < value)
                else:
                    col = getattr(cls, key, None)
                    if col is not None:
                        stmt = stmt.where(col == value)
            result = s.execute(stmt)
            return result.rowcount
