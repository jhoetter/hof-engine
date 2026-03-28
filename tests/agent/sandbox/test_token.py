"""Sandbox JWT minting."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from hof.agent.sandbox.token import mint_sandbox_bearer_token


def test_mint_returns_none_without_jwt_secret() -> None:
    cfg = MagicMock()
    cfg.jwt_secret_key = ""
    cfg.admin_username = "admin"
    cfg.user_roles = {}
    cfg.jwt_algorithm = "HS256"
    cfg.jwt_access_token_expire_minutes = 60
    with patch("hof.config.get_config", return_value=cfg):
        assert mint_sandbox_bearer_token() is None


def test_mint_returns_jwt_when_secret_set() -> None:
    cfg = MagicMock()
    cfg.jwt_secret_key = "test-secret-at-least-16-bytes"
    cfg.admin_username = "admin"
    cfg.user_roles = {"admin": ["admin"]}
    cfg.jwt_algorithm = "HS256"
    cfg.jwt_access_token_expire_minutes = 60
    with patch("hof.config.get_config", return_value=cfg):
        tok = mint_sandbox_bearer_token()
    assert tok is not None
    assert isinstance(tok, str)
    assert tok.count(".") == 2
