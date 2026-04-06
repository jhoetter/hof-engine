"""REST API for web session state (Browser Use Cloud + Redis cache)."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from hof.agent.policy import try_get_agent_policy
from hof.browser.config import resolve_browser_api_key_value
from hof.browser.store import list_recent_web_session_ids, load_web_session

router = APIRouter()


class WebSessionListItem(BaseModel):
    session_id: str
    task: str | None = None
    live_url: str | None = None
    status: str | None = None
    sse_channel: str | None = None


@router.get("/web-sessions")
async def list_web_sessions() -> dict[str, Any]:
    """Recent Browser Use sessions (newest first), from Redis index."""
    ids = list_recent_web_session_ids(100)
    sessions: list[WebSessionListItem] = []
    for sid in ids:
        data = load_web_session(sid)
        if not data:
            continue
        sessions.append(
            WebSessionListItem(
                session_id=str(data.get("session_id") or sid),
                task=data.get("task") if isinstance(data.get("task"), str) else None,
                live_url=data.get("live_url")
                if isinstance(data.get("live_url"), str)
                else None,
                status=data.get("status") if isinstance(data.get("status"), str) else None,
                sse_channel=data.get("sse_channel")
                if isinstance(data.get("sse_channel"), str)
                else None,
            )
        )
    return {"sessions": sessions}


class WebSessionView(BaseModel):
    session_id: str
    task: str | None = None
    live_url: str | None = None
    sse_channel: str | None = None
    status: str | None = None
    output: Any = None
    recording_urls: list[str] | None = None
    messages: list[dict[str, Any]] | None = None


def _resolve_browser_api_key() -> str:
    pol = try_get_agent_policy()
    if pol is not None and pol.browser is not None:
        k = resolve_browser_api_key_value(pol.browser.api_key or "")
        if k:
            return k
    return (os.environ.get("BROWSER_USE_API_KEY") or "").strip()


@router.get("/web-sessions/{session_id}")
async def get_web_session(session_id: str) -> WebSessionView:
    data = load_web_session(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Unknown web session")
    return WebSessionView(
        session_id=str(data.get("session_id") or session_id),
        task=data.get("task") if isinstance(data.get("task"), str) else None,
        live_url=data.get("live_url") if isinstance(data.get("live_url"), str) else None,
        sse_channel=data.get("sse_channel") if isinstance(data.get("sse_channel"), str) else None,
        status=data.get("status") if isinstance(data.get("status"), str) else None,
        output=data.get("output"),
        recording_urls=data.get("recording_urls")
        if isinstance(data.get("recording_urls"), list)
        else None,
        messages=data.get("messages") if isinstance(data.get("messages"), list) else None,
    )


@router.get("/web-sessions/{session_id}/messages")
async def get_web_session_messages(session_id: str) -> dict[str, Any]:
    data = load_web_session(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Unknown web session")
    msgs = data.get("messages")
    if not isinstance(msgs, list):
        msgs = []
    return {"session_id": session_id, "messages": msgs}


@router.post("/web-sessions/{session_id}/stop")
async def stop_web_session(session_id: str) -> dict[str, Any]:
    key = _resolve_browser_api_key()
    if not key:
        raise HTTPException(status_code=503, detail="Browser API key not configured")
    try:
        from browser_use_sdk.v3 import AsyncBrowserUse
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="browser-use-sdk is not installed; reinstall hof-engine (pip install -U hof-engine)",
        ) from exc

    client = AsyncBrowserUse(api_key=key, timeout=120.0)
    try:
        stopped = await client.sessions.stop(session_id, strategy="task")
        return {"session_id": session_id, "status": stopped.status.value}
    finally:
        await client.close()


@router.get("/web-sessions/{session_id}/recording")
async def get_web_session_recording(session_id: str) -> dict[str, Any]:
    key = _resolve_browser_api_key()
    if not key:
        raise HTTPException(status_code=503, detail="Browser API key not configured")
    try:
        from browser_use_sdk.v3 import AsyncBrowserUse
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="browser-use-sdk is not installed; reinstall hof-engine (pip install -U hof-engine)",
        ) from exc

    client = AsyncBrowserUse(api_key=key, timeout=120.0)
    try:
        urls = list(await client.sessions.wait_for_recording(session_id))
    finally:
        await client.close()
    return {"session_id": session_id, "recording_urls": urls}
