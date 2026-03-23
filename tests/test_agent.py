"""Tests for hof.agent (policy, attachment defaults, stream fold)."""

from __future__ import annotations

from unittest.mock import patch

from hof.agent.policy import AgentPolicy, configure_agent, get_agent_policy
from hof.agent.stream import (
    collect_agent_chat_from_stream,
    default_normalize_attachments,
    iter_agent_chat_stream,
)
from llm_markdown.agent_stream import AgentContentDelta, AgentMessageFinish


def test_default_normalize_attachments_accepts_keys() -> None:
    raw = [{"object_key": "tenant/x.pdf", "filename": "x.pdf"}]
    out, err = default_normalize_attachments(raw)
    assert err is None
    assert out == [{"object_key": "tenant/x.pdf", "filename": "x.pdf"}]


def test_default_normalize_attachments_rejects_non_list() -> None:
    out, err = default_normalize_attachments("nope")
    assert out == []
    assert err == "attachments must be a list"


def test_configure_and_effective_allowlist() -> None:
    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset({"a", "b"}),
            allowlist_mutation=frozenset({"c"}),
            system_prompt_intro="intro ",
        )
    )
    p = get_agent_policy()
    assert p.effective_allowlist() == frozenset({"a", "b", "c"})


def test_collect_agent_chat_from_stream_final() -> None:
    def events():
        yield {"type": "run_start", "run_id": "r1", "model": "m1"}
        yield {"type": "final", "reply": "hi", "tool_rounds_used": 1, "model": "m1"}

    out = collect_agent_chat_from_stream(events())
    assert out["reply"] == "hi"
    assert out["tool_rounds_used"] == 1
    assert out["model"] == "m1"
    assert not out.get("error")


def test_iter_agent_chat_stream_uses_anthropic_when_configured(monkeypatch) -> None:
    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset(),
            allowlist_mutation=frozenset(),
            system_prompt_intro="x",
        )
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("AGENT_LLM_BACKEND", "anthropic")

    backends: list[str] = []

    def _fake_stream_agent_turn(prov, backend, *_a, **_kw):
        backends.append(backend)
        yield AgentContentDelta(text="ok")
        yield AgentMessageFinish(finish_reason="stop", usage=None)

    with patch("hof.agent.stream.stream_agent_turn", side_effect=_fake_stream_agent_turn):
        ev = list(iter_agent_chat_stream([{"role": "user", "content": "hello"}], None))
    assert not any(x.get("type") == "error" for x in ev)
    assert backends == ["anthropic"]


def test_iter_agent_chat_stream_anthropic_fallback_becomes_native_adaptive(monkeypatch) -> None:
    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset(),
            allowlist_mutation=frozenset(),
            system_prompt_intro="x",
        )
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("AGENT_LLM_BACKEND", "anthropic")
    monkeypatch.setenv("AGENT_REASONING_MODE", "fallback")
    monkeypatch.delenv("AGENT_ANTHROPIC_THINKING", raising=False)

    seen: list = []

    def _fake_stream_agent_turn(prov, backend, *_a, reasoning, **_kw):
        seen.append(reasoning)
        assert backend == "anthropic"
        assert reasoning.mode.value == "native"
        assert reasoning.anthropic_thinking == {"type": "adaptive"}
        yield AgentContentDelta(text="ok")
        yield AgentMessageFinish(finish_reason="stop", usage=None)

    with patch("hof.agent.stream.stream_agent_turn", side_effect=_fake_stream_agent_turn):
        ev = list(iter_agent_chat_stream([{"role": "user", "content": "hello"}], None))
    assert not any(x.get("type") == "error" for x in ev)
    assert len(seen) == 1


def test_iter_agent_chat_stream_anthropic_native_respects_thinking_off(monkeypatch) -> None:
    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset(),
            allowlist_mutation=frozenset(),
            system_prompt_intro="x",
        )
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("AGENT_LLM_BACKEND", "anthropic")
    monkeypatch.setenv("AGENT_REASONING_MODE", "native")
    monkeypatch.setenv("AGENT_ANTHROPIC_THINKING", "off")

    def _fake_stream_agent_turn(prov, backend, *_a, reasoning, **_kw):
        assert reasoning.anthropic_thinking is None
        yield AgentContentDelta(text="ok")
        yield AgentMessageFinish(finish_reason="stop", usage=None)

    with patch("hof.agent.stream.stream_agent_turn", side_effect=_fake_stream_agent_turn):
        ev = list(iter_agent_chat_stream([{"role": "user", "content": "hello"}], None))
    assert not any(x.get("type") == "error" for x in ev)


