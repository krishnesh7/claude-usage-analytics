# Fluency Table & Recommendations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the card-based "fluency" panel with a sortable table (matching the other dashboard tables) that uses threshold-colored share-bars for each axis, and add a small recommendations section below it with actionable tips and "Learn more" links.

**Architecture:** Pure frontend change in `templates/dashboard.html` — `computeFluency()` is unchanged. Replace the `#fluency-cards` markup with a new `#t-fluency` table and `#fluency-recs` div, rewrite `renderFluencyPanel()` to render rows instead of cards, add a new `renderFluencyRecs()` derived from the same `computeFluency()` output, and register `#t-fluency` with the existing `enableSort` sorting helper.

**Tech Stack:** Vanilla JS, single-file HTML template (`templates/dashboard.html`), no build step or JS test runner — verification is via `node --check` for syntax and the Claude Preview tools for rendering.

---

## Reference: spec

See [docs/superpowers/specs/2026-06-10-fluency-table-recommendations-design.md](../specs/2026-06-10-fluency-table-recommendations-design.md) for the full design rationale.

## Reference: JS syntax check helper

Several steps verify JS syntax by extracting the inline `<script>` block and running `node --check` on it. Use this command (the script is delimited by lines that are exactly `<script>` and `</script>`):

```bash
sed -n '/^<script>$/,/^<\/script>$/p' templates/dashboard.html | sed '1d;$d' > /tmp/dashboard.js && node --check /tmp/dashboard.js && echo OK
```

Expected output: `OK`

---

### Task 1: Extract `appendRichText` helper and refactor `renderTakes`

**Files:**
- Modify: `templates/dashboard.html` (the `renderTakes` function)

- [ ] **Step 1: Add `appendRichText` helper and refactor `renderTakes` to use it**

Find this exact block (currently around line 424):

```js
function renderTakes(takes) {
  const section = $('#takes-section');
  clearKids(section);
  if (!takes || takes.length === 0) return;
  const borderColors = { good: 'var(--green)', warn: 'var(--yellow)', bad: 'var(--red)' };
  for (const t of takes) {
    const row = document.createElement('div');
    row.className = 'take-row';
    row.style.borderLeftColor = borderColors[t.cls] || 'var(--dim)';
    row.appendChild(mkEl('span', t.fig, 'take-fig'));
    const txtEl = document.createElement('span');
    // Parse <b>...</b> from server-generated text without using innerHTML
    const parts = t.txt.split(/(<b>[^<]*<\/b>)/g);
    for (const part of parts) {
      const m = part.match(/^<b>([^<]*)<\/b>$/);
      if (m) {
        txtEl.appendChild(mkEl('b', m[1]));
      } else {
        txtEl.appendChild(document.createTextNode(part));
      }
    }
    row.appendChild(txtEl);
    section.appendChild(row);
  }
}
```

Replace it with:

```js
// Append text to `el`, rendering any <b>...</b> spans as real <b> elements
// without using innerHTML (avoids HTML injection from any embedded text).
function appendRichText(el, text) {
  const parts = text.split(/(<b>[^<]*<\/b>)/g);
  for (const part of parts) {
    const m = part.match(/^<b>([^<]*)<\/b>$/);
    if (m) {
      el.appendChild(mkEl('b', m[1]));
    } else {
      el.appendChild(document.createTextNode(part));
    }
  }
}

function renderTakes(takes) {
  const section = $('#takes-section');
  clearKids(section);
  if (!takes || takes.length === 0) return;
  const borderColors = { good: 'var(--green)', warn: 'var(--yellow)', bad: 'var(--red)' };
  for (const t of takes) {
    const row = document.createElement('div');
    row.className = 'take-row';
    row.style.borderLeftColor = borderColors[t.cls] || 'var(--dim)';
    row.appendChild(mkEl('span', t.fig, 'take-fig'));
    const txtEl = document.createElement('span');
    appendRichText(txtEl, t.txt);
    row.appendChild(txtEl);
    section.appendChild(row);
  }
}
```

- [ ] **Step 2: Verify JS syntax**

Run the syntax check command from the "Reference" section above.
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add templates/dashboard.html
git commit -m "refactor(dashboard): extract appendRichText helper from renderTakes"
```

---

### Task 2: Replace fluency panel HTML with a table + recommendations container

**Files:**
- Modify: `templates/dashboard.html` (`#fluency-panel` markup, currently around lines 207-211)

