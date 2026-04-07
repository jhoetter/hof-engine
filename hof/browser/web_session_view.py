"""Normalized web session phase + UI-safe labels for API consumers."""

from __future__ import annotations

import re
from typing import Any, Literal

# Public API surface for GET /api/web-sessions*
WebSessionPhase = Literal[
    "running",
    "waiting_for_user",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
]

_RAW_TERMINAL = frozenset({"idle", "stopped", "timed_out", "error"})

# Heuristic: agent message text suggests the human must act in the browser UI.
_USER_INPUT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bcaptcha\b", re.I),
    re.compile(r"\b2[\s-]?fa\b", re.I),
    re.compile(r"\btwo[\s-]factor\b", re.I),
    re.compile(r"\botp\b", re.I),
    re.compile(r"\bmfa\b", re.I),
    re.compile(r"\blogin\b", re.I),
    re.compile(r"\bsign[\s-]?in\b", re.I),
    re.compile(r"\bpassword\b", re.I),
    re.compile(r"\bauthenticate\b", re.I),
    re.compile(r"\bverification\s+code\b", re.I),
    re.compile(r"\bsms\s+code\b", re.I),
    re.compile(r"\bhuman\s+verification\b", re.I),
)


def _combined_message_text(msgs: list[dict[str, Any]], last_n: int = 12) -> str:
    parts: list[str] = []
    for m in msgs[-last_n:] if len(msgs) > last_n else msgs:
        if not isinstance(m, dict):
            continue
        for k in ("summary", "data", "type"):
            v = m.get(k)
            if isinstance(v, str) and v.strip():
                parts.append(v)
    return "\n".join(parts)


def _messages_suggest_user_input(data: dict[str, Any]) -> bool:
    msgs = data.get("messages")
    if not isinstance(msgs, list) or not msgs:
        return False
    blob = _combined_message_text([m for m in msgs if isinstance(m, dict)])
    if not blob.strip():
        return False
    return any(p.search(blob) for p in _USER_INPUT_PATTERNS)


def _raw_cloud_status(data: dict[str, Any]) -> str:
    s = data.get("status")
    return str(s).strip().lower() if isinstance(s, str) else ""


def _failure_from_store(data: dict[str, Any]) -> tuple[str | None, str | None]:
    code = data.get("failure_code")
    msg = data.get("failure_message")
    c = str(code).strip() if isinstance(code, str) else None
    m = str(msg).strip() if isinstance(msg, str) else None
    if not m:
        err = data.get("error")
        if isinstance(err, str) and err.strip():
            m = err.strip()
    return (c, m)


def compute_web_session_phase(data: dict[str, Any]) -> WebSessionPhase:
    """Derive normalized phase from persisted session payload."""
    raw = _raw_cloud_status(data)
    err = data.get("error")
    has_err = isinstance(err, str) and err.strip()

    if raw == "idle":
        return "succeeded"
    if raw == "stopped":
        return "cancelled"
    if raw == "timed_out":
        return "timed_out"
    if raw == "error" or has_err:
        return "failed"

    # Non-terminal cloud states: created, running, or unknown while task proceeds
    if raw in ("created", "running", "") and _messages_suggest_user_input(data):
        return "waiting_for_user"
    return "running"


def build_web_session_view_extras(data: dict[str, Any]) -> dict[str, Any]:
    """UI-safe fields derived from stored session JSON (no secrets)."""
    phase = compute_web_session_phase(data)
    raw = _raw_cloud_status(data)

    status_label: str
    status_detail: str | None = None

    if phase == "succeeded":
        status_label = "Completed"
    elif phase == "cancelled":
        status_label = "Stopped"
        status_detail = "Session was stopped."
    elif phase == "timed_out":
        status_label = "Timed out"
        status_detail = "The browser task exceeded its time limit."
    elif phase == "failed":
        status_label = "Failed"
        fc, fm = _failure_from_store(data)
        if fc:
            status_detail = f"{fc}: {fm}" if fm else fc
        elif fm:
            status_detail = fm
        else:
            status_detail = "The browser task failed."
    elif phase == "waiting_for_user":
        status_label = "Needs you"
        status_detail = "Sign in, 2FA, CAPTCHA, or other input may be required in the live view."
    else:
        status_label = "Running"
        status_detail = None

    fc_out, fm_out = _failure_from_store(data)
    if phase != "failed":
        fc_out, fm_out = None, None

    checkpoints: list[str] = []
    cp = data.get("checkpoints")
    if isinstance(cp, list):
        for x in cp:
            if isinstance(x, str) and x.strip():
                checkpoints.append(x.strip()[:500])

    checkpoint_last = checkpoints[-1] if checkpoints else None
    checkpoint_count = len(checkpoints)

    return {
        "phase": phase,
        "status_label": status_label,
        "status_detail": status_detail,
        "failure_code": fc_out,
        "failure_message": fm_out,
        "checkpoints": checkpoints or None,
        "checkpoint_last": checkpoint_last,
        "checkpoint_count": checkpoint_count,
        "cloud_status": raw or None,
    }
