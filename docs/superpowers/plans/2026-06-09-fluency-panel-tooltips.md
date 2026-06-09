# Fluency Panel + Dashboard Tooltips Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-project Fluency efficiency panel (4-axis percentile scoring) and hover tooltips on every metric label across the dashboard.

**Architecture:** All changes are in `templates/dashboard.html` — no backend required. The Fluency panel is computed client-side from `d.by_project` and `d.by_model` already returned by `/api/data`. Tooltips use a single shared `#tt` div with global `mouseenter` delegation on any `[data-tip]` element.

**Tech Stack:** Vanilla JS, CSS custom properties (existing design system), Chart.js (already present, not touched), pytest for data-shape regression test.

---

## Files

- **Modify:** `templates/dashboard.html` (all 4 tasks)
- **Modify:** `tests/test_dashboard_panels.py` (Task 3 — data shape regression)

---

## Task 1: Tooltip CSS, HTML element, and init JS

**Files:**
- Modify: `templates/dashboard.html`

- [ ] **Step 1: Add `#tt` CSS rule inside the existing `<style>` block**

  Find the `.spark-tip` rule at line ~73 and insert after it:

  ```css
  #tt {
    position: fixed; pointer-events: none; z-index: 100;
    background: var(--tb); color: var(--fg);
    border: 1px solid var(--outline); border-radius: 4px;
    padding: 5px 9px; font-size: 11px; max-width: 260px;
    line-height: 1.4; display: none; white-space: normal;
  }
  [data-tip] { cursor: default; }
  ```

- [ ] **Step 2: Add `<div id="tt"></div>` just before `</body>` (line 1287)**

  ```html
  <div id="tt"></div>
  </body>
  ```

- [ ] **Step 3: Add `initTooltips()` function and call it at page init**

  Add the function just before the `applyPreset('7d')` call at line ~1283:

  ```js
  function initTooltips() {
    const tt = document.createElement('div');
    tt.id = 'tt';
    document.body.appendChild(tt);
    document.addEventListener('mouseover', e => {
      const el = e.target.closest('[data-tip]');
      if (!el) { tt.style.display = 'none'; return; }
      tt.textContent = el.dataset.tip;
      tt.style.display = 'block';
    });
    document.addEventListener('mousemove', e => {
      tt.style.left = (e.clientX + 14) + 'px';
      tt.style.top  = (e.clientY + 14) + 'px';
    });
    document.addEventListener('mouseout', e => {
      if (!e.target.closest('[data-tip]')) tt.style.display = 'none';
    });
  }
  initTooltips();
  ```

  Note: `#tt` in HTML (step 2) and the one created in JS will coexist — remove the HTML one since `initTooltips` creates it programmatically. Only keep the JS creation in step 3; do NOT add the HTML `<div id="tt">` in step 2.

- [ ] **Step 4: Start the dev server and verify tooltip appears on hover**

  ```bash
  cu serve --port 7777
  ```

  Open `http://localhost:7777`. There's nothing with `data-tip` yet so no tooltip fires — this step just confirms the JS doesn't throw. Check browser console for errors.

- [ ] **Step 5: Commit**

  ```bash
  git add templates/dashboard.html
  git commit -m "feat(dashboard): add tooltip infrastructure (#tt, initTooltips)"
  ```

---

## Task 2: Add `data-tip` to static HTML elements

**Files:**
- Modify: `templates/dashboard.html`

Add `data-tip` attributes directly in the HTML for all static elements: cost mode buttons and every `<th>` across all 5 tables.

- [ ] **Step 1: Add `data-tip` to cost mode buttons (~line 151–153)**

  Replace:
  ```html
  <button class="preset-btn cost-mode-btn" data-mode="api">API</button>
  <button class="preset-btn cost-mode-btn" data-mode="conservative">Conservative</button>
  <button class="preset-btn cost-mode-btn active" data-mode="subscription">Subscription</button>
  ```
  With:
  ```html
  <button class="preset-btn cost-mode-btn" data-mode="api" data-tip="Pay-per-token API pricing. Accurate if you use the API directly.">API</button>
  <button class="preset-btn cost-mode-btn" data-mode="conservative" data-tip="Blended rate assuming ~50% cache savings. A middle-ground estimate.">Conservative</button>
  <button class="preset-btn cost-mode-btn active" data-mode="subscription" data-tip="Imputed cost using subscription plan token allowance. Use if you pay a flat monthly fee.">Subscription</button>
  ```

