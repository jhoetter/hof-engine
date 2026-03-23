"""Project configuration with environment variable interpolation."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


def find_project_root(start: Path | None = None) -> Path | None:
    """Walk *start* and its parents for ``hof.config.py``.

    Returns the directory containing the config file, or ``None`` if not found.
    """
    current = (start or Path.cwd()).resolve()
    for directory in [current, *current.parents]:
        if (directory / "hof.config.py").is_file():
            return directory
    return None


def _resolve_env_vars(value: Any, *, strict: bool = True) -> Any:
    """Replace ${VAR_NAME} patterns with environment variable values.

    When *strict* is False, unset variables are left as-is (``${VAR}``).
    """
    if not isinstance(value, str):
        return value
    pattern = re.compile(r"\$\{(\w+)\}")

    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        env_val = os.environ.get(var_name)
        if env_val is None:
            if strict:
                raise ValueError(f"Environment variable {var_name} is not set")
            return match.group(0)
        return env_val

    return pattern.sub(replacer, value)


class Config:
    """hof project configuration.

    Reads settings from hof.config.py and resolves ${ENV_VAR} references.
    """

    def __init__(
        self,
        *,
        app_name: str = "hof-app",
        debug: bool = False,
        secret_key: str = "",
        # Database
        database_url: str = "postgresql://localhost:5433/hof",
        database_pool_size: int = 20,
        database_echo: bool = False,
        # Redis / Celery
        redis_url: str = "redis://localhost:6380/0",
        celery_concurrency: int = 8,
        # Server
        host: str = "0.0.0.0",
        port: int = 8001,
        cors_origins: list[str] | None = None,
        # Auth
        admin_username: str = "admin",
        admin_password: str = "",
        api_key: str = "",
        # JWT — set a strong random secret in production
        jwt_secret_key: str = "",
        jwt_algorithm: str = "HS256",
        jwt_access_token_expire_minutes: int = 60,
        # RBAC: map username → list of roles, e.g. {"alice": ["admin", "viewer"]}
        user_roles: dict[str, list[str]] | None = None,
        # LLM
        llm_provider: Any = None,
        llm_model: str = "",
        llm_api_key: str = "",
        # Agent (OpenAI tool loop) — see docs/reference/agent.md
        agent_model: str = "",
        agent_max_rounds: int = 10,
        agent_max_tool_output_chars: int = 18_000,
        agent_max_model_text_chars: int = 8000,
        agent_max_cli_line_chars: int = 240,
        # OpenAI completion cap per request; many chat models max at 16_384 (override via env).
        agent_max_completion_tokens: int = 16_384,
        # Agent streamed reasoning: native (default), off (no reasoning_delta), fallback (llm-markdown two-phase).
        agent_reasoning_mode: str = "native",
        # Langfuse
        langfuse_public_key: str = "",
        langfuse_secret_key: str = "",
        langfuse_host: str = "https://cloud.langfuse.com",
        # Files
        file_storage_path: str = "./storage",
        file_max_size_mb: int = 100,
        # Auto-discovery directories
        tables_dir: str = "tables",
        functions_dir: str = "functions",
        flows_dir: str = "flows",
        cron_dir: str = "cron",
        ui_dir: str = "ui",
        # Documentation
        docs_dir: str = "docs",
    ):
        self.app_name = app_name
        self.debug = debug
        self.secret_key = secret_key

        self.database_url = database_url
        self.database_pool_size = database_pool_size
        self.database_echo = database_echo

        self.redis_url = redis_url
        self.celery_concurrency = celery_concurrency

        self.host = host
        self.port = port
        self.cors_origins = cors_origins or ["*"]

        self.admin_username = admin_username
        self.admin_password = admin_password
        self.api_key = api_key
        self.jwt_secret_key = jwt_secret_key
        self.jwt_algorithm = jwt_algorithm
        self.jwt_access_token_expire_minutes = jwt_access_token_expire_minutes
        self.user_roles: dict[str, list[str]] = user_roles or {}

        self.llm_provider = llm_provider
        self.llm_model = llm_model
        self.llm_api_key = llm_api_key

        self.agent_model = agent_model
        self.agent_max_rounds = agent_max_rounds
        self.agent_max_tool_output_chars = agent_max_tool_output_chars
        self.agent_max_model_text_chars = agent_max_model_text_chars
        self.agent_max_cli_line_chars = agent_max_cli_line_chars
        self.agent_max_completion_tokens = agent_max_completion_tokens
        self.agent_reasoning_mode = agent_reasoning_mode

        self.langfuse_public_key = langfuse_public_key
        self.langfuse_secret_key = langfuse_secret_key
        self.langfuse_host = langfuse_host

        self.file_storage_path = file_storage_path
        self.file_max_size_mb = file_max_size_mb

        self.tables_dir = tables_dir
        self.functions_dir = functions_dir
        self.flows_dir = flows_dir
        self.cron_dir = cron_dir
        self.ui_dir = ui_dir
        self.docs_dir = docs_dir

    def resolve(self, *, strict: bool = True) -> Config:
        """Resolve all ${ENV_VAR} references in string fields.

        When *strict* is False, missing env vars are left as placeholders.
        """
        for attr_name in vars(self):
            value = getattr(self, attr_name)
            if isinstance(value, str):
                setattr(self, attr_name, _resolve_env_vars(value, strict=strict))
            elif isinstance(value, list):
                setattr(
                    self,
                    attr_name,
                    [_resolve_env_vars(v, strict=strict) for v in value],
                )
        return self

    @property
    def discovery_dirs(self) -> dict[str, str]:
        return {
            "tables": self.tables_dir,
            "functions": self.functions_dir,
            "flows": self.flows_dir,
            "cron": self.cron_dir,
        }


_current_config: Config | None = None


def load_config(project_root: Path | None = None, *, strict: bool = True) -> Config:
    """Load config from hof.config.py in the project root.

    Set *strict=False* during build steps where runtime env vars
    (e.g. DATABASE_URL) are unavailable.
    """
    global _current_config

    if project_root is not None:
        root = project_root
    else:
        env_root = os.environ.get("HOF_PROJECT_ROOT")
        if env_root:
            root = Path(env_root).resolve()
        else:
            found = find_project_root()
            root = found if found is not None else Path.cwd()

    load_dotenv(root / ".env")

    config_file = root / "hof.config.py"
    if not config_file.exists():
        _current_config = Config()
        return _current_config

    import importlib.util

    spec = importlib.util.spec_from_file_location("hof_user_config", config_file)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    config = getattr(module, "config", None)
    if not isinstance(config, Config):
        raise ValueError("hof.config.py must define a `config = Config(...)` variable")

    config.resolve(strict=strict)
    _current_config = config
    return config


def get_config() -> Config:
    """Get the current loaded config, or load from cwd."""
    global _current_config
    if _current_config is None:
        return load_config()
    return _current_config
