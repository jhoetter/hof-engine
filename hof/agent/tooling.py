"""OpenAI tool specs, CLI formatting, and registry-backed tool execution."""

from __future__ import annotations

import json
import logging
import re
import shlex
import threading
from typing import Any

from pydantic import ValidationError

from hof.agent.policy import AgentPolicy
from hof.core.registry import registry
from hof.db.schemas import build_function_input_schema
from hof.functions import FunctionMetadata

logger = logging.getLogger(__name__)

# Propagates ``run_id`` / tool_call_id into builtins (e.g. ``hof_builtin_terminal_exec``) when
# TLS state is set by the agent stream before ``execute_tool`` (Starlette streaming).
_tls_tool_run_id = threading.local()
_tls_tool_call_id = threading.local()


def get_tool_execution_run_id() -> str | None:
    return getattr(_tls_tool_run_id, "run_id", None)


def get_tool_execution_tool_call_id() -> str | None:
    return getattr(_tls_tool_call_id, "tool_call_id", None)

_REDACT_SUBSTRINGS = ("token", "password", "secret", "api_key", "authorization")

# OpenAI and other providers accept long descriptions; keep a hard cap for stability.
AGENT_TOOL_DESCRIPTION_MAX_CHARS = 2000

# Optional tool-arguments key: model supplies a short UI label; stripped before execute/history/CLI.
AGENT_TOOL_DISPLAY_TITLE_KEY = "_display_title"
AGENT_TOOL_DISPLAY_TITLE_MAX_CHARS = 120

def _json_type_for_param(type_name: str) -> str:
    return {
        "int": "integer",
        "float": "number",
        "bool": "boolean",
        "str": "string",
        "dict": "object",
        "list": "array",
        "Any": "string",
    }.get(type_name, "string")


def _openai_property_schema_for_param(type_name: str) -> dict[str, Any]:
    """JSON Schema for one tool param (OpenAI array schemas need ``items``)."""
    desc = (type_name or "value")[:120]
    if type_name == "list":
        return {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": True,
            },
            "description": desc,
        }
    return {
        "type": _json_type_for_param(type_name),
        "description": desc,
    }


def compose_agent_tool_description(function_name: str, meta: FunctionMetadata) -> str:
    """Build the model-facing tool description (docstring + optional metadata + policy hints)."""
    from hof.agent.policy import try_get_agent_policy

    policy = try_get_agent_policy()
    parts: list[str] = []
    summary = (meta.tool_summary or "").strip()
    body = (meta.description or "").strip()
    if summary and body:
        parts.append(f"{summary}\n\n{body}")
    elif summary:
        parts.append(summary)
    elif body:
        parts.append(body)
    else:
        parts.append(function_name)

    when = (meta.when_to_use or "").strip()
    if not when and policy is not None:
        when = (policy.tool_when_to_use.get(function_name) or "").strip()
    if when:
        parts.append(f"When to use: {when}")

    when_not = (meta.when_not_to_use or "").strip()
    if when_not:
        parts.append(f"When not to use: {when_not}")

    related = list(meta.related_tools) if meta.related_tools else []
    if not related and policy is not None:
        related = list(policy.tool_related_tools.get(function_name, []))
    if related:
        parts.append(f"Typical next steps: {', '.join(related)}")

    text = "\n\n".join(parts)
    if len(text) > AGENT_TOOL_DESCRIPTION_MAX_CHARS:
        text = text[: AGENT_TOOL_DESCRIPTION_MAX_CHARS - 1] + "…"
    return text


