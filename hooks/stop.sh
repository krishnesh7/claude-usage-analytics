#!/usr/bin/env bash
# stop.sh — Claude Code Stop hook for claude-usage-tracker.
#
# When a session ends:
#   1. Resolve cwd → registered project (via projects.json).
#   2. Run `cu parse && cu doc --project <name>` in the BACKGROUND so the
#      session shutdown is not blocked by parsing.
#   3. Cost: 0 LLM tokens (deterministic code only).
#
# If no project matches, we still run `cu parse` so the global DB stays fresh,
# but skip doc generation (no project to write to).

set -uo pipefail

ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
CU_BIN="${ROOT}/bin/cu"
DATA_DIR="${CU_DATA_DIR:-${ROOT}/data}"
PROJECTS_JSON="${DATA_DIR}/projects.json"

if [ ! -x "$CU_BIN" ]; then
  exit 0
fi

# Read hook payload (JSON on stdin in newer Claude Code; env vars in older).
PAYLOAD=""
if [ ! -t 0 ]; then
  PAYLOAD="$(cat || true)"
fi

cwd="${CLAUDE_PROJECT_DIR:-$(pwd)}"
if command -v jq >/dev/null 2>&1 && [ -n "$PAYLOAD" ]; then
  c="$(printf '%s' "$PAYLOAD" | jq -r '.cwd // .working_dir // empty' 2>/dev/null || true)"
  [ -n "$c" ] && cwd="$c"
fi

# Look up the project for this cwd.
project_name=""
if command -v jq >/dev/null 2>&1 && [ -f "$PROJECTS_JSON" ]; then
  # Encoded form: replace path separators with '-'.
  encoded="-$(printf '%s' "$cwd" | sed 's|^/||; s|/|-|g')"
  project_name="$(
    jq -r --arg cwd "$cwd" --arg enc "$encoded" '
      .projects // {}
      | to_entries[]
      | . as $e
      | select(($e.key | startswith("_")) | not)
      | (.value.match_patterns // [])[] as $p
      | select($p != "" and (($cwd | contains($p)) or ($enc | contains($p))))
      | $e.key
    ' "$PROJECTS_JSON" 2>/dev/null | head -1 || true
  )"
fi

# Detach: run parse (and optionally doc) in the background so the user's
# session-close is instant. Errors are swallowed; nothing bubbles up to Claude.
(
  "$CU_BIN" parse >/dev/null 2>&1 || true
  "$CU_BIN" classify >/dev/null 2>&1 || true
  if [ -n "$project_name" ]; then
    "$CU_BIN" doc --project "$project_name" >/dev/null 2>&1 || true
  fi
) </dev/null >/dev/null 2>&1 &
disown 2>/dev/null || true

exit 0
