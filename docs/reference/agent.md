# Agent (tool loop)

The **Hof agent** runs a chat completion with tools bound to registered `@function` handlers (default **OpenAI**; optional **Anthropic**). Streaming uses **llm-markdown** [`stream_agent_turn`](https://github.com/jhoetter/llm-markdown/blob/main/llm_markdown/agent_turn.py) with [`ReasoningConfig`](https://github.com/jhoetter/llm-markdown/blob/main/llm_markdown/reasoning.py) so tool deltas, optional reasoning text, and usage chunks are normalized before being mapped to NDJSON. Read tools execute immediately; **mutation** tools pause until the user confirms in the UI or via `POST /api/functions/agent_resume_mutations` (same NDJSON stream contract as `agent_chat`).

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
| `agent_reasoning_mode` | `native` (default), `off`, or explicit `fallback`. Overridden by `AGENT_REASONING_MODE` env when set. **Semantics:** see “Thinking on every turn” below — OpenAI and Anthropic interpret `native` differently. |
| (env) `AGENT_LLM_BACKEND` | `openai` (default) or `anthropic`. With `anthropic`, set **`ANTHROPIC_API_KEY`** and a Claude model id in **`AGENT_MODEL`** / **`LLM_MARKDOWN_MODEL`**. Saved mutation runs include `llm_backend` so resume uses the same provider. |

**Thinking on every turn (default `agent_reasoning_mode=native`):**

- **Anthropic:** Hof uses adaptive [extended thinking](https://platform.claude.com/docs/en/build-with-claude/adaptive-thinking) and **always** passes `thinking={"type": "adaptive"}` (unless `AGENT_ANTHROPIC_THINKING=off`) **and** `output_config={"effort": "high"}` on every `messages.stream` call so short prompts still receive thinking blocks. Not configurable via a separate effort env var.

- **OpenAI (default `AGENT_LLM_BACKEND=openai`):** Chat Completions on common chat models (e.g. `gpt-4o-mini`) usually emit **no** `reasoning_delta` in true native mode. So when `native` is selected and **`AGENT_REASONING_OPENAI_EXTRAS` is unset**, Hof automatically uses llm-markdown **`fallback`** (two-phase planning + tools) so **every** agent turn still streams a thinking lane. To use **Chat Completions native** reasoning instead (e.g. o-series / models that support `reasoning_effort`), set **`AGENT_REASONING_OPENAI_EXTRAS`** to any JSON object — even `{}` — and Hof uses **native** mode and merges **`reasoning_effort: "high"`** into that object (your keys override).

**Env (reasoning):** `AGENT_REASONING_OPENAI_EXTRAS` — optional JSON object. **Unset** → OpenAI backend uses **fallback** for thinking visibility (see above). **Set** → native Chat Completions with merged `reasoning_effort`. Incompatible with `off`. **Not used when `AGENT_LLM_BACKEND=anthropic`.**

**Env (Anthropic thinking):** `AGENT_ANTHROPIC_THINKING` — when backend is `anthropic` and mode resolves to **native** (including when config asks for `fallback`; see below). Unset → `{"type": "adaptive"}`. `off` / `false` / `0` / `no` → omit `thinking` on the API request. Any other value must be a JSON object passed through to `messages.stream` (e.g. extended thinking with `budget_tokens` on older models).

**Anthropic + `fallback`:** If `agent_reasoning_mode` / `AGENT_REASONING_MODE` is `fallback` but **`AGENT_LLM_BACKEND=anthropic`**, Hof **upgrades to native** and applies `AGENT_ANTHROPIC_THINKING` instead. The two-phase llm-markdown fallback is intended for OpenAI-style models without provider-native reasoning; Claude uses adaptive thinking instead.

**Dependency:** `llm-markdown[openai,anthropic]` **>=0.3.17** (`stream_agent_turn`, `AgentSegmentStart`, `ReasoningConfig`, `ReasoningMode.fallback`). Capability matrix: [llm-markdown `docs/agent-streaming.md`](https://github.com/jhoetter/llm-markdown/blob/main/docs/agent-streaming.md). The default completion budget is **16_384** tokens so common chat models accept the request; raise it in config or `AGENT_MAX_COMPLETION_TOKENS` (capped at **128_000**) when your model allows more.

**Observability:** At **INFO**, logger `hof.agent.stream` emits `agent_chat …` lines to the API process stdout (uvicorn terminal): run start, each model round (`finish_reason`, delta counts, assistant text preview), each `tool_call` / `tool_done`, `awaiting_confirmation`, and `final`. No `.env` toggle required. Optional **`HOF_AGENT_STREAM_DEBUG_LOG`** still appends structured NDJSON to a file (see your app’s `agent-chat-stream.md`).

**Reasoning / “thinking” text:** With default **`native`**, Hof is tuned so **both** backends stream a thinking lane (see “Thinking on every turn” above). **`off`** strips `AgentReasoningDelta` even if the model emits them. Explicit **`fallback`** uses llm-markdown’s two-phase planning stream on **OpenAI**; with **Anthropic**, `fallback` in config is upgraded to adaptive native thinking. See **llm-markdown** [docs/agent-streaming.md](https://github.com/jhoetter/llm-markdown/blob/main/docs/agent-streaming.md).

**NDJSON (tool rounds):** When tools are enabled, the stream may include **`segment_start`** objects: `{"type":"segment_start","segment":"reasoning"|"content"}`. These mirror llm-markdown **`AgentSegmentStart`**: the turn always opens with `reasoning`; the first `assistant_delta` or tool-call assembly is preceded by `segment":"content"`. Clients can open the thinking lane without inferring from the first delta type. Existing `reasoning_delta` / `assistant_delta` lines are unchanged.

Without streamed reasoning, the observable tool chain is: `assistant_done` (`finish_reason: tool_calls`) → `tool_call` → `tool_result` → `assistant_delta` / `final`.

`@hof-engine/react` consumes `segment_start` and `reasoning_delta` / `assistant_delta` for ordered reasoning vs reply segments.

**Anthropic:** set `AGENT_LLM_BACKEND=anthropic` and `ANTHROPIC_API_KEY`. The same NDJSON stream and tool loop apply; `stream_agent_turn` uses the Messages API with **`thinking=`** (default adaptive) and fixed **`output_config.effort=high`** whenever thinking is enabled.

## Built-in agent tools

These **read-only** tools are always part of the effective allowlist (`AgentPolicy.effective_allowlist()`): they are merged with your `allowlist_read` and `allowlist_mutation` names. They are **not** mutation tools (no confirmation step). Implementations live in the framework; modules register at the end of **`discover_all`** so app `functions/` load first and reserved `hof_builtin_*` names win on accidental collision.

| Tool | Purpose |
|------|---------|
| `hof_builtin_server_time` | UTC ISO time, unix timestamp, server-local ISO; optional `iana_timezone` (IANA name, e.g. `Europe/Berlin`) for `requested_zone_iso`. |
| `hof_builtin_runtime_info` | `hostname`, OS/platform string, Python version, **`hof-engine` package version**, and `app_name` when `hof.config` is loaded. |
| `hof_builtin_http_get` | GET a URL; returns `status_code`, `content_type`, and UTF-8 `text` (truncated). |
| `hof_builtin_calculate` | Numeric math: `expression` or batch `expressions` (simpleeval), or `values` + `operation` / `operations` for aggregates (`sum`, `mean`, `min`, `max`, `median`, `product`, `count`). |

**Calculate (`hof_builtin_calculate`):**

- **Expression mode:** literals, `+ - * / // % **`, comparisons, parentheses; functions `int`, `float`, `abs`, `round`, `min`, `max`, `sum`, `pow`, `sqrt`, `floor`, `ceil`; constants `pi`, `e`, `True`/`False`/`None`. List/tuple literals allowed (EvalWithCompoundTypes). Not a general Python or shell runner.
- **Batch expression mode:** send **`expressions`** as an array of strings (each evaluated like `expression`). Mutually exclusive with **`values`** and with a singular **`expression`**. Response: `mode: batch_expression`, `results`: `[{ "index": 0, "result": … }, { "index": 1, "error": "…" }, …]`.
- **Aggregate mode:** send **`values`** and **`operation`** (one stat) or **`operations`** (several stats in one call). **`operations`** is a string array, a JSON-array string, or comma-separated names (e.g. `sum, mean`). If both **`operation`** and **`operations`** are set, the server merges them (**`operations` first**, then appends **`operation`** if not already listed). With a **single** op, the response keeps **`operation`** + **`result`** (backward compatible). With **multiple** ops, the response uses **`results`**: `{ "sum": 6, "mean": 2 }` (per-op failures appear as `{ "error": "…" }` under that op key). For table columns, prefer **one** call with all numbers in **`values`** and **`operations`**, not one call per row.
- **Values parsing:** Prefer a JSON **array of numbers**; the server also accepts a **string** containing a JSON array (e.g. tooling that double-encodes), **comma-separated** numbers (`1, 2, 3.5`), **numeric strings** inside the array, or a **single number**. If both `values` and `expression` are present, **aggregate wins** and `ignored_expression` is set when `expression` was non-empty.
- **Limits:** `HOF_AGENT_CALC_MAX_EXPRESSION_CHARS` (default **4096**, hard max **64000**), `HOF_AGENT_CALC_MAX_VALUES` (default **10000**, hard max **50000**), `HOF_AGENT_CALC_MAX_BATCH_EXPRESSIONS` (default **200**, hard max **1000**).

**Fetch safety (`hof_builtin_http_get`):**

- **HTTPS:** the hostname must resolve only to **public** addresses (`ipaddress.is_global`). Link-local, loopback, and private ranges are rejected (SSRF mitigation).
- **HTTP:** allowed only for hostnames `localhost`, `127.0.0.1`, or `::1`; resolved IPs must be **loopback**.
- **Redirects:** disabled (`follow_redirects=False`).
- **Size / time:** response body is capped (default **512 KiB**, hard max **2 MiB**). Override with **`HOF_AGENT_FETCH_MAX_BYTES`**. Timeout default **15s**; cap with **`HOF_AGENT_FETCH_TIMEOUT_SECONDS`** (1–120).

They appear in `GET /api/agent/tools` like any other registered function once discovery has run (same as the dev server and CLI bootstrap).

## State

Pending runs and mutation placeholders are stored in **Redis** when `REDIS_URL` is set; otherwise **in-process** memory (not safe across multiple workers).

## Security

- Direct `POST /api/functions/<mutation>` still runs immediately.
- Only the agent path wraps mutations in `pending_confirmation` + user approval.
- Validate attachments in `AgentPolicy.normalize_attachments` (e.g. tenant S3 prefix).
- Built-in **`hof_builtin_http_get`** is not a general egress proxy: no redirects, strict host/IP rules, bounded body size (see **Built-in agent tools**).
- Built-in **`hof_builtin_calculate`** evaluates only whitelisted numeric expressions and aggregates; it does not execute arbitrary code.

## React UI

`@hof-engine/react` exports **`HofAgentChat`**: conversation + composer only (no FAB, no fixed panel). The host app owns layout (full page, sidebar, slide-over) and passes `welcomeName` and `presignUpload`.

Stream types and tool rendering stay aligned with your app’s NDJSON contract; see your app’s `docs/agent-chat-stream.md` if present.
