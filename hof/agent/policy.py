"""Per-application agent policy (tool allowlists, prompts, attachment rules)."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from hof.agent.sandbox.config import SandboxConfig
from hof.agent.sandbox.constants import HOF_BUILTIN_TERMINAL_EXEC
from hof.browser.config import BrowserConfig
from hof.browser.constants import HOF_BUILTIN_BROWSE_WEB

# (raw attachments from client) -> (normalized list, error message or None)
NormalizeAttachmentsFn = Callable[[Any], tuple[list[dict[str, str]], str | None]]
# normalized attachment list -> system prompt fragment
AttachmentsSystemNoteFn = Callable[[list[dict[str, str]]], str]
# Copy user chat uploads into the sandbox container ``/workspace`` (first terminal session).
# Args: ``TerminalSession``, normalized attachments (``object_key``, optional ``filename`` /
# ``content_type``).
SandboxStageChatAttachmentsFn = Callable[[Any, list[dict[str, str]]], None]


@dataclass(frozen=True)
class PostApplyReviewHint:
    """Human-in-the-loop step after the mutation applies (not the chat confirm gate)."""

    label: str
    url: str | None = None
    path: str | None = None


@dataclass(frozen=True)
class InboxWatchDescriptor:
    """Persisted inbox HITL watch: user completes review in Inbox, then client resumes."""

    watch_id: str
    record_type: str
    record_id: str
    label: str | None = None
    url: str | None = None
    path: str | None = None


def inbox_watch_to_wire(w: InboxWatchDescriptor) -> dict[str, Any]:
    d: dict[str, Any] = {
        "watch_id": w.watch_id,
        "record_type": w.record_type,
        "record_id": w.record_id,
    }
    if w.label is not None:
        d["label"] = w.label
    if w.url is not None:
        d["url"] = w.url
    if w.path is not None:
        d["path"] = w.path
    return d


def inbox_watch_from_wire(raw: dict[str, Any]) -> InboxWatchDescriptor | None:
    wid = str(raw.get("watch_id") or "").strip()
    rt = str(raw.get("record_type") or "").strip()
    rid = str(raw.get("record_id") or "").strip()
    if not wid or not rt or not rid:
        return None
    lab = raw.get("label")
    url = raw.get("url")
    path = raw.get("path")
    return InboxWatchDescriptor(
        watch_id=wid,
        record_type=rt,
        record_id=rid,
        label=str(lab).strip() if isinstance(lab, str) and lab.strip() else None,
        url=str(url).strip() if isinstance(url, str) and url.strip() else None,
        path=str(path).strip() if isinstance(path, str) and path.strip() else None,
    )


@dataclass(frozen=True)
class MutationPreviewResult:
    """Structured mutation preview for model + UI (no DB writes)."""

    summary: str
    data: dict[str, Any] | None = None
    post_apply_review: PostApplyReviewHint | None = None
    status_hint: str | None = None
    cli_line: str | None = None


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

# after confirmed mutation -> inbox watches until Inbox review completes
MutationInboxWatchFn = Callable[
    [str, dict[str, Any], dict[str, Any]],
    Sequence[InboxWatchDescriptor] | None,
]
# True + optional synthetic user line; False + None = pending; False + str = error detail
VerifyInboxWatchFn = Callable[[InboxWatchDescriptor], tuple[bool, str | None]]


@dataclass(frozen=True)
class MutationBatchEntry:
    """One resolved pending mutation from the resume batch (confirmed or rejected)."""

    function_name: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    confirmed: bool


# Pending inbox item ids before the mutation batch (e.g. workflow row ids).
InboxSnapshotFn = Callable[[], set[str]]
# (snapshot_ids, batch, watches_from_per_tool_hooks) -> extra watches from diff / async settle
InboxScanAfterMutationsFn = Callable[
    [set[str], list[MutationBatchEntry], list[InboxWatchDescriptor]],
    list[InboxWatchDescriptor],
]

# After inbox watches verify: (resolved watches, baseline pending ids at last barrier) ->
# (extra watches for newly appeared pending rows, updated baseline = current pending ids).
InboxScanAfterInboxResumeFn = Callable[
    [list[InboxWatchDescriptor], frozenset[str]],
    tuple[list[InboxWatchDescriptor], frozenset[str]],
]

# App constants / secrets -> dict for Browser Use Cloud ``sensitiveData`` (async for DB/API).
BrowserSensitiveDataFn = Callable[[], Awaitable[dict[str, str]]]


def post_apply_review_hint_to_wire(hint: PostApplyReviewHint) -> dict[str, Any]:
    """Serialize ``PostApplyReviewHint`` for NDJSON ``mutation_applied`` events."""
    pr: dict[str, Any] = {"label": hint.label}
    if hint.url is not None:
        pr["url"] = hint.url
    if hint.path is not None:
        pr["path"] = hint.path
    return pr


def mutation_preview_to_wire(
    result: MutationPreviewResult | dict[str, Any],
) -> dict[str, Any]:
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
        if result.cli_line:
            d["cli_line"] = result.cli_line
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
        "hof_builtin_present_plan",
        "hof_builtin_present_plan_clarification",
        "hof_builtin_update_plan_todo_state",
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
while mutations wait for confirmation before the assistant continues.

Some mutations, after the user confirms them in the chat UI, still require a **human step in
the app Inbox** (e.g. manager approval). When that applies, the stream pauses on
**awaiting_inbox_review** until Inbox status changes and the client resumes via
**agent_resume_inbox_reviews** (server re-verifies). Use read-only tools such as
**get_inbox_review_link** when you need to show a deep link in tool output for the user.
For links you paste in the **in-app web assistant** thread, pass **agent_embed=True** (or the
deployment’s equivalent) so the UI opens the **/inbox-review** single-item page beside the chat
instead of a new browser tab; omit it for TUI or generic sharing."""

