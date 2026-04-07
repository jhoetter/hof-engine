"""Run Browser Use Cloud tasks and produce step events."""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from collections.abc import Callable
from typing import Any

from hof.browser import events as browser_events
from hof.browser.store import (
    append_web_session_message,
    load_web_session,
    merge_web_session_runtime_fields,
    save_web_session,
)

logger = logging.getLogger(__name__)

_TERMINAL = frozenset({"idle", "stopped", "timed_out", "error"})


def _serialize_message(msg: Any) -> dict[str, Any]:
    return {
        "id": str(msg.id),
        "role": str(msg.role or ""),
        "type": str(msg.type or ""),
        "summary": str(msg.summary or ""),
        "data": str(msg.data or ""),
        "screenshot_url": getattr(msg, "screenshot_url", None),
    }


def _emit_sse(sse_channel: str, event: dict[str, Any]) -> None:
    try:
        from hof.api.routes.sse import emit_computation_event, publish_computation_event

        emit_computation_event(sse_channel, event)
        publish_computation_event(sse_channel, event)
    except Exception:
        logger.debug("sse emit for web session failed", exc_info=True)


def _persist_poll_failure(
    session_id: str,
    sse_channel: str,
    message: str,
) -> None:
    prev = load_web_session(session_id) or {}
    prev["status"] = "error"
    prev["error"] = message
    prev["failure_code"] = "poll_error"
    prev["failure_message"] = message[:2000]
    save_web_session(session_id, prev)
    _emit_sse(
        sse_channel,
        {
            "type": browser_events.WEB_SESSION_ENDED,
            "session_id": session_id,
            "output": "",
            "status": "error",
            "detail": message,
        },
    )


