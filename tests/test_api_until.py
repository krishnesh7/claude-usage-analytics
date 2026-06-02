import sqlite3 as _sqlite3
import pytest
from fastapi.testclient import TestClient

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY,
  project_path TEXT,
  project_dir TEXT,
  project_name TEXT,
  started_at TEXT,
  ended_at TEXT,
  parent_session_id TEXT,
  agent_type TEXT,
  is_tracker_overhead INTEGER DEFAULT 0,
  first_user_message TEXT,
  ai_title TEXT,
  worktree_branch TEXT,
  subagent_description TEXT
);
CREATE TABLE IF NOT EXISTS turns (
  id INTEGER PRIMARY KEY,
  session_id TEXT NOT NULL,
  request_id TEXT UNIQUE,
  ts TEXT,
  model TEXT,
  input_tokens INTEGER DEFAULT 0,
  cache_creation_tokens INTEGER DEFAULT 0,
  cache_creation_1h_tokens INTEGER DEFAULT 0,
  cache_read_tokens INTEGER DEFAULT 0,
  output_tokens INTEGER DEFAULT 0,
  service_tier TEXT
);
CREATE TABLE IF NOT EXISTS session_stage (
  session_id TEXT PRIMARY KEY,
  stage TEXT NOT NULL,
  source TEXT NOT NULL,
  classified_at TEXT
);
CREATE TABLE IF NOT EXISTS skill_invocations (
  id INTEGER PRIMARY KEY,
  session_id TEXT NOT NULL,
  skill_name TEXT NOT NULL,
  ts TEXT
);
CREATE TABLE IF NOT EXISTS session_attribution (
  session_id TEXT NOT NULL,
  attribution_plugin TEXT,
  attribution_skill TEXT,
  count INTEGER DEFAULT 0,
  PRIMARY KEY (session_id, attribution_plugin, attribution_skill)
);
"""


def _get_client(monkeypatch, db_path):
    """Import serve after env is set so db_path() picks up CLAUDE_USAGE_DB."""
    monkeypatch.setenv("CLAUDE_USAGE_DB", str(db_path))
    from claude_usage.serve import make_app
    app = make_app()
    return TestClient(app)


def _seed(db_path):
    conn = _sqlite3.connect(str(db_path))
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.execute(
        "INSERT INTO sessions(session_id, project_name, started_at) VALUES ('a1','alpha','2026-05-20T10:00:00')"
    )
    conn.execute(
        "INSERT INTO turns(session_id, ts, input_tokens) VALUES ('a1','2026-05-20T10:00:00', 500)"
    )
    conn.execute(
        "INSERT INTO sessions(session_id, project_name, started_at) VALUES ('a2','alpha','2026-05-26T10:00:00')"
    )
    conn.execute(
        "INSERT INTO turns(session_id, ts, input_tokens) VALUES ('a2','2026-05-26T10:00:00', 999)"
    )
    conn.execute(
        "INSERT INTO session_attribution(session_id, attribution_plugin, attribution_skill, count) "
        "VALUES ('a1','frontend-design','frontend-design', 10)"
    )
    conn.commit()
    conn.close()


def test_summary_until_filters_tokens(tmp_path, monkeypatch):
    _seed(tmp_path / "test.db")
    client = _get_client(monkeypatch, tmp_path / "test.db")
    resp = client.get("/api/summary?since=2026-05-01&until=2026-05-21&kind=all")
    assert resp.status_code == 200
    data = resp.json()
    assert data["totals"]["input_tokens"] == 500


def test_summary_until_none_returns_all(tmp_path, monkeypatch):
    _seed(tmp_path / "test.db")
    client = _get_client(monkeypatch, tmp_path / "test.db")
    resp = client.get("/api/summary?since=2026-05-01&kind=all")
    assert resp.status_code == 200
    data = resp.json()
    assert data["totals"]["input_tokens"] >= 1499


def test_sessions_until_filters(tmp_path, monkeypatch):
    _seed(tmp_path / "test.db")
    client = _get_client(monkeypatch, tmp_path / "test.db")
    resp = client.get("/api/sessions?project=alpha&since=2026-05-01&until=2026-05-21")
    assert resp.status_code == 200
    sessions = resp.json()["sessions"]
    ids = [s["session_id"] for s in sessions]
    assert "a1" in ids
    assert "a2" not in ids


def test_attribution_endpoint_returns_data(tmp_path, monkeypatch):
    _seed(tmp_path / "test.db")
    client = _get_client(monkeypatch, tmp_path / "test.db")
    resp = client.get("/api/attribution?project=alpha")
    assert resp.status_code == 200
    rows = resp.json()["attribution"]
    assert len(rows) == 1
    assert rows[0]["plugin"] == "frontend-design"
    assert rows[0]["turns"] == 10


def test_attribution_endpoint_missing_project_422(tmp_path, monkeypatch):
    client = _get_client(monkeypatch, tmp_path / "test.db")
    resp = client.get("/api/attribution")
    assert resp.status_code == 422
