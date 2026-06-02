# tests/test_dashboard_panels.py
import sqlite3 as _sqlite3
from claude_usage.db import daily_cost_by_day


def _insert_turn(db_path, session_id, project_name, ts, model, input_tokens=100, output_tokens=50):
    conn = _sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT OR IGNORE INTO sessions(session_id, project_name, started_at) VALUES (?,?,?)",
        (session_id, project_name, ts),
    )
    conn.execute(
        "INSERT INTO turns(session_id, ts, model, input_tokens, output_tokens) VALUES (?,?,?,?,?)",
        (session_id, ts, model, input_tokens, output_tokens),
    )
    conn.commit()
    conn.close()


def test_daily_cost_by_day_returns_day_model_tokens(db):
    _insert_turn(db, "s1", "proj", "2026-05-01T10:00:00", "claude-3-5-sonnet-20241022", input_tokens=1000, output_tokens=500)
    _insert_turn(db, "s2", "proj", "2026-05-02T10:00:00", "claude-3-5-sonnet-20241022", input_tokens=200, output_tokens=100)

    rows = daily_cost_by_day()

    assert len(rows) == 2
    by_day = {r["day"]: r for r in rows}
    assert "2026-05-01" in by_day
    assert "2026-05-02" in by_day
    for r in rows:
        assert "day" in r
        assert "model" in r
        assert "input_tokens" in r
        assert "cache_creation_tokens" in r
        assert "cache_read_tokens" in r
        assert "output_tokens" in r
    row_day1 = by_day["2026-05-01"]
    assert row_day1["input_tokens"] == 1000
    assert row_day1["output_tokens"] == 500
    assert row_day1["cache_creation_tokens"] == 0
    assert row_day1["cache_read_tokens"] == 0
    row_day2 = by_day["2026-05-02"]
    assert row_day2["input_tokens"] == 200
    assert row_day2["output_tokens"] == 100


def test_daily_cost_by_day_project_filter(db):
    _insert_turn(db, "s1", "proj_a", "2026-05-01T10:00:00", "claude-3-5-sonnet-20241022", input_tokens=300, output_tokens=150)
    _insert_turn(db, "s2", "proj_a", "2026-05-02T10:00:00", "claude-3-5-sonnet-20241022", input_tokens=400, output_tokens=200)
    _insert_turn(db, "s3", "proj_b", "2026-05-01T10:00:00", "claude-3-5-sonnet-20241022", input_tokens=999, output_tokens=888)

    rows = daily_cost_by_day(project="proj_a")

    assert len(rows) == 2
    days = {r["day"] for r in rows}
    assert "2026-05-01" in days
    assert "2026-05-02" in days
    by_day = {r["day"]: r for r in rows}
    assert by_day["2026-05-01"]["input_tokens"] == 300
    assert by_day["2026-05-02"]["input_tokens"] == 400


def test_daily_cost_by_day_respects_since_filter(db):
    _insert_turn(db, "s1", "proj", "2026-05-01T10:00:00", "claude-3-5-sonnet-20241022")
    _insert_turn(db, "s2", "proj", "2026-05-10T10:00:00", "claude-3-5-sonnet-20241022")
    from datetime import datetime, timezone
    since = datetime(2026, 5, 5, tzinfo=timezone.utc)
    rows = daily_cost_by_day(since=since)
    assert all(r["day"] >= "2026-05-05" for r in rows)
    assert len(rows) == 1
