# claude-usage-analytics

Local-first token usage & imputed-cost analytics for Claude Code. Parses your
`~/.claude/projects` session transcripts into SQLite and surfaces them through a
live dashboard, static HTML reports, slash commands, and an in-project
`CLAUDE_USAGE.md`. Everything runs offline on your machine — no data leaves it,
and there's near-zero LLM overhead (the parser is pure code).

## What it tracks

- Token usage and imputed API-equivalent **$ cost** per project, SDLC stage, and model
- **Session-kind** split (user vs subagent vs tracker) so totals aren't double-counted
- **Cache-hit rate** per project / stage / model
- Per-day stacked **trend chart** (user vs subagent)
- Cleaned session labels, secret **redaction** on every display surface

## Prerequisites

The plugin auto-creates its Python venv and installs its own dependencies on
first run, but it assumes these are already on your machine:

| Tool | Required | Used for |
|------|----------|----------|
| **Python ≥ 3.10** | yes | the `cu` CLI + dashboard |
| **Node.js** | yes | the transcript parser (`parse.mjs`) |
| Internet (first run only) | yes | one-time `pip install` of deps |
| `jq`, `sqlite3` | optional | hook conveniences; degrade gracefully if absent |

> Without **Node**, the database never populates and reports show zeros.
> `cu parse` prints a warning to stderr if `node` is missing.

## Install

```text
/plugin marketplace add krishnesh7/claude-usage-analytics
/plugin install claude-usage-analytics
```

Then just start a Claude Code session. The `SessionStart` hook runs `bin/cu`,
which on first use:

1. creates a private venv under the plugin and `pip install`s the package,
2. creates the SQLite DB + seeds config defaults,
3. migrates any existing `~/.claude/usage` history,
4. begins parsing your sessions in the background.

No manual setup.

## Slash commands

| Command | Does |
|---------|------|
| `/usage` | Token + cost summary for this project (last 7 days) |
| `/usage-report` | Self-contained interactive HTML report |
| `/usage-doc` | Write/refresh `docs/usage/CLAUDE_USAGE.md` |
| `/usage-parse` | Force a re-parse |
| `/stage` | Set this session's SDLC stage |
| `/project-init` | Register the current directory as a project |
| `/project-list` | List registered projects with totals |
| `/project-confirm` | Verify/correct this session's project tag |
| `/usage-guide` | Getting-started guide |
| `/usage-compare` | Compare vs the official session-report plugin |

## Live dashboard

```bash
cu serve            # http://localhost:7777, auto-refreshes every 30s
```

While serving, a background loop re-parses every 60s so in-flight sessions
appear without a manual refresh. The dashboard has time + kind filters,
sortable tables, per-session drill-down, and session search.

## Configuration

| Env var | Default | Purpose |
|---------|---------|---------|
| `CU_DATA_DIR` | `${CLAUDE_PLUGIN_ROOT}/data` (else `~/.claude/usage`) | Where the DB + config live |
| `CU_REDACT_PROMPTS` | `mask` | Secret redaction mode: `mask` / `hash` / `off` |
| `CU_SERVE_AUTO_PARSE_SEC` | `60` | Dashboard background re-parse interval (`0` disables) |

Pricing lives in `<data dir>/prices.json` (USD per 1M tokens). The DB stores raw
token counts, so editing prices reprices all history retroactively.

## Privacy

- All data stays in your local SQLite DB; nothing is transmitted.
- Prompt content is **redacted** (9 secret patterns) before it reaches the
  dashboard, static report, or `CLAUDE_USAGE.md`.
- The data dir (DB, history) is git-ignored and never committed.

## Development

```bash
git clone https://github.com/krishnesh7/claude-usage-analytics
cd claude-usage-analytics
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/cu --help
```

Run from a checkout and `cu` resolves the parser at `./parser/parse.mjs` and the
data dir at `~/.claude/usage` (no `CLAUDE_PLUGIN_ROOT`).

## License

MIT