- [ ] **Step 1: Replace the fluency panel markup**

Find this exact block:

```html
      <div id="fluency-panel" style="display:none">
        <h2>fluency <span class="sub" style="font-size:12px;font-weight:400;color:var(--dim);margin-left:8px">token efficiency by project</span></h2>
        <p class="hint">Percentile scores within your projects. Higher = more efficient.</p>
        <div id="fluency-cards" class="fluency-row"></div>
      </div>
```

Replace it with:

```html
      <div id="fluency-panel" style="display:none">
        <h2>by fluency <span class="sub" style="font-size:12px;font-weight:400;color:var(--dim);margin-left:8px">token efficiency by project</span></h2>
        <p class="hint">Percentile scores within your projects. Higher = more efficient.</p>
        <table id="t-fluency">
          <colgroup>
            <col class="c-name"><col class="c-pct"><col class="c-pct"><col class="c-pct"><col class="c-pct"><col class="c-pct">
          </colgroup>
          <thead><tr>
            <th>project</th>
            <th data-tip="Composite of the 4 axes below, as a percentile among your projects. Tells you which projects have the healthiest token usage patterns.">fluency</th>
            <th data-tip="% of input-side tokens served from cache. High = you reuse context well instead of re-sending it fresh.">cache hygiene</th>
            <th data-tip="Ratio of cache reads to cache writes. High = your cached prompts got reused many times; low = cache was written but rarely read back.">cache payback</th>
            <th data-tip="How much of your token spend used lighter models (Sonnet/Haiku) vs Opus. Scored globally across all projects in v1.">model fit</th>
            <th data-tip="Your cost per turn relative to your other projects. High = efficient spend per interaction.">cost economy</th>
          </tr></thead>
          <tbody></tbody>
        </table>
        <div id="fluency-recs"></div>
      </div>
```

- [ ] **Step 2: Commit**

```bash
git add templates/dashboard.html
git commit -m "feat(dashboard): replace fluency cards markup with a table + recs container"
```

---

### Task 3: Replace fluency CSS — drop card styles, add share-bar threshold colors and rec styles

**Files:**
- Modify: `templates/dashboard.html` (CSS block, currently around lines 92-112 and 157-159)

- [ ] **Step 1: Replace the `.fluency-*` card rules**

Find this exact block:

```css
  /* Fluency panel */
  .fluency-row { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 20px; }
  .fluency-card {
    background: rgba(255,255,255,0.03); border: 1px solid var(--outline);
    border-radius: 6px; padding: 14px 16px; min-width: 180px; flex: 1 1 180px; max-width: 240px;
  }
  .fluency-name { font-size: 11px; color: var(--dim); white-space: nowrap; overflow: hidden;
    text-overflow: ellipsis; margin-bottom: 8px; }
  .fluency-badge { font-size: 22px; font-weight: 700; margin-bottom: 10px; }
  .fluency-badge.ok   { color: var(--green); }
  .fluency-badge.warn { color: var(--yellow); }
  .fluency-badge.red  { color: var(--red); }
  .fluency-axis { margin-bottom: 6px; }
  .fluency-axis-header { display: flex; justify-content: space-between;
    font-size: 10px; color: var(--dim); margin-bottom: 2px; }
  .fluency-axis-header .ax-score { font-weight: 600; }
  .fluency-bar-track { height: 4px; background: rgba(255,255,255,0.08); border-radius: 2px; }
  .fluency-bar-fill  { height: 4px; border-radius: 2px; transition: width 0.3s; }
  .fluency-bar-fill.ok   { background: var(--green); }
  .fluency-bar-fill.warn { background: var(--yellow); }
  .fluency-bar-fill.red  { background: var(--red); }
```

Replace it with:

```css
  /* Fluency panel */
  .fluency-score { font-weight: 700; }
  .fluency-rec { border-left: 3px solid var(--red); padding: 6px 10px; margin-bottom: 6px;
    background: rgba(255,107,128,0.06); font-size: 12px; line-height: 1.4; }
  .fluency-rec a { color: var(--blue); display: inline-block; margin-top: 4px; }
```

- [ ] **Step 2: Add threshold-colored share-bar variants**

Find this exact block:

