"""Read-layer over the SQLite DB the Node parser writes."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterator

from .paths import db_path


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(db_path()))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def parse_since(since: str | None) -> datetime | None:
    """Accepts '24h', '7d', '30d', 'all', or an ISO timestamp. None means 'all'."""
    if not since or since == "all":
        return None
    s = since.strip().lower()
    if s.endswith("h") and s[:-1].isdigit():
        return datetime.now(timezone.utc) - timedelta(hours=int(s[:-1]))
    if s.endswith("d") and s[:-1].isdigit():
        return datetime.now(timezone.utc) - timedelta(days=int(s[:-1]))
    try:
        dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def parse_until(s: str | None) -> datetime | None:
    """Accepts an ISO date ('YYYY-MM-DD') or datetime string, or None/'all' (unbounded).
    Date-only strings are treated as end-of-day (23:59:59 UTC) so the range is inclusive."""
    if not s or s in ("all", ""):
        return None
    try:
        dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if len(s.strip()) == 10:
            dt = dt.replace(hour=23, minute=59, second=59)
        return dt
    except ValueError:
        return None


@dataclass
class TurnTotals:
    sessions: int
    turns: int
    input_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    output_tokens: int

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.cache_creation_tokens
            + self.cache_read_tokens
            + self.output_tokens
        )


def _kind_condition(kind: str | None) -> str | None:
    """Return a boolean SQL condition on session row `s` for the given kind, or None.

    kind ∈ {'user', 'subagent', 'tracker', 'all', None}. 'all' or None means no filter.
    """
    if kind == "user":
        return "(s.parent_session_id IS NULL AND s.session_id NOT LIKE '%::agent-%' AND COALESCE(s.is_tracker_overhead, 0) = 0)"
    if kind == "subagent":
        return "(s.parent_session_id IS NOT NULL OR s.session_id LIKE '%::agent-%')"
    if kind == "tracker":
        return "COALESCE(s.is_tracker_overhead, 0) = 1"
    return None


def _where_clauses(
    project: str | None,
    since: datetime | None,
    stage: str | None,
    kind: str | None = None,
    until: datetime | None = None,
) -> tuple[str, list]:
    """Build a parameterized WHERE clause. Project filter substring-matches against
    both project_path (decoded) and project_dir (encoded on-disk dir name), so
    callers can pass either form.

    kind ∈ {'user', 'subagent', 'tracker', 'all', None}. Defaults to None (no filter).
    """
    where = []
    params: list = []
    if project:
        where.append("(s.project_name = ? OR s.project_path LIKE ? OR s.project_dir LIKE ?)")
        like = f"%{project}%"
        params.extend([project, like, like])
    if since:
        where.append("(t.ts >= ? OR (t.ts IS NULL AND s.started_at >= ?))")
        iso = since.isoformat()
        params.extend([iso, iso])
    if until:
        where.append("(t.ts <= ? OR (t.ts IS NULL AND s.started_at <= ?))")
        iso = until.isoformat()
        params.extend([iso, iso])
    if stage:
        where.append("ss.stage = ?")
        params.append(stage)
    cond = _kind_condition(kind)
    if cond:
        where.append(cond)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    return clause, params


def totals_by_stage(
    project: str | None = None,
    since: datetime | None = None,
    kind: str | None = None,
    until: datetime | None = None,
) -> list[dict]:
    """Aggregate token usage grouped by SDLC stage.

    Child/agent sessions inherit their parent's stage so subagent turns count
    toward the parent's SDLC work. Only root sessions count in `sessions`;
    overhead sessions are excluded entirely.
    """
    # Resolve effective stage: own stage for roots, parent's stage for children.
    # COUNT(sessions) uses only root sessions; token SUMs span the whole tree.
    sql = """
        SELECT
          COALESCE(
            CASE WHEN s.parent_session_id IS NULL AND s.session_id NOT LIKE '%::agent-%'
                 THEN own_ss.stage
                 ELSE par_ss.stage END,
            'unclassified'
          ) AS stage,
          COUNT(DISTINCT CASE
            WHEN s.parent_session_id IS NULL AND s.session_id NOT LIKE '%::agent-%'
            THEN s.session_id END) AS sessions,
          COUNT(t.id) AS turns,
          COALESCE(SUM(t.input_tokens), 0) AS input_tokens,
          COALESCE(SUM(t.cache_creation_tokens), 0) AS cache_creation_tokens,
          COALESCE(SUM(t.cache_read_tokens), 0) AS cache_read_tokens,
          COALESCE(SUM(t.output_tokens), 0) AS output_tokens
        FROM sessions s
        LEFT JOIN session_stage own_ss ON own_ss.session_id = s.session_id
        LEFT JOIN session_stage par_ss ON par_ss.session_id = s.parent_session_id
        LEFT JOIN turns t ON t.session_id = s.session_id
        WHERE COALESCE(s.is_tracker_overhead, 0) = 0
          AND COALESCE(own_ss.stage, '') != '_tracker_overhead_'
    """
    extra_clause, params = _where_clauses(project, since, None, kind=kind, until=until)
    extra = extra_clause.lstrip(" WHERE ").strip()
    if extra:
        sql += f" AND {extra}"
    sql = f"""
        SELECT * FROM ({sql}
        GROUP BY 1) sub
        WHERE sub.stage != 'unclassified' OR sub.sessions > 0
        ORDER BY input_tokens + cache_creation_tokens + cache_read_tokens + output_tokens DESC
    """
    with connect() as c:
        return [dict(r) for r in c.execute(sql, params)]


def totals_by_project(since: datetime | None = None, kind: str | None = None, until: datetime | None = None) -> list[dict]:
    """Group by registered project_name when available, fall back to project_path."""
    sql = """
        SELECT
          COALESCE(s.project_name, s.project_path, '(unknown)') AS display_name,
          s.project_name,
          COALESCE(s.project_path, '(unknown)') AS project_path,
          COUNT(DISTINCT s.session_id) AS sessions,
          COUNT(t.id) AS turns,
          COALESCE(SUM(t.input_tokens), 0) AS input_tokens,
          COALESCE(SUM(t.cache_creation_tokens), 0) AS cache_creation_tokens,
          COALESCE(SUM(t.cache_read_tokens), 0) AS cache_read_tokens,
          COALESCE(SUM(t.output_tokens), 0) AS output_tokens,
          COALESCE(SUM(t.input_tokens), 0) + COALESCE(SUM(t.cache_creation_tokens), 0)
            + COALESCE(SUM(t.cache_read_tokens), 0) + COALESCE(SUM(t.output_tokens), 0) AS total_tokens
        FROM sessions s
        LEFT JOIN turns t ON t.session_id = s.session_id
    """
    clause, params = _where_clauses(None, since, None, kind=kind, until=until)
    sql += (
        clause
        + " GROUP BY COALESCE(s.project_name, s.project_path)"
        + " ORDER BY total_tokens DESC"
    )
    with connect() as c:
        return [dict(r) for r in c.execute(sql, params)]


def sessions_for_project(
    project: str,
    stage: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    kind: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Return root sessions for a project plus their subagent children, newest first.

    Each row is tagged with an effective `stage`: a root session's own stage
    (or 'unclassified' if it has none), or its parent's effective stage for a
    subagent child — the same inheritance rule used by totals_by_stage().

    kind ∈ {'user', 'subagent', 'tracker', 'all', None} filters the returned
    session rows using the same semantics as _where_clauses().
    """
    sql = """
        WITH matched_roots AS (
          SELECT s.session_id AS session_id,
                 COALESCE(ss.stage, 'unclassified') AS eff_stage
          FROM sessions s
          LEFT JOIN session_stage ss ON ss.session_id = s.session_id
          WHERE (s.project_name = ? OR s.project_path LIKE ? OR s.project_dir LIKE ?)
            AND s.parent_session_id IS NULL
            AND s.session_id NOT LIKE '%::agent-%'
        )
        SELECT
          s.session_id,
          s.project_name,
          s.project_path,
          s.started_at,
          s.ended_at,
          s.is_tracker_overhead,
          s.ai_title,
          s.first_user_message,
          s.agent_type,
          s.parent_session_id,
          s.subagent_description,
          mr.eff_stage AS stage,
          COUNT(t.id) AS turns,
          COALESCE(SUM(t.input_tokens), 0) AS input_tokens,
          COALESCE(SUM(t.cache_creation_tokens), 0) AS cache_creation_tokens,
          COALESCE(SUM(t.cache_read_tokens), 0) AS cache_read_tokens,
          COALESCE(SUM(t.output_tokens), 0) AS output_tokens
        FROM sessions s
        JOIN matched_roots mr
          ON s.session_id = mr.session_id OR s.parent_session_id = mr.session_id
        LEFT JOIN turns t ON t.session_id = s.session_id
        WHERE 1=1
    """
    params: list = [project, f"%{project}%", f"%{project}%"]
    if stage:
        sql += " AND mr.eff_stage = ?"
        params.append(stage)
    if since:
        sql += " AND s.started_at >= ?"
        params.append(since.isoformat())
    if until:
        sql += " AND s.started_at <= ?"
        params.append(until.isoformat())
    cond = _kind_condition(kind)
    if cond:
        sql += f" AND {cond}"
    sql += " GROUP BY s.session_id ORDER BY s.started_at DESC LIMIT ?"
    params.append(limit)
    with connect() as c:
        return [dict(r) for r in c.execute(sql, params)]


