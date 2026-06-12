"""build_project_view's Summary totals must describe one consistent population:
total_tokens, sessions, turns, token-mix and cost should all span every
session (including tracker-overhead ones), while the by-stage breakdown
excludes overhead and the gap is reported as "tracker overhead".
"""
import sqlite3 as _sql

from claude_usage._project_view import build_project_view


def _seed(db, sessions, stages=None, turns=None):
    conn = _sql.connect(str(db))
    for s in sessions:
        conn.execute(
            "INSERT INTO sessions(session_id, project_name, project_path, project_dir, "
            "parent_session_id, started_at, ended_at, is_tracker_overhead) "
            "VALUES (:session_id, :project_name, :project_path, :project_dir, "
            ":parent_session_id, :started_at, :ended_at, :is_tracker_overhead)",
            {
                "session_id": s["session_id"],
                "project_name": s.get("project_name", "myproj"),
                "project_path": s.get("project_path", "/Users/me/code/myproj"),
                "project_dir": s.get("project_dir", "-Users-me-code-myproj"),
                "parent_session_id": s.get("parent_session_id"),
                "started_at": s.get("started_at", "2026-06-01T00:00:00"),
                "ended_at": s.get("ended_at", "2026-06-01T00:05:00"),
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
            "INSERT INTO turns(session_id, model, input_tokens) VALUES (?,?,?)",
            (session_id, "claude-sonnet-4-6", tokens),
        )
    conn.commit()
    conn.close()


def test_total_tokens_includes_overhead_sessions(db):
    _seed(
        db,
        sessions=[
            {"session_id": "root1"},
            {"session_id": "root1::agent-abc123", "parent_session_id": "root1"},
            {"session_id": "root2", "is_tracker_overhead": 1},
            {"session_id": "root2::agent-def456", "parent_session_id": "root2"},
        ],
        stages=[("root1", "impl"), ("root2", "_tracker_overhead_")],
        turns=[
            ("root1", 100),
            ("root1::agent-abc123", 200),
            ("root2", 50),
            ("root2::agent-def456", 150),
        ],
    )
    view = build_project_view("myproj")
    totals = view["totals"]

    # Total tokens spans all four sessions (300 real + 200 overhead).
    assert totals["total_tokens"] == 500
    assert totals["sessions_total"] == 4
    assert totals["sessions_main"] == 2
    assert totals["sessions_subagent"] == 2

    # by_stage excludes the overhead root and its subagent.
    stages = {r["stage"]: r for r in view["by_stage"]}
    assert "_tracker_overhead_" not in stages
    assert stages["impl"]["total_tokens"] == 300
    assert stages["impl"]["pct_of_total"] == 100.0

    # The gap (200 tokens) is reported as tracker overhead, as a % of the
    # same total_tokens the Summary headlines.
    assert totals["overhead_tokens_h"] == "200"
    assert totals["overhead_pct"] == 40.0


def test_cost_usd_approx_uses_full_population_denominator(db):
    """Per-session cost_usd_approx must be proportional to total_tokens
    (across ALL sessions), not just the stage-classified subset."""
    _seed(
        db,
        sessions=[
            {"session_id": "root1"},
            {"session_id": "root2", "is_tracker_overhead": 1},
        ],
        stages=[("root1", "impl"), ("root2", "_tracker_overhead_")],
        turns=[("root1", 100), ("root2", 100)],
    )
    view = build_project_view("myproj")
    by_id = {s["session_id"]: s for s in view["sessions_audit"]}

    # Equal token counts -> equal imputed cost, and together they should
    # account for the full lifetime cost (proportional split sums to 1.0).
    assert by_id["root1"]["cost_usd_approx"] == by_id["root2"]["cost_usd_approx"]
    total = by_id["root1"]["cost_usd_approx"] + by_id["root2"]["cost_usd_approx"]
    assert abs(total - view["totals"]["cost"]["total_usd"]) < 0.01
