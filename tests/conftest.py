import sqlite3
import pytest

SCHEMA = """
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
CREATE TABLE IF NOT EXISTS session_tools (
  session_id TEXT NOT NULL,
  tool_name TEXT NOT NULL,
  count INTEGER DEFAULT 0,
  PRIMARY KEY (session_id, tool_name)
);
CREATE TABLE IF NOT EXISTS session_cwds (
  session_id TEXT NOT NULL,
  cwd TEXT NOT NULL,
  PRIMARY KEY (session_id, cwd)
);
CREATE TABLE IF NOT EXISTS session_branches (
  session_id TEXT NOT NULL,
  git_branch TEXT NOT NULL,
  PRIMARY KEY (session_id, git_branch)
);
"""


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Temp SQLite with schema. Sets CLAUDE_USAGE_DB so db.connect() uses it."""
    db_file = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_file))
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    monkeypatch.setenv("CLAUDE_USAGE_DB", str(db_file))
    return db_file
