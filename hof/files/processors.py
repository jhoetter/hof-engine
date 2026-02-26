"""File type detection and content extraction."""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Any


def detect_file_type(file_path: str) -> dict[str, str]:
    """Detect file type from extension and MIME type."""
    path = Path(file_path)
    ext = path.suffix.lstrip(".").lower()
    mime_type, _ = mimetypes.guess_type(file_path)

    type_map = {
        "xlsx": "spreadsheet",
        "xls": "spreadsheet",
        "csv": "spreadsheet",
        "md": "markdown",
        "txt": "text",
        "pdf": "pdf",
        "docx": "document",
        "doc": "document",
        "json": "structured",
        "yaml": "structured",
        "yml": "structured",
        "xml": "structured",
        "html": "markup",
        "png": "image",
        "jpg": "image",
        "jpeg": "image",
        "gif": "image",
        "webp": "image",
    }

    return {
        "file_type": type_map.get(ext, "unknown"),
        "extension": ext,
        "mime_type": mime_type or "application/octet-stream",
        "file_name": path.name,
    }


def read_text_file(file_path: str) -> str:
    """Read a text file and return its content."""
    return Path(file_path).read_text(encoding="utf-8")


def read_json_file(file_path: str) -> Any:
    """Read and parse a JSON file."""
    with open(file_path) as f:
        return json.load(f)


def get_file_size(file_path: str) -> int:
    """Get file size in bytes."""
    return Path(file_path).stat().st_size
