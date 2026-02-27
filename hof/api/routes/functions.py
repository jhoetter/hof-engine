"""Auto-generated routes for registered functions."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from hof.api.auth import verify_auth
from hof.core.registry import registry
from hof.db.schemas import build_function_input_schema

router = APIRouter()


@router.get("")
async def list_functions(user: str = Depends(verify_auth)) -> list[dict]:
    """List all registered functions."""
    return [meta.to_dict() for meta in registry.functions.values()]


@router.post("/{function_name}")
async def call_function(
    function_name: str,
    body: dict[str, Any] | None = None,
    user: str = Depends(verify_auth),
) -> dict:
    """Execute a registered function. Input is validated against the function signature."""
    meta = registry.get_function(function_name)
    if meta is None:
        raise HTTPException(404, f"Function '{function_name}' not found")

    kwargs = body or {}

    # Validate inputs if the function has declared parameters
    if meta.parameters:
        schema = build_function_input_schema(meta)
        try:
            validated = schema(**kwargs)
        except ValidationError as exc:
            raise HTTPException(422, detail=exc.errors())
        kwargs = validated.model_dump(exclude_none=False)

    start = time.monotonic()

    try:
        if meta.is_async:
            result = await meta.fn(**kwargs)
        else:
            result = meta.fn(**kwargs)
    except Exception as exc:
        raise HTTPException(500, f"Function error: {exc}")

    duration_ms = int((time.monotonic() - start) * 1000)

    return {
        "result": result,
        "duration_ms": duration_ms,
        "function": function_name,
    }


@router.get("/{function_name}/schema")
async def get_function_schema(
    function_name: str,
    user: str = Depends(verify_auth),
) -> dict:
    """Get the input/output schema of a function."""
    meta = registry.get_function(function_name)
    if meta is None:
        raise HTTPException(404, f"Function '{function_name}' not found")

    return meta.to_dict()