- [ ] **Step 2: Add `data-tip` to project table `<th>` elements (~line 185)**

  Replace:
  ```html
  <thead><tr><th>project</th><th>sess</th><th>turns</th><th>tokens</th><th>cost</th><th>cache·hit</th><th>%</th><th>Δ cost</th></tr></thead>
  ```
  With:
  ```html
  <thead><tr>
    <th>project</th>
    <th data-tip="Number of conversation sessions">sess</th>
    <th data-tip="Number of back-and-forth exchanges (user message + assistant response = 1 turn)">turns</th>
    <th data-tip="Total tokens consumed (input + cache creation + cache read + output)">tokens</th>
    <th data-tip="Estimated cost under the selected pricing mode">cost</th>
    <th data-tip="% of input-side tokens served from cache. Green ≥ 85%, yellow ≥ 50%, red &lt; 50%.">cache·hit</th>
    <th data-tip="This row's share of total tokens in the selected period">%</th>
    <th data-tip="Cost change vs. the previous equivalent period. Green = spending less, red = spending more.">Δ cost</th>
  </tr></thead>
  ```

- [ ] **Step 3: Add `data-tip` to model table `<th>` elements (~line 191)**

  Replace:
  ```html
  <thead><tr><th>model</th><th>tokens</th><th>input</th><th>cache·read</th><th>output</th><th>cost</th><th>cache·hit</th></tr></thead>
  ```
  With:
  ```html
  <thead><tr>
    <th>model</th>
    <th data-tip="Total tokens consumed (input + cache creation + cache read + output)">tokens</th>
    <th data-tip="Fresh input tokens sent to the model (not from cache)">input</th>
    <th data-tip="Tokens read from the prompt cache (billed at ~10× lower rate)">cache·read</th>
    <th data-tip="Tokens generated by the model">output</th>
    <th data-tip="Estimated cost under the selected pricing mode">cost</th>
    <th data-tip="% of input-side tokens served from cache. Green ≥ 85%, yellow ≥ 50%, red &lt; 50%.">cache·hit</th>
  </tr></thead>
  ```

- [ ] **Step 4: Add `data-tip` to stage table `<th>` elements (~line 201)**

  Replace:
  ```html
  <thead><tr><th>stage</th><th>sess</th><th>turns</th><th>tokens</th><th>cost</th><th>cache·hit</th><th>%</th></tr></thead>
  ```
  With:
  ```html
  <thead><tr>
    <th>stage</th>
    <th data-tip="Number of conversation sessions">sess</th>
    <th data-tip="Number of back-and-forth exchanges (user message + assistant response = 1 turn)">turns</th>
    <th data-tip="Total tokens consumed (input + cache creation + cache read + output)">tokens</th>
    <th data-tip="Estimated cost under the selected pricing mode">cost</th>
    <th data-tip="% of input-side tokens served from cache. Green ≥ 85%, yellow ≥ 50%, red &lt; 50%.">cache·hit</th>
    <th data-tip="This row's share of total tokens in the selected period">%</th>
  </tr></thead>
  ```

- [ ] **Step 5: Add `data-tip` to agent table `<th>` elements (~line 208)**

  Replace:
  ```html
  <thead><tr><th>agent_type</th><th>sess</th><th>turns</th><th>tokens</th><th>avg/sess</th></tr></thead>
  ```
  With:
  ```html
  <thead><tr>
    <th data-tip="The subagent role (e.g. code-architect, code-reviewer) or '(main)' for the top-level session">agent_type</th>
    <th data-tip="Number of conversation sessions">sess</th>
    <th data-tip="Number of back-and-forth exchanges (user message + assistant response = 1 turn)">turns</th>
    <th data-tip="Total tokens consumed (input + cache creation + cache read + output)">tokens</th>
    <th data-tip="Average tokens per session">avg/sess</th>
  </tr></thead>
  ```