def sessions_for_system_ops(
    since: datetime | None = None,
    until: datetime | None = None,
    kind: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Return sessions from system temp directories (plugin/automation sessions).

    kind ∈ {'user', 'subagent', 'tracker', 'all', None} filters the returned
    session rows using the same semantics as _where_clauses().
    """
    sys_prefixes = ("/private/tmp", "/tmp", "/private/var/folders/", "/var/folders/")
    conditions = " OR ".join("s.project_path LIKE ?" for _ in sys_prefixes)
    sql = f"""
        SELECT
          s.session_id, s.project_name, s.project_path,
          s.started_at, s.ended_at, s.is_tracker_overhead,
          s.ai_title, s.first_user_message, s.agent_type,
          s.parent_session_id, s.subagent_description,
          ss.stage AS stage,
          COUNT(t.id) AS turns,
          COALESCE(SUM(t.input_tokens), 0) AS input_tokens,
          COALESCE(SUM(t.cache_creation_tokens), 0) AS cache_creation_tokens,
          COALESCE(SUM(t.cache_read_tokens), 0) AS cache_read_tokens,
          COALESCE(SUM(t.output_tokens), 0) AS output_tokens
        FROM sessions s
        LEFT JOIN turns t ON t.session_id = s.session_id
        LEFT JOIN session_stage ss ON ss.session_id = s.session_id
        WHERE ({conditions})
    """
    params: list = [f"{p}%" for p in sys_prefixes]
    if since:
        sql += " AND s.started_at >= ?"
        params.append(since.isoformat())
    if until:
        sql += " AND s.started_at <= ?"
        params.append(until.isoformat())
    cond = _kind_condition(kind)
    if cond:
        sql += f" AND {cond}"
    sql += " GROUP BY s.session_id ORDER BY s.started_at DESC LIMIT ?"
    params.append(limit)
    with connect() as c:
        return [dict(r) for r in c.execute(sql, params)]


def projects_by_dim(
    dim: str,
    key: str,
    since: datetime | None = None,
) -> list[dict]:
    """Cross-tab: for a given stage or agent_type, break down totals per project.

    dim must be 'stage' or 'agent_type'. Returns rows shaped like totals_by_project().
    """
    if dim == "stage":
        join = "LEFT JOIN session_stage ss ON ss.session_id = s.session_id"
        filter_clause = "COALESCE(ss.stage, 'unclassified') = ?"
    elif dim == "agent_type":
        join = ""
        filter_clause = "COALESCE(s.agent_type, '(main)') = ?"
    else:
        raise ValueError(f"unknown dim: {dim}")

    sql = f"""
        SELECT
          COALESCE(s.project_name, s.project_path, '(unknown)') AS display_name,
          s.project_name,
          COALESCE(s.project_path, '(unknown)') AS project_path,
          COUNT(DISTINCT s.session_id) AS sessions,
          COUNT(t.id) AS turns,
          COALESCE(SUM(t.input_tokens), 0) AS input_tokens,
          COALESCE(SUM(t.cache_creation_tokens), 0) AS cache_creation_tokens,
          COALESCE(SUM(t.cache_read_tokens), 0) AS cache_read_tokens,
          COALESCE(SUM(t.output_tokens), 0) AS output_tokens
        FROM sessions s
        LEFT JOIN turns t ON t.session_id = s.session_id
        {join}
        WHERE {filter_clause}
    """
    params: list = [key]
    if since:
        sql += " AND (t.ts >= ? OR (t.ts IS NULL AND s.started_at >= ?))"
        iso = since.isoformat()
        params.extend([iso, iso])
    sql += (
        " GROUP BY COALESCE(s.project_name, s.project_path)"
        " ORDER BY input_tokens + cache_creation_tokens + cache_read_tokens + output_tokens DESC"
    )
    with connect() as c:
        return [dict(r) for r in c.execute(sql, params)]


def totals_by_agent_type(
    project: str | None = None,
    since: datetime | None = None,
    kind: str | None = None,
    until: datetime | None = None,
) -> list[dict]:
    sql = """
        SELECT
          COALESCE(s.agent_type, '(main)') AS agent_type,
          COUNT(DISTINCT s.session_id) AS sessions,
          COUNT(t.id) AS turns,
          COALESCE(SUM(t.input_tokens), 0) AS input_tokens,
          COALESCE(SUM(t.cache_creation_tokens), 0) AS cache_creation_tokens,
          COALESCE(SUM(t.cache_read_tokens), 0) AS cache_read_tokens,
          COALESCE(SUM(t.output_tokens), 0) AS output_tokens
        FROM sessions s
        LEFT JOIN turns t ON t.session_id = s.session_id
    """
    clause, params = _where_clauses(project, since, None, kind=kind, until=until)
    sql += clause + " GROUP BY COALESCE(s.agent_type, '(main)') ORDER BY input_tokens + cache_creation_tokens + cache_read_tokens + output_tokens DESC"
    with connect() as c:
        return [dict(r) for r in c.execute(sql, params)]


def turns_by_model(
    project: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[dict]:
    """Per-model rows joined with sessions for filter compatibility. Used by pricing."""
    sql = """
        SELECT
          COALESCE(t.model, 'unknown') AS model,
          COALESCE(SUM(t.input_tokens), 0) AS input_tokens,
          COALESCE(SUM(t.cache_creation_tokens), 0) AS cache_creation_tokens,
          COALESCE(SUM(t.cache_creation_1h_tokens), 0) AS cache_creation_1h_tokens,
          COALESCE(SUM(t.cache_read_tokens), 0) AS cache_read_tokens,
          COALESCE(SUM(t.output_tokens), 0) AS output_tokens,
          COUNT(t.id) AS turns
        FROM sessions s
        JOIN turns t ON t.session_id = s.session_id
    """
    clause, params = _where_clauses(project, since, None, until=until)
    sql += clause + " GROUP BY COALESCE(t.model, 'unknown')"
    with connect() as c:
        return [dict(r) for r in c.execute(sql, params)]


def turns_by_model_for_stage(
    stage: str,
    project: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[dict]:
    sql = """
        SELECT
          COALESCE(t.model, 'unknown') AS model,
          COALESCE(SUM(t.input_tokens), 0) AS input_tokens,
          COALESCE(SUM(t.cache_creation_tokens), 0) AS cache_creation_tokens,
          COALESCE(SUM(t.cache_creation_1h_tokens), 0) AS cache_creation_1h_tokens,
          COALESCE(SUM(t.cache_read_tokens), 0) AS cache_read_tokens,
          COALESCE(SUM(t.output_tokens), 0) AS output_tokens,
          COUNT(t.id) AS turns
        FROM sessions s
        JOIN turns t ON t.session_id = s.session_id
        JOIN session_stage ss ON ss.session_id = s.session_id
    """
    clause, params = _where_clauses(project, since, stage, until=until)
    sql += clause + " GROUP BY COALESCE(t.model, 'unknown')"
    with connect() as c:
        return [dict(r) for r in c.execute(sql, params)]


def get_sessions_missing_stage(limit: int | None = None) -> list[dict]:
    sql = """
        SELECT s.session_id, s.project_path, s.first_user_message, s.is_tracker_overhead
        FROM sessions s
        LEFT JOIN session_stage ss ON ss.session_id = s.session_id
        WHERE ss.session_id IS NULL
          AND s.parent_session_id IS NULL
          AND s.session_id NOT LIKE '%::agent-%'
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    with connect() as c:
        return [dict(r) for r in c.execute(sql)]


def clear_classifier_stages() -> None:
    """Drop only classifier-authored stage rows so they can be re-evaluated.

    Parser-authored ('overhead_detect') and manual/cwd_map rows are preserved.
    """
    with connect() as c:
        c.execute("DELETE FROM session_stage WHERE source = 'classifier'")
        c.commit()


def upsert_stage(session_id: str, stage: str, source: str) -> None:
    with connect() as c:
        c.execute(
            """
            INSERT INTO session_stage (session_id, stage, source, classified_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(session_id) DO UPDATE SET
              stage = excluded.stage,
              source = excluded.source,
              classified_at = excluded.classified_at
            """,
            (session_id, stage, source),
        )
        c.commit()


def tag_session_project(session_id: str, project_name: str) -> None:
    """Write project_name into the sessions row. INSERT OR IGNORE means we
    never create a shell row — only update a row the parser already knows about.
    Rows created mid-session (before the first parse) get tagged on next parse
    automatically via resolveProjectName in parse.mjs.
    """
    with connect() as c:
        c.execute(
            """
            UPDATE sessions SET project_name = ?
            WHERE session_id = ? AND (project_name IS NULL OR project_name = '')
            """,
            (project_name, session_id),
        )
        c.commit()


def daily_timeline(
    project: str | None = None,
    days: int = 30,
    until: datetime | None = None,
) -> list[dict]:
    """Per-day token + cost-input rollup. Returns one row per date in the range,
    including zero days, sorted oldest first."""
    where: list[str] = []
    params: list = []
    if project:
        where.append("(s.project_name = ? OR s.project_path LIKE ? OR s.project_dir LIKE ?)")
        like = f"%{project}%"
        params.extend([project, like, like])
    sql = """
        SELECT date(COALESCE(t.ts, s.started_at)) AS day,
               COUNT(DISTINCT s.session_id) AS sessions,
               COUNT(t.id) AS turns,
               COALESCE(SUM(t.input_tokens), 0) AS input_tokens,
               COALESCE(SUM(t.cache_creation_tokens), 0) AS cache_creation_tokens,
               COALESCE(SUM(t.cache_read_tokens), 0) AS cache_read_tokens,
               COALESCE(SUM(t.output_tokens), 0) AS output_tokens
        FROM sessions s
        LEFT JOIN turns t ON t.session_id = s.session_id
    """
    where.append(f"date(COALESCE(t.ts, s.started_at)) >= date('now', '-{int(days)} days')")
    if until:
        where.append("date(COALESCE(t.ts, s.started_at)) <= date(?)")
        params.append(until.date().isoformat())
    sql += (" WHERE " + " AND ".join(where)) if where else ""
    sql += " GROUP BY date(COALESCE(t.ts, s.started_at)) ORDER BY day ASC"
    with connect() as c:
        return [dict(r) for r in c.execute(sql, params)]


def daily_timeline_by_kind(
    project: str | None = None,
    since: "datetime | None" = None,
    until: datetime | None = None,
) -> list[dict]:
    """Per-day tokens split into user vs subagent buckets, for a stacked trend chart.

    'subagent' = sessions with a parent or a ::agent- id; everything else (excluding
    tracker overhead) counts as 'user'. Pass since=None to include all history.
    """
    where: list[str] = []
    params: list = []
    if project:
        where.append("(s.project_name = ? OR s.project_path LIKE ? OR s.project_dir LIKE ?)")
        like = f"%{project}%"
        params.extend([project, like, like])
    if since is not None:
        where.append("COALESCE(t.ts, s.started_at) >= ?")
        params.append(since.isoformat())
    if until is not None:
        where.append("COALESCE(t.ts, s.started_at) <= ?")
        params.append(until.isoformat())
    tok = "(t.input_tokens + t.cache_creation_tokens + t.cache_read_tokens + t.output_tokens)"
    is_sub = "(s.parent_session_id IS NOT NULL OR s.session_id LIKE '%::agent-%')"
    is_user = ("(s.parent_session_id IS NULL AND s.session_id NOT LIKE '%::agent-%'"
               " AND COALESCE(s.is_tracker_overhead, 0) = 0)")
    sql = f"""
        SELECT date(COALESCE(t.ts, s.started_at)) AS day,
               COALESCE(SUM(CASE WHEN {is_user} THEN {tok} ELSE 0 END), 0) AS user_tokens,
               COALESCE(SUM(CASE WHEN {is_sub} THEN {tok} ELSE 0 END), 0) AS subagent_tokens
        FROM sessions s
        LEFT JOIN turns t ON t.session_id = s.session_id
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " GROUP BY date(COALESCE(t.ts, s.started_at)) ORDER BY day ASC"
    with connect() as c:
        return [dict(r) for r in c.execute(sql, params)]


def daily_cost_by_day(
    since: "datetime | None" = None,
    until: "datetime | None" = None,
    project: str | None = None,
    kind: str | None = None,
) -> list[dict]:
    """Per-day, per-model token rows for cost imputation across a date range.

    Returns [{day, model, input_tokens, cache_creation_tokens, cache_creation_1h_tokens, cache_read_tokens, output_tokens}]
    for each (day, model) combination. Used by _view.build() to add cost_usd to sparkline rows.
    """
    where: list[str] = []
    params: list = []
    if project:
        where.append("(s.project_name = ? OR s.project_path LIKE ? OR s.project_dir LIKE ?)")
        like = f"%{project}%"
        params.extend([project, like, like])
    if since is not None:
        where.append("COALESCE(t.ts, s.started_at) >= ?")
        params.append(since.isoformat())
    if until is not None:
        where.append("COALESCE(t.ts, s.started_at) <= ?")
        params.append(until.isoformat())
    if kind and kind != "all":
        if kind == "user":
            where.append("(s.parent_session_id IS NULL AND s.session_id NOT LIKE '%::agent-%' AND COALESCE(s.is_tracker_overhead, 0) = 0)")
        elif kind == "subagent":
            where.append("(s.parent_session_id IS NOT NULL OR s.session_id LIKE '%::agent-%')")
        elif kind == "tracker":
            where.append("COALESCE(s.is_tracker_overhead, 0) = 1")
    sql = """
        SELECT date(COALESCE(t.ts, s.started_at)) AS day,
               COALESCE(t.model, 'unknown') AS model,
               COALESCE(SUM(t.input_tokens), 0) AS input_tokens,
               COALESCE(SUM(t.cache_creation_tokens), 0) AS cache_creation_tokens,
               COALESCE(SUM(t.cache_creation_1h_tokens), 0) AS cache_creation_1h_tokens,
               COALESCE(SUM(t.cache_read_tokens), 0) AS cache_read_tokens,
               COALESCE(SUM(t.output_tokens), 0) AS output_tokens
        FROM sessions s
        LEFT JOIN turns t ON t.session_id = s.session_id
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " GROUP BY date(COALESCE(t.ts, s.started_at)), COALESCE(t.model, 'unknown') ORDER BY day ASC"
    with connect() as c:
        return [dict(r) for r in c.execute(sql, params)]


def turns_by_model_for_day(
    day: str,
    project: str | None = None,
) -> list[dict]:
    """Per-model rows scoped to a single date — used for daily cost imputation."""
    where = ["date(COALESCE(t.ts, s.started_at)) = ?"]
    params: list = [day]
    if project:
        where.append("(s.project_name = ? OR s.project_path LIKE ? OR s.project_dir LIKE ?)")
        like = f"%{project}%"
        params.extend([project, like, like])
    sql = f"""
        SELECT COALESCE(t.model, 'unknown') AS model,
               COALESCE(SUM(t.input_tokens),0) AS input_tokens,
               COALESCE(SUM(t.cache_creation_tokens),0) AS cache_creation_tokens,
               COALESCE(SUM(t.cache_creation_1h_tokens),0) AS cache_creation_1h_tokens,
               COALESCE(SUM(t.cache_read_tokens),0) AS cache_read_tokens,
               COALESCE(SUM(t.output_tokens),0) AS output_tokens,
               COUNT(t.id) AS turns
        FROM sessions s
        JOIN turns t ON t.session_id = s.session_id
        WHERE {' AND '.join(where)}
        GROUP BY COALESCE(t.model, 'unknown')
    """
    with connect() as c:
        return [dict(r) for r in c.execute(sql, params)]


def project_sessions_audit(project: str, limit: int = 500) -> list[dict]:
    """Per-session audit trail for a project: id, started, title, tokens, cost-relevant token mix, top tools, branches.

    Joins to subagent rollups so each row reflects the session AS A WHOLE
    (main + its subagents)."""
    where = ["(s.project_name = ? OR s.project_path LIKE ? OR s.project_dir LIKE ?)"]
    like = f"%{project}%"
    params: list = [project, like, like]
    sql = f"""
        SELECT s.session_id, s.parent_session_id, s.agent_type, s.ai_title, s.first_user_message,
               s.started_at, s.ended_at, s.worktree_branch,
               COUNT(t.id) AS turns,
               COALESCE(SUM(t.input_tokens),0) AS input_tokens,
               COALESCE(SUM(t.cache_creation_tokens),0) AS cache_creation_tokens,
               COALESCE(SUM(t.cache_read_tokens),0) AS cache_read_tokens,
               COALESCE(SUM(t.output_tokens),0) AS output_tokens,
               s.is_tracker_overhead
        FROM sessions s
        LEFT JOIN turns t ON t.session_id = s.session_id
        WHERE {' AND '.join(where)}
        GROUP BY s.session_id
        ORDER BY s.started_at DESC
        LIMIT {int(limit)}
    """
    with connect() as c:
        rows = [dict(r) for r in c.execute(sql, params)]

    # Annotate with per-session top tools and branches.
    if rows:
        ids = [r["session_id"] for r in rows]
        placeholders = ",".join(["?"] * len(ids))
        with connect() as c:
            tool_rows = c.execute(
                f"SELECT session_id, tool_name, count FROM session_tools WHERE session_id IN ({placeholders}) ORDER BY count DESC",
                ids,
            ).fetchall()
            branch_rows = c.execute(
                f"SELECT session_id, git_branch FROM session_branches WHERE session_id IN ({placeholders})",
                ids,
            ).fetchall()
        tools_by_session: dict[str, list[tuple[str, int]]] = {}
        for tr in tool_rows:
            tools_by_session.setdefault(tr["session_id"], []).append((tr["tool_name"], tr["count"]))
        branches_by_session: dict[str, list[str]] = {}
        for br in branch_rows:
            branches_by_session.setdefault(br["session_id"], []).append(br["git_branch"])
        for r in rows:
            r["top_tools"] = tools_by_session.get(r["session_id"], [])[:5]
            r["branches"] = branches_by_session.get(r["session_id"], [])
    return rows


def tool_counts_for_project(project: str) -> list[dict]:
    sql = """
        SELECT st.tool_name, SUM(st.count) AS total
        FROM session_tools st
        JOIN sessions s ON s.session_id = st.session_id
        WHERE s.project_name = ? OR s.project_path LIKE ? OR s.project_dir LIKE ?
        GROUP BY st.tool_name
        ORDER BY total DESC
    """
    like = f"%{project}%"
    with connect() as c:
        return [dict(r) for r in c.execute(sql, (project, like, like))]


def cwds_for_project(project: str) -> list[dict]:
    sql = """
        SELECT sc.cwd, COUNT(DISTINCT sc.session_id) AS sessions
        FROM session_cwds sc
        JOIN sessions s ON s.session_id = sc.session_id
        WHERE s.project_name = ? OR s.project_path LIKE ? OR s.project_dir LIKE ?
        GROUP BY sc.cwd
        ORDER BY sessions DESC
    """
    like = f"%{project}%"
    with connect() as c:
        return [dict(r) for r in c.execute(sql, (project, like, like))]


def branches_for_project(project: str) -> list[dict]:
    sql = """
        SELECT sb.git_branch, COUNT(DISTINCT sb.session_id) AS sessions
        FROM session_branches sb
        JOIN sessions s ON s.session_id = sb.session_id
        WHERE s.project_name = ? OR s.project_path LIKE ? OR s.project_dir LIKE ?
        GROUP BY sb.git_branch
        ORDER BY sessions DESC
    """
    like = f"%{project}%"
    with connect() as c:
        return [dict(r) for r in c.execute(sql, (project, like, like))]


def attribution_for_project(project: str) -> list[dict]:
    sql = """
        SELECT COALESCE(sa.attribution_plugin, '(none)') AS plugin,
               COALESCE(sa.attribution_skill, '(none)') AS skill,
               SUM(sa.count) AS turns,
               COUNT(DISTINCT sa.session_id) AS sessions
        FROM session_attribution sa
        JOIN sessions s ON s.session_id = sa.session_id
        WHERE s.project_name = ? OR s.project_path LIKE ? OR s.project_dir LIKE ?
        GROUP BY plugin, skill
        ORDER BY turns DESC
    """
    like = f"%{project}%"
    with connect() as c:
        return [dict(r) for r in c.execute(sql, (project, like, like))]


def top_skills(
    project: str | None = None,
    since: datetime | None = None,
    limit: int = 20,
    until: datetime | None = None,
) -> list[dict]:
    where: list[str] = []
    params: list = []
    if project:
        where.append("(s.project_name = ? OR s.project_path LIKE ? OR s.project_dir LIKE ?)")
        like = f"%{project}%"
        params.extend([project, like, like])
    if since:
        where.append("si.ts >= ?")
        params.append(since.isoformat())
    if until:
        where.append("si.ts <= ?")
        params.append(until.isoformat())
    sql = """
        SELECT si.skill_name, COUNT(*) AS invocations,
               COUNT(DISTINCT si.session_id) AS sessions
        FROM skill_invocations si
        JOIN sessions s ON s.session_id = si.session_id
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" GROUP BY si.skill_name ORDER BY invocations DESC LIMIT {int(limit)}"
    with connect() as c:
        return [dict(r) for r in c.execute(sql, params)]
