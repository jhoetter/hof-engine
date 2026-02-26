"""Thin wrapper around llm-markdown's ``@prompt`` with hof-aware defaults."""

from __future__ import annotations

import functools
from typing import Any, Callable


def prompt(
    fn: Callable | None = None,
    *,
    provider: Any = None,
    stream: bool = False,
    langfuse_metadata: dict | None = None,
) -> Callable:
    """LLM prompt decorator — wraps ``llm_markdown.prompt`` with the project's
    configured provider so you don't have to pass it every time.

    Structured output is automatic: return a Pydantic model and the response
    is validated. Return ``str`` for plain text.
    """

    def decorator(fn: Callable) -> Callable:
        actual_provider = provider
        if actual_provider is None:
            from hof.llm.provider import get_provider

            actual_provider = get_provider()

        if actual_provider is None:

            @functools.wraps(fn)
            def no_provider_wrapper(*args: Any, **kwargs: Any) -> Any:
                raise RuntimeError(
                    "No LLM provider configured. Set llm_provider and llm_api_key in hof.config.py"
                )

            return no_provider_wrapper

        try:
            from llm_markdown import prompt as _prompt
        except ImportError:
            raise ImportError(
                "llm-markdown[openai] is required for LLM integration. "
                "Install it with: pip install llm-markdown[openai]"
            )

        return _prompt(
            actual_provider,
            stream=stream,
            langfuse_metadata=langfuse_metadata,
        )(fn)

    if fn is not None:
        return decorator(fn)
    return decorator
