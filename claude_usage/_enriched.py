"""Enrichment layer — imports cache-break and top-prompt data from the
official session-report analyzer into persistent SQLite tables.

Why delegate to analyze-sessions.mjs instead of reimplementing?
  - Cache-break detection requires tracking per-turn uncached-token spikes
    across multi-block deduplicated entries.
  - Subagent-rollup for top prompts requires linking Agent tool_use calls
    in parent sessions to child subagent transcripts.
  Both are already correctly implemented in the official analyzer. We reuse
  the output and store it persistently so history isn't capped at 7 days.

Smart-window strategy:
  - First run (empty tables): --since all  (~1.3 s, one-time cost)
  - Subsequent runs: --since <max_ts_in_db - 1 day>  (fast, overlap avoids gaps)
  - All writes use ON CONFLICT DO NOTHING, so re-importing is always safe.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .db import connect
from .paths import ENRICHED_CACHE_PATH, OFFICIAL_ANALYZER_PATH

# ---------------------------------------------------------------------------
# Schema bootstrap (runs on every import; CREATE IF NOT EXISTS is idempotent)
# ---------------------------------------------------------------------------
_DDL = """
CREATE TABLE IF NOT EXISTS cache_breaks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT    NOT NULL,
    ts              TEXT    NOT NULL,
    project_path    TEXT,               -- raw encoded path from official analyzer
    uncached_tokens INTEGER,
    total_tokens    INTEGER,
    kind            TEXT,               -- 'main' | 'subagent'
    context_json    TEXT,               -- JSON: [{text, ts, calls, here}, ...]
    imported_at     TEXT DEFAULT (datetime('now')),
    UNIQUE(session_id, ts)
);

CREATE TABLE IF NOT EXISTS prompt_costs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT    NOT NULL,
    ts              TEXT    NOT NULL,
    project_path    TEXT,
    text            TEXT,               -- first human message (truncated)
    api_calls       INTEGER,
    subagent_calls  INTEGER,
    total_tokens    INTEGER,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    context_json    TEXT,               -- JSON: surrounding turn context
    imported_at     TEXT DEFAULT (datetime('now')),
    UNIQUE(session_id, ts)
);

CREATE INDEX IF NOT EXISTS idx_cache_breaks_project  ON cache_breaks(project_path);
CREATE INDEX IF NOT EXISTS idx_cache_breaks_ts       ON cache_breaks(ts);
CREATE INDEX IF NOT EXISTS idx_prompt_costs_project  ON prompt_costs(project_path);
CREATE INDEX IF NOT EXISTS idx_prompt_costs_tokens   ON prompt_costs(total_tokens DESC);
"""


def _ensure_schema() -> None:
    with connect() as c:
        for stmt in _DDL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                c.execute(stmt)
        c.commit()


_ensure_schema()


# ---------------------------------------------------------------------------
# Smart window: look at what we already have and only fetch new data
# ---------------------------------------------------------------------------
def _since_arg() -> str | None:
    """Return the --since argument to pass to analyze-sessions.mjs.

    If we have existing data, fetch only from (oldest missing day - 1) to
    avoid re-processing gigabytes of history on every parse.
    Returns None to mean '--since all' (first run / forced refresh).
    """
    with connect() as c:
        # Use MAX(ts) across both tables — whichever was updated most recently.
        row = c.execute(
            "SELECT MIN(newest) AS since_dt FROM ("
            "  SELECT MAX(ts) AS newest FROM cache_breaks"
            "  UNION ALL"
            "  SELECT MAX(ts) AS newest FROM prompt_costs"
            ") WHERE newest IS NOT NULL"
        ).fetchone()

    newest = row["since_dt"] if row else None
    if not newest:
        return None  # first run — fetch all

    # Step back 1 day from the newest stored timestamp as the fetch window,
    # so we never miss entries written just before the last import.
    try:
        dt = datetime.fromisoformat(newest.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        cutoff = dt - timedelta(days=1)
        return cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Run official analyzer and import results
# ---------------------------------------------------------------------------
def enrich(force: bool = False) -> dict:
    """Run analyze-sessions.mjs and import cache_breaks + prompt_costs.

    Args:
        force: If True, re-import all history regardless of what's stored.

    Returns a summary dict: {cache_breaks_added, prompts_added, since, elapsed_s}
    """
    if not OFFICIAL_ANALYZER_PATH.exists():
        return {"error": f"Official analyzer not found at {OFFICIAL_ANALYZER_PATH}"}

    since = None if force else _since_arg()
    cmd = ["node", str(OFFICIAL_ANALYZER_PATH), "--json"]
    if since:
        cmd += ["--since", since]

    import time
    t0 = time.monotonic()

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return {"error": "analyze-sessions.mjs timed out after 60 s"}

    elapsed = round(time.monotonic() - t0, 2)

    if result.returncode != 0:
        return {"error": result.stderr[:400] if result.stderr else "non-zero exit"}

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        return {"error": f"JSON parse failed: {e}"}

    # Write raw output to the cache file for debugging / fallback.
    try:
        ENRICHED_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        ENRICHED_CACHE_PATH.write_text(result.stdout, encoding="utf-8")
    except OSError:
        pass

    breaks_added = _import_cache_breaks(data.get("cache_breaks", []))
    prompts_added = _import_prompt_costs(data.get("top_prompts", []))

    return {
        "cache_breaks_added": breaks_added,
        "prompts_added": prompts_added,
        "since": since or "all",
        "elapsed_s": elapsed,
    }


def _import_cache_breaks(breaks: list[dict]) -> int:
    added = 0
    with connect() as c:
        for b in breaks:
            session_id = b.get("session") or ""
            ts = b.get("ts") or ""
            if not session_id or not ts:
                continue
            cur = c.execute(
                """
                INSERT OR IGNORE INTO cache_breaks
                    (session_id, ts, project_path, uncached_tokens, total_tokens,
                     kind, context_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    ts,
                    b.get("project"),
                    b.get("uncached"),
                    b.get("total"),
                    b.get("kind"),
                    json.dumps(b.get("context") or []),
                ),
            )
            added += cur.rowcount
        c.commit()
    return added


