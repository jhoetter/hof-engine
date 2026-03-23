"""OpenAI tool specs, CLI formatting, and registry-backed tool execution."""

from __future__ import annotations

import json
import logging
import shlex
from typing import Any

from pydantic import ValidationError

from hof.core.registry import registry
from hof.db.schemas import build_function_input_schema

logger = logging.getLogger(__name__)

_REDACT_SUBSTRINGS = ("token", "password", "secret", "api_key", "authorization")


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
                    "description": (meta.description or name)[:900],
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
