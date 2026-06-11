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
