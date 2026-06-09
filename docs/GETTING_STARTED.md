# claude-usage-tracker — Getting Started

Track token usage and imputed API-equivalent cost across all your Claude Code
sessions. Data is stored locally in SQLite; nothing leaves your machine.

---

## Prerequisites (already done if you installed the plugin)

| Component | Location | Purpose |
|---|---|---|
| SQLite DB | `~/.claude/usage/usage.db` | Permanent session history |
| Node parser | `~/.claude/usage/parser/parse.mjs` | Reads JSONL → DB |
| Python CLI | `~/code/claude-usage-analytics/.venv/bin/cu` | Analytics + reports |
| Plugin | `~/.claude/plugins/cache/local-rk-plugins/claude-usage-tracker/unknown/` | Slash commands + hooks |
| Prices | `~/.claude/usage/prices.json` | USD/1M-token rates per model |

---

## Starting a new project — 3-step setup

### Step 1 — Register the project

Run once from the project root in your terminal:

```bash
cd /path/to/your-project
cu project init <name>                        # e.g. cu project init my-saas-app
cu project init <name> --notes "brief desc"  # optional free-text note
```

This writes an entry to `~/.claude/usage/projects.json` and immediately
re-links any historical sessions from that directory. Verify:

```bash
cu project list   # shows all registered projects with lifetime token totals
```

### Step 2 — (Optional) pre-tag the SDLC stage

If sessions in this project are always the same stage, add a mapping so the
hook never needs to ask:

```json
// ~/.claude/usage/stage_map.json  →  "mappings" block
"my-saas-app": "impl"
```

Valid stages: `requirements` · `design` · `impl` · `test` · `deploy` · `explore` · `adhoc`

Skip this if you want per-session stage tagging (Claude will ask at a natural
moment when the stage is unknown).

### Step 3 — Open Claude Code normally

The tracker runs invisibly. The SessionStart hook resolves your cwd:

| Confidence | Condition | Behaviour |
|---|---|---|
| **EXACT** | cwd == project root | Silent auto-tag |
| **SUBDIR** | cwd is inside the root | Auto-tag + one-line info |
| **WORKTREE** | git worktree of the project | Auto-tag + one-line info |
| **FUZZY** | pattern match, one project | Soft confirmation note |
| **AMBIGUOUS** | multiple projects match | Claude asks you to pick |
| **UNMATCHED** | nothing matched | Claude asks project + stage |

---

## Day-to-day workflow

```
Open Claude Code
  → SessionStart hook fires (usually silent)
  → Work normally

Close the session
  → Stop hook fires in background (~2 s, non-blocking):
       cu parse        ← ingests new JSONL bytes into SQLite
       enrichment      ← imports cache breaks + top prompts
       cu doc          ← rewrites docs/usage/CLAUDE_USAGE.md in your project
```

The `docs/usage/CLAUDE_USAGE.md` file is always current after each session.
Commit it alongside your code for a permanent record.

---

## Slash commands (inside Claude Code)

| Command | What it does |
|---|---|
| `/usage` | Token + cost summary for this project (last 7 days) |
| `/usage-doc` | Regenerate `CLAUDE_USAGE.md` now |
| `/usage-report` | Full interactive HTML report (saved to current directory) |
| `/usage-parse` | Force re-parse if the DB seems stale |
| `/stage` | Manually set this session's SDLC stage |
| `/project-init` | Register current directory as a new project |
| `/project-list` | All registered projects with token totals |
| `/project-confirm` | Verify/correct this session's project assignment |
| `/usage-guide` | Show this guide |

---

## Live dashboard

```bash
cu serve          # starts at http://localhost:7777
cu serve --port 8888   # custom port
```

Open **http://localhost:7777** in any browser. The dashboard shows:

- Token + cost totals across all projects, filterable by time window
- Per-project spend breakdown
- SDLC stage distribution (impl vs test vs adhoc etc.)
- Auto-refreshes every 30 seconds — leave it open while you work

Stop it with **Ctrl+C** in the terminal when done.

---

## Terminal CLI (`cu`)

```bash
# Text summary
cu summary --project <name>
cu summary --project <name> --since 30d
cu summary --project <name> --stage impl

# HTML report (self-contained file, shareable)
cu report --project <name> --out ~/Desktop/report.html

# Live dashboard (see section above)
cu serve

# Register a new project
cu project init <name>
cu project list
cu project relink   # re-run project tagging after adding patterns

# Force full re-parse + enrichment
cu parse --force

# Classify new sessions
cu classify

# Re-run classifier on all existing sessions (e.g. after editing stage_keywords.json)
cu classify --reclassify

# Override a session's stage
cu stage --session <uuid> --set impl

# Override a session's project
cu project tag --session <uuid> --name <project-name>

# Resolve a directory to a project (shows confidence tier)
cu session-resolve --cwd /path/to/dir
```

---

## Reading CLAUDE_USAGE.md

| Section | What to look for |
|---|---|
| **Summary** | Lifetime cost; compare projects to size up relative spend |
| **By SDLC stage** | High `adhoc` = sessions aren't being tagged; run `cu classify --reclassify` or add project to `stage_map.json` |
| **By work mode** | High `subagent-orchestration` = lots of parallel agent work |
| **Most expensive prompts** | Tokens include all subagent work — the *true* cost of each message |
| **Cache breaks** | Each row = cache flushed mid-session; trigger column shows what caused it |
| **Session audit trail** | Top tools column reveals session character (Edit×50 = impl, Bash×80 = debug) |

---

## Reducing overhead

| Tip | Why it helps |
|---|---|
| Start sessions in the project **root**, not a subdir | Gets EXACT confidence → zero prompting overhead |
| Add frequent projects to **`stage_map.json`** | Eliminates stage-tagging LLM call entirely |
| Avoid **`/model` mid-session** | Model switches flush the cache; start a new session instead |
| Break sessions at **natural boundaries** | Long "continue" sessions after hours = cold cache anyway |
| Register **worktrees** via `cu project init` | Feature-branch sessions roll up to the same project automatically |

---

## Updating prices

When Anthropic publishes new pricing, edit `~/.claude/usage/prices.json`.
Format: USD per 1 million tokens.

```json
{
  "claude-opus-4-7": {
    "input": 15.00, "output": 75.00,
    "cache_write_5m": 18.75, "cache_write_1h": 30.00, "cache_read": 1.50
  }
}
```

All historical cost calculations update immediately — the DB stores raw tokens,
not dollars, so a prices.json change reprices everything retroactively.
