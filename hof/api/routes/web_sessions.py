"""REST API for web session state (Browser Use Cloud + Redis cache)."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from hof.agent.policy import try_get_agent_policy
from hof.browser.config import resolve_browser_api_key_value
from hof.browser.store import (
    is_terminal_cloud_status,
    list_recent_web_session_ids,
    load_web_session,
    save_web_session,
)
from hof.browser.web_session_view import build_web_session_view_extras

logger = logging.getLogger(__name__)

_BROWSER_SDK_MISSING = (
    "browser-use-sdk is not installed; reinstall hof-engine (pip install -U hof-engine)"
)

router = APIRouter()

# Throttle Browser Use ``sessions.get`` coalesce (canvas polls ~2.5s).
_CLOUD_GET_COALESCE_LAST: dict[str, float] = {}
_CLOUD_GET_MIN_INTERVAL_SEC = 4.0


class WebSessionListItem(BaseModel):
    session_id: str
    task: str | None = None
    live_url: str | None = None
    status: str | None = None
    sse_channel: str | None = None
    phase: str
    status_label: str
    status_detail: str | None = None
    checkpoint_last: str | None = None
    checkpoint_count: int = 0
    cloud_status: str | None = None
    phase_hint: str | None = None
    cloud_step_count: int | None = None


@router.get("/web-sessions")
async def list_web_sessions() -> dict[str, Any]:
    """Recent Browser Use sessions (newest first), from Redis index."""
    ids = list_recent_web_session_ids(100)
    sessions: list[WebSessionListItem] = []
    for sid in ids:
        data = load_web_session(sid)
        if not data:
            continue
        extras = build_web_session_view_extras(data)
        sessions.append(
            WebSessionListItem(
                session_id=str(data.get("session_id") or sid),
                task=data.get("task") if isinstance(data.get("task"), str) else None,
                live_url=data.get("live_url") if isinstance(data.get("live_url"), str) else None,
                status=data.get("status") if isinstance(data.get("status"), str) else None,
                sse_channel=data.get("sse_channel")
                if isinstance(data.get("sse_channel"), str)
                else None,
                phase=str(extras["phase"]),
                status_label=str(extras["status_label"]),
                status_detail=extras["status_detail"],
                checkpoint_last=extras.get("checkpoint_last"),
                checkpoint_count=int(extras.get("checkpoint_count") or 0),
                cloud_status=extras.get("cloud_status"),
                phase_hint=extras.get("phase_hint"),
                cloud_step_count=extras.get("cloud_step_count"),
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
    phase: str
    status_label: str
    status_detail: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    checkpoints: list[str] | None = None
    checkpoint_last: str | None = None
    checkpoint_count: int = 0
    cloud_status: str | None = None
    phase_hint: str | None = None
    cloud_step_count: int | None = None


def _resolve_browser_api_key() -> str:
    pol = try_get_agent_policy()
    if pol is not None and pol.browser is not None:
        k = resolve_browser_api_key_value(pol.browser.api_key or "")
        if k:
            return k
    return (os.environ.get("BROWSER_USE_API_KEY") or "").strip()


async def _coalesce_web_session_with_cloud(session_id: str) -> None:
    """If Redis still says *running* but Browser Use already finished, sync from cloud.

    Background polling can miss the final snapshot (disconnect, races). The live
    iframe may show Session ended while our API still returns ``running``.
    """
    data = load_web_session(session_id)
    if not data:
        return
    if is_terminal_cloud_status(data.get("status")):
        return
    key = _resolve_browser_api_key()
    if not key:
        return
    now = time.monotonic()
    last = _CLOUD_GET_COALESCE_LAST.get(session_id, 0.0)
    if now - last < _CLOUD_GET_MIN_INTERVAL_SEC:
        return

    try:
        from browser_use_sdk.v3 import AsyncBrowserUse
    except ImportError:
        return

    client = AsyncBrowserUse(api_key=key, timeout=45.0)
    try:
        sess = await client.sessions.get(session_id)
    except Exception as exc:
        logger.debug(
            "web session cloud coalesce failed session_id=%s: %s",
            session_id,
            exc,
        )
        return
    finally:
        await client.close()

    _CLOUD_GET_COALESCE_LAST[session_id] = time.monotonic()

    cloud_st = sess.status.value if sess.status is not None else ""
    if not is_terminal_cloud_status(cloud_st):
        return

    prev = load_web_session(session_id) or {}
    prev["session_id"] = str(prev.get("session_id") or session_id)
    prev["status"] = cloud_st
    out = sess.output
    if out is not None:
        prev["output"] = out
    if cloud_st == "error":
        prev["failure_code"] = prev.get("failure_code") or "cloud_error"
        err_txt = out if isinstance(out, str) else str(out or "")
        if err_txt.strip():
            prev["failure_message"] = err_txt.strip()[:2000]
    sc = getattr(sess, "step_count", None)
    if sc is not None:
        try:
            prev["cloud_step_count"] = int(sc)
        except (TypeError, ValueError):
            pass
    save_web_session(session_id, prev)


@router.get("/web-sessions/{session_id}")
async def get_web_session(session_id: str) -> WebSessionView:
    data = load_web_session(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Unknown web session")
    await _coalesce_web_session_with_cloud(session_id)
    data = load_web_session(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Unknown web session")
    extras = build_web_session_view_extras(data)
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
        phase=str(extras["phase"]),
        status_label=str(extras["status_label"]),
        status_detail=extras["status_detail"],
        failure_code=extras.get("failure_code"),
        failure_message=extras.get("failure_message"),
        checkpoints=extras.get("checkpoints"),
        checkpoint_last=extras.get("checkpoint_last"),
        checkpoint_count=int(extras.get("checkpoint_count") or 0),
        cloud_status=extras.get("cloud_status"),
        phase_hint=extras.get("phase_hint"),
        cloud_step_count=extras.get("cloud_step_count"),
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
        raise HTTPException(status_code=503, detail=_BROWSER_SDK_MISSING) from exc

    client = AsyncBrowserUse(api_key=key, timeout=120.0)
    try:
        stopped = await client.sessions.stop(session_id, strategy="task")
        prev = load_web_session(session_id) or {}
        prev["session_id"] = str(prev.get("session_id") or session_id)
        prev["status"] = "stopped"
        prev["failure_message"] = None
        prev["failure_code"] = None
        save_web_session(session_id, prev)
        return {
            "session_id": session_id,
            "status": stopped.status.value,
            "phase": "cancelled",
        }
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
        raise HTTPException(status_code=503, detail=_BROWSER_SDK_MISSING) from exc

    client = AsyncBrowserUse(api_key=key, timeout=120.0)
    try:
        urls = list(await client.sessions.wait_for_recording(session_id))
    finally:
        await client.close()
    return {"session_id": session_id, "recording_urls": urls}
