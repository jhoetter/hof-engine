"""OpenAI tool specs, CLI formatting, and registry-backed tool execution."""

from __future__ import annotations

import json
import logging
import shlex
from typing import Any

from pydantic import ValidationError

from hof.core.registry import registry
from hof.db.schemas import build_function_input_schema
from hof.functions import FunctionMetadata

logger = logging.getLogger(__name__)

_REDACT_SUBSTRINGS = ("token", "password", "secret", "api_key", "authorization")

# OpenAI and other providers accept long descriptions; keep a hard cap for stability.
AGENT_TOOL_DESCRIPTION_MAX_CHARS = 2000


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


def format_cli_line(name: str, arguments_json: str, *, max_cli_line_chars: int) -> str:
    """Human-readable pseudo-CLI for UI/TUI (not executed)."""
    raw = arguments_json or "{}"
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            parsed = {"_": parsed}
    except json.JSONDecodeError:
        frag = raw.strip().replace("\n", " ")
        if len(frag) > 120:
            frag = frag[:117] + "…"
        return f"hof fn {name} {frag}" if frag else f"hof fn {name}"

    safe = _redact_for_cli(parsed)
    parts: list[str] = ["hof", "fn", name]
    nested = False
    for key in sorted(safe.keys()):
        val = safe[key]
        if isinstance(val, (dict, list)):
            nested = True
            break
        if val is True:
            parts.append(f"--{key}")
        elif val is False:
            parts.extend((f"--{key}", "false"))
        elif val is None:
            parts.extend((f"--{key}", "null"))
        else:
            parts.append(f"--{key}")
            parts.append(shlex.quote(str(val)))
    if nested:
        compact = json.dumps(safe, separators=(",", ":"), ensure_ascii=False)
        line = f"POST /api/functions/{name} {compact}"
    else:
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
) -> tuple[str, str]:
    """Execute a tool (read or mutation). Returns (json_string_for_model, summary_for_ui)."""
    meta = registry.get_function(name)
    if meta is None or name not in allowlist:
        err = {"error": f"unknown or disallowed function: {name}"}
        raw = json.dumps(err)
        return raw, summarize_tool_json(name, raw)

    try:
        parsed = json.loads(arguments_json) if arguments_json else {}
        if not isinstance(parsed, dict):
            parsed = {}
    except json.JSONDecodeError as exc:
        err = {"error": f"invalid JSON arguments: {exc}"}
        raw = json.dumps(err)
        return raw, summarize_tool_json(name, raw)

    schema = build_function_input_schema(meta)
    try:
        validated = schema(**parsed)
        kwargs = validated.model_dump(exclude_none=False)
    except ValidationError as exc:
        err = {"error": "validation failed", "detail": exc.errors()}
        raw = json.dumps(err, default=str)
        return raw, summarize_tool_json(name, raw)

    try:
        if meta.is_async:
            err = {"error": "async functions are not supported in the agent runner"}
            raw = json.dumps(err)
            return raw, summarize_tool_json(name, raw)
        result = meta.fn(**kwargs)
    except Exception as exc:
        logger.exception("agent tool %s failed", name)
        err = {"error": str(exc)}
        raw = json.dumps(err)
        return raw, summarize_tool_json(name, raw)

    try:
        raw = json.dumps(result, default=str)
    except TypeError:
        raw = json.dumps({"result": repr(result)})
    if len(raw) > max_tool_output_chars:
        raw = raw[: max_tool_output_chars - 24] + "\n…(truncated)"
    return raw, summarize_tool_json(name, raw)


_TOOL_TRUNCATION_MARKER = "\n…(truncated)"


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
