"""Configuration for Browser Use Cloud."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

_ENV_PLACEHOLDER = re.compile(r"\$\{(\w+)\}")


def resolve_browser_api_key_value(value: str) -> str:
    """Resolve ``${VAR}`` in API key strings.

    Uses :func:`os.environ.get` (same idea as ``hof.config.Config``).

    If the value has no placeholders, it is returned stripped as-is. Missing env vars become empty
    segments (caller should treat empty result as misconfiguration).
    """

    if not value or not isinstance(value, str):
        return ""

    def replacer(match: re.Match[str]) -> str:
        v = os.environ.get(match.group(1))
        return v if v is not None else ""

    out = _ENV_PLACEHOLDER.sub(replacer, value)
    return out.strip()


@dataclass(frozen=True)
class BrowserConfig:
    """Browser Use Cloud settings.

    ``api_key`` may be a literal key or ``${BROWSER_USE_API_KEY}``; use
    :func:`resolve_browser_api_key_value` at runtime (hof-engine does this in the agent stream).
    """

    api_key: str
    default_model: str = "bu-mini"
    enable_recording: bool = True
    poll_interval_sec: float = 2.0
    task_timeout_sec: float = 14_400.0
    http_timeout_sec: float = 120.0
    #: Keys to list in the system prompt (e.g. app constant names). End-users map values via
    #: ``browser_sensitive_data_fn``; the model references ``<secret:key>`` in tasks.
    sensitive_keys_for_prompt: tuple[str, ...] = ()
    #: When ``True`` (default), ``hof_builtin_browse_web`` is exposed on the
    #: parent agent's tool list whenever this config is attached to the policy.
    #: Set ``False`` for "router" parent agents that should delegate live web
    #: browsing to a sub-agent (the sub-agent attaches its own
    #: :class:`BrowserConfig` with ``expose_to_parent=True`` so it can browse
    #: directly). Affects both
    #: :meth:`hof.agent.policy.AgentPolicy.effective_allowlist` and
    #: :meth:`hof.agent.policy.AgentPolicy.skills_catalog_allowlist`.
    expose_to_parent: bool = True
