"""LLM provider configuration and factory."""

from __future__ import annotations

from typing import Any

_default_provider: Any = None


def configure_provider(config: Any) -> None:
    """Set up the default LLM provider from hof config."""
    global _default_provider

    if config.llm_provider and not isinstance(config.llm_provider, str):
        _default_provider = config.llm_provider
        return

    if config.llm_provider == "openai" and config.llm_api_key:
        try:
            from llm_markdown.providers import OpenAIProvider

            _default_provider = OpenAIProvider(
                api_key=config.llm_api_key,
                model=config.llm_model or "gpt-4o",
            )

            if config.langfuse_public_key and config.langfuse_secret_key:
                from llm_markdown.providers import LangfuseWrapper

                _default_provider = LangfuseWrapper(
                    provider=_default_provider,
                    secret_key=config.langfuse_secret_key,
                    public_key=config.langfuse_public_key,
                    host=config.langfuse_host,
                )
        except ImportError:
            pass


def get_provider() -> Any:
    """Get the configured default LLM provider."""
    if _default_provider is None:
        from hof.config import get_config

        configure_provider(get_config())

    return _default_provider
