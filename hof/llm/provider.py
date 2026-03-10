"""LLM provider configuration and factory."""

from __future__ import annotations

from typing import Any

# Module-level default kept for backward compatibility with code that calls
# get_provider() without an active HofApp context.
_default_provider: Any = None


def _build_provider(config: Any) -> Any:
    """Build an LLM provider instance from a Config object."""
    if config.llm_provider and not isinstance(config.llm_provider, str):
        return config.llm_provider

    if config.llm_provider == "openai" and config.llm_api_key:
        try:
            from llm_markdown.providers import OpenAIProvider

            provider: Any = OpenAIProvider(
                api_key=config.llm_api_key,
                model=config.llm_model or "gpt-4o",
            )

            if config.langfuse_public_key and config.langfuse_secret_key:
                from llm_markdown.providers import LangfuseWrapper

                provider = LangfuseWrapper(
                    provider=provider,
                    secret_key=config.langfuse_secret_key,
                    public_key=config.langfuse_public_key,
                    host=config.langfuse_host,
                )

            return provider
        except ImportError:
            pass

    return None


def configure_provider(config: Any) -> None:
    """Set up the module-level default LLM provider from a config object."""
    global _default_provider
    _default_provider = _build_provider(config)


def get_provider() -> Any:
    """Get the LLM provider.

    Prefers the active HofApp's provider when one is set; falls back to the
    module-level default for backward compatibility.
    """
    from hof.app import get_current_app

    app = get_current_app()
    if app is not None:
        return app.get_llm_provider()

    global _default_provider
    if _default_provider is None:
        from hof.config import get_config

        configure_provider(get_config())

    return _default_provider