async def create_browser_cloud_session(
    *,
    task: str,
    api_key: str,
    model: str | None,
    enable_recording: bool,
    http_timeout_sec: float,
    sensitive_data: dict[str, str] | None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Create a cloud session, persist stub, emit started. Does not poll."""
    try:
        from browser_use_sdk.v3 import AsyncBrowserUse
    except ImportError as exc:
        raise RuntimeError(
            "browser-use-sdk is not installed. Reinstall hof-engine so dependencies resolve: pip install -U hof-engine"
        ) from exc

    sse_channel = uuid.uuid4().hex
    extra: dict[str, Any] = {}
    if sensitive_data:
        extra["sensitiveData"] = sensitive_data

    client = AsyncBrowserUse(api_key=api_key, timeout=http_timeout_sec)
    try:
        session = await client.sessions.create(
            task,
            model=model,
            keep_alive=False,
            enable_recording=enable_recording,
            **extra,
        )

        session_id = str(session.id)
        live_url = session.live_url or ""
        status_val = session.status.value if session.status is not None else ""

        initial: dict[str, Any] = {
            "session_id": session_id,
            "task": task,
            "live_url": live_url,
            "sse_channel": sse_channel,
            "status": status_val,
            "messages": [],
        }
        save_web_session(session_id, initial)

        started = {
            "type": browser_events.WEB_SESSION_STARTED,
            "session_id": session_id,
            "live_url": live_url,
            "task": task,
            "sse_channel": sse_channel,
        }
        if on_progress:
            on_progress(started)
        _emit_sse(sse_channel, started)

        return {
            "session_id": session_id,
            "live_url": live_url,
            "sse_channel": sse_channel,
            "task": task,
        }
    finally:
        await client.close()


async def poll_browser_cloud_session(
    *,
    session_id: str,
    live_url: str,
    sse_channel: str,
    api_key: str,
    enable_recording: bool,
    poll_interval_sec: float,
    task_timeout_sec: float,
    http_timeout_sec: float,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Poll messages until terminal, then finalize Redis + recording. Separate client from create."""
    try:
        from browser_use_sdk.v3 import AsyncBrowserUse
    except ImportError as exc:
        raise RuntimeError(
            "browser-use-sdk is not installed. Reinstall hof-engine so dependencies resolve: pip install -U hof-engine"
        ) from exc

    client = AsyncBrowserUse(api_key=api_key, timeout=http_timeout_sec)
    try:
        cursor: str | None = None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + task_timeout_sec
        final_session: Any = None

        while loop.time() < deadline:
            resp = await client.sessions.messages(session_id, after=cursor, limit=100)
            for msg in resp.messages:
                wire = _serialize_message(msg)
                append_web_session_message(session_id, wire)
                step_ev = {
                    "type": browser_events.WEB_SESSION_STEP,
                    "session_id": session_id,
                    "role": wire["role"],
                    "summary": wire["summary"],
                    "message_type": wire["type"],
                    "screenshot_url": wire.get("screenshot_url"),
                }
                if on_progress:
                    on_progress(step_ev)
                _emit_sse(sse_channel, step_ev)
                cursor = str(msg.id)

            sess = await client.sessions.get(session_id)
            st = sess.status.value if sess.status is not None else ""
            merge_web_session_runtime_fields(session_id, cloud_status=st)
            if st in _TERMINAL:
                while True:
                    resp2 = await client.sessions.messages(
                        session_id, after=cursor, limit=100
                    )
                    if not resp2.messages:
                        break
                    for msg in resp2.messages:
                        wire = _serialize_message(msg)
                        append_web_session_message(session_id, wire)
                        step_ev = {
                            "type": browser_events.WEB_SESSION_STEP,
                            "session_id": session_id,
                            "role": wire["role"],
                            "summary": wire["summary"],
                            "message_type": wire["type"],
                            "screenshot_url": wire.get("screenshot_url"),
                        }
                        if on_progress:
                            on_progress(step_ev)
                        _emit_sse(sse_channel, step_ev)
                        cursor = str(msg.id)
                final_session = sess
                break

            await asyncio.sleep(poll_interval_sec)
        else:
            raise TimeoutError(f"browser task timed out after {task_timeout_sec}s")

        recording_urls: list[str] = []
        if enable_recording:
            try:
                recording_urls = list(
                    await client.sessions.wait_for_recording(session_id)
                )
            except Exception:
                logger.debug("wait_for_recording failed", exc_info=True)

        out = final_session.output
        output_str = out if isinstance(out, str) else str(out)
        ended = {
            "type": browser_events.WEB_SESSION_ENDED,
            "session_id": session_id,
            "output": output_str,
            "recording_urls": recording_urls,
            "status": final_session.status.value
            if final_session.status is not None
            else "",
        }
        if on_progress:
            on_progress(ended)
        _emit_sse(sse_channel, {**ended, "status": "done"})

        merged = load_web_session(session_id) or {}
        fin_st = (
            final_session.status.value if final_session.status is not None else ""
        )
        merged.update(
            {
                "status": fin_st,
                "output": out,
                "recording_urls": recording_urls,
                "live_url": live_url,
            }
        )
        if fin_st == "error":
            merged["failure_code"] = merged.get("failure_code") or "cloud_error"
            out_err = final_session.output
            err_txt = (
                out_err if isinstance(out_err, str) else str(out_err or "")
            ).strip()
            if err_txt:
                merged["failure_message"] = err_txt[:2000]
        save_web_session(session_id, merged)

        return {
            "session_id": session_id,
            "live_url": live_url,
            "output": out,
            "recording_urls": recording_urls,
            "status": final_session.status.value
            if final_session.status is not None
            else "",
            "sse_channel": sse_channel,
        }
    finally:
        await client.close()


async def run_browser_cloud_task(
    *,
    task: str,
    api_key: str,
    model: str | None,
    enable_recording: bool,
    poll_interval_sec: float,
    task_timeout_sec: float,
    http_timeout_sec: float,
    sensitive_data: dict[str, str] | None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Create a cloud session, stream messages until terminal, return final payload dict."""
    created = await create_browser_cloud_session(
        task=task,
        api_key=api_key,
        model=model,
        enable_recording=enable_recording,
        http_timeout_sec=http_timeout_sec,
        sensitive_data=sensitive_data,
        on_progress=on_progress,
    )
    return await poll_browser_cloud_session(
        session_id=created["session_id"],
        live_url=created["live_url"],
        sse_channel=created["sse_channel"],
        api_key=api_key,
        enable_recording=enable_recording,
        poll_interval_sec=poll_interval_sec,
        task_timeout_sec=task_timeout_sec,
        http_timeout_sec=http_timeout_sec,
        on_progress=on_progress,
    )


def spawn_browser_poll_background(
    *,
    session_id: str,
    live_url: str,
    sse_channel: str,
    api_key: str,
    enable_recording: bool,
    poll_interval_sec: float,
    task_timeout_sec: float,
    http_timeout_sec: float,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    """Run :func:`poll_browser_cloud_session` in a daemon thread (async barrier + resume pattern)."""

    def worker() -> None:
        async def _run() -> None:
            try:
                await poll_browser_cloud_session(
                    session_id=session_id,
                    live_url=live_url,
                    sse_channel=sse_channel,
                    api_key=api_key,
                    enable_recording=enable_recording,
                    poll_interval_sec=poll_interval_sec,
                    task_timeout_sec=task_timeout_sec,
                    http_timeout_sec=http_timeout_sec,
                    on_progress=on_progress,
                )
            except Exception as exc:
                logger.exception(
                    "background browser poll failed session_id=%s", session_id
                )
                _persist_poll_failure(session_id, sse_channel, str(exc))

        try:
            asyncio.run(_run())
        except Exception as exc:
            logger.exception("asyncio.run browser poll failed session_id=%s", session_id)
            _persist_poll_failure(session_id, sse_channel, str(exc))

    t = threading.Thread(
        target=worker,
        name="hof-browser-poll",
        daemon=True,
    )
    t.start()


def run_browser_cloud_task_sync(
    *,
    task: str,
    api_key: str,
    model: str | None,
    enable_recording: bool,
    poll_interval_sec: float,
    task_timeout_sec: float,
    http_timeout_sec: float,
    sensitive_data: dict[str, str] | None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run async browser task from sync agent stream."""

    async def _coro() -> dict[str, Any]:
        return await run_browser_cloud_task(
            task=task,
            api_key=api_key,
            model=model,
            enable_recording=enable_recording,
            poll_interval_sec=poll_interval_sec,
            task_timeout_sec=task_timeout_sec,
            http_timeout_sec=http_timeout_sec,
            sensitive_data=sensitive_data,
            on_progress=on_progress,
        )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_coro())

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(asyncio.run, _coro())
        return fut.result()


def create_browser_cloud_session_sync(
    *,
    task: str,
    api_key: str,
    model: str | None,
    enable_recording: bool,
    http_timeout_sec: float,
    sensitive_data: dict[str, str] | None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Sync wrapper for :func:`create_browser_cloud_session` (agent stream thread)."""

    async def _coro() -> dict[str, Any]:
        return await create_browser_cloud_session(
            task=task,
            api_key=api_key,
            model=model,
            enable_recording=enable_recording,
            http_timeout_sec=http_timeout_sec,
            sensitive_data=sensitive_data,
            on_progress=on_progress,
        )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_coro())

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(asyncio.run, _coro())
        return fut.result()
