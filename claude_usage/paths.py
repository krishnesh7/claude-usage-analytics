"""Canonical paths for the tracker. Kept in one place so tests and CLI agree.

Path resolution is layered so the package works in three contexts:

  1. Installed as a Claude Code plugin — CLAUDE_PLUGIN_ROOT is set; data lives
     under ${CLAUDE_PLUGIN_ROOT}/data and the parser is vendored at
     ${CLAUDE_PLUGIN_ROOT}/parser/parse.mjs (self-contained).
  2. Dev checkout — run from the repo; data dir falls back to the legacy
     ~/.claude/usage, parser resolves to the repo's ./parser/parse.mjs.
  3. Explicit override — CU_DATA_DIR / CLAUDE_USAGE_DB env vars win over all.

Only artifacts we own (DB, prices, stage maps, enriched cache, parser) move
with the data dir. PROJECTS_DIR always points at Claude Code's own transcript
store (~/.claude/projects) — that's our read-only source, not ours to relocate.
"""
from __future__ import annotations

import os
from pathlib import Path

HOME = Path.home()
_REPO_ROOT = Path(__file__).resolve().parent.parent


def _plugin_root() -> Path | None:
    root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    return Path(root) if root else None


def _resolve_data_dir() -> Path:
    """Where we keep the DB and derived artifacts. Env > plugin > legacy."""
    override = os.environ.get("CU_DATA_DIR")
    if override:
        return Path(override).expanduser()
    proot = _plugin_root()
    if proot:
        return proot / "data"
    return HOME / ".claude" / "usage"


def _resolve_parser() -> Path:
    """The vendored Node parser. Plugin install > repo checkout > legacy."""
    proot = _plugin_root()
    if proot and (proot / "parser" / "parse.mjs").exists():
        return proot / "parser" / "parse.mjs"
    repo_parser = _REPO_ROOT / "parser" / "parse.mjs"
    if repo_parser.exists():
        return repo_parser
    return HOME / ".claude" / "usage" / "parser" / "parse.mjs"


USAGE_DIR = _resolve_data_dir()
USAGE_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = USAGE_DIR / "usage.db"
PRICES_PATH = USAGE_DIR / "prices.json"
STAGE_MAP_PATH = USAGE_DIR / "stage_map.json"
STAGE_KEYWORDS_PATH = USAGE_DIR / "stage_keywords.json"
PARSER_PATH = _resolve_parser()
PROJECTS_DIR = HOME / ".claude" / "projects"

# Official session-report analyzer — reused for cache-break detection and
# subagent-rollup top-prompts. Path is stable because the plugin uses "unknown".
OFFICIAL_ANALYZER_PATH = (
    HOME / ".claude/plugins/cache/claude-plugins-official"
    / "session-report/unknown/skills/session-report/analyze-sessions.mjs"
)
# Raw JSON written on each enrich run — useful for debugging and fallback.
ENRICHED_CACHE_PATH = USAGE_DIR / "enriched-cache.json"


def db_path() -> Path:
    """Allow override via env for tests."""
    override = os.environ.get("CLAUDE_USAGE_DB")
    return Path(override) if override else DB_PATH