```css
  .share-cell { position: relative; overflow: hidden; }
  .share-bar { position: absolute; top: 0; left: 0; height: 100%; background: rgba(100,160,255,0.10); pointer-events: none; }
  .share-text { position: relative; }
```

Replace it with:

```css
  .share-cell { position: relative; overflow: hidden; }
  .share-bar { position: absolute; top: 0; left: 0; height: 100%; background: rgba(100,160,255,0.10); pointer-events: none; }
  .share-bar.ok   { background: rgba(78,186,101,0.18); }
  .share-bar.warn { background: rgba(255,193,7,0.18); }
  .share-bar.red  { background: rgba(255,107,128,0.18); }
  .share-text { position: relative; }
```

- [ ] **Step 3: Commit**

```bash
git add templates/dashboard.html
git commit -m "style(dashboard): drop fluency card CSS, add threshold share-bar colors"
```

---

### Task 4: Rewrite `renderFluencyPanel` to render the table

**Files:**
- Modify: `templates/dashboard.html` (`renderFluencyPanel` function, currently around lines 595-641)

- [ ] **Step 1: Replace `renderFluencyPanel` with table rendering**

Find this exact block:

```js
function renderFluencyPanel(byProject, byModel) {
  const panel = $('#fluency-panel');
  const container = $('#fluency-cards');
  clearKids(container);
  const scored = computeFluency(byProject, byModel);
  if (!scored) { panel.style.display = 'none'; return; }
  panel.style.display = '';

  function scoreCls(s) { return s >= 70 ? 'ok' : s >= 40 ? 'warn' : 'red'; }
  const shortName = n => !n ? '(unknown)' : n.length > 22 ? n.slice(0, 21) + '…' : n;

  for (const p of scored.slice(0, 6)) {
    const card = document.createElement('div');
    card.className = 'fluency-card';

    const nameEl = mkEl('div', shortName(p.name), 'fluency-name');
    nameEl.title = p.name;
    card.appendChild(nameEl);

    const badge = mkEl('div', String(p.composite), 'fluency-badge ' + scoreCls(p.composite));
    badge.dataset.tip = 'Composite of the 4 axes below, as a percentile among your projects. Tells you which projects have the healthiest token usage patterns.';
    card.appendChild(badge);

    for (const ax of p.axes) {
      const axDiv = document.createElement('div');
      axDiv.className = 'fluency-axis';
      axDiv.dataset.tip = ax.tip;

      const header = document.createElement('div');
      header.className = 'fluency-axis-header';
      header.appendChild(mkEl('span', ax.label, 'ax-label'));
      header.appendChild(mkEl('span', String(ax.score), 'ax-score'));
      axDiv.appendChild(header);

      const track = document.createElement('div');
      track.className = 'fluency-bar-track';
      const fill = document.createElement('div');
      fill.className = 'fluency-bar-fill ' + scoreCls(ax.score);
      fill.style.width = ax.score + '%';
      track.appendChild(fill);
      axDiv.appendChild(track);

      card.appendChild(axDiv);
    }
    container.appendChild(card);
  }
}
```

Replace it with:

```js
function fluencyScoreCls(s) { return s >= 70 ? 'ok' : s >= 40 ? 'warn' : 'red'; }

function renderFluencyPanel(byProject, byModel) {
  const panel = $('#fluency-panel');
  const scored = computeFluency(byProject, byModel);
  if (!scored) { panel.style.display = 'none'; return; }
  panel.style.display = '';
  rowCache['t-fluency'] = scored;
  renderFluencyTable(scored);
  renderFluencyRecs(scored);
}

function renderFluencyTable(scored) {
  const tbody = $('#t-fluency tbody');
  clearKids(tbody);
  const shortName = n => !n ? '(unknown)' : n.length > 22 ? n.slice(0, 21) + '…' : n;
  const rows = applySort('t-fluency', scored);
  markSortHeader('t-fluency');
  for (const p of rows.slice(0, 20)) {
    const cls = fluencyScoreCls(p.composite);
    const tr = mkRow([
      { text: shortName(p.name), title: p.name },
      { text: String(p.composite), cls: 'pct fluency-score ' + cls },
    ]);
    for (const ax of p.axes) {
      const axCls = fluencyScoreCls(ax.score);
      const td = document.createElement('td');
      td.className = 'share-cell';
      const bar = document.createElement('div');
      bar.className = 'share-bar ' + axCls;
      bar.style.width = ax.score + '%';
      td.appendChild(bar);
      td.appendChild(mkEl('span', String(ax.score), 'share-text pct ' + axCls));
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
}
```

