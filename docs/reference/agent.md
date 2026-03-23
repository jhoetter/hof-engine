# Agent (OpenAI tool loop)

The **Hof agent** runs an OpenAI chat completion with tools bound to registered `@function` handlers. Streaming uses **llm-markdown** (`OpenAIProvider.stream_chat_completion_events`) so tool deltas, optional reasoning text, and usage chunks are normalized before being mapped to NDJSON. Read tools execute immediately; **mutation** tools pause until the user confirms in the UI or via `POST /api/functions/agent_resume_mutations` (same NDJSON stream contract as `agent_chat`).

## Setup

1. **Configure a policy** at import time in your `functions/` package (before any chat runs):

```python
from hof.agent import AgentPolicy, configure_agent

configure_agent(
    AgentPolicy(
        allowlist_read=frozenset({"list_items", "get_item"}),
        allowlist_mutation=frozenset({"create_item"}),
        system_prompt_intro="You are …\n",
        # Optional: tool_internal_rationale (short UI hints),
        # tool_when_to_use / tool_related_tools (merged into OpenAI tool descriptions + hof fn describe),
        # normalize_attachments, attachments_system_note
    ),
)
```

2. **Register streaming functions** (same pattern as spreadsheet-app):

```python
from hof import function
from hof.agent import collect_agent_chat_from_stream, iter_agent_chat_stream, iter_agent_resume_stream

@function(tags=["ai"], stream=iter_agent_chat_stream)
def agent_chat(messages: list, attachments: list | None = None) -> dict:
    return collect_agent_chat_from_stream(iter_agent_chat_stream(messages, attachments))

@function(tags=["ai"], stream=iter_agent_resume_stream)
def agent_resume_mutations(run_id: str, resolutions: list) -> dict:
    return collect_agent_chat_from_stream(iter_agent_resume_stream(run_id, resolutions))
```

3. **HTTP**: use `POST /api/functions/agent_chat/stream` and `POST /api/functions/agent_resume_mutations/stream` (NDJSON). Non-streaming `POST /api/functions/agent_chat` folds the same events into JSON.

## Configuration (`hof.config.py`)

| Field | Purpose |
|--------|---------|
| `llm_api_key` | Used when `OPENAI_API_KEY` is unset |
| `llm_model` | Fallback model when `agent_model` and env are empty |
| `agent_model` | Preferred agent model (overridden by `AGENT_MODEL` / `LLM_MARKDOWN_MODEL` env) |
| `agent_max_rounds` | Max model turns (default `10`) |
| `agent_max_tool_output_chars` | Truncate tool JSON (default `18000`) |
| `agent_max_model_text_chars` | Legacy JSON trace truncation (default `8000`) |
| `agent_max_cli_line_chars` | Pseudo-CLI width for UI (default `240`) |

**Dependency:** `llm-markdown[openai]` **0.3.4+** with `OpenAIProvider.stream_chat_completion_events`. The lockfile may pin the Git tag `v0.3.4` until the package is published to PyPI; after publishing, depend on `llm-markdown[openai]>=0.3.4` from PyPI only. The agent requests up to **128_000** completion tokens per turn (high ceiling; the model still enforces its own cap).

**Reasoning / chain-of-thought:** When the OpenAI stream exposes `reasoning_content` (or `reasoning`) on deltas, the server emits NDJSON `reasoning_delta` lines. Clients should treat them like other incremental thinking text (see your app’s `agent-chat-stream.md`).

**Anthropic:** `llm-markdown` also provides `AnthropicProvider.stream_messages_events` (tools + optional extended thinking) for reuse in custom code; the stock Hof `agent_chat` stream remains OpenAI-backed.

## State

Pending runs and mutation placeholders are stored in **Redis** when `REDIS_URL` is set; otherwise **in-process** memory (not safe across multiple workers).

## Security

- Direct `POST /api/functions/<mutation>` still runs immediately.
- Only the agent path wraps mutations in `pending_confirmation` + user approval.
- Validate attachments in `AgentPolicy.normalize_attachments` (e.g. tenant S3 prefix).

## React UI

`@hof-engine/react` exports **`HofAgentChat`**: conversation + composer only (no FAB, no fixed panel). The host app owns layout (full page, sidebar, slide-over) and passes `welcomeName` and `presignUpload`.

Stream types and tool rendering stay aligned with your app’s NDJSON contract; see your app’s `docs/agent-chat-stream.md` if present.
