"""Per-application agent policy (tool allowlists, prompts, attachment rules)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

# (raw attachments from client) -> (normalized list, error message or None)
NormalizeAttachmentsFn = Callable[[Any], tuple[list[dict[str, str]], str | None]]
# normalized attachment list -> system prompt fragment
AttachmentsSystemNoteFn = Callable[[list[dict[str, str]]], str]


@dataclass(frozen=True)
class PostApplyReviewHint:
    """Human-in-the-loop step after the mutation applies (not the chat confirm gate)."""

    label: str
    url: str | None = None
    path: str | None = None


@dataclass(frozen=True)
class MutationPreviewResult:
    """Structured mutation preview for model + UI (no DB writes)."""

    summary: str
    data: dict[str, Any] | None = None
    post_apply_review: PostApplyReviewHint | None = None
    status_hint: str | None = None


# validated mutation arguments -> preview envelope or legacy flat dict (wrapped by stream)
MutationPreviewFn = Callable[
    [dict[str, Any]],
    MutationPreviewResult | dict[str, Any] | None,
]

# after successful mutation: (tool_name, args, result_row) -> optional post-apply review hint for UI
MutationPostApplyFn = Callable[
    [str, dict[str, Any], dict[str, Any]],
    PostApplyReviewHint | None,
]


def post_apply_review_hint_to_wire(hint: PostApplyReviewHint) -> dict[str, Any]:
    """Serialize ``PostApplyReviewHint`` for NDJSON ``mutation_applied`` events."""
    pr: dict[str, Any] = {"label": hint.label}
    if hint.url is not None:
        pr["url"] = hint.url
    if hint.path is not None:
        pr["path"] = hint.path
    return pr


def mutation_preview_to_wire(result: MutationPreviewResult | dict[str, Any]) -> dict[str, Any]:
    """Serialize preview for NDJSON stream, tool placeholder, and model JSON (JSON-serializable)."""
    if isinstance(result, MutationPreviewResult):
        d: dict[str, Any] = {"summary": result.summary}
        if result.data is not None:
            d["data"] = result.data
        if result.post_apply_review is not None:
            r = result.post_apply_review
            pr: dict[str, Any] = {"label": r.label}
            if r.url is not None:
                pr["url"] = r.url
            if r.path is not None:
                pr["path"] = r.path
            d["post_apply_review"] = pr
        if result.status_hint:
            d["status_hint"] = result.status_hint
        return d
    # Legacy: flat dict from older apps — expose as opaque data with a generated summary line
    raw = dict(result)
    try:
        summary = json.dumps(raw, default=str, sort_keys=True)
    except TypeError:
        summary = str(raw)
    if len(summary) > 200:
        summary = summary[:197] + "…"
    return {"summary": summary, "data": raw}

# Framework agent tools (read-only); registered after user discovery in ``discover_all``.
BUILTIN_AGENT_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "hof_builtin_server_time",
        "hof_builtin_runtime_info",
        "hof_builtin_http_get",
        "hof_builtin_calculate",
    },
)

DEFAULT_SYSTEM_PROMPT_BODY = """Use tools to fetch real data; do not invent row counts or amounts.
Tool JSON is live output from executed tools on this backend (not training recall). Treat it as
authoritative: state counts, amounts, and labels directly. Avoid meta-disclaimers such as "based on
actual/real data" unless the tool errored or the payload is incomplete (ends with "…(truncated)" or
rows clearly short of a stated total).
Answer concisely in the same language as the user's chat messages
(the `messages` entries with role user).
Do not infer language from attachment filenames, PDF or invoice body text,
or other document content—only from what the user typed.
If there are no user messages yet, use English. If a tool errors, explain briefly and suggest a fix.

