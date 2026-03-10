"""File storage abstraction."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import BinaryIO

from hof.config import get_config


class FileStorage:
    """Local file storage with organized directory structure."""

    def __init__(self, base_path: str | None = None) -> None:
        config = get_config()
        self.base_path = Path(base_path or config.file_storage_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def store(self, file: BinaryIO, filename: str, *, subdir: str = "") -> str:
        """Store a file and return its storage path."""
        file_id = str(uuid.uuid4())
        ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
        stored_name = f"{file_id}.{ext}" if ext else file_id

        target_dir = self.base_path / subdir if subdir else self.base_path
        target_dir.mkdir(parents=True, exist_ok=True)

        target_path = target_dir / stored_name
        with open(target_path, "wb") as f:
            shutil.copyfileobj(file, f)

        return str(target_path)

    def get_path(self, storage_path: str) -> Path:
        """Get the full path to a stored file."""
        return Path(storage_path)

    def delete(self, storage_path: str) -> bool:
        """Delete a stored file."""
        path = Path(storage_path)
        if path.exists():
            path.unlink()
            return True
        return False

    def exists(self, storage_path: str) -> bool:
        """Check if a file exists in storage."""
        return Path(storage_path).exists()
