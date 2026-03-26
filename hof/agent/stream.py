"""NDJSON agent chat stream: OpenAI tool loop, mutation gate, resume."""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

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
    execute_tool,
    format_cli_line,
    format_tool_result_for_model,
    openai_tool_specs,
    parsed_tool_result_for_stream,
    split_agent_tool_display_metadata,
    tool_result_status_for_ui,
)
from hof.config import get_config

logger = logging.getLogger(__name__)

_HOF_BUILTIN_PRESENT_PLAN_CLARIFICATION = "hof_builtin_present_plan_clarification"
_HOF_BUILTIN_UPDATE_PLAN_TODO_STATE = "hof_builtin_update_plan_todo_state"


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
    """How many times Hof may run ``stream_agent_turn`` for one model step (after llm-markdown retries)."""
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
    """``stream_agent_turn`` failed with a retryable provider error after all engine-level attempts."""

    __slots__ = ("attempts", "cause")

    def __init__(self, cause: BaseException, *, attempts: int) -> None:
        self.cause = cause
        self.attempts = attempts
        super().__init__(str(cause))


def _provider_error_eligible_for_engine_stream_retry(exc: BaseException) -> bool:
    from llm_markdown.providers.base import ProviderError
    from llm_markdown.providers.failure_info import ProviderFailureCategory

    if not isinstance(exc, ProviderError):
        return False
    if exc.failure is not None:
        return exc.failure.category in {
            ProviderFailureCategory.RATE_LIMIT,
            ProviderFailureCategory.OVERLOADED,
            ProviderFailureCategory.SERVER,
            ProviderFailureCategory.TIMEOUT,
        }
    return bool(exc.retryable)


def _engine_stream_retry_sleep_seconds(exc: ProviderError) -> float:
    from llm_markdown.providers.failure_info import ProviderFailureCategory

    f = exc.failure
    raw = (
        float(f.retry_after_seconds)
        if f is not None and f.retry_after_seconds is not None
        else None
    )
    if raw is not None and raw > 0:
        return min(120.0, max(0.5, raw))
    if f is not None and f.category == ProviderFailureCategory.TIMEOUT:
        return 3.0
    return 5.0


def _engine_stream_wait_reason(exc: ProviderError) -> str:
    from llm_markdown.providers.failure_info import ProviderFailureCategory

    if exc.failure is not None and exc.failure.category == ProviderFailureCategory.RATE_LIMIT:
        return "rate_limit"
    return "transient_error"


def _user_message_after_engine_retries_exhausted(
    f: Any,
    *,
    attempts: int,
) -> str:
    """First-person copy after all Hof engine-level stream retries failed (no raw provider payload)."""
    times_word = "time" if attempts == 1 else "times"
    base = (
        "I hit a usage limit (too many requests or tokens in a short window). "
        f"I waited and tried again automatically {attempts} {times_word}, then had to stop."
    )
    ra = getattr(f, "retry_after_seconds", None)
    if ra is not None and isinstance(ra, (int, float)) and ra > 0:
        secs = max(1, int(round(float(ra))))
        base += f" Waiting about {secs} more seconds before you send your message again may help."
    else:
        base += " Please wait a short while, then send your message again."
    return base


def _user_message_transient_limit_without_exhausted_retries(f: Any) -> str:
    """First-person copy when a limit error is shown without engine-exhausted wording (e.g. partial stream)."""
    from llm_markdown.providers.failure_info import ProviderFailureCategory

    cat = getattr(f, "category", None)
    ra = getattr(f, "retry_after_seconds", None)
    if cat == ProviderFailureCategory.RATE_LIMIT:
        msg = (
            "I hit a usage limit before I could finish this step. "
            "Please wait a short moment and try again."
        )
    elif cat == ProviderFailureCategory.TIMEOUT:
        msg = (
            "The request timed out before I could finish this step. "
            "Please try again in a moment."
        )
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


