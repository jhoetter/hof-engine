"""Built-in read-only agent tools.

Registered when ``discover_all`` finishes so app ``@function`` modules load first; reserved
``hof_builtin_*`` names then win on collision. Always on ``AgentPolicy.effective_allowlist()``.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from hof.agent.sandbox.context import resolve_sandbox_run_state
from hof.agent.sandbox.token import mint_sandbox_bearer_token
from hof.agent.tooling import get_tool_execution_run_id, get_tool_execution_tool_call_id
from hof.functions import function

logger = logging.getLogger(__name__)


@function(
    name="hof_builtin_present_plan",
    tool_summary=(
        "Present a structured plan to the user for review and approval. "
        "After calling this tool, STOP — do not write any assistant text."
    ),
    when_to_use=(
        "When you have enough context to propose a concrete plan. "
        "Call with title, description, and steps."
    ),
    when_not_to_use=(
        "When you still need clarification from the user — "
        "use hof_builtin_present_plan_clarification instead."
    ),
)
def hof_builtin_present_plan(
    title: str,
    description: str,
    steps: list,
) -> dict[str, Any]:
    """Intercepted by the stream loop; this body is never reached.

    Validated server-side via :class:`~hof.agent.plan_types.PlanProposal`.
    ``steps``: list of ``{label: str}`` objects.
    """
    return {"status": "intercepted"}


@function(
    name="hof_builtin_present_plan_clarification",
    tool_summary=(
        "Show the user multiple-choice clarification questions during plan discovery. "
        "The UI renders each question as a card with selectable options. "
        "After calling this tool, STOP — do not write any assistant text."
    ),
    when_to_use=(
        "In plan discovery, call this **after** your first exploration summary, whenever "
        "the work could be scoped or delivered in more than one way. "
        "Fill `questions` with 2–5 items (scope, format, timeframe, filters, priorities). "
        "Use exploration tool results to write **specific** option labels. "
        "Then STOP (no assistant text after the tool call)."
    ),
    when_not_to_use=(
        "Use `hof_builtin_present_plan` instead once clarification answers are already in the "
        "thread and you are ready to output the structured plan proposal."
    ),
)
def hof_builtin_present_plan_clarification(questions: list) -> dict[str, Any]:
    """Intercepted by the stream loop; this body is never reached.

    ``questions`` is validated server-side via
    :class:`~hof.agent.plan_types.PlanClarificationQuestion`.
    Required shape: ``{id, prompt, options: [{id, label, is_other?}], allow_multiple}``.
    ``key``/``label``/``hint`` are accepted as aliases for ``id``/``prompt``.
    ``options`` (at least 2) is **required** — omitting it causes a validation
    error returned to the model so it can retry with correct choices.
    If no option has ``is_other: true``, the server appends ``Other / specify``.
    """
    return {"status": "intercepted"}


@function(
    name="hof_builtin_update_plan_todo_state",
    tool_summary="Mark plan checklist items as completed during plan execution.",
    when_to_use="After completing one or more steps in the approved plan, call this "
    "with the 0-based indices of the finished items.",
    when_not_to_use="Outside plan execution mode.",
)
def hof_builtin_update_plan_todo_state(done_indices: list) -> dict[str, Any]:
    raw = done_indices or []
    idxs: list[int] = []
    for x in raw:
        try:
            idxs.append(int(x))
        except (TypeError, ValueError):
            continue
    return {"done_indices": idxs}


def _sandbox_api_environment() -> dict[str, str]:
    from hof.agent.policy import try_get_agent_policy
    from hof.agent.sandbox.config import SandboxConfig

    policy = try_get_agent_policy()
    sc = getattr(policy, "sandbox", None)
    if not isinstance(sc, SandboxConfig):
        return {}
    sc = sc.with_env_overrides()
    env: dict[str, str] = {}
    base = (sc.api_base_url or "").strip()
    if not base:
        # Same vars apps often use for the Hof API (no HOF_SANDBOX_* required).
        for key in ("HOF_API_BASE", "VITE_HOF_API", "HOF_SANDBOX_API_BASE_URL"):
            cand = (os.environ.get(key) or "").strip()
            if cand:
                base = cand
                break
    if not base:
        try:
            from hof.config import get_config

            cfg = get_config()
            port = getattr(cfg, "port", 8001)
            base = f"http://127.0.0.1:{port}"
        except Exception:
            base = "http://127.0.0.1:8001"
    env["API_BASE_URL"] = base.rstrip("/")
    env["HOF_FN_FORMAT"] = "json"
    tok = (sc.api_token or "").strip()
    if not tok:
        tok = (os.environ.get("HOF_SANDBOX_API_TOKEN") or os.environ.get("HOF_TOKEN") or "").strip()
    if tok:
        env["API_TOKEN"] = tok
    else:
        minted = mint_sandbox_bearer_token()
        if minted:
            env["API_TOKEN"] = minted
        else:
            # Fallback when ``jwt_secret_key`` is unset: HTTP Basic (``HOF_ADMIN_PASSWORD``).
            basic_pw = (
                os.environ.get("HOF_SANDBOX_BASIC_PASSWORD")
                or os.environ.get("HOF_ADMIN_PASSWORD")
                or ""
            ).strip()
            if basic_pw:
                try:
                    from hof.config import get_config

                    cfg = get_config()
                    default_user = (
                        getattr(cfg, "admin_username", None) or "admin"
                    ).strip() or "admin"
                except Exception:
                    default_user = "admin"
                env["HOF_BASIC_USER"] = (
                    os.environ.get("HOF_SANDBOX_BASIC_USER") or ""
                ).strip() or default_user
                env["HOF_BASIC_PASSWORD"] = basic_pw
    pol = try_get_agent_policy()
    if pol is not None:
        try:
            cat = pol.skills_catalog_allowlist()
            env["HOF_AGENT_SKILLS_CATALOG"] = "\n".join(sorted(cat))
        except Exception:
            logger.debug("sandbox: could not build HOF_AGENT_SKILLS_CATALOG", exc_info=True)
    return env


def _sandbox_per_exec_agent_headers_env() -> dict[str, str]:
    """Per ``docker exec`` vars so curl can pass mutation correlation headers."""
    out: dict[str, str] = {}
    rid = get_tool_execution_run_id()
    if rid and str(rid).strip():
        out["HOF_AGENT_RUN_ID"] = str(rid).strip()
    tid = get_tool_execution_tool_call_id()
    if tid and str(tid).strip():
        out["HOF_AGENT_TOOL_CALL_ID"] = str(tid).strip()
    return out


@function(
    name="hof_builtin_terminal_exec",
    tool_summary=(
        "Run a shell command in the isolated sandbox (workspace under /workspace). "
        "Prefer **`hof fn list`**, **`hof fn describe <name>`**, **`hof fn <name> '<json>'`** "
        "(installed in the container, same as the host Hof CLI). "
        "For data-app reads use **`hof fn read_data '<json>'`**. "
        "Use raw curl only when needed."
    ),
    when_to_use=(
        "For normal shell work (python, jq, pipes) and for app data via **`hof fn …`** "
        "(e.g. **`hof fn read_data`** in spreadsheet sandbox), or "
        "generated `list-*` CLIs — the path to skills when terminal-only dispatch is enabled."
    ),
    when_not_to_use=(
        "Not for separate JSON tools to domain functions; those are not exposed to the model."
    ),
)
def hof_builtin_terminal_exec(command: str) -> dict[str, Any]:
    """Execute ``command`` via ``docker exec`` in a pooled container (see ``hof.agent.sandbox``)."""
    from hof.agent.policy import try_get_agent_policy
    from hof.agent.sandbox.config import SandboxConfig
    from hof.agent.sandbox.context import get_sandbox_run
    from hof.agent.sandbox.pool import get_container_pool
    from hof.agent.sandbox.session import create_session_for_run

    policy = try_get_agent_policy()
    sc = getattr(policy, "sandbox", None)
    if not isinstance(sc, SandboxConfig):
        return {"error": "sandbox is not configured on AgentPolicy"}
    sc = sc.with_env_overrides()
    if not sc.enabled:
        return {
            "error": (
                "sandbox is disabled — set AgentPolicy.sandbox.enabled=True in configure_agent, "
                "or optional env HOF_SANDBOX_ENABLED=1"
            )
        }
    tool_rid = get_tool_execution_run_id()
    run = resolve_sandbox_run_state(tool_rid)
    if run is None:
        logger.warning(
            "hof_builtin_terminal_exec: missing sandbox state (tool_run_id=%r ctx_var=%s)",
            tool_rid,
            get_sandbox_run() is not None,
        )
        return {"error": "sandbox run context is not set"}
    if run.terminal_session is None:
        pool = get_container_pool(sc)
        env = _sandbox_api_environment()
        run.terminal_session = create_session_for_run(
            pool,
            workdir="/workspace",
            environment=env,
            max_output_chars=sc.max_output_chars,
            max_timeout_sec=sc.max_exec_timeout_sec,
        )
        stage_fn = getattr(policy, "sandbox_stage_chat_attachments", None)
        if not run.sandbox_attachments_staged:
            atts = run.chat_attachments or []
            if atts and callable(stage_fn):
                try:
                    stage_fn(run.terminal_session, atts)
                except Exception as exc:
                    logger.exception("sandbox_stage_chat_attachments failed")
                    return {
                        "exit_code": 1,
                        "output": (
                            f"error: could not copy chat attachments into /workspace: {exc}"
                        ),
                    }
            run.sandbox_attachments_staged = True
    cmd = (command or "").strip() or "true"
    result = run.terminal_session.exec_command(
        cmd,
        extra_env=_sandbox_per_exec_agent_headers_env(),
    )
    return {"exit_code": result.exit_code, "output": result.output}


# Browser Use Cloud tool (optional ``browser-use-sdk`` extra).
try:
    import hof.browser.tools  # noqa: F401
except ImportError:
    pass
