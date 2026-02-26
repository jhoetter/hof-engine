"""Framework-level error types."""

from __future__ import annotations


class HofError(Exception):
    """Base error for hof-engine, returned as structured API responses."""

    def __init__(self, message: str, *, status_code: int = 400, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}

    def to_dict(self) -> dict:
        return {
            "error": self.message,
            "status_code": self.status_code,
            "details": self.details,
        }


class ConfigError(HofError):
    """Raised when configuration is invalid or missing."""

    def __init__(self, message: str):
        super().__init__(message, status_code=500)


class TableError(HofError):
    """Raised for table-related errors (not found, validation, etc.)."""

    pass


class FlowError(HofError):
    """Raised for flow-related errors (invalid DAG, execution failures, etc.)."""

    pass


class NodeError(FlowError):
    """Raised when a flow node fails."""

    def __init__(self, message: str, *, node_name: str, **kwargs):
        super().__init__(message, **kwargs)
        self.node_name = node_name