def _agent_stream_error_event(
    exc: BaseException,
    *,
    engine_turn_retries_exhausted: bool = False,
    engine_retry_max_attempts: int | None = None,
) -> dict[str, Any]:
    """Map exceptions to NDJSON ``error``; use structured fields when :class:`ProviderError` carries failure info."""
    from llm_markdown.providers.base import ProviderError
    from llm_markdown.providers.failure_info import ProviderFailureCategory

    exhausted_categories = {
        ProviderFailureCategory.RATE_LIMIT,
        ProviderFailureCategory.OVERLOADED,
        ProviderFailureCategory.SERVER,
        ProviderFailureCategory.TIMEOUT,
    }

    if isinstance(exc, ProviderError) and exc.failure is not None:
        f = exc.failure
        attempts = (
            engine_retry_max_attempts
            if engine_retry_max_attempts is not None
            else _resolve_agent_engine_stream_max_attempts()
        )
        if engine_turn_retries_exhausted and f.category in exhausted_categories:
            detail = _user_message_after_engine_retries_exhausted(f, attempts=attempts)
        elif f.category in exhausted_categories:
            detail = _user_message_transient_limit_without_exhausted_retries(f)
        else:
            detail = f.public_message
        out: dict[str, Any] = {
            "type": "error",
            "detail": detail,
            "error_category": f.category.value,
            "retryable": False if engine_turn_retries_exhausted else bool(exc.retryable),
        }
        if f.http_status is not None:
            out["http_status"] = f.http_status
        if f.retry_after_seconds is not None:
            out["retry_after_seconds"] = f.retry_after_seconds
        return out
    return {"type": "error", "detail": str(exc)}


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

    Some ids (Haiku, Sonnet 4.5-class) return 400 ``adaptive thinking is not supported on this model``.
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

    ``model_id`` is the resolved model for this request (``PLAN_AGENT`` or ``AGENT_MODEL``); adaptive
    thinking is omitted when the id is known not to support it (e.g. ``claude-sonnet-4-5``).

    ``plan_execute`` uses the default agent model and default reasoning config (no plan-only override).
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


def _build_system_prompt(policy: AgentPolicy, *, attachment_note: str) -> str:
    text = (
        policy.system_prompt_intro
        + policy.system_prompt_body
        + policy.system_prompt_mutation_suffix
    )
    if attachment_note.strip():
        text += "\n\n## User file attachments\n" + attachment_note.strip()
    return text


_AGENT_CHAT_PLAN_MODE_SUFFIX = (
    "\n\n## Plan mode (planning only)\n"
    "The user asked for a plan before any execution. Respond with a clear markdown plan. "
    "Use `- [ ]` checkboxes for concrete actionable steps. "
    "Do not call tools and do not state that work is already done—planning only.\n"
)

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
    "`{\"done_indices\": [0, 1]}`; after the third, `{\"done_indices\": [0, 1, 2]}`.\n"
    "- Call the tool **multiple times per turn** if you complete several steps in one round.\n"
    "- Do not rely on editing markdown checkboxes — only this tool updates the UI.\n"
    "Also briefly note progress in your visible replies.\n"
)

