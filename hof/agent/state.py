"""Run and pending-mutation persistence for the Hof agent (Redis or in-process)."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_AGENT_STATE_TTL_SEC = 900
_AGENT_KEY_RUN = "hof:agent_run:{run_id}"
_AGENT_KEY_PENDING = "hof:agent_pending:{pending_id}"
_agent_state_lock = threading.Lock()
_agent_memory_runs: dict[str, tuple[float, str]] = {}
_agent_memory_pending: dict[str, tuple[float, str]] = {}


def _agent_prune_memory(store: dict[str, tuple[float, str]], now: float) -> None:
    dead = [k for k, (exp, _) in store.items() if exp <= now]
    for k in dead:
        del store[k]


def _agent_memory_set(store: dict[str, tuple[float, str]], key: str, raw: str) -> None:
    now = time.monotonic()
    with _agent_state_lock:
        _agent_prune_memory(store, now)
        store[key] = (now + _AGENT_STATE_TTL_SEC, raw)


def _agent_memory_get(store: dict[str, tuple[float, str]], key: str) -> str | None:
    now = time.monotonic()
    with _agent_state_lock:
        _agent_prune_memory(store, now)
        tup = store.get(key)
        if not tup:
            return None
        exp, raw = tup
        if exp <= now:
            del store[key]
            return None
        return raw


def _agent_memory_delete(store: dict[str, tuple[float, str]], key: str) -> None:
    with _agent_state_lock:
        store.pop(key, None)


def _agent_redis_client():  # pragma: no cover - optional
    try:
        import redis
    except ImportError:
        return None
    url = os.environ.get("REDIS_URL", "").strip()
    if not url:
        return None
    try:
        return redis.Redis.from_url(url, decode_responses=True)
    except Exception as exc:
        logger.warning("agent state: Redis URL invalid or unreachable: %s", exc)
        return None


_agent_redis = _agent_redis_client()
if _agent_redis is None:
    logger.info(
        "agent state: in-memory store (set REDIS_URL for multi-worker-safe mutation confirmation)",
    )


def save_agent_run(run_id: str, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, default=str)
    rid = run_id.strip()
    if _agent_redis is not None:
        _agent_redis.setex(_AGENT_KEY_RUN.format(run_id=rid), _AGENT_STATE_TTL_SEC, raw)
        return
    _agent_memory_set(_agent_memory_runs, rid, raw)


def load_agent_run(run_id: str) -> dict[str, Any] | None:
    rid = run_id.strip()
    raw: str | None
    if _agent_redis is not None:
        raw = _agent_redis.get(_AGENT_KEY_RUN.format(run_id=rid))
    else:
        raw = _agent_memory_get(_agent_memory_runs, rid)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def delete_agent_run(run_id: str) -> None:
    rid = run_id.strip()
    if _agent_redis is not None:
        _agent_redis.delete(_AGENT_KEY_RUN.format(run_id=rid))
        return
    _agent_memory_delete(_agent_memory_runs, rid)


def save_pending(pending_id: str, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, default=str)
    pid = pending_id.strip()
    if _agent_redis is not None:
        _agent_redis.setex(_AGENT_KEY_PENDING.format(pending_id=pid), _AGENT_STATE_TTL_SEC, raw)
        return
    _agent_memory_set(_agent_memory_pending, pid, raw)


def load_pending(pending_id: str) -> dict[str, Any] | None:
    pid = pending_id.strip()
    raw: str | None
    if _agent_redis is not None:
        raw = _agent_redis.get(_AGENT_KEY_PENDING.format(pending_id=pid))
    else:
        raw = _agent_memory_get(_agent_memory_pending, pid)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def delete_pending(pending_id: str) -> None:
    pid = pending_id.strip()
    if _agent_redis is not None:
        _agent_redis.delete(_AGENT_KEY_PENDING.format(pending_id=pid))
        return
    _agent_memory_delete(_agent_memory_pending, pid)