- [ ] **Step 6: Add `data-tip` to sessions drill-down table `<th>` elements (~line 240)**

  Replace:
  ```html
  <thead><tr><th>started</th><th>stage</th><th>turns</th><th>tokens</th><th>cost</th><th>cache·read</th><th>name / id</th></tr></thead>
  ```
  With:
  ```html
  <thead><tr>
    <th>started</th>
    <th data-tip="SDLC stage classified for this session (explore, build, fix, etc.)">stage</th>
    <th data-tip="Number of back-and-forth exchanges (user message + assistant response = 1 turn)">turns</th>
    <th data-tip="Total tokens consumed (input + cache creation + cache read + output)">tokens</th>
    <th data-tip="Estimated cost under the selected pricing mode">cost</th>
    <th data-tip="Tokens read from the prompt cache (billed at ~10× lower rate)">cache·read</th>
    <th>name / id</th>
  </tr></thead>
  ```

- [ ] **Step 7: Verify tooltips fire in browser**

  Open `http://localhost:7777`. Hover over any `<th>` column header — tooltip should appear after cursor moves over the element. Hover over API / Conservative / Subscription buttons.

- [ ] **Step 8: Commit**

  ```bash
  git add templates/dashboard.html
  git commit -m "feat(dashboard): add data-tip to table headers and cost mode buttons"
  ```

---

## Task 3: KPI card tooltips + data shape test

**Files:**
- Modify: `templates/dashboard.html`
- Modify: `tests/test_dashboard_panels.py`

- [ ] **Step 1: Write failing test — verify `by_project` rows carry fields needed for Fluency**

  Add to `tests/test_dashboard_panels.py`:

  ```python
  import sqlite3 as _sqlite3
  from claude_usage._view import projects_view


  def _insert_full_turn(db_path, session_id, project_name, ts, model,
                        input_tokens=1000, output_tokens=200,
                        cache_creation_tokens=800, cache_read_tokens=3000):
      conn = _sqlite3.connect(str(db_path))
      conn.execute(
          "INSERT OR IGNORE INTO sessions(session_id, project_name, started_at) VALUES (?,?,?)",
          (session_id, project_name, ts),
      )
      conn.execute(
          """INSERT INTO turns(session_id, ts, model,
               input_tokens, output_tokens,
               cache_creation_tokens, cache_read_tokens)
             VALUES (?,?,?,?,?,?,?)""",
          (session_id, ts, model, input_tokens, output_tokens,
           cache_creation_tokens, cache_read_tokens),
      )
      conn.commit()
      conn.close()


  def test_by_project_has_fluency_fields(db):
      """by_project rows must carry the fields used by computeFluency() client-side."""
      _insert_full_turn(db, "fx1", "alpha", "2026-06-01T10:00:00",
                        "claude-sonnet-4-6")
      _insert_full_turn(db, "fx2", "beta",  "2026-06-01T11:00:00",
                        "claude-opus-4-8")

      rows = projects_view()

      assert len(rows) >= 2
      for r in rows:
          assert "cache_read_tokens"    in r, f"missing cache_read_tokens in {r}"
          assert "cache_creation_tokens" in r, f"missing cache_creation_tokens in {r}"
          assert "input_tokens"         in r, f"missing input_tokens in {r}"
          assert "total_tokens"         in r, f"missing total_tokens in {r}"
          assert "turns"                in r, f"missing turns in {r}"
  ```

- [ ] **Step 2: Run test to see it fail (or pass if `projects_view` already exists)**

  ```bash
  cd /Users/kpujari/code/claude-usage-analytics
  python -m pytest tests/test_dashboard_panels.py::test_by_project_has_fluency_fields -v
  ```

  If `projects_view` doesn't exist in `_view.py`, it will fail with ImportError — check `_view.py` for the correct function name. The function that feeds `d.by_project` is `projects_by_dim` or `totals_by_project` in `db.py`, assembled via `_view.py`. Find it with:

  ```bash
  grep -n "def.*project\|by_project" claude_usage/_view.py | head -20
  ```

  Adjust the import to match the actual function name.

- [ ] **Step 3: Run all tests to establish baseline**

  ```bash
  python -m pytest tests/ -v --tb=short 2>&1 | tail -20
  ```

  Expected: all existing tests pass (77 currently). Note any pre-existing failures.

