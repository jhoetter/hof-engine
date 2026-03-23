"""Hof agent: OpenAI tool-calling with mutation confirmation and NDJSON streaming."""

from hof.agent.policy import (
    AgentPolicy,
    configure_agent,
    get_agent_policy,
    try_get_agent_policy,
)
from hof.agent.stream import (
    collect_agent_chat_from_stream,
    default_attachments_system_note,
    default_normalize_attachments,
    iter_agent_chat_stream,
    iter_agent_resume_stream,
)
from hof.agent.tooling import format_cli_line

__all__ = [
    "AgentPolicy",
    "collect_agent_chat_from_stream",
    "configure_agent",
    "default_attachments_system_note",
    "default_normalize_attachments",
    "format_cli_line",
    "get_agent_policy",
    "iter_agent_chat_stream",
    "iter_agent_resume_stream",
    "try_get_agent_policy",
]
