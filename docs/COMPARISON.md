# claude-usage-tracker vs session-report (official)

Both plugins parse Claude Code's `~/.claude/projects/**/*.jsonl` transcripts and
report on token usage. That's where the similarity ends.

---

## At a glance

| Capability | session-report (official) | claude-usage-tracker (this plugin) |
|---|:---:|:---:|
| Token counts per session | ✅ | ✅ |
| Cache-break detection | ✅ | ✅ via enrichment pipeline |
| Top prompts w/ subagent rollup | ✅ | ✅ via enrichment pipeline |
| Session timeline Gantt | ✅ | ❌ |
| **Persistent history (any time window)** | ❌ re-parse every run | ✅ SQLite |
| **Dollar cost imputation** | ❌ | ✅ USD per session / project / stage |
| **SDLC stage tagging** | ❌ | ✅ requirements · design · impl · test · deploy |
| **Named project registry** | ❌ raw encoded paths | ✅ named products + worktree grouping |
| **In-project CLAUDE_USAGE.md** | ❌ | ✅ auto-updated on every session close |
| **Per-model cost breakdown** | ❌ | ✅ Opus vs Sonnet vs Haiku per turn |
| **Tracker self-overhead** | ❌ | ✅ `_tracker_overhead_` stage |
| **Auto-refresh (Stop hook)** | ❌ manual only | ✅ runs on every session end |
| **Live dashboard** | ❌ | ✅ `cu serve` → localhost:7777 |
| **6-tier session confidence resolver** | ❌ | ✅ EXACT / SUBDIR / WORKTREE / FUZZY / AMBIGUOUS / UNMATCHED |
| **Git worktree consolidation** | ❌ | ✅ worktree sessions roll up to parent project |
| **Cost-mode toggle (API/Conservative/Subscription)** | ❌ | ✅ with auto-detected default per your plan |
| **Efficiency scoring** | ❌ | ✅ 4-axis percentile scoring + recommendations per project |
| **Drill-down navigation (project → stage → session)** | ❌ | ✅ breadcrumb nav in the dashboard |

---

## Deeper comparison

### Persistence — the fundamental difference

**session-report** re-reads every `.jsonl` file from scratch on every run. It has
no memory between invocations. Ask it "what happened last month?" and it re-parses
everything. Its `--since 7d` flag limits what gets shown, but the parse still
happens each time.

**claude-usage-tracker** writes to SQLite on first parse and then only reads new
bytes on subsequent runs (`parse_state` table tracks byte offsets per file). Ask
it for last month, last year, or all time — the answer comes from an indexed DB
in milliseconds.

| Metric | session-report | claude-usage-tracker |
|---|---|---|
| Cold parse (all history) | ~1.3 s | ~0.3 s (first run only) |
| Subsequent parse | ~1.3 s (always full) | ~50 ms (only new bytes) |
| History window | Limited by `--since` flag | Unlimited — grows forever |

---

### Dollar cost imputation

session-report shows token counts. It has no concept of cost.

claude-usage-tracker multiplies every turn's token breakdown by per-model rates
from `~/.claude/usage/prices.json`:

```
cost = (input_tokens        × input_rate)
     + (cache_creation_tokens × cache_write_rate)
     + (cache_read_tokens    × cache_read_rate)
     + (output_tokens        × output_rate)
```

Every view — per-session, per-project, per-stage, per-day — shows imputed USD
alongside token counts. When Anthropic changes pricing you update `prices.json`
once and **all historical data reprices instantly** (the DB stores raw tokens,
not dollars).

---

### Named project registry

session-report groups sessions by their encoded filesystem path:
`-Users-kpujari-Documents-Claude-Projects-rk-canslim`

This creates a separate entry for every working directory variant:
- Main project dir → one entry
- Worktree on a feature branch → different entry
- Subdirectory session → different entry

claude-usage-tracker has a project registry (`~/.claude/usage/projects.json`).
You register a project once with `cu project init my-app`. All sessions from
the root, any subdirectory, or any git worktree automatically roll up to `my-app`.
The 6-tier confidence resolver (`EXACT → SUBDIR → WORKTREE → FUZZY → AMBIGUOUS →
UNMATCHED`) determines which project a session belongs to and how certain we are.

