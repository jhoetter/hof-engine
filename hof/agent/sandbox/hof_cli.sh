#!/usr/bin/env bash
# Native-style Hof CLI inside the agent sandbox (mirrors host `hof fn` for skills).
# Installed as /usr/local/bin/hof. Uses API_BASE_URL + API_TOKEN (or Basic auth).
set -euo pipefail

HOF_USAGE="usage: hof fn list | hof fn describe <name> | hof fn <function_name> [json-body]"

_curl_post_fn() {
  local url="$1"
  local body="${2:-}"
  local tmp
  tmp=$(mktemp)
  local args=(
    -sS
    -H "Content-Type: application/json"
    -o "$tmp"
    -w "%{http_code}"
  )
  if [[ -n "${API_TOKEN:-}" ]]; then
    args+=(-H "Authorization: Bearer $API_TOKEN")
  elif [[ -n "${HOF_BASIC_PASSWORD:-}" ]]; then
    args+=(-u "${HOF_BASIC_USER:-admin}:$HOF_BASIC_PASSWORD")
  else
    echo "hof: set API_TOKEN or HOF_BASIC_PASSWORD in the sandbox" >&2
    rm -f "$tmp"
    exit 1
  fi
  [[ -n "${HOF_AGENT_RUN_ID:-}" ]] && args+=(-H "X-Hof-Agent-Run-Id: $HOF_AGENT_RUN_ID")
  [[ -n "${HOF_AGENT_TOOL_CALL_ID:-}" ]] && args+=(-H "X-Hof-Agent-Tool-Call-Id: $HOF_AGENT_TOOL_CALL_ID")
  local http_code
  if [[ -n "$body" ]]; then
    http_code=$(curl "${args[@]}" -d "$body" "$url")
  else
    http_code=$(curl "${args[@]}" -d @- "$url")
  fi
  local out
  out=$(cat "$tmp")
  rm -f "$tmp"
  if [[ "$http_code" -ge 400 ]]; then
    echo "hof: HTTP $http_code from $url" >&2
    printf '%s\n' "$out" >&2
    exit 1
  fi
  printf '%s' "$out"
}

_curl_get_describe() {
  local url="$1"
  local tmp
  tmp=$(mktemp)
  local http_code
  if [[ -n "${API_TOKEN:-}" ]]; then
    http_code=$(curl -sS -o "$tmp" -w "%{http_code}" -H "Authorization: Bearer $API_TOKEN" "$url")
  elif [[ -n "${HOF_BASIC_PASSWORD:-}" ]]; then
    http_code=$(curl -sS -o "$tmp" -w "%{http_code}" -u "${HOF_BASIC_USER:-admin}:$HOF_BASIC_PASSWORD" "$url")
  else
    echo "hof: set API_TOKEN or HOF_BASIC_PASSWORD in the sandbox" >&2
    rm -f "$tmp"
    exit 1
  fi
  local out
  out=$(cat "$tmp")
  rm -f "$tmp"
  if [[ "$http_code" -ge 400 ]]; then
    echo "hof: HTTP $http_code from $url" >&2
    printf '%s\n' "$out" >&2
    exit 1
  fi
  printf '%s' "$out"
}

if [[ "${1:-}" != "fn" ]]; then
  echo "$HOF_USAGE" >&2
  exit 2
fi
shift
cmd="${1:-}"
if [[ -z "$cmd" ]]; then
  echo "$HOF_USAGE" >&2
  exit 2
fi
shift

case "$cmd" in
  list)
    # grep exits 1 when there are no lines; keep success for empty catalog.
    (printf '%s\n' "${HOF_AGENT_SKILLS_CATALOG:-}" | grep -v '^[[:space:]]*$' || true) | sort -u
    ;;
  describe)
    name="${1:-}"
    if [[ -z "$name" ]]; then
      echo "hof fn describe: missing function name" >&2
      exit 2
    fi
    base="${API_BASE_URL:?set API_BASE_URL}"
    url="$base/api/functions/$name/schema"
    _curl_get_describe "$url"
    ;;
  help | --help | -h)
    echo "$HOF_USAGE"
    echo "Environment: API_BASE_URL, API_TOKEN (or HOF_BASIC_*), optional HOF_AGENT_SKILLS_CATALOG."
    ;;
  *)
    NAME="$cmd"
    base="${API_BASE_URL:?set API_BASE_URL}"
    url="$base/api/functions/$NAME"
    if [[ $# -ge 1 ]]; then
      _curl_post_fn "$url" "$1"
    else
      _curl_post_fn "$url" "{}"
    fi
    ;;
esac
