from claude_usage._view import _project_description, _readme_description


def test_readme_description_skips_heading_and_badges(tmp_path):
    (tmp_path / "README.md").write_text(
        "# My Project\n"
        "\n"
        "[![CI](https://example.com/badge.svg)](https://example.com)\n"
        "\n"
        "A tool that tracks token usage and cost across Claude Code sessions.\n"
        "\n"
        "## Installation\n"
    )
    assert _readme_description(str(tmp_path)) == (
        "A tool that tracks token usage and cost across Claude Code sessions."
    )


def test_readme_description_returns_none_without_readme(tmp_path):
    assert _readme_description(str(tmp_path)) is None


def test_readme_description_strips_markdown_links_and_bold(tmp_path):
    (tmp_path / "README.md").write_text(
        "# Title\n\n**Bold start** and a [link](https://example.com) inside text.\n"
    )
    assert _readme_description(str(tmp_path)) == (
        "Bold start and a link inside text."
    )


def test_readme_description_truncates_long_lines(tmp_path):
    long_line = "x" * 250
    (tmp_path / "README.md").write_text(f"# Title\n\n{long_line}\n")
    result = _readme_description(str(tmp_path))
    assert len(result) == 198  # 197 chars + "…"
    assert result.endswith("…")


from claude_usage import projects as projects_mod


def test_project_description_prefers_notes(tmp_path):
    registry = {
        "alpha": projects_mod.Project(name="alpha", root_path=str(tmp_path), notes="Hand-written description"),
    }
    assert _project_description({"project_name": "alpha"}, registry) == "Hand-written description"


def test_project_description_falls_back_to_readme(tmp_path):
    (tmp_path / "README.md").write_text("# Alpha\n\nDoes alpha things.\n")
    registry = {
        "alpha": projects_mod.Project(name="alpha", root_path=str(tmp_path), notes=""),
    }
    assert _project_description({"project_name": "alpha"}, registry) == "Does alpha things."


def test_project_description_none_for_unregistered_or_path_rows():
    registry = {}
    assert _project_description({"project_path": "/some/path"}, registry) is None
    assert _project_description({"project_name": "unknown"}, registry) is None


import sqlite3

from claude_usage._view import build


def _insert_turn(db_path, session_id, project_name, ts, model):
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT OR IGNORE INTO sessions(session_id, project_name, started_at) VALUES (?,?,?)",
        (session_id, project_name, ts),
    )
    conn.execute(
        """INSERT INTO turns(session_id, ts, model, input_tokens, output_tokens,
             cache_creation_tokens, cache_read_tokens)
           VALUES (?,?,?,?,?,?,?)""",
        (session_id, ts, model, 1000, 200, 800, 3000),
    )
    conn.commit()
    conn.close()


def test_build_by_project_includes_description(db, tmp_path, monkeypatch):
    monkeypatch.setattr(projects_mod, "PROJECTS_PATH", tmp_path / "projects.json")
    projects_mod.init_project("alpha", tmp_path / "alpha-root", notes="Test description")

    _insert_turn(db, "s1", "alpha", "2026-06-01T10:00:00", "claude-sonnet-4-6")

    result = build(project=None, since="all", kind=None)
    rows = [r for r in result["by_project"] if r.get("project_name") == "alpha"]
    assert len(rows) == 1
    assert rows[0]["description"] == "Test description"


def test_build_by_project_description_none_when_unregistered(db, tmp_path, monkeypatch):
    monkeypatch.setattr(projects_mod, "PROJECTS_PATH", tmp_path / "projects.json")

    _insert_turn(db, "s2", "unregistered-proj", "2026-06-01T10:00:00", "claude-sonnet-4-6")

    result = build(project=None, since="all", kind=None)
    rows = [r for r in result["by_project"] if r.get("project_name") == "unregistered-proj"]
    assert len(rows) == 1
    assert rows[0]["description"] is None
