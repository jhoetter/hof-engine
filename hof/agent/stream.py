"""NDJSON agent chat stream: OpenAI tool loop, mutation gate, resume."""

from __future__ import annotations

import json
import logging
import os
import uuid
from collections.abc import Iterator
from typing import Any

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
    openai_tool_specs,
    parsed_tool_result_for_stream,
)
from hof.config import get_config

logger = logging.getLogger(__name__)


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
        elif t == "assistant_delta":
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
    client: Any,
    model: str,
    oa_messages: list[dict[str, Any]],
    rounds: int,
    summary_user_message: str,
) -> Iterator[dict[str, Any]]:
    msgs = list(oa_messages) + [{"role": "user", "content": summary_user_message}]
    yield {"type": "phase", "round": rounds, "phase": "summary"}
    create_kwargs: dict[str, Any] = {"model": model, "messages": msgs, "stream": True}
    try:
        try:
            stream = client.chat.completions.create(
                **create_kwargs,
                stream_options={"include_usage": True},
            )
        except TypeError:
            stream = client.chat.completions.create(**create_kwargs)
    except Exception as exc:
        logger.warning("confirmation summary model call failed: %s", exc)
        fb = (
            "I've prepared the actions above. Please use Approve or Reject for each item below; "
            "the assistant continues automatically after you choose."
        )
        yield {"type": "assistant_delta", "text": fb}
        yield {"type": "assistant_done", "finish_reason": "stop"}
        return

    assistant_text = ""
    finish_reason: str | None = None
    last_usage: dict[str, Any] | None = None
    for chunk in stream:
        if not chunk.choices:
            continue
        ch0 = chunk.choices[0]
        delta = ch0.delta
        c = getattr(delta, "content", None) or None
        if c:
            assistant_text += c
            yield {"type": "assistant_delta", "text": c}
        if ch0.finish_reason:
            finish_reason = ch0.finish_reason
        u = getattr(chunk, "usage", None)
        if u is not None:
            last_usage = _usage_to_dict(u)
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
    client: Any,
    model: str,
    policy: AgentPolicy,
    allowlist: frozenset[str],
    tools: list[dict[str, Any]],
    oa_messages: list[dict[str, Any]],
    start_round: int,
    run_id: str,
    *,
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

            create_kwargs: dict[str, Any] = {
                "model": model,
                "messages": oa_messages,
                "tools": tools,
                "tool_choice": "auto",
                "stream": True,
            }
            try:
                stream = client.chat.completions.create(
                    **create_kwargs,
                    stream_options={"include_usage": True},
                )
            except TypeError:
                stream = client.chat.completions.create(**create_kwargs)

            parts: dict[int, dict[str, str]] = {}
            assistant_text = ""
            finish_reason: str | None = None
            last_usage: dict[str, Any] | None = None

            for chunk in stream:
                if not chunk.choices:
                    continue
                ch0 = chunk.choices[0]
                delta = ch0.delta
                c = getattr(delta, "content", None) or None
                if c:
                    assistant_text += c
                    yield {"type": "assistant_delta", "text": c}
                tcd = getattr(delta, "tool_calls", None)
                if tcd:
                    for tc in tcd:
                        idx = int(tc.index)
                        if idx not in parts:
                            parts[idx] = {"id": "", "name": "", "arguments": ""}
                        if getattr(tc, "id", None):
                            parts[idx]["id"] = tc.id
                        fn = getattr(tc, "function", None)
                        if fn is not None:
                            nm = getattr(fn, "name", None) or ""
                            if nm:
                                parts[idx]["name"] += nm
                            arg = getattr(fn, "arguments", None) or ""
                            if arg:
                                parts[idx]["arguments"] += arg
                if ch0.finish_reason:
                    finish_reason = ch0.finish_reason
                u = getattr(chunk, "usage", None)
                if u is not None:
                    last_usage = _usage_to_dict(u)

            done_ev: dict[str, Any] = {"type": "assistant_done", "finish_reason": finish_reason}
            if last_usage:
                done_ev["usage"] = last_usage
            yield done_ev

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
                            "tool_call_id": tid,
                        }
                        oa_messages.append(
                            {"role": "tool", "tool_call_id": tid, "content": placeholder},
                        )
                        pending_ids.append(pid)
                    else:
                        out_json, summary = execute_tool(
                            name,
                            args,
                            allowlist,
                            max_tool_output_chars=max_tool_output_chars,
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
                            {"role": "tool", "tool_call_id": tid, "content": out_json},
                        )
                if pending_ids:
                    yield from _stream_confirmation_summary_for_ui(
                        client,
                        model,
                        oa_messages,
                        rounds,
                        policy.confirmation_summary_user_message,
                    )
                    save_agent_run(
                        run_id,
                        {
                            "oa_messages": oa_messages,
                            "model": model,
                            "rounds": rounds,
                            "open_pending_ids": pending_ids,
                        },
                    )
                    yield {
                        "type": "awaiting_confirmation",
                        "run_id": run_id,
                        "pending_ids": pending_ids,
                    }
                    return
                continue

            text = assistant_text.strip()
            delete_agent_run(run_id)
            yield {"type": "final", "reply": text, "tool_rounds_used": rounds, "model": model}
            return

        yield {"type": "error", "detail": f"Stopped after {max_rounds} model turns"}
    except Exception as exc:
        logger.exception("agent_openai_loop failed")
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

    api_key = _resolve_openai_api_key()
    if not api_key:
        yield {
            "type": "error",
            "detail": "Missing OPENAI_API_KEY (or llm_api_key in hof.config.py)",
        }
        return

    try:
        from openai import OpenAI
    except ImportError:
        yield {"type": "error", "detail": "Install the openai Python package"}
        return

    model = _resolve_agent_model()
    run_id = str(uuid.uuid4())
    yield {"type": "run_start", "run_id": run_id, "model": model}

    client = OpenAI(api_key=api_key)
    allowlist = policy.effective_allowlist()
    tools = openai_tool_specs(allowlist)

    note_fn = policy.attachments_system_note or default_attachments_system_note
    att_note = note_fn(att_norm) if att_norm else ""
    system_content = _build_system_prompt(policy, attachment_note=att_note)
    oa_messages: list[dict[str, Any]] = [{"role": "system", "content": system_content}]
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            oa_messages.append({"role": role, "content": content})

    yield from _run_agent_openai_loop(
        client,
        model,
        policy,
        allowlist,
        tools,
        oa_messages,
        0,
        run_id,
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

    api_key = _resolve_openai_api_key()
    if not api_key:
        yield {
            "type": "error",
            "detail": "Missing OPENAI_API_KEY (or llm_api_key in hof.config.py)",
        }
        return

    try:
        from openai import OpenAI
    except ImportError:
        yield {"type": "error", "detail": "Install the openai Python package"}
        return

    oa_messages = run["oa_messages"]
    if not isinstance(oa_messages, list):
        yield {"type": "error", "detail": "Invalid saved agent state"}
        return

    model = str(run.get("model") or "gpt-4o-mini").strip() or "gpt-4o-mini"
    start_round = int(run.get("rounds") or 0)
    allowlist = policy.effective_allowlist()
    tools = openai_tool_specs(allowlist)

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
            else:
                out_json = json.dumps(
                    {
                        "rejected": True,
                        "message": "User rejected this action in the assistant.",
                    }
                )
            _replace_tool_message_content(oa_messages, tid, out_json)
            delete_pending(pid)
    except ValueError as exc:
        yield {"type": "error", "detail": str(exc)}
        return

    delete_agent_run(rid)
    yield {"type": "resume_start", "run_id": rid, "model": model}

    client = OpenAI(api_key=api_key)
    yield from _run_agent_openai_loop(
        client,
        model,
        policy,
        allowlist,
        tools,
        oa_messages,
        start_round,
        rid,
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
