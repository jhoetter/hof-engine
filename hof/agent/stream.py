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

from hof.agent.policy import AgentPolicy, get_agent_policy
from hof.agent.state import (
    delete_agent_run,
    delete_pending,
    load_agent_run,
    load_pending,
    save_agent_run,
    save_pending,
)
from hof.agent.tooling import (
    execute_tool,
    format_cli_line,
    format_tool_result_for_model,
    openai_tool_specs,
    parsed_tool_result_for_stream,
)
from hof.config import get_config

logger = logging.getLogger(__name__)


def _log_preview(text: str, max_len: int = 140) -> str:
    """Single-line snippet for server logs (not full message bodies)."""
    if not text or not text.strip():
        return "—"
    one = " ".join(text.split())
    if len(one) <= max_len:
        return one
    return f"{one[: max_len - 1]}…"


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


def _resolve_anthropic_thinking_kw() -> dict[str, Any] | None:
    """``thinking=...`` for Anthropic Messages API (native mode only).

    ``AGENT_ANTHROPIC_THINKING``:

    - unset / empty → ``{"type": "adaptive"}`` (Sonnet/Opus 4.6)
    - ``adaptive`` → same
    - ``off`` / ``false`` / ``0`` / ``no`` → omit thinking (no ``AgentReasoningDelta`` from API)
    - otherwise parsed as JSON object (e.g. extended thinking with ``budget_tokens``)
    """
    raw = os.environ.get("AGENT_ANTHROPIC_THINKING", "").strip()
    if not raw:
        return {"type": "adaptive"}
    low = raw.lower()
    if low in ("off", "false", "0", "no"):
        return None
    if low == "adaptive":
        return {"type": "adaptive"}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"AGENT_ANTHROPIC_THINKING must be adaptive, off, or valid JSON object: {exc}"
        raise ValueError(msg) from exc
    if not isinstance(parsed, dict):
        msg = "AGENT_ANTHROPIC_THINKING JSON must be an object"
        raise ValueError(msg)
    return parsed


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
                "AGENT_REASONING_OPENAI_EXTRAS is not allowed when "
                "AGENT_REASONING_MODE is fallback"
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


def _usage_to_dict(u: Any) -> dict[str, Any] | None:
    if u is None:
        return None
    out: dict[str, Any] = {}
    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
        v = getattr(u, k, None)
        if v is not None:
            out[k] = v
    return out or None


