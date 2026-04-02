"""Sandbox / terminal configuration.

All settings can be set on :class:`SandboxConfig` in ``configure_agent(AgentPolicy(...))``.
``HOF_SANDBOX_*`` environment variables are **optional** overrides for deployments that prefer
config without code changes; nothing is required if sandbox stays disabled (default) or you
set fields in code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import Any


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_str(key: str, default: str) -> str:
    raw = os.environ.get(key, "").strip()
    return raw if raw else default


def _env_opt_str(key: str) -> str | None:
    raw = os.environ.get(key, "").strip()
    return raw if raw else None


@dataclass(frozen=True)
class SandboxConfig:
    """Docker terminal pool + exec limits. Used when ``AgentPolicy.sandbox`` is set."""

    enabled: bool = False
    terminal_only_dispatch: bool = False
    image: str = "hof-skill-base:latest"
    pool_size: int = 3
    pool_max_idle_sec: int = 600
    max_exec_timeout_sec: int = 30
    max_output_chars: int = 32_768
    memory_limit: str = "512m"
    cpu_period: int = 100_000
    cpu_quota: int = 100_000
    network_mode: str = "bridge"
    s3_workspace_prefix: str | None = None
    api_base_url: str = ""
    api_token: str = ""
    builtins_when_terminal_only: frozenset[str] = field(default_factory=frozenset)

    def with_env_overrides(self) -> SandboxConfig:
        """Return a copy with ``HOF_SANDBOX_*`` environment variables applied."""
        enabled = _env_bool("HOF_SANDBOX_ENABLED", self.enabled)
        terminal_only = _env_bool("HOF_SANDBOX_TERMINAL_ONLY", self.terminal_only_dispatch)
        raw_builtins = os.environ.get("HOF_SANDBOX_BUILTINS", "").strip()
        builtins: frozenset[str] = self.builtins_when_terminal_only
        if raw_builtins:
            parts = {p.strip() for p in raw_builtins.replace(",", " ").split() if p.strip()}
            builtins = frozenset(parts)

        return replace(
            self,
            enabled=enabled,
            terminal_only_dispatch=terminal_only,
            image=_env_str("HOF_SANDBOX_IMAGE", self.image),
            pool_size=_env_int("HOF_SANDBOX_POOL_SIZE", self.pool_size),
            pool_max_idle_sec=_env_int("HOF_SANDBOX_POOL_MAX_IDLE_SEC", self.pool_max_idle_sec),
            max_exec_timeout_sec=_env_int(
                "HOF_SANDBOX_MAX_EXEC_TIMEOUT_SEC",
                self.max_exec_timeout_sec,
            ),
            max_output_chars=_env_int("HOF_SANDBOX_MAX_OUTPUT_CHARS", self.max_output_chars),
            memory_limit=_env_str("HOF_SANDBOX_MEMORY_LIMIT", self.memory_limit),
            cpu_period=_env_int("HOF_SANDBOX_CPU_PERIOD", self.cpu_period),
            cpu_quota=_env_int("HOF_SANDBOX_CPU_QUOTA", self.cpu_quota),
            network_mode=_env_str("HOF_SANDBOX_NETWORK_MODE", self.network_mode),
            s3_workspace_prefix=_env_opt_str("HOF_SANDBOX_S3_PREFIX") or self.s3_workspace_prefix,
            api_base_url=_env_str("HOF_SANDBOX_API_BASE_URL", self.api_base_url or ""),
            api_token=_env_str("HOF_SANDBOX_API_TOKEN", self.api_token or ""),
            builtins_when_terminal_only=builtins,
        )


def merge_sandbox_config(
    base: SandboxConfig | None,
    overrides: dict[str, Any] | None,
) -> SandboxConfig | None:
    """Shallow-merge dict into SandboxConfig (for tests / programmatic setup)."""
    if base is None:
        return None
    if not overrides:
        return base.with_env_overrides()
    data: dict[str, Any] = {}
    for k, v in overrides.items():
        if hasattr(base, k):
            data[k] = v
    merged = replace(base, **data) if data else base
    return merged.with_env_overrides()
