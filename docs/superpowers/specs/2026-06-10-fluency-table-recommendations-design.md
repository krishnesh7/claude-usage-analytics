# Fluency Panel: Table Layout + Recommendations

## Context

The dashboard's "fluency" panel (`#fluency-panel` in [templates/dashboard.html](../../../templates/dashboard.html)) currently renders one card per project (`.fluency-card`), each showing a composite percentile score and four axis bars (Cache Hygiene, Cache Payback, Model Fit (global), Cost Economy). `computeFluency(byProject, byModel)` already does all the scoring — only the rendering needs to change.

This spec covers two changes:
1. Replace the card layout with a sortable table, matching the visual language of the other dashboard tables (`#t-project`, `#t-stage`, etc.), using the existing share-bar pattern for axis cells.
2. Add a small "recommendations" section below the table that surfaces actionable tips for the worst-scoring axes, each linking to relevant Anthropic docs.

`computeFluency` itself is unchanged — both features are new rendering/derivation logic layered on its existing output.

## Design: Fluency Table

### Layout

New `<h2>by fluency</h2>` section, structured like the existing tables:

```html
<h2>by fluency <span class="sub" style="font-size:12px;font-weight:400;color:var(--dim);margin-left:8px">token efficiency by project</span></h2>
<p class="hint">Percentile scores within your projects. Higher = more efficient.</p>
<table id="t-fluency">
  <colgroup>
    <col class="c-name"><col class="c-pct"><col class="c-pct"><col class="c-pct"><col class="c-pct"><col class="c-pct">
  </colgroup>
  <thead><tr>
    <th>project</th>
    <th data-tip="Composite of the 4 axes, as a percentile among your projects.">fluency</th>
    <th data-tip="% of input-side tokens served from cache. High = you reuse context well instead of re-sending it fresh.">cache hygiene</th>
    <th data-tip="Ratio of cache reads to cache writes. High = your cached prompts got reused many times.">cache payback</th>
    <th data-tip="How much of your token spend used lighter models (Sonnet/Haiku) vs Opus. Scored globally.">model fit</th>
    <th data-tip="Your cost per turn relative to your other projects. High = efficient spend per interaction.">cost economy</th>
  </tr></thead>
  <tbody></tbody>
</table>
```

This replaces `<div id="fluency-cards" class="fluency-row">` inside `#fluency-panel`. The panel's show/hide logic (`computeFluency` returning `null` when fewer than 2 projects → `panel.style.display = 'none'`) is unchanged.

### Row rendering

Each row: project name, composite score, then one cell per axis. Axis cells reuse the `.share-cell` / `.share-bar` / `.share-text` structure already used for the "%" column in `#t-project`, but tinted by the existing ok/warn/red thresholds (≥70 green, 40-69 yellow, <40 red) instead of the fixed blue:

- Bar fill width = axis score (0-100%), background color = threshold color at ~0.18 opacity
- Score number overlaid on top, text colored to match the threshold (reusing `.pct.ok/.warn/.red`)
- Composite "fluency" column: bold score number only (no bar), same threshold text coloring — same visual weight as the old `.fluency-badge`