def collect_agent_chat_from_stream(events_iter: Iterator[dict[str, Any]]) -> dict[str, Any]:
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
            legacy.append(
                {
                    "type": "tool_call",
                    "name": ev.get("name"),
                    "arguments": str(ev.get("arguments") or "")[:2000],
                    "cli_line": ev.get("cli_line", ""),
                },
            )
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
    from llm_markdown.agent_stream import AgentContentDelta, AgentMessageFinish, AgentReasoningDelta

    msgs = list(oa_messages) + [{"role": "user", "content": summary_user_message}]
    yield {"type": "phase", "round": rounds, "phase": "summary"}
    assistant_text = ""
    finish_reason: str | None = None
    last_usage: dict[str, Any] | None = None
    try:
        for ev in stream_agent_turn(
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
            if isinstance(ev, AgentContentDelta):
                assistant_text += ev.text
                yield {"type": "assistant_delta", "text": ev.text}
            elif isinstance(ev, AgentReasoningDelta):
                yield {"type": "reasoning_delta", "text": ev.text}
            elif isinstance(ev, AgentMessageFinish):
                finish_reason = ev.finish_reason
                last_usage = ev.usage
    except Exception as exc:
        logger.warning("confirmation summary model call failed: %s", exc)
        fb = (
            "I've prepared the actions above. Please use Approve or Reject for each item below; "
            "the assistant continues automatically after you choose."
        )
        yield {"type": "assistant_delta", "text": fb}
        yield {"type": "assistant_done", "finish_reason": "stop"}
        return

    if not assistant_text.strip():
        fb = (
            "I've prepared the actions above. Please use Approve or Reject for each item below; "
            "the assistant continues automatically after you choose."
        )
        yield {"type": "assistant_delta", "text": fb}
        finish_reason = finish_reason or "stop"
    done_ev: dict[str, Any] = {"type": "assistant_done", "finish_reason": finish_reason or "stop"}
    if last_usage:
        done_ev["usage"] = last_usage
    yield done_ev


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

            for ev in stream_agent_turn(
                provider,
                lm_backend,
                oa_messages,
                model=model,
                tools=tools,
                tool_choice="auto",
                max_tokens=_resolve_agent_max_completion_tokens(),
                reasoning=reasoning,
                **_anthropic_stream_turn_extras(lm_backend, reasoning),
            ):
                if isinstance(ev, AgentSegmentStart):
                    yield {"type": "segment_start", "segment": ev.segment}
                elif isinstance(ev, AgentContentDelta):
                    assistant_text += ev.text
                    n_content_delta += 1
                    yield {"type": "assistant_delta", "text": ev.text}
                elif isinstance(ev, AgentReasoningDelta):
                    n_reasoning_delta += 1
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

            done_ev: dict[str, Any] = {"type": "assistant_done", "finish_reason": finish_reason}
            if last_usage:
                done_ev["usage"] = last_usage
            yield done_ev
            _agent_stream_debug_append(
                {
                    "kind": "model_round",
                    "run_id": run_id,
                    "model": model,
                    "round": rounds,
                    "finish_reason": finish_reason,
                    "content_deltas": n_content_delta,
                    "reasoning_deltas": n_reasoning_delta,
                    "assistant_text_chars": len(assistant_text),
                    "tool_slots": len(parts),
                },
            )

            logger.info(
                "agent_chat model_round run_id=%s round=%d model=%s finish=%s "
                "content_deltas=%d reasoning_deltas=%d assistant_chars=%d tool_slots=%d preview=%s",
                run_id,
                rounds,
                model,
                finish_reason,
                n_content_delta,
                n_reasoning_delta,
                len(assistant_text),
                len(parts),
                _log_preview(assistant_text),
            )

            if finish_reason == "tool_calls":
                if not parts:
                    yield {
                        "type": "error",
                        "detail": "model returned tool_calls but no tool deltas",
                    }
                    return
                yield {"type": "phase", "round": rounds, "phase": "tools"}
                sorted_idx = sorted(parts.keys())
                tool_calls_payload: list[dict[str, Any]] = []
                for idx in sorted_idx:
                    tc = parts[idx]
                    tid = tc["id"] or f"call_{idx}"
                    name = tc["name"]
                    args = tc["arguments"] or "{}"
                    tool_calls_payload.append(
                        {
                            "id": tid,
                            "type": "function",
                            "function": {"name": name, "arguments": args},
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
                for idx in sorted_idx:
                    tc = parts[idx]
                    name = tc["name"]
                    args = tc["arguments"] or "{}"
                    tid = tc["id"] or f"call_{idx}"
                    cli = format_cli_line(name, args, max_cli_line_chars=max_cli_line_chars)
                    tc_ev: dict[str, Any] = {
                        "type": "tool_call",
                        "name": name,
                        "arguments": args[:2000],
                        "cli_line": cli,
                        "tool_call_id": tid,
                    }
                    note = policy.rationale_for(name)
                    if note:
                        tc_ev["internal_rationale"] = note
                    yield tc_ev
                    logger.info(
                        "agent_chat tool_call run_id=%s round=%d name=%s args_chars=%d mutation=%s",
                        run_id,
                        rounds,
                        name,
                        len(args),
                        "yes" if name in mutation_allowlist else "no",
                    )
                    _agent_stream_debug_append(
                        {
                            "kind": "tool_call",
                            "run_id": run_id,
                            "round": rounds,
                            "name": name,
                            "arguments_chars": len(args),
                        },
                    )
                    if name in mutation_allowlist:
                        pid = str(uuid.uuid4())
                        save_pending(
                            pid,
                            {
                                "run_id": run_id,
                                "tool_call_id": tid,
                                "function_name": name,
                                "arguments_json": args,
                            },
                        )
                        placeholder = json.dumps(
                            {"pending_confirmation": True, "pending_id": pid, "function": name},
                        )
                        yield {
                            "type": "mutation_pending",
                            "run_id": run_id,
                            "pending_id": pid,
                            "name": name,
                            "arguments": args[:12000],
                            "cli_line": cli,
                            "tool_call_id": tid,
                        }
                        yield {
                            "type": "tool_result",
                            "name": name,
                            "summary": (
                                "Awaiting your confirmation "
                                "(Assistant panel or agent_resume_mutations)."
                            ),
                            "pending_confirmation": True,
                            "tool_call_id": tid,
                        }
                        oa_messages.append(
                            {"role": "tool", "tool_call_id": tid, "content": placeholder},
                        )
                        pending_ids.append(pid)
                        logger.info(
                            "agent_chat tool_pending_confirmation run_id=%s name=%s pending_id=%s",
                            run_id,
                            name,
                            pid,
                        )
                    else:
                        out_json, summary = execute_tool(
                            name,
                            args,
                            allowlist,
                            max_tool_output_chars=max_tool_output_chars,
                        )
                        logger.info(
                            "agent_chat tool_done run_id=%s name=%s summary=%s",
                            run_id,
                            name,
                            _log_preview(summary, 200),
                        )
                        tr_out: dict[str, Any] = {
                            "type": "tool_result",
                            "name": name,
                            "summary": summary,
                            "tool_call_id": tid,
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
                if pending_ids:
                    yield from _stream_confirmation_summary_for_ui(
                        provider,
                        model,
                        oa_messages,
                        rounds,
                        policy.confirmation_summary_user_message,
                        lm_backend=lm_backend,
                        reasoning=reasoning,
                    )
                    save_agent_run(
                        run_id,
                        {
                            "oa_messages": oa_messages,
                            "model": model,
                            "llm_backend": lm_backend,
                            "rounds": rounds,
                            "open_pending_ids": pending_ids,
                        },
                    )
                    yield {
                        "type": "awaiting_confirmation",
                        "run_id": run_id,
                        "pending_ids": pending_ids,
                    }
                    logger.info(
                        "agent_chat awaiting_confirmation run_id=%s pending_ids=%d",
                        run_id,
                        len(pending_ids),
                    )
                    return
                continue

            text = assistant_text.strip()
            delete_agent_run(run_id)
            yield {"type": "final", "reply": text, "tool_rounds_used": rounds, "model": model}
            logger.info(
                "agent_chat final run_id=%s model=%s rounds_used=%d reply_chars=%d preview=%s",
                run_id,
                model,
                rounds,
                len(text),
                _log_preview(text, 180),
            )
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

        yield {"type": "error", "detail": f"Stopped after {max_rounds} model turns"}
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
        yield {"type": "error", "detail": str(exc)}


def _run_agent_chat_stream(
    messages: list,
    attachments: list | None,
    *,
    policy: AgentPolicy,
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

    model = _resolve_agent_model()
    try:
        reasoning = _resolve_agent_reasoning_config(lm_backend)
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
    oa_messages: list[dict[str, Any]] = [{"role": "system", "content": system_content}]
    _append_client_messages(oa_messages, messages, att_norm)

    logger.info(
        "agent_chat start run_id=%s backend=%s model=%s messages=%d tool_specs=%d",
        run_id,
        lm_backend,
        model,
        len(oa_messages),
        len(tools),
    )

    yield from _run_agent_openai_loop(
        provider,
        model,
        policy,
        allowlist,
        tools,
        oa_messages,
        0,
        run_id,
        lm_backend=lm_backend,
        reasoning=reasoning,
        max_rounds=max_rounds,
        max_tool_output_chars=max_tool_output_chars,
        max_cli_line_chars=max_cli_line_chars,
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
        yield {"type": "error", "detail": "run_id is required"}
        return

    run = load_agent_run(rid)
    if not run:
        yield {"type": "error", "detail": "Unknown or expired run_id; start a new chat."}
        return

    open_ids = [str(x) for x in (run.get("open_pending_ids") or []) if str(x).strip()]
    if not open_ids:
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
    try:
        reasoning = _resolve_agent_reasoning_config(lm_backend)
    except ValueError as exc:
        yield {"type": "error", "detail": str(exc)}
        return
    start_round = int(run.get("rounds") or 0)
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
    try:
        for pid in open_ids:
            confirm = by_id[pid]
            p = load_pending(pid)
            if not p or str(p.get("run_id") or "") != rid:
                yield {"type": "error", "detail": f"Invalid or expired pending_id: {pid}"}
                return
            tid = str(p["tool_call_id"])
            fname = str(p["function_name"])
            args = str(p.get("arguments_json") or "{}")
            if confirm:
                out_json, _s = execute_tool(
                    fname,
                    args,
                    allowlist,
                    max_tool_output_chars=max_tool_output_chars,
                )
                model_tool_body = format_tool_result_for_model(fname, out_json)
            else:
                out_json = json.dumps(
                    {
                        "rejected": True,
                        "message": "User rejected this action in the assistant.",
                    }
                )
                model_tool_body = format_tool_result_for_model(fname, out_json)
            _replace_tool_message_content(oa_messages, tid, model_tool_body)
            delete_pending(pid)
    except ValueError as exc:
        yield {"type": "error", "detail": str(exc)}
        return

    delete_agent_run(rid)
    yield {"type": "resume_start", "run_id": rid, "model": model}
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
    )


def iter_agent_chat_stream(
    messages: list,
    attachments: list | None = None,
) -> Iterator[dict[str, Any]]:
    """Stream agent trace (same contract as ``POST …/agent_chat/stream``)."""
    policy = get_agent_policy()
    yield from _run_agent_chat_stream(messages, attachments, policy=policy)


def iter_agent_resume_stream(run_id: str, resolutions: list) -> Iterator[dict[str, Any]]:
    """Stream continued agent trace after mutation confirmation."""
    policy = get_agent_policy()
    yield from _run_agent_resume_stream(run_id, resolutions, policy=policy)
