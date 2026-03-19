"""hof-engine: Full-stack Python + React framework."""

from hof.app import HofApp
from hof.config import Config
from hof.core.registry import registry
from hof.core.types import types
from hof.cron.scheduler import cron
from hof.db.table import Column, ForeignKey, Table
from hof.errors import HofError
from hof.flows.flow import Flow
from hof.flows.human import human_node
from hof.flows.node import node
from hof.functions import function
from hof.logging_config import configure_logging
from hof.scaffold import get_project_files

def emit_computation_event(channel_id: str, event: dict) -> None:
    """Emit a progress event to an SSE channel. Lazy-imports to avoid pulling in FastAPI at module load."""
    from hof.api.routes.sse import emit_computation_event as _emit
    _emit(channel_id, event)


def publish_computation_event(channel_id: str, event: dict) -> None:
    """Publish an SSE event via Redis pub/sub (for cross-process callers like Celery workers)."""
    from hof.api.routes.sse import publish_computation_event as _publish
    _publish(channel_id, event)


__version__ = "0.1.3"

__all__ = [
    "HofApp",
    "Config",
    "configure_logging",
    "Table",
    "Column",
    "ForeignKey",
    "Flow",
    "node",
    "human_node",
    "function",
    "cron",
    "types",
    "registry",
    "HofError",
    "emit_computation_event",
    "publish_computation_event",
    "get_project_files",
]
