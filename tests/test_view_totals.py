"""_view.build()'s Summary totals must describe one consistent population:
total_tokens, sessions, turns, token-mix and cost should all span every
session (including tracker-overhead ones), while the by-stage breakdown
excludes overhead and the gap is reported via overhead_tokens/overhead_pct.

by_project[].pct_of_total (global view) must be a share of that same
population total, not the smaller stage-classified subset - otherwise a
single project's share can exceed 100%.
"""
import sqlite3 as _sql

import pytest

from claude_usage import _view
from claude_usage import projects as projects_mod


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


def test_total_tokens_and_cost_share_one_population(db):
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
    result = _view.build(project="myproj", since="all")
    totals = result["totals"]

    # Total tokens spans all four sessions (300 real + 200 overhead).
    assert totals["total_tokens"] == 500
    assert totals["sessions"] == 2
    assert totals["input_tokens"] == 500

    # by_stage excludes the overhead root and its subagent.
    stages = {r["stage"]: r for r in result["by_stage"]}
    assert "_tracker_overhead_" not in stages
    assert stages["impl"]["total_tokens"] == 300
    assert stages["impl"]["pct_of_total"] == 100.0

    # The gap (200 tokens) is reported as tracker overhead, as a % of the
    # same total_tokens the Summary headlines.
    assert totals["overhead_tokens_h"] == "200"
    assert totals["overhead_pct"] == 40.0

    # Cost is imputed across the full 500-token population, not just the
    # 300 stage-classified tokens.
    assert totals["cost"]["total_usd"] > 0


def test_by_project_pct_of_total_not_inflated(db):
    _seed(
        db,
        sessions=[
            {"session_id": "a1", "project_name": "proj_a", "project_path": "/Users/me/code/proj_a", "project_dir": "-Users-me-code-proj_a"},
            {"session_id": "b1", "project_name": "proj_b", "project_path": "/Users/me/code/proj_b", "project_dir": "-Users-me-code-proj_b"},
        ],
        turns=[
            ("a1", 300),
            ("b1", 200),
        ],
    )
    result = _view.build(project=None, since="all")
    totals = result["totals"]

    assert totals["total_tokens"] == 500

    by_name = {r["project_name"]: r for r in result["by_project"]}
    assert by_name["proj_a"]["pct_of_total"] == 60.0
    assert by_name["proj_b"]["pct_of_total"] == 40.0


def test_ancestor_path_row_kept_and_pct_of_total_sums_to_100(db, monkeypatch):
    monkeypatch.setattr(
        projects_mod,
        "load_all",
        lambda: {
            "proj_a": projects_mod.Project(name="proj_a", root_path="/Users/me/code/proj_a"),
        },
    )
    _seed(
        db,
        sessions=[
            {"session_id": "a1", "project_name": "proj_a", "project_path": "/Users/me/code/proj_a", "project_dir": "-Users-me-code-proj_a"},
            {"session_id": "p1", "project_name": None, "project_path": "/Users/me/code", "project_dir": "-Users-me-code"},
        ],
        turns=[
            ("a1", 300),
            ("p1", 200),
        ],
    )
    result = _view.build(project=None, since="all")

    by_project = result["by_project"]
    assert sum(r["pct_of_total"] for r in by_project) == pytest.approx(100.0)

    ancestor = next(r for r in by_project if r.get("is_ancestor_row"))
    assert ancestor["project_path"] == "/Users/me/code"
    assert ancestor["pct_of_total"] == pytest.approx(40.0)
    assert "parent directory" in ancestor["label"]