---

### SDLC stage tagging

session-report has no notion of what kind of work a session represents.

claude-usage-tracker classifies every session into one of:
`requirements · design · impl · test · deploy · adhoc · _tracker_overhead_`

Three mechanisms (in priority order):
1. **`stage_map.json`** — explicit cwd substring → stage mapping (zero LLM cost)
2. **Keyword classifier** — scans the first 3 human messages against `stage_keywords.json`
3. **SessionStart hook prompt** — asks Claude to ask the user, once, when the stage is unknown

The `by_stage` table in every report answers: *where am I spending my AI budget
across the product lifecycle?*

---

### In-project CLAUDE_USAGE.md

session-report writes nothing to your project. You invoke `/session-report`,
get a one-time HTML file, and it disappears.

claude-usage-tracker writes `docs/usage/CLAUDE_USAGE.md` directly into your
project and **keeps it current**. The Stop hook regenerates it automatically
when any session closes. Commit it alongside your code — it becomes a permanent,
version-controlled audit trail of how the product was built:

- Daily timeline (last 30 days)
- By SDLC stage
- By work mode (subagent-orchestration · implementation · ops/debug · exploration)
- By git branch type
- By model
- Most expensive prompts (with subagent token rollup)
- Cache breaks with trigger prompt shown
- Full session-by-session audit trail

---

### Enrichment pipeline — best of both

claude-usage-tracker **delegates** cache-break detection and subagent-rollup
prompt attribution to the official analyzer rather than reimplementing them.
During every `cu parse` run:

```
parse.mjs (our incremental parser)    → new sessions/turns → SQLite
analyze-sessions.mjs (official)       → cache_breaks + top_prompts → SQLite
```

The official analyzer's carefully-tuned logic (multi-block deduplication,
Agent-tool → child-session attribution) is reused exactly. Our contribution
is **storing the results permanently** so they survive past the 7-day window
and can be filtered by named project.

---

### Efficiency scoring — not just spend

session-report (and raw token totals generally) tell you *how much* you spent.
Neither tells you whether that spend was *efficient*.

claude-usage-tracker's efficiency panel scores each project on four axes, each a
percentile rank against your other projects:

- **Cache Hygiene** — % of input-side tokens served from cache vs sent fresh
- **Cache Payback** — ratio of cache reads to cache writes (did cached prompts get reused?)
- **Model Fit** — how much spend used lighter models (Sonnet/Haiku) vs Opus
- **Cost Economy** — cost per turn relative to your other projects

Each axis renders as a share-bar with threshold coloring, and projects with
weak axes get a plain-language recommendation (e.g. "Cache Hygiene is low —
most input tokens are sent fresh rather than reused").

### Cost modes — pick the price that matches your plan

Token costs only mean something relative to what you actually pay.
claude-usage-tracker computes three cost modes from the same raw token data:

| Mode | Assumption |
|---|---|
| **API** | Pay-per-token at list price — accurate if you call the API directly |
| **Conservative** | Blended rate assuming ~50% cache savings — a middle-ground estimate |
| **Subscription** | Imputed cost against your subscription plan's token allowance |

`/api/plan-hint` auto-detects which mode matches your plan and pre-selects it
on first load (with a badge showing the detected plan); switching modes
re-renders every cost figure in the dashboard, including the trend chart.

## When to use which

**Use `/session-report`** when you want a quick one-off look at the last 7 days
across all your sessions, with the interactive Gantt timeline. No setup required.

**Use claude-usage-tracker** when you want:
- Historical data beyond 7 days
- Cost in dollars, not just token counts
- Per-product rollups across multiple sessions and worktrees
- A committed CLAUDE_USAGE.md in your project
- SDLC stage visibility ("how much of my impl budget went to testing?")
- Ongoing monitoring via the live dashboard

The two are complementary, not mutually exclusive. We intentionally reuse the
official analyzer's output rather than competing with it.
