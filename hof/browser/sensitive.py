"""Resolve app-level secrets for Browser Use ``sensitiveData``."""

from __future__ import annotations

import asyncio

from hof.agent.policy import AgentPolicy


def resolve_sensitive_data_sync(
    policy: AgentPolicy,
    sensitive_keys: list[str] | None,
) -> dict[str, str]:
    """Call ``policy.browser_sensitive_data_fn`` (async) from sync agent stream context."""
    fn = policy.browser_sensitive_data_fn
    if fn is None:
        return {}

    async def _load() -> dict[str, str]:
        raw = await fn()
        if not isinstance(raw, dict):
            return {}
        out: dict[str, str] = {}
        for k, v in raw.items():
            ks = str(k).strip()
            if not ks:
                continue
            out[ks] = str(v) if v is not None else ""
        return out

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        full = asyncio.run(_load())
    else:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            full = pool.submit(asyncio.run, _load()).result()

    if not sensitive_keys:
        return full

    sk = {str(k).strip() for k in sensitive_keys if k and str(k).strip()}
    return {k: full[k] for k in sk if k in full}