_AGENT_CHAT_PLAN_DISCOVER_PREFIX = (
    "# \u26a0\ufe0f MODE: PLAN DISCOVERY (overrides ALL other instructions)\n\n"
    "You are in plan discovery mode. Your goal is to produce a plan the user can review and "
    "execute.\n\n"
    "## DEFAULT: ASK FIRST (use this in >90% of real requests)\n\n"
    "**First message in a new conversation:** treat the task as underspecified unless the user "
    "already stated every parameter you need (scope, method, time range, entities, preferences). "
    "In almost all cases use **(A)** clarification after light research.\n\n"
    "Most user requests are **ambiguous** about scope, method, parameters, legal/accounting rules, "
    "or preferences. **Default to (A):** call `hof_builtin_present_plan_clarification` after "
    "light research, then STOP.\n\n"
    "Only skip clarification **(B)** when the task is trivially unambiguous and fully specified. "
    "If you are unsure, **always choose (A)**.\n\n"
    "Before choosing (B), check whether anything could still be ambiguous: scope; which records "
    "or entities apply; method or parameters; time windows; policy or compliance constraints; "
    "defaults vs explicit user preferences; destructive vs non-destructive scope. If any of "
    "these are not fixed by the user\u2019s message, use (A).\n\n"
    "**When in doubt, ASK.** One extra clarification round is better than a wrong plan.\n\n"
    "## DECISION RULE (follow this EXACTLY)\n\n"
    "After researching with tools, choose **one** of two actions:\n\n"
    "**(A) Clarification needed** (default) \u2192 call `hof_builtin_present_plan_clarification` "
    "and STOP. Do NOT write any assistant text. Do NOT output a plan.\n\n"
    "**(B) Enough context** (rare) \u2192 output the structured plan as your final reply.\n\n"
    "There is NO option C. **NEVER write questions, requests for information, or open-ended "
    "requests for more detail in assistant text** \u2014 use the tool for (A).\n\n"
    "## Plan format (final reply, option B only)\n\n"
    "Your final reply must follow this exact shape:\n"
    "- Line 1: `# ` + short title (3\u20138 words)\n"
    "- Blank line\n"
    "- 1\u20132 sentences describing the approach (no data, no questions)\n"
    "- Blank line\n"
    "- `- [ ]` task lines (one concrete action per line)\n\n"
    "The description must be a **statement of intent**, not a question or request.\n\n"
    "## Rules\n\n"
    "- **NEVER** ask questions in assistant text (use tool for option A)\n"
    "- **NEVER** write data summaries from tool output in the final reply (no row counts, totals, "
    "or tables)\n"
    "- **NEVER** call mutation tools\n"
    "- Keep intermediate assistant text (before tool calls) very short\n\n"
    "## Workflow\n\n"
    "1. **Research** \u2014 call read-only tools to understand the data\n"
    "2. **Decide** \u2014 (A) need clarification? \u2192 call tool, STOP. "
    "(B) enough context? \u2192 step 3\n"
    "3. **Output plan** \u2014 reply with the structured plan\n\n"
    "## Clarification tool format (option A)\n\n"
    "Call `hof_builtin_present_plan_clarification` with:\n"
    "- Each question: `id`, `prompt`, `options` (2\u20134 choices + ALWAYS one with "
    "`id` containing \"other\" and `label` \"Andere / eigene Angabe\"), `allow_multiple`.\n"
    "- After the tool call, STOP. No text after.\n\n"
    "## WRONG vs CORRECT (shape only)\n\n"
    "\u274c Any question or multiple-choice in assistant prose \u2192 use the clarification tool "
    "(A), not text.\n"
    "\u274c Final reply that repeats tool-derived numbers or lists \u2192 forbidden.\n"
    "\u274c Final reply without `- [ ]` lines \u2192 broken.\n\n"
    "\u2705 Final reply: `# Title`, short intent statement, then `- [ ]` lines only.\n\n"
    "---\n\n"
)

_AGENT_CHAT_PLAN_DISCOVER_SUFFIX = (
    "\n\n## CRITICAL REMINDER \u2014 plan discovery mode\n"
    "**Prefer (A).** Unless the request is trivially specific, call "
    "`hof_builtin_present_plan_clarification`, then STOP (no assistant text).\n"
    "Only (B) if unambiguous: reply with `# Title` + description + `- [ ]` lines.\n"
    "NEVER put questions or data dumps in assistant text.\n"
)


