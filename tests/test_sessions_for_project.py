"""Tests for sessions_for_project: root sessions plus their subagent children,
each tagged with an effective SDLC stage (own stage for roots, parent's for children).
"""
import sqlite3 as _sql
from claude_usage.db import parse_until, sessions_for_project


def _seed(db, sessions, stages=None, turns=None):
    """Insert sessions, optional stage rows, optional turn rows.

    sessions: list of dicts with keys: session_id, project_name (opt),
              parent_session_id (opt), started_at (opt), is_tracker_overhead (opt)
    stages:   list of (session_id, stage)
    turns:    list of (session_id, input_tokens)
    """
    conn = _sql.connect(str(db))
    for s in sessions:
        conn.execute(
            "INSERT INTO sessions(session_id, project_name, parent_session_id, started_at, is_tracker_overhead) "
            "VALUES (:session_id, :project_name, :parent_session_id, :started_at, :is_tracker_overhead)",
            {
                "session_id": s["session_id"],
                "project_name": s.get("project_name", "myproj"),
                "parent_session_id": s.get("parent_session_id"),
                "started_at": s.get("started_at", "2026-06-01T00:00:00"),
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


def test_includes_subagent_children(db):
    _seed(db, [
        {"session_id": "root1"},
        {"session_id": "root1::agent-abc123", "parent_session_id": "root1"},
    ], stages=[("root1", "build")])
    rows = sessions_for_project("myproj")
    ids = {r["session_id"] for r in rows}
    assert ids == {"root1", "root1::agent-abc123"}


def test_child_inherits_parent_stage(db):
    _seed(db, [
        {"session_id": "root1"},
        {"session_id": "root1::agent-abc123", "parent_session_id": "root1"},
    ], stages=[("root1", "build")])
    rows = {r["session_id"]: r for r in sessions_for_project("myproj")}
    assert rows["root1"]["stage"] == "build"
    assert rows["root1::agent-abc123"]["stage"] == "build"


def test_unclassified_root_gets_unclassified_stage(db):
    _seed(db, [{"session_id": "root1"}])
    rows = sessions_for_project("myproj")
    assert rows[0]["stage"] == "unclassified"


def test_stage_filter_includes_matching_children(db):
    _seed(db, [
        {"session_id": "root1"},
        {"session_id": "root1::agent-abc123", "parent_session_id": "root1"},
        {"session_id": "root2"},
    ], stages=[("root1", "build"), ("root2", "fix")])
    rows = sessions_for_project("myproj", stage="build")
    ids = {r["session_id"] for r in rows}
    assert ids == {"root1", "root1::agent-abc123"}


def test_stage_filter_unclassified(db):
    _seed(db, [
        {"session_id": "root1"},
        {"session_id": "root2"},
    ], stages=[("root2", "build")])
    rows = sessions_for_project("myproj", stage="unclassified")
    ids = {r["session_id"] for r in rows}
    assert ids == {"root1"}


def test_child_tokens_counted_on_own_row(db):
    _seed(
        db,
        sessions=[
            {"session_id": "root1"},
            {"session_id": "root1::agent-abc123", "parent_session_id": "root1"},
        ],
        stages=[("root1", "build")],
        turns=[("root1", 100), ("root1::agent-abc123", 400)],
    )
    rows = {r["session_id"]: r for r in sessions_for_project("myproj")}
    assert rows["root1"]["input_tokens"] == 100
    assert rows["root1::agent-abc123"]["input_tokens"] == 400


def test_kind_user_excludes_subagent_children(db):
    _seed(db, [
        {"session_id": "root1"},
        {"session_id": "root1::agent-abc123", "parent_session_id": "root1"},
    ], stages=[("root1", "build")])
    rows = sessions_for_project("myproj", kind="user")
    ids = {r["session_id"] for r in rows}
    assert ids == {"root1"}


def test_kind_subagent_returns_only_children(db):
    _seed(db, [
        {"session_id": "root1"},
        {"session_id": "root1::agent-abc123", "parent_session_id": "root1"},
    ], stages=[("root1", "build")])
    rows = sessions_for_project("myproj", kind="subagent")
    ids = {r["session_id"] for r in rows}
    assert ids == {"root1::agent-abc123"}


def test_kind_user_excludes_tracker_overhead(db):
    _seed(db, [
        {"session_id": "root1"},
        {"session_id": "tracker1", "is_tracker_overhead": 1},
    ])
    rows = sessions_for_project("myproj", kind="user")
    ids = {r["session_id"] for r in rows}
    assert ids == {"root1"}


def test_kind_tracker_returns_only_overhead_sessions(db):
    _seed(db, [
        {"session_id": "root1"},
        {"session_id": "tracker1", "is_tracker_overhead": 1},
    ])
    rows = sessions_for_project("myproj", kind="tracker")
    ids = {r["session_id"] for r in rows}
    assert ids == {"tracker1"}


def test_until_excludes_later_sessions(db):
    _seed(db, [
        {"session_id": "sfp1", "started_at": "2026-05-20T10:00:00"},
        {"session_id": "sfp2", "started_at": "2026-05-25T10:00:00"},
    ])
    rows = sessions_for_project("myproj", until=parse_until("2026-05-21"))
    ids = {r["session_id"] for r in rows}
    assert ids == {"sfp1"}
