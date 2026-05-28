"""Canonical paths for the tracker. Kept in one place so tests and CLI agree."""
from __future__ import annotations

import os
from pathlib import Path

HOME = Path.home()
USAGE_DIR = HOME / ".claude" / "usage"
DB_PATH = USAGE_DIR / "usage.db"
PRICES_PATH = USAGE_DIR / "prices.json"
STAGE_MAP_PATH = USAGE_DIR / "stage_map.json"
STAGE_KEYWORDS_PATH = USAGE_DIR / "stage_keywords.json"
PARSER_PATH = USAGE_DIR / "parser" / "parse.mjs"
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
