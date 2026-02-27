"""Auto-generated CRUD routes for all registered tables."""

from __future__ import annotations

from typing import Any, Generator

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError
from sqlalchemy.orm import Session

from hof.api.auth import verify_auth
from hof.core.registry import registry
from hof.db.engine import get_session
from hof.db.schemas import build_create_schema, build_update_schema

router = APIRouter()


def _get_sync_session() -> Generator[Session, None, None]:
    """FastAPI dependency that provides a request-scoped sync session."""
    with get_session() as session:
        yield session


@router.get("")
async def list_tables(user: str = Depends(verify_auth)) -> list[dict]:
    """List all registered tables."""
    result = []
    for name, table_cls in registry.tables.items():
        columns = [
            {"name": c.name, "type": str(c.type)}
            for c in table_cls.__table__.columns
        ]
        result.append({"name": name, "columns": columns})
    return result


@router.get("/{table_name}")
async def list_records(
    table_name: str,
    filter: str | None = Query(None, description="Filter: key:value,key:value"),
    order_by: str | None = Query(None),
    limit: int = Query(20, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None),
    user: str = Depends(verify_auth),
    session: Session = Depends(_get_sync_session),
) -> list[dict]:
    """List records from a table with optional filtering and pagination."""
    table_cls = registry.get_table(table_name)
    if table_cls is None:
        raise HTTPException(404, f"Table '{table_name}' not found")

    filters = _parse_filter_string(filter) if filter else {}
    records = table_cls.query(
        filters=filters, order_by=order_by, limit=limit, offset=offset, session=session
    )
    return [r.to_dict() for r in records]


@router.post("/{table_name}")
async def create_record(
    table_name: str,
    body: dict[str, Any],
    user: str = Depends(verify_auth),
    session: Session = Depends(_get_sync_session),
) -> dict:
    """Create a new record. Input is validated against the table schema."""
    table_cls = registry.get_table(table_name)
    if table_cls is None:
        raise HTTPException(404, f"Table '{table_name}' not found")

    schema = build_create_schema(table_cls)
    try:
        validated = schema(**body)
    except ValidationError as exc:
        raise HTTPException(422, detail=exc.errors())

    record = table_cls.create(**validated.model_dump(exclude_none=False), session=session)
    return record.to_dict()


@router.get("/{table_name}/{record_id}")
async def get_record(
    table_name: str,
    record_id: str,
    user: str = Depends(verify_auth),
    session: Session = Depends(_get_sync_session),
) -> dict:
    """Get a single record by ID."""
    table_cls = registry.get_table(table_name)
    if table_cls is None:
        raise HTTPException(404, f"Table '{table_name}' not found")

    record = table_cls.get(record_id, session=session)
    if record is None:
        raise HTTPException(404, f"Record '{record_id}' not found")
    return record.to_dict()


@router.put("/{table_name}/{record_id}")
async def update_record(
    table_name: str,
    record_id: str,
    body: dict[str, Any],
    user: str = Depends(verify_auth),
    session: Session = Depends(_get_sync_session),
) -> dict:
    """Update a record by ID. Only provided fields are changed."""
    table_cls = registry.get_table(table_name)
    if table_cls is None:
        raise HTTPException(404, f"Table '{table_name}' not found")

    schema = build_update_schema(table_cls)
    try:
        validated = schema(**body)
    except ValidationError as exc:
        raise HTTPException(422, detail=exc.errors())

    # Only pass fields that were explicitly provided (non-None after validation)
    updates = {k: v for k, v in validated.model_dump().items() if v is not None}
    record = table_cls.update(record_id, session=session, **updates)
    if record is None:
        raise HTTPException(404, f"Record '{record_id}' not found")
    return record.to_dict()


@router.delete("/{table_name}/{record_id}")
async def delete_record(
    table_name: str,
    record_id: str,
    user: str = Depends(verify_auth),
    session: Session = Depends(_get_sync_session),
) -> dict:
    """Delete a record by ID."""
    table_cls = registry.get_table(table_name)
    if table_cls is None:
        raise HTTPException(404, f"Table '{table_name}' not found")

    deleted = table_cls.delete(record_id, session=session)
    if not deleted:
        raise HTTPException(404, f"Record '{record_id}' not found")
    return {"deleted": True, "id": record_id}


def _parse_filter_string(filter_str: str) -> dict:
    """Parse 'key:value,key:value' filter string."""
    filters = {}
    for pair in filter_str.split(","):
        if ":" in pair:
            key, val = pair.split(":", 1)
            filters[key.strip()] = val.strip()
    return filters
