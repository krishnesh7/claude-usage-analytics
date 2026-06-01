# Dashboard Panels — Design Spec
_2026-06-01_

## Problem

The live dashboard (`templates/dashboard.html`) has three pain points:
1. **Visual density** — the stage table has 11 columns; KPI numbers are buried in a single hero text line; all content is stacked in one long scroll.
2. **Missing information** — `_build_takes()` in `_view.py` produces insight commentary on every `/api/summary` call, but `dashboard.html` never renders it. A cost trend line is also absent (only token bars exist).
3. **Clunky navigation** — returning to the overview from a drill-down requires a page refresh; back links are small and easy to miss.

## Solution: Approach B — Dashboard Panels

Restructure `templates/dashboard.html` into a grid-panel layout with a persistent header. Minimal backend changes: one new DB query to supply daily cost data for the trend chart; everything else is already in `/api/summary`.

---

## 1. Persistent Header (replaces single titlebar)

Two always-visible bars at the top of the terminal chrome:

### 1a. Navbar
```
[● ● ●]  ~ overview  /  claude-usage-analytics  /  user sessions   ·  ● live  14:32:01
```
- Dots + path on left; live badge on right.
- Each breadcrumb segment except the last (current level) is a `<button>` that calls the appropriate show function. Clicking `~ overview` calls `showOverview()`; clicking a project name calls `showKindPanel()`.
- Replaces all in-panel `<div class="breadcrumb">` elements.

### 1b. Filter Bar
```
[24h] [7d●] [30d] [all]  |  project: ________  kind: [user only ▾]  [↺ refresh]
```
- Identical controls to the current filter bar, now always visible at every drill depth.
- The `#f-project`, `#f-kind`, `#f-from`, `#f-to` inputs move here from the overview panel.

---

## 2. Overview Panel

### 2a. KPI Cards Row
Four cards in a 4-column grid:

| Card | Value | Δ badge |
|------|-------|---------|
| imputed cost | `$X.XX` | vs prior period cost |
| sessions | `N` | vs prior period sessions |
| total tokens | `X.XM` | vs prior period tokens |
| cache hit rate | `XX%` | vs prior period rate |

The Δ badges use the existing `mkDelta()` helper and `delta-good` / `delta-bad` / `delta-neutral` CSS classes. This surfaces the comparison data that currently only appears in the compressed hero text.

### 2b. Insight Callouts
Rendered immediately below the KPI row. Each `takes` entry from `/api/summary` becomes a left-bordered strip:

```
| 0.18%  tracker overhead is 0.18% of total tokens (target <0.5%) — healthy
| 62%    feature-dev consumed 62% of all tokens — consider balance
```

- Green border: `cls === "good"`
- Yellow border: `cls === "warn"`
- Red border: `cls === "bad"`
- Hidden when `takes` array is empty.

### 2c. Charts Row (Chart.js)
Two panels side-by-side via CSS grid (`1fr 240px`):

**Left — Daily Tokens & Cost Trend**
- Replaces the current SVG sparkline (`#sparkline-wrap`).
- Chart.js bar chart: stacked bars (user tokens blue, subagent tokens orange).
- Overlaid line dataset: daily cost in clay (`#D97757`), right y-axis scaled to dollars.
- Tooltip shows date, total tokens, user/subagent split, daily cost.
- Data source: `d.sparkline` (existing) — cost per day requires a new field `cost_usd` on each sparkline row, added in `_view.py`'s `build()`.

**Right — Model Share Donut**
- Chart.js doughnut chart from `d.by_model`.
- Each segment = one model, sized by `total_tokens`.
- Legend lists model name + percentage.
- Hidden when `by_model` has ≤ 1 entry.

**CDN:** `<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>` added to `<head>`.

### 2d. Projects Table
Columns: `project | sess | turns | tokens | cost | cache·hit | share | Δ cost`

- The `share` column renders an inline CSS bar (absolute-positioned `<div>` behind the percentage text) — no JS needed, pure CSS using `width: X%` on a positioned child.
- Column count unchanged from current (8 cols); the inline bar replaces the plain text `%` column.

### 2e. Stage Table
Trimmed from 11 → 7 columns: `stage | sess | turns | tokens | cost | cache·hit | share`

Removed columns: `input`, `cache·write`, `cache·read`, `output` (individual token breakdown). These are secondary detail not needed for the overview scan. The full breakdown remains available by clicking a stage row to expand the project sub-table.

### 2f. Agent + Skills Tables
Unchanged in structure. Hidden when empty (current behavior preserved).

---

## 3. Navigation Fix

### Current state
- `showOverview()`, `drillIntoProject()`, `renderKindPanel()` are separate JS functions that hide/show three `<div id="panel-*">` elements.
- Back links are `<button>` elements inside each panel, easy to scroll past.

### New state
- The three `<div id="panel-*">` elements are preserved — same show/hide logic.
- A single `renderBreadcrumb(segments)` function updates the navbar breadcrumb on every state transition. `segments` is an array of `{label, onClick}` objects; the last item is rendered as plain text (current level), all others as clickable buttons.
- Called from `showOverview()`, `renderKindPanel()`, and `drillIntoKind()`.

```js
// Example calls
showOverview()         → renderBreadcrumb([{label:'~ overview'}])
renderKindPanel(label) → renderBreadcrumb([{label:'~ overview', onClick:showOverview}, {label}])
drillIntoKind(kind)    → renderBreadcrumb([{label:'~ overview', onClick:showOverview},
                                           {label: projectLabel, onClick:showKindPanel},
                                           {label: kind}])
```

The kind-card intermediate step (user/subagent split + skill attribution) is kept — it provides useful breakdown without an extra API call.

---

## 4. Backend Changes

### 4a. Cost per day in sparkline
`_view.py` `build()` currently produces `sparkline` rows with `{day, user, subagent, total}`. Add `cost_usd: float` per day.

Add `daily_cost_by_day(since, until)` to `db.py`. It joins `turns` on `sessions` grouped by `date(started_at)` and model, returning rows `{day, model, input_tokens, cache_creation_tokens, cache_read_tokens, output_tokens}`. `_view.py` `build()` prices these with `pricing_mod.total_cost()` and merges the result onto each existing sparkline row as `cost_usd`.

### 4b. No other backend changes
`takes`, `by_model`, `by_project`, `by_stage`, `by_agent_type`, `top_skills` are all already in `/api/summary`.

---

## 5. Files Changed

| File | Change |
|------|--------|
| `templates/dashboard.html` | Major rewrite — new HTML structure, CSS additions, JS changes for breadcrumb + Chart.js |
| `claude_usage/_view.py` | Add `cost_usd` field to each sparkline row in `build()` |
| `claude_usage/db.py` | Add `daily_cost_by_day(since, until)` query |

No changes to `serve.py`, `report.html.j2`, `project_usage.md.j2`, or any Python CLI commands.

---

## 6. Out of Scope

- Sessions panel column changes (structure unchanged)
- Stage table per-token column restore toggle (deferred — can add later)
- Keyboard shortcuts / dark/light theme toggle
- Mobile responsiveness improvements
- Export or download functionality
