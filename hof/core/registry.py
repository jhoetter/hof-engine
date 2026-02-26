"""Central registry for all user-defined components.

All tables, functions, flows, and cron jobs register themselves here at import
time via their decorators. The server, CLI, and admin UI read from this single
source of truth.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hof.cron.scheduler import CronMetadata
    from hof.db.table import TableMeta
    from hof.flows.flow import Flow
    from hof.functions import FunctionMetadata


class _Registry:
    """Thread-safe singleton registry."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tables: dict[str, TableMeta] = {}
        self._functions: dict[str, FunctionMetadata] = {}
        self._flows: dict[str, Flow] = {}
        self._cron_jobs: dict[str, CronMetadata] = {}

    # -- Tables ----------------------------------------------------------------

    def register_table(self, table_cls: Any) -> None:
        with self._lock:
            name = table_cls.__tablename__
            self._tables[name] = table_cls

    def get_table(self, name: str) -> Any | None:
        return self._tables.get(name)

    @property
    def tables(self) -> dict[str, Any]:
        return dict(self._tables)

    # -- Functions -------------------------------------------------------------

    def register_function(self, metadata: FunctionMetadata) -> None:
        with self._lock:
            self._functions[metadata.name] = metadata

    def get_function(self, name: str) -> FunctionMetadata | None:
        return self._functions.get(name)

    @property
    def functions(self) -> dict[str, FunctionMetadata]:
        return dict(self._functions)

    # -- Flows -----------------------------------------------------------------

    def register_flow(self, flow: Flow) -> None:
        with self._lock:
            self._flows[flow.name] = flow

    def get_flow(self, name: str) -> Flow | None:
        return self._flows.get(name)

    @property
    def flows(self) -> dict[str, Flow]:
        return dict(self._flows)

    # -- Cron Jobs -------------------------------------------------------------

    def register_cron(self, metadata: CronMetadata) -> None:
        with self._lock:
            self._cron_jobs[metadata.name] = metadata

    def get_cron(self, name: str) -> CronMetadata | None:
        return self._cron_jobs.get(name)

    @property
    def cron_jobs(self) -> dict[str, CronMetadata]:
        return dict(self._cron_jobs)

    # -- Introspection ---------------------------------------------------------

    def summary(self) -> dict[str, int]:
        return {
            "tables": len(self._tables),
            "functions": len(self._functions),
            "flows": len(self._flows),
            "cron_jobs": len(self._cron_jobs),
        }

    def clear(self) -> None:
        """Reset the registry (useful for testing)."""
        with self._lock:
            self._tables.clear()
            self._functions.clear()
            self._flows.clear()
            self._cron_jobs.clear()


registry = _Registry()
