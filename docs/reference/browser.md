# Browser Use Cloud

hof-engine can expose **`hof_builtin_browse_web`** to the assistant when you configure
`AgentPolicy.browser` with a [`BrowserConfig`][hof.browser.config.BrowserConfig] and optional
`browser_sensitive_data_fn` for app constants / secrets.

## Dependencies

`browser-use-sdk` is a **core** dependency of hof-engine (no extra). Install or upgrade as usual:

```bash
pip install -U hof-engine
```

Set **`BROWSER_USE_API_KEY`** in the environment (or in `.env` loaded by `hof dev`). If you pass
`BrowserConfig(api_key="${BROWSER_USE_API_KEY}")`, hof-engine **resolves** that placeholder at
runtime via :func:`hof.browser.config.resolve_browser_api_key_value` — the literal string
``${BROWSER_USE_API_KEY}`` must never be sent to Browser Use Cloud.

## Policy

```python
from hof.agent.policy import AgentPolicy, configure_agent
from hof.browser.config import BrowserConfig

async def load_secrets() -> dict[str, str]:
    # e.g. read app constants from your DB
    return {"portal_user": "...", "portal_pass": "..."}

configure_agent(
    AgentPolicy(
        allowlist_read=frozenset({...}),
        allowlist_mutation=frozenset({...}),
        system_prompt_intro="...",
        browser=BrowserConfig(
            api_key="${BROWSER_USE_API_KEY}",
            sensitive_keys_for_prompt=("portal_user", "portal_pass"),
        ),
        browser_sensitive_data_fn=load_secrets,
    )
)
```

List **`sensitive_keys_for_prompt`** so the system prompt tells the model which `<secret:key>`
placeholders exist. At runtime, **`browser_sensitive_data_fn`** returns a string dict; the browse
tool can filter keys via its **`sensitive_keys`** argument. Values are sent to Browser Use Cloud as
**`sensitiveData`** on session create (camelCase JSON).

## Tool

- **`task`** (required): natural-language instructions; use `<secret:portal_user>` etc. in text.
- **`sensitive_keys`** (optional): subset of keys to include from `browser_sensitive_data_fn`.

## NDJSON stream

The agent stream emits:

| Type | Meaning |
|------|---------|
| `web_session_started` | `session_id`, `live_url`, `task`, `sse_channel` |
| `web_session_step` | Per message from the cloud session |
| `web_session_ended` | Final `output`, `recording_urls`, `status` |

Session metadata and messages are cached under **`hof:web_session:{id}`** in Redis when
`REDIS_URL` is set (in-memory fallback otherwise).

## REST API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/web-sessions/{session_id}` | Metadata + message list |
| GET | `/api/web-sessions/{session_id}/messages` | Messages only |
| POST | `/api/web-sessions/{session_id}/stop` | Stop task (`strategy=task`) |
| GET | `/api/web-sessions/{session_id}/recording` | Poll recording URLs |

## React (`@hof-engine/react`)

- **`WebSessionCanvas`**: embeds `liveUrl` and polls `/api/web-sessions/.../messages`; subscribes to
  `/api/sse/{sse_channel}` when available.
- **`isAssistantWebSessionEmbedLink` / `toWebSessionEmbedSrc`**: same pattern as inbox review
  embeds — intercept Markdown links to `/web-sessions?id=…` and open your host route beside the chat.

Host app checklist:

1. Route **`/web-sessions`** rendering `WebSessionCanvas` (read `id` from query).
2. Pass `onAssistantMarkdownLinkClick` to `HofAgentChatProvider` and call
   `isAssistantWebSessionEmbedLink` to open the aside / canvas.

[hof.browser.config.BrowserConfig]: ../../hof/browser/config.py