def split_agent_tool_display_metadata(arguments_json: str) -> tuple[str, str | None]:
    """Split UI-only display title from tool arguments JSON.

    Returns ``(arguments_json_for_wire_and_execute, display_title_or_none)``.
    On invalid JSON, returns the original string and ``None`` (caller may fall back to CLI
    formatting).
    """
    raw = (arguments_json or "").strip() or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw, None
    if not isinstance(parsed, dict):
        return raw, None
    work = dict(parsed)
    title_raw = work.pop(AGENT_TOOL_DISPLAY_TITLE_KEY, None)
    title: str | None = None
    if isinstance(title_raw, str):
        t = title_raw.strip()
        if t:
            title = t[:AGENT_TOOL_DISPLAY_TITLE_MAX_CHARS]
    wire = json.dumps(work, separators=(",", ":"), ensure_ascii=False)
    return wire, title


def structured_agent_tool_for_ui(
    function_name: str,
    meta: FunctionMetadata,
    policy: AgentPolicy | None,
    *,
    mutation: bool,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    """Structured fields for agent skills UI (policy merge matches composed tool description)."""
    when = (meta.when_to_use or "").strip()
    if not when and policy is not None:
        when = (policy.tool_when_to_use.get(function_name) or "").strip()
    when_not = (meta.when_not_to_use or "").strip()
    related = list(meta.related_tools) if meta.related_tools else []
    if not related and policy is not None:
        related = list(policy.tool_related_tools.get(function_name, []))
    return {
        "name": function_name,
        "mutation": mutation,
        "tool_summary": (meta.tool_summary or "").strip(),
        "description": (meta.description or "").strip(),
        "when_to_use": when,
        "when_not_to_use": when_not,
        "related_tools": related,
        "parameters": parameters,
    }


def format_function_describe_from_static_meta(data: dict[str, Any]) -> str:
    """Format static ``function_schema`` / ``to_dict()`` JSON (no policy/registry merge)."""
    name = str(data.get("name") or "")
    lines: list[str] = [f"Function: {name}", ""]
    parts: list[str] = []
    summary = str(data.get("tool_summary") or "").strip()
    body = str(data.get("description") or "").strip()
    if summary and body:
        parts.append(f"{summary}\n\n{body}")
    elif summary:
        parts.append(summary)
    elif body:
        parts.append(body)
    else:
        parts.append(name or "(no description)")
    when = str(data.get("when_to_use") or "").strip()
    if when:
        parts.append(f"When to use: {when}")
    when_not = str(data.get("when_not_to_use") or "").strip()
    if when_not:
        parts.append(f"When not to use: {when_not}")
    related = data.get("related_tools")
    if isinstance(related, list) and related:
        parts.append(f"Typical next steps: {', '.join(str(x) for x in related)}")
    lines.append("\n\n".join(parts))
    lines.extend(["", "Parameters:"])
    params = data.get("parameters") or []
    if not params:
        lines.append("  (none)")
    else:
        for p in params:
            if not isinstance(p, dict):
                continue
            pname = p.get("name")
            if not isinstance(pname, str) or pname.startswith("_"):
                continue
            tname = p.get("type") or "Any"
            req = "required" if p.get("required") else "optional"
            lines.append(f"  - {pname} ({tname}, {req})")
    return "\n".join(lines)


def format_function_describe_text(function_name: str, meta: FunctionMetadata) -> str:
    """Multi-line help for ``hof fn describe`` (agent parity, including parameters)."""
    lines: list[str] = [
        f"Function: {function_name}",
        "",
        compose_agent_tool_description(function_name, meta),
        "",
        "Parameters:",
    ]
    for p in meta.parameters:
        if p.name.startswith("_"):
            continue
        tname = getattr(p.type_annotation, "__name__", str(p.type_annotation))
        req = "required" if p.required else "optional"
        lines.append(f"  - {p.name} ({tname}, {req})")
    if len(lines) == 5:
        lines.append("  (none)")
    return "\n".join(lines)


def openai_tool_specs(allowlist: frozenset[str]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for name in sorted(allowlist):
        meta = registry.get_function(name)
        if meta is None:
            continue
        properties: dict[str, Any] = {}
        required: list[str] = []
        for p in meta.parameters:
            if p.name.startswith("_"):
                continue
            raw = getattr(p.type_annotation, "__name__", str(p.type_annotation))
            properties[p.name] = _openai_property_schema_for_param(raw)
            if p.required:
                required.append(p.name)
        properties[AGENT_TOOL_DISPLAY_TITLE_KEY] = {
            "type": "string",
            "maxLength": AGENT_TOOL_DISPLAY_TITLE_MAX_CHARS,
            "description": (
                "Optional. One short phrase for the assistant UI tool row: **what you are doing** "
                "plus **which target** (e.g. 'Registering receipt: Rechnung.pdf', "
                "'Loading expense #3'). "
                "When calling the same tool several times in parallel, make each title "
                "**distinct** "
                "(use row #, id snippet, or filename). A bare filename alone is weak — include the "
                "action. "
                "Not passed to the function implementation."
            ),
        }
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": compose_agent_tool_description(name, meta),
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            }
        )
    return specs


