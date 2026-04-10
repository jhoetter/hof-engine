"""Docker-backed terminal sandbox for agent CLI execution."""

from hof.agent.sandbox.config import SandboxConfig, merge_sandbox_config
from hof.agent.sandbox.constants import HOF_BUILTIN_TERMINAL_EXEC
from hof.agent.sandbox.context import (
    get_sandbox_run,
    release_bound_terminal_session,
    reset_sandbox_run,
    set_sandbox_run,
)
from hof.agent.sandbox.mutation_bridge import (
    AGENT_RUN_HEADER_NAME,
    AGENT_TOOL_CALL_HEADER_NAME,
    PENDING_CONFIRMATION_KEY,
    PENDING_ID_KEY,
)
from hof.agent.sandbox.pool import get_container_pool
from hof.agent.sandbox.session import TerminalResult, TerminalSession, create_session_for_run
from hof.agent.sandbox.skill_cli import write_skill_cli_tree
from hof.agent.sandbox.token import mint_sandbox_bearer_token

__all__ = [
    "AGENT_RUN_HEADER_NAME",
    "AGENT_TOOL_CALL_HEADER_NAME",
    "HOF_BUILTIN_TERMINAL_EXEC",
    "PENDING_CONFIRMATION_KEY",
    "PENDING_ID_KEY",
    "SandboxConfig",
    "TerminalResult",
    "TerminalSession",
    "create_session_for_run",
    "get_container_pool",
    "get_sandbox_run",
    "merge_sandbox_config",
    "mint_sandbox_bearer_token",
    "release_bound_terminal_session",
    "reset_sandbox_run",
    "set_sandbox_run",
    "write_skill_cli_tree",
]
