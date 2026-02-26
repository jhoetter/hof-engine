"""Simple authentication for the admin UI and API."""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader, HTTPBasic, HTTPBasicCredentials

if TYPE_CHECKING:
    from fastapi import FastAPI
    from hof.config import Config

_config: Config | None = None

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
basic_auth = HTTPBasic(auto_error=False)


def setup_auth(app: FastAPI, config: Config) -> None:
    """Configure authentication on the FastAPI app."""
    global _config
    _config = config


async def verify_auth(
    request: Request,
    api_key: str | None = Security(api_key_header),
    credentials: HTTPBasicCredentials | None = Depends(basic_auth),
) -> str:
    """Verify authentication via API key or basic auth.

    Returns the authenticated identity (username or "api-key").
    """
    if _config is None:
        return "anonymous"

    if not _config.admin_password and not _config.api_key:
        return "anonymous"

    if api_key and _config.api_key:
        if secrets.compare_digest(api_key, _config.api_key):
            return "api-key"

    if credentials and _config.admin_password:
        username_ok = secrets.compare_digest(credentials.username, _config.admin_username)
        password_ok = secrets.compare_digest(credentials.password, _config.admin_password)
        if username_ok and password_ok:
            return credentials.username

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
        headers={"WWW-Authenticate": "Basic"},
    )
