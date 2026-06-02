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
    days = {r["day"] for r in rows}
    assert "2026-05-01" in days
    assert "2026-05-02" in days
    for r in rows:
        assert "day" in r
        assert "model" in r
        assert "input_tokens" in r
        assert "cache_creation_tokens" in r
        assert "cache_read_tokens" in r
        assert "output_tokens" in r


def test_daily_cost_by_day_respects_since_filter(db):
    _insert_turn(db, "s1", "proj", "2026-05-01T10:00:00", "claude-3-5-sonnet-20241022")
    _insert_turn(db, "s2", "proj", "2026-05-10T10:00:00", "claude-3-5-sonnet-20241022")
    from datetime import datetime, timezone
    since = datetime(2026, 5, 5, tzinfo=timezone.utc)
    rows = daily_cost_by_day(since=since)
    assert all(r["day"] >= "2026-05-05" for r in rows)
    assert len(rows) == 1