- [ ] **Step 4: Add `data-tip` to KPI cards inside `renderKpiCards` (~line 289)**

  The `cards` array already has a `label` field. Add a `tip` field to each card object, then set `card.dataset.tip` after `card.className = 'kpi-card'`:

  ```js
  const cards = [
    {
      label: 'imputed cost',
      tip: 'Cost estimated from token counts. The mode (API / Conservative / Subscription) sets the pricing assumption.',
      // ... existing fields unchanged
    },
    {
      label: 'sessions',
      tip: 'Total conversation sessions in the selected period.',
      // ... existing fields unchanged
    },
    {
      label: 'total tokens',
      tip: 'Sum of input, cache creation, cache read, and output tokens across all turns.',
      // ... existing fields unchanged
    },
    {
      label: 'cache hit',
      tip: '% of input-side tokens served from cache. Higher means less re-sending repeated context.',
      // ... existing fields unchanged
    },
  ];
  ```

  Then in the `for (const c of cards)` loop, right after `card.className = 'kpi-card'` add:

  ```js
  if (c.tip) card.dataset.tip = c.tip;
  ```

- [ ] **Step 5: Run test suite — all tests should still pass**

  ```bash
  python -m pytest tests/ -v --tb=short 2>&1 | tail -10
  ```

- [ ] **Step 6: Verify KPI card tooltips in browser**

  Hover over "imputed cost", "sessions", "total tokens", "cache hit" KPI cards — tooltip should appear.

- [ ] **Step 7: Commit**

  ```bash
  git add templates/dashboard.html tests/test_dashboard_panels.py
  git commit -m "feat(dashboard): add tooltips to KPI cards; test by_project field shape"
  ```

---

## Task 4: Fluency panel — CSS, HTML, JS, wire-up

**Files:**
- Modify: `templates/dashboard.html`

- [ ] **Step 1: Add Fluency CSS inside the `<style>` block**

  Add after the `.hint` rule (~line 84):

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

- [ ] **Step 2: Add Fluency panel HTML in the overview panel, between takes-section and "by project" heading**

  Find the line `<h2 id="h-project">by project</h2>` (~line 179) and insert before it:

  ```html
  <div id="fluency-panel" style="display:none">
    <h2>fluency <span class="sub" style="font-size:12px;font-weight:400;color:var(--dim);margin-left:8px">token efficiency by project</span></h2>
    <p class="hint">Percentile scores within your projects. Higher = more efficient.</p>
    <div id="fluency-cards" class="fluency-row"></div>
  </div>
  ```

- [ ] **Step 3: Add `computeFluency(byProject, byModel)` pure function**

  Add just before `renderStageTable` (~line 459):

  ```js
  function computeFluency(byProject, byModel) {
    if (!byProject || byProject.length < 2) return null;

    // Global Model Fit: opus token share across all models
    const totalModelTokens = (byModel || []).reduce((s, r) => s + (r.total_tokens || 0), 0);
    const opusTokens = (byModel || [])
      .filter(r => (r.model || '').toLowerCase().includes('opus'))
      .reduce((s, r) => s + (r.total_tokens || 0), 0);
    const globalModelFitRaw = totalModelTokens > 0 ? 1 - (opusTokens / totalModelTokens) : 0.5;

    // Raw scores per project
    const projects = byProject.map(r => {
      const inp = r.input_tokens || 0;
      const cc  = r.cache_creation_tokens || 0;
      const cr  = r.cache_read_tokens || 0;
      const inputSide = inp + cc + cr;
      const cacheHygiene = inputSide > 0 ? cr / inputSide : 0;
      const cachePayback = cc > 0 ? Math.min(cr / cc, 1) : (cr > 0 ? 1 : 0);
      const turns = r.turns || 1;
      const cost = r.cost?.total_usd ?? r.cost_subscription ?? 0;
      const costPerTurn = cost / turns;
      return {
        key: r.project_name || r.display_name || r.project_path,
        raw: { cacheHygiene, cachePayback, modelFit: globalModelFitRaw, costEconomy: costPerTurn },
        r,
      };
    });

    // Percentile rank each axis (0 = worst, 100 = best)
    function percentileRank(items, key, higherIsBetter) {
      const vals = items.map(p => p.raw[key]);
      const sorted = [...vals].sort((a, b) => a - b);
      return items.map(p => {
        const rank = sorted.indexOf(p.raw[key]);
        const pct = Math.round((rank / (sorted.length - 1)) * 100);
        return higherIsBetter ? pct : 100 - pct;
      });
    }

    const hygieneScores  = percentileRank(projects, 'cacheHygiene',  true);
    const paybackScores  = percentileRank(projects, 'cachePayback',  true);
    const modelScores    = percentileRank(projects, 'modelFit',      true);
    const economyScores  = percentileRank(projects, 'costEconomy',   false); // lower cost = better

    return projects.map((p, i) => {
      const axes = [
        { label: 'Cache Hygiene', score: hygieneScores[i],
          tip: '% of input-side tokens served from cache. High = you reuse context well instead of re-sending it fresh.' },
        { label: 'Cache Payback', score: paybackScores[i],
          tip: 'Ratio of cache reads to cache writes. High = your cached prompts got reused many times; low = cache was written but rarely read back.' },
        { label: 'Model Fit (global)', score: modelScores[i],
          tip: 'How much of your token spend used lighter models (Sonnet/Haiku) vs Opus. Scored globally across all projects in v1.' },
        { label: 'Cost Economy', score: economyScores[i],
          tip: 'Your cost per turn relative to your other projects. High = efficient spend per interaction.' },
      ];
      const composite = Math.round(axes.reduce((s, a) => s + a.score, 0) / axes.length);
      return { key: p.key, name: p.key, axes, composite, r: p.r };
    });
  }
  ```