## Visible text before tools (required for the in-app “Thinking” stream)
Before you call any tool, you MUST output at least one short sentence in the normal assistant
message (the same visible `content` stream users see—not only tool calls). Say what you will
look up or change and why. Do not jump to tools with an empty assistant message: the UI
streams this pre-tool text as “Thinking” and it must not be blank.
Keep it to one or two sentences; after tools, answer the user in the final reply pass.

After tool results, write for the user in clear language (that pass is the main reply, not
labeled as thinking). Each tool row still shows technical details separately."""

DEFAULT_SYSTEM_PROMPT_MUTATION_SUFFIX = """

## Mutation tools (create / update / delete / inbox resolves)
When you call a mutation tool, execution waits until the user confirms in the app (or via API).
You will receive a tool result with pending_confirmation. The JSON may include a **preview** object
(computed from the proposed arguments): it has **summary** (one-line), optional **data** (opaque
fields you should reason about), and optional **post_apply_review** (label + url/path for a human
step after the write — not the same as chat confirmation). The UI shows proposed mutations with
Approve / Reject (and related controls)
automatically—you do not need to explain that approval mechanism or where to click. Do not ask
users to type "yes" as the only way to proceed; the UI is authoritative.

Read/list tools run immediately. You may mix reads and mutations in one turn: reads return data
while mutations wait for confirmation before the assistant continues."""

DEFAULT_CONFIRMATION_SUMMARY_USER_MESSAGE = (
    "The data-changing tools above have NOT run yet — nothing was written to the database. "
    "The user must Approve or Reject each proposed action in the assistant UI (then Apply / confirm "
    "if shown). Expandable tool rows show technical detail only.\n\n"
    "Reply with 1–3 short sentences in the same language as the user's chat messages "
    "(role user only), "
    "not the language of any attached document or filename. "
    "Use future or conditional wording only (e.g. \"will\", \"after you approve\", \"proposed\"). "
    "Never use past tense as if the mutation already succeeded (do not say you already registered, "
    "created, updated, saved, or completed the action).\n"
    "Briefly remind them what will happen after they approve or reject in that panel. "
    "Do not call tools."
)

# After pending mutations: optional short assistant message before awaiting_confirmation.
# - llm_stream: extra model round, token-streamed (legacy).
# - static: one short fixed hint (no LLM).
# - none: no assistant text; UI pending bar only (main reply streams after resume).
ConfirmationSummaryMode = Literal["llm_stream", "static", "none"]


@dataclass(frozen=True)
class AgentPolicy:
    """Configure the Hof agent for your app. Pass to ``configure_agent`` at import time."""

    allowlist_read: frozenset[str]
    allowlist_mutation: frozenset[str]
    system_prompt_intro: str
    system_prompt_body: str = DEFAULT_SYSTEM_PROMPT_BODY
    system_prompt_mutation_suffix: str = DEFAULT_SYSTEM_PROMPT_MUTATION_SUFFIX
    confirmation_summary_user_message: str = DEFAULT_CONFIRMATION_SUMMARY_USER_MESSAGE
    confirmation_summary_mode: ConfirmationSummaryMode = "llm_stream"
    # Short hint for streamed tool_call events (UI); keep concise.
    tool_internal_rationale: dict[str, str] = field(default_factory=dict)
    # Merged into OpenAI tool descriptions and hof fn describe.
    tool_when_to_use: dict[str, str] = field(default_factory=dict)
    # Typical follow-up tool names (hints only; no auto-chaining).
    tool_related_tools: dict[str, list[str]] = field(default_factory=dict)
    normalize_attachments: NormalizeAttachmentsFn | None = None
    attachments_system_note: AttachmentsSystemNoteFn | None = None
    mutation_preview: dict[str, MutationPreviewFn] = field(default_factory=dict)
    mutation_post_apply: dict[str, MutationPostApplyFn] = field(default_factory=dict)

    def effective_allowlist(self) -> frozenset[str]:
        return frozenset(self.allowlist_read | self.allowlist_mutation | BUILTIN_AGENT_TOOL_NAMES)

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