New CSS (added near the existing share-bar rules, [templates/dashboard.html:157-159](../../../templates/dashboard.html#L157-L159)):

```css
.share-bar.ok   { background: rgba(78,186,101,0.18); }
.share-bar.warn { background: rgba(255,193,7,0.18); }
.share-bar.red  { background: rgba(255,107,128,0.18); }
```

`.pct.ok/.warn/.red` already exist ([templates/dashboard.html:67-69](../../../templates/dashboard.html#L67-L69)) and provide the matching text colors.

### JS changes

- `renderFluencyPanel(byProject, byModel)` ([templates/dashboard.html:595-641](../../../templates/dashboard.html#L595-L641)): replace the card-building loop with row-building for `#t-fluency tbody`, using `mkRow`. Each axis cell gets `className = 'share-cell'`, a `.share-bar.<cls>` div sized to the score, and a `.share-text pct <cls>` span with the score text. The composite cell gets `className = 'pct <cls>'` with the bold score.
- Register `enableSort('t-fluency', accessors, renderFluencyPanel-equivalent)` so columns are sortable like other tables (accessors index into `scored[i].composite` / `scored[i].axes[n].score`). Cache the `scored` array in `rowCache` for re-render on sort, same pattern as `rowCache['t-project']`.
- `data-tip` on each `<th>` reuses the `tip` strings already present in `computeFluency`'s axis objects ([templates/dashboard.html:580-588](../../../templates/dashboard.html#L580-L588)) — copy them into the static `<th>` markup since the tips are constant text, not per-row.
- Remove the now-unused `.fluency-card`, `.fluency-name`, `.fluency-badge`, `.fluency-axis*`, `.fluency-bar-*` CSS rules ([templates/dashboard.html:94-112](../../../templates/dashboard.html#L94-L112)) and the `#fluency-cards` div/`.fluency-row` CSS, since nothing else references them.

### Row cap

Unlike the card layout (capped at 6 for horizontal width reasons), the table shows all scored projects, consistent with the other dashboard tables — apply the same `.slice(0, 20)` cap used by `renderProjectTable` ([templates/dashboard.html:688](../../../templates/dashboard.html#L688)) for consistency. `computeFluency` already requires ≥2 projects, and project counts are typically well under 20.

## Design: Recommendations

### Placement

A new `<div id="fluency-recs"></div>` directly below `#t-fluency`, inside `#fluency-panel`. Visually identical to the existing "takes" callouts (`#takes-section` / `.take-row`, [templates/dashboard.html:424-448](../../../templates/dashboard.html#L424-L448)): colored left border (red only, since recommendations only fire on red axes), small text, optional bold project name, plus a "Learn more" link.

```html
<div id="fluency-recs"></div>
```

```css
.fluency-rec { border-left: 3px solid var(--red); padding: 6px 10px; margin-bottom: 6px;
  background: rgba(255,107,128,0.06); font-size: 12px; line-height: 1.4; }
.fluency-rec a { color: var(--blue); display: inline-block; margin-top: 4px; }
```

### Algorithm (client-side, in `renderFluencyPanel`)

For each project's `scored` entry (from `computeFluency`):

1. Find the axis with the **lowest score**. Ties broken by axis order (Cache Hygiene, Cache Payback, Model Fit, Cost Economy).
2. If that lowest score is **< 40** (red), it's a candidate: `{ projectName, axisLabel, score }`.
3. Projects whose lowest axis is ≥ 40 produce no candidate.

**Dedup Model Fit:** `Model Fit (global)` is computed once and is identical across all projects ([templates/dashboard.html:544](../../../templates/dashboard.html#L544)), so if it's the worst axis for multiple projects, collapse those candidates into a single entry attributed to "all projects" (keep the shared score).

**Selection:** Sort remaining candidates by score ascending (worst first), take the first **3**.

**No candidates → render nothing.** (No "all good" message — keeping this simple per the locked mockup's "(or nothing)" option.)

### Callout templates

Each candidate renders one `.fluency-rec` div with bold project name (or "all projects" for the Model Fit case), the axis name + score, a one-line actionable tip, and a "Learn more" link:

| Axis | Tip text | Learn more link |
|---|---|---|
| Cache Hygiene | "Cache Hygiene is **{score}** (lowest of your projects). Most input tokens are sent fresh rather than reused from cache. Try keeping a stable prompt prefix so Claude can cache more context." | [Prompt Caching](https://docs.claude.com/en/docs/build-with-claude/prompt-caching) |
| Cache Payback | "Cache Payback is **{score}**. Your cached prompts were written but rarely reused — consider whether the cached context is still relevant across turns." | [Prompt Caching](https://docs.claude.com/en/docs/build-with-claude/prompt-caching) |
| Model Fit (global) | "Model Fit is **{score}** (global). A meaningful share of tokens go to Opus-tier models — consider Sonnet or Haiku for routine work." | [Choosing a model](https://docs.claude.com/en/docs/about-claude/models/choosing-a-model) |
| Cost Economy | "Cost Economy is **{score}**. Cost-per-turn here is higher than your other projects — check for redundant context or heavy subagent fan-out." | [Pricing & cost optimization](https://docs.claude.com/en/docs/about-claude/pricing) |

Format: `<b>{project or "all projects"}</b> — {tip text}` on one line, "Learn more: {title} →" link on the next, opening in a new tab (`target="_blank" rel="noopener"`).

### JS changes

New function `renderFluencyRecs(scored)`, called from `renderFluencyPanel` after the table is built:

```js
function renderFluencyRecs(scored) {
  const container = $('#fluency-recs');
  clearKids(container);
  const RECS = {
    'Cache Hygiene':      { href: 'https://docs.claude.com/en/docs/build-with-claude/prompt-caching', title: 'Prompt Caching' },
    'Cache Payback':      { href: 'https://docs.claude.com/en/docs/build-with-claude/prompt-caching', title: 'Prompt Caching' },
    'Model Fit (global)': { href: 'https://docs.claude.com/en/docs/about-claude/models/choosing-a-model', title: 'Choosing a model' },
    'Cost Economy':       { href: 'https://docs.claude.com/en/docs/about-claude/pricing', title: 'Pricing & cost optimization' },
  };
  // 1. find each project's worst axis; 2. filter score < 40;
  // 3. dedup Model Fit into one "all projects" entry; 4. sort ascending; 5. slice(0, 3)
  // 6. for each candidate, build the tip text from the per-axis template in the
  //    table above (with {score} interpolated and project/"all projects" bolded),
  //    render a .fluency-rec div with that text plus a "Learn more: {RECS[axis].title} →" link to RECS[axis].href
}
```

Text construction follows the same `<b>...</b>`-splitting approach as `renderTakes` ([templates/dashboard.html:436-444](../../../templates/dashboard.html#L436-L444)) to avoid `innerHTML`.

## Edge Cases

- **Fewer than 2 projects** (`computeFluency` returns `null`): `#fluency-panel` stays hidden, including `#fluency-recs` — no change from current behavior.
- **No red axes anywhere**: `#fluency-recs` is left empty (no DOM children) — takes no vertical space.
- **`__system_ops__` pseudo-project**: included in `byProject` like any other row if it appears there; no special-casing needed since it participates in `computeFluency` the same as today's cards.

## Testing

- Existing fluency tests (if any) should be checked for assumptions about `#fluency-cards`/`.fluency-card` and updated to query `#t-fluency` rows instead.
- Manual check in the browser: table renders with correct share-bar widths/colors per threshold, columns sort, recommendations appear/disappear correctly when toggling cost-mode or filters that change which project is "worst".
