"""Composable agent extension registry.

Domain modules (starters, custom code) register :class:`AgentExtension`
objects at import time.  The application calls :func:`discover_domain_extensions`
before :func:`~hof.agent.policy.configure_agent` to auto-import
``domain/agent_hooks.py`` and ``domain/*/agent_hooks.py``, then
:func:`merge_extensions` folds all registered extensions into the platform
base configuration.

Typical usage in a domain module::

    # domain/my_entity/agent_hooks.py
    from hof.agent.extensions import AgentExtension, register_agent_extension

    register_agent_extension(AgentExtension(
        name="my_entity",
        allowlist_mutation=frozenset({"create_my_entity", ...}),
        mutation_preview={"create_my_entity": my_preview_fn},
        system_prompt_section="## My Entity\\n\\nEntity value: `my_entity`.",
    ))
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

from hof.agent.policy import (
    InboxScanAfterInboxResumeFn,
    InboxScanAfterMutationsFn,
    InboxSnapshotFn,
    MutationInboxWatchFn,
    MutationPostApplyFn,
    MutationPreviewFn,
    VerifyInboxWatchFn,
)

logger = logging.getLogger("hof.agent.extensions")

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class AgentExtension:
    """A domain module's contribution to the agent policy.

    Each field is optional.  The merge step unions allowlists, merges dicts,
    and concatenates system prompt sections.
    """

    name: str = ""

    allowlist_read: frozenset[str] = frozenset()
    allowlist_mutation: frozenset[str] = frozenset()
    #: Mutation tools whose execution depends on the agent sandbox being alive
    #: (e.g. they read files from ``/workspace``). When any such mutation is
    #: pending after ``awaiting_confirmation``, the engine defers releasing the
    #: terminal session so the workspace is still populated when the user
    #: resumes the run via ``agent_resume_mutations``.
    sandbox_required: frozenset[str] = frozenset()

    tool_internal_rationale: dict[str, str] = field(default_factory=dict)
    tool_when_to_use: dict[str, str] = field(default_factory=dict)
    tool_related_tools: dict[str, list[str]] = field(default_factory=dict)
    tool_param_hints: dict[str, str] = field(default_factory=dict)

    mutation_preview: dict[str, MutationPreviewFn] = field(default_factory=dict)
    mutation_post_apply: dict[str, MutationPostApplyFn] = field(default_factory=dict)
    mutation_inbox_watches: dict[str, MutationInboxWatchFn] = field(default_factory=dict)

    inbox_snapshot_before_mutations: InboxSnapshotFn | None = None
    inbox_scan_after_mutations: InboxScanAfterMutationsFn | None = None
    inbox_scan_after_inbox_resume: InboxScanAfterInboxResumeFn | None = None
    verify_inbox_watch: VerifyInboxWatchFn | None = None

    system_prompt_section: str = ""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_EXTENSIONS: list[AgentExtension] = []


def register_agent_extension(ext: AgentExtension) -> None:
    """Register a domain extension (call at module-level in ``agent_hooks.py``)."""
    _EXTENSIONS.append(ext)
    logger.debug("Registered agent extension: %s", ext.name or "(unnamed)")


def get_all_extensions() -> list[AgentExtension]:
    """Return a copy of the registered extensions list."""
    return list(_EXTENSIONS)


# ---------------------------------------------------------------------------
# Auto-discovery
# ---------------------------------------------------------------------------

_DOMAIN_DIR_NAME = "domain"


def discover_domain_extensions(*, app_root: Path | None = None) -> None:
    """Import ``domain/agent_hooks.py`` and ``domain/*/agent_hooks.py``.

    *app_root* defaults to the parent of the ``functions/`` directory that
    contains the caller's ``agent_assistant.py``.  Pass explicitly when the
    default heuristic does not apply.

    Silently skips when ``domain/`` does not exist (clean platform mode).
    """
    if app_root is None:
        import inspect

        frame = inspect.stack()[1]
        caller_path = Path(frame.filename).resolve()
        app_root = caller_path.parent.parent

    domain_dir = app_root / _DOMAIN_DIR_NAME

    if not domain_dir.is_dir():
        logger.debug("No domain/ directory — clean platform mode, skipping extension discovery")
        return

    root_hooks = domain_dir / "agent_hooks.py"
    if root_hooks.is_file():
        _safe_import(f"{_DOMAIN_DIR_NAME}.agent_hooks", root_hooks)

    for entity_dir in sorted(domain_dir.iterdir()):
        if not entity_dir.is_dir() or entity_dir.name.startswith(("_", ".")):
            continue
        hooks_file = entity_dir / "agent_hooks.py"
        if hooks_file.is_file():
            module_name = f"{_DOMAIN_DIR_NAME}.{entity_dir.name}.agent_hooks"
            _safe_import(module_name, hooks_file)


def _safe_import(module_name: str, path: Path) -> None:
    try:
        importlib.import_module(module_name)
        logger.debug("Imported agent hooks: %s", module_name)
    except Exception:
        logger.exception("Failed to import agent hooks %s from %s", module_name, path)


# ---------------------------------------------------------------------------
# Merge helpers
# ---------------------------------------------------------------------------


@dataclass
class MergedExtensions:
    """Result of merging platform base + all domain extensions."""

    allowlist_read: frozenset[str]
    allowlist_mutation: frozenset[str]
    sandbox_required: frozenset[str]

    tool_internal_rationale: dict[str, str]
    tool_when_to_use: dict[str, str]
    tool_related_tools: dict[str, list[str]]
    tool_param_hints: dict[str, str]

    mutation_preview: dict[str, MutationPreviewFn]
    mutation_post_apply: dict[str, MutationPostApplyFn]
    mutation_inbox_watches: dict[str, MutationInboxWatchFn]

    inbox_snapshot_before_mutations: InboxSnapshotFn | None
    inbox_scan_after_mutations: InboxScanAfterMutationsFn | None
    inbox_scan_after_inbox_resume: InboxScanAfterInboxResumeFn | None
    verify_inbox_watch: VerifyInboxWatchFn | None

    system_prompt_sections: list[str]


def merge_extensions(
    *,
    base_read: frozenset[str],
    base_mutation: frozenset[str],
    base_rationale: dict[str, str],
    base_when_to_use: dict[str, str],
    base_related_tools: dict[str, list[str]],
    base_param_hints: dict[str, str],
    base_mutation_preview: dict[str, MutationPreviewFn],
    base_mutation_post_apply: dict[str, MutationPostApplyFn],
    base_mutation_inbox_watches: dict[str, MutationInboxWatchFn],
    extensions: list[AgentExtension],
) -> MergedExtensions:
    """Merge platform base configuration with all registered domain extensions."""

    read = set(base_read)
    mutation = set(base_mutation)
    sandbox_required: set[str] = set()
    rationale = dict(base_rationale)
    when_to_use = dict(base_when_to_use)
    related: dict[str, list[str]] = {k: list(v) for k, v in base_related_tools.items()}
    param_hints = dict(base_param_hints)
    previews = dict(base_mutation_preview)
    post_apply = dict(base_mutation_post_apply)
    inbox_watches = dict(base_mutation_inbox_watches)

    inbox_snapshot: InboxSnapshotFn | None = None
    inbox_scan: InboxScanAfterMutationsFn | None = None
    inbox_resume: InboxScanAfterInboxResumeFn | None = None
    verify_watch: VerifyInboxWatchFn | None = None

    prompt_sections: list[str] = []

    for ext in extensions:
        read |= ext.allowlist_read
        mutation |= ext.allowlist_mutation
        sandbox_required |= ext.sandbox_required

        rationale.update(ext.tool_internal_rationale)
        when_to_use.update(ext.tool_when_to_use)
        param_hints.update(ext.tool_param_hints)

        for tool_name, tool_related in ext.tool_related_tools.items():
            if tool_name in related:
                existing = related[tool_name]
                for r in tool_related:
                    if r not in existing:
                        existing.append(r)
            else:
                related[tool_name] = list(tool_related)

        previews.update(ext.mutation_preview)
        post_apply.update(ext.mutation_post_apply)
        inbox_watches.update(ext.mutation_inbox_watches)

        if ext.inbox_snapshot_before_mutations is not None:
            inbox_snapshot = ext.inbox_snapshot_before_mutations
        if ext.inbox_scan_after_mutations is not None:
            inbox_scan = ext.inbox_scan_after_mutations
        if ext.inbox_scan_after_inbox_resume is not None:
            inbox_resume = ext.inbox_scan_after_inbox_resume
        if ext.verify_inbox_watch is not None:
            verify_watch = ext.verify_inbox_watch

        if ext.system_prompt_section:
            prompt_sections.append(ext.system_prompt_section)

    return MergedExtensions(
        allowlist_read=frozenset(read),
        allowlist_mutation=frozenset(mutation),
        sandbox_required=frozenset(sandbox_required),
        tool_internal_rationale=rationale,
        tool_when_to_use=when_to_use,
        tool_related_tools=related,
        tool_param_hints=param_hints,
        mutation_preview=previews,
        mutation_post_apply=post_apply,
        mutation_inbox_watches=inbox_watches,
        inbox_snapshot_before_mutations=inbox_snapshot,
        inbox_scan_after_mutations=inbox_scan,
        inbox_scan_after_inbox_resume=inbox_resume,
        verify_inbox_watch=verify_watch,
        system_prompt_sections=prompt_sections,
    )
