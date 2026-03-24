"""Per-request cancel signal for function NDJSON streams (client disconnect / Stop).

Set from the HTTP layer in the same thread that runs ``stream_fn`` via
:class:`contextvars.ContextVar` so :func:`stream_cancel_requested` reads the
correct event inside ``iter_agent_chat_stream`` without threading hacks.
"""

from __future__ import annotations

import contextvars
import threading
from typing import Any

_stream_cancel_event: contextvars.ContextVar[threading.Event | None] = contextvars.ContextVar(
    "hof_stream_cancel_event",
    default=None,
)


def attach_stream_cancel_event(event: threading.Event) -> contextvars.Token[Any]:
    """Bind ``event`` for the current context.

    Returns a token for :func:`reset_stream_cancel_event`.
    """
    return _stream_cancel_event.set(event)


def reset_stream_cancel_event(token: contextvars.Token[Any]) -> None:
    _stream_cancel_event.reset(token)


def stream_cancel_requested() -> bool:
    """True when the bound event exists and is set (disconnect or cooperative stop)."""
    ev = _stream_cancel_event.get()
    return ev is not None and ev.is_set()


__all__ = [
    "attach_stream_cancel_event",
    "reset_stream_cancel_event",
    "stream_cancel_requested",
]
