"""Re-export the @llm decorator with hof-aware defaults."""

from __future__ import annotations

from typing import Any, Callable


def llm(
    fn: Callable | None = None,
    *,
    provider: Any = None,
    reasoning_first: bool = False,
    stream: bool = False,
    max_retries: int = 2,
    langfuse_metadata: dict | None = None,
) -> Callable:
    """LLM decorator that wraps llm-markdown with hof defaults.

    If no provider is specified, uses the project's configured default provider.
    """

    def decorator(fn: Callable) -> Callable:
        actual_provider = provider
        if actual_provider is None:
            from hof.llm.provider import get_provider

            actual_provider = get_provider()

        if actual_provider is None:
            import functools

            @functools.wraps(fn)
            def no_provider_wrapper(*args: Any, **kwargs: Any) -> Any:
                raise RuntimeError(
                    "No LLM provider configured. Set llm_provider and llm_api_key in hof.config.py"
                )

            return no_provider_wrapper

        try:
            from llm_markdown import llm as llm_decorator

            return llm_decorator(
                provider=actual_provider,
                reasoning_first=reasoning_first,
                stream=stream,
                max_retries=max_retries,
                langfuse_metadata=langfuse_metadata or {},
            )(fn)
        except ImportError:
            raise ImportError(
                "llm-markdown is required for LLM integration. "
                "Install it with: pip install llm-markdown"
            )

    if fn is not None:
        return decorator(fn)
    return decorator