def test_iter_agent_chat_stream_rejects_openai_extras_with_anthropic(monkeypatch) -> None:
    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset(),
            allowlist_mutation=frozenset(),
            system_prompt_intro="x",
        )
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("AGENT_LLM_BACKEND", "anthropic")
    monkeypatch.setenv("AGENT_REASONING_MODE", "native")
    monkeypatch.setenv("AGENT_REASONING_OPENAI_EXTRAS", '{"reasoning_effort":"low"}')
    ev = list(iter_agent_chat_stream([{"role": "user", "content": "hello"}], None))
    assert ev and ev[0].get("type") == "error"
    assert "anthropic" in str(ev[0].get("detail", "")).lower()


def test_iter_agent_chat_stream_uses_fallback_reasoning_mode(monkeypatch) -> None:
    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset(),
            allowlist_mutation=frozenset(),
            system_prompt_intro="x",
        )
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("AGENT_REASONING_MODE", "fallback")

    def _fake_stream_agent_turn(*_a, reasoning, **_kw):
        assert reasoning.mode.value == "fallback"
        yield AgentContentDelta(text="ok")
        yield AgentMessageFinish(finish_reason="stop", usage=None)

    with patch("hof.agent.stream.stream_agent_turn", side_effect=_fake_stream_agent_turn):
        ev = list(iter_agent_chat_stream([{"role": "user", "content": "hello"}], None))
    assert not any(x.get("type") == "error" for x in ev)
    assert any(x.get("type") == "run_start" for x in ev)


def test_iter_agent_chat_stream_rejects_fallback_with_openai_extras(monkeypatch) -> None:
    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset(),
            allowlist_mutation=frozenset(),
            system_prompt_intro="x",
        )
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("AGENT_REASONING_MODE", "fallback")
    monkeypatch.setenv("AGENT_REASONING_OPENAI_EXTRAS", '{"reasoning_effort":"low"}')
    ev = list(iter_agent_chat_stream([{"role": "user", "content": "hello"}], None))
    assert ev and ev[0].get("type") == "error"
    assert "AGENT_REASONING_OPENAI_EXTRAS" in str(ev[0].get("detail", ""))


def test_iter_agent_chat_stream_rejects_bad_reasoning_extras_json(monkeypatch) -> None:
    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset(),
            allowlist_mutation=frozenset(),
            system_prompt_intro="x",
        )
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("AGENT_REASONING_OPENAI_EXTRAS", "not-json")
    ev = list(iter_agent_chat_stream([{"role": "user", "content": "hello"}], None))
    assert ev and ev[0].get("type") == "error"
    assert "AGENT_REASONING_OPENAI_EXTRAS" in str(ev[0].get("detail", ""))


def test_iter_agent_chat_stream_rejects_off_with_openai_extras(monkeypatch) -> None:
    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset(),
            allowlist_mutation=frozenset(),
            system_prompt_intro="x",
        )
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("AGENT_REASONING_MODE", "off")
    monkeypatch.setenv("AGENT_REASONING_OPENAI_EXTRAS", '{"reasoning_effort":"low"}')
    ev = list(iter_agent_chat_stream([{"role": "user", "content": "hello"}], None))
    assert ev and ev[0].get("type") == "error"
    assert "off" in str(ev[0].get("detail", "")).lower()


def test_iter_agent_chat_stream_requires_api_key(monkeypatch) -> None:
    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset(),
            allowlist_mutation=frozenset(),
            system_prompt_intro="x",
        )
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    ev = list(iter_agent_chat_stream([{"role": "user", "content": "hello"}], None))
    assert ev and ev[0].get("type") == "error"
    assert "OPENAI_API_KEY" in str(ev[0].get("detail", ""))
