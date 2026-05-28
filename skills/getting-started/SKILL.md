---
name: getting-started
description: >
  Use when the user asks how to set up the claude-usage-tracker for a new
  project, wants to register a project, doesn't see their sessions being
  tracked, or asks what commands are available. Walks through the 3-step
  setup and surfaces the right CLI commands for their situation.
---

# claude-usage-tracker — New Project Setup

You are helping the user set up token/cost tracking for a new Claude Code
project. Follow these steps in order, checking state before running commands.

## Step 1 — Verify the tracker is installed

```bash
~/.claude/usage/parser/parse.mjs --version 2>/dev/null || \
  ls ~/.claude/usage/usage.db 2>/dev/null && echo "DB exists" || echo "DB missing"
```

If the DB doesn't exist yet, run `cu parse` first.

## Step 2 — Check if the project is already registered

```bash
/Users/kpujari/code/claude-usage-analytics/.venv/bin/cu project list
```

If the project already appears in the list, skip to Step 4.

## Step 3 — Register the project

Ask the user for the project name if you don't already know it.
Then run from the project's root directory:

```bash
cd <project-root>
/Users/kpujari/code/claude-usage-analytics/.venv/bin/cu project init <name>
```

Confirm registration succeeded — the output shows `match_patterns` that will
be used to link sessions.

## Step 4 — Check stage mapping (optional but recommended)

```bash
cat ~/.claude/usage/stage_map.json
```

If the project's directory name is not in the `mappings` block, offer to add
it. Ask: "What SDLC stage are most sessions in this project?
(requirements / design / impl / test / deploy / adhoc)"

When they answer, show them the line to add to `stage_map.json`.

## Step 5 — Confirm session resolution

Run a quick confidence check on the current directory:

```bash
/Users/kpujari/code/claude-usage-analytics/.venv/bin/cu session-resolve --cwd "$(pwd)"
```

Explain the result:
- `EXACT` or `SUBDIR` → perfect, sessions will auto-tag silently
- `FUZZY` → will work but might prompt occasionally; offer to tighten the pattern
- `UNMATCHED` → registration didn't take; check that `cu project list` shows the project

## Step 6 — Show quick-reference

Summarise the key commands they'll use day-to-day:

| What | How |
|---|---|
| See this week's spend | `/usage` in Claude Code |
| Check session assignment | `/project-confirm` |
| Regenerate CLAUDE_USAGE.md | `/usage-doc` |
| Full HTML report | `/usage-report` |
| Fix project tag mid-session | `/project-confirm` → follow prompts |
| Read the full guide | `/usage-guide` |

## Notes

- Sessions that happened **before** registration are retroactively linked — the
  parser uses path matching, not a hook, so historical data is not lost.
- Worktrees are auto-detected by `cu project init` and grouped under the parent
  project automatically.
- The `docs/usage/CLAUDE_USAGE.md` file in the project is auto-updated after
  each session closes (Stop hook). Commit it with your code.
