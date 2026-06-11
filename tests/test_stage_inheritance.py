"""Tests for child-session stage inheritance.

get_sessions_missing_stage must only return root sessions.
totals_by_stage must attribute child/agent token turns to the parent's stage
while counting only root sessions in the `sessions` column.
"""
import sqlite3 as _sql
import pytest
from claude_usage.db import get_sessions_missing_stage, totals_by_stage


def _seed(db, sessions, stages=None, turns=None):
    """Insert sessions, optional stage rows, optional turn rows.

    sessions: list of dicts with keys: session_id, parent_session_id (opt),
              first_user_message (opt), is_tracker_overhead (opt)
    stages:   list of (session_id, stage)
    turns:    list of (session_id, input_tokens)
    """
    conn = _sql.connect(str(db))
    for s in sessions:
        conn.execute(
            "INSERT INTO sessions(session_id, parent_session_id, first_user_message, is_tracker_overhead) "
            "VALUES (:session_id, :parent_session_id, :first_user_message, :is_tracker_overhead)",
            {
                "session_id": s["session_id"],
                "parent_session_id": s.get("parent_session_id"),
                "first_user_message": s.get("first_user_message", ""),
                "is_tracker_overhead": s.get("is_tracker_overhead", 0),
            },
        )
    for session_id, stage in (stages or []):
        conn.execute(
            "INSERT INTO session_stage(session_id, stage, source) VALUES (?,?,?)",
            (session_id, stage, "classifier"),
        )
    for session_id, tokens in (turns or []):
        conn.execute(
            "INSERT INTO turns(session_id, input_tokens) VALUES (?,?)",
            (session_id, tokens),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# get_sessions_missing_stage: children must be excluded
# ---------------------------------------------------------------------------

def test_missing_stage_excludes_child_sessions(db):
    _seed(db, [
        {"session_id": "root1"},
        {"session_id": "child1", "parent_session_id": "root1"},
    ])
    ids = {r["session_id"] for r in get_sessions_missing_stage()}
    assert "root1" in ids
    assert "child1" not in ids


def test_missing_stage_excludes_agent_sessions(db):
    _seed(db, [
        {"session_id": "root1"},
        {"session_id": "root1::agent-foo123abc", "parent_session_id": "root1"},
    ])
    ids = {r["session_id"] for r in get_sessions_missing_stage()}
    assert "root1" in ids
    assert "root1::agent-foo123abc" not in ids


def test_missing_stage_returns_root_with_no_stage(db):
    _seed(db, [{"session_id": "root1"}, {"session_id": "root2"}],
          stages=[("root1", "impl")])
    ids = {r["session_id"] for r in get_sessions_missing_stage()}
    assert ids == {"root2"}


# ---------------------------------------------------------------------------
# totals_by_stage: child tokens roll up under parent's stage
# ---------------------------------------------------------------------------

def test_child_tokens_attributed_to_parent_stage(db):
    """Agent session tokens must count under the parent's stage, not 'unclassified'."""
    _seed(
        db,
        sessions=[
            {"session_id": "root1"},
            {"session_id": "root1::agent-abc123", "parent_session_id": "root1"},
        ],
        stages=[("root1", "impl")],
        turns=[("root1", 100), ("root1::agent-abc123", 400)],
    )
    rows = {r["stage"]: r for r in totals_by_stage()}
    assert "impl" in rows
    assert rows["impl"]["input_tokens"] == 500   # 100 root + 400 child
    assert "unclassified" not in rows


def test_sessions_count_excludes_child_sessions(db):
    """totals_by_stage must count only root sessions in `sessions`."""
    _seed(
        db,
        sessions=[
            {"session_id": "root1"},
            {"session_id": "root1::agent-abc123", "parent_session_id": "root1"},
            {"session_id": "root1::agent-def456", "parent_session_id": "root1"},
        ],
        stages=[("root1", "impl")],
        turns=[("root1", 100), ("root1::agent-abc123", 200), ("root1::agent-def456", 300)],
    )
    rows = {r["stage"]: r for r in totals_by_stage()}
    assert rows["impl"]["sessions"] == 1       # only root1
    assert rows["impl"]["input_tokens"] == 600  # 100+200+300


def test_unclassified_children_do_not_inflate_unclassified_bucket(db):
    """A child with no stage row and a parent with no stage row stays invisible,
    not piling into 'unclassified' alongside root sessions."""
    _seed(
        db,
        sessions=[
            {"session_id": "root1"},
            {"session_id": "root1::agent-abc123", "parent_session_id": "root1"},
        ],
        stages=[("root1", "design")],
        turns=[("root1", 50), ("root1::agent-abc123", 50)],
    )
    rows = {r["stage"]: r for r in totals_by_stage()}
    assert rows.get("unclassified", {}).get("sessions", 0) == 0


def test_overhead_sessions_excluded_from_totals_by_stage(db):
    _seed(
        db,
        sessions=[
            {"session_id": "root1", "is_tracker_overhead": 0},
            {"session_id": "ovh1",  "is_tracker_overhead": 1},
        ],
        stages=[("root1", "impl"), ("ovh1", "_tracker_overhead_")],
        turns=[("root1", 100), ("ovh1", 999)],
    )
    rows = {r["stage"]: r for r in totals_by_stage()}
    assert "_tracker_overhead_" not in rows
    assert rows.get("impl", {}).get("input_tokens") == 100


def test_project_filter_falls_back_to_overhead_when_all_sessions_overhead(db):
    """A stage_map cwd rule can tag every session of a project as
    _tracker_overhead_ (e.g. to keep a meta/tooling project out of global SDLC
    stats). Querying that project specifically should still surface its
    totals as a _tracker_overhead_ row instead of an empty list."""
    conn = _sql.connect(str(db))
    conn.execute(
        "INSERT INTO sessions(session_id, project_name, project_path, project_dir, "
        "first_user_message, is_tracker_overhead) VALUES (?,?,?,?,?,?)",
        ("root1", "myproj", "/Users/me/code/myproj", "-Users-me-code-myproj", "hello", 0),
    )
    conn.execute(
        "INSERT INTO session_stage(session_id, stage, source) VALUES (?,?,?)",
        ("root1", "_tracker_overhead_", "cwd_map"),
    )
    conn.execute("INSERT INTO turns(session_id, input_tokens) VALUES (?,?)", ("root1", 100))
    conn.commit()
    conn.close()

    # Global aggregate still excludes overhead entirely.
    assert totals_by_stage() == []

    # Project-scoped query falls back to surfacing the overhead totals.
    rows = totals_by_stage(project="myproj")
    assert len(rows) == 1
    assert rows[0]["stage"] == "_tracker_overhead_"
    assert rows[0]["sessions"] == 1
    assert rows[0]["input_tokens"] == 100
