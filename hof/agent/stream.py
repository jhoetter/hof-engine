"""NDJSON agent chat stream: LLM tool loop, mutation gate, resume."""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from llm_markdown.providers import ReasoningConfig, ReasoningMode, stream_agent_turn

from hof.agent.policy import (
    BUILTIN_AGENT_TOOL_NAMES,
    AgentPolicy,
    InboxWatchDescriptor,
    MutationBatchEntry,
    MutationPreviewResult,
    get_agent_policy,
    inbox_watch_from_wire,
    inbox_watch_to_wire,
    mutation_preview_to_wire,
    post_apply_review_hint_to_wire,
)
from hof.agent.sandbox.constants import HOF_BUILTIN_TERMINAL_EXEC
from hof.agent.sandbox.context import (
    bind_sandbox_run,
    get_sandbox_run,
    release_bound_terminal_session,
    reset_sandbox_run,
    set_sandbox_run,
    unbind_sandbox_run,
)
from hof.agent.state import (
    delete_agent_run,
    delete_pending,
    load_agent_run,
    load_pending,
    save_agent_run,
    save_agent_run_with_ttl,
    save_pending,
)
from hof.agent.tooling import (
    ToolExecResult,
    execute_tool,
    format_cli_line,
    format_tool_result_for_model,
    openai_tool_specs,
    parsed_tool_result_for_stream,
    split_agent_tool_display_metadata,
    summarize_tool_json,
    tool_result_status_for_ui,
)
from hof.browser.config import resolve_browser_api_key_value
from hof.browser.constants import HOF_BUILTIN_BROWSE_WEB
from hof.browser.store import load_web_session
from hof.config import get_config

logger = logging.getLogger(__name__)

_WEB_SESSION_TERMINAL = frozenset({"idle", "stopped", "timed_out", "error"})


def _browser_async_enabled(policy: AgentPolicy) -> bool:
    if not policy.browser_async:
        return False
    return (os.environ.get("HOF_BROWSER_ASYNC", "1") or "").strip() != "0"


def _save_agent_run_merge_attachments(run_id: str, payload: dict[str, Any]) -> None:
    """Persist run state; keep ``chat_attachments`` if missing from ``payload``."""
    prev = load_agent_run(run_id)
    has_prev_att = prev and isinstance(prev.get("chat_attachments"), list)
    if has_prev_att and "chat_attachments" not in payload:
        payload = {**payload, "chat_attachments": prev["chat_attachments"]}
    save_agent_run(run_id, payload)


def _save_agent_run_with_ttl_merge_attachments(
    run_id: str,
    payload: dict[str, Any],
    ttl_sec: int,
) -> None:
    prev = load_agent_run(run_id)
    has_prev_att = prev and isinstance(prev.get("chat_attachments"), list)
    if has_prev_att and "chat_attachments" not in payload:
        payload = {**payload, "chat_attachments": prev["chat_attachments"]}
    save_agent_run_with_ttl(run_id, payload, ttl_sec)


def _coerce_persisted_chat_attachments(raw: Any) -> list[dict[str, str]] | None:
    """Normalize ``chat_attachments`` from persisted agent run JSON."""
    if not isinstance(raw, list) or not raw:
        return None
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = str(item.get("object_key") or "").strip()
        if not key:
            continue
        row: dict[str, str] = {"object_key": key}
        fn = item.get("filename")
        if isinstance(fn, str) and fn.strip():
            row["filename"] = fn.strip()[:500]
        ct = item.get("content_type")
        if isinstance(ct, str) and ct.strip():
            row["content_type"] = ct.strip()[:200]
        out.append(row)
    return out or None


def _cli_line_cap_for_tool(name: str, base: int) -> int:
    """Long ``hof_builtin_terminal_exec`` commands need a higher cap than generic tools."""
    if name == HOF_BUILTIN_TERMINAL_EXEC:
        return max(base, 120_000)
    return base


def _args_wire_emit_cap_chars(name: str) -> int:
    """NDJSON ``tool_call.arguments`` is capped for safety; terminal scripts need more room."""
    if name == HOF_BUILTIN_TERMINAL_EXEC:
        return 120_000
    return 2000


def _maybe_wrap_sandbox(
    policy: AgentPolicy,
    run_id: str,
    loop_gen: Iterator[dict[str, Any]],
    chat_attachments: list[dict[str, str]] | None = None,
) -> Iterator[dict[str, Any]]:
    """Bind sandbox terminal session to this run (release container when the loop ends)."""
    sc = policy.sandbox.with_env_overrides() if policy.sandbox is not None else None
    if sc is not None and sc.enabled:
        token = set_sandbox_run(
            run_id=run_id,
            user_id=run_id,
            policy=policy,
            chat_attachments=chat_attachments,
        )
        st = get_sandbox_run()
        if st is not None:
            bind_sandbox_run(run_id, st)
            logger.info(
                "sandbox: bound run_id=%s (thread-safe table + ContextVar)",
                run_id,
            )
        try:
            yield from loop_gen
        finally:
            release_bound_terminal_session(run_id=run_id)
            unbind_sandbox_run(run_id)
            try:
                reset_sandbox_run(token)
            except ValueError:
                # Token may be from another context (e.g. streaming thread); table unbind wins.
                logger.debug(
                    "sandbox: skipped ContextVar reset (different execution context)",
                )
    else:
        yield from loop_gen


_HOF_BUILTIN_PRESENT_PLAN = "hof_builtin_present_plan"
_HOF_BUILTIN_PRESENT_PLAN_CLARIFICATION = "hof_builtin_present_plan_clarification"
_HOF_BUILTIN_UPDATE_PLAN_TODO_STATE = "hof_builtin_update_plan_todo_state"

# Plan-discover explore phase: no terminal plan tools (must reply with text before questioning).
_DISCOVER_EXCLUDE_FROM_EXPLORE: frozenset[str] = frozenset(
    {
        _HOF_BUILTIN_PRESENT_PLAN,
        _HOF_BUILTIN_PRESENT_PLAN_CLARIFICATION,
        _HOF_BUILTIN_UPDATE_PLAN_TODO_STATE,
    },
)


def _provider_wait_wire(ev: Any) -> dict[str, Any] | None:
    """Map llm-markdown :class:`~llm_markdown.agent_stream.AgentRateLimitWait` to NDJSON."""
    from llm_markdown.agent_stream import AgentRateLimitWait

    if isinstance(ev, AgentRateLimitWait):
        return {
            "type": "provider_wait",
            "seconds": float(ev.seconds),
            "reason": ev.reason,
        }
    return None


def _resolve_agent_engine_stream_max_attempts() -> int:
    """How many times Hof may run ``stream_agent_turn`` for one model step
    (after llm-markdown retries)."""
    raw = os.environ.get("HOF_AGENT_ENGINE_STREAM_ATTEMPTS", "").strip()
    if not raw:
        n = 3
    else:
        try:
            n = int(raw, 10)
        except ValueError:
            n = 3
    return max(1, min(10, n))


class _AgentStreamTurnExhaustedError(Exception):
    """``stream_agent_turn`` failed with a retryable provider error after all
    engine-level attempts."""

    __slots__ = ("attempts", "cause")

    def __init__(self, cause: BaseException, *, attempts: int) -> None:
        self.cause = cause
        self.attempts = attempts
        super().__init__(str(cause))


def _provider_error_eligible_for_engine_stream_retry(exc: BaseException) -> bool:
    """Retry engine-level stream when failure looks transient (duck-type :class:`ProviderError`)."""
    if not _looks_like_llm_provider_error(exc):
        return False
    failure = getattr(exc, "failure", None)
    if failure is not None:
        return _provider_failure_category_is_engine_exhaustible(failure)
    return bool(getattr(exc, "retryable", False))


def _engine_stream_retry_sleep_seconds(exc: BaseException) -> float:
    f = getattr(exc, "failure", None)
    raw = (
        float(f.retry_after_seconds)
        if f is not None and getattr(f, "retry_after_seconds", None) is not None
        else None
    )
    if raw is not None and raw > 0:
        return min(120.0, max(0.5, raw))
    cv = _failure_category_value(f)
    if cv == "timeout":
        return 3.0
    # Anthropic 529 overloaded: short fixed waits rarely help; give capacity time to recover.
    if cv == "overloaded":
        return 12.0
    return 5.0


def _engine_stream_wait_reason(exc: BaseException) -> str:
    f = getattr(exc, "failure", None)
    if f is not None and _failure_category_value(f) == "rate_limit":
        return "rate_limit"
    return "transient_error"


def _user_message_after_engine_retries_exhausted(
    f: Any,
    *,
    attempts: int,
) -> str:
    """First-person copy after all Hof engine-level stream retries failed
    (no raw provider payload)."""
    times_word = "time" if attempts == 1 else "times"
    cv = _failure_category_value(f)

    if cv == "rate_limit":
        base = (
            "I hit a usage limit (too many requests or tokens in a short window). "
            f"I waited and tried again automatically {attempts} {times_word}, then had to stop."
        )
    elif cv == "overloaded":
        base = (
            "The AI provider is temporarily overloaded "
            "(high demand on their side — not your quota). "
            f"I waited and tried again automatically {attempts} {times_word}, then had to stop."
        )
    elif cv == "server":
        base = (
            "The AI provider returned a temporary server error. "
            f"I waited and tried again automatically {attempts} {times_word}, then had to stop."
        )
    elif cv == "timeout":
        base = (
            "The request timed out. "
            f"I waited and tried again automatically {attempts} {times_word}, then had to stop."
        )
    else:
        base = (
            "The AI request failed after automatic retries. "
            f"I tried {attempts} {times_word}, then had to stop."
        )

    ra = getattr(f, "retry_after_seconds", None)
    if ra is not None and isinstance(ra, (int, float)) and ra > 0:
        secs = max(1, int(round(float(ra))))
        base += f" Waiting about {secs} more seconds before you send your message again may help."
    elif cv == "overloaded":
        base += (
            " Please wait a few minutes and try again — overload often clears after a short pause."
        )
    else:
        base += " Please wait a short while, then send your message again."
    return base


def _user_message_transient_limit_without_exhausted_retries(f: Any) -> str:
    """First-person copy when a limit error is shown without engine-exhausted wording
    (e.g. partial stream)."""
    cv = _failure_category_value(f)
    ra = getattr(f, "retry_after_seconds", None)
    if cv == "rate_limit":
        msg = (
            "I hit a usage limit before I could finish this step. "
            "Please wait a short moment and try again."
        )
    elif cv == "timeout":
        msg = "The request timed out before I could finish this step. Please try again in a moment."
    else:
        msg = (
            "The AI service was temporarily unavailable before I could finish this step. "
            "Please try again in a moment."
        )
    if ra is not None and isinstance(ra, (int, float)) and ra > 0:
        secs = max(1, int(round(float(ra))))
        msg += f" A delay of about {secs}s may help."
    return msg


def _iter_stream_agent_turn_with_engine_retries(
    *st_args: Any,
    **st_kwargs: Any,
) -> Iterator[Any]:
    """Run ``stream_agent_turn`` with up to N outer attempts on retryable provider limits.

    Yields the same event objects as ``stream_agent_turn``. Emits :class:`AgentRateLimitWait`
    and sleeps before each retry so clients can show a wait notice.
    """
    from llm_markdown.agent_stream import (
        AgentContentDelta,
        AgentRateLimitWait,
        AgentReasoningDelta,
        AgentToolCallDelta,
    )
    from llm_markdown.providers.base import ProviderError

    max_attempts = _resolve_agent_engine_stream_max_attempts()
    for attempt in range(max_attempts):
        # Do not treat AgentSegmentStart as progress: agent_turn injects it before the
        # provider opens the stream, so a failure on stream open would wrongly skip retries.
        emitted_meaningful = False
        try:
            for ev in stream_agent_turn(*st_args, **st_kwargs):
                if isinstance(
                    ev,
                    (AgentContentDelta, AgentReasoningDelta, AgentToolCallDelta),
                ):
                    emitted_meaningful = True
                yield ev
            return
        except ProviderError as exc:
            if emitted_meaningful:
                raise
            if not _provider_error_eligible_for_engine_stream_retry(exc):
                raise
            if attempt + 1 >= max_attempts:
                raise _AgentStreamTurnExhaustedError(exc, attempts=max_attempts) from exc
            wait = _engine_stream_retry_sleep_seconds(exc)
            yield AgentRateLimitWait(
                seconds=wait,
                reason=_engine_stream_wait_reason(exc),  # type: ignore[arg-type]
            )
            time.sleep(wait)


def _looks_like_llm_provider_error(exc: BaseException) -> bool:
    """True if ``exc`` is a :class:`~llm_markdown.providers.base.ProviderError`-like object.

    Avoid ``isinstance(..., ProviderError)``: two copies of ``llm_markdown`` in the same
    process (editable + import path quirks) can produce distinct ``ProviderError`` classes,
    so ``isinstance`` returns false even though the runtime error is the same shape.
    """
    return hasattr(exc, "failure") and hasattr(exc, "provider")


def _failure_category_value(failure: object | None) -> str | None:
    """Normalized ``failure.category`` as a lowercase string (enum or raw str)."""
    if failure is None:
        return None
    cat = getattr(failure, "category", None)
    if isinstance(cat, str) and cat.strip():
        return cat.strip().lower()
    val = getattr(cat, "value", None) if cat is not None else None
    if isinstance(val, str) and val.strip():
        return val.strip().lower()
    return None


_TRANSIENT_FAILURE_CATEGORIES: frozenset[str] = frozenset(
    ("rate_limit", "overloaded", "server", "timeout"),
)


def _provider_failure_category_is_engine_exhaustible(failure: object | None) -> bool:
    cv = _failure_category_value(failure)
    return cv in _TRANSIENT_FAILURE_CATEGORIES


def _provider_error_is_transient_for_log(exc: BaseException) -> bool:
    """Whether a provider failure is expected-transient (log at warning, not exception)."""
    if not _looks_like_llm_provider_error(exc):
        return False
    # llm-markdown sets this from HTTP status / message heuristics; trust it first.
    if bool(getattr(exc, "retryable", False)):
        return True
    failure = getattr(exc, "failure", None)
    cv = _failure_category_value(failure)
    if cv is not None:
        return cv in _TRANSIENT_FAILURE_CATEGORIES
    return False


def _agent_stream_error_event(
    exc: BaseException,
    *,
    engine_turn_retries_exhausted: bool = False,
    engine_retry_max_attempts: int | None = None,
) -> dict[str, Any]:
    """Map exceptions to NDJSON ``error``; duck-type
    :class:`~llm_markdown.providers.base.ProviderError`."""
    if not _looks_like_llm_provider_error(exc):
        return {"type": "error", "detail": str(exc)}
    f = getattr(exc, "failure", None)
    if f is None:
        return {"type": "error", "detail": str(exc)}
    attempts = (
        engine_retry_max_attempts
        if engine_retry_max_attempts is not None
        else _resolve_agent_engine_stream_max_attempts()
    )
    exhaustible = _provider_failure_category_is_engine_exhaustible(f)
    if engine_turn_retries_exhausted and exhaustible:
        detail = _user_message_after_engine_retries_exhausted(f, attempts=attempts)
    elif exhaustible:
        detail = _user_message_transient_limit_without_exhausted_retries(f)
    else:
        detail = getattr(f, "public_message", None) or str(exc)
    cat_key = _failure_category_value(f) or "unknown"
    out: dict[str, Any] = {
        "type": "error",
        "detail": detail,
        "error_category": cat_key,
        "retryable": (
            False if engine_turn_retries_exhausted else bool(getattr(exc, "retryable", False))
        ),
    }
    http_status = getattr(f, "http_status", None)
    if http_status is not None:
        out["http_status"] = http_status
    retry_after = getattr(f, "retry_after_seconds", None)
    if retry_after is not None:
        out["retry_after_seconds"] = retry_after
    return out


def _mutation_preview_payload(
    name: str,
    arguments_json: str,
    policy: AgentPolicy,
) -> dict[str, Any] | None:
    """Optional app-registered preview envelope for pending mutations; must be JSON-serializable."""
    fn = policy.mutation_preview.get(name)
    if fn is None:
        return None
    try:
        parsed = json.loads(arguments_json) if arguments_json else {}
        if not isinstance(parsed, dict):
            return None
        out = fn(parsed)
        if out is None:
            return None
        if isinstance(out, MutationPreviewResult):
            wire = mutation_preview_to_wire(out)
        elif isinstance(out, dict):
            wire = mutation_preview_to_wire(out)
        else:
            return None
        json.dumps(wire, default=str)
        return wire
    except Exception:
        logger.debug("mutation_preview failed for %s", name, exc_info=True)
        return None


def _extract_json_dict_from_text(text: str) -> dict[str, Any] | None:
    s = (text or "").strip()
    if not s:
        return None
    try:
        o = json.loads(s)
        return o if isinstance(o, dict) else None
    except json.JSONDecodeError:
        pass
    i = s.find("{")
    if i < 0:
        return None
    try:
        o, _ = json.JSONDecoder().raw_decode(s[i:])
        return o if isinstance(o, dict) else None
    except json.JSONDecodeError:
        return None


def _terminal_http_body_inner_pending(body: dict[str, Any]) -> dict[str, Any] | None:
    inner = body.get("result")
    if isinstance(inner, dict) and inner.get("pending_confirmation") is True:
        return inner
    if body.get("pending_confirmation") is True:
        return body
    return None


def _try_coerce_terminal_exec_mutation_events(
    *,
    out_json: str,
    run_id: str,
    tid: str,
    mutation_allowlist: frozenset[str],
    max_cli_line_chars: int,
) -> tuple[list[dict[str, Any]], dict[str, Any], str] | None:
    """If terminal stdout is an HTTP wrapper with a deferred mutation, emit pending rows."""
    pdata = parsed_tool_result_for_stream(out_json)
    if not isinstance(pdata, dict):
        return None
    raw_out = pdata.get("output")
    if not isinstance(raw_out, str):
        return None
    wrapper = _extract_json_dict_from_text(raw_out)
    if wrapper is None:
        return None
    inner = _terminal_http_body_inner_pending(wrapper)
    if inner is None:
        return None
    pid = str(inner.get("pending_id") or "").strip()
    fname = str(inner.get("function") or "").strip()
    if not pid or not fname or fname not in mutation_allowlist:
        return None
    loaded = load_pending(pid)
    if loaded is None or str(loaded.get("run_id") or "") != str(run_id):
        return None
    args_wire = str(loaded.get("arguments_json") or "{}")
    cap = _cli_line_cap_for_tool(fname, max_cli_line_chars)
    cli_line = format_cli_line(fname, args_wire, max_cli_line_chars=cap)
    preview = inner.get("preview")
    if isinstance(preview, dict) and preview.get("cli_line"):
        cli_line = str(preview["cli_line"])
    mp_ev: dict[str, Any] = {
        "type": "mutation_pending",
        "run_id": run_id,
        "pending_id": pid,
        "name": fname,
        "arguments": args_wire[:12000],
        "cli_line": cli_line,
        "tool_call_id": tid,
    }
    if isinstance(preview, dict):
        mp_ev["preview"] = preview
    tr_pending: dict[str, Any] = {
        "type": "tool_result",
        "name": HOF_BUILTIN_TERMINAL_EXEC,
        "summary": ("Awaiting your confirmation (Assistant panel or agent_resume_mutations)."),
        "pending_confirmation": True,
        "status_code": 202,
        "tool_call_id": tid,
    }
    if isinstance(preview, dict):
        tr_pending["data"] = preview
    ph_obj: dict[str, Any] = {
        "status": "success",
        "pending_confirmation": True,
        "pending_id": pid,
        "function": fname,
        "next_step": "STOP",
        "instruction": (
            "The mutation was successfully received and is now pending user approval. "
            "Your turn is DONE. Do NOT call any more tools. Do NOT retry or probe. "
            "Write a brief confirmation message and end your turn."
        ),
    }
    if isinstance(preview, dict):
        ph_obj["preview"] = preview
    oa_tool = {
        "role": "tool",
        "tool_call_id": tid,
        "content": json.dumps(ph_obj),
    }
    return ([mp_ev, tr_pending], oa_tool, pid)


