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

PhaseHint = Literal["structured_type", "summary_heuristic"]

_RAW_TERMINAL = frozenset({"idle", "stopped", "timed_out", "error"})

# Recent messages scanned for user-gate signals (Browser Use message stream is append-only).
_RECENT_MESSAGE_LIMIT = 15

# Substrings matched against normalized ``MessageResponse.type`` (SDK: free-form category).
# See browser_use_sdk ``MessageResponse.type`` — extend when vendor documents new values.
_USER_INPUT_MESSAGE_TYPE_MARKERS: tuple[str, ...] = (
    "human",
    "user_input",
    "interactive",
    "authentication",
    "login",
    "challenge",
    "captcha",
    "mfa",
    "2fa",
    "otp",
    "verification",
)

# Tier B: regex on ``summary`` only (not ``data``) to avoid JSON-noise false positives.
_USER_INPUT_SUMMARY_PATTERNS: tuple[re.Pattern[str], ...] = (
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


def _recent_wire_messages(data: dict[str, Any]) -> list[dict[str, Any]]:
    msgs = data.get("messages")
    if not isinstance(msgs, list):
        return []
    out = [m for m in msgs if isinstance(m, dict)]
    if len(out) <= _RECENT_MESSAGE_LIMIT:
        return out
    return out[-_RECENT_MESSAGE_LIMIT :]


def _message_type_suggests_user_input(msg: dict[str, Any]) -> bool:
    typ = msg.get("type")
    if not isinstance(typ, str) or not typ.strip():
        return False
    low = typ.lower()
    return any(marker in low for marker in _USER_INPUT_MESSAGE_TYPE_MARKERS)


def _tier_a_structured_type(msgs: list[dict[str, Any]]) -> bool:
    return any(_message_type_suggests_user_input(m) for m in msgs)


def _tier_b_summary_heuristic(msgs: list[dict[str, Any]]) -> bool:
    for m in msgs:
        summ = m.get("summary")
        if not isinstance(summ, str) or not summ.strip():
            continue
        if any(p.search(summ) for p in _USER_INPUT_SUMMARY_PATTERNS):
            return True
    return False


def infer_user_gate(
    data: dict[str, Any],
) -> tuple[bool, PhaseHint | None]:
    """Whether the session likely needs human action in the browser (non-terminal only).

    Order: Tier A (``type`` substrings) then Tier B (``summary`` regex only).
    """
    msgs = _recent_wire_messages(data)
    if not msgs:
        return (False, None)
    if _tier_a_structured_type(msgs):
        return (True, "structured_type")
    if _tier_b_summary_heuristic(msgs):
        return (True, "summary_heuristic")
    return (False, None)


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

    wait, _ = infer_user_gate(data)
    if raw in ("created", "running", "") and wait:
        return "waiting_for_user"
    return "running"


def build_web_session_view_extras(data: dict[str, Any]) -> dict[str, Any]:
    """UI-safe fields derived from stored session JSON (no secrets)."""
    phase = compute_web_session_phase(data)
    _, hint = infer_user_gate(data)
    raw = _raw_cloud_status(data)

    phase_hint: PhaseHint | None = hint if phase == "waiting_for_user" else None

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

    sc = data.get("cloud_step_count")
    cloud_step_count = int(sc) if isinstance(sc, int) else None

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
        "phase_hint": phase_hint,
        "cloud_step_count": cloud_step_count,
    }
