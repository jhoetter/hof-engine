"""Built-in ``hof_builtin_browse_web`` registration."""

from __future__ import annotations

from typing import Any

from hof.browser.constants import HOF_BUILTIN_BROWSE_WEB
from hof.functions import function


@function(
    name=HOF_BUILTIN_BROWSE_WEB,
    tool_summary=(
        "Run a cloud browser agent to navigate websites, fill forms, click, and extract data."
    ),
    when_to_use=(
        "When the user needs real web interaction: log in, download, scrape visible UI, "
        "multi-step flows. Reference stored secrets as <secret:key_name> in the task text."
    ),
    when_not_to_use="For APIs or data already in this app — use read/list tools instead.",
)
def hof_builtin_browse_web(
    task: str,
    sensitive_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Executed via the agent stream runner, not this body.

    The stream layer calls :func:`hof.browser.runner.run_browser_cloud_task_sync` so the UI
    can receive ``web_session_*`` NDJSON events before the tool finishes.
    """
    return {
        "error": "hof_builtin_browse_web must be executed by the agent stream",
        "hint": "This tool is only available through the assistant agent.",
    }