- [ ] **Step 4: Add `renderFluencyPanel(byProject, byModel)` function**

  Add immediately after `computeFluency`:

  ```js
  function renderFluencyPanel(byProject, byModel) {
    const panel = $('#fluency-panel');
    const container = $('#fluency-cards');
    clearKids(container);
    const scored = computeFluency(byProject, byModel);
    if (!scored) { panel.style.display = 'none'; return; }
    panel.style.display = '';

    function scoreCls(s) { return s >= 70 ? 'ok' : s >= 40 ? 'warn' : 'red'; }
    const shortName = n => !n ? '(unknown)' : n.length > 22 ? n.slice(0, 20) + '…' : n;

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

- [ ] **Step 5: Wire `renderFluencyPanel` into the `load()` function**

  Find the block around line 1188–1192:
  ```js
  renderStageTable(d.by_stage);
  renderProjectTable(d.by_project, priorData ? priorData.by_project : null);
  renderModelTable(d.by_model);
  ```

  Add one line after `renderModelTable`:
  ```js
  renderFluencyPanel(d.by_project || [], d.by_model || []);
  ```

- [ ] **Step 6: Run test suite — all tests must pass**

  ```bash
  python -m pytest tests/ -v --tb=short 2>&1 | tail -15
  ```

  Expected: all tests pass. No backend was changed so no regressions expected.

- [ ] **Step 7: Verify Fluency panel in browser end-to-end**

  Open `http://localhost:7777`. Confirm:
  - Fluency panel appears between the insight callouts and the "by project" table
  - Cards show composite score badge colored green/yellow/red
  - Each card has 4 axis bars with correct colors
  - Hovering any axis row or the badge shows a tooltip
  - If fewer than 2 projects exist in the current time range, the panel is hidden

- [ ] **Step 8: Commit**

  ```bash
  git add templates/dashboard.html
  git commit -m "feat(dashboard): add Fluency efficiency panel with 4-axis percentile scoring"
  ```

---

## Self-Review Checklist

- [x] **Spec coverage:** Tooltip CSS/mechanism ✓, KPI card tips ✓, cost mode button tips ✓, all table `<th>` tips ✓, Fluency panel HTML/CSS/JS ✓, 4 axes with formulas ✓, color thresholds ✓, hidden < 2 projects ✓, axis tips ✓, composite badge tip ✓
- [x] **Placeholders:** None — all code is complete in each step
- [x] **Type consistency:** `computeFluency` returns `{key, name, axes, composite, r}[]`; `renderFluencyPanel` consumes that shape; `scoreCls` used consistently in both badge and bar fills; `clearKids` and `mkEl` are existing helpers already used throughout the file
- [x] **`mkEl` usage:** existing helper signature is `mkEl(tag, text, cls)` — used correctly throughout
