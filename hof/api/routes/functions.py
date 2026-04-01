"""Auto-generated routes for registered functions."""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Security
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBasicCredentials
from pydantic import ValidationError

from hof.agent.http_mutation_gate import defer_mutation_if_terminal_agent_http
from hof.agent.sandbox.mutation_bridge import (
    AGENT_RUN_HEADER_NAME,
    AGENT_TOOL_CALL_HEADER_NAME,
)
from hof.api.auth import api_key_header, basic_auth, oauth2_scheme, verify_auth
from hof.core.registry import registry
from hof.db.schemas import build_function_input_schema

router = APIRouter()


async def _optional_auth(
    request: Request,
    bearer_token: str | None = Depends(oauth2_scheme),
    api_key: str | None = Security(api_key_header),
    credentials: HTTPBasicCredentials | None = Depends(basic_auth),
) -> str:
    """Resolve auth only when the target function is not public.

    Public functions (``@function(public=True)``) skip authentication entirely.
    """
    function_name = request.path_params.get("function_name")
    if function_name:
        meta = registry.get_function(function_name)
        if meta and meta.public:
            return "anonymous"
    return await verify_auth(
        request,
        bearer_token=bearer_token,
        api_key=api_key,
        credentials=credentials,
    )


@router.get("")
async def list_functions(user: str = Depends(verify_auth)) -> list[dict]:
    """List all registered functions."""
    return [meta.to_dict() for meta in registry.functions.values()]


@router.post("/{function_name}/stream")
async def call_function_stream(
    function_name: str,
    body: dict[str, Any] | None = Body(default=None),
    user: str = Depends(_optional_auth),
) -> StreamingResponse:
    """Stream NDJSON from a registered ``stream`` generator (same auth/body as POST /{name})."""
    meta = registry.get_function(function_name)
    if meta is None:
        raise HTTPException(404, f"Function '{function_name}' not found")
    if meta.stream_fn is None:
        raise HTTPException(404, f"Function '{function_name}' has no stream endpoint")

    kwargs = body or {}
    if meta.parameters:
        schema = build_function_input_schema(meta)
        try:
            validated = schema(**kwargs)
        except ValidationError as exc:
            raise HTTPException(422, detail=exc.errors())
        kwargs = validated.model_dump(exclude_none=False, by_alias=True)

    def ndjson_bytes() -> Any:
        try:
            for ev in meta.stream_fn(**kwargs):
                line = json.dumps(ev, default=str, ensure_ascii=False) + "\n"
                yield line.encode("utf-8")
        except Exception as exc:
            err_line = (
                json.dumps({"type": "error", "detail": str(exc)}, ensure_ascii=False)
                + "\n"
            )
            yield err_line.encode("utf-8")

    return StreamingResponse(
        ndjson_bytes(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{function_name}")
async def call_function(
    function_name: str,
    request: Request,
    body: dict[str, Any] | None = None,
    user: str = Depends(_optional_auth),
) -> dict:
    """Execute a registered function. Input is validated against the function signature."""
    meta = registry.get_function(function_name)
    if meta is None:
        raise HTTPException(404, f"Function '{function_name}' not found")

    kwargs = body or {}

    if meta.parameters:
        schema = build_function_input_schema(meta)
        try:
            validated = schema(**kwargs)
        except ValidationError as exc:
            raise HTTPException(422, detail=exc.errors())
        kwargs = validated.model_dump(exclude_none=False, by_alias=True)

    agent_run = (request.headers.get(AGENT_RUN_HEADER_NAME) or "").strip()
    agent_tcid = (request.headers.get(AGENT_TOOL_CALL_HEADER_NAME) or "").strip()
    if agent_run:
        deferred = defer_mutation_if_terminal_agent_http(
            function_name=function_name,
            kwargs=kwargs,
            agent_run_id=agent_run,
            tool_call_id=agent_tcid,
        )
        if deferred is not None:
            return {
                "result": deferred,
                "duration_ms": 0,
                "function": function_name,
            }

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
