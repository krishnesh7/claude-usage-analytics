# Fluency Panel + Dashboard Tooltips

**Date:** 2026-06-09
**Status:** Approved

## Overview

Two related improvements to the dashboard:

1. **Fluency Panel** — a "fitness tracker" section showing per-project AI usage efficiency across 4 axes, scored as peer-normalized percentiles within the user's own project data.
2. **Tooltips** — hover explanations on every metric label, table header, and Fluency axis across the dashboard.

---

## Part 1: Fluency Panel

### Location

Between the KPI cards/takes section and the "by project" table. Inserted as `<div id="fluency-panel">` in the overview panel HTML.

### Data Source

Computed from `d.by_project` (already fetched by `/api/data`). No new backend endpoint needed. Model Fit requires `by_model` broken down per project — use `by_project` rows which already carry `total_tokens`; Model Fit falls back to a neutral score (50) if per-project model breakdown is unavailable in the current data shape. A future enhancement can add per-project model split to the backend.

### Layout

Horizontal scrollable row of cards, one per project, ordered by total token volume descending. Show top 6 projects (cards are wider than table rows; 6 fits without horizontal scroll on a typical 1280px viewport). On narrow viewports cards wrap.

Each card:
- Project name (truncated to ~20 chars, full name in tooltip)
- Composite Fluency badge: a single 0–100 number with color
- 4 axis rows: label + thin progress bar (full width of card) + score number

### Axes

All axes produce a raw score ∈ [0, 1], then are ranked across all projects and rescaled to percentile 0–100.

| Axis | Raw Score Formula | Direction |
|---|---|---|
| Cache Hygiene | `cache_read_tokens / (input_tokens + cache_creation_tokens + cache_read_tokens)` | higher = better |
| Cache Payback | `min(cache_read_tokens / max(cache_creation_tokens, 1), 1)` | higher = better |
| Model Fit | `1 - (opus_fraction)` where `opus_fraction = opus_tokens / total_tokens`; defaults to `0.5` if model breakdown unavailable | higher = better |
| Cost Economy | `1 - (cost_per_turn / max_cost_per_turn_across_projects)` | higher = better |

**Composite score:** arithmetic mean of the 4 percentile scores, rounded to integer.

**Percentile normalization:** for N projects, the project with the highest raw score gets 100, lowest gets 0. With only 1 project, score is 50 for all axes.

### Color Thresholds

Reuses existing CSS classes:
- ≥ 70 → `.ok` (green)
- 40–69 → `.warn` (yellow)
- < 40 → `.red` (red)

Applied to both the axis bar fill and the composite badge.

### Rendering

Pure JS, computed client-side from `d.by_project` and `d.by_model` inside `renderFluencyPanel(byProject, byModel)`. Called from the main `render()` function alongside other table renders.

Model Fit computation: aggregate `by_model` rows whose model name contains "opus", compute their share of total tokens. Since `by_model` is a global breakdown (not split per-project), every project card gets the **same** Model Fit score in v1. This is noted in the axis label with "(global)" and is acceptable since model choice is usually consistent across a user's projects. A future enhancement adds per-project model breakdown to the backend.

### HTML Structure

```html
<div id="fluency-panel" style="display:none">
  <h2>fluency <span class="sub">token efficiency by project</span></h2>
  <p class="hint">Percentile scores within your projects. Higher = more efficient.</p>
  <div id="fluency-cards" class="fluency-row"></div>
</div>
```

Hidden when fewer than 2 projects exist (percentile ranking is meaningless with 1 project).

---

## Part 2: Tooltips

### Mechanism

A single shared tooltip element `<div id="tt">` appended to `<body>`. Absolutely positioned, follows mouse. Shown on `mouseenter` of any element carrying a `data-tip` attribute; hidden on `mouseleave`.

```css
#tt {
  position: fixed; pointer-events: none; z-index: 100;
  background: var(--tb); color: var(--fg);
  border: 1px solid var(--outline); border-radius: 4px;
  padding: 5px 9px; font-size: 11px; max-width: 260px;
  line-height: 1.4; display: none; white-space: normal;
}
```

`data-tip` is added to elements in HTML (static) or injected via JS (dynamic table headers, KPI cards, Fluency axes).

### Tooltip Coverage

**KPI Cards** (injected in `renderKpiCards`):

| Card | Tooltip |
|---|---|
| imputed cost | Cost estimated from token counts. Mode (API / Conservative / Subscription) sets the pricing assumption. |
| sessions | Total conversation sessions in the selected period. |
| total tokens | Sum of input, cache creation, cache read, and output tokens across all turns. |
| cache hit | % of input-side tokens served from cache. Higher means less re-sending repeated context. |

**Cost mode buttons** (static `data-tip` in HTML):

| Button | Tooltip |
|---|---|
| API | Pay-per-token API pricing. Accurate if you use the API directly. |
| Conservative | Blended rate assuming ~50% cache savings. A middle-ground estimate. |
| Subscription | Imputed cost using subscription plan token allowance. Use if you pay a flat monthly fee. |

**Table column headers** (static `data-tip` in `<th>` elements):

| Header | Tooltip |
|---|---|
| sess | Number of conversation sessions |
| turns | Number of back-and-forth exchanges (one user message + one assistant response = one turn) |
| tokens | Total tokens consumed (input + cache creation + cache read + output) |
| cost | Estimated cost under the selected pricing mode |
| cache·hit | % of input-side tokens that came from the prompt cache. Green ≥ 85%, yellow ≥ 50%, red < 50%. |
| % (project/stage) | This row's share of total tokens in the selected period |
| Δ cost | Cost change vs. the previous equivalent period. Green = spending less, red = spending more. |
| input | Fresh input tokens sent to the model (not from cache) |
| cache·read | Tokens read from the prompt cache (billed at ~10× lower rate) |
| output | Tokens generated by the model |
| avg/sess | Average tokens per session |
| agent_type | The subagent role (e.g. code-architect, code-reviewer) or "(main)" for the top-level session |

**Fluency axis labels** (injected in `renderFluencyPanel`):

| Axis | Tooltip |
|---|---|
| Cache Hygiene | % of input-side tokens served from cache. High = you reuse context well instead of re-sending it fresh. |
| Cache Payback | Ratio of cache reads to cache writes. High = your cached prompts got reused many times; low = you wrote cache that was rarely read back. |
| Model Fit | How much of your token spend used lighter models (Sonnet/Haiku) vs Opus. High = right-sizing model choice to task complexity. (Scored globally across all projects in v1.) |
| Cost Economy | Your cost per turn relative to your other projects. High = efficient spend per interaction. |
| Fluency (badge) | Composite of the 4 axes above, as a percentile among your projects. Tells you which projects have the healthiest token usage patterns. |

---

## Implementation Notes

- No backend changes required for v1.
- Model Fit uses global `by_model` data; per-project model breakdown is a future enhancement.
- Fluency panel is hidden when `by_project` has fewer than 2 rows.
- Tooltip JS is ~20 lines, appended once at page init.
- All `data-tip` strings are set in HTML or JS — no external data source.

---

## Files Changed

- `templates/dashboard.html` — all changes (HTML structure, CSS, JS)
