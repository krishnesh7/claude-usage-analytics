import sqlite3 as _sqlite3
from datetime import datetime, timezone
import pytest
from claude_usage.db import parse_until, totals_by_project, daily_timeline_by_kind, top_skills, sessions_for_project


def _insert(db_path, session_id, project_name, ts, tokens=100):
    conn = _sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO sessions(session_id, project_name, started_at) VALUES (?,?,?)",
        (session_id, project_name, ts),
    )
    conn.execute(
        "INSERT INTO turns(session_id, ts, input_tokens) VALUES (?,?,?)",
        (session_id, ts, tokens),
    )
    conn.commit()
    conn.close()


def test_parse_until_none_returns_none(db):
    assert parse_until(None) is None


def test_parse_until_all_returns_none(db):
    assert parse_until("all") is None


def test_parse_until_empty_returns_none(db):
    assert parse_until("") is None


def test_parse_until_date_only_sets_end_of_day(db):
    result = parse_until("2026-05-29")
    assert result is not None
    assert result.year == 2026
    assert result.month == 5
    assert result.day == 29
    assert result.hour == 23
    assert result.minute == 59
    assert result.second == 59
    assert result.tzinfo is not None


def test_parse_until_iso_datetime_preserved(db):
    result = parse_until("2026-05-15T10:00:00")
    assert result is not None
    assert result.year == 2026
    assert result.month == 5
    assert result.day == 15
    assert result.hour == 10


def test_parse_until_invalid_returns_none(db):
    assert parse_until("bogus") is None


def test_totals_by_project_until_excludes_later_turns(db):
    _insert(db, "s1", "proj", "2026-05-20T10:00:00")
    _insert(db, "s2", "proj", "2026-05-25T10:00:00")
    until_dt = parse_until("2026-05-21")
    rows = totals_by_project(until=until_dt)
    assert len(rows) == 1
    assert rows[0]["display_name"] == "proj"
    assert rows[0]["input_tokens"] == 100


def test_totals_by_project_until_none_returns_all(db):
    _insert(db, "s3", "proj2", "2026-05-20T10:00:00")
    _insert(db, "s4", "proj2", "2026-05-25T10:00:00")
    rows = totals_by_project(until=None)
    assert any(r["input_tokens"] >= 200 for r in rows)


def test_daily_timeline_by_kind_until_excludes_later(db):
    _insert(db, "s5", "p", "2026-05-20T10:00:00")
    _insert(db, "s6", "p", "2026-05-25T10:00:00")
    until_dt = parse_until("2026-05-21")
    rows = daily_timeline_by_kind(until=until_dt)
    days = [r["day"] for r in rows]
    assert "2026-05-25" not in days
    assert "2026-05-20" in days


def test_top_skills_until_excludes_later(db):
    conn = _sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO sessions(session_id, project_name, started_at) VALUES ('sk1','p','2026-05-20T00:00:00')"
    )
    conn.execute(
        "INSERT INTO skill_invocations(session_id, skill_name, ts) VALUES ('sk1','frontend-design','2026-05-20T00:00:00')"
    )
    conn.execute(
        "INSERT INTO sessions(session_id, project_name, started_at) VALUES ('sk2','p','2026-05-25T00:00:00')"
    )
    conn.execute(
        "INSERT INTO skill_invocations(session_id, skill_name, ts) VALUES ('sk2','feature-dev','2026-05-25T00:00:00')"
    )
    conn.commit()
    conn.close()
    until_dt = parse_until("2026-05-21")
    rows = top_skills(until=until_dt)
    names = [r["skill_name"] for r in rows]
    assert "frontend-design" in names
    assert "feature-dev" not in names


def test_sessions_for_project_until_excludes_later(db):
    conn = _sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO sessions(session_id, project_name, started_at) VALUES ('sfp1','myproj','2026-05-20T10:00:00')"
    )
    conn.execute(
        "INSERT INTO sessions(session_id, project_name, started_at) VALUES ('sfp2','myproj','2026-05-25T10:00:00')"
    )
    conn.commit()
    conn.close()
    until_dt = parse_until("2026-05-21")
    rows = sessions_for_project("myproj", until=until_dt)
    assert len(rows) == 1
    assert rows[0]["session_id"] == "sfp1"
