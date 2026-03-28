"""Generate curl-based CLI wrappers for registry ``@function`` names (skill image)."""

from __future__ import annotations

import stat
from pathlib import Path

from hof.core.registry import registry


def _script_body(function_name: str) -> str:
    """Bash wrapper: POST JSON body (first arg or stdin) to ``/api/functions/<name>``."""
    return f"""#!/usr/bin/env bash
set -euo pipefail
# Auto-generated skill CLI for {function_name}
NAME="{function_name}"
BASE="${{API_BASE_URL:?set API_BASE_URL}}"
URL="$BASE/api/functions/$NAME"
_curl_json() {{
  if [[ -n "${{API_TOKEN:-}}" ]]; then
    curl -sS -f -H "Authorization: Bearer $API_TOKEN" -H "Content-Type: application/json" "$@"
  elif [[ -n "${{HOF_BASIC_PASSWORD:-}}" ]]; then
    curl -sS -f -u "${{HOF_BASIC_USER:-admin}}:$HOF_BASIC_PASSWORD" \\
      -H "Content-Type: application/json" "$@"
  else
    echo "set API_TOKEN or HOF_BASIC_PASSWORD (e.g. from HOF_ADMIN_PASSWORD on the host)" >&2
    exit 1
  fi
}}
if [[ $# -ge 1 ]]; then
  _curl_json -d "$1" "$URL"
else
  _curl_json -d @- "$URL"
fi
"""


def write_skill_cli_tree(
    out_dir: Path,
    *,
    names: frozenset[str] | None = None,
) -> list[Path]:
    """Write one executable script per function into ``out_dir``. Returns written paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    reg = registry.functions
    chosen = sorted(reg.keys()) if names is None else sorted(names)
    for fn in chosen:
        if fn not in reg:
            continue
        cli_name = fn.replace("_", "-")
        path = out_dir / cli_name
        path.write_text(_script_body(fn), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        written.append(path)
    return written