(`renderFluencyRecs` is added in Task 5 — the file will not pass the syntax check until that task is done, since it's referenced here. Proceed to Task 5 before verifying.)

- [ ] **Step 2: Commit**

```bash
git add templates/dashboard.html
git commit -m "feat(dashboard): render fluency table rows from computeFluency output"
```

---

### Task 5: Add `renderFluencyRecs` and the recommendation templates

**Files:**
- Modify: `templates/dashboard.html` (insert a new function after `renderFluencyTable`, which Task 4 added)

- [ ] **Step 1: Add `FLUENCY_REC_INFO` and `renderFluencyRecs` after `renderFluencyTable`**

Immediately after the closing `}` of `renderFluencyTable` (added in Task 4), insert:

```js

const FLUENCY_REC_INFO = {
  'Cache Hygiene': {
    text: score => `Cache Hygiene is <b>${score}</b> (lowest of your projects). Most input tokens are sent fresh rather than reused from cache. Try keeping a stable prompt prefix so Claude can cache more context.`,
    href: 'https://docs.claude.com/en/docs/build-with-claude/prompt-caching',
    title: 'Prompt Caching',
  },
  'Cache Payback': {
    text: score => `Cache Payback is <b>${score}</b>. Your cached prompts were written but rarely reused — consider whether the cached context is still relevant across turns.`,
    href: 'https://docs.claude.com/en/docs/build-with-claude/prompt-caching',
    title: 'Prompt Caching',
  },
  'Model Fit (global)': {
    text: score => `Model Fit is <b>${score}</b> (global). A meaningful share of tokens go to Opus-tier models — consider Sonnet or Haiku for routine work.`,
    href: 'https://docs.claude.com/en/docs/about-claude/models/choosing-a-model',
    title: 'Choosing a model',
  },
  'Cost Economy': {
    text: score => `Cost Economy is <b>${score}</b>. Cost-per-turn here is higher than your other projects — check for redundant context or heavy subagent fan-out.`,
    href: 'https://docs.claude.com/en/docs/about-claude/pricing',
    title: 'Pricing & cost optimization',
  },
};

function renderFluencyRecs(scored) {
  const container = $('#fluency-recs');
  clearKids(container);

  // 1. Find each project's worst-scoring axis (ties broken by axis order,
  //    since p.axes is always [Cache Hygiene, Cache Payback, Model Fit, Cost Economy]).
  const candidates = [];
  for (const p of scored) {
    let worst = p.axes[0];
    for (const ax of p.axes) {
      if (ax.score < worst.score) worst = ax;
    }
    if (worst.score < 40) {
      candidates.push({ project: p.name, axis: worst.label, score: worst.score });
    }
  }

  // 2. Model Fit (global) is identical across projects — collapse all
  //    occurrences into a single "all projects" entry.
  const modelFit = candidates.filter(c => c.axis === 'Model Fit (global)');
  const deduped = candidates.filter(c => c.axis !== 'Model Fit (global)');
  if (modelFit.length > 0) {
    deduped.push({ project: 'all projects', axis: 'Model Fit (global)', score: modelFit[0].score });
  }

  // 3. Worst first, cap at 3.
  deduped.sort((a, b) => a.score - b.score);

  for (const c of deduped.slice(0, 3)) {
    const info = FLUENCY_REC_INFO[c.axis];
    const row = document.createElement('div');
    row.className = 'fluency-rec';

    const textEl = document.createElement('div');
    appendRichText(textEl, `<b>${c.project}</b> — ${info.text(c.score)}`);
    row.appendChild(textEl);

    const link = document.createElement('a');
    link.href = info.href;
    link.target = '_blank';
    link.rel = 'noopener';
    link.textContent = 'Learn more: ' + info.title + ' →';
    row.appendChild(link);

    container.appendChild(row);
  }
}
```

- [ ] **Step 2: Verify JS syntax**

Run the syntax check command from the "Reference" section above.
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add templates/dashboard.html
git commit -m "feat(dashboard): add fluency recommendations callouts with doc links"
```

---

### Task 6: Register `#t-fluency` for column sorting

**Files:**
- Modify: `templates/dashboard.html` (the `enableSort(...)` registration block, currently around lines 1417-1429)

- [ ] **Step 1: Add the `enableSort` call for `t-fluency`**

Find this exact block:

```js
// Register sortable columns (col index → value accessor).
enableSort('t-project', {
  0: r => (r.display_name || r.project_name || r.project_path || ''),
  1: r => r.sessions, 2: r => r.turns, 3: r => r.total_tokens,
  4: r => r.cost?.total_usd ?? 0, 5: r => r.cache_hit_rate ?? -1,
  6: r => r.pct_of_total ?? 0,
  7: r => r.cost?.total_usd ?? 0,
}, renderProjectTable);
enableSort('t-model', {
  0: r => r.model, 1: r => r.total_tokens, 2: r => r.input_tokens,
  3: r => r.cache_read_tokens, 4: r => r.output_tokens,
  5: r => r.cost?.total_usd ?? 0, 6: r => r.cache_hit_rate ?? -1,
}, renderModelTable);
```

Replace it with:

```js
// Register sortable columns (col index → value accessor).
enableSort('t-project', {
  0: r => (r.display_name || r.project_name || r.project_path || ''),
  1: r => r.sessions, 2: r => r.turns, 3: r => r.total_tokens,
  4: r => r.cost?.total_usd ?? 0, 5: r => r.cache_hit_rate ?? -1,
  6: r => r.pct_of_total ?? 0,
  7: r => r.cost?.total_usd ?? 0,
}, renderProjectTable);
enableSort('t-model', {
  0: r => r.model, 1: r => r.total_tokens, 2: r => r.input_tokens,
  3: r => r.cache_read_tokens, 4: r => r.output_tokens,
  5: r => r.cost?.total_usd ?? 0, 6: r => r.cache_hit_rate ?? -1,
}, renderModelTable);
enableSort('t-fluency', {
  0: r => r.name || '',
  1: r => r.composite,
  2: r => r.axes[0].score,
  3: r => r.axes[1].score,
  4: r => r.axes[2].score,
  5: r => r.axes[3].score,
}, renderFluencyTable);
```

- [ ] **Step 2: Verify JS syntax**

Run the syntax check command from the "Reference" section above.
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add templates/dashboard.html
git commit -m "feat(dashboard): make fluency table columns sortable"
```

---

### Task 7: Manual verification in the browser

**Files:** none (verification only)

- [ ] **Step 1: Start the dashboard server**

Use `preview_start` (or confirm it's already running) to serve the dashboard so it's reachable in the browser preview.

- [ ] **Step 2: Reload and locate the fluency table**

Reload the page (`preview_eval: window.location.reload()`), then use `preview_snapshot` to confirm:
- A `by fluency` heading and `#t-fluency` table are present (replacing the old card row).
- Each row has 6 cells: project, fluency (bold, colored), and 4 axis cells.
- `#fluency-recs` appears below the table.

- [ ] **Step 3: Verify share-bar coloring**

Use `preview_inspect` on a `.share-bar` element inside `#t-fluency` to confirm its `background-color` matches the threshold for its score (green `rgba(78,186,101,0.18)` for ≥70, yellow `rgba(255,193,7,0.18)` for 40-69, red `rgba(255,107,128,0.18)` for <40), and that the bar's `width` matches the displayed score.

- [ ] **Step 4: Verify sorting**

Use `preview_click` on the `fluency` column header, then `preview_snapshot` to confirm rows reorder by composite score (ascending, then descending on a second click).

- [ ] **Step 5: Verify recommendations**

If any project has a red (<40) axis, confirm a `.fluency-rec` callout appears with bold project name, tip text, and a "Learn more" link with `target="_blank"`. If no project has a red axis, confirm `#fluency-recs` is empty (no visible callouts).

- [ ] **Step 6: Verify tooltips**

Use `preview_eval` to hover (dispatch `mouseover`) over a `#t-fluency th` with `data-tip` and confirm the tooltip element (`#tt`) shows the expected text.

- [ ] **Step 7: Take a screenshot for the record**

Use `preview_screenshot` of the fluency section (table + recommendations) to confirm the visual result matches the locked mockup style (`fluency-table-sharebar.html` / `fluency-recs-links.html`).
