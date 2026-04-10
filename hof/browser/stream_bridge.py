"""Bridge async browser runner to sync NDJSON agent stream via a thread + queue."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from queue import Empty, Queue
from typing import Any

from hof.browser.runner import run_browser_cloud_task_sync


def start_browser_tool_progress(
    *,
    task: str,
    api_key: str,
    model: str | None,
    enable_recording: bool,
    poll_interval_sec: float,
    task_timeout_sec: float,
    http_timeout_sec: float,
    sensitive_data: dict[str, str] | None,
) -> tuple[Iterator[dict[str, Any]], dict[str, Any]]:
    """Return ``(iterator, result_holder)``.

    Iterate events until exhausted; ``result_holder['result']`` is set to the tool result dict
    on success (or missing if the worker failed before producing a result).
    """
    q: Queue[dict[str, Any] | None] = Queue()
    err: list[BaseException] = []
    result_holder: dict[str, Any] = {}

    def worker() -> None:
        try:

            def on_progress(ev: dict[str, Any]) -> None:
                q.put(ev)

            out = run_browser_cloud_task_sync(
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
            result_holder["result"] = out
        except BaseException as e:
            err.append(e)
        finally:
            q.put(None)

    t = threading.Thread(target=worker, name="hof-browser-use")
    t.start()

    def yield_events() -> Iterator[dict[str, Any]]:
        while True:
            try:
                ev = q.get(timeout=3600.0)
            except Empty:
                break
            if ev is None:
                break
            yield ev
        t.join()
        if err:
            raise err[0]

    return yield_events(), result_holder
