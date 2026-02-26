"""LLM integration layer wrapping llm-markdown."""

from hof.llm.decorators import prompt
from hof.llm.provider import get_provider

__all__ = ["prompt", "get_provider"]