def _collapse_agent_round_trace(parts: list[str], *, max_parts: int = 200) -> str:
    """Compact trace: Sr/Sc=segment_start, r=reasoning, cN/tN repeated deltas, f=finish."""
    seq = parts[:max_parts]
    out: list[str] = []
    i = 0
    while i < len(seq):
        ch = seq[i]
        if ch in ("c", "t"):
            j = i + 1
            while j < len(seq) and seq[j] == ch:
                j += 1
            n = j - i
            out.append(ch if n == 1 else f"{ch}{n}")
            i = j
        else:
            out.append(ch)
            i += 1
    if len(parts) > max_parts:
        out.append("…")
    return "".join(out)


_STREAM_DEBUG_UNSET = object()
_stream_debug_path: Any = _STREAM_DEBUG_UNSET
_stream_debug_open_warned = False
_stream_debug_confirmed = False


def _resolve_agent_stream_debug_path() -> str | None:
    """Path for NDJSON agent stream diagnostics, or None if disabled.

    Re-reads project ``.env`` once if the var is missing from ``os.environ`` (uvicorn
    ``--reload`` / subprocess edge cases where only ``HOF_PROJECT_ROOT`` was forwarded).
    ``HOF_AGENT_STREAM_DEBUG_LOG=1`` (or ``true``) uses ``/tmp/hof-agent-stream.ndjson``.
    """
    raw = os.environ.get("HOF_AGENT_STREAM_DEBUG_LOG", "").strip()
    if not raw:
        try:
            from dotenv import load_dotenv

            env_root = os.environ.get("HOF_PROJECT_ROOT", "").strip()
            if env_root:
                load_dotenv(Path(env_root) / ".env", override=False)
            else:
                from hof.config import find_project_root

                root = find_project_root()
                if root is not None:
                    load_dotenv(root / ".env", override=False)
            raw = os.environ.get("HOF_AGENT_STREAM_DEBUG_LOG", "").strip()
        except Exception:
            raw = os.environ.get("HOF_AGENT_STREAM_DEBUG_LOG", "").strip()
    if not raw:
        return None
    if raw.lower() in ("1", "true", "yes", "on"):
        return str(Path("/tmp") / "hof-agent-stream.ndjson")
    return raw


def _agent_stream_debug_append(record: dict[str, Any]) -> None:
    """Append one NDJSON line when ``HOF_AGENT_STREAM_DEBUG_LOG`` is set.

    No message bodies or full tool JSON—only lengths and metadata.
    """
    global _stream_debug_path, _stream_debug_open_warned, _stream_debug_confirmed

    if _stream_debug_path is _STREAM_DEBUG_UNSET:
        _stream_debug_path = _resolve_agent_stream_debug_path()
    path = _stream_debug_path
    if not path:
        return
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        line = {"ts_ms": int(time.time() * 1000), **record}
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, default=str) + "\n")
        if not _stream_debug_confirmed:
            _stream_debug_confirmed = True
            # warning level so it is visible even when root log level is WARNING
            logger.warning(
                "HOF_AGENT_STREAM_DEBUG_LOG active — appending agent stream diagnostics to %s",
                path,
            )
    except OSError as exc:
        if not _stream_debug_open_warned:
            _stream_debug_open_warned = True
            logger.warning(
                "HOF_AGENT_STREAM_DEBUG_LOG set but cannot write %s: %s",
                path,
                exc,
            )


_AGENT_SUMMARY_MAX_TOKENS = 2048
# Shown when confirmation_summary_mode is static, or as LLM-summary fallback.
_CONFIRMATION_SUMMARY_STATIC_FALLBACK = (
    "I've prepared the actions above. Please use Approve or Reject for each item below; "
    "the assistant continues automatically after you choose."
)
_AGENT_COMPLETION_TOKENS_CAP = 128_000
_AGENT_COMPLETION_TOKENS_FLOOR = 256


def _agent_limits() -> tuple[int, int, int, int]:
    try:
        c = get_config()
        return (
            c.agent_max_rounds,
            c.agent_max_tool_output_chars,
            c.agent_max_model_text_chars,
            c.agent_max_cli_line_chars,
        )
    except Exception:
        return 10, 18_000, 8000, 240


def _resolve_openai_api_key() -> str:
    v = os.environ.get("OPENAI_API_KEY", "").strip()
    if v:
        return v
    try:
        return (get_config().llm_api_key or "").strip()
    except Exception:
        return ""


def _resolve_anthropic_api_key() -> str:
    return os.environ.get("ANTHROPIC_API_KEY", "").strip()


def _resolve_agent_llm_backend() -> str:
    """``openai`` (default) or ``anthropic`` — from ``AGENT_LLM_BACKEND``."""
    raw = os.environ.get("AGENT_LLM_BACKEND", "").strip().lower()
    if raw in ("", "openai"):
        return "openai"
    if raw in ("anthropic", "claude"):
        return "anthropic"
    msg = f"Unknown AGENT_LLM_BACKEND: {raw!r} (use openai or anthropic)"
    raise ValueError(msg)


def _resolve_agent_model() -> str:
    for key in ("AGENT_MODEL", "LLM_MARKDOWN_MODEL"):
        v = os.environ.get(key, "").strip()
        if v:
            return v
    try:
        c = get_config()
        am = getattr(c, "agent_model", "") or ""
        if isinstance(am, str) and am.strip():
            return am.strip()
        lm = getattr(c, "llm_model", "") or ""
        if isinstance(lm, str) and lm.strip():
            return lm.strip()
    except Exception:
        pass
    return "gpt-4o-mini"


def _resolve_agent_model_for_chat_mode(chat_mode: str) -> str:
    """Use ``PLAN_AGENT`` for ``plan`` / ``plan_discover`` when set; else default agent model.

    ``plan_execute`` always uses the default agent model so execution matches normal chat.
    """
    if chat_mode in ("plan", "plan_discover"):
        plan_m = os.environ.get("PLAN_AGENT", "").strip()
        if plan_m:
            return plan_m
    return _resolve_agent_model()


def _anthropic_stream_turn_extras(
    lm_backend: str,
    reasoning: ReasoningConfig,
) -> dict[str, Any]:
    """Always bias adaptive thinking so Claude emits a thinking block (not env-tunable)."""
    if lm_backend != "anthropic":
        return {}
    if reasoning.mode is not ReasoningMode.NATIVE:
        return {}
    if not reasoning.anthropic_thinking:
        return {}
    return {"output_config": {"effort": "high"}}


def _anthropic_adaptive_thinking_supported_for_model_id(model_id: str) -> bool:
    """Whether Anthropic Messages API accepts ``thinking`` with ``type: adaptive`` for this model.

    Some ids (Haiku, Sonnet 4.5-class) return 400
    ``adaptive thinking is not supported on this model``.
    """
    m = (model_id or "").strip().lower()
    if not m or "haiku" in m:
        return False
    if "sonnet-4-5" in m or "sonnet_4_5" in m:
        return False
    return True


