"""LLM provider configuration and factory."""

from __future__ import annotations

from typing import Any

_default_provider: Any = None


class LLMProvider:
    """Base class for LLM providers (re-exported from llm-markdown)."""

    def query(self, messages: list, **kwargs: Any) -> str:
        raise NotImplementedError

    def query_async(self, messages: list, **kwargs: Any):
        raise NotImplementedError

    def query_structured(self, messages: list, schema: dict, **kwargs: Any) -> Any:
        raise NotImplementedError

    def supports_structured_output(self) -> bool:
        return False


def configure_provider(config: Any) -> None:
    """Set up the default LLM provider from hof config."""
    global _default_provider

    if config.llm_provider and not isinstance(config.llm_provider, str):
        _default_provider = config.llm_provider
        return

    if config.llm_provider == "openai" and config.llm_api_key:
        try:
            from llm_markdown.providers.openai import OpenAIProvider

            _default_provider = OpenAIProvider(
                api_key=config.llm_api_key,
                model=config.llm_model or "gpt-4o",
            )

            if config.langfuse_public_key and config.langfuse_secret_key:
                from llm_markdown.providers.langfuse import LangfuseWrapper

                _default_provider = LangfuseWrapper(
                    provider=_default_provider,
                    public_key=config.langfuse_public_key,
                    secret_key=config.langfuse_secret_key,
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
