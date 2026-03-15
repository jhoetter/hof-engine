"""Documentation router — serves markdown files from the project's docs_dir."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

router = APIRouter()

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Extract YAML-like frontmatter from markdown.

    Supports simple ``key: value`` lines only — no full YAML parsing to keep
    the dependency footprint zero.  Returns (meta, body_without_frontmatter).
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    meta: dict[str, Any] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            raw = value.strip()
            # Coerce bare integers so `order` sorting works numerically.
            if raw.isdigit():
                meta[key.strip()] = int(raw)
            else:
                meta[key.strip()] = raw
    return meta, text[match.end() :]


def _docs_root() -> Path | None:
    """Return the resolved docs directory or None if disabled/missing."""
    from hof.config import get_config

    config = get_config()
    if not config.docs_dir:
        return None

    root = Path.cwd() / config.docs_dir
    return root if root.is_dir() else None


def _build_doc_tree() -> list[dict[str, Any]]:
    """Scan the docs directory and return an ordered nav tree."""
    docs_root = _docs_root()
    if docs_root is None:
        return []

    entries: list[dict[str, Any]] = []
    for md_file in sorted(docs_root.rglob("*.md")):
        rel = md_file.relative_to(docs_root)
        text = md_file.read_text(encoding="utf-8")
        meta, _ = _parse_frontmatter(text)

        # Derive defaults from filesystem when frontmatter is absent.
        default_title = rel.stem.replace("-", " ").replace("_", " ").title()
        parent_name = rel.parent.name
        default_section = (
            parent_name.replace("-", " ").replace("_", " ").title() if parent_name else ""
        )

        entries.append(
            {
                "path": str(rel.as_posix()),
                "title": meta.get("title", default_title),
                "section": meta.get("section", default_section),
                "order": meta.get("order", 9999),
            }
        )

    entries.sort(key=lambda e: (e["section"], e["order"], e["title"]))
    return entries


@router.get("")
async def list_docs() -> list[dict[str, Any]]:
    """Return the ordered navigation tree of available documentation files."""
    return _build_doc_tree()


@router.get("/{doc_path:path}", response_class=PlainTextResponse)
async def get_doc(doc_path: str) -> str:
    """Return the raw markdown content of a single documentation file."""
    docs_root = _docs_root()
    if docs_root is None:
        raise HTTPException(status_code=404, detail="Documentation not available")

    # Normalise and guard against path traversal.
    target = (docs_root / doc_path).resolve()
    if not str(target).startswith(str(docs_root.resolve())):
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target.exists() or not target.suffix == ".md":
        raise HTTPException(status_code=404, detail="Document not found")

    return target.read_text(encoding="utf-8")