def _import_prompt_costs(prompts: list[dict]) -> int:
    added = 0
    with connect() as c:
        for p in prompts:
            session_id = p.get("session") or ""
            ts = p.get("ts") or ""
            if not session_id or not ts:
                continue
            # `input` is a dict {uncached, cache_create, cache_read}; `output` is int.
            inp = p.get("input") or {}
            if isinstance(inp, dict):
                input_tokens = (inp.get("uncached") or 0) + (inp.get("cache_create") or 0) + (inp.get("cache_read") or 0)
            else:
                input_tokens = int(inp or 0)
            output_tokens = int(p.get("output") or 0)

            cur = c.execute(
                """
                INSERT OR IGNORE INTO prompt_costs
                    (session_id, ts, project_path, text, api_calls,
                     subagent_calls, total_tokens, input_tokens, output_tokens,
                     context_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    ts,
                    p.get("project"),
                    (p.get("text") or "")[:500],
                    p.get("api_calls"),
                    p.get("subagent_calls"),
                    p.get("total_tokens"),
                    input_tokens,
                    output_tokens,
                    json.dumps(p.get("context") or []),
                ),
            )
            added += cur.rowcount
        c.commit()
    return added


# ---------------------------------------------------------------------------
# Read helpers — used by _project_view.py and cu summary
# ---------------------------------------------------------------------------
def _project_path_filter(project_name: str) -> list[str]:
    """Return the list of path substrings to match against project_path.

    The official analyzer uses encoded paths (/ → -). Our project registry
    has match_patterns which are substrings of either the decoded or encoded
    form. We use them directly as LIKE patterns.
    """
    from . import projects as pm
    all_p = pm.load_all()
    p = all_p.get(project_name)
    if not p:
        # Fallback: treat the name itself as a pattern
        return [project_name]
    return p.match_patterns or [project_name]


def cache_breaks_for_project(project_name: str, limit: int = 20) -> list[dict]:
    """Return cache breaks matching a registered project, newest first."""
    patterns = _project_path_filter(project_name)
    like_clauses = " OR ".join("project_path LIKE ?" for _ in patterns)
    params = [f"%{p}%" for p in patterns]

    with connect() as c:
        rows = c.execute(
            f"""
            SELECT session_id, ts, project_path, uncached_tokens, total_tokens,
                   kind, context_json
            FROM cache_breaks
            WHERE {like_clauses}
            ORDER BY ts DESC
            LIMIT {int(limit)}
            """,
            params,
        ).fetchall()

    from . import _redact

    result = []
    for r in rows:
        d = dict(r)
        try:
            d["context"] = json.loads(d.pop("context_json") or "[]")
        except (json.JSONDecodeError, TypeError):
            d["context"] = []
        for c in d["context"]:
            if isinstance(c.get("text"), str):
                c["text"] = _redact.redact(c["text"])
        trigger = next((c for c in d["context"] if c.get("here")), None)
        d["trigger_text"] = (trigger.get("text") or "")[:120] if trigger else ""
        result.append(d)
    return result


def top_prompts_for_project(project_name: str, limit: int = 10) -> list[dict]:
    """Return most expensive prompts for a project, with subagent rollup."""
    patterns = _project_path_filter(project_name)
    like_clauses = " OR ".join("project_path LIKE ?" for _ in patterns)
    params = [f"%{p}%" for p in patterns]

    with connect() as c:
        rows = c.execute(
            f"""
            SELECT session_id, ts, text, api_calls, subagent_calls,
                   total_tokens, input_tokens, output_tokens
            FROM prompt_costs
            WHERE {like_clauses}
            ORDER BY total_tokens DESC
            LIMIT {int(limit)}
            """,
            params,
        ).fetchall()

    grand_total = 1
    with connect() as c:
        row = c.execute(
            "SELECT COALESCE(SUM(total_tokens),1) AS gt FROM prompt_costs"
        ).fetchone()
        if row:
            grand_total = row["gt"] or 1

    from . import _redact

    result = []
    for r in rows:
        d = dict(r)
        if isinstance(d.get("text"), str):
            d["text"] = _redact.redact(d["text"])
        d["pct_of_project"] = 0.0  # filled below with per-project total
        result.append(d)

    project_total = sum(r["total_tokens"] or 0 for r in result) or 1
    for r in result:
        r["pct_of_project"] = round(100.0 * (r["total_tokens"] or 0) / project_total, 1)

    return result
