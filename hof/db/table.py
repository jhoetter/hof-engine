"""Table and Column base classes for schema-as-code."""

from __future__ import annotations

import uuid
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import func
from sqlalchemy.orm import Session, mapped_column

from hof.core.registry import registry
from hof.db.engine import Base, get_session
from hof.db.window import WindowColumn


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
                sa_kwargs["default"] = lambda: datetime.now(UTC)
            elif col.auto_now_update:
                sa_kwargs["server_default"] = func.now()
                sa_kwargs["onupdate"] = func.now()
                sa_kwargs["default"] = lambda: datetime.now(UTC)
            elif col.default is not None:
                sa_kwargs["default"] = col.default

            namespace[attr_name] = mapped_column(col.type_, **sa_kwargs)

        for attr_name, fk in hof_fks.items():
            target_table = (
                fk.target.__tablename__
                if hasattr(fk.target, "__tablename__")
                else fk.target.__name__.lower()
            )
            namespace[attr_name] = mapped_column(
                sa.Uuid(),
                sa.ForeignKey(f"{target_table}.id", ondelete=fk.on_delete),
                nullable=fk.nullable,
            )

        if not has_created_at:
            namespace["created_at"] = mapped_column(
                sa.DateTime(timezone=True),
                server_default=func.now(),
                default=lambda: datetime.now(UTC),
            )

        if not has_updated_at:
            namespace["updated_at"] = mapped_column(
                sa.DateTime(timezone=True),
                server_default=func.now(),
                onupdate=func.now(),
                default=lambda: datetime.now(UTC),
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
    def _session_scope(cls, session: Session | None) -> Generator[Session, None, None]:
        """Yield the provided session, or open a new auto-commit one."""
        if session is not None:
            yield session
        else:
            with get_session() as s:
                yield s

    @classmethod
    def _apply_filters(cls, stmt: Any, filters: dict[str, Any]) -> Any:
        """Apply a filter dict to a SQLAlchemy select statement.

        Supported operators (suffix after ``__``):
          lt, gt, lte, gte, ne, in, ilike
        No suffix = exact equality match.
        """
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
                    elif op == "ilike":
                        stmt = stmt.where(col.ilike(f"%{value}%"))
            else:
                col = getattr(cls, key, None)
                if col is not None:
                    stmt = stmt.where(col == value)
        return stmt

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
    def create(cls, *, session: Session | None = None, **kwargs: Any) -> Table:
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
    def get(cls, record_id: Any, *, session: Session | None = None) -> Table | None:
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
    ) -> list[Table]:
        """Query records with optional filtering, sorting, and pagination."""
        with cls._session_scope(session) as s:
            stmt = sa.select(cls)

            if filters:
                stmt = cls._apply_filters(stmt, filters)

            if order_by:
                desc = order_by.startswith("-")
                field_name = order_by.lstrip("-")
                col = getattr(cls, field_name, None)
                if col is not None:
                    stmt = stmt.order_by(col.desc() if desc else col.asc())

            stmt = stmt.limit(limit).offset(offset)
            return list(s.scalars(stmt).all())

    @classmethod
    def query_with_windows(
        cls,
        *,
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
        secondary_order_by: str | None = None,
        limit: int = 100,
        offset: int = 0,
        window_columns: list[WindowColumn] | None = None,
        window_filters: dict[str, Any] | None = None,
        session: Session | None = None,
    ) -> list[dict[str, Any]]:
        """Query records and append SQL window function columns to each row.

        Builds a CTE from the base query (with filters and ordering), then
        wraps it with window expressions. Returns plain dicts so that the extra
        window columns — which are not ORM model attributes — can be included.

        Args:
            filters:        Same filter syntax as ``query()``. Applied before
                            window functions (affects what window functions see).
            order_by:       Column name to order by (prefix ``-`` for DESC).
            secondary_order_by: Optional tiebreaker column (same prefix syntax).
            limit:          Maximum rows to return.
            offset:         Row offset for pagination.
            window_columns: Window function specifications. If None or empty,
                            behaves identically to ``query()`` but returns dicts.
            window_filters: Filters applied *after* window functions, on the
                            computed columns (e.g. ``running_total__gte=100``).
                            Uses the same operator syntax as ``filters``.
            session:        Optional external session.

        Returns:
            List of dicts, each containing all model columns plus any computed
            window columns keyed by ``WindowColumn.key``.
        """
        with cls._session_scope(session) as s:
            # ----------------------------------------------------------------
            # 1. Base query: filters + ordering (no limit/offset yet — window
            #    functions must see the full ordered dataset before slicing).
            # ----------------------------------------------------------------
            base_stmt = sa.select(cls)

            if filters:
                base_stmt = cls._apply_filters(base_stmt, filters)

            if order_by:
                desc = order_by.startswith("-")
                field_name = order_by.lstrip("-")
                col = getattr(cls, field_name, None)
                if col is not None:
                    base_stmt = base_stmt.order_by(
                        col.desc() if desc else col.asc()
                    )

            if secondary_order_by:
                _desc2 = secondary_order_by.startswith("-")
                _fname2 = secondary_order_by.lstrip("-")
                _col2 = getattr(cls, _fname2, None)
                if _col2 is not None:
                    base_stmt = base_stmt.order_by(
                        _col2.desc() if _desc2 else _col2.asc()
                    )

            # Always append primary key as ultimate tiebreaker for deterministic
            # ordering (critical for bulk-inserted rows sharing the same timestamps).
            base_stmt = base_stmt.order_by(cls.id.asc())

            if not window_columns:
                # No window functions requested — add limit/offset and return dicts.
                base_stmt = base_stmt.limit(limit).offset(offset)
                instances = list(s.scalars(base_stmt).all())
                return [inst.to_dict() for inst in instances]

            # ----------------------------------------------------------------
            # 2. Wrap in a CTE so window functions can reference it cleanly.
            # ----------------------------------------------------------------
            cte = base_stmt.cte("base")

            # ----------------------------------------------------------------
            # 3. Build window expressions for each WindowColumn.
            # ----------------------------------------------------------------
            def _order_clause(wc: WindowColumn) -> list:
                col = cte.c[wc.order_by]
                primary = col.desc() if wc.order_dir == "desc" else col.asc()
                return [primary, cte.c["id"].asc()]

            def _partition(wc: WindowColumn) -> list:
                return [cte.c[f] for f in wc.partition_by] if wc.partition_by else []

            def _over(wc: WindowColumn, **extra: Any) -> sa.Over:
                return sa.over(
                    extra.pop("agg"),
                    partition_by=_partition(wc),
                    order_by=_order_clause(wc),
                    **extra,
                )

            window_exprs: list[Any] = []
            for wc in window_columns:
                over_col = cte.c[wc.over] if wc.over else None

                match wc.fn:
                    case "row_number":
                        expr = sa.over(
                            func.row_number(),
                            partition_by=_partition(wc),
                            order_by=_order_clause(wc),
                        )
                    case "running_sum":
                        expr = sa.over(
                            func.sum(over_col),
                            partition_by=_partition(wc),
                            order_by=_order_clause(wc),
                            rows=(None, 0),
                        )
                    case "running_avg":
                        expr = sa.over(
                            func.avg(over_col),
                            partition_by=_partition(wc),
                            order_by=_order_clause(wc),
                            rows=(None, 0),
                        )
                    case "cumulative_count":
                        expr = sa.over(
                            func.count(),
                            partition_by=_partition(wc),
                            order_by=_order_clause(wc),
                            rows=(None, 0),
                        )
                    case "rank":
                        rank_order = [over_col.desc(), cte.c["id"].asc()]
                        expr = sa.over(
                            func.rank(),
                            partition_by=_partition(wc),
                            order_by=rank_order,
                        )
                    case "lag":
                        expr = sa.over(
                            func.lag(over_col, wc.offset),
                            partition_by=_partition(wc),
                            order_by=_order_clause(wc),
                        )
                    case "lead":
                        expr = sa.over(
                            func.lead(over_col, wc.offset),
                            partition_by=_partition(wc),
                            order_by=_order_clause(wc),
                        )
                    case "delta":
                        # current - previous: expressed as col - LAG(col, 1)
                        lag_expr = sa.over(
                            func.lag(over_col, 1),
                            partition_by=_partition(wc),
                            order_by=_order_clause(wc),
                        )
                        expr = over_col - lag_expr
                    case "pct_of_total":
                        total_expr = sa.over(
                            func.sum(over_col),
                            partition_by=_partition(wc),
                        )
                        expr = over_col * sa.cast(100.0, sa.Float) / total_expr
                    case "moving_avg":
                        expr = sa.over(
                            func.avg(over_col),
                            partition_by=_partition(wc),
                            order_by=_order_clause(wc),
                            rows=(-(wc.frame_size - 1), 0),
                        )
                    case _:
                        raise ValueError(f"Unknown window function: {wc.fn!r}")

                window_exprs.append(expr.label(wc.key))

            # ----------------------------------------------------------------
            # 4. Wrap window results in a second CTE if window_filters exist,
            #    then paginate.
            # ----------------------------------------------------------------
            window_stmt = sa.select(cte, *window_exprs)

            if window_filters:
                # Wrap in a subquery so we can WHERE on the window columns.
                window_cte = window_stmt.cte("windowed")
                outer_stmt = sa.select(window_cte)
                for key, value in window_filters.items():
                    if "__" in key:
                        field_name, op = key.rsplit("__", 1)
                        wcol = window_cte.c.get(field_name)
                        if wcol is not None:
                            if op == "lt":
                                outer_stmt = outer_stmt.where(wcol < value)
                            elif op == "gt":
                                outer_stmt = outer_stmt.where(wcol > value)
                            elif op == "lte":
                                outer_stmt = outer_stmt.where(wcol <= value)
                            elif op == "gte":
                                outer_stmt = outer_stmt.where(wcol >= value)
                            elif op == "ne":
                                outer_stmt = outer_stmt.where(wcol != value)
                            elif op == "in":
                                outer_stmt = outer_stmt.where(wcol.in_(value))
                            elif op == "ilike":
                                outer_stmt = outer_stmt.where(wcol.ilike(f"%{value}%"))
                    else:
                        wcol = window_cte.c.get(key)
                        if wcol is not None:
                            outer_stmt = outer_stmt.where(wcol == value)
            else:
                outer_stmt = window_stmt

            # Re-apply ordering on the outer query — ORDER BY inside a CTE
            # is not guaranteed to propagate to the outer SELECT.
            if order_by:
                _desc = order_by.startswith("-")
                _fname = order_by.lstrip("-")
                _src = window_cte if window_filters else cte
                _ocol = _src.c.get(_fname)
                if _ocol is not None:
                    outer_stmt = outer_stmt.order_by(
                        _ocol.desc() if _desc else _ocol.asc()
                    )

            if secondary_order_by:
                _desc2o = secondary_order_by.startswith("-")
                _fname2o = secondary_order_by.lstrip("-")
                _src2 = window_cte if window_filters else cte
                _ocol2 = _src2.c.get(_fname2o)
                if _ocol2 is not None:
                    outer_stmt = outer_stmt.order_by(
                        _ocol2.desc() if _desc2o else _ocol2.asc()
                    )

            # Ultimate tiebreaker on outer query (CTE ordering doesn't propagate).
            _src_id = window_cte if window_filters else cte
            _ocol_id = _src_id.c.get("id")
            if _ocol_id is not None:
                outer_stmt = outer_stmt.order_by(_ocol_id.asc())

            outer_stmt = outer_stmt.limit(limit).offset(offset)
            rows = s.execute(outer_stmt).mappings().all()
            return [dict(r) for r in rows]

    @classmethod
    def update(
        cls,
        record_id: Any,
        *,
        session: Session | None = None,
        **kwargs: Any,
    ) -> Table | None:
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
    def delete(cls, record_id: Any, *, session: Session | None = None) -> bool:
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
    ) -> list[Table]:
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
