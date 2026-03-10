"""Authentication and role-based access control for the hof API.

Supported authentication methods (tried in order):
1. Bearer JWT token  — ``Authorization: Bearer <token>``
2. API key header    — ``X-API-Key: <key>``
3. HTTP Basic auth   — username / password

JWT tokens are issued via ``POST /api/auth/token`` and carry the user's roles
as a claim.  When no credentials are configured, all requests are allowed as
``anonymous``.

Roles
-----
Roles are configured in ``hof.config.py``:

    config = Config(
        admin_username="admin",
        admin_password="secret",
        user_roles={
            "admin": ["admin", "viewer"],
            "readonly": ["viewer"],
        },
    )

Built-in roles:
- ``admin``  — full access to all endpoints
- ``viewer`` — read-only access (GET requests only)

Custom roles can be defined and checked with ``require_role()``.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import (
    APIKeyHeader,
    HTTPBasic,
    HTTPBasicCredentials,
    OAuth2PasswordBearer,
    OAuth2PasswordRequestForm,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

    from hof.config import Config

_config: Config | None = None

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
basic_auth = HTTPBasic(auto_error=False)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def setup_auth(app: FastAPI, config: Config) -> None:
    """Configure authentication on the FastAPI app and register the token endpoint."""
    global _config
    _config = config

    from fastapi import APIRouter

    auth_router = APIRouter()

    @auth_router.post("/token")
    async def login(form_data: OAuth2PasswordRequestForm = Depends()) -> dict:
        """Issue a JWT access token for valid credentials."""
        cfg = _config
        if cfg is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Auth not configured")

        username_ok = secrets.compare_digest(form_data.username, cfg.admin_username)
        password_ok = secrets.compare_digest(form_data.password, cfg.admin_password)

        if not (username_ok and password_ok):
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

        roles = cfg.user_roles.get(form_data.username, ["admin"])
        token = _create_access_token(
            subject=form_data.username,
            roles=roles,
            secret=cfg.jwt_secret_key or cfg.admin_password,
            algorithm=cfg.jwt_algorithm,
            expires_minutes=cfg.jwt_access_token_expire_minutes,
        )
        return {"access_token": token, "token_type": "bearer"}

    app.include_router(auth_router, prefix="/api/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------


def _create_access_token(
    *,
    subject: str,
    roles: list[str],
    secret: str,
    algorithm: str,
    expires_minutes: int,
) -> str:
    try:
        from jose import jwt
    except ImportError:
        raise ImportError("python-jose[cryptography] is required for JWT auth.")

    expire = datetime.now(UTC) + timedelta(minutes=expires_minutes)
    payload = {
        "sub": subject,
        "roles": roles,
        "exp": expire,
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


def _decode_jwt(token: str) -> dict[str, Any] | None:
    if _config is None:
        return None
    secret = _config.jwt_secret_key or _config.admin_password
    if not secret:
        return None
    try:
        from jose import jwt

        return jwt.decode(token, secret, algorithms=[_config.jwt_algorithm])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Dependency: verify authentication
# ---------------------------------------------------------------------------


async def verify_auth(
    request: Request,
    bearer_token: str | None = Depends(oauth2_scheme),
    api_key: str | None = Security(api_key_header),
    credentials: HTTPBasicCredentials | None = Depends(basic_auth),
) -> str:
    """Verify authentication via JWT Bearer token, API key, or Basic auth.

    Returns the authenticated identity (username or ``"api-key"``).
    When no credentials are configured, returns ``"anonymous"``.
    """
    if _config is None:
        return "anonymous"

    if not _config.admin_password and not _config.api_key and not _config.jwt_secret_key:
        return "anonymous"

    # 1. JWT Bearer token
    if bearer_token:
        payload = _decode_jwt(bearer_token)
        if payload and "sub" in payload:
            return payload["sub"]

    # 2. API key
    if api_key and _config.api_key:
        if secrets.compare_digest(api_key, _config.api_key):
            return "api-key"

    # 3. HTTP Basic auth
    if credentials and _config.admin_password:
        username_ok = secrets.compare_digest(credentials.username, _config.admin_username)
        password_ok = secrets.compare_digest(credentials.password, _config.admin_password)
        if username_ok and password_ok:
            return credentials.username

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing credentials",
        headers={"WWW-Authenticate": 'Bearer, Basic realm="hof"'},
    )


# ---------------------------------------------------------------------------
# Dependency: require specific role(s)
# ---------------------------------------------------------------------------


def require_role(*required_roles: str):
    """FastAPI dependency factory that enforces role-based access.

    Usage:
        @router.delete("/{id}")
        async def delete_item(user: str = Depends(require_role("admin"))):
            ...
    """

    async def _check_role(user: str = Depends(verify_auth)) -> str:
        if _config is None or not required_roles:
            return user

        # API key and anonymous get admin-level access when no RBAC is configured
        if user in ("api-key", "anonymous"):
            return user

        user_role_list = _config.user_roles.get(user, [])
        if not any(r in user_role_list for r in required_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role(s) required: {', '.join(required_roles)}",
            )
        return user

    return _check_role


def get_user_roles(username: str) -> list[str]:
    """Return the roles assigned to a user."""
    if _config is None:
        return []
    return _config.user_roles.get(username, [])
