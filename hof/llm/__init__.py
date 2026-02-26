"""LLM integration layer wrapping llm-markdown."""

from hof.llm.decorators import llm
from hof.llm.provider import get_provider, LLMProvider

__all__ = ["llm", "get_provider", "LLMProvider"]
