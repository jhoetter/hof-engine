"""Persist web session metadata for API + canvas (Redis or in-process)."""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_WEB_SESSION_TTL_SEC = 172_800  # 48h — align with inbox review barrier
_KEY = "hof:web_session:{session_id}"
_WEB_SESSIONS_INDEX_KEY = "hof:web_sessions:index"
_MAX_INDEX_IDS = 100
_web_redis = None
_web_memory: dict[str, tuple[float, str]] = {}
_web_lock = threading.Lock()


def _redis():
    global _web_redis
    if _web_redis is False:
        return None
    if _web_redis is not None:
        return _web_redis
    try:
        import os

        import redis
    except ImportError:
        _web_redis = False
        return None
    url = (os.environ.get("REDIS_URL") or "").strip()
    if not url:
        _web_redis = False
        return None
    try:
        _web_redis = redis.Redis.from_url(url, decode_responses=True)
    except Exception as exc:
        logger.warning("web session store: Redis unavailable: %s", exc)
        _web_redis = False
        return None
    return _web_redis


def _prune_memory(now: float) -> None:
    dead = [k for k, (exp, _) in _web_memory.items() if exp <= now]
    for k in dead:
        del _web_memory[k]


def save_web_session(session_id: str, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, default=str)
    sid = session_id.strip()
    r = _redis()
    ttl = max(300, int(_WEB_SESSION_TTL_SEC))
    if r is not None:
        r.setex(_KEY.format(session_id=sid), ttl, raw)
        try:
            # One index entry per session: every poll calls save_web_session again; without
            # LREM the same id is LPUSHed repeatedly and the list shows duplicates.
            r.lrem(_WEB_SESSIONS_INDEX_KEY, 0, sid)
            r.lpush(_WEB_SESSIONS_INDEX_KEY, sid)
            r.ltrim(_WEB_SESSIONS_INDEX_KEY, 0, _MAX_INDEX_IDS - 1)
            r.expire(_WEB_SESSIONS_INDEX_KEY, ttl)
        except Exception:
            logger.debug("web session index lpush failed", exc_info=True)
        return
    now = time.monotonic()
    with _web_lock:
        _prune_memory(now)
        _web_memory[sid] = (now + float(ttl), raw)


def load_web_session(session_id: str) -> dict[str, Any] | None:
    sid = session_id.strip()
    r = _redis()
    raw: str | None
    if r is not None:
        raw = r.get(_KEY.format(session_id=sid))
    else:
        now = time.monotonic()
        with _web_lock:
            _prune_memory(now)
            tup = _web_memory.get(sid)
            if not tup:
                raw = None
            else:
                exp, val = tup
                if exp <= now:
                    del _web_memory[sid]
                    raw = None
                else:
                    raw = val
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def list_recent_web_session_ids(limit: int = 100) -> list[str]:
    """Recent session ids (Redis list order: newest first). Empty if no Redis."""
    lim = max(1, min(int(limit), _MAX_INDEX_IDS))
    r = _redis()
    if r is None:
        return []
    try:
        raw = r.lrange(_WEB_SESSIONS_INDEX_KEY, 0, lim - 1)
    except Exception:
        logger.debug("web session index lrange failed", exc_info=True)
        return []
    out: list[str] = []
    seen: set[str] = set()
    for x in raw or []:
        s = str(x).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def append_web_session_message(session_id: str, message: dict[str, Any]) -> None:
    prev = load_web_session(session_id) or {}
    msgs = prev.get("messages")
    if not isinstance(msgs, list):
        msgs = []
    msgs.append(message)
    prev["messages"] = msgs
    save_web_session(session_id, prev)
