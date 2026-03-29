"""Ephemeral JWT for sandbox → Hof API (no static HOF_TOKEN / password in container env)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


def mint_sandbox_bearer_token() -> str | None:
    """Return a short-lived JWT that :func:`hof.api.auth.verify_auth` accepts as Bearer.

    Uses the same secret and role mapping as normal login when ``jwt_secret_key`` is set.
    Returns ``None`` if JWT auth is not configured (caller may fall back to HTTP Basic).
    """
    try:
        from jose import jwt
    except ImportError:
        return None
    try:
        from hof.config import get_config

        cfg = get_config()
    except Exception:
        return None
    secret = (cfg.jwt_secret_key or "").strip()
    if not secret:
        return None
    subject = (cfg.admin_username or "admin").strip() or "admin"
    roles = list(cfg.user_roles.get(subject, ["admin"])) if cfg.user_roles else ["admin"]
    algo = cfg.jwt_algorithm or "HS256"
    minutes = max(5, min(int(cfg.jwt_access_token_expire_minutes or 60), 24 * 60))
    expire = datetime.now(UTC) + timedelta(minutes=minutes)
    payload: dict[str, Any] = {
        "sub": subject,
        "roles": roles,
        "exp": expire,
    }
    try:
        return jwt.encode(payload, secret, algorithm=algo)
    except Exception:
        logger.exception("sandbox: failed to mint JWT for API")
        return None
