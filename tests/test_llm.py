"""Tests for hof.llm.decorators."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hof.llm.decorators import prompt


class TestPromptDecorator:
    def test_no_provider_raises_at_call_time(self):
        with patch("hof.llm.provider.get_provider", return_value=None):

            @prompt
            def my_fn(text: str) -> str:
                """Summarize: {text}"""

            with pytest.raises(RuntimeError, match="No LLM provider configured"):
                my_fn(text="hello")

    def test_no_provider_returns_callable(self):
        with patch("hof.llm.provider.get_provider", return_value=None):

            @prompt
            def my_fn(text: str) -> str:
                """Summarize: {text}"""

            assert callable(my_fn)

    def test_explicit_provider_used(self):
        mock_provider = MagicMock()
        mock_prompt_fn = MagicMock(return_value=lambda fn: fn)

        with patch("hof.llm.provider.get_provider", return_value=mock_provider):
            with patch("llm_markdown.prompt", mock_prompt_fn):
                @prompt(provider=mock_provider)
                def my_fn(text: str) -> str:
                    """Summarize: {text}"""

    def test_decorator_with_args_syntax(self):
        with patch("hof.llm.provider.get_provider", return_value=None):

            @prompt(stream=False)
            def my_fn(text: str) -> str:
                """Summarize: {text}"""

            assert callable(my_fn)

    def test_missing_llm_markdown_raises_import_error(self):
        mock_provider = MagicMock()

        with patch("hof.llm.provider.get_provider", return_value=mock_provider):
            with patch.dict("sys.modules", {"llm_markdown": None}):
                with pytest.raises(ImportError, match="llm-markdown"):

                    @prompt
                    def my_fn(text: str) -> str:
                        """Summarize: {text}"""

    def test_bare_decorator_syntax(self):
        with patch("hof.llm.provider.get_provider", return_value=None):

            @prompt
            def bare_fn(x: str) -> str:
                """Process: {x}"""

            assert callable(bare_fn)

    def test_preserves_function_name(self):
        with patch("hof.llm.provider.get_provider", return_value=None):

            @prompt
            def named_function(x: str) -> str:
                """Process: {x}"""

            assert named_function.__name__ == "named_function"