def _redact_for_cli(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            lk = str(k).lower()
            if any(s in lk for s in _REDACT_SUBSTRINGS):
                out[k] = "***"
            else:
                out[k] = _redact_for_cli(v)
        return out
    if isinstance(obj, list):
        return [_redact_for_cli(x) for x in obj[:80]]
    return obj


_TERMINAL_HOF_FN_RE = re.compile(r"\bhof\s+fn\s+([a-zA-Z0-9_]+)")


def _hof_fn_shell_to_pseudo_cli(cmd: str, cap: int) -> str | None:
    """Turn ``hof fn <name> '<json>'`` into the same pseudo-CLI as :func:`format_cli_line`."""
    m = re.search(r"\bhof\s+fn\s+([a-zA-Z0-9_]+)\s*", cmd)
    if not m:
        return None
    fn_name = m.group(1)
    if fn_name in ("list", "describe", "help"):
        return None
    rest = cmd[m.end() :].strip()
    if not rest:
        return f"hof fn {fn_name}"
    if (rest.startswith("'") and rest.endswith("'")) or (
        rest.startswith('"') and rest.endswith('"')
    ):
        rest = rest[1:-1]
    try:
        body = json.loads(rest)
    except json.JSONDecodeError:
        return None
    if isinstance(body, dict):
        args_wire = json.dumps(body, ensure_ascii=False)
        return format_cli_line(fn_name, args_wire, max_cli_line_chars=cap)
    compact = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
    line = f"hof fn {fn_name} {compact}"
    if len(line) > cap:
        return line[: cap - 1] + "…"
    return line


def _format_terminal_exec_cli_line(wire: str, cap: int) -> str:
    """For ``hof_builtin_terminal_exec``, show the shell command itself, not the wrapper."""
    from hof.agent.sandbox.mutation_bridge import (
        parse_terminal_exec_command,
    )

    cmd = parse_terminal_exec_command(wire)
    if not cmd:
        return "(terminal)"
    pseudo = _hof_fn_shell_to_pseudo_cli(cmd, cap)
    if pseudo:
        return pseudo
    fn_match = _TERMINAL_HOF_FN_RE.search(cmd)
    if fn_match:
        fn_name = fn_match.group(1)
        return f"hof fn {fn_name}" if len(cmd) > cap else cmd
    if len(cmd) > cap:
        cmd = cmd[: cap - 1] + "…"
    return cmd




def format_cli_line(name: str, arguments_json: str, *, max_cli_line_chars: int) -> str:
    """Human-readable pseudo-CLI for UI/TUI (not executed)."""
    from hof.agent.sandbox.constants import HOF_BUILTIN_TERMINAL_EXEC

    raw = arguments_json or "{}"
    wire, _ = split_agent_tool_display_metadata(raw)

    if name == HOF_BUILTIN_TERMINAL_EXEC:
        return _format_terminal_exec_cli_line(wire, max_cli_line_chars)

    try:
        parsed = json.loads(wire)
        if not isinstance(parsed, dict):
            parsed = {"_": parsed}
    except json.JSONDecodeError:
        frag = wire.strip().replace("\n", " ")
        if len(frag) > 120:
            frag = frag[:117] + "…"
        return f"hof fn {name} {frag}" if frag else f"hof fn {name}"

    safe = _redact_for_cli(parsed)
    parts: list[str] = ["hof", "fn", name]
    for key in sorted(safe.keys()):
        val = safe[key]
        if val is True:
            parts.append(f"--{key}")
        elif val is False:
            parts.extend((f"--{key}", "false"))
        elif val is None:
            parts.extend((f"--{key}", "null"))
        elif isinstance(val, (dict, list)):
            parts.append(f"--{key}")
            parts.append(shlex.quote(json.dumps(val, separators=(",", ":"), ensure_ascii=False)))
        else:
            parts.append(f"--{key}")
            parts.append(shlex.quote(str(val)))
    line = " ".join(parts)
    if len(line) > max_cli_line_chars:
        line = line[: max_cli_line_chars - 1] + "…"
    return line


def summarize_tool_json(name: str, payload: str) -> str:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return payload[:400] + ("…" if len(payload) > 400 else "")
    if isinstance(data, dict) and "error" in data:
        return f"error: {data.get('error')}"
    if isinstance(data, dict) and "total" in data and "rows" in data:
        rows = data.get("rows") or []
        total = data.get("total")
        return f"{name}: {len(rows)} row(s) on this page, total={total}"
    if isinstance(data, dict) and len(data) <= 6:
        return json.dumps(data, default=str)[:500]
    text = json.dumps(data, default=str)
    return text[:600] + ("…" if len(text) > 600 else "")


def parsed_tool_result_for_stream(out_json: str) -> Any | None:
    """Parse tool JSON for UI (same payload the model sees)."""
    try:
        return json.loads(out_json)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def execute_tool(
    name: str,
    arguments_json: str,
    allowlist: frozenset[str],
    *,
    max_tool_output_chars: int,
    run_id: str | None = None,
    tool_call_id: str | None = None,
) -> tuple[str, str]:
    """Execute a tool (read or mutation). Returns (json_string_for_model, summary_for_ui)."""
    meta = registry.get_function(name)
    if meta is None or name not in allowlist:
        logger.warning(
            "agent tool skipped (not allowed): name=%s in_allowlist=%s",
            name,
            name in allowlist,
        )
        err = {"error": f"unknown or disallowed function: {name}"}
        raw = json.dumps(err)
        return raw, summarize_tool_json(name, raw)

    try:
        parsed = json.loads(arguments_json) if arguments_json else {}
        if not isinstance(parsed, dict):
            parsed = {}
    except json.JSONDecodeError as exc:
        logger.warning("agent tool bad JSON args: name=%s error=%s", name, exc)
        err = {"error": f"invalid JSON arguments: {exc}"}
        raw = json.dumps(err)
        return raw, summarize_tool_json(name, raw)

    schema = build_function_input_schema(meta)
    try:
        validated = schema(**parsed)
        kwargs = validated.model_dump(exclude_none=False)
    except ValidationError as exc:
        logger.warning(
            "agent tool validation failed: name=%s errors=%s",
            name,
            exc.errors(),
        )
        err = {"error": "validation failed", "detail": exc.errors()}
        raw = json.dumps(err, default=str)
        return raw, summarize_tool_json(name, raw)

    try:
        if meta.is_async:
            err = {"error": "async functions are not supported in the agent runner"}
            raw = json.dumps(err)
            return raw, summarize_tool_json(name, raw)
        prev_rid = getattr(_tls_tool_run_id, "run_id", None)
        prev_tid = getattr(_tls_tool_call_id, "tool_call_id", None)
        if run_id is not None:
            _tls_tool_run_id.run_id = run_id
        if tool_call_id is not None:
            _tls_tool_call_id.tool_call_id = tool_call_id
        try:
            result = meta.fn(**kwargs)
        finally:
            if run_id is not None:
                if prev_rid is not None:
                    _tls_tool_run_id.run_id = prev_rid
                elif hasattr(_tls_tool_run_id, "run_id"):
                    delattr(_tls_tool_run_id, "run_id")
            if tool_call_id is not None:
                if prev_tid is not None:
                    _tls_tool_call_id.tool_call_id = prev_tid
                elif hasattr(_tls_tool_call_id, "tool_call_id"):
                    delattr(_tls_tool_call_id, "tool_call_id")
    except Exception as exc:
        logger.exception("agent tool %s failed", name)
        err = {"error": str(exc)}
        raw = json.dumps(err)
        return raw, summarize_tool_json(name, raw)

    try:
        raw = json.dumps(result, default=str)
    except TypeError:
        raw = json.dumps({"result": repr(result)})
    truncated = len(raw) > max_tool_output_chars
    if truncated:
        raw = raw[: max_tool_output_chars - 24] + "\n…(truncated)"
    ok, code = tool_result_status_for_ui(raw)
    logger.info(
        "agent tool executed: name=%s ok=%s status_code=%s json_chars=%d truncated=%s",
        name,
        ok,
        code,
        len(raw),
        truncated,
    )
    return raw, summarize_tool_json(name, raw)


_TOOL_TRUNCATION_MARKER = "\n…(truncated)"


def _peel_terminal_exec_dict(data: dict[str, Any]) -> dict[str, Any] | None:
    """Follow ``result`` / ``data`` / string ``result`` until ``exit_code`` + ``output``."""
    cur: Any = data
    for _ in range(8):
        if not isinstance(cur, dict):
            return None
        if "exit_code" in cur and "output" in cur:
            return cur
        nxt: Any = None
        if "result" in cur:
            r = cur["result"]
            if isinstance(r, str) and r.strip().startswith("{"):
                try:
                    nxt = json.loads(r)
                except (json.JSONDecodeError, TypeError, ValueError):
                    nxt = None
            elif isinstance(r, dict):
                nxt = r
        if nxt is None and "data" in cur:
            dd = cur["data"]
            if isinstance(dd, dict):
                nxt = dd
        if nxt is not None:
            cur = nxt
            continue
        return None
    return None


def tool_result_status_for_ui(out_json: str) -> tuple[bool, int]:
    """Return (ok, http_shaped_code) for the assistant UI (not a real HTTP response)."""
    try:
        data = json.loads(out_json)
    except (json.JSONDecodeError, TypeError, ValueError):
        return False, 500

    if isinstance(data, dict) and data.get("rejected") is True:
        return False, 499

    if not isinstance(data, dict):
        return True, 200

    # Sandbox terminal: {"exit_code": int, "output": str, ...} — vacuous ``error`` (or bad
    # ok/status from upstream) must not mark success as failure. Peel HTTP/proxy wrappers.
    peeled = _peel_terminal_exec_dict(data) if isinstance(data, dict) else None
    if peeled is not None:
        try:
            ec = int(peeled["exit_code"])
        except (TypeError, ValueError):
            ec = -1
        if ec == 0:
            return True, 200
        return False, 500

    if "error" in data:
        err = str(data.get("error") or "").lower()
        if data.get("detail") is not None or "validation" in err:
            return False, 422
        if "unknown or disallowed" in err:
            return False, 403
        if "invalid json" in err:
            return False, 400
        if "async functions" in err:
            return False, 501
        return False, 500

    return True, 200


def format_tool_result_for_model(function_name: str, out_json: str) -> str:
    """Tiny prefix so the model sees server-backed, complete-vs-truncated tool payloads (~40 chars).

    Keeps the JSON body unchanged (still valid for ``parsed_tool_result_for_stream`` on the raw
    string before wrapping).
    """
    name = (function_name or "").strip() or "tool"
    status = "truncated" if _TOOL_TRUNCATION_MARKER in out_json else "complete"
    return f"[hof:{name} · {status}]\n{out_json}"