DEFAULT_CONFIRMATION_SUMMARY_USER_MESSAGE = (
    "The data-changing tools above have NOT run yet — nothing was written to the database. "
    "The user must Approve or Reject each proposed action in the assistant UI "
    "(then Apply / confirm "
    "if shown). Expandable tool rows show technical detail only.\n\n"
    "Reply with 1–3 short sentences in the same language as the user's chat messages "
    "(role user only), "
    "not the language of any attached document or filename. "
    'Use future or conditional wording only (e.g. "will", "after you approve", "proposed"). '
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

DEFAULT_INBOX_REVIEW_SUMMARY_USER_MESSAGE = (
    "The system detected one or more **Inbox reviews** that must be completed in the app "
    "before this assistant run can continue (separate from chat mutation Approve/Reject).\n\n"
    "Below is structured data for each pending review (record type, id, label, URL/path). "
    "Reply to the user in the same language as their chat messages (role user only): "
    "explain what needs doing, include the relevant link(s) in Markdown, and say you will "
    "continue automatically after they finish in Inbox. You may call **read-only** tools "
    "if you need more detail; do not call mutation tools."
)

# Before awaiting_inbox_review: optional streamed assistant turn(s) with read-only tools.
# - llm_stream: model may use read tools and stream text (default).
# - static: deterministic text from watch URLs/labels (no LLM).
# - none: emit barrier immediately (legacy).
InboxReviewSummaryMode = Literal["llm_stream", "static", "none"]

DEFAULT_WEB_SESSION_BARRIER_SUMMARY_USER_MESSAGE = (
    "There is an active browser session. Explain briefly what is running, "
    "include the **in-app** Web sessions link in Markdown "
    "(path like `/web-sessions?id=…` only — do not paste external or third-party "
    "live-view URLs), and say the assistant continues automatically when the "
    "session finishes. You may call **read-only** tools if you need more detail; "
    "do not call mutation tools."
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
    confirmation_summary_mode: ConfirmationSummaryMode = "llm_stream"
    inbox_review_summary_user_message: str = DEFAULT_INBOX_REVIEW_SUMMARY_USER_MESSAGE
    inbox_review_summary_mode: InboxReviewSummaryMode = "llm_stream"
    # Redis/memory TTL for runs on awaiting_inbox_review (longer than mutation pending).
    inbox_review_state_ttl_sec: int = 172_800
    # Before ``awaiting_web_session`` (async browse): same modes as
    # inbox review — optional streamed turn.
    web_session_barrier_summary_user_message: str = DEFAULT_WEB_SESSION_BARRIER_SUMMARY_USER_MESSAGE
    web_session_barrier_summary_mode: InboxReviewSummaryMode = "llm_stream"
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
    mutation_inbox_watches: dict[str, MutationInboxWatchFn] = field(default_factory=dict)
    verify_inbox_watch: VerifyInboxWatchFn | None = None
    # Optional: pending inbox ids before confirmed mutations (pair with inbox_scan_after_mutations).
    inbox_snapshot_before_mutations: InboxSnapshotFn | None = None
    # Optional: after the batch + per-tool watches, add watches (async pipelines, etc.).
    inbox_scan_after_mutations: InboxScanAfterMutationsFn | None = None
    # Optional: after inbox verify, new pending rows (e.g. expense_review after receipt HITL).
    inbox_scan_after_inbox_resume: InboxScanAfterInboxResumeFn | None = None
    # Optional: Docker terminal pool; when ``terminal_only_dispatch``, domain tools are not exposed
    # to the model — only ``hof_builtin_terminal_exec`` and ``builtins_when_terminal_only``.
    sandbox: SandboxConfig | None = None
    # Optional: when sandbox is enabled, stage chat S3 attachments into ``/workspace`` before the
    # first ``hof_builtin_terminal_exec`` in a run (so shell tools can read uploaded files).
    sandbox_stage_chat_attachments: SandboxStageChatAttachmentsFn | None = None
    # Optional: Browser Use Cloud — adds ``hof_builtin_browse_web`` to the model allowlist.
    browser: BrowserConfig | None = None
    # Resolve app constant values for ``sensitiveData`` (e.g. from ``list_constants``).
    browser_sensitive_data_fn: BrowserSensitiveDataFn | None = None
    # When True (default), browse returns after ``sessions.create``; poll runs in a background
    # thread; client resumes with ``iter_agent_resume_web_session_stream``. Set ``False`` or
    # ``HOF_BROWSER_ASYNC=0`` for synchronous full poll (debug).
    browser_async: bool = True

    def effective_allowlist(self) -> frozenset[str]:
        sc = self.sandbox.with_env_overrides() if self.sandbox is not None else None
        if sc is not None and sc.enabled and sc.terminal_only_dispatch:
            term = frozenset({HOF_BUILTIN_TERMINAL_EXEC})
            out = frozenset(sc.builtins_when_terminal_only) | term
            # Browser runs in Browser Use Cloud (not the sandbox shell); still expose it here
            # so terminal-only apps can browse without disabling HOF_SANDBOX_TERMINAL_ONLY.
            if self.browser is not None:
                out = out | frozenset({HOF_BUILTIN_BROWSE_WEB})
            return out
        base = frozenset(self.allowlist_read | self.allowlist_mutation | BUILTIN_AGENT_TOOL_NAMES)
        if self.browser is not None:
            base = base | frozenset({HOF_BUILTIN_BROWSE_WEB})
        if sc is not None and sc.enabled and not sc.terminal_only_dispatch:
            return base | frozenset({HOF_BUILTIN_TERMINAL_EXEC})
        return base

    def skills_catalog_allowlist(self) -> frozenset[str]:
        """Logical tools for ``GET /api/agent/tools`` (domain read/mutation + plan builtins).

        Unlike :meth:`effective_allowlist`, this always includes ``allowlist_read`` and
        ``allowlist_mutation`` even when ``terminal_only_dispatch`` hides them from the model.
        The terminal transport tool is never listed.
        """
        base = frozenset(self.allowlist_read | self.allowlist_mutation | BUILTIN_AGENT_TOOL_NAMES)
        if self.browser is not None:
            base = base | frozenset({HOF_BUILTIN_BROWSE_WEB})
        sc = self.sandbox.with_env_overrides() if self.sandbox is not None else None
        if sc is not None and sc.enabled and sc.terminal_only_dispatch:
            base = base | frozenset(sc.builtins_when_terminal_only)
        return base - frozenset({HOF_BUILTIN_TERMINAL_EXEC})

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
