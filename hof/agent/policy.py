"""Per-application agent policy (tool allowlists, prompts, attachment rules)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# (raw attachments from client) -> (normalized list, error message or None)
NormalizeAttachmentsFn = Callable[[Any], tuple[list[dict[str, str]], str | None]]
# normalized attachment list -> system prompt fragment
AttachmentsSystemNoteFn = Callable[[list[dict[str, str]]], str]

DEFAULT_SYSTEM_PROMPT_BODY = """Use tools to fetch real data; do not invent row counts or amounts.
Answer concisely in the same language as the user's chat messages
(the `messages` entries with role user).
Do not infer language from attachment filenames, PDF or invoice body text,
or other document content—only from what the user typed.
If there are no user messages yet, use English. If a tool errors, explain briefly and suggest a fix.

During a model round (before tool calls), the app labels your streaming text as Reasoning,
not as the final reply. After tools, text meant for the user appears as Assistant reply.
Keep pre-tool sentences short (what you will try next and why).
Each tool row includes a technical description automatically."""

DEFAULT_SYSTEM_PROMPT_MUTATION_SUFFIX = """

## Mutation tools (create / update / delete / inbox resolves)
When you call a mutation tool, execution waits until the user confirms in the app (or via API).
You will receive a tool result with pending_confirmation — tell the user clearly what will happen
and that they must use the Approve or Reject controls on that action's card in the assistant.
Do not ask them to type "yes" as the only way to proceed; the UI is authoritative.

Read/list tools run immediately. You may mix reads and mutations in one turn: reads return data
while mutations wait for confirmation before the assistant continues."""

DEFAULT_CONFIRMATION_SUMMARY_USER_MESSAGE = (
    "The data-changing tools above have NOT run yet — nothing was written to the database. "
    "Each proposed action is an expandable function row; the user must Approve or Reject there.\n\n"
    "Reply with 1–3 short sentences in the same language as the user's chat messages "
    "(role user only), "
    "not the language of any attached document or filename. "
    "Use future or conditional wording only (e.g. \"will\", \"after you approve\", \"proposed\"). "
    "Never use past tense as if the mutation already succeeded (do not say you already registered, "
    "created, updated, saved, or completed the action).\n"
    "Briefly remind them what will happen after they approve or reject in that panel. "
    "Do not call tools."
)


@dataclass(frozen=True)
class AgentPolicy:
    """Configure the Hof agent for your app. Pass to ``configure_agent`` at import time."""

    allowlist_read: frozenset[str]
    allowlist_mutation: frozenset[str]
    system_prompt_intro: str
    system_prompt_body: str = DEFAULT_SYSTEM_PROMPT_BODY
    system_prompt_mutation_suffix: str = DEFAULT_SYSTEM_PROMPT_MUTATION_SUFFIX
    confirmation_summary_user_message: str = DEFAULT_CONFIRMATION_SUMMARY_USER_MESSAGE
    # Short hint for streamed tool_call events (UI); keep concise.
    tool_internal_rationale: dict[str, str] = field(default_factory=dict)
    # Merged into OpenAI tool descriptions and hof fn describe.
    tool_when_to_use: dict[str, str] = field(default_factory=dict)
    # Typical follow-up tool names (hints only; no auto-chaining).
    tool_related_tools: dict[str, list[str]] = field(default_factory=dict)
    normalize_attachments: NormalizeAttachmentsFn | None = None
    attachments_system_note: AttachmentsSystemNoteFn | None = None

    def effective_allowlist(self) -> frozenset[str]:
        return frozenset(self.allowlist_read | self.allowlist_mutation)

    def rationale_for(self, function_name: str) -> str | None:
        key = (function_name or "").strip()
        return self.tool_internal_rationale.get(key)


_policy: AgentPolicy | None = None


def configure_agent(policy: AgentPolicy) -> None:
    """Set the global agent policy (call once from your app's functions package)."""
    global _policy
    _policy = policy


def get_agent_policy() -> AgentPolicy:
    if _policy is None:
        msg = (
            "Hof agent is not configured: call hof.agent.configure_agent(AgentPolicy(...)) "
            "from your app."
        )
        raise RuntimeError(msg)
    return _policy


def try_get_agent_policy() -> AgentPolicy | None:
    return _policy
