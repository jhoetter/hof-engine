"""Built-in read-only agent tools.

Registered when ``discover_all`` finishes so app ``@function`` modules load first; reserved
``hof_builtin_*`` names then win on collision. Always on ``AgentPolicy.effective_allowlist()``.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import math
import os
import platform
import socket
import statistics
from datetime import UTC, datetime
from numbers import Real
from typing import Any
from urllib.parse import ParseResult, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from simpleeval import (
    EvalWithCompoundTypes,
    FeatureNotAvailable,
    InvalidExpression,
    IterableTooLong,
)

from hof.functions import function

logger = logging.getLogger(__name__)

_DEFAULT_FETCH_MAX_BYTES = 512 * 1024
_HARD_FETCH_MAX_BYTES = 2 * 1024 * 1024
_DEFAULT_FETCH_TIMEOUT = 15.0

_DEFAULT_CALC_MAX_EXPRESSION_CHARS = 4096
_HARD_CALC_MAX_EXPRESSION_CHARS = 64_000
_DEFAULT_CALC_MAX_VALUES = 10_000
_HARD_CALC_MAX_VALUES = 50_000
_DEFAULT_CALC_MAX_BATCH_EXPRESSIONS = 200
_HARD_CALC_MAX_BATCH_EXPRESSIONS = 1000

_AGGREGATE_OPS: frozenset[str] = frozenset(
    {"sum", "mean", "min", "max", "median", "product", "count"},
)


def _fetch_max_bytes() -> int:
    raw = os.environ.get("HOF_AGENT_FETCH_MAX_BYTES", "").strip()
    if not raw:
        return _DEFAULT_FETCH_MAX_BYTES
    try:
        n = int(raw)
    except ValueError:
        return _DEFAULT_FETCH_MAX_BYTES
    return max(1024, min(n, _HARD_FETCH_MAX_BYTES))


def _fetch_timeout() -> float:
    raw = os.environ.get("HOF_AGENT_FETCH_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return _DEFAULT_FETCH_TIMEOUT
    try:
        t = float(raw)
    except ValueError:
        return _DEFAULT_FETCH_TIMEOUT
    return max(1.0, min(t, 120.0))


def _localhost_http_hosts() -> frozenset[str]:
    return frozenset({"localhost", "127.0.0.1", "::1"})


def _ip_allowed_for_fetch(
    parsed: ParseResult,
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    if parsed.scheme == "https":
        return bool(ip.is_global)
    host = (parsed.hostname or "").strip().lower()
    if parsed.scheme == "http" and host in _localhost_http_hosts():
        return bool(ip.is_loopback)
    return False


def _url_host_ips_allowed(url: str) -> tuple[bool, str | None]:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False, "only http and https URLs are allowed"
    if not parsed.netloc or parsed.hostname is None:
        return False, "missing host"
    if any(c in url for c in ("\n", "\r", "\0")):
        return False, "invalid URL"
    host = parsed.hostname.strip().lower()
    if parsed.scheme == "http" and host not in _localhost_http_hosts():
        return False, "http is only allowed for localhost (use https elsewhere)"
    try:
        infos = socket.getaddrinfo(parsed.hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        return False, f"dns resolution failed: {exc}"
    seen: set[str] = set()
    for info in infos:
        ip_str = info[4][0]
        if ip_str in seen:
            continue
        seen.add(ip_str)
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False, f"could not parse resolved address: {ip_str}"
        if not _ip_allowed_for_fetch(parsed, ip):
            if parsed.scheme == "https":
                reason = "non-public IP blocked (SSRF)"
            else:
                reason = "non-loopback IP blocked"
            return False, f"{reason}: {ip_str}"
    if not seen:
        return False, "no addresses for host"
    return True, None


def _read_body_limited(response: httpx.Response, max_bytes: int) -> tuple[str, bool]:
    buf = bytearray()
    truncated = False
    for chunk in response.iter_bytes():
        if not chunk:
            continue
        remain = max_bytes - len(buf)
        if remain <= 0:
            truncated = True
            break
        if len(chunk) <= remain:
            buf.extend(chunk)
        else:
            buf.extend(chunk[:remain])
            truncated = True
            break
    text = bytes(buf).decode("utf-8", errors="replace")
    return text, truncated


@function(
    name="hof_builtin_server_time",
    tool_summary="Current server time (UTC, local ISO, unix); optional IANA timezone.",
    when_to_use="When the user asks what time or date it is, deadlines relative to today, or "
    "timezone-specific scheduling.",
    when_not_to_use="When the question is purely about app data with no calendar/time context.",
)
def hof_builtin_server_time(iana_timezone: str | None = None) -> dict[str, Any]:
    now = datetime.now(UTC)
    out: dict[str, Any] = {
        "utc_iso": now.isoformat().replace("+00:00", "Z"),
        "unix_utc": int(now.timestamp()),
    }
    local = datetime.now().astimezone()
    out["server_local_iso"] = local.isoformat()
    tz = (iana_timezone or "").strip()
    if tz:
        try:
            z = ZoneInfo(tz)
            out["requested_timezone"] = tz
            out["requested_zone_iso"] = datetime.now(z).isoformat()
        except ZoneInfoNotFoundError:
            out["requested_timezone"] = tz
            out["timezone_error"] = "unknown IANA timezone"
    return out


@function(
    name="hof_builtin_runtime_info",
    tool_summary="Process environment identity: host, platform, Python, hof-engine version.",
    when_to_use="Debugging deploy/environment issues or confirming which stack is running.",
    when_not_to_use="For business or tenant data; use domain-specific list/get tools instead.",
)
def hof_builtin_runtime_info() -> dict[str, Any]:
    from importlib.metadata import PackageNotFoundError, version

    try:
        he_ver = version("hof-engine")
    except PackageNotFoundError:
        he_ver = "unknown"

    out: dict[str, Any] = {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "hof_engine_version": he_ver,
    }
    try:
        from hof.config import get_config

        cfg = get_config()
        out["app_name"] = getattr(cfg, "app_name", "") or ""
    except Exception:
        logger.debug("builtin runtime_info: get_config unavailable", exc_info=True)
    return out


@function(
    name="hof_builtin_http_get",
    tool_summary="Fetch a public HTTPS URL (GET); body truncated; SSRF-safe.",
    when_to_use=(
        "When the user needs a small public web page or API JSON and no domain tool exists."
    ),
    when_not_to_use="For internal services, file://, or large downloads; never for secrets or "
    "credentials in URLs.",
)
def hof_builtin_http_get(url: str, max_chars: int | None = None) -> dict[str, Any]:
    raw_url = (url or "").strip()
    if not raw_url:
        return {"error": "url is required"}

    ok, err = _url_host_ips_allowed(raw_url)
    if not ok:
        return {"error": err or "url not allowed"}

    max_bytes = _fetch_max_bytes()
    if max_chars is not None:
        try:
            mc = int(max_chars)
        except (TypeError, ValueError):
            mc = max_bytes
        max_bytes = max(256, min(mc, _HARD_FETCH_MAX_BYTES))

    timeout = _fetch_timeout()
    headers = {"User-Agent": "hof-engine-agent-fetch/1.0"}

    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            with client.stream("GET", raw_url, headers=headers) as resp:
                text, truncated = _read_body_limited(resp, max_bytes)
                out: dict[str, Any] = {
                    "url": raw_url,
                    "status_code": resp.status_code,
                    "content_type": resp.headers.get("content-type", ""),
                    "text": text,
                    "truncated": truncated,
                }
                return out
    except httpx.HTTPError as exc:
        return {"error": str(exc), "url": raw_url}


def _calc_max_expression_chars() -> int:
    raw = os.environ.get("HOF_AGENT_CALC_MAX_EXPRESSION_CHARS", "").strip()
    if not raw:
        return _DEFAULT_CALC_MAX_EXPRESSION_CHARS
    try:
        n = int(raw)
    except ValueError:
        return _DEFAULT_CALC_MAX_EXPRESSION_CHARS
    return max(16, min(n, _HARD_CALC_MAX_EXPRESSION_CHARS))


def _calc_max_values() -> int:
    raw = os.environ.get("HOF_AGENT_CALC_MAX_VALUES", "").strip()
    if not raw:
        return _DEFAULT_CALC_MAX_VALUES
    try:
        n = int(raw)
    except ValueError:
        return _DEFAULT_CALC_MAX_VALUES
    return max(1, min(n, _HARD_CALC_MAX_VALUES))


def _calc_max_batch_expressions() -> int:
    raw = os.environ.get("HOF_AGENT_CALC_MAX_BATCH_EXPRESSIONS", "").strip()
    if not raw:
        return _DEFAULT_CALC_MAX_BATCH_EXPRESSIONS
    try:
        n = int(raw)
    except ValueError:
        return _DEFAULT_CALC_MAX_BATCH_EXPRESSIONS
    return max(1, min(n, _HARD_CALC_MAX_BATCH_EXPRESSIONS))


def _parse_operations_input(raw: Any) -> tuple[list[str] | None, str | None]:
    """Parse plural `operations`: list, JSON array string, or comma-separated names."""
    if raw is None:
        return [], None
    if isinstance(raw, list):
        out = [str(x).strip().lower() for x in raw if str(x).strip()]
        return out, None
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return [], None
        try:
            decoded = json.loads(s)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, list):
            return [str(x).strip().lower() for x in decoded if str(x).strip()], None
        if decoded is not None:
            return None, "operations JSON must be an array of strings"
        return [p.strip().lower() for p in s.split(",") if p.strip()], None
    return None, f"operations must be a list or string, not {type(raw).__name__}"


def _merge_aggregate_operation_names(
    singular: str,
    plural_raw: Any,
) -> tuple[list[str] | None, str | None]:
    """Plural ops first (deduped), then singular if not already present."""
    extra, err = _parse_operations_input(plural_raw)
    if err:
        return None, err
    seen: set[str] = set()
    merged: list[str] = []
    for o in extra:
        if o not in seen:
            seen.add(o)
            merged.append(o)
    one = (singular or "").strip().lower()
    if one and one not in seen:
        merged.append(one)
    return merged, None


def _parse_expressions_list(raw: Any) -> tuple[list[str] | None, str | None]:
    if raw is None:
        return None, None
    if isinstance(raw, list):
        return [str(x) for x in raw], None
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return [], None
        try:
            decoded = json.loads(s)
        except json.JSONDecodeError as exc:
            return None, f"expressions must be a JSON array of strings: {exc}"
        if not isinstance(decoded, list):
            return None, "expressions JSON must be an array of strings"
        return [str(x) for x in decoded], None
    return None, f"expressions must be a list or string, not {type(raw).__name__}"


def _parse_values_input(raw: Any) -> tuple[list[Any] | None, str | None]:
    """Turn API/tool payloads into a list: real arrays, stringified JSON, CSV, or a scalar."""
    if raw is None:
        return None, None
    if isinstance(raw, bool):
        return None, "values must be a list, string of numbers, or a single number, not boolean"
    if isinstance(raw, Real):
        return [raw], None
    if isinstance(raw, tuple):
        return list(raw), None
    if isinstance(raw, list):
        return raw, None
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None, "values string is empty"
        try:
            decoded = json.loads(s)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, list):
            return decoded, None
        if isinstance(decoded, bool):
            return None, "parsed JSON must be an array of numbers, not a boolean"
        if isinstance(decoded, Real):
            return [decoded], None
        if decoded is not None:
            return None, "values JSON must be an array of numbers"
        parts = [p.strip() for p in s.split(",") if p.strip()]
        if not parts:
            return None, "could not parse values as a list of numbers"
        return parts, None
    return None, f"values must be a list, tuple, string, or number, not {type(raw).__name__}"


def _normalize_agg_values(values: list[Any]) -> tuple[list[float] | None, str | None]:
    out: list[float] = []
    for i, v in enumerate(values):
        if isinstance(v, bool):
            return None, f"values[{i}] must be a number, not boolean"
        if isinstance(v, Real):
            out.append(float(v))
            continue
        if isinstance(v, str):
            t = v.strip()
            if not t:
                return None, f"values[{i}] is empty"
            try:
                out.append(float(t))
            except ValueError:
                return None, f"values[{i}] is not a valid number: {t!r}"
            continue
        return None, f"values[{i}] must be a number"
    return out, None


def _single_aggregate_result(nums: list[float], operation: str) -> tuple[Any, str | None]:
    op = (operation or "").strip().lower()
    if op not in _AGGREGATE_OPS:
        allowed = ", ".join(sorted(_AGGREGATE_OPS))
        return None, f"unknown operation {operation!r}; allowed: {allowed}"
    n = len(nums)
    if op == "count":
        return n, None
    if op == "sum":
        return sum(nums), None
    if op == "product":
        return math.prod(nums), None
    if n == 0 and op in ("mean", "median", "min", "max"):
        return None, f"{op} requires at least one value"
    if op == "mean":
        return statistics.mean(nums), None
    if op == "median":
        return statistics.median(nums), None
    if op == "min":
        return min(nums), None
    if op == "max":
        return max(nums), None
    return None, "internal aggregate error"


def _run_aggregate(nums: list[float], operation: str) -> dict[str, Any]:
    val, err = _single_aggregate_result(nums, operation)
    if err:
        return {"error": err}
    op = (operation or "").strip().lower()
    return {"mode": "aggregate", "operation": op, "result": val}


def _run_multi_aggregate(nums: list[float], operations: list[str]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for op in operations:
        val, err = _single_aggregate_result(nums, op)
        if err:
            results[op] = {"error": err}
        else:
            results[op] = val
    return {"mode": "aggregate", "results": results}


_calc_evaluator: EvalWithCompoundTypes | None = None


def _get_calc_evaluator() -> EvalWithCompoundTypes:
    global _calc_evaluator
    if _calc_evaluator is None:
        safe_names = {"True": True, "False": False, "None": None, "pi": math.pi, "e": math.e}
        safe_functions = {
            "int": int,
            "float": float,
            "abs": abs,
            "round": round,
            "min": min,
            "max": max,
            "sum": sum,
            "pow": pow,
            "sqrt": math.sqrt,
            "floor": math.floor,
            "ceil": math.ceil,
        }
        _calc_evaluator = EvalWithCompoundTypes(functions=safe_functions, names=safe_names)
    return _calc_evaluator


@function(
    name="hof_builtin_calculate",
    tool_summary="Numeric math: safe expression evaluation or list aggregates (sum, mean, …).",
    when_to_use="For any non-trivial arithmetic, percentages, totals, averages, or stats over "
    "numbers. Prefer this over mental math. For a table column, extract numbers once and pass "
    "`values` with `operation` (one stat) or `operations` (several stats in one call: e.g. sum, "
    "mean, min); avoid one tool call per row unless you truly need per-row formulas. `values` "
    "accepts a JSON array, stringified JSON array, comma-separated numbers, numeric strings in "
    "the array, or a single number. Use `expression` for a single formula, or `expressions` for "
    "many formulas in one round-trip (mutually exclusive with `values`). If both `values` and "
    "`expression` are sent, `values`+aggregate wins.",
    when_not_to_use="General code execution, text processing, or business data lookups — use "
    "domain tools instead.",
)
def hof_builtin_calculate(
    expression: str | None = None,
    values: list[Any] | None = None,
    operation: str | None = None,
    operations: list[Any] | None = None,
    expressions: list[Any] | None = None,
) -> dict[str, Any]:
    expr_raw = (expression or "").strip()
    op_raw = (operation or "").strip()

    expr_batch, ebatch_err = _parse_expressions_list(expressions)
    if ebatch_err:
        return {"error": ebatch_err}
    batch_mode = expressions is not None

    if batch_mode and values is not None:
        return {"error": "cannot combine values with expressions; use one mode only"}

    if batch_mode and expr_raw:
        return {"error": "cannot combine expression with expressions; use one mode only"}

    if batch_mode:
        if not expr_batch:
            return {"error": "expressions must contain at least one expression"}
        max_batch = _calc_max_batch_expressions()
        if len(expr_batch) > max_batch:
            return {"error": f"at most {max_batch} expressions allowed in one call"}
        max_chars = _calc_max_expression_chars()
        ev = _get_calc_evaluator()
        items: list[dict[str, Any]] = []
        for i, ex in enumerate(expr_batch):
            ex_stripped = ex.strip()
            entry: dict[str, Any] = {"index": i}
            if len(ex_stripped) > max_chars:
                entry["error"] = f"expression exceeds max length ({max_chars} characters)"
                items.append(entry)
                continue
            if not ex_stripped:
                entry["error"] = "expression is empty"
                items.append(entry)
                continue
            try:
                entry["result"] = ev.eval(ex_stripped)
            except ZeroDivisionError as exc:
                entry["error"] = f"division by zero: {exc}"
            except (InvalidExpression, FeatureNotAvailable, IterableTooLong) as exc:
                entry["error"] = str(exc)
            except (TypeError, ValueError, OverflowError) as exc:
                entry["error"] = str(exc)
            except Exception as exc:
                logger.exception("hof_builtin_calculate batch expression failed")
                entry["error"] = str(exc)
            items.append(entry)
        return {"mode": "batch_expression", "results": items}

    if values is not None:
        merged_ops, merr = _merge_aggregate_operation_names(op_raw, operations)
        if merr:
            return {"error": merr}
        if not merged_ops:
            return {"error": "operation or operations is required when values is provided"}
        parsed, perr = _parse_values_input(values)
        if perr:
            return {"error": perr}
        assert parsed is not None
        max_n = _calc_max_values()
        if len(parsed) > max_n:
            return {"error": f"at most {max_n} values allowed"}
        nums, verr = _normalize_agg_values(parsed)
        if verr:
            return {"error": verr}
        assert nums is not None
        if len(merged_ops) == 1:
            out = _run_aggregate(nums, merged_ops[0])
        else:
            out = _run_multi_aggregate(nums, merged_ops)
        if expr_raw:
            out["ignored_expression"] = True
        return out

    if not expr_raw:
        return {
            "error": ("provide expression, expressions, or values with operation/operations"),
        }

    max_chars = _calc_max_expression_chars()
    if len(expr_raw) > max_chars:
        return {"error": f"expression exceeds max length ({max_chars} characters)"}

    ev = _get_calc_evaluator()
    try:
        result = ev.eval(expr_raw)
    except ZeroDivisionError as exc:
        return {"error": f"division by zero: {exc}"}
    except (InvalidExpression, FeatureNotAvailable, IterableTooLong) as exc:
        return {"error": str(exc)}
    except (TypeError, ValueError, OverflowError) as exc:
        return {"error": str(exc)}
    except Exception as exc:
        logger.exception("hof_builtin_calculate expression failed")
        return {"error": str(exc)}

    return {"mode": "expression", "result": result}


@function(
    name="hof_builtin_present_plan",
    tool_summary=(
        "Present a structured plan to the user for review and approval. "
        "After calling this tool, STOP — do not write any assistant text."
    ),
    when_to_use=(
        "When you have enough context to propose a concrete plan. "
        "Call with title, description, and steps."
    ),
    when_not_to_use=(
        "When you still need clarification from the user — "
        "use hof_builtin_present_plan_clarification instead."
    ),
)
def hof_builtin_present_plan(
    title: str, description: str, steps: list,
) -> dict[str, Any]:
    """Intercepted by the stream loop; this body is never reached.

    Validated server-side via :class:`~hof.agent.plan_types.PlanProposal`.
    ``steps``: list of ``{label: str}`` objects.
    """
    return {"status": "intercepted"}


@function(
    name="hof_builtin_present_plan_clarification",
    tool_summary=(
        "Show the user multiple-choice clarification questions during plan discovery. "
        "The UI renders each question as a card with selectable options. "
        "After calling this tool, STOP — do not write any assistant text."
    ),
    when_to_use=(
        "In plan discovery, call this **after** your first exploration summary, whenever "
        "the work could be scoped or delivered in more than one way. "
        "Fill `questions` with 2–5 items (scope, format, timeframe, filters, priorities). "
        "Use exploration tool results to write **specific** option labels. "
        "Then STOP (no assistant text after the tool call)."
    ),
    when_not_to_use=(
        "Use `hof_builtin_present_plan` instead once clarification answers are already in the "
        "thread and you are ready to output the structured plan proposal."
    ),
)
def hof_builtin_present_plan_clarification(questions: list) -> dict[str, Any]:
    """Intercepted by the stream loop; this body is never reached.

    ``questions`` is validated server-side via
    :class:`~hof.agent.plan_types.PlanClarificationQuestion`.
    Required shape: ``{id, prompt, options: [{id, label, is_other?}], allow_multiple}``.
    ``key``/``label``/``hint`` are accepted as aliases for ``id``/``prompt``.
    ``options`` (at least 2) is **required** — omitting it causes a validation
    error returned to the model so it can retry with correct choices.
    If no option has ``is_other: true``, the server appends ``Other / specify``.
    """
    return {"status": "intercepted"}


@function(
    name="hof_builtin_update_plan_todo_state",
    tool_summary="Mark plan checklist items as completed during plan execution.",
    when_to_use="After completing one or more steps in the approved plan, call this "
    "with the 0-based indices of the finished items.",
    when_not_to_use="Outside plan execution mode.",
)
def hof_builtin_update_plan_todo_state(done_indices: list) -> dict[str, Any]:
    raw = done_indices or []
    idxs: list[int] = []
    for x in raw:
        try:
            idxs.append(int(x))
        except (TypeError, ValueError):
            continue
    return {"done_indices": idxs}