def _normalize_agent_chat_mode(mode: str | None) -> str:
    """Return ``instant``, ``plan``, ``plan_discover``, or ``plan_execute``."""
    raw = (mode or "").strip().lower().replace("-", "_")
    if raw in ("plan", "plan_discover", "plan_execute"):
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
                "questions": ev.get("questions") if isinstance(ev.get("questions"), list) else [],
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
            "confirmation summary model call failed after engine stream retries, using static fallback",
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
        yield {"type": "phase", "round": start_round + 1, "phase": "inbox_review_summary"}
        yield {"type": "assistant_delta", "text": text}
        yield {"type": "assistant_done", "finish_reason": "stop"}
        oa_messages.append({"role": "assistant", "content": text})
        return

    if mode != "llm_stream":
        yield {
            "type": "error",
            "detail": (
                f"invalid inbox_review_summary_mode={mode!r} "
                "(expected llm_stream, static, or none)"
            ),
        }
        return

    oa_messages.append({"role": "user", "content": user_content})
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
                "inbox review summary model call failed after engine stream retries, using static fallback",
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

        yield {"type": "phase", "round": phase_round, "phase": "inbox_review_summary_tools"}
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
            cli = format_cli_line(name, args_wire, max_cli_line_chars=max_cli_line_chars)
            tc_ev: dict[str, Any] = {
                "type": "tool_call",
                "name": name,
                "arguments": args_wire[:2000],
                "cli_line": cli,
                "tool_call_id": tid,
            }
            if display_title:
                tc_ev["display_title"] = display_title
            note = policy.rationale_for(name)
            if note:
                tc_ev["internal_rationale"] = note
            yield tc_ev
            out_json, summary = execute_tool(
                name,
                args_wire,
                read_allowlist,
                max_tool_output_chars=max_tool_output_chars,
            )
            ok, status_code = tool_result_status_for_ui(out_json)
            tr_out: dict[str, Any] = {
                "type": "tool_result",
                "name": name,
                "summary": summary,
                "tool_call_id": tid,
                "ok": ok,
                "status_code": status_code,
            }
            pdata = parsed_tool_result_for_stream(out_json)
            if pdata is not None:
                tr_out["data"] = pdata
            yield tr_out
            oa_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tid,
                    "content": format_tool_result_for_model(name, out_json),
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
    save_agent_run_with_ttl(
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
    try:
        parsed = json.loads(arguments_json or "{}")
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"
    if not isinstance(parsed, dict):
        return None, "arguments must be a JSON object"
    raw_q = parsed.get("questions")
    if isinstance(raw_q, str):
        try:
            raw_q = json.loads(raw_q)
        except json.JSONDecodeError:
            pass
    if not isinstance(raw_q, list) or len(raw_q) < 1:
        return None, "questions must be a non-empty array"
    out: list[dict[str, Any]] = []
    for i, q in enumerate(raw_q):
        if not isinstance(q, dict):
            return None, f"questions[{i}] must be an object"
        qid = str(q.get("id") or "").strip()
        prompt = str(q.get("prompt") or "").strip()
        if not qid or not prompt:
            return None, f"questions[{i}]: id and prompt are required"
        opts = q.get("options")
        if not isinstance(opts, list) or len(opts) < 2:
            return None, f"questions[{i}]: at least two options required"
        if len(opts) > 5:
            return None, f"questions[{i}]: at most 5 options allowed (2-4 concrete + 'other')"
        norm_opts: list[dict[str, str]] = []
        seen_o: set[str] = set()
        has_other = False
        for j, o in enumerate(opts):
            if not isinstance(o, dict):
                return None, f"questions[{i}].options[{j}] must be object"
            oid = str(o.get("id") or "").strip()
            label = str(o.get("label") or "").strip()
            if not oid or not label:
                return None, f"questions[{i}].options[{j}]: id and label required"
            if oid in seen_o:
                return None, f"duplicate option id {oid!r}"
            seen_o.add(oid)
            norm_opts.append({"id": oid, "label": label})
            if "other" in oid.lower():
                has_other = True
        if not has_other:
            norm_opts.append({"id": f"q{i}_other", "label": "Andere / eigene Angabe"})
        am = q.get("allow_multiple")
        allow_multiple = bool(am) if am is not None else False
        out.append(
            {
                "id": qid,
                "prompt": prompt,
                "options": norm_opts,
                "allow_multiple": allow_multiple,
            },
        )
    return out, None


def _validate_clarification_answers(
    questions: list[dict[str, Any]],
    answers: list[Any],
) -> tuple[dict[str, list[str]] | None, dict[str, str], str | None]:
    if not isinstance(answers, list):
        return None, {}, "answers must be a list"
    qmap = {str(q["id"]): q for q in questions}
    out: dict[str, list[str]] = {}
    other_text_by_qid: dict[str, str] = {}
    for i, a in enumerate(answers):
        if not isinstance(a, dict):
            return None, {}, f"answers[{i}] must be object"
        qid = str(a.get("question_id") or a.get("questionId") or "").strip()
        sel = a.get("selected_option_ids") or a.get("selectedOptionIds")
        if not qid or qid not in qmap:
            return None, {}, f"unknown question_id: {qid!r}"
        if not isinstance(sel, list):
            return None, {}, f"selected_option_ids must be array for {qid!r}"
        oids = [str(x).strip() for x in sel if str(x).strip()]
        allowed = {o["id"] for o in qmap[qid]["options"]}
        for oid in oids:
            if oid not in allowed:
                return None, {}, f"invalid option id {oid!r} for question {qid!r}"
        if not qmap[qid]["allow_multiple"] and len(oids) > 1:
            return None, {}, f"question {qid!r} allows only one option"
        if len(oids) < 1:
            return None, {}, f"question {qid!r} requires at least one selected option"
        raw_other = a.get("other_text") or a.get("otherText")
        other_t = str(raw_other).strip() if raw_other is not None else ""
        has_other_option = any("other" in oid.lower() for oid in oids)
        if has_other_option and not other_t:
            return (
                None,
                {},
                f"question {qid!r}: other_text is required when an Other option is selected",
            )
        if other_t and not has_other_option:
            return (
                None,
                {},
                f"question {qid!r}: other_text is only allowed when an Other option is selected",
            )
        if other_t:
            other_text_by_qid[qid] = other_t
        out[qid] = oids
    if set(out.keys()) != set(qmap.keys()):
        return None, {}, "each question must be answered exactly once"
    return out, other_text_by_qid, None


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


def _run_agent_openai_loop(
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
) -> Iterator[dict[str, Any]]:
    """Run model ↔ tools until final reply, error, or halt for mutation confirmation."""
    rounds = start_round
    mutation_allowlist = policy.allowlist_mutation
    try:
        while rounds < max_rounds:
            rounds += 1
            yield {"type": "phase", "round": rounds, "phase": "model"}

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

            st_tools = tools if len(tools) > 0 else None
            st_tool_choice = "auto" if st_tools is not None else None
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
                if agent_chat_mode == "plan_discover":
                    clarify_idxs = [
                        i
                        for i in sorted_idx
                        if parts[i].get("name") == _HOF_BUILTIN_PRESENT_PLAN_CLARIFICATION
                    ]
                    if len(clarify_idxs) > 1:
                        yield {
                            "type": "error",
                            "detail": (
                                "at most one hof_builtin_present_plan_clarification "
                                "per round"
                            ),
                        }
                        return
                    if len(clarify_idxs) == 1:
                        cix = clarify_idxs[0]
                        if cix != sorted_idx[-1]:
                            yield {
                                "type": "error",
                                "detail": (
                                    "hof_builtin_present_plan_clarification must be the last "
                                    "tool call in the round"
                                ),
                            }
                            return
                        if any(
                            parts[j].get("name") in mutation_allowlist for j in sorted_idx
                        ):
                            yield {
                                "type": "error",
                                "detail": (
                                    "cannot combine hof_builtin_present_plan_clarification "
                                    "with mutation tools in the same round"
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
                for idx in sorted_idx:
                    tc = parts[idx]
                    name = tc["name"]
                    args_raw = tc["arguments"] or "{}"
                    args_wire, display_title = split_agent_tool_display_metadata(args_raw)
                    tid = tc["id"] or f"call_{idx}"
                    cli = format_cli_line(name, args_wire, max_cli_line_chars=max_cli_line_chars)
                    tc_ev: dict[str, Any] = {
                        "type": "tool_call",
                        "name": name,
                        "arguments": args_wire[:2000],
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
                            "agent_chat plan_clarification_validating run_id=%s "
                            "args_wire_chars=%d",
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
                            yield {"type": "error", "detail": verr}
                            return
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
                        mp_ev: dict[str, Any] = {
                            "type": "mutation_pending",
                            "run_id": run_id,
                            "pending_id": pid,
                            "name": name,
                            "arguments": args_wire[:12000],
                            "cli_line": cli,
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
                    else:
                        out_json, summary = execute_tool(
                            name,
                            args_wire,
                            allowlist,
                            max_tool_output_chars=max_tool_output_chars,
                        )
                        ok, status_code = tool_result_status_for_ui(out_json)
                        logger.info(
                            "agent_chat tool_result emit run_id=%s round=%d name=%s "
                            "tool_call_id=%s ok=%s status_code=%s summary_chars=%d",
                            run_id,
                            rounds,
                            name,
                            tid,
                            ok,
                            status_code,
                            len(summary or ""),
                        )
                        tr_out: dict[str, Any] = {
                            "type": "tool_result",
                            "name": name,
                            "summary": summary,
                            "tool_call_id": tid,
                            "ok": ok,
                            "status_code": status_code,
                        }
                        pdata = parsed_tool_result_for_stream(out_json)
                        if pdata is not None:
                            tr_out["data"] = pdata
                        if name in BUILTIN_AGENT_TOOL_NAMES:
                            tr_out["internal"] = True
                        yield tr_out
                        oa_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tid,
                                "content": format_tool_result_for_model(name, out_json),
                            },
                        )
                        if (
                            name == _HOF_BUILTIN_UPDATE_PLAN_TODO_STATE
                            and agent_chat_mode == "plan_execute"
                        ):
                            try:
                                body = json.loads(out_json)
                                di = body.get("done_indices")
                                if isinstance(di, list) and di:
                                    idxs: list[int] = []
                                    for x in di:
                                        try:
                                            idxs.append(int(x))
                                        except (TypeError, ValueError):
                                            continue
                                    if idxs:
                                        # Wire contract + client normalization: hof-react
                                        # docs/plan-todo-contract.md
                                        yield {
                                            "type": "plan_todo_update",
                                            "done_indices": idxs,
                                        }
                            except (json.JSONDecodeError, TypeError):
                                pass
                if plan_clarify_halt is not None:
                    store_extras = (
                        plan_resume_final_extras
                        if plan_resume_final_extras is not None
                        else {}
                    )
                    save_agent_run(
                        run_id,
                        {
                            "oa_messages": oa_messages,
                            "model": model,
                            "llm_backend": lm_backend,
                            "rounds": rounds,
                            "open_plan_clarification_id": plan_clarify_halt,
                            "agent_chat_mode": "plan_discover",
                            "plan_resume_final_extras": store_extras,
                        },
                    )
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
                    save_agent_run(
                        run_id,
                        {
                            "oa_messages": oa_messages,
                            "model": model,
                            "llm_backend": lm_backend,
                            "rounds": rounds,
                            "open_pending_ids": pending_ids,
                            "agent_chat_mode": agent_chat_mode,
                        },
                    )
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
                continue

            text = assistant_text.strip()
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
        logger.exception("agent_openai_loop failed after engine stream retries")
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
        logger.exception("agent_openai_loop failed")
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

    if lm_backend == "anthropic":
        api_key = _resolve_anthropic_api_key()
        if not api_key:
            yield {
                "type": "error",
                "detail": "Missing ANTHROPIC_API_KEY (required when AGENT_LLM_BACKEND=anthropic)",
            }
            return
        try:
            from llm_markdown.providers import AnthropicProvider
        except ImportError:
            yield {
                "type": "error",
                "detail": "Install llm-markdown with the anthropic extra (llm-markdown[anthropic])",
            }
            return
        provider = AnthropicProvider(
            api_key=api_key,
            model=model,
            max_tokens=_resolve_agent_max_completion_tokens(),
        )
    else:
        api_key = _resolve_openai_api_key()
        if not api_key:
            yield {
                "type": "error",
                "detail": "Missing OPENAI_API_KEY (or llm_api_key in hof.config.py)",
            }
            return
        try:
            from llm_markdown.providers import OpenAIProvider
        except ImportError:
            yield {
                "type": "error",
                "detail": "Install llm-markdown with the openai extra (llm-markdown[openai])",
            }
            return
        provider = OpenAIProvider(
            api_key=api_key,
            model=model,
            max_tokens=_resolve_agent_max_completion_tokens(),
        )

    run_id = str(uuid.uuid4())
    yield {"type": "run_start", "run_id": run_id, "model": model}
    _agent_stream_debug_append({"kind": "run_begin", "run_id": run_id, "model": model})
    allowlist = policy.effective_allowlist()
    tools = openai_tool_specs(allowlist)

    note_fn = policy.attachments_system_note or default_attachments_system_note
    att_note = note_fn(att_norm) if att_norm else ""
    system_content = _build_system_prompt(policy, attachment_note=att_note)
    plan_resume_final_extras: dict[str, Any] | None = None
    if chat_mode == "plan":
        system_content += _AGENT_CHAT_PLAN_MODE_SUFFIX
        loop_tools: list[dict[str, Any]] = []
        final_extras: dict[str, Any] | None = {"mode": "plan"}
    elif chat_mode == "plan_discover":
        system_content = _AGENT_CHAT_PLAN_DISCOVER_PREFIX + system_content + _AGENT_CHAT_PLAN_DISCOVER_SUFFIX
        discover_allowlist = frozenset(policy.allowlist_read | BUILTIN_AGENT_TOOL_NAMES)
        loop_tools = openai_tool_specs(discover_allowlist)
        final_extras = {"mode": "plan"}
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

    yield from _run_agent_openai_loop(
        provider,
        model,
        policy,
        allowlist,
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
    )


def _run_agent_resume_stream(
    run_id: str,
    resolutions: list,
    *,
    policy: AgentPolicy,
) -> Iterator[dict[str, Any]]:
    """Apply confirm/reject for pending mutations and continue the OpenAI loop."""
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
    tools = openai_tool_specs(allowlist)

    if lm_backend == "anthropic":
        api_key = _resolve_anthropic_api_key()
        if not api_key:
            yield {
                "type": "error",
                "detail": "Missing ANTHROPIC_API_KEY (required to resume this run)",
            }
            return
        try:
            from llm_markdown.providers import AnthropicProvider
        except ImportError:
            yield {
                "type": "error",
                "detail": "Install llm-markdown with the anthropic extra (llm-markdown[anthropic])",
            }
            return
        provider = AnthropicProvider(
            api_key=api_key,
            model=model,
            max_tokens=_resolve_agent_max_completion_tokens(),
        )
    else:
        api_key = _resolve_openai_api_key()
        if not api_key:
            yield {
                "type": "error",
                "detail": "Missing OPENAI_API_KEY (or llm_api_key in hof.config.py)",
            }
            return
        try:
            from llm_markdown.providers import OpenAIProvider
        except ImportError:
            yield {
                "type": "error",
                "detail": "Install llm-markdown with the openai extra (llm-markdown[openai])",
            }
            return
        provider = OpenAIProvider(
            api_key=api_key,
            model=model,
            max_tokens=_resolve_agent_max_completion_tokens(),
        )

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
                out_json, _s = execute_tool(
                    fname,
                    args,
                    allowlist,
                    max_tool_output_chars=max_tool_output_chars,
                )
                _ok, _code = tool_result_status_for_ui(out_json)
                logger.info(
                    "agent_resume_mutations confirmed_tool run_id=%s pending_id=%s name=%s "
                    "tool_call_id=%s ok=%s status_code=%s",
                    rid,
                    pid,
                    fname,
                    tid,
                    _ok,
                    _code,
                )
                parsed_args = parsed_args_loop
                parsed_result = json.loads(out_json) if out_json else {}
                if not isinstance(parsed_result, dict):
                    parsed_result = {}
                batch_entries.append(
                    MutationBatchEntry(
                        function_name=fname,
                        arguments=parsed_args,
                        result=parsed_result,
                        confirmed=True,
                    ),
                )
                model_tool_body = format_tool_result_for_model(fname, out_json)
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
                baseline_ids = sorted(
                    str(x).strip() for x in (raw_live or []) if str(x).strip()
                )
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

    delete_agent_run(rid)
    yield {"type": "resume_start", "run_id": rid, "model": model, "continuation": True}
    logger.info(
        "agent_chat resume_start run_id=%s model=%s start_round=%d mutations_resolved=%d",
        rid,
        model,
        start_round,
        len(open_ids),
    )

    yield from _run_agent_openai_loop(
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
        yield {"type": "error", "detail": "No matching plan clarification gate for this run."}
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

    sel_map, other_text_map, aerr = _validate_clarification_answers(
        qnorm, answers or []
    )
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

    discover_allowlist = frozenset(policy.allowlist_read | BUILTIN_AGENT_TOOL_NAMES)
    tools = openai_tool_specs(discover_allowlist)

    if lm_backend == "anthropic":
        api_key = _resolve_anthropic_api_key()
        if not api_key:
            yield {
                "type": "error",
                "detail": "Missing ANTHROPIC_API_KEY (required to resume this run)",
            }
            return
        try:
            from llm_markdown.providers import AnthropicProvider
        except ImportError:
            yield {
                "type": "error",
                "detail": "Install llm-markdown with the anthropic extra (llm-markdown[anthropic])",
            }
            return
        provider = AnthropicProvider(
            api_key=api_key,
            model=model,
            max_tokens=_resolve_agent_max_completion_tokens(),
        )
    else:
        api_key = _resolve_openai_api_key()
        if not api_key:
            yield {
                "type": "error",
                "detail": "Missing OPENAI_API_KEY (or llm_api_key in hof.config.py)",
            }
            return
        try:
            from llm_markdown.providers import OpenAIProvider
        except ImportError:
            yield {
                "type": "error",
                "detail": "Install llm-markdown with the openai extra (llm-markdown[openai])",
            }
            return
        provider = OpenAIProvider(
            api_key=api_key,
            model=model,
            max_tokens=_resolve_agent_max_completion_tokens(),
        )

    summary = _clarification_answer_summary_for_model(
        qnorm, sel_map, other_text_map
    )
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
    delete_agent_run(rid)
    yield {"type": "resume_start", "run_id": rid, "model": model, "continuation": True}
    logger.info(
        "agent_chat plan_clarification resume_start run_id=%s clarification_id=%s",
        rid,
        cid,
    )

    yield from _run_agent_openai_loop(
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
    """After client inbox watches clear: server verify, then continue the OpenAI loop."""
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
        summary_lines.append(
            msg
            or f"{desc.record_type} {desc.record_id}: inbox review completed."
        )

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

    if lm_backend == "anthropic":
        api_key = _resolve_anthropic_api_key()
        if not api_key:
            yield {
                "type": "error",
                "detail": "Missing ANTHROPIC_API_KEY (required to resume this run)",
            }
            return
        try:
            from llm_markdown.providers import AnthropicProvider
        except ImportError:
            yield {
                "type": "error",
                "detail": "Install llm-markdown with the anthropic extra (llm-markdown[anthropic])",
            }
            return
        provider = AnthropicProvider(
            api_key=api_key,
            model=model,
            max_tokens=_resolve_agent_max_completion_tokens(),
        )
    else:
        api_key = _resolve_openai_api_key()
        if not api_key:
            yield {
                "type": "error",
                "detail": "Missing OPENAI_API_KEY (or llm_api_key in hof.config.py)",
            }
            return
        try:
            from llm_markdown.providers import OpenAIProvider
        except ImportError:
            yield {
                "type": "error",
                "detail": "Install llm-markdown with the openai extra (llm-markdown[openai])",
            }
            return
        provider = OpenAIProvider(
            api_key=api_key,
            model=model,
            max_tokens=_resolve_agent_max_completion_tokens(),
        )

    combined = "Inbox review completed:\n" + "\n".join(summary_lines)

    scan_resume_fn = policy.inbox_scan_after_inbox_resume
    baseline_raw = run.get("inbox_pending_baseline_ids")
    if (
        scan_resume_fn is not None
        and isinstance(baseline_raw, list)
        and baseline_raw
    ):
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

    delete_agent_run(rid)
    yield {"type": "resume_start", "run_id": rid, "model": model, "continuation": True}
    logger.debug(
        "agent_chat inbox resume_start run_id=%s model=%s start_round=%d",
        rid,
        model,
        start_round,
    )

    yield from _run_agent_openai_loop(
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
    )


def iter_agent_resume_inbox_stream(run_id: str, resolutions: list) -> Iterator[dict[str, Any]]:
    """Stream trace after inbox review resolution (client assert + server verify)."""
    policy = get_agent_policy()
    yield from _run_agent_resume_inbox_stream(run_id, resolutions, policy=policy)
