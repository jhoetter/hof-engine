# Agent (OpenAI tool loop)

The **Hof agent** runs an OpenAI chat completion with tools bound to registered `@function` handlers. Streaming uses **llm-markdown** [`stream_agent_turn`](https://github.com/jhoetter/llm-markdown/blob/main/llm_markdown/agent_turn.py) with [`ReasoningConfig`](https://github.com/jhoetter/llm-markdown/blob/main/llm_markdown/reasoning.py) (wrapper over `OpenAIProvider.stream_chat_completion_events`) so tool deltas, optional reasoning text, and usage chunks are normalized before being mapped to NDJSON. Read tools execute immediately; **mutation** tools pause until the user confirms in the UI or via `POST /api/functions/agent_resume_mutations` (same NDJSON stream contract as `agent_chat`).

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
| `agent_max_completion_tokens` | Max completion tokens per OpenAI request (default `16384`; overridden by `AGENT_MAX_COMPLETION_TOKENS` env) |
| `agent_reasoning_mode` | `native` (default), `off` (no `reasoning_delta` on the wire), or `fallback` (two-phase planning + tools via llm-markdown). Overridden by `AGENT_REASONING_MODE` env when set. |

**Env (reasoning):** `AGENT_REASONING_OPENAI_EXTRAS` — optional JSON object merged into the OpenAI chat request when mode is `native` (e.g. model-specific reasoning parameters). Incompatible with `agent_reasoning_mode` / `AGENT_REASONING_MODE` `off`.

**Dependency:** `llm-markdown[openai]` **>=0.3.8** on PyPI (`stream_agent_turn`, `AgentSegmentStart`, `ReasoningConfig`, `ReasoningMode.fallback`). Capability matrix: [llm-markdown `docs/agent-streaming.md`](https://github.com/jhoetter/llm-markdown/blob/main/docs/agent-streaming.md). The default completion budget is **16_384** tokens so common chat models accept the request; raise it in config or `AGENT_MAX_COMPLETION_TOKENS` (capped at **128_000**) when your model allows more.

**Observability:** At **INFO**, logger `hof.agent.stream` emits `agent_chat …` lines to the API process stdout (uvicorn terminal): run start, each model round (`finish_reason`, delta counts, assistant text preview), each `tool_call` / `tool_done`, `awaiting_confirmation`, and `final`. No `.env` toggle required. Optional **`HOF_AGENT_STREAM_DEBUG_LOG`** still appends structured NDJSON to a file (see your app’s `agent-chat-stream.md`).

**Reasoning / “thinking” text:** Hof does not invent reasoning text in **native** mode. **`agent_reasoning_mode=native`** (default) forwards provider-native `AgentReasoningDelta` events; **`off`** strips them even if the model emits them. **`fallback`** uses llm-markdown’s provider-agnostic planning stream (synthetic `AgentReasoningDelta` from the planning phase) plus a tool turn; the tool-capable phase **forwards** provider reasoning when present. **`reasoning_delta` still only appears from the model in native mode when the OpenAI stream carries `reasoning_content` / `reasoning` on deltas** — e.g. **`gpt-4o` typically does not**, so `reasoning_deltas=0` in logs is normal unless you use **`fallback`**. Use a **reasoning-capable** model plus optional `AGENT_REASONING_OPENAI_EXTRAS` when your API supports it; see **llm-markdown** [docs/agent-streaming.md](https://github.com/jhoetter/llm-markdown/blob/main/docs/agent-streaming.md).

**NDJSON (tool rounds):** When tools are enabled, the stream may include **`segment_start`** objects: `{"type":"segment_start","segment":"reasoning"|"content"}`. These mirror llm-markdown **`AgentSegmentStart`**: the turn always opens with `reasoning`; the first `assistant_delta` or tool-call assembly is preceded by `segment":"content"`. Clients can open the thinking lane without inferring from the first delta type. Existing `reasoning_delta` / `assistant_delta` lines are unchanged.

Without streamed reasoning, the observable tool chain is: `assistant_done` (`finish_reason: tool_calls`) → `tool_call` → `tool_result` → `assistant_delta` / `final`.

`@hof-engine/react` consumes `segment_start` and `reasoning_delta` / `assistant_delta` for ordered reasoning vs reply segments.

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
