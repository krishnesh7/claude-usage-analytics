# Tier 2 Dashboard Features — Design Spec
_2026-05-29_

## Scope

Three features from the Tier 2 roadmap. Two features deferred with notes:
- **Outliers panel** — deferred; future enhancement
- **CSV export** — deferred; future enhancement

Features in scope:
1. Date-range picker
2. Compare windows
3. Skill / plugin attribution

---

## 1. Date-range Picker

### Goal
Replace the fixed `<select>` (24h / 7d / 30d / all) with a from/to date pair plus quick-pick preset buttons, giving users precise control over the analysis window.

### UI
The controls bar changes from:
```
project [____]   since [▼ 7d]   kind [▼ user only]   [↺ refresh]
```
to:
```
project [____]   [24h] [7d] [30d] [all]   from [2026-05-22]  to [2026-05-29]   kind [▼ user only]   [↺ refresh]
```

- Preset buttons are `<button class="preset-btn">` elements; the active preset gets a highlighted border
- Clicking a preset auto-fills both date fields with the computed range and fires `load()`
- Manually editing either date field deactivates all presets and fires `load()` on blur or Enter
- On initial page load, the `7d` preset is active and date fields are pre-filled accordingly

### Backend changes

**`db.py`**
- Add `parse_until(s: str | None) -> datetime | None` mirroring `parse_since`
- All query functions that accept `since` gain a companion `until: datetime | None = None` parameter
- Each adds `AND <ts_col> <= ?` to WHERE when `until` is set
- Affected functions: `totals_by_stage`, `totals_by_project`, `totals_by_agent_type`, `turns_by_model`, `turns_by_model_for_stage`, `daily_timeline`, `daily_timeline_by_kind`, `top_skills`

**`serve.py`**
- `/api/summary` gains `until: str | None = Query(default=None)`; passes `parse_until(until)` through to `_view.build()`
- `/api/sessions` gains `until: str | None = Query(default=None)` for consistency
- No breaking changes — `until=None` is unbounded (existing behaviour)

**`_view.py`**
- `build()` gains `until: datetime | None = None` and threads it through all `db.*` calls

### Invariants
- `from` must be ≤ `to`; if user enters an invalid range the fields go red and `load()` is not called
- When `until` is set to today or later, compare windows still computes correctly (see §2)

---

## 2. Compare Windows

### Goal
Show whether spend/usage is trending up or down relative to the equivalent prior period. Surfaces in two places: hero stat delta badges and a Δ cost column in the project table.

### Prior-period computation (frontend)
Given a window `[from, to]` of duration `D = to - from`:
```
priorFrom = from - D
priorUntil = from   (exclusive)
```
Examples:
- Last 7d → prior 7d before that
- Custom 2026-05-01 → 2026-05-14 → compares against 2026-04-18 → 2026-05-01

When the `all` preset is active, compare is disabled (no bounded prior period). Delta badges are hidden.

### Frontend — two parallel fetches
`load()` fires two `/api/summary` calls simultaneously using `Promise.all`:
1. Current: `since=<from>&until=<to>`
2. Prior: `since=<priorFrom>&until=<priorUntil>`

No new API endpoint needed.

### Hero badges
The three hero stat values (cost, tokens, cache-hit %) each gain a `<span class="delta">` badge:
- `+$1.20 ↑` / `-$0.40 ↓` for cost (red if up, green if down — higher cost is worse)
- `+12M ↑` / `-3M ↓` for tokens (red if up, green if down)
- `+2.1% ↑` / `-0.8% ↓` for cache hit (green if up, red if down — higher cache is better)
- Badge hidden when prior value is zero (no data) or compare is disabled

### Project table Δ cost column
- Added as the last column in `#t-project`
- After both fetches resolve, each project row looks up its cost in the prior window data by project key
- Shows `+$X.XX` / `-$X.XX` coloured accordingly; `—` if project had no prior data
- Column header: `Δ cost`

### Sorting
The existing `enableSort` wiring for `t-project` is extended to include the new `Δ cost` column.

---

## 3. Skill / Plugin Attribution

### Goal
Surface which Claude Code skills/plugins are driving usage, both globally on the overview and per-project in the drill-down.

### Overview — `▸ top skills` section

**Data:** `top_skills` array is already present in the `/api/summary` payload:
```json
[{"skill_name": "frontend-design", "invocations": 12, "sessions": 4}, ...]
```

**UI:** New `<table id="t-skills">` section below the model table:
```
▸ top skills
skill                  invocations   sessions
frontend-design             12          4
feature-dev:feature-dev      8          3
...
```

New `renderSkillsTable(rows)` function. No backend changes needed.

### Project drill-down — attribution panel

**New endpoint:**
```python
@app.get("/api/attribution")
def api_attribution(project: str = Query(...)) -> JSONResponse:
    return JSONResponse({"attribution": dbmod.attribution_for_project(project)})
```
Backed by `attribution_for_project()` already in `db.py`.

Response shape:
```json
[{"plugin": "frontend-design", "skill": "frontend-design", "turns": 45, "sessions": 3}, ...]
```

**UI placement:** The kind-selector panel (`#panel-kind`) gains a `▸ skill attribution` subsection below the kind cards. It is fetched in parallel with the sessions fetch inside `drillIntoProject()`:

```js
const [sessionsResp, attrResp] = await Promise.all([
  fetch(`/api/sessions?project=...`),
  fetch(`/api/attribution?project=...`)
]);
```

The attribution table shows: plugin · skill · turns · sessions. If the project has no attribution data, the section is hidden.

---

## Files Changed

| File | Change |
|------|--------|
| `templates/dashboard.html` | Preset buttons + date fields; delta badges + Δ col; top-skills table; attribution panel in kind view |
| `claude_usage/db.py` | Add `parse_until()`; add `until` param to 8 query functions |
| `claude_usage/_view.py` | Add `until` param, thread through db calls |
| `claude_usage/serve.py` | Add `until` to `/api/summary` and `/api/sessions`; add `/api/attribution` endpoint |

No schema migrations. No new tables. No new Python dependencies.

---

## Out of Scope (deferred)

- **Outliers panel** (top-5 costliest / worst cache-hit sessions) — future enhancement
- **CSV export** — future enhancement
- **Worktree rollup / unmatched bucket** — Tier 3, separate spec
