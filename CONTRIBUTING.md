# Contributing

Thanks for your interest in improving claude-usage-analytics. Issues and PRs
are welcome.

## Setup

```bash
git clone https://github.com/krishnesh7/claude-usage-analytics
cd claude-usage-analytics
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cd parser && npm install && cd ..
```

## Running tests

```bash
.venv/bin/pytest
```

## Running the dashboard locally

```bash
.venv/bin/cu serve   # http://localhost:7777
```

## Before opening a PR

- Add/update tests for any behavior change (`tests/`).
- Keep PRs focused on a single change - unrelated fixes should be separate PRs.
- If you're changing pricing, SDLC classification, or cost-mode logic, explain
  the reasoning in the PR description; these affect every historical number on
  the dashboard.
- Don't commit personal paths, machine-specific config, or local databases
  (`*.db`).

## Reporting bugs

Open an issue with:
- What you ran (`cu ...` command or dashboard action)
- What you expected vs. what happened
- Your OS, Python version, and Node version (`node --version`)

## Project structure

- `claude_usage/` - Python package (CLI, db, pricing, classification, dashboard server)
- `parser/` - Node.js incremental transcript parser
- `templates/` - dashboard HTML
- `commands/`, `skills/`, `hooks/` - Claude Code plugin integration
- `tests/` - pytest suite
