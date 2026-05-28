#!/usr/bin/env bash
# session-start.sh — Claude Code SessionStart hook for claude-usage-tracker.
#
# Tiered behavior (lowest → highest LLM cost):
#
#   EXACT    — cwd == project root → auto-tag + stage-map lookup; silent exit.
#   SUBDIR   — cwd inside project  → auto-tag; emit one-line info (no reply needed).
#   WORKTREE — cwd is a git worktree → auto-tag; emit one-line info.
#   FUZZY    — pattern substring match (single project) → emit confirm prompt.
#   AMBIGUOUS — multiple projects matched → emit multi-choice prompt.
#   UNMATCHED — no project matched → emit ask-to-tag prompt (SDLC stage too).
#
# Stage tagging uses stage_map.json independently of project matching.
# On any error we exit 0 — classifier fills in stage retroactively.

set -uo pipefail

# ── Resolve plugin root, wrapper, and data dir (portable) ────────────────────
ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
CU="${ROOT}/bin/cu"
DATA_DIR="${CU_DATA_DIR:-${ROOT}/data}"
DB="${DATA_DIR}/usage.db"
STAGE_MAP="${DATA_DIR}/stage_map.json"

[ ! -x "$CU" ] && exit 0

# ── Read hook payload ────────────────────────────────────────────────────────
PAYLOAD=""
if [ ! -t 0 ]; then
  PAYLOAD="$(cat || true)"
fi

cwd="${CLAUDE_PROJECT_DIR:-$(pwd)}"
session_id="${CLAUDE_SESSION_ID:-}"

if command -v jq >/dev/null 2>&1 && [ -n "$PAYLOAD" ]; then
  c="$(printf '%s' "$PAYLOAD" | jq -r '.cwd // .working_dir // empty' 2>/dev/null || true)"
  s="$(printf '%s' "$PAYLOAD" | jq -r '.session_id // .sessionId // empty' 2>/dev/null || true)"
  [ -n "$c" ] && cwd="$c"
  [ -n "$s" ] && session_id="$s"
fi

[ -z "$session_id" ] && exit 0

# ── Background parse — also triggers first-run bootstrap (venv + DB creation) ──
# Detached so a fresh-install bootstrap (pip install, ~30-60s) never blocks the
# session. Zero LLM cost: incremental byte-offset parse. On first ever run this
# builds the venv AND the DB; project resolution below resumes next session.
( "$CU" parse --no-enrich >/dev/null 2>&1 || true ) </dev/null >/dev/null 2>&1 &
disown 2>/dev/null || true

# DB not built yet (fresh install) — let the background parse create it.
[ ! -f "$DB" ] && exit 0

# ── Stage-map lookup (independent of project resolution) ────────────────────
matched_stage=""
if [ -f "$STAGE_MAP" ] && command -v jq >/dev/null 2>&1; then
  project_dir="$(printf '%s' "$cwd" | sed 's|/|-|g')"
  matched_stage="$(
    jq -r --arg cwd "$cwd" --arg dir "$project_dir" '
      .mappings // {}
      | to_entries[]
      | . as $e
      | select(($e.key | startswith("_")) | not)
      | select(($cwd | contains($e.key)) or ($dir | contains($e.key)))
      | .value
    ' "$STAGE_MAP" 2>/dev/null | head -1 || true
  )"
fi

if [ -n "$matched_stage" ]; then
  sqlite3 "$DB" \
    "INSERT OR IGNORE INTO session_stage (session_id, stage, source, classified_at)
     VALUES ('${session_id//\'/\'\'}', '${matched_stage//\'/\'\'}', 'cwd_map_hook', datetime('now'));" \
    >/dev/null 2>&1 || true
fi

# ── Project resolution via cu session-resolve ────────────────────────────────
resolve_json="$("$CU" session-resolve --cwd "$cwd" --session "$session_id" --tag 2>/dev/null || true)"

[ -z "$resolve_json" ] && exit 0

confidence="$(printf '%s' "$resolve_json" | jq -r '.confidence // empty' 2>/dev/null || true)"
project="$(printf '%s' "$resolve_json" | jq -r '.project // empty' 2>/dev/null || true)"
hook_action="$(printf '%s' "$resolve_json" | jq -r '.hook_action // empty' 2>/dev/null || true)"
branch="$(printf '%s' "$resolve_json" | jq -r '.worktree_branch // empty' 2>/dev/null || true)"
projects_list="$(printf '%s' "$resolve_json" | jq -r '.projects[]? // empty' 2>/dev/null | paste -sd ',' - || true)"

case "$hook_action" in

  silent)
    # EXACT match — perfectly certain. Nothing to say.
    exit 0
    ;;

  info)
    # SUBDIR or WORKTREE — auto-tagged, but let the user see it.
    if [ "$confidence" = "WORKTREE" ]; then
      echo "[tracker] Session tagged to project **${project}** (worktree: ${branch:-unknown}). No action needed."
    else
      echo "[tracker] Session tagged to project **${project}** (subdirectory of project root). No action needed."
    fi
    exit 0
    ;;

  confirm)
    # FUZZY match — ask Claude to confirm with user at a natural moment.
    cat <<EOF
[claude-usage-tracker] I matched this session to project **${project}** based on path pattern, but I'm not 100% certain.
At a natural pause (not interrupting the user's first request), briefly note: "I've tagged this session to the **${project}** project for usage tracking. Type \`/project-confirm\` if that's wrong."
Do not ask directly — just mention it as a one-liner alongside your first response.
EOF
    exit 0
    ;;

  choose)
    # AMBIGUOUS — multiple projects matched. Ask user to pick.
    cat <<EOF
[claude-usage-tracker] Multiple projects match this working directory: **${projects_list}**.
At a natural moment, ask the user: "For usage tracking, which project does this session belong to: ${projects_list}? (Or 'none' to skip.)"
When they answer (and it's not 'none'), run: ${CU} project tag --session ${session_id} --name <their-answer>
EOF
    exit 0
    ;;

  ask)
    # UNMATCHED — no project found. Ask about both project and stage.
    stage_prompt=""
    if [ -z "$matched_stage" ]; then
      stage_prompt="Also ask: \"What SDLC stage is this — requirements, design, impl, test, deploy, or adhoc?\" When they answer, run: ${CU} stage --session ${session_id} --set <stage>"
    fi
    cat <<EOF
[claude-usage-tracker] This session's directory (${cwd}) isn't mapped to any registered project.
At a natural pause, ask: "What project/product is this session for? (Or 'skip' to leave untagged.)"
If they give a name that's already registered, run: ${CU} project tag --session ${session_id} --name <their-answer>
If it's a new project, suggest: "Run \`cu project init <name>\` in your terminal to register it, then I'll tag this session automatically."
${stage_prompt}
EOF
    exit 0
    ;;

  *)
    exit 0
    ;;
esac