def _coerce_anthropic_thinking_kw_for_model(
    model_id: str,
    kw: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Drop unsupported ``adaptive`` thinking so the provider does not 400."""
    if kw is None:
        return None
    if kw.get("type") != "adaptive":
        return kw
    if _anthropic_adaptive_thinking_supported_for_model_id(model_id):
        return kw
    logger.info(
        "anthropic thinking: omitting adaptive for model_id=%s (not supported by API)",
        model_id,
    )
    return None


def _anthropic_thinking_from_env_raw(raw: str, env_name: str) -> dict[str, Any] | None:
    """Parse ``thinking=...`` for Anthropic Messages API (native mode only).

    - unset / empty → ``{"type": "adaptive"}`` (Sonnet/Opus 4.6-class default)
    - ``adaptive`` → same
    - ``off`` / ``false`` / ``0`` / ``no`` → omit thinking (no ``AgentReasoningDelta`` from API)
    - otherwise parsed as JSON object (e.g. extended thinking with ``budget_tokens``)
    """
    stripped = (raw or "").strip()
    if not stripped:
        return {"type": "adaptive"}
    low = stripped.lower()
    if low in ("off", "false", "0", "no"):
        return None
    if low == "adaptive":
        return {"type": "adaptive"}
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        msg = f"{env_name} must be adaptive, off, or valid JSON object: {exc}"
        raise ValueError(msg) from exc
    if not isinstance(parsed, dict):
        msg = f"{env_name} JSON must be an object"
        raise ValueError(msg)
    return parsed


def _resolve_anthropic_thinking_kw() -> dict[str, Any] | None:
    """``AGENT_ANTHROPIC_THINKING`` → thinking kw for Anthropic."""
    return _anthropic_thinking_from_env_raw(
        os.environ.get("AGENT_ANTHROPIC_THINKING", ""),
        "AGENT_ANTHROPIC_THINKING",
    )


def _resolve_agent_reasoning_config(backend: str | None = None) -> ReasoningConfig:
    """Map config/env to llm-markdown :class:`ReasoningConfig` for ``stream_agent_turn``."""
    mode_src = os.environ.get("AGENT_REASONING_MODE", "").strip().lower()
    if not mode_src:
        try:
            mode_src = (get_config().agent_reasoning_mode or "native").strip().lower()
        except Exception:
            mode_src = "native"
    extras: dict[str, Any] | None = None
    raw_extras = os.environ.get("AGENT_REASONING_OPENAI_EXTRAS", "").strip()
    if raw_extras:
        try:
            parsed = json.loads(raw_extras)
        except json.JSONDecodeError as exc:
            msg = f"AGENT_REASONING_OPENAI_EXTRAS must be valid JSON object: {exc}"
            raise ValueError(msg) from exc
        if not isinstance(parsed, dict):
            msg = "AGENT_REASONING_OPENAI_EXTRAS must be a JSON object"
            raise ValueError(msg)
        extras = parsed
    backend_norm = (backend or "").strip().lower()

    if mode_src in ("off", "false", "0", "no"):
        if extras:
            msg = "AGENT_REASONING_OPENAI_EXTRAS is not allowed when AGENT_REASONING_MODE is off"
            raise ValueError(msg)
        return ReasoningConfig.off()
    if mode_src in ("fallback",):
        if extras:
            msg = (
                "AGENT_REASONING_OPENAI_EXTRAS is not allowed when AGENT_REASONING_MODE is fallback"
            )
            raise ValueError(msg)
        if backend_norm == "anthropic":
            logger.warning(
                "FALLBACK reasoning is not recommended for Anthropic; "
                "using native mode with provider thinking instead (see AGENT_ANTHROPIC_THINKING)"
            )
            return ReasoningConfig.native(anthropic_thinking=_resolve_anthropic_thinking_kw())
        return ReasoningConfig(mode=ReasoningMode.FALLBACK)
    if mode_src not in ("native", "", "on", "true", "1", "yes"):
        msg = f"Unknown agent reasoning mode: {mode_src!r} (use native, off, or fallback)"
        raise ValueError(msg)
    if backend_norm == "anthropic":
        if extras:
            msg = "AGENT_REASONING_OPENAI_EXTRAS is not used when AGENT_LLM_BACKEND=anthropic"
            raise ValueError(msg)
        return ReasoningConfig.native(anthropic_thinking=_resolve_anthropic_thinking_kw())
    # OpenAI (default backend): "native" in config means "show thinking for every turn".
    # Chat Completions on gpt-4o-class models usually emit no reasoning_delta; llm-markdown
    # FALLBACK always streams a planning/thinking lane. Opt into true Chat Completions native
    # reasoning (o-series etc.) by setting AGENT_REASONING_OPENAI_EXTRAS to any JSON object
    # (e.g. {}); we merge reasoning_effort=high so reasoning tends to appear when supported.
    if not raw_extras:
        return ReasoningConfig(mode=ReasoningMode.FALLBACK)
    assert extras is not None
    merged_openai: dict[str, Any] = {"reasoning_effort": "high"}
    merged_openai.update(extras)
    return ReasoningConfig.native(openai_extras=merged_openai)


def _resolve_agent_reasoning_config_for_chat_mode(
    lm_backend: str,
    chat_mode: str,
    model_id: str,
) -> ReasoningConfig:
    """Like :func:`_resolve_agent_reasoning_config` but honor ``PLAN_AGENT_ANTHROPIC_THINKING``.

    When ``PLAN_AGENT`` is set and the chat is ``plan`` or ``plan_discover`` on Anthropic, use
    ``PLAN_AGENT_ANTHROPIC_THINKING`` if non-empty so Sonnet can use adaptive thinking while
    ``AGENT_ANTHROPIC_THINKING=off`` keeps Haiku happy for instant chat.

    ``model_id`` is the resolved model for this request (``PLAN_AGENT`` or
    ``AGENT_MODEL``); adaptive thinking is omitted when the id is known not to
    support it (e.g. ``claude-sonnet-4-5``).

    ``plan_execute`` uses the default agent model and default reasoning config
    (no plan-only override).
    """
    base = _resolve_agent_reasoning_config(lm_backend)
    if chat_mode not in ("plan", "plan_discover"):
        return base
    if lm_backend != "anthropic":
        return base
    if not os.environ.get("PLAN_AGENT", "").strip():
        return base
    override_raw = os.environ.get("PLAN_AGENT_ANTHROPIC_THINKING", "").strip()
    if not override_raw:
        return base
    if base.mode is not ReasoningMode.NATIVE:
        return base
    kw = _anthropic_thinking_from_env_raw(override_raw, "PLAN_AGENT_ANTHROPIC_THINKING")
    kw = _coerce_anthropic_thinking_kw_for_model(model_id, kw)
    return ReasoningConfig.native(anthropic_thinking=kw)


def _resolve_agent_max_completion_tokens() -> int:
    """OpenAI completion token budget per agent request (API may enforce a lower cap)."""
    raw = os.environ.get("AGENT_MAX_COMPLETION_TOKENS", "").strip()
    if raw:
        try:
            n = int(raw)
        except ValueError:
            n = 16_384
        return max(_AGENT_COMPLETION_TOKENS_FLOOR, min(n, _AGENT_COMPLETION_TOKENS_CAP))
    try:
        c = get_config()
        n = int(getattr(c, "agent_max_completion_tokens", 16_384))
        if n > 0:
            return max(_AGENT_COMPLETION_TOKENS_FLOOR, min(n, _AGENT_COMPLETION_TOKENS_CAP))
    except Exception:
        pass
    return 16_384


class _ProviderSetupError(Exception):
    """Raised by :func:`_resolve_provider` when the provider cannot be created."""

    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


def _resolve_provider(lm_backend: str, model: str) -> Any:
    """Instantiate the LLM provider for *lm_backend* and *model*.

    Raises :class:`_ProviderSetupError` with a user-facing message on failure.
    Callers in generator entrypoints catch this and ``yield`` the error event.
    """
    max_tokens = _resolve_agent_max_completion_tokens()
    if lm_backend == "anthropic":
        api_key = _resolve_anthropic_api_key()
        if not api_key:
            raise _ProviderSetupError(
                "Missing ANTHROPIC_API_KEY (required when AGENT_LLM_BACKEND=anthropic)"
            )
        try:
            from llm_markdown.providers import AnthropicProvider
        except ImportError:
            raise _ProviderSetupError(
                "Install llm-markdown with the anthropic extra (llm-markdown[anthropic])"
            )
        return AnthropicProvider(api_key=api_key, model=model, max_tokens=max_tokens)
    else:
        api_key = _resolve_openai_api_key()
        if not api_key:
            raise _ProviderSetupError("Missing OPENAI_API_KEY (or llm_api_key in hof.config.py)")
        try:
            from llm_markdown.providers import OpenAIProvider
        except ImportError:
            raise _ProviderSetupError(
                "Install llm-markdown with the openai extra (llm-markdown[openai])"
            )
        return OpenAIProvider(api_key=api_key, model=model, max_tokens=max_tokens)


def default_normalize_attachments(raw: Any) -> tuple[list[dict[str, str]], str | None]:
    """Accept ``[{object_key, filename?, content_type?}]`` without extra validation."""
    if raw is None:
        return [], None
    if not isinstance(raw, list):
        return [], "attachments must be a list"
    out: list[dict[str, str]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            return [], f"attachments[{i}] must be an object"
        key = (item.get("object_key") or item.get("s3_key") or "").strip()
        if not key:
            return [], f"attachments[{i}] missing object_key"
        entry: dict[str, str] = {"object_key": key}
        fn = item.get("filename")
        if isinstance(fn, str) and fn.strip():
            entry["filename"] = fn.strip()[:500]
        ct = item.get("content_type")
        if isinstance(ct, str) and ct.strip():
            entry["content_type"] = ct.strip()[:200]
        out.append(entry)
    return out, None


def default_attachments_system_note(items: list[dict[str, str]]) -> str:
    lines = []
    for it in items:
        k = it["object_key"]
        extra = []
        if it.get("filename"):
            extra.append(f"name={it['filename']}")
        if it.get("content_type"):
            extra.append(f"type={it['content_type']}")
        suf = f" ({', '.join(extra)})" if extra else ""
        lines.append(f"- {k}{suf}")
    return "\n".join(lines)


def _browser_system_prompt_suffix(policy: AgentPolicy) -> str:
    bc = policy.browser
    if bc is None:
        return ""
    keys = list(bc.sensitive_keys_for_prompt)
    keys_block = ""
    if keys:
        lines = "\n".join(f"- {k}" for k in keys)
        keys_block = (
            "\n\nAvailable sensitive data keys (use in the task as `<secret:key>`):\n" + lines
        )
    return (
        "\n\n## Web browsing\n\n"
        "Use the `hof_builtin_browse_web` tool to run a real browser in Browser Use Cloud. "
        "Pass a clear `task` string. For credentials or secrets configured in the app, "
        "reference them as `<secret:key_name>` in the task text.\n\n"
        "Public sites often show **cookie banners** and **login/register modals** (e.g. “Hallo”, "
        "“Einloggen”, newsletter popups). In the `task`, tell the browser"
        " agent to **close or dismiss "
        "those first** (Schließen, Später, Not now, X, or continue without account) **before** "
        "searching or clicking results — otherwise the run can appear to stop with the UI blocked "
        "behind a modal." + keys_block
    )


def _build_system_prompt(policy: AgentPolicy, *, attachment_note: str) -> str:
    text = (
        policy.system_prompt_intro
        + policy.system_prompt_body
        + policy.system_prompt_mutation_suffix
    )
    if attachment_note.strip():
        text += "\n\n## User file attachments\n" + attachment_note.strip()
    text += _browser_system_prompt_suffix(policy)
    return text


def _browser_tool_exec_result_from_raw(name: str, raw: str) -> ToolExecResult:
    ok, code = tool_result_status_for_ui(raw)
    return ToolExecResult(
        raw_json=raw,
        summary=summarize_tool_json(name, raw),
        ok=ok,
        status_code=code,
        parsed_data=parsed_tool_result_for_stream(raw),
    )


def _yield_awaiting_web_session_barrier(
    *,
    provider: Any,
    model: str,
    policy: AgentPolicy,
    oa_messages: list[dict[str, Any]],
    start_round: int,
    rid: str,
    session_id: str,
    tool_call_id: str,
    canvas_path: str,
    sse_channel: str,
    task: str,
    lm_backend: str,
    reasoning: ReasoningConfig,
    max_tool_output_chars: int,
    max_cli_line_chars: int,
    agent_chat_mode: str,
    chat_attachments: list[dict[str, str]] | None,
) -> Iterator[dict[str, Any]]:
    """Optional summary turn (like inbox review), then persist and emit ``awaiting_web_session``."""
    if policy.web_session_barrier_summary_mode != "none":
        yield from _stream_web_session_barrier_summary_for_ui(
            provider,
            model,
            policy,
            oa_messages,
            start_round,
            rid,
            task=task,
            session_id=session_id,
            lm_backend=lm_backend,
            reasoning=reasoning,
            max_tool_output_chars=max_tool_output_chars,
            max_cli_line_chars=max_cli_line_chars,
        )
    ttl = max(60, int(policy.inbox_review_state_ttl_sec))
    payload: dict[str, Any] = {
        "oa_messages": oa_messages,
        "model": model,
        "llm_backend": lm_backend,
        "rounds": start_round,
        "open_web_session": {
            "session_id": session_id,
            "tool_call_id": tool_call_id,
        },
        "agent_chat_mode": agent_chat_mode,
    }
    if chat_attachments is not None:
        payload["chat_attachments"] = chat_attachments
    _save_agent_run_with_ttl_merge_attachments(rid, payload, ttl)
    yield {
        "type": "awaiting_web_session",
        "run_id": rid,
        "session_id": session_id,
        "tool_call_id": tool_call_id,
        "canvas_path": canvas_path,
        "sse_channel": sse_channel,
    }
    _agent_stream_debug_append(
        {
            "kind": "awaiting_web_session",
            "run_id": rid,
            "session_id": session_id,
        },
    )
    logger.debug(
        "agent_chat awaiting_web_session run_id=%s session_id=%s tool_call_id=%s",
        rid,
        session_id,
        tool_call_id,
    )


def _stream_hof_browser_tool_async_barrier(
    *,
    policy: AgentPolicy,
    provider: Any,
    args_wire: str,
    run_id: str,
    tid: str,
    oa_messages: list[dict[str, Any]],
    rounds: int,
    model: str,
    lm_backend: str,
    reasoning: ReasoningConfig,
    max_tool_output_chars: int,
    max_cli_line_chars: int,
    agent_chat_mode: str,
    chat_attachments: list[dict[str, str]] | None,
) -> Iterator[dict[str, Any]]:
    """Fast create + background poll; placeholder tool row; ``awaiting_web_session`` barrier."""
    from hof.browser.runner import create_browser_cloud_session_sync, spawn_browser_poll_background
    from hof.browser.sensitive import resolve_sensitive_data_sync

    bc = policy.browser
    if bc is None:
        err = {
            "error": "browser is not configured on AgentPolicy (set browser=BrowserConfig(...))",
        }
        raw = json.dumps(err)
        tex = _browser_tool_exec_result_from_raw(HOF_BUILTIN_BROWSE_WEB, raw)
        tr_out: dict[str, Any] = {
            "type": "tool_result",
            "name": HOF_BUILTIN_BROWSE_WEB,
            "summary": tex.summary,
            "tool_call_id": tid,
            "ok": tex.ok,
            "status_code": tex.status_code,
        }
        if tex.parsed_data is not None:
            tr_out["data"] = tex.parsed_data
        yield tr_out
        oa_messages.append(
            {
                "role": "tool",
                "tool_call_id": tid,
                "content": format_tool_result_for_model(HOF_BUILTIN_BROWSE_WEB, tex.raw_json),
            },
        )
        return
    try:
        parsed = json.loads(args_wire) if args_wire else {}
        if not isinstance(parsed, dict):
            parsed = {}
    except json.JSONDecodeError:
        parsed = {}
    task = str(parsed.get("task") or "").strip()
    sk_raw = parsed.get("sensitive_keys")
    sensitive_keys: list[str] | None = None
    if isinstance(sk_raw, list):
        sensitive_keys = [str(x) for x in sk_raw if x is not None]

    if not task:
        err = {"error": "task is required"}
        raw = json.dumps(err)
        tex = _browser_tool_exec_result_from_raw(HOF_BUILTIN_BROWSE_WEB, raw)
        tr_err: dict[str, Any] = {
            "type": "tool_result",
            "name": HOF_BUILTIN_BROWSE_WEB,
            "summary": tex.summary,
            "tool_call_id": tid,
            "ok": tex.ok,
            "status_code": tex.status_code,
        }
        if tex.parsed_data is not None:
            tr_err["data"] = tex.parsed_data
        yield tr_err
        oa_messages.append(
            {
                "role": "tool",
                "tool_call_id": tid,
                "content": format_tool_result_for_model(HOF_BUILTIN_BROWSE_WEB, tex.raw_json),
            },
        )
        return

    sensitive = resolve_sensitive_data_sync(policy, sensitive_keys)

    try:
        api_key_resolved = resolve_browser_api_key_value(bc.api_key)
        if not api_key_resolved:
            raise ValueError(
                "browser API key is empty after resolving ${VAR} placeholders "
                "(set BROWSER_USE_API_KEY or pass a literal key in BrowserConfig)"
            )
        created = create_browser_cloud_session_sync(
            task=task,
            api_key=api_key_resolved,
            model=(bc.default_model or "").strip() or None,
            enable_recording=bc.enable_recording,
            http_timeout_sec=bc.http_timeout_sec,
            sensitive_data=sensitive if sensitive else None,
            on_progress=None,
        )
    except Exception as exc:
        logger.exception("hof_builtin_browse_web async create failed run_id=%s", run_id)
        err = {"error": str(exc)}
        raw = json.dumps(err)
        tex = _browser_tool_exec_result_from_raw(HOF_BUILTIN_BROWSE_WEB, raw)
        tr_exc: dict[str, Any] = {
            "type": "tool_result",
            "name": HOF_BUILTIN_BROWSE_WEB,
            "summary": tex.summary,
            "tool_call_id": tid,
            "ok": tex.ok,
            "status_code": tex.status_code,
        }
        if tex.parsed_data is not None:
            tr_exc["data"] = tex.parsed_data
        yield tr_exc
        oa_messages.append(
            {
                "role": "tool",
                "tool_call_id": tid,
                "content": format_tool_result_for_model(HOF_BUILTIN_BROWSE_WEB, tex.raw_json),
            },
        )
        return

    sid = str(created.get("session_id") or "")
    live_url = str(created.get("live_url") or "")
    sse_ch = str(created.get("sse_channel") or "")
    yield {
        "type": "web_session_started",
        "session_id": sid,
        "live_url": live_url,
        "task": task,
        "sse_channel": sse_ch,
    }
    canvas_path = f"/web-sessions?id={sid}" if sid else "/web-sessions"
    ph_obj: dict[str, Any] = {
        "web_session_pending": True,
        "session_id": sid,
        "live_url": live_url,
        "message": "Browser session running in Browser Use Cloud.",
        "canvas_path": canvas_path,
    }
    placeholder = json.dumps(ph_obj)
    yield {
        "type": "tool_result",
        "name": HOF_BUILTIN_BROWSE_WEB,
        "summary": "Browser session running in cloud (resume when complete).",
        "status_code": 202,
        "tool_call_id": tid,
        "data": ph_obj,
    }
    oa_messages.append(
        {
            "role": "tool",
            "tool_call_id": tid,
            "content": placeholder,
        },
    )
    spawn_browser_poll_background(
        session_id=sid,
        live_url=live_url,
        sse_channel=sse_ch,
        api_key=api_key_resolved,
        enable_recording=bc.enable_recording,
        poll_interval_sec=bc.poll_interval_sec,
        task_timeout_sec=bc.task_timeout_sec,
        http_timeout_sec=bc.http_timeout_sec,
        on_progress=None,
    )
    yield from _yield_awaiting_web_session_barrier(
        provider=provider,
        model=model,
        policy=policy,
        oa_messages=oa_messages,
        start_round=rounds,
        rid=run_id,
        session_id=sid,
        tool_call_id=tid,
        canvas_path=canvas_path,
        sse_channel=sse_ch,
        task=task,
        lm_backend=lm_backend,
        reasoning=reasoning,
        max_tool_output_chars=max_tool_output_chars,
        max_cli_line_chars=max_cli_line_chars,
        agent_chat_mode=agent_chat_mode,
        chat_attachments=chat_attachments,
    )


def _stream_hof_browser_tool(
    *,
    policy: AgentPolicy,
    args_wire: str,
    run_id: str,
    tid: str,
    max_tool_output_chars: int,
    oa_messages: list[dict[str, Any]],
) -> Iterator[dict[str, Any]]:
    """Emit ``web_session_*`` NDJSON events, then ``tool_result`` for the browse tool."""
    from hof.browser.sensitive import resolve_sensitive_data_sync
    from hof.browser.stream_bridge import start_browser_tool_progress

    if policy.browser is None:
        err = {
            "error": "browser is not configured on AgentPolicy (set browser=BrowserConfig(...))",
        }
        raw = json.dumps(err)
        tex = _browser_tool_exec_result_from_raw(HOF_BUILTIN_BROWSE_WEB, raw)
        tr_out: dict[str, Any] = {
            "type": "tool_result",
            "name": HOF_BUILTIN_BROWSE_WEB,
            "summary": tex.summary,
            "tool_call_id": tid,
            "ok": tex.ok,
            "status_code": tex.status_code,
        }
        if tex.parsed_data is not None:
            tr_out["data"] = tex.parsed_data
        yield tr_out
        oa_messages.append(
            {
                "role": "tool",
                "tool_call_id": tid,
                "content": format_tool_result_for_model(HOF_BUILTIN_BROWSE_WEB, tex.raw_json),
            },
        )
        return

    bc = policy.browser
    try:
        parsed = json.loads(args_wire) if args_wire else {}
        if not isinstance(parsed, dict):
            parsed = {}
    except json.JSONDecodeError:
        parsed = {}
    task = str(parsed.get("task") or "").strip()
    sk_raw = parsed.get("sensitive_keys")
    sensitive_keys: list[str] | None = None
    if isinstance(sk_raw, list):
        sensitive_keys = [str(x) for x in sk_raw if x is not None]

    if not task:
        err = {"error": "task is required"}
        raw = json.dumps(err)
        tex = _browser_tool_exec_result_from_raw(HOF_BUILTIN_BROWSE_WEB, raw)
        tr_out = {
            "type": "tool_result",
            "name": HOF_BUILTIN_BROWSE_WEB,
            "summary": tex.summary,
            "tool_call_id": tid,
            "ok": tex.ok,
            "status_code": tex.status_code,
        }
        if tex.parsed_data is not None:
            tr_out["data"] = tex.parsed_data
        yield tr_out
        oa_messages.append(
            {
                "role": "tool",
                "tool_call_id": tid,
                "content": format_tool_result_for_model(HOF_BUILTIN_BROWSE_WEB, tex.raw_json),
            },
        )
        return

    sensitive = resolve_sensitive_data_sync(policy, sensitive_keys)

    try:
        api_key_resolved = resolve_browser_api_key_value(bc.api_key)
        if not api_key_resolved:
            raise ValueError(
                "browser API key is empty after resolving ${VAR} placeholders "
                "(set BROWSER_USE_API_KEY or pass a literal key in BrowserConfig)"
            )
        gen, holder = start_browser_tool_progress(
            task=task,
            api_key=api_key_resolved,
            model=(bc.default_model or "").strip() or None,
            enable_recording=bc.enable_recording,
            poll_interval_sec=bc.poll_interval_sec,
            task_timeout_sec=bc.task_timeout_sec,
            http_timeout_sec=bc.http_timeout_sec,
            sensitive_data=sensitive if sensitive else None,
        )
        yield from gen
        result = holder.get("result")
    except Exception as exc:
        logger.exception("hof_builtin_browse_web failed run_id=%s", run_id)
        err = {"error": str(exc)}
        raw = json.dumps(err)
        tex = _browser_tool_exec_result_from_raw(HOF_BUILTIN_BROWSE_WEB, raw)
        tr_out = {
            "type": "tool_result",
            "name": HOF_BUILTIN_BROWSE_WEB,
            "summary": tex.summary,
            "tool_call_id": tid,
            "ok": tex.ok,
            "status_code": tex.status_code,
        }
        if tex.parsed_data is not None:
            tr_out["data"] = tex.parsed_data
        yield tr_out
        oa_messages.append(
            {
                "role": "tool",
                "tool_call_id": tid,
                "content": format_tool_result_for_model(HOF_BUILTIN_BROWSE_WEB, tex.raw_json),
            },
        )
        return

    if not isinstance(result, dict):
        err = {"error": "browser task produced no result"}
        raw = json.dumps(err)
        tex = _browser_tool_exec_result_from_raw(HOF_BUILTIN_BROWSE_WEB, raw)
        tr_out = {
            "type": "tool_result",
            "name": HOF_BUILTIN_BROWSE_WEB,
            "summary": tex.summary,
            "tool_call_id": tid,
            "ok": tex.ok,
            "status_code": tex.status_code,
        }
        if tex.parsed_data is not None:
            tr_out["data"] = tex.parsed_data
        yield tr_out
        oa_messages.append(
            {
                "role": "tool",
                "tool_call_id": tid,
                "content": format_tool_result_for_model(HOF_BUILTIN_BROWSE_WEB, tex.raw_json),
            },
        )
        return

    sid = str(result.get("session_id") or "")
    out_payload: dict[str, Any] = {
        "session_id": sid,
        "live_url": result.get("live_url"),
        "output": result.get("output"),
        "recording_urls": result.get("recording_urls"),
        "status": result.get("status"),
        "sse_channel": result.get("sse_channel"),
    }
    if sid:
        out_payload["canvas_path"] = f"/web-sessions?id={sid}"
        out_payload["canvas_href"] = (
            f"[Open browser session]({out_payload['canvas_path']}?hof_chat_embed=1)"
        )
    raw = json.dumps(out_payload, default=str)
    truncated = len(raw) > max_tool_output_chars
    if truncated:
        raw = raw[: max_tool_output_chars - 24] + "\n…(truncated)"
    tex = _browser_tool_exec_result_from_raw(HOF_BUILTIN_BROWSE_WEB, raw)
    tr_out = {
        "type": "tool_result",
        "name": HOF_BUILTIN_BROWSE_WEB,
        "summary": tex.summary,
        "tool_call_id": tid,
        "ok": tex.ok,
        "status_code": tex.status_code,
    }
    if tex.parsed_data is not None:
        tr_out["data"] = tex.parsed_data
    yield tr_out
    oa_messages.append(
        {
            "role": "tool",
            "tool_call_id": tid,
            "content": format_tool_result_for_model(HOF_BUILTIN_BROWSE_WEB, tex.raw_json),
        },
    )


def _build_discover_tools(
    policy: AgentPolicy,
    *,
    phase: Literal["explore", "clarify", "propose"],
) -> tuple[frozenset[str], list[dict[str, Any]]]:
    """Allowlist and OpenAI tool specs for plan-discover mode.

    - **explore:** Domain reads and non-terminal builtins only — model cannot
      call clarification or ``hof_builtin_present_plan`` until it has produced
      at least one assistant text turn (enforced in the tool loop).
    - **clarify:** Like explore plus ``hof_builtin_present_plan_clarification``;
      ``hof_builtin_present_plan`` stays unavailable until resume after answers.
    - **propose:** Full read set plus all builtins (used after clarification resume).

    With **terminal-only** sandbox dispatch, domain reads are omitted; the effective
    allowlist is :meth:`AgentPolicy.effective_allowlist` minus phase excludes.
    """
    sc = policy.sandbox.with_env_overrides() if policy.sandbox is not None else None
    if sc is not None and sc.enabled and sc.terminal_only_dispatch:
        eff = policy.effective_allowlist()
        if phase == "explore":
            allowlist = frozenset(eff - _DISCOVER_EXCLUDE_FROM_EXPLORE)
        elif phase == "clarify":
            allowlist = frozenset(eff - {_HOF_BUILTIN_PRESENT_PLAN})
        else:
            allowlist = eff
        return allowlist, openai_tool_specs(allowlist)
    base_read = policy.allowlist_read
    builtins_all = BUILTIN_AGENT_TOOL_NAMES
    if phase == "explore":
        allowlist = frozenset(
            base_read | (builtins_all - _DISCOVER_EXCLUDE_FROM_EXPLORE),
        )
    elif phase == "clarify":
        allowlist = frozenset(
            base_read | (builtins_all - {_HOF_BUILTIN_PRESENT_PLAN}),
        )
    else:
        allowlist = frozenset(base_read | builtins_all)
    return allowlist, openai_tool_specs(allowlist)


_AGENT_CHAT_PLAN_EXECUTE_SUFFIX = (
    "\n\n## Approved plan execution\n"
    "The user approved the plan. Execute it step by step using tools when needed.\n"
    "**Checklist is the source of truth.** Map your work to the `- [ ]` lines in the approved plan "
    "(0-based index from top to bottom).\n\n"
    "**Reasoning / thinking (before tools):** In every turn, briefly state **which step(s)** you "
    "are on (index + short label), **which steps are already complete**, and **what is next**. "
    "Do not only describe tools — tie progress to the plan checklist.\n\n"
    "**MANDATORY (UI progress):** Call `hof_builtin_update_plan_todo_state` whenever "
    "checklist progress changes — **not** only at the end. After each substantive step that "
    "completes a checklist row, call with **cumulative** `done_indices`.\n"
    "- Pass `done_indices` as a JSON array of integers: the **0-based indices** of every checklist "
    "row that is **complete so far** (same top-to-bottom order as the `- [ ]` lines in "
    "the approved plan below). Example: after finishing the first two tasks, call with "
    '`{"done_indices": [0, 1]}`; after the third, `{"done_indices": [0, 1, 2]}`.\n'
    "- Call the tool **multiple times per turn** if you complete several steps in one round.\n"
    "- Do not rely on editing markdown checkboxes — only this tool updates the UI.\n"
    "Also briefly note progress in your visible replies.\n"
)

_AGENT_CHAT_PLAN_DISCOVER_PREFIX = (
    "# Plan discovery mode\n\n"
    "The user wants a **reviewable plan** before any execution. Delivery happens in "
    "three layers: explore → **clarification questionnaire** → **structured plan proposal**. "
    "The UI shows questions and the plan from the built-in tools; treat those tools as the "
    "official handoff points.\n\n"
    "## Explore (first phase)\n\n"
    "Use domain read tools to understand scope, counts, and constraints. "
    "**Purpose:** inform what you will ask, not to deliver the final answer.\n\n"
    "After tools, write **at least one** assistant message that is **short**: restate the goal "
    "in your own words, note what you inspected, and what remains to decide. "
    "Keep it to a brief orientation (roughly a small paragraph). "
    "**Include detailed tables, full line-by-line listings, long reports, or exhaustive "
    "figures only after** the user has answered clarification and approved a plan "
    "(execution phase). During exploration, prefer high-level counts or one example if needed "
    "to phrase questions.\n\n"
    "## Clarify (second phase)\n\n"
    "Call `hof_builtin_present_plan_clarification` with **concrete** multiple-choice "
    "questions about anything that changes the plan (format, timeframe, scope, filters, "
    "priorities). "
    "Aim for questions that a product owner would expect before signing off. "
    "This step **is** the user’s steering moment before you commit to steps.\n\n"
    "## Propose (after the user submits answers)\n\n"
    "Use reads if needed, then call `hof_builtin_present_plan` with title, description, "
    "and checklist steps the user can approve.\n\n"
    "---\n\n"
)

_AGENT_CHAT_PLAN_DISCOVER_SUFFIX = (
    "\n\n## Plan discovery (reminder)\n"
    "Phase order: explore briefly → **`hof_builtin_present_plan_clarification`** → "
    "(user answers) → **`hof_builtin_present_plan`**. "
    "The active tool set matches that sequence; your visible prose should too: "
    "orientation and questions first, rich deliverables after approval.\n"
)

_AGENT_CHAT_PLAN_DISCOVER_FINAL_LOCK = (
    "\n\n## Planning mode — priority (read this section last)\n"
    "**For Plan discovery, this section applies on top of the general instructions above.**\n"
    "Until the user has submitted the clarification questionnaire, your visible output is **only** "
    "short orientation: restate the goal, note what you checked with tools, and what still needs a "
    "decision. **Then call** `hof_builtin_present_plan_clarification` with concrete "
    "multiple-choice questions.\n"
    "**Reserve for plan execution (after the user approves a plan):** full markdown tables, "
    "line-by-line expense listings, depreciation schedules, totals, and narrative reports. "
    "**During discovery,** one or two numbers to phrase a question are fine; comprehensive answers "
    "are not.\n"
)


def _normalize_agent_chat_mode(mode: str | None) -> str:
    """Return ``instant``, ``plan_discover``, or ``plan_execute``."""
    raw = (mode or "").strip().lower().replace("-", "_")
    if raw in ("plan", "plan_discover"):
        return "plan_discover"
    if raw == "plan_execute":
        return raw
    return "instant"


def _append_client_messages(
    oa_messages: list[dict[str, Any]],
    messages: list,
    att_norm: list[dict[str, str]],
) -> None:
    """Append client ``messages`` into ``oa_messages`` (mutates in place).

    Skips empty user/assistant text except: last list item is ``user`` with whitespace-only
    content and ``att_norm`` is non-empty — then append a user turn with U+2060 WORD JOINER
    (strip() is non-empty for providers; attachment metadata is in the system prompt note).
    """
    n = len(messages)
    for idx, m in enumerate(messages):
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        if not isinstance(content, str):
            continue
        stripped = content.strip()
        if role == "user":
            if stripped:
                oa_messages.append({"role": "user", "content": stripped})
            elif att_norm and idx == n - 1:
                oa_messages.append({"role": "user", "content": "\u2060"})
        elif role == "assistant" and stripped:
            oa_messages.append({"role": "assistant", "content": stripped})


def collect_agent_chat_from_stream(
    events_iter: Iterator[dict[str, Any]],
) -> dict[str, Any]:
    """Fold stream events into the legacy JSON shape for non-streaming ``agent_chat`` callers."""
    max_model_text_chars = _agent_limits()[2]

    legacy: list[dict[str, Any]] = []
    reply = ""
    model_out = ""
    rounds = 0
    buf = ""
    for ev in events_iter:
        t = ev.get("type")
        if t == "run_start":
            model_out = str(ev.get("model") or "")
            legacy.append({"type": "thinking", "detail": "Starting agent run…"})
        elif t == "phase":
            r = int(ev.get("round") or 0)
            ph = str(ev.get("phase") or "")
            if ph == "model":
                legacy.append({"type": "thinking", "detail": f"Round {r}: calling model…"})
            elif ph == "tools":
                legacy.append({"type": "thinking", "detail": f"Round {r}: executing tools…"})
            elif ph == "summary":
                legacy.append({"type": "thinking", "detail": f"Round {r}: confirmation reply…"})
        elif t == "segment_start":
            continue
        elif t == "assistant_delta" or t == "reasoning_delta":
            buf += str(ev.get("text") or "")
        elif t == "assistant_done":
            raw = buf.strip()
            if raw:
                tr = len(raw) > max_model_text_chars
                legacy.append(
                    {
                        "type": "model_text",
                        "content": raw[:max_model_text_chars] if tr else raw,
                        "truncated": tr,
                    },
                )
            buf = ""
            meta_ev: dict[str, Any] = {"type": "model_meta"}
            if ev.get("finish_reason") is not None:
                meta_ev["finish_reason"] = ev["finish_reason"]
            if ev.get("usage"):
                meta_ev["usage"] = ev["usage"]
            if len(meta_ev) > 1:
                legacy.append(meta_ev)
        elif t == "tool_call":
            leg_tc: dict[str, Any] = {
                "type": "tool_call",
                "name": ev.get("name"),
                "arguments": str(ev.get("arguments") or "")[:2000],
                "cli_line": ev.get("cli_line", ""),
            }
            dtl = ev.get("display_title")
            if isinstance(dtl, str) and dtl.strip():
                leg_tc["display_title"] = dtl.strip()
            legacy.append(leg_tc)
        elif t == "tool_result":
            tr_legacy: dict[str, Any] = {
                "type": "tool_result",
                "name": ev.get("name"),
                "summary": ev.get("summary", ""),
            }
            if "data" in ev:
                tr_legacy["data"] = ev["data"]
            if ev.get("pending_confirmation"):
                tr_legacy["pending_confirmation"] = True
            if "status_code" in ev:
                tr_legacy["status_code"] = ev["status_code"]
            if "ok" in ev:
                tr_legacy["ok"] = ev["ok"]
            legacy.append(tr_legacy)
        elif t == "mutation_pending":
            legacy.append(
                {
                    "type": "thinking",
                    "detail": (
                        f"Mutation pending confirmation: {ev.get('name')} "
                        f"(pending_id={ev.get('pending_id')})"
                    ),
                },
            )
        elif t == "awaiting_confirmation":
            legacy.append(
                {
                    "type": "thinking",
                    "detail": (
                        "Waiting for user confirmation in the assistant "
                        "(or agent_resume_mutations)."
                    ),
                },
            )
        elif t == "awaiting_plan_clarification":
            legacy.append(
                {
                    "type": "thinking",
                    "detail": (
                        "Waiting for plan clarification answers "
                        "(agent_resume_plan_clarification stream)."
                    ),
                },
            )
            return {
                "awaiting_plan_clarification": True,
                "run_id": str(ev.get("run_id") or ""),
                "clarification_id": str(ev.get("clarification_id") or ""),
                "questions": (ev.get("questions") if isinstance(ev.get("questions"), list) else []),
                "reply": "",
                "events": legacy,
                "tool_rounds_used": rounds,
                "model": model_out,
            }
        elif t == "awaiting_web_session":
            legacy.append(
                {
                    "type": "thinking",
                    "detail": (
                        "Waiting for browser session to complete (agent_resume_web_session stream)."
                    ),
                },
            )
            return {
                "awaiting_web_session": True,
                "run_id": str(ev.get("run_id") or ""),
                "session_id": str(ev.get("session_id") or ""),
                "tool_call_id": str(ev.get("tool_call_id") or ""),
                "canvas_path": str(ev.get("canvas_path") or ""),
                "reply": "",
                "events": legacy,
                "tool_rounds_used": rounds,
                "model": model_out,
            }
        elif t == "resume_start":
            legacy.append({"type": "thinking", "detail": "Continuing after confirmation…"})
        elif t == "final":
            reply = str(ev.get("reply") or "").strip()
            rounds = int(ev.get("tool_rounds_used") or rounds)
            model_out = str(ev.get("model") or model_out)
            legacy.append({"type": "done", "detail": "Answer ready"})
            return {
                "reply": reply,
                "events": legacy,
                "tool_rounds_used": rounds,
                "model": model_out,
            }
        elif t == "error":
            err_detail = str(ev.get("detail") or "error")
            legacy.append({"type": "error", "detail": err_detail})
            return {
                "error": err_detail,
                "reply": "",
                "events": legacy,
                "tool_rounds_used": rounds,
                "model": model_out,
            }
    return {
        "error": "agent_empty",
        "reply": "",
        "events": legacy,
        "tool_rounds_used": rounds,
        "model": model_out,
    }


def _yield_confirmation_summary_static(
    rounds: int,
    text: str,
) -> Iterator[dict[str, Any]]:
    """Single non-streamed assistant hint before awaiting_confirmation (no extra LLM round)."""
    yield {"type": "phase", "round": rounds, "phase": "summary"}
    yield {"type": "assistant_delta", "text": text}
    yield {"type": "assistant_done", "finish_reason": "stop"}


def _stream_confirmation_summary_for_ui(
    provider: Any,
    model: str,
    oa_messages: list[dict[str, Any]],
    rounds: int,
    summary_user_message: str,
    *,
    lm_backend: str,
    reasoning: ReasoningConfig,
) -> Iterator[dict[str, Any]]:
    from llm_markdown.agent_stream import (
        AgentContentDelta,
        AgentMessageFinish,
        AgentReasoningDelta,
    )

    msgs = list(oa_messages) + [{"role": "user", "content": summary_user_message}]
    yield {"type": "phase", "round": rounds, "phase": "summary"}
    assistant_text = ""
    finish_reason: str | None = None
    last_usage: dict[str, Any] | None = None
    try:
        for ev in _iter_stream_agent_turn_with_engine_retries(
            provider,
            lm_backend,
            msgs,
            model=model,
            tools=None,
            tool_choice=None,
            max_tokens=_AGENT_SUMMARY_MAX_TOKENS,
            reasoning=reasoning,
            **_anthropic_stream_turn_extras(lm_backend, reasoning),
        ):
            pw = _provider_wait_wire(ev)
            if pw is not None:
                yield pw
                continue
            if isinstance(ev, AgentContentDelta):
                assistant_text += ev.text
                yield {"type": "assistant_delta", "text": ev.text}
            elif isinstance(ev, AgentReasoningDelta):
                yield {"type": "reasoning_delta", "text": ev.text}
            elif isinstance(ev, AgentMessageFinish):
                finish_reason = ev.finish_reason
                last_usage = ev.usage
    except _AgentStreamTurnExhaustedError:
        logger.warning(
            "confirmation summary model call failed after engine stream retries, "
            "using static fallback",
        )
        yield {"type": "assistant_delta", "text": _CONFIRMATION_SUMMARY_STATIC_FALLBACK}
        yield {"type": "assistant_done", "finish_reason": "stop"}
        return
    except Exception as exc:
        logger.warning("confirmation summary model call failed: %s", exc)
        yield {"type": "assistant_delta", "text": _CONFIRMATION_SUMMARY_STATIC_FALLBACK}
        yield {"type": "assistant_done", "finish_reason": "stop"}
        return

    if not assistant_text.strip():
        yield {"type": "assistant_delta", "text": _CONFIRMATION_SUMMARY_STATIC_FALLBACK}
        finish_reason = finish_reason or "stop"
    done_ev: dict[str, Any] = {
        "type": "assistant_done",
        "finish_reason": finish_reason or "stop",
    }
    if last_usage:
        done_ev["usage"] = last_usage
    yield done_ev


_INBOX_REVIEW_SUMMARY_MAX_ROUNDS = 5


def _format_web_session_barrier_block(
    *,
    task: str,
    session_id: str,
) -> str:
    """Human- and model-readable lines.

    In-app markdown link opens the embed panel (no external URLs).
    """
    qid = quote(session_id, safe="")
    app_path = f"/web-sessions?id={qid}"
    return "\n".join(
        [
            f"- **Session id:** `{session_id}`",
            f"- **Task:** {task or '—'}",
            f"- **Watch in side panel:** [Open Web sessions]({app_path})",
        ],
    )


def _web_session_barrier_static_message(
    *,
    task: str,
    session_id: str,
) -> str:
    parts = [
        "The assistant started a **browser session**. "
        "Open **Web sessions** in the side panel (in-app link below) "
        "to see the live view and activity; "
        "the chat continues automatically when the session finishes.",
        "",
        "### Session",
        _format_web_session_barrier_block(
            task=task,
            session_id=session_id,
        ),
    ]
    return "\n".join(parts)


def _stream_web_session_barrier_summary_for_ui(
    provider: Any,
    model: str,
    policy: AgentPolicy,
    oa_messages: list[dict[str, Any]],
    start_round: int,
    run_id: str,
    *,
    task: str,
    session_id: str,
    lm_backend: str,
    reasoning: ReasoningConfig,
    max_tool_output_chars: int,
    max_cli_line_chars: int,
) -> Iterator[dict[str, Any]]:
    """Stream assistant guidance before ``awaiting_web_session`` (mirrors inbox review summary)."""
    mode = policy.web_session_barrier_summary_mode
    if mode == "none":
        return

    block = _format_web_session_barrier_block(
        task=task,
        session_id=session_id,
    )
    user_content = (
        f"{policy.web_session_barrier_summary_user_message}\n\n### Active browser session\n{block}"
    )

    if mode == "static":
        text = _web_session_barrier_static_message(
            task=task,
            session_id=session_id,
        )
        oa_messages.append({"role": "user", "content": user_content})
        yield {
            "type": "phase",
            "round": start_round + 1,
            "phase": "web_session_barrier_summary",
        }
        yield {"type": "assistant_delta", "text": text}
        yield {"type": "assistant_done", "finish_reason": "stop"}
        oa_messages.append({"role": "assistant", "content": text})
        return

    if mode != "llm_stream":
        yield {
            "type": "error",
            "detail": (
                f"invalid web_session_barrier_summary_mode={mode!r} "
                "(expected llm_stream, static, or none)"
            ),
        }
        return

    oa_messages.append({"role": "user", "content": user_content})
    sc_wb = policy.sandbox.with_env_overrides() if policy.sandbox is not None else None
    if sc_wb is not None and sc_wb.enabled and sc_wb.terminal_only_dispatch:
        read_allowlist = policy.effective_allowlist()
    else:
        read_allowlist = frozenset(policy.allowlist_read | BUILTIN_AGENT_TOOL_NAMES)
    read_tools = openai_tool_specs(read_allowlist)

    from llm_markdown.agent_stream import (
        AgentContentDelta,
        AgentMessageFinish,
        AgentReasoningDelta,
        AgentSegmentStart,
        AgentToolCallDelta,
    )

    sub_start = start_round
    for sub_i in range(_INBOX_REVIEW_SUMMARY_MAX_ROUNDS):
        phase_round = sub_start + sub_i + 1
        yield {
            "type": "phase",
            "round": phase_round,
            "phase": "web_session_barrier_summary",
        }

        parts: dict[int, dict[str, str]] = {}
        assistant_text = ""
        finish_reason: str | None = None
        last_usage: dict[str, Any] | None = None

        try:
            for ev in _iter_stream_agent_turn_with_engine_retries(
                provider,
                lm_backend,
                oa_messages,
                model=model,
                tools=read_tools,
                tool_choice="auto",
                max_tokens=_AGENT_SUMMARY_MAX_TOKENS,
                reasoning=reasoning,
                **_anthropic_stream_turn_extras(lm_backend, reasoning),
            ):
                pw = _provider_wait_wire(ev)
                if pw is not None:
                    yield pw
                    continue
                if isinstance(ev, AgentSegmentStart):
                    yield {"type": "segment_start", "segment": ev.segment}
                elif isinstance(ev, AgentContentDelta):
                    assistant_text += ev.text
                    yield {"type": "assistant_delta", "text": ev.text}
                elif isinstance(ev, AgentReasoningDelta):
                    yield {"type": "reasoning_delta", "text": ev.text}
                elif isinstance(ev, AgentToolCallDelta):
                    idx = int(ev.index)
                    if idx not in parts:
                        parts[idx] = {"id": "", "name": "", "arguments": ""}
                    if ev.tool_call_id:
                        parts[idx]["id"] = ev.tool_call_id
                    if ev.name:
                        parts[idx]["name"] += ev.name
                    if ev.arguments:
                        parts[idx]["arguments"] += ev.arguments
                elif isinstance(ev, AgentMessageFinish):
                    finish_reason = ev.finish_reason
                    last_usage = ev.usage
        except _AgentStreamTurnExhaustedError:
            logger.warning(
                "web session barrier summary model call failed after engine stream retries, "
                "using static fallback",
            )
            fb = _web_session_barrier_static_message(
                task=task,
                session_id=session_id,
            )
            yield {"type": "assistant_delta", "text": fb}
            yield {"type": "assistant_done", "finish_reason": "stop"}
            oa_messages.append({"role": "assistant", "content": fb})
            return
        except Exception as exc:
            logger.warning("web session barrier summary model call failed: %s", exc)
            fb = _web_session_barrier_static_message(
                task=task,
                session_id=session_id,
            )
            yield {"type": "assistant_delta", "text": fb}
            yield {"type": "assistant_done", "finish_reason": "stop"}
            oa_messages.append({"role": "assistant", "content": fb})
            return

        if finish_reason != "tool_calls":
            final_text = assistant_text.strip() or _web_session_barrier_static_message(
                task=task,
                session_id=session_id,
            )
            if not assistant_text.strip():
                yield {"type": "assistant_delta", "text": final_text}
            done_ev_stop: dict[str, Any] = {
                "type": "assistant_done",
                "finish_reason": finish_reason or "stop",
            }
            if last_usage:
                done_ev_stop["usage"] = last_usage
            yield done_ev_stop
            oa_messages.append({"role": "assistant", "content": final_text})
            return

        done_ev_tc: dict[str, Any] = {
            "type": "assistant_done",
            "finish_reason": finish_reason,
        }
        if last_usage:
            done_ev_tc["usage"] = last_usage
        yield done_ev_tc

        if not parts:
            fb = _web_session_barrier_static_message(
                task=task,
                session_id=session_id,
            )
            yield {"type": "assistant_delta", "text": fb}
            yield {"type": "assistant_done", "finish_reason": "stop"}
            oa_messages.append({"role": "assistant", "content": fb})
            return

        yield {
            "type": "phase",
            "round": phase_round,
            "phase": "web_session_barrier_summary_tools",
        }
        sorted_idx = sorted(parts.keys())
        tool_calls_payload: list[dict[str, Any]] = []
        for idx in sorted_idx:
            tc = parts[idx]
            tid = tc["id"] or f"call_{idx}"
            name = tc["name"]
            args_raw = tc["arguments"] or "{}"
            args_wire, _ = split_agent_tool_display_metadata(args_raw)
            tool_calls_payload.append(
                {
                    "id": tid,
                    "type": "function",
                    "function": {"name": name, "arguments": args_wire},
                },
            )
        oa_messages.append(
            {
                "role": "assistant",
                "content": assistant_text or None,
                "tool_calls": tool_calls_payload,
            },
        )
        for idx in sorted_idx:
            tc = parts[idx]
            name = tc["name"]
            args_raw = tc["arguments"] or "{}"
            args_wire, display_title = split_agent_tool_display_metadata(args_raw)
            tid = tc["id"] or f"call_{idx}"
            cap = _cli_line_cap_for_tool(name, max_cli_line_chars)
            cli = format_cli_line(name, args_wire, max_cli_line_chars=cap)
            arg_cap = _args_wire_emit_cap_chars(name)
            tc_ev: dict[str, Any] = {
                "type": "tool_call",
                "name": name,
                "arguments": args_wire[:arg_cap],
                "cli_line": cli,
                "tool_call_id": tid,
            }
            if display_title:
                tc_ev["display_title"] = display_title
            note = policy.rationale_for(name)
            if note:
                tc_ev["internal_rationale"] = note
            yield tc_ev
            tex = execute_tool(
                name,
                args_wire,
                read_allowlist,
                max_tool_output_chars=max_tool_output_chars,
                run_id=run_id,
                tool_call_id=tid,
            )
            tr_out: dict[str, Any] = {
                "type": "tool_result",
                "name": name,
                "summary": tex.summary,
                "tool_call_id": tid,
                "ok": tex.ok,
                "status_code": tex.status_code,
            }
            if tex.parsed_data is not None:
                tr_out["data"] = tex.parsed_data
            yield tr_out
            oa_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tid,
                    "content": format_tool_result_for_model(name, tex.raw_json),
                },
            )

    fb = _web_session_barrier_static_message(
        task=task,
        session_id=session_id,
    )
    yield {"type": "assistant_delta", "text": fb}
    yield {"type": "assistant_done", "finish_reason": "stop"}
    oa_messages.append({"role": "assistant", "content": fb})


def _format_inbox_watches_block(wires: list[dict[str, Any]]) -> str:
    """Human- and model-readable lines for pending inbox watches (wire dicts)."""
    lines: list[str] = []
    for w in wires:
        wid = str(w.get("watch_id") or "").strip()
        rt = str(w.get("record_type") or "").strip()
        rid = str(w.get("record_id") or "").strip()
        label = str(w.get("label") or "").strip()
        url = str(w.get("url") or "").strip()
        path = str(w.get("path") or "").strip()
        head = label or f"{rt} {rid}".strip() or wid or "item"
        lines.append(
            f"- watch_id={wid!r} record_type={rt!r} record_id={rid!r} "
            f"label={head!r} url={url!r} path={path!r}"
        )
    return "\n".join(lines) if lines else "(no watch rows)"


def _inbox_review_static_message_from_wires(wires: list[dict[str, Any]]) -> str:
    parts = [
        "Please complete the following **Inbox** review(s). "
        "The assistant continues automatically when each item is resolved:",
        "",
    ]
    for w in wires:
        label = str(w.get("label") or "").strip()
        rt = str(w.get("record_type") or "").strip()
        rid = str(w.get("record_id") or "").strip()
        head = label or f"{rt} · {rid}".strip() or "Inbox item"
        url = str(w.get("url") or "").strip()
        path = str(w.get("path") or "").strip()
        link = url or path or "Open **Inbox** in the app to complete this review."
        parts.append(f"- **{head}** — {link}")
    return "\n".join(parts)


def _stream_inbox_review_summary_for_ui(
    provider: Any,
    model: str,
    policy: AgentPolicy,
    oa_messages: list[dict[str, Any]],
    start_round: int,
    run_id: str,
    wires: list[dict[str, Any]],
    *,
    lm_backend: str,
    reasoning: ReasoningConfig,
    max_tool_output_chars: int,
    max_cli_line_chars: int,
) -> Iterator[dict[str, Any]]:
    """Stream assistant guidance before ``awaiting_inbox_review``; mutates ``oa_messages``."""
    mode = policy.inbox_review_summary_mode
    if mode == "none":
        return

    watch_block = _format_inbox_watches_block(wires)
    user_content = (
        f"{policy.inbox_review_summary_user_message}\n\n"
        f"### Detected Inbox review items\n{watch_block}"
    )

    if mode == "static":
        text = _inbox_review_static_message_from_wires(wires)
        oa_messages.append({"role": "user", "content": user_content})
        yield {
            "type": "phase",
            "round": start_round + 1,
            "phase": "inbox_review_summary",
        }
        yield {"type": "assistant_delta", "text": text}
        yield {"type": "assistant_done", "finish_reason": "stop"}
        oa_messages.append({"role": "assistant", "content": text})
        return

    if mode != "llm_stream":
        yield {
            "type": "error",
            "detail": (
                f"invalid inbox_review_summary_mode={mode!r} (expected llm_stream, static, or none)"
            ),
        }
        return

    oa_messages.append({"role": "user", "content": user_content})
    sc_inbox = policy.sandbox.with_env_overrides() if policy.sandbox is not None else None
    if sc_inbox is not None and sc_inbox.enabled and sc_inbox.terminal_only_dispatch:
        read_allowlist = policy.effective_allowlist()
    else:
        read_allowlist = frozenset(policy.allowlist_read | BUILTIN_AGENT_TOOL_NAMES)
    read_tools = openai_tool_specs(read_allowlist)

    from llm_markdown.agent_stream import (
        AgentContentDelta,
        AgentMessageFinish,
        AgentReasoningDelta,
        AgentSegmentStart,
        AgentToolCallDelta,
    )

    sub_start = start_round
    for sub_i in range(_INBOX_REVIEW_SUMMARY_MAX_ROUNDS):
        phase_round = sub_start + sub_i + 1
        yield {"type": "phase", "round": phase_round, "phase": "inbox_review_summary"}

        parts: dict[int, dict[str, str]] = {}
        assistant_text = ""
        finish_reason: str | None = None
        last_usage: dict[str, Any] | None = None

        try:
            for ev in _iter_stream_agent_turn_with_engine_retries(
                provider,
                lm_backend,
                oa_messages,
                model=model,
                tools=read_tools,
                tool_choice="auto",
                max_tokens=_AGENT_SUMMARY_MAX_TOKENS,
                reasoning=reasoning,
                **_anthropic_stream_turn_extras(lm_backend, reasoning),
            ):
                pw = _provider_wait_wire(ev)
                if pw is not None:
                    yield pw
                    continue
                if isinstance(ev, AgentSegmentStart):
                    yield {"type": "segment_start", "segment": ev.segment}
                elif isinstance(ev, AgentContentDelta):
                    assistant_text += ev.text
                    yield {"type": "assistant_delta", "text": ev.text}
                elif isinstance(ev, AgentReasoningDelta):
                    yield {"type": "reasoning_delta", "text": ev.text}
                elif isinstance(ev, AgentToolCallDelta):
                    idx = int(ev.index)
                    if idx not in parts:
                        parts[idx] = {"id": "", "name": "", "arguments": ""}
                    if ev.tool_call_id:
                        parts[idx]["id"] = ev.tool_call_id
                    if ev.name:
                        parts[idx]["name"] += ev.name
                    if ev.arguments:
                        parts[idx]["arguments"] += ev.arguments
                elif isinstance(ev, AgentMessageFinish):
                    finish_reason = ev.finish_reason
                    last_usage = ev.usage
        except _AgentStreamTurnExhaustedError:
            logger.warning(
                "inbox review summary model call failed after engine stream retries, "
                "using static fallback",
            )
            fb = _inbox_review_static_message_from_wires(wires)
            yield {"type": "assistant_delta", "text": fb}
            yield {"type": "assistant_done", "finish_reason": "stop"}
            oa_messages.append({"role": "assistant", "content": fb})
            return
        except Exception as exc:
            logger.warning("inbox review summary model call failed: %s", exc)
            fb = _inbox_review_static_message_from_wires(wires)
            yield {"type": "assistant_delta", "text": fb}
            yield {"type": "assistant_done", "finish_reason": "stop"}
            oa_messages.append({"role": "assistant", "content": fb})
            return

        if finish_reason != "tool_calls":
            final_text = assistant_text.strip() or _inbox_review_static_message_from_wires(
                wires,
            )
            if not assistant_text.strip():
                yield {"type": "assistant_delta", "text": final_text}
            done_ev_stop: dict[str, Any] = {
                "type": "assistant_done",
                "finish_reason": finish_reason or "stop",
            }
            if last_usage:
                done_ev_stop["usage"] = last_usage
            yield done_ev_stop
            oa_messages.append({"role": "assistant", "content": final_text})
            return

        done_ev_tc: dict[str, Any] = {
            "type": "assistant_done",
            "finish_reason": finish_reason,
        }
        if last_usage:
            done_ev_tc["usage"] = last_usage
        yield done_ev_tc

        if not parts:
            fb = _inbox_review_static_message_from_wires(wires)
            yield {"type": "assistant_delta", "text": fb}
            yield {"type": "assistant_done", "finish_reason": "stop"}
            oa_messages.append({"role": "assistant", "content": fb})
            return

        yield {
            "type": "phase",
            "round": phase_round,
            "phase": "inbox_review_summary_tools",
        }
        sorted_idx = sorted(parts.keys())
        tool_calls_payload: list[dict[str, Any]] = []
        for idx in sorted_idx:
            tc = parts[idx]
            tid = tc["id"] or f"call_{idx}"
            name = tc["name"]
            args_raw = tc["arguments"] or "{}"
            args_wire, _ = split_agent_tool_display_metadata(args_raw)
            tool_calls_payload.append(
                {
                    "id": tid,
                    "type": "function",
                    "function": {"name": name, "arguments": args_wire},
                },
            )
        oa_messages.append(
            {
                "role": "assistant",
                "content": assistant_text or None,
                "tool_calls": tool_calls_payload,
            },
        )
        for idx in sorted_idx:
            tc = parts[idx]
            name = tc["name"]
            args_raw = tc["arguments"] or "{}"
            args_wire, display_title = split_agent_tool_display_metadata(args_raw)
            tid = tc["id"] or f"call_{idx}"
            cap = _cli_line_cap_for_tool(name, max_cli_line_chars)
            cli = format_cli_line(name, args_wire, max_cli_line_chars=cap)
            arg_cap = _args_wire_emit_cap_chars(name)
            tc_ev: dict[str, Any] = {
                "type": "tool_call",
                "name": name,
                "arguments": args_wire[:arg_cap],
                "cli_line": cli,
                "tool_call_id": tid,
            }
            if display_title:
                tc_ev["display_title"] = display_title
            note = policy.rationale_for(name)
            if note:
                tc_ev["internal_rationale"] = note
            yield tc_ev
            tex = execute_tool(
                name,
                args_wire,
                read_allowlist,
                max_tool_output_chars=max_tool_output_chars,
                run_id=run_id,
                tool_call_id=tid,
            )
            tr_out: dict[str, Any] = {
                "type": "tool_result",
                "name": name,
                "summary": tex.summary,
                "tool_call_id": tid,
                "ok": tex.ok,
                "status_code": tex.status_code,
            }
            if tex.parsed_data is not None:
                tr_out["data"] = tex.parsed_data
            yield tr_out
            oa_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tid,
                    "content": format_tool_result_for_model(name, tex.raw_json),
                },
            )

    fb = _inbox_review_static_message_from_wires(wires)
    yield {"type": "assistant_delta", "text": fb}
    yield {"type": "assistant_done", "finish_reason": "stop"}
    oa_messages.append({"role": "assistant", "content": fb})


def _yield_awaiting_inbox_review_barrier(
    *,
    provider: Any,
    model: str,
    policy: AgentPolicy,
    oa_messages: list[dict[str, Any]],
    start_round: int,
    rid: str,
    wires: list[dict[str, Any]],
    baseline_ids: list[str],
    lm_backend: str,
    reasoning: ReasoningConfig,
    max_tool_output_chars: int,
    max_cli_line_chars: int,
    chained_from_inbox_resume: bool = False,
    agent_chat_mode: str = "instant",
) -> Iterator[dict[str, Any]]:
    """Persist run, emit ``awaiting_inbox_review``, debug + log.

    Used from mutation resume and chained inbox-resume paths.
    """
    inbox_ttl = max(60, int(policy.inbox_review_state_ttl_sec))
    if policy.inbox_review_summary_mode != "none":
        yield from _stream_inbox_review_summary_for_ui(
            provider,
            model,
            policy,
            oa_messages,
            start_round,
            rid,
            wires,
            lm_backend=lm_backend,
            reasoning=reasoning,
            max_tool_output_chars=max_tool_output_chars,
            max_cli_line_chars=max_cli_line_chars,
        )
    _save_agent_run_with_ttl_merge_attachments(
        rid,
        {
            "oa_messages": oa_messages,
            "model": model,
            "llm_backend": lm_backend,
            "rounds": start_round,
            "open_inbox_watches": wires,
            "inbox_pending_baseline_ids": baseline_ids,
            "agent_chat_mode": agent_chat_mode,
        },
        inbox_ttl,
    )
    yield {"type": "awaiting_inbox_review", "run_id": rid, "watches": wires}
    dbg: dict[str, Any] = {
        "kind": "awaiting_inbox_review",
        "run_id": rid,
        "n_watches": len(wires),
    }
    if chained_from_inbox_resume:
        dbg["after_inbox_resume"] = True
    _agent_stream_debug_append(dbg)
    if chained_from_inbox_resume:
        logger.debug(
            "agent_chat awaiting_inbox_review (chained) run_id=%s watches=%d",
            rid,
            len(wires),
        )
    else:
        logger.debug(
            "agent_chat awaiting_inbox_review run_id=%s watches=%d",
            rid,
            len(wires),
        )


def _replace_tool_message_content(
    oa_messages: list[dict[str, Any]],
    tool_call_id: str,
    content: str,
) -> None:
    for msg in oa_messages:
        if msg.get("role") == "tool" and msg.get("tool_call_id") == tool_call_id:
            msg["content"] = content
            return
    msg = f"no tool message for tool_call_id={tool_call_id}"
    raise ValueError(msg)


def _parse_and_validate_plan_clarification_questions(
    arguments_json: str,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    from hof.agent.plan_types import parse_plan_clarification_questions

    return parse_plan_clarification_questions(arguments_json)


def _parse_and_validate_plan_proposal(
    arguments_json: str,
) -> tuple[dict[str, Any] | None, str | None]:
    from hof.agent.plan_types import parse_plan_proposal

    return parse_plan_proposal(arguments_json)


def _validate_clarification_answers(
    questions: list[dict[str, Any]],
    answers: list[Any],
) -> tuple[dict[str, list[str]] | None, dict[str, str], str | None]:
    from hof.agent.plan_types import validate_plan_clarification_answers

    return validate_plan_clarification_answers(questions, answers)


def _clarification_answer_summary_for_model(
    questions: list[dict[str, Any]],
    selections: dict[str, list[str]],
    other_text_by_qid: dict[str, str],
) -> str:
    lines: list[str] = []
    for q in questions:
        qid = str(q["id"])
        labels_by_id = {o["id"]: o["label"] for o in q["options"]}
        chosen = selections.get(qid, [])
        pretty = ", ".join(labels_by_id[oid] for oid in chosen)
        extra = other_text_by_qid.get(qid, "").strip()
        if extra:
            pretty = f"{pretty}\nOther: {extra}"
        lines.append(f"{q['prompt']}\nSelected: {pretty}")
    return "User clarification answers:\n" + "\n\n".join(lines)


def _run_agent_llm_tool_loop(
    provider: Any,
    model: str,
    policy: AgentPolicy,
    allowlist: frozenset[str],
    tools: list[dict[str, Any]],
    oa_messages: list[dict[str, Any]],
    start_round: int,
    run_id: str,
    *,
    lm_backend: str,
    reasoning: ReasoningConfig,
    max_rounds: int,
    max_tool_output_chars: int,
    max_cli_line_chars: int,
    final_extras: dict[str, Any] | None = None,
    agent_chat_mode: str = "instant",
    plan_resume_final_extras: dict[str, Any] | None = None,
    discover_explore_allowlist: frozenset[str] | None = None,
    discover_explore_tools: list[dict[str, Any]] | None = None,
    discover_post_clarification_resume: bool = False,
    chat_attachments: list[dict[str, str]] | None = None,
) -> Iterator[dict[str, Any]]:
    """Run model ↔ tools until final reply, error, or halt for mutation confirmation."""
    rounds = start_round
    mutation_allowlist = policy.allowlist_mutation
    _discover_text_retried = False
    _discover_explored = False
    _clarification_retries = 0
    _max_clarification_retries = 3

    # Ensure the agent run exists in state so sandbox curl can defer mutations via
    # ``defer_mutation_if_terminal_agent_http`` (which calls ``load_agent_run``).
    # Critical after resume paths that ``delete_agent_run`` before re-entering this loop.
    _loop_payload: dict[str, Any] = {
        "oa_messages": oa_messages,
        "model": model,
        "llm_backend": lm_backend,
        "rounds": rounds,
        "agent_chat_mode": agent_chat_mode,
    }
    if chat_attachments is not None:
        _loop_payload["chat_attachments"] = chat_attachments
    _save_agent_run_merge_attachments(run_id, _loop_payload)

    try:
        while rounds < max_rounds:
            rounds += 1
            _phase_model: dict[str, Any] = {
                "type": "phase",
                "round": rounds,
                "phase": "model",
            }
            if agent_chat_mode == "plan_discover":
                # Fresh chat: explore → clarify. After ``agent_resume_plan_clarification`` the
                # loop is recreated with ``_discover_explored`` false; without this flag every
                # ``phase: model`` would incorrectly emit ``discover_phase: explore`` (UI
                # stuck on explore semantics). ``propose`` = drafting structured plan / tools.
                if discover_post_clarification_resume:
                    _phase_model["discover_phase"] = "propose"
                else:
                    _phase_model["discover_phase"] = (
                        "explore" if not _discover_explored else "clarify"
                    )
                logger.info(
                    "agent_chat ndjson_phase run_id=%s round=%d phase=model discover_phase=%s",
                    run_id,
                    rounds,
                    _phase_model["discover_phase"],
                )
            yield _phase_model
            # Explicit plan-discover subphase (additive; mirrors ``discover_phase`` on ``phase``).
            if (
                agent_chat_mode == "plan_discover"
                and _phase_model.get("phase") == "model"
                and "discover_phase" in _phase_model
            ):
                yield {
                    "type": "plan_discover",
                    "subphase": _phase_model["discover_phase"],
                    "round": rounds,
                    "ts_ms": int(time.time() * 1000),
                }

            from llm_markdown.agent_stream import (
                AgentContentDelta,
                AgentMessageFinish,
                AgentReasoningDelta,
                AgentSegmentStart,
                AgentToolCallDelta,
            )

            parts: dict[int, dict[str, str]] = {}
            assistant_text = ""
            finish_reason: str | None = None
            last_usage: dict[str, Any] | None = None
            n_content_delta = 0
            n_reasoning_delta = 0
            n_segment_start_reasoning = 0
            n_segment_start_content = 0
            reasoning_chars = 0
            trace_parts: list[str] = []

            _in_discover_explore = (
                agent_chat_mode == "plan_discover"
                and discover_explore_allowlist is not None
                and discover_explore_tools is not None
                and not _discover_explored
            )
            active_allowlist = discover_explore_allowlist if _in_discover_explore else allowlist
            active_tools = discover_explore_tools if _in_discover_explore else tools
            st_tools = active_tools if len(active_tools) > 0 else None
            if st_tools is not None and agent_chat_mode == "plan_discover":
                st_tool_choice: str | dict[str, str] | None = "auto"
            elif st_tools is not None:
                st_tool_choice = "auto"
            else:
                st_tool_choice = None
            for ev in _iter_stream_agent_turn_with_engine_retries(
                provider,
                lm_backend,
                oa_messages,
                model=model,
                tools=st_tools,
                tool_choice=st_tool_choice,
                max_tokens=_resolve_agent_max_completion_tokens(),
                reasoning=reasoning,
                **_anthropic_stream_turn_extras(lm_backend, reasoning),
            ):
                pw = _provider_wait_wire(ev)
                if pw is not None:
                    yield pw
                    continue
                if isinstance(ev, AgentSegmentStart):
                    if ev.segment == "reasoning":
                        n_segment_start_reasoning += 1
                        trace_parts.append("Sr")
                    elif ev.segment == "content":
                        n_segment_start_content += 1
                        trace_parts.append("Sc")
                    yield {"type": "segment_start", "segment": ev.segment}
                elif isinstance(ev, AgentContentDelta):
                    assistant_text += ev.text
                    n_content_delta += 1
                    trace_parts.append("c")
                    yield {"type": "assistant_delta", "text": ev.text}
                elif isinstance(ev, AgentReasoningDelta):
                    n_reasoning_delta += 1
                    reasoning_chars += len(ev.text or "")
                    trace_parts.append("r")
                    yield {"type": "reasoning_delta", "text": ev.text}
                elif isinstance(ev, AgentToolCallDelta):
                    idx = int(ev.index)
                    if idx not in parts:
                        parts[idx] = {"id": "", "name": "", "arguments": ""}
                    if ev.tool_call_id:
                        parts[idx]["id"] = ev.tool_call_id
                    if ev.name:
                        parts[idx]["name"] += ev.name
                    if ev.arguments:
                        parts[idx]["arguments"] += ev.arguments
                    trace_parts.append("t")
                elif isinstance(ev, AgentMessageFinish):
                    finish_reason = ev.finish_reason
                    last_usage = ev.usage
                    trace_parts.append("f")

            done_ev: dict[str, Any] = {
                "type": "assistant_done",
                "finish_reason": finish_reason,
            }
            if last_usage:
                done_ev["usage"] = last_usage
            yield done_ev
            if os.environ.get("HOF_AGENT_UI_TRACE", "").strip().lower() in (
                "1",
                "true",
                "yes",
                "on",
            ):
                _dp_ui = (
                    str(_phase_model.get("discover_phase", ""))
                    if agent_chat_mode == "plan_discover"
                    else "-"
                )
                logger.info(
                    "agent_chat ui_trace run_id=%s round=%s discover_phase=%s "
                    "finish_reason=%s content_deltas=%s reasoning_deltas=%s "
                    "reasoning_chars=%s assistant_text_chars=%s "
                    "segment_start_reasoning=%s segment_start_content=%s",
                    run_id,
                    rounds,
                    _dp_ui,
                    finish_reason,
                    n_content_delta,
                    n_reasoning_delta,
                    reasoning_chars,
                    len(assistant_text),
                    n_segment_start_reasoning,
                    n_segment_start_content,
                )
            trace_collapsed = _collapse_agent_round_trace(trace_parts)
            _agent_stream_debug_append(
                {
                    "kind": "model_round",
                    "run_id": run_id,
                    "model": model,
                    "round": rounds,
                    "finish_reason": finish_reason,
                    "content_deltas": n_content_delta,
                    "reasoning_deltas": n_reasoning_delta,
                    "reasoning_chars": reasoning_chars,
                    "segment_start_reasoning": n_segment_start_reasoning,
                    "segment_start_content": n_segment_start_content,
                    "assistant_text_chars": len(assistant_text),
                    "tool_slots": len(parts),
                    "event_trace": trace_collapsed,
                },
            )

            if finish_reason == "tool_calls":
                if not parts:
                    logger.warning(
                        "agent_chat tool_calls_missing_deltas run_id=%s round=%d",
                        run_id,
                        rounds,
                    )
                    yield {
                        "type": "error",
                        "detail": "model returned tool_calls but no tool deltas",
                    }
                    return
                yield {"type": "phase", "round": rounds, "phase": "tools"}
                sorted_idx = sorted(parts.keys())
                browse_only_async = (
                    _browser_async_enabled(policy)
                    and len(sorted_idx) == 1
                    and str(parts[sorted_idx[0]].get("name") or "") == HOF_BUILTIN_BROWSE_WEB
                )
                if agent_chat_mode == "plan_discover":
                    _plan_terminal_tools = {
                        _HOF_BUILTIN_PRESENT_PLAN,
                        _HOF_BUILTIN_PRESENT_PLAN_CLARIFICATION,
                    }
                    terminal_idxs = [
                        i for i in sorted_idx if parts[i].get("name") in _plan_terminal_tools
                    ]
                    if len(terminal_idxs) > 1:
                        yield {
                            "type": "error",
                            "detail": ("at most one plan/clarification tool per round"),
                        }
                        return
                    if len(terminal_idxs) == 1:
                        tix = terminal_idxs[0]
                        tname = parts[tix].get("name")
                        if tix != sorted_idx[-1]:
                            yield {
                                "type": "error",
                                "detail": (f"{tname} must be the last tool call in the round"),
                            }
                            return
                        if any(parts[j].get("name") in mutation_allowlist for j in sorted_idx):
                            yield {
                                "type": "error",
                                "detail": (
                                    f"cannot combine {tname} with mutation tools in the same round"
                                ),
                            }
                            return
                tool_calls_payload: list[dict[str, Any]] = []
                for idx in sorted_idx:
                    tc = parts[idx]
                    tid = tc["id"] or f"call_{idx}"
                    name = tc["name"]
                    args_raw = tc["arguments"] or "{}"
                    args_wire, _ = split_agent_tool_display_metadata(args_raw)
                    tool_calls_payload.append(
                        {
                            "id": tid,
                            "type": "function",
                            "function": {"name": name, "arguments": args_wire},
                        },
                    )
                oa_messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_text or None,
                        "tool_calls": tool_calls_payload,
                    },
                )
                pending_ids: list[str] = []
                plan_clarify_halt: str | None = None
                plan_clarify_questions: list[dict[str, Any]] | None = None
                plan_clarify_tool_call_id: str | None = None
                plan_proposal_halt: dict[str, Any] | None = None
                for idx in sorted_idx:
                    tc = parts[idx]
                    name = tc["name"]
                    args_raw = tc["arguments"] or "{}"
                    args_wire, display_title = split_agent_tool_display_metadata(args_raw)
                    tid = tc["id"] or f"call_{idx}"
                    cap = _cli_line_cap_for_tool(name, max_cli_line_chars)
                    cli = format_cli_line(name, args_wire, max_cli_line_chars=cap)
                    arg_cap = _args_wire_emit_cap_chars(name)
                    tc_ev: dict[str, Any] = {
                        "type": "tool_call",
                        "name": name,
                        "arguments": args_wire[:arg_cap],
                        "cli_line": cli,
                        "tool_call_id": tid,
                    }
                    if display_title:
                        tc_ev["display_title"] = display_title
                    note = policy.rationale_for(name)
                    if note:
                        tc_ev["internal_rationale"] = note
                    if name in BUILTIN_AGENT_TOOL_NAMES:
                        tc_ev["internal"] = True
                    yield tc_ev
                    logger.info(
                        "agent_chat tool_call run_id=%s round=%d name=%s tool_call_id=%s "
                        "args_chars=%d mutation=%s",
                        run_id,
                        rounds,
                        name,
                        tid,
                        len(args_wire),
                        "yes" if name in mutation_allowlist else "no",
                    )
                    _agent_stream_debug_append(
                        {
                            "kind": "tool_call",
                            "run_id": run_id,
                            "round": rounds,
                            "name": name,
                            "arguments_chars": len(args_wire),
                        },
                    )
                    if (
                        name == _HOF_BUILTIN_PRESENT_PLAN_CLARIFICATION
                        and agent_chat_mode == "plan_discover"
                    ):
                        logger.info(
                            "agent_chat plan_clarification_validating run_id=%s args_wire_chars=%d",
                            run_id,
                            len(args_wire),
                        )
                        qs, verr = _parse_and_validate_plan_clarification_questions(args_wire)
                        if verr is not None:
                            logger.warning(
                                "agent_chat plan_clarification_validation_error "
                                "run_id=%s error=%s args_wire_start=%s",
                                run_id,
                                verr,
                                args_wire[:300],
                            )
                            _clarification_retries += 1
                            if _clarification_retries > _max_clarification_retries:
                                yield {
                                    "type": "error",
                                    "detail": (
                                        "plan clarification validation failed after "
                                        f"{_max_clarification_retries} retries: {verr}"
                                    ),
                                }
                                return
                            oa_messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tid,
                                    "content": json.dumps(
                                        {
                                            "error": "validation_failed",
                                            "message": verr,
                                            "hint": (
                                                "Retry with a corrected questions array. "
                                                "Each question requires: id (string), "
                                                "prompt (string), options (list of 2–5 "
                                                "objects each with id and label strings). "
                                                "Never omit options."
                                            ),
                                        }
                                    ),
                                }
                            )
                            logger.info(
                                "agent_chat plan_clarification_retry run_id=%s round=%d "
                                "retry=%d/%d",
                                run_id,
                                rounds,
                                _clarification_retries,
                                _max_clarification_retries,
                            )
                            break  # clarification is always last; outer loop retries
                        cid = str(uuid.uuid4())
                        save_pending(
                            cid,
                            {
                                "run_id": run_id,
                                "kind": "plan_clarification",
                                "tool_call_id": tid,
                                "questions": qs,
                            },
                        )
                        ph_obj: dict[str, Any] = {
                            "awaiting_plan_clarification": True,
                            "clarification_id": cid,
                        }
                        placeholder = json.dumps(ph_obj)
                        tr_cl: dict[str, Any] = {
                            "type": "tool_result",
                            "name": name,
                            "summary": (
                                "Awaiting clarification answers "
                                "(agent_resume_plan_clarification stream)."
                            ),
                            "status_code": 202,
                            "tool_call_id": tid,
                            "data": {"questions": qs, "clarification_id": cid},
                            "internal": True,
                        }
                        yield tr_cl
                        oa_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tid,
                                "content": placeholder,
                            },
                        )
                        plan_clarify_halt = cid
                        plan_clarify_questions = qs
                        plan_clarify_tool_call_id = tid
                        logger.info(
                            "agent_chat plan_clarification_pending run_id=%s round=%d "
                            "clarification_id=%s tool_call_id=%s",
                            run_id,
                            rounds,
                            cid,
                            tid,
                        )
                    elif name == _HOF_BUILTIN_PRESENT_PLAN and agent_chat_mode == "plan_discover":
                        logger.info(
                            "agent_chat plan_proposal_validating run_id=%s args_wire_chars=%d",
                            run_id,
                            len(args_wire),
                        )
                        proposal, verr = _parse_and_validate_plan_proposal(args_wire)
                        if verr is not None:
                            logger.warning(
                                "agent_chat plan_proposal_validation_error "
                                "run_id=%s error=%s args_wire_start=%s",
                                run_id,
                                verr,
                                args_wire[:300],
                            )
                            yield {"type": "error", "detail": verr}
                            return
                        from hof.agent.plan_types import (
                            PlanProposal,
                            plan_proposal_to_markdown,
                        )

                        md = plan_proposal_to_markdown(
                            PlanProposal.model_validate(proposal),
                        )
                        tr_plan: dict[str, Any] = {
                            "type": "tool_result",
                            "name": name,
                            "summary": "Plan presented to user for review.",
                            "status_code": 200,
                            "tool_call_id": tid,
                            "data": {"proposal": proposal},
                            "internal": True,
                        }
                        yield tr_plan
                        oa_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tid,
                                "content": json.dumps(
                                    {"status": "plan_presented"},
                                ),
                            },
                        )
                        plan_proposal_halt = {
                            "markdown": md,
                            "structured_plan": proposal,
                        }
                        logger.info(
                            "agent_chat plan_proposal_accepted run_id=%s round=%d steps=%d",
                            run_id,
                            rounds,
                            len(proposal.get("steps", [])),
                        )
                    elif name in mutation_allowlist:
                        pid = str(uuid.uuid4())
                        preview = _mutation_preview_payload(name, args_wire, policy)
                        save_pending(
                            pid,
                            {
                                "run_id": run_id,
                                "tool_call_id": tid,
                                "function_name": name,
                                "arguments_json": args_wire,
                            },
                        )
                        ph_obj: dict[str, Any] = {
                            "pending_confirmation": True,
                            "pending_id": pid,
                            "function": name,
                        }
                        if preview is not None:
                            ph_obj["preview"] = preview
                        placeholder = json.dumps(ph_obj)
                        effective_cli = cli
                        if isinstance(preview, dict) and preview.get("cli_line"):
                            effective_cli = str(preview["cli_line"])
                        mp_ev: dict[str, Any] = {
                            "type": "mutation_pending",
                            "run_id": run_id,
                            "pending_id": pid,
                            "name": name,
                            "arguments": args_wire[:12000],
                            "cli_line": effective_cli,
                            "tool_call_id": tid,
                        }
                        if preview is not None:
                            mp_ev["preview"] = preview
                        yield mp_ev
                        tr_pending: dict[str, Any] = {
                            "type": "tool_result",
                            "name": name,
                            "summary": (
                                "Awaiting your confirmation "
                                "(Assistant panel or agent_resume_mutations)."
                            ),
                            "pending_confirmation": True,
                            "status_code": 202,
                            "tool_call_id": tid,
                        }
                        if preview is not None:
                            tr_pending["data"] = preview
                        yield tr_pending
                        oa_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tid,
                                "content": placeholder,
                            },
                        )
                        pending_ids.append(pid)
                        logger.info(
                            "agent_chat mutation_pending run_id=%s round=%d name=%s "
                            "pending_id=%s tool_call_id=%s (client should show 202 / confirm)",
                            run_id,
                            rounds,
                            name,
                            pid,
                            tid,
                        )
                    elif name == HOF_BUILTIN_BROWSE_WEB:
                        if browse_only_async:
                            yield from _stream_hof_browser_tool_async_barrier(
                                policy=policy,
                                provider=provider,
                                args_wire=args_wire,
                                run_id=run_id,
                                tid=tid,
                                oa_messages=oa_messages,
                                rounds=rounds,
                                model=model,
                                lm_backend=lm_backend,
                                reasoning=reasoning,
                                max_tool_output_chars=max_tool_output_chars,
                                max_cli_line_chars=max_cli_line_chars,
                                agent_chat_mode=agent_chat_mode,
                                chat_attachments=chat_attachments,
                            )
                            logger.info(
                                "agent_chat browser_async_barrier "
                                "run_id=%s round=%d tool_call_id=%s",
                                run_id,
                                rounds,
                                tid,
                            )
                            return
                        yield from _stream_hof_browser_tool(
                            policy=policy,
                            args_wire=args_wire,
                            run_id=run_id,
                            tid=tid,
                            max_tool_output_chars=max_tool_output_chars,
                            oa_messages=oa_messages,
                        )
                        logger.info(
                            "agent_chat browser_tool_done run_id=%s round=%d tool_call_id=%s",
                            run_id,
                            rounds,
                            tid,
                        )
                    else:
                        tex = execute_tool(
                            name,
                            args_wire,
                            active_allowlist,
                            max_tool_output_chars=max_tool_output_chars,
                            run_id=run_id,
                            tool_call_id=tid,
                        )
                        if name == HOF_BUILTIN_TERMINAL_EXEC:
                            coerced = _try_coerce_terminal_exec_mutation_events(
                                out_json=tex.raw_json,
                                run_id=run_id,
                                tid=tid,
                                mutation_allowlist=mutation_allowlist,
                                max_cli_line_chars=max_cli_line_chars,
                            )
                            if coerced is not None:
                                t_ev, oa_tool, pid_c = coerced
                                yield from t_ev
                                oa_messages.append(oa_tool)
                                pending_ids.append(pid_c)
                                logger.info(
                                    "agent_chat terminal_exec coerced mutation_pending "
                                    "run_id=%s pending_id=%s tool_call_id=%s",
                                    run_id,
                                    pid_c,
                                    tid,
                                )
                                continue
                        logger.info(
                            "agent_chat tool_result emit run_id=%s round=%d name=%s "
                            "tool_call_id=%s ok=%s status_code=%s summary_chars=%d",
                            run_id,
                            rounds,
                            name,
                            tid,
                            tex.ok,
                            tex.status_code,
                            len(tex.summary or ""),
                        )
                        tr_out: dict[str, Any] = {
                            "type": "tool_result",
                            "name": name,
                            "summary": tex.summary,
                            "tool_call_id": tid,
                            "ok": tex.ok,
                            "status_code": tex.status_code,
                        }
                        if tex.parsed_data is not None:
                            tr_out["data"] = tex.parsed_data
                        if name in BUILTIN_AGENT_TOOL_NAMES:
                            tr_out["internal"] = True
                        yield tr_out
                        oa_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tid,
                                "content": format_tool_result_for_model(name, tex.raw_json),
                            },
                        )
                        if (
                            name == _HOF_BUILTIN_UPDATE_PLAN_TODO_STATE
                            and agent_chat_mode == "plan_execute"
                        ):
                            pdata_todo = tex.parsed_data
                            if isinstance(pdata_todo, dict):
                                di = pdata_todo.get("done_indices")
                                if isinstance(di, list) and di:
                                    idxs: list[int] = []
                                    for x in di:
                                        try:
                                            idxs.append(int(x))
                                        except (TypeError, ValueError):
                                            continue
                                    if idxs:
                                        yield {
                                            "type": "plan_todo_update",
                                            "done_indices": idxs,
                                        }
                if plan_proposal_halt is not None:
                    delete_agent_run(run_id)
                    plan_md = plan_proposal_halt["markdown"]
                    plan_run_id = str(uuid.uuid4())
                    plan_final: dict[str, Any] = {
                        "type": "final",
                        "reply": plan_md,
                        "tool_rounds_used": rounds,
                        "model": model,
                        "mode": "plan",
                        "plan_run_id": plan_run_id,
                        "structured_plan": plan_proposal_halt["structured_plan"],
                        # Clients must not treat assistant_delta as plan body during discovery:
                        # markdown is derived server-side from validated tool args, not streamed.
                        "plan_text_source": "structured_tool",
                    }
                    if final_extras:
                        for k, v in final_extras.items():
                            if k not in plan_final:
                                plan_final[k] = v
                    yield plan_final
                    logger.info(
                        "agent_chat plan_proposal_final run_id=%s round=%d reply_chars=%d",
                        run_id,
                        rounds,
                        len(plan_md),
                    )
                    return
                if plan_clarify_halt is not None:
                    store_extras = (
                        plan_resume_final_extras if plan_resume_final_extras is not None else {}
                    )
                    _pc_payload: dict[str, Any] = {
                        "oa_messages": oa_messages,
                        "model": model,
                        "llm_backend": lm_backend,
                        "rounds": rounds,
                        "open_plan_clarification_id": plan_clarify_halt,
                        "agent_chat_mode": "plan_discover",
                        "plan_resume_final_extras": store_extras,
                    }
                    if chat_attachments is not None:
                        _pc_payload["chat_attachments"] = chat_attachments
                    _save_agent_run_merge_attachments(run_id, _pc_payload)
                    yield {
                        "type": "awaiting_plan_clarification",
                        "run_id": run_id,
                        "clarification_id": plan_clarify_halt,
                        "tool_call_id": plan_clarify_tool_call_id,
                        "questions": plan_clarify_questions,
                    }
                    logger.info(
                        "agent_chat awaiting_plan_clarification run_id=%s round=%d "
                        "clarification_id=%s (stream pauses until resume)",
                        run_id,
                        rounds,
                        plan_clarify_halt,
                    )
                    return
                if pending_ids:
                    mode = policy.confirmation_summary_mode
                    if mode == "llm_stream":
                        yield from _stream_confirmation_summary_for_ui(
                            provider,
                            model,
                            oa_messages,
                            rounds,
                            policy.confirmation_summary_user_message,
                            lm_backend=lm_backend,
                            reasoning=reasoning,
                        )
                    elif mode == "static":
                        yield from _yield_confirmation_summary_static(
                            rounds,
                            _CONFIRMATION_SUMMARY_STATIC_FALLBACK,
                        )
                    elif mode != "none":
                        yield {
                            "type": "error",
                            "detail": (
                                f"invalid confirmation_summary_mode={mode!r} "
                                "(expected llm_stream, static, or none)"
                            ),
                        }
                        return
                    _pend_payload: dict[str, Any] = {
                        "oa_messages": oa_messages,
                        "model": model,
                        "llm_backend": lm_backend,
                        "rounds": rounds,
                        "open_pending_ids": pending_ids,
                        "agent_chat_mode": agent_chat_mode,
                    }
                    if chat_attachments is not None:
                        _pend_payload["chat_attachments"] = chat_attachments
                    _save_agent_run_merge_attachments(run_id, _pend_payload)
                    yield {
                        "type": "awaiting_confirmation",
                        "run_id": run_id,
                        "pending_ids": pending_ids,
                    }
                    logger.info(
                        "agent_chat awaiting_confirmation run_id=%s round=%d "
                        "pending_count=%d pending_ids=%s (stream pauses until resume)",
                        run_id,
                        rounds,
                        len(pending_ids),
                        pending_ids,
                    )
                    return
                # Explore phase often ends with read-only tool calls (no assistant prose-only
                # round). In that case ``discover_explore_complete`` below never runs because
                # ``finish_reason == tool_calls`` skips it. Mark explore done after any tool
                # round that did not yet call plan/clarification builtins so the next
                # ``phase: model`` emits ``discover_phase: clarify`` (UI: "Generating questions").
                if (
                    agent_chat_mode == "plan_discover"
                    and discover_explore_allowlist is not None
                    and not _discover_explored
                ):
                    _plan_terminal = {
                        _HOF_BUILTIN_PRESENT_PLAN,
                        _HOF_BUILTIN_PRESENT_PLAN_CLARIFICATION,
                    }
                    tool_names = {str(parts[i].get("name") or "") for i in sorted_idx}
                    tool_names.discard("")
                    if tool_names and not (tool_names & _plan_terminal):
                        _discover_explored = True
                        logger.info(
                            "agent_chat discover_explore_complete_via_tools run_id=%s "
                            "round=%d tools=%s",
                            run_id,
                            rounds,
                            sorted(tool_names),
                        )
                continue

            text = assistant_text.strip()

            # Explore phase complete: first non-tool round ends with visible text (or empty);
            # switch to clarify-phase tools without emitting ``final``.
            if (
                agent_chat_mode == "plan_discover"
                and discover_explore_allowlist is not None
                and not _discover_explored
            ):
                _discover_explored = True
                oa_messages.append(
                    {"role": "assistant", "content": text if text else ""},
                )
                logger.info(
                    "agent_chat discover_explore_complete run_id=%s round=%d text_chars=%d",
                    run_id,
                    rounds,
                    len(text),
                )
                continue

            # Anthropic: clarify phase only — if the model keeps replying with text
            # instead of calling ``hof_builtin_present_plan_clarification``, nudge once
            # then allow final (tool_choice stays auto).
            if (
                agent_chat_mode == "plan_discover"
                and lm_backend == "anthropic"
                and not _discover_text_retried
                and text
                and _discover_explored
            ):
                _discover_text_retried = True
                oa_messages.append({"role": "assistant", "content": text})
                oa_messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Please present your questions using the "
                            "hof_builtin_present_plan_clarification tool now."
                        ),
                    },
                )
                reasoning = ReasoningConfig.off()
                logger.info(
                    "agent_chat discover_text_retry run_id=%s round=%d text_chars=%d",
                    run_id,
                    rounds,
                    len(text),
                )
                continue

            delete_agent_run(run_id)
            logger.info(
                "agent_chat final run_id=%s round=%s reply_chars=%d",
                run_id,
                rounds,
                len(text),
            )
            final_ev: dict[str, Any] = {
                "type": "final",
                "reply": text,
                "tool_rounds_used": rounds,
                "model": model,
            }
            if final_extras:
                final_ev.update(final_extras)
                if final_extras.get("mode") == "plan":
                    final_ev["plan_run_id"] = str(uuid.uuid4())
            yield final_ev
            _agent_stream_debug_append(
                {
                    "kind": "final",
                    "run_id": run_id,
                    "model": model,
                    "tool_rounds_used": rounds,
                    "reply_chars": len(text),
                },
            )
            return

        logger.warning(
            "agent_chat max_rounds_exceeded run_id=%s max_rounds=%d",
            run_id,
            max_rounds,
        )
        yield {"type": "error", "detail": f"Stopped after {max_rounds} model turns"}
    except _AgentStreamTurnExhaustedError as wrap:
        if _provider_error_is_transient_for_log(wrap.cause):
            logger.warning(
                "agent_llm_tool_loop engine_stream_retries_exhausted run_id=%s attempts=%s "
                "cause=%s",
                run_id,
                wrap.attempts,
                str(wrap.cause)[:400],
            )
        else:
            logger.exception("agent_llm_tool_loop failed after engine stream retries")
        _agent_stream_debug_append(
            {
                "kind": "stream_error",
                "run_id": run_id,
                "exc_type": type(wrap.cause).__name__,
                "detail": str(wrap.cause)[:400],
            },
        )
        yield _agent_stream_error_event(
            wrap.cause,
            engine_turn_retries_exhausted=True,
            engine_retry_max_attempts=wrap.attempts,
        )
    except Exception as exc:
        if not _looks_like_llm_provider_error(exc):
            logger.exception("agent_llm_tool_loop failed")
            _agent_stream_debug_append(
                {
                    "kind": "stream_error",
                    "run_id": run_id,
                    "exc_type": type(exc).__name__,
                    "detail": str(exc)[:400],
                },
            )
            yield _agent_stream_error_event(exc)
            return
        if _provider_error_is_transient_for_log(exc):
            logger.warning(
                "agent_llm_tool_loop provider_error_transient run_id=%s detail=%s",
                run_id,
                str(exc)[:400],
            )
        else:
            logger.exception("agent_llm_tool_loop failed")
        _agent_stream_debug_append(
            {
                "kind": "stream_error",
                "run_id": run_id,
                "exc_type": type(exc).__name__,
                "detail": str(exc)[:400],
            },
        )
        yield _agent_stream_error_event(exc)


def _run_agent_chat_stream(
    messages: list,
    attachments: list | None,
    *,
    policy: AgentPolicy,
    mode: str | None = None,
    plan_text: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield NDJSON-shaped dicts."""
    max_rounds, max_tool_output_chars, _max_model_text, max_cli_line_chars = _agent_limits()

    norm_fn = policy.normalize_attachments or default_normalize_attachments
    att_norm, att_err = norm_fn(attachments)
    if att_err:
        yield {"type": "error", "detail": att_err}
        return

    try:
        lm_backend = _resolve_agent_llm_backend()
    except ValueError as exc:
        yield {"type": "error", "detail": str(exc)}
        return

    chat_mode = _normalize_agent_chat_mode(mode)
    model = _resolve_agent_model_for_chat_mode(chat_mode)
    try:
        reasoning = _resolve_agent_reasoning_config_for_chat_mode(
            lm_backend,
            chat_mode,
            model,
        )
    except ValueError as exc:
        yield {"type": "error", "detail": str(exc)}
        return

    try:
        provider = _resolve_provider(lm_backend, model)
    except _ProviderSetupError as exc:
        yield {"type": "error", "detail": exc.detail}
        return

    run_id = str(uuid.uuid4())
    yield {"type": "run_start", "run_id": run_id, "model": model}
    _agent_stream_debug_append({"kind": "run_begin", "run_id": run_id, "model": model})
    allowlist = policy.effective_allowlist()
    tools = openai_tool_specs(allowlist)
    loop_allowlist = allowlist

    note_fn = policy.attachments_system_note or default_attachments_system_note
    att_note = note_fn(att_norm) if att_norm else ""
    system_content = _build_system_prompt(policy, attachment_note=att_note)
    plan_resume_final_extras: dict[str, Any] | None = None
    discover_explore_allowlist: frozenset[str] | None = None
    discover_explore_tools: list[dict[str, Any]] | None = None
    if chat_mode == "plan_discover":
        system_content = (
            _AGENT_CHAT_PLAN_DISCOVER_PREFIX
            + system_content
            + _AGENT_CHAT_PLAN_DISCOVER_SUFFIX
            + _AGENT_CHAT_PLAN_DISCOVER_FINAL_LOCK
        )
        discover_explore_allowlist, discover_explore_tools = _build_discover_tools(
            policy,
            phase="explore",
        )
        loop_allowlist, loop_tools = _build_discover_tools(
            policy,
            phase="clarify",
        )
        final_extras: dict[str, Any] | None = {"mode": "plan"}
        plan_resume_final_extras = {"mode": "plan"}
    elif chat_mode == "plan_execute":
        exec_suffix = _AGENT_CHAT_PLAN_EXECUTE_SUFFIX
        pt = (plan_text or "").strip()
        if pt:
            exec_suffix += (
                "\n\n## Approved plan markdown (authoritative; execute these steps in order)\n\n"
                + pt
            )
        system_content += exec_suffix
        loop_tools = tools
        final_extras = None
    else:
        loop_tools = tools
        final_extras = None

    oa_messages: list[dict[str, Any]] = [{"role": "system", "content": system_content}]
    _append_client_messages(oa_messages, messages, att_norm)

    logger.info(
        "agent_chat start run_id=%s backend=%s model=%s oa_messages=%d tool_specs=%d mode=%s",
        run_id,
        lm_backend,
        model,
        len(oa_messages),
        len(loop_tools),
        chat_mode,
    )
    # Persist early so terminal sandbox ``curl`` can defer mutations via
    # ``defer_mutation_if_terminal_agent_http`` (``load_agent_run`` must hit on first tool round).
    save_agent_run(
        run_id,
        {
            "oa_messages": oa_messages,
            "model": model,
            "llm_backend": lm_backend,
            "rounds": 0,
            "agent_chat_mode": chat_mode,
            "chat_attachments": att_norm,
        },
    )

    yield from _maybe_wrap_sandbox(
        policy,
        run_id,
        _run_agent_llm_tool_loop(
            provider,
            model,
            policy,
            loop_allowlist,
            loop_tools,
            oa_messages,
            0,
            run_id,
            lm_backend=lm_backend,
            reasoning=reasoning,
            max_rounds=max_rounds,
            max_tool_output_chars=max_tool_output_chars,
            max_cli_line_chars=max_cli_line_chars,
            final_extras=final_extras,
            agent_chat_mode=chat_mode,
            plan_resume_final_extras=plan_resume_final_extras,
            discover_explore_allowlist=discover_explore_allowlist,
            discover_explore_tools=discover_explore_tools,
            chat_attachments=att_norm,
        ),
        chat_attachments=att_norm,
    )


def _run_agent_resume_stream(
    run_id: str,
    resolutions: list,
    *,
    policy: AgentPolicy,
) -> Iterator[dict[str, Any]]:
    """Apply confirm/reject for pending mutations and continue the LLM tool loop."""
    max_rounds, max_tool_output_chars, _m, max_cli_line_chars = _agent_limits()

    rid = (run_id or "").strip()
    if not rid:
        logger.warning("agent_resume_mutations rejected: missing run_id")
        yield {"type": "error", "detail": "run_id is required"}
        return

    run = load_agent_run(rid)
    if not run:
        logger.warning("agent_resume_mutations rejected: unknown or expired run_id=%s", rid)
        yield {
            "type": "error",
            "detail": "Unknown or expired run_id; start a new chat.",
        }
        return

    open_ids = [str(x) for x in (run.get("open_pending_ids") or []) if str(x).strip()]
    if not open_ids:
        logger.warning("agent_resume_mutations rejected: no pending mutations run_id=%s", rid)
        yield {"type": "error", "detail": "No pending mutations for this run."}
        return

    res_norm: list[dict[str, Any]] = []
    for r in resolutions or []:
        if not isinstance(r, dict):
            continue
        pid = str(r.get("pending_id") or "").strip()
        if not pid:
            continue
        res_norm.append({"pending_id": pid, "confirm": bool(r.get("confirm"))})

    got = {r["pending_id"] for r in res_norm}
    if got != set(open_ids) or len(res_norm) != len(open_ids):
        logger.warning(
            "agent_resume_mutations rejected: resolution mismatch run_id=%s open=%s got=%s",
            rid,
            open_ids,
            sorted(got),
        )
        yield {
            "type": "error",
            "detail": (
                "resolutions must include each pending_id from awaiting_confirmation exactly once"
            ),
        }
        return

    oa_messages = run["oa_messages"]
    if not isinstance(oa_messages, list):
        yield {"type": "error", "detail": "Invalid saved agent state"}
        return

    model = str(run.get("model") or "gpt-4o-mini").strip() or "gpt-4o-mini"
    lm_backend = str(run.get("llm_backend") or "openai").strip().lower()
    if lm_backend not in ("openai", "anthropic"):
        lm_backend = "openai"
    start_round = int(run.get("rounds") or 0)
    resume_chat_mode = _normalize_agent_chat_mode(str(run.get("agent_chat_mode") or ""))
    try:
        reasoning = _resolve_agent_reasoning_config_for_chat_mode(
            lm_backend,
            resume_chat_mode,
            model,
        )
    except ValueError as exc:
        yield {"type": "error", "detail": str(exc)}
        return
    allowlist = policy.effective_allowlist()
    # Confirmed mutations must be executable even in terminal-only dispatch
    # where effective_allowlist only contains builtins.
    exec_allowlist = allowlist | policy.allowlist_mutation
    tools = openai_tool_specs(allowlist)

    try:
        provider = _resolve_provider(lm_backend, model)
    except _ProviderSetupError as exc:
        yield {"type": "error", "detail": exc.detail}
        return

    by_id = {r["pending_id"]: r["confirm"] for r in res_norm}
    n_confirm = sum(1 for c in by_id.values() if c)
    logger.info(
        "agent_resume_mutations begin run_id=%s pending=%d confirm=%d reject=%d",
        rid,
        len(open_ids),
        n_confirm,
        len(open_ids) - n_confirm,
    )
    inbox_watches_accum: list[InboxWatchDescriptor] = []
    batch_entries: list[MutationBatchEntry] = []
    inbox_id_snapshot: set[str] = set()
    snap_fn = policy.inbox_snapshot_before_mutations
    if snap_fn is not None:
        try:
            raw_snap = snap_fn()
            inbox_id_snapshot = set(raw_snap) if raw_snap is not None else set()
        except Exception:
            logger.debug(
                "inbox_snapshot_before_mutations failed",
                exc_info=True,
            )
            inbox_id_snapshot = set()
    try:
        for pid in open_ids:
            confirm = by_id[pid]
            p = load_pending(pid)
            if not p or str(p.get("run_id") or "") != rid:
                yield {
                    "type": "error",
                    "detail": f"Invalid or expired pending_id: {pid}",
                }
                return
            tid = str(p["tool_call_id"])
            fname = str(p["function_name"])
            args = str(p.get("arguments_json") or "{}")
            parsed_args_loop = json.loads(args) if args else {}
            if not isinstance(parsed_args_loop, dict):
                parsed_args_loop = {}
            if confirm:
                tex = execute_tool(
                    fname,
                    args,
                    exec_allowlist,
                    max_tool_output_chars=max_tool_output_chars,
                    run_id=rid,
                )
                logger.info(
                    "agent_resume_mutations confirmed_tool run_id=%s pending_id=%s name=%s "
                    "tool_call_id=%s ok=%s status_code=%s",
                    rid,
                    pid,
                    fname,
                    tid,
                    tex.ok,
                    tex.status_code,
                )
                parsed_args = parsed_args_loop
                parsed_result = tex.parsed_data if isinstance(tex.parsed_data, dict) else {}
                batch_entries.append(
                    MutationBatchEntry(
                        function_name=fname,
                        arguments=parsed_args,
                        result=parsed_result,
                        confirmed=True,
                    ),
                )
                model_tool_body = format_tool_result_for_model(fname, tex.raw_json)
                post_apply_fn = policy.mutation_post_apply.get(fname)
                if post_apply_fn is not None:
                    try:
                        hint = post_apply_fn(fname, parsed_args, parsed_result)
                    except Exception:
                        logger.debug(
                            "mutation_post_apply failed for %s",
                            fname,
                            exc_info=True,
                        )
                        hint = None
                    if hint is not None:
                        yield {
                            "type": "mutation_applied",
                            "pending_id": pid,
                            "name": fname,
                            "tool_call_id": tid,
                            "post_apply_review": post_apply_review_hint_to_wire(hint),
                        }
                watch_fn = policy.mutation_inbox_watches.get(fname)
                if watch_fn is not None:
                    try:
                        ws = watch_fn(fname, parsed_args, parsed_result)
                    except Exception:
                        logger.debug(
                            "mutation_inbox_watches failed for %s",
                            fname,
                            exc_info=True,
                        )
                        ws = None
                    if ws:
                        inbox_watches_accum.extend(ws)
            else:
                logger.info(
                    "agent_resume_mutations rejected_tool run_id=%s pending_id=%s name=%s "
                    "tool_call_id=%s",
                    rid,
                    pid,
                    fname,
                    tid,
                )
                rejected_result = {
                    "rejected": True,
                    "message": "User rejected this action in the assistant.",
                }
                out_json = json.dumps(rejected_result)
                batch_entries.append(
                    MutationBatchEntry(
                        function_name=fname,
                        arguments=parsed_args_loop,
                        result=rejected_result,
                        confirmed=False,
                    ),
                )
                model_tool_body = format_tool_result_for_model(fname, out_json)
            _replace_tool_message_content(oa_messages, tid, model_tool_body)
            delete_pending(pid)
    except ValueError as exc:
        logger.warning(
            "agent_resume_mutations failed run_id=%s detail=%s",
            rid,
            str(exc)[:200],
        )
        yield {"type": "error", "detail": str(exc)}
        return

    scan_fn = policy.inbox_scan_after_mutations
    if scan_fn is not None:
        try:
            extra = scan_fn(
                inbox_id_snapshot,
                batch_entries,
                list(inbox_watches_accum),
            )
        except Exception:
            logger.debug(
                "inbox_scan_after_mutations failed",
                exc_info=True,
            )
            extra = None
        if extra:
            inbox_watches_accum.extend(extra)

    if inbox_watches_accum:
        wires = [inbox_watch_to_wire(w) for w in inbox_watches_accum]
        baseline_ids: list[str] = []
        snap_live = policy.inbox_snapshot_before_mutations
        if snap_live is not None:
            try:
                raw_live = snap_live()
                baseline_ids = sorted(str(x).strip() for x in (raw_live or []) if str(x).strip())
            except Exception:
                logger.debug(
                    "inbox pending baseline snapshot failed",
                    exc_info=True,
                )
        yield from _yield_awaiting_inbox_review_barrier(
            provider=provider,
            model=model,
            policy=policy,
            oa_messages=oa_messages,
            start_round=start_round,
            rid=rid,
            wires=wires,
            baseline_ids=baseline_ids,
            lm_backend=lm_backend,
            reasoning=reasoning,
            max_tool_output_chars=max_tool_output_chars,
            max_cli_line_chars=max_cli_line_chars,
            agent_chat_mode=resume_chat_mode,
        )
        return

    # Tell the model which mutations were applied so it doesn't repeat them.
    _applied = [e for e in batch_entries if e.confirmed]
    _rejected = [e for e in batch_entries if not e.confirmed]
    _parts: list[str] = []
    for e in _applied:
        _parts.append(f"✓ {e.function_name} — confirmed and executed.")
    for e in _rejected:
        _parts.append(f"✗ {e.function_name} — rejected by user.")
    if _parts:
        _resume_note = (
            "Mutations resolved by the user:\n"
            + "\n".join(_parts)
            + "\nDo NOT repeat any confirmed mutation. "
            "Continue only if there is remaining work."
        )
        oa_messages.append({"role": "user", "content": _resume_note})

    resume_chat_attachments = _coerce_persisted_chat_attachments(run.get("chat_attachments"))

    delete_agent_run(rid)
    yield {"type": "resume_start", "run_id": rid, "model": model, "continuation": True}
    logger.info(
        "agent_chat resume_start run_id=%s model=%s start_round=%d mutations_resolved=%d",
        rid,
        model,
        start_round,
        len(open_ids),
    )

    yield from _maybe_wrap_sandbox(
        policy,
        rid,
        _run_agent_llm_tool_loop(
            provider,
            model,
            policy,
            allowlist,
            tools,
            oa_messages,
            start_round,
            rid,
            lm_backend=lm_backend,
            reasoning=reasoning,
            max_rounds=max_rounds,
            max_tool_output_chars=max_tool_output_chars,
            max_cli_line_chars=max_cli_line_chars,
            agent_chat_mode=resume_chat_mode,
            chat_attachments=resume_chat_attachments,
        ),
        chat_attachments=resume_chat_attachments,
    )


def _run_agent_resume_plan_clarification_stream(
    run_id: str,
    clarification_id: str,
    answers: list[Any],
    *,
    policy: AgentPolicy,
) -> Iterator[dict[str, Any]]:
    """Feed clarification answers into the paused plan-discovery tool call and continue."""
    max_rounds, max_tool_output_chars, _m, max_cli_line_chars = _agent_limits()

    rid = (run_id or "").strip()
    cid = (clarification_id or "").strip()
    if not rid or not cid:
        yield {"type": "error", "detail": "run_id and clarification_id are required"}
        return

    run = load_agent_run(rid)
    if not run:
        yield {
            "type": "error",
            "detail": "Unknown or expired run_id; start a new chat.",
        }
        return

    open_cid = str(run.get("open_plan_clarification_id") or "").strip()
    if not open_cid or open_cid != cid:
        yield {
            "type": "error",
            "detail": "No matching plan clarification gate for this run.",
        }
        return

    pend = load_pending(cid)
    if not pend or str(pend.get("kind") or "") != "plan_clarification":
        yield {"type": "error", "detail": "Clarification session expired or invalid."}
        return

    questions = pend.get("questions")
    if not isinstance(questions, list):
        yield {"type": "error", "detail": "Invalid saved clarification state"}
        return

    qnorm: list[dict[str, Any]] = []
    for q in questions:
        if isinstance(q, dict):
            qnorm.append(q)
    if len(qnorm) != len(questions):
        yield {"type": "error", "detail": "Invalid saved clarification state"}
        return

    sel_map, other_text_map, aerr = _validate_clarification_answers(qnorm, answers or [])
    if aerr is not None:
        yield {"type": "error", "detail": aerr}
        return
    if sel_map is None:
        yield {"type": "error", "detail": "invalid clarification answers"}
        return

    oa_messages = run["oa_messages"]
    if not isinstance(oa_messages, list):
        yield {"type": "error", "detail": "Invalid saved agent state"}
        return

    tid = str(pend.get("tool_call_id") or "").strip()
    if not tid:
        yield {"type": "error", "detail": "Invalid saved clarification state"}
        return

    model = str(run.get("model") or "gpt-4o-mini").strip() or "gpt-4o-mini"
    lm_backend = str(run.get("llm_backend") or "openai").strip().lower()
    if lm_backend not in ("openai", "anthropic"):
        lm_backend = "openai"
    start_round = int(run.get("rounds") or 0)
    resume_chat_mode = _normalize_agent_chat_mode(str(run.get("agent_chat_mode") or ""))
    if resume_chat_mode != "plan_discover":
        resume_chat_mode = "plan_discover"
    try:
        reasoning = _resolve_agent_reasoning_config_for_chat_mode(
            lm_backend,
            resume_chat_mode,
            model,
        )
    except ValueError as exc:
        yield {"type": "error", "detail": str(exc)}
        return
    raw_extras = run.get("plan_resume_final_extras")
    plan_resume_final_extras: dict[str, Any] | None
    if isinstance(raw_extras, dict):
        plan_resume_final_extras = dict(raw_extras)
    else:
        plan_resume_final_extras = {"mode": "plan"}

    discover_allowlist, tools = _build_discover_tools(
        policy,
        phase="propose",
    )

    try:
        provider = _resolve_provider(lm_backend, model)
    except _ProviderSetupError as exc:
        yield {"type": "error", "detail": exc.detail}
        return

    summary = _clarification_answer_summary_for_model(qnorm, sel_map, other_text_map)
    payload = {
        "answered": True,
        "selections": sel_map,
        "other_text_by_question": other_text_map,
        "summary_for_model": summary,
    }
    out_json = json.dumps(payload)
    model_body = format_tool_result_for_model(
        _HOF_BUILTIN_PRESENT_PLAN_CLARIFICATION,
        out_json,
    )
    try:
        _replace_tool_message_content(oa_messages, tid, model_body)
    except ValueError as exc:
        yield {"type": "error", "detail": str(exc)}
        return

    delete_pending(cid)
    plan_resume_chat_attachments = _coerce_persisted_chat_attachments(
        run.get("chat_attachments"),
    )
    delete_agent_run(rid)
    yield {"type": "resume_start", "run_id": rid, "model": model, "continuation": True}
    logger.info(
        "agent_chat plan_clarification resume_start run_id=%s clarification_id=%s",
        rid,
        cid,
    )

    yield from _maybe_wrap_sandbox(
        policy,
        rid,
        _run_agent_llm_tool_loop(
            provider,
            model,
            policy,
            discover_allowlist,
            tools,
            oa_messages,
            start_round,
            rid,
            lm_backend=lm_backend,
            reasoning=reasoning,
            max_rounds=max_rounds,
            max_tool_output_chars=max_tool_output_chars,
            max_cli_line_chars=max_cli_line_chars,
            final_extras=plan_resume_final_extras,
            agent_chat_mode=resume_chat_mode,
            plan_resume_final_extras=plan_resume_final_extras,
            discover_post_clarification_resume=True,
            chat_attachments=plan_resume_chat_attachments,
        ),
        chat_attachments=plan_resume_chat_attachments,
    )


def iter_agent_chat_stream(
    messages: list,
    attachments: list | None = None,
    mode: str | None = None,
    plan_text: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Stream agent trace (same contract as ``POST …/agent_chat/stream``).

    ``mode``:
    - ``instant`` (default): normal tool loop.
    - ``plan``: one model turn, no tools; ``final`` includes ``"mode": "plan"``.
    - ``plan_discover``: tool loop for discovery; may pause with ``awaiting_plan_clarification``.
    - ``plan_execute``: normal tool loop with system guidance to follow the approved plan.

    ``plan_text``: when ``mode`` is ``plan_execute``, optional full approved plan markdown
    (injected into the system prompt so the client need not duplicate it in ``messages``).
    """
    policy = get_agent_policy()
    yield from _run_agent_chat_stream(
        messages,
        attachments,
        policy=policy,
        mode=mode,
        plan_text=plan_text,
    )


def iter_agent_resume_stream(run_id: str, resolutions: list) -> Iterator[dict[str, Any]]:
    """Stream continued agent trace after mutation confirmation."""
    policy = get_agent_policy()
    yield from _run_agent_resume_stream(run_id, resolutions, policy=policy)


def iter_agent_resume_plan_clarification_stream(
    run_id: str,
    clarification_id: str,
    answers: list,
) -> Iterator[dict[str, Any]]:
    """Continue plan discovery after the user submits clarification answers."""
    policy = get_agent_policy()
    yield from _run_agent_resume_plan_clarification_stream(
        run_id,
        clarification_id,
        answers,
        policy=policy,
    )


def _run_agent_resume_inbox_stream(
    run_id: str,
    resolutions: list,
    *,
    policy: AgentPolicy,
) -> Iterator[dict[str, Any]]:
    """After client inbox watches clear: server verify, then continue the LLM tool loop."""
    max_rounds, max_tool_output_chars, _m, max_cli_line_chars = _agent_limits()

    rid = (run_id or "").strip()
    if not rid:
        yield {"type": "error", "detail": "run_id is required"}
        return

    run = load_agent_run(rid)
    if not run:
        yield {
            "type": "error",
            "detail": "Unknown or expired run_id; start a new chat.",
        }
        return

    raw_watches = run.get("open_inbox_watches") or []
    if not raw_watches:
        yield {"type": "error", "detail": "No inbox review watches for this run."}
        return

    descriptors: list[InboxWatchDescriptor] = []
    for w in raw_watches:
        if not isinstance(w, dict):
            continue
        d = inbox_watch_from_wire(w)
        if d is not None:
            descriptors.append(d)
    expected_ids = {d.watch_id for d in descriptors}
    if len(descriptors) != len(expected_ids) or not expected_ids:
        yield {"type": "error", "detail": "Invalid saved inbox watch state"}
        return

    res_norm: list[dict[str, Any]] = []
    for r in resolutions or []:
        if not isinstance(r, dict):
            continue
        wid = str(r.get("watch_id") or "").strip()
        if wid:
            res_norm.append({"watch_id": wid})

    got = {r["watch_id"] for r in res_norm}
    if got != expected_ids or len(res_norm) != len(expected_ids):
        yield {
            "type": "error",
            "detail": (
                "resolutions must include each watch_id from awaiting_inbox_review exactly once"
            ),
        }
        return

    verify_fn = policy.verify_inbox_watch
    if verify_fn is None:
        yield {
            "type": "error",
            "detail": "Inbox review verifier is not configured on AgentPolicy.",
        }
        return

    summary_lines: list[str] = []
    for desc in descriptors:
        try:
            ok, msg = verify_fn(desc)
        except Exception as exc:
            yield {"type": "error", "detail": f"Inbox verify failed: {exc}"}
            return
        if not ok:
            yield {
                "type": "error",
                "detail": msg or f"Inbox watch {desc.watch_id!r} is still pending review",
            }
            return
        summary_lines.append(msg or f"{desc.record_type} {desc.record_id}: inbox review completed.")

    oa_messages = run["oa_messages"]
    if not isinstance(oa_messages, list):
        yield {"type": "error", "detail": "Invalid saved agent state"}
        return

    model = str(run.get("model") or "gpt-4o-mini").strip() or "gpt-4o-mini"
    lm_backend = str(run.get("llm_backend") or "openai").strip().lower()
    if lm_backend not in ("openai", "anthropic"):
        lm_backend = "openai"
    start_round = int(run.get("rounds") or 0)
    resume_chat_mode = _normalize_agent_chat_mode(str(run.get("agent_chat_mode") or ""))
    try:
        reasoning = _resolve_agent_reasoning_config_for_chat_mode(
            lm_backend,
            resume_chat_mode,
            model,
        )
    except ValueError as exc:
        yield {"type": "error", "detail": str(exc)}
        return
    allowlist = policy.effective_allowlist()
    tools = openai_tool_specs(allowlist)

    try:
        provider = _resolve_provider(lm_backend, model)
    except _ProviderSetupError as exc:
        yield {"type": "error", "detail": exc.detail}
        return

    combined = "Inbox review completed:\n" + "\n".join(summary_lines)

    scan_resume_fn = policy.inbox_scan_after_inbox_resume
    baseline_raw = run.get("inbox_pending_baseline_ids")
    if scan_resume_fn is not None and isinstance(baseline_raw, list) and baseline_raw:
        baseline_f = frozenset(str(x).strip() for x in baseline_raw if str(x).strip())
        try:
            extra_watches, updated_baseline = scan_resume_fn(descriptors, baseline_f)
        except Exception:
            logger.debug(
                "inbox_scan_after_inbox_resume failed",
                exc_info=True,
            )
            extra_watches = []
            updated_baseline = None
        if extra_watches:
            wires = [inbox_watch_to_wire(w) for w in extra_watches]
            bl_save = sorted(updated_baseline) if updated_baseline is not None else []
            yield from _yield_awaiting_inbox_review_barrier(
                provider=provider,
                model=model,
                policy=policy,
                oa_messages=oa_messages,
                start_round=start_round,
                rid=rid,
                wires=wires,
                baseline_ids=bl_save,
                lm_backend=lm_backend,
                reasoning=reasoning,
                max_tool_output_chars=max_tool_output_chars,
                max_cli_line_chars=max_cli_line_chars,
                chained_from_inbox_resume=True,
                agent_chat_mode=resume_chat_mode,
            )
            return

    oa_messages.append({"role": "user", "content": combined})

    inbox_resume_chat_attachments = _coerce_persisted_chat_attachments(
        run.get("chat_attachments"),
    )

    delete_agent_run(rid)
    yield {"type": "resume_start", "run_id": rid, "model": model, "continuation": True}
    logger.debug(
        "agent_chat inbox resume_start run_id=%s model=%s start_round=%d",
        rid,
        model,
        start_round,
    )

    yield from _maybe_wrap_sandbox(
        policy,
        rid,
        _run_agent_llm_tool_loop(
            provider,
            model,
            policy,
            allowlist,
            tools,
            oa_messages,
            start_round,
            rid,
            lm_backend=lm_backend,
            reasoning=reasoning,
            max_rounds=max_rounds,
            max_tool_output_chars=max_tool_output_chars,
            max_cli_line_chars=max_cli_line_chars,
            agent_chat_mode=resume_chat_mode,
            chat_attachments=inbox_resume_chat_attachments,
        ),
        chat_attachments=inbox_resume_chat_attachments,
    )


def _run_agent_resume_web_session_stream(
    run_id: str,
    *,
    policy: AgentPolicy,
) -> Iterator[dict[str, Any]]:
    """After web session reaches a terminal state: inject tool result and continue the tool loop."""
    max_rounds, max_tool_output_chars, _m, max_cli_line_chars = _agent_limits()

    rid = (run_id or "").strip()
    if not rid:
        yield {"type": "error", "detail": "run_id is required"}
        return

    run = load_agent_run(rid)
    if not run:
        yield {
            "type": "error",
            "detail": "Unknown or expired run_id; start a new chat.",
        }
        return

    ows = run.get("open_web_session")
    if not isinstance(ows, dict):
        yield {"type": "error", "detail": "No pending web session for this run."}
        return

    session_id = str(ows.get("session_id") or "").strip()
    tool_call_id = str(ows.get("tool_call_id") or "").strip()
    if not session_id or not tool_call_id:
        yield {"type": "error", "detail": "Invalid open_web_session state."}
        return

    ws = load_web_session(session_id)
    if not ws:
        yield {"type": "error", "detail": "Web session not found in storage."}
        return

    st = str(ws.get("status") or "").strip()
    if st not in _WEB_SESSION_TERMINAL:
        yield {
            "type": "error",
            "detail": "Web session is still running; wait until it completes.",
        }
        return

    oa_messages = run["oa_messages"]
    if not isinstance(oa_messages, list):
        yield {"type": "error", "detail": "Invalid saved agent state"}
        return

    model = str(run.get("model") or "gpt-4o-mini").strip() or "gpt-4o-mini"
    lm_backend = str(run.get("llm_backend") or "openai").strip().lower()
    if lm_backend not in ("openai", "anthropic"):
        lm_backend = "openai"
    start_round = int(run.get("rounds") or 0)
    resume_chat_mode = _normalize_agent_chat_mode(str(run.get("agent_chat_mode") or ""))
    try:
        reasoning = _resolve_agent_reasoning_config_for_chat_mode(
            lm_backend,
            resume_chat_mode,
            model,
        )
    except ValueError as exc:
        yield {"type": "error", "detail": str(exc)}
        return
    allowlist = policy.effective_allowlist()
    tools = openai_tool_specs(allowlist)

    try:
        provider = _resolve_provider(lm_backend, model)
    except _ProviderSetupError as exc:
        yield {"type": "error", "detail": exc.detail}
        return

    sid = session_id
    live_url = ws.get("live_url")
    out = ws.get("output")
    rec = ws.get("recording_urls")
    recording_urls = list(rec) if isinstance(rec, list) else []
    out_payload: dict[str, Any] = {
        "session_id": sid,
        "live_url": live_url,
        "output": out,
        "recording_urls": recording_urls,
        "status": st,
        "sse_channel": ws.get("sse_channel"),
    }
    if sid:
        out_payload["canvas_path"] = f"/web-sessions?id={sid}"
        out_payload["canvas_href"] = (
            f"[Open browser session]({out_payload['canvas_path']}?hof_chat_embed=1)"
        )
    raw = json.dumps(out_payload, default=str)
    truncated = len(raw) > max_tool_output_chars
    if truncated:
        raw = raw[: max_tool_output_chars - 24] + "\n…(truncated)"
    _replace_tool_message_content(
        oa_messages,
        tool_call_id,
        format_tool_result_for_model(HOF_BUILTIN_BROWSE_WEB, raw),
    )

    resume_chat_attachments = _coerce_persisted_chat_attachments(
        run.get("chat_attachments"),
    )

    delete_agent_run(rid)
    yield {"type": "resume_start", "run_id": rid, "model": model, "continuation": True}
    logger.debug(
        "agent_chat web_session resume_start run_id=%s model=%s start_round=%d",
        rid,
        model,
        start_round,
    )

    yield from _maybe_wrap_sandbox(
        policy,
        rid,
        _run_agent_llm_tool_loop(
            provider,
            model,
            policy,
            allowlist,
            tools,
            oa_messages,
            start_round,
            rid,
            lm_backend=lm_backend,
            reasoning=reasoning,
            max_rounds=max_rounds,
            max_tool_output_chars=max_tool_output_chars,
            max_cli_line_chars=max_cli_line_chars,
            agent_chat_mode=resume_chat_mode,
            chat_attachments=resume_chat_attachments,
        ),
        chat_attachments=resume_chat_attachments,
    )


def iter_agent_resume_web_session_stream(
    run_id: str,
) -> Iterator[dict[str, Any]]:
    """Continue after ``awaiting_web_session`` when the Browser Use session has finished."""
    policy = get_agent_policy()
    yield from _run_agent_resume_web_session_stream(run_id, policy=policy)


def iter_agent_resume_inbox_stream(run_id: str, resolutions: list) -> Iterator[dict[str, Any]]:
    """Stream trace after inbox review resolution (client assert + server verify)."""
    policy = get_agent_policy()
    yield from _run_agent_resume_inbox_stream(run_id, resolutions, policy=policy)
