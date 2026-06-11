# First-Column Tooltips Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add hover tooltips to the first column of the "by project", "by fluency", "by model", and "by SDLC stage" (incl. project drill-down) dashboard tables, explaining what each row represents.

**Architecture:** Backend (`claude_usage/_view.py`) computes a per-project `description` (from `projects.json` notes, falling back to the project's README) and adds it to each `by_project` row. The dashboard's existing `[data-tip]` / `#tt` floating-tooltip mechanism is extended to table cells via a new `tip` field on `mkRow` cell descriptors, then wired into the project, fluency, model, and stage table renderers.

**Tech Stack:** Python (FastAPI backend, sqlite), vanilla JS dashboard (`templates/dashboard.html`), pytest.

**Spec:** `docs/superpowers/specs/2026-06-11-first-column-tooltips-design.md`

---

### Task 1: `_readme_description` helper

**Files:**
- Modify: `claude_usage/_view.py`
- Test: `tests/test_project_description.py` (new file)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_project_description.py`:

```python
from claude_usage._view import _project_description, _readme_description


def test_readme_description_skips_heading_and_badges(tmp_path):
    (tmp_path / "README.md").write_text(
        "# My Project\n"
        "\n"
        "[![CI](https://example.com/badge.svg)](https://example.com)\n"
        "\n"
        "A tool that tracks token usage and cost across Claude Code sessions.\n"
        "\n"
        "## Installation\n"
    )
    assert _readme_description(str(tmp_path)) == (
        "A tool that tracks token usage and cost across Claude Code sessions."
    )


def test_readme_description_returns_none_without_readme(tmp_path):
    assert _readme_description(str(tmp_path)) is None


def test_readme_description_strips_markdown_links_and_bold(tmp_path):
    (tmp_path / "README.md").write_text(
        "# Title\n\n**Bold start** and a [link](https://example.com) inside text.\n"
    )
    assert _readme_description(str(tmp_path)) == (
        "Bold start and a link inside text."
    )


def test_readme_description_truncates_long_lines(tmp_path):
    long_line = "x" * 250
    (tmp_path / "README.md").write_text(f"# Title\n\n{long_line}\n")
    result = _readme_description(str(tmp_path))
    assert len(result) == 198  # 197 chars + "…"
    assert result.endswith("…")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_project_description.py -v`
Expected: FAIL with `ImportError: cannot import name '_readme_description'` (and `_project_description`, used by Task 2's tests once added — for now only the `_readme_description` tests run and fail on import).

- [ ] **Step 3: Add imports and the helper to `_view.py`**

In `claude_usage/_view.py`, change the imports at the top of the file from:

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import db as dbmod
from . import pricing as pricing_mod
from . import projects as projects_mod
```

to:

```python
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import db as dbmod
from . import pricing as pricing_mod
from . import projects as projects_mod
```

Then, immediately after the `_project_label` function (after its closing `return path + " (path)"` line, before the `_SYSTEM_TEMP_PREFIXES` constant), add:

```python
_README_NAMES = ("README.md", "Readme.md", "readme.md")


def _readme_description(root_path: str) -> str | None:
    """First non-heading, non-badge line of the project's README, truncated to ~200 chars."""
    if not root_path:
        return None
    root = Path(root_path)
    for name in _README_NAMES:
        f = root / name
        if not f.exists():
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None
        for line in text.splitlines()[:60]:
            line = line.strip()
            if not line or line.startswith(("#", "[![", "![", "<")):
                continue
            line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
            line = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", line)
            return line[:197] + "…" if len(line) > 200 else line
        return None
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_project_description.py -v`
Expected: the 4 tests above PASS (the file also has no `_project_description` tests yet, so nothing else runs).

- [ ] **Step 5: Commit**

```bash
git add claude_usage/_view.py tests/test_project_description.py
git commit -m "feat(view): add _readme_description helper for project tooltips"
```

---

### Task 2: `_project_description` helper

**Files:**
- Modify: `claude_usage/_view.py`
- Test: `tests/test_project_description.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_project_description.py`:

```python
from claude_usage import projects as projects_mod


def test_project_description_prefers_notes(tmp_path):
    registry = {
        "alpha": projects_mod.Project(name="alpha", root_path=str(tmp_path), notes="Hand-written description"),
    }
    assert _project_description({"project_name": "alpha"}, registry) == "Hand-written description"


def test_project_description_falls_back_to_readme(tmp_path):
    (tmp_path / "README.md").write_text("# Alpha\n\nDoes alpha things.\n")
    registry = {
        "alpha": projects_mod.Project(name="alpha", root_path=str(tmp_path), notes=""),
    }
    assert _project_description({"project_name": "alpha"}, registry) == "Does alpha things."


def test_project_description_none_for_unregistered_or_path_rows():
    registry = {}
    assert _project_description({"project_path": "/some/path"}, registry) is None
    assert _project_description({"project_name": "unknown"}, registry) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_project_description.py -v`
Expected: the 3 new tests FAIL with `ImportError: cannot import name '_project_description'` (the Task 1 tests still pass once import is fixed in Step 3 — see note: the import error will fail the whole module collection, so all 7 tests will show as errors until Step 3 is done).

- [ ] **Step 3: Add the helper to `_view.py`**

Immediately after the `_readme_description` function added in Task 1, add:

```python
def _project_description(r: dict, registry: dict) -> str | None:
    """projects.json `notes` (if non-empty) else README description, else None."""
    name = r.get("project_name")
    if not name:
        return None
    project = registry.get(name)
    if not project:
        return None
    if project.notes and project.notes.strip():
        return project.notes.strip()
    return _readme_description(project.root_path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_project_description.py -v`
Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add claude_usage/_view.py tests/test_project_description.py
git commit -m "feat(view): add _project_description helper for project tooltips"
```

---

### Task 3: Wire `description` into `build()`'s `by_project` rows

**Files:**
- Modify: `claude_usage/_view.py`
- Test: `tests/test_project_description.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_project_description.py`:

```python
import sqlite3

from claude_usage._view import build


def _insert_turn(db_path, session_id, project_name, ts, model):
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT OR IGNORE INTO sessions(session_id, project_name, started_at) VALUES (?,?,?)",
        (session_id, project_name, ts),
    )
    conn.execute(
        """INSERT INTO turns(session_id, ts, model, input_tokens, output_tokens,
             cache_creation_tokens, cache_read_tokens)
           VALUES (?,?,?,?,?,?,?)""",
        (session_id, ts, model, 1000, 200, 800, 3000),
    )
    conn.commit()
    conn.close()


def test_build_by_project_includes_description(db, tmp_path, monkeypatch):
    monkeypatch.setattr(projects_mod, "PROJECTS_PATH", tmp_path / "projects.json")
    projects_mod.init_project("alpha", tmp_path / "alpha-root", notes="Test description")

    _insert_turn(db, "s1", "alpha", "2026-06-01T10:00:00", "claude-sonnet-4-6")

    result = build(project=None, since="all", kind=None)
    rows = [r for r in result["by_project"] if r.get("project_name") == "alpha"]
    assert len(rows) == 1
    assert rows[0]["description"] == "Test description"


def test_build_by_project_description_none_when_unregistered(db, tmp_path, monkeypatch):
    monkeypatch.setattr(projects_mod, "PROJECTS_PATH", tmp_path / "projects.json")

    _insert_turn(db, "s2", "unregistered-proj", "2026-06-01T10:00:00", "claude-sonnet-4-6")

    result = build(project=None, since="all", kind=None)
    rows = [r for r in result["by_project"] if r.get("project_name") == "unregistered-proj"]
    assert len(rows) == 1
    assert rows[0]["description"] is None
```

This file already uses the `db` fixture from `tests/conftest.py`, which sets `CLAUDE_USAGE_DB` to a temp sqlite database with the required schema.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_project_description.py -v`
Expected: the 2 new tests FAIL with `KeyError: 'description'`.

- [ ] **Step 3: Wire the helper into `build()`**

In `claude_usage/_view.py`, find the `by_project` loop:

```python
    by_project = []
    if not project:
        by_project = dbmod.totals_by_project(since=since_dt, kind=kind, until=until_dt)
        for r in by_project[:30]:
            lookup_key = r.get("project_name") or r.get("project_path", "")
            per_model = dbmod.turns_by_model(project=lookup_key, since=since_dt, until=until_dt)
            all_costs = pricing_mod.total_cost_all_modes(per_model, prices)
            r["cost"] = pricing_mod.cost_dict(all_costs["subscription"])
            r["cost_api"] = round(all_costs["api"].total_usd, 4)
            r["cost_conservative"] = round(all_costs["conservative"].total_usd, 4)
            r["cost_subscription"] = round(all_costs["subscription"].total_usd, 4)
            for k in ("input_tokens", "cache_creation_tokens", "cache_read_tokens", "output_tokens"):
                r[k + "_h"] = _fmt(r[k])
            r["total_tokens"] = _total_tokens(r)
            r["total_tokens_h"] = _fmt(r["total_tokens"])
            r["pct_of_total"] = (100.0 * r["total_tokens"] / grand_total) if grand_total else 0.0
            r["cache_hit_rate"] = _cache_hit_rate(r)
            r["label"] = _project_label(r)
        by_project = _collapse_project_rows(by_project[:30], grand_total)
```

Replace it with:

```python
    by_project = []
    if not project:
        by_project = dbmod.totals_by_project(since=since_dt, kind=kind, until=until_dt)
        registry = projects_mod.load_all()
        for r in by_project[:30]:
            lookup_key = r.get("project_name") or r.get("project_path", "")
            per_model = dbmod.turns_by_model(project=lookup_key, since=since_dt, until=until_dt)
            all_costs = pricing_mod.total_cost_all_modes(per_model, prices)
            r["cost"] = pricing_mod.cost_dict(all_costs["subscription"])
            r["cost_api"] = round(all_costs["api"].total_usd, 4)
            r["cost_conservative"] = round(all_costs["conservative"].total_usd, 4)
            r["cost_subscription"] = round(all_costs["subscription"].total_usd, 4)
            for k in ("input_tokens", "cache_creation_tokens", "cache_read_tokens", "output_tokens"):
                r[k + "_h"] = _fmt(r[k])
            r["total_tokens"] = _total_tokens(r)
            r["total_tokens_h"] = _fmt(r["total_tokens"])
            r["pct_of_total"] = (100.0 * r["total_tokens"] / grand_total) if grand_total else 0.0
            r["cache_hit_rate"] = _cache_hit_rate(r)
            r["label"] = _project_label(r)
            r["description"] = _project_description(r, registry)
        by_project = _collapse_project_rows(by_project[:30], grand_total)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_project_description.py -v`
Expected: all 9 tests PASS.

- [ ] **Step 5: Run the full test suite**

Run: `python -m pytest -q`
Expected: all tests PASS (no regressions in other `by_project` consumers).

- [ ] **Step 6: Commit**

```bash
git add claude_usage/_view.py tests/test_project_description.py
git commit -m "feat(view): include project description in by_project rows"
```

---

### Task 4: `mkRow` tip support

**Files:**
- Modify: `templates/dashboard.html`

- [ ] **Step 1: Add `tip` handling to `mkRow`**

Find:

```js
function mkRow(cells, rowCls) {
  const tr = document.createElement('tr');
  if (rowCls) tr.className = rowCls;
  for (const c of cells) {
    const td = document.createElement('td');
    if (c && typeof c === 'object') {
      td.textContent = String(c.text ?? '');
      if (c.cls) td.className = c.cls;
      if (c.title) td.title = c.title;
      if (c.costApi != null) {
```

Replace with:

```js
function mkRow(cells, rowCls) {
  const tr = document.createElement('tr');
  if (rowCls) tr.className = rowCls;
  for (const c of cells) {
    const td = document.createElement('td');
    if (c && typeof c === 'object') {
      td.textContent = String(c.text ?? '');
      if (c.cls) td.className = c.cls;
      if (c.title) td.title = c.title;
      if (c.tip) td.dataset.tip = c.tip;
      if (c.costApi != null) {
```

- [ ] **Step 2: Manual smoke check**

This is a no-op change until cells start passing `tip` (Tasks 5-8), so there's nothing to observe yet. Just confirm the file still has valid syntax:

Run: `node --check templates/dashboard.html 2>&1 | head -5 || true`

(This will report a parse error pointing at the `<` of the first HTML tag, which is expected since this is an HTML file, not pure JS — the goal is just to confirm `node` doesn't choke earlier than that on the `<script>` body. If unavailable, skip this step; Task 9's browser check is the real verification.)

- [ ] **Step 3: Commit**

```bash
git add templates/dashboard.html
git commit -m "feat(dashboard): support tip field on table cells"
```

---

### Task 5: Project table tooltip

**Files:**
- Modify: `templates/dashboard.html`

- [ ] **Step 1: Update `renderProjectTable`**

Find (inside `renderProjectTable`):

```js
    const tooltip = isSysOps
      ? 'Plugin & automation sessions (memory consolidation etc.) — included in grand total'
      : (r.project_path || '');
```

Replace with:

```js
    const tooltip = isSysOps
      ? 'Plugin & automation sessions (memory consolidation etc.) — included in grand total'
      : (r.description || r.project_path || '');
```

Then find:

```js
    const tr = mkRow([
      { text: label, title: tooltip },
      r.sessions, r.turns,
```

Replace with:

```js
    const tr = mkRow([
      { text: label, tip: tooltip },
      r.sessions, r.turns,
```

- [ ] **Step 2: Commit**

```bash
git add templates/dashboard.html
git commit -m "feat(dashboard): show project description tooltip in by-project table"
```

---

### Task 6: Fluency table tooltip

**Files:**
- Modify: `templates/dashboard.html`

- [ ] **Step 1: Update `renderFluencyTable`**

Find (inside `renderFluencyTable`):

```js
  for (const p of rows.slice(0, 20)) {
    const cls = fluencyScoreCls(p.composite);
    const tr = mkRow([
      { text: shortName(p.name), title: p.name },
      { text: String(p.composite), cls: 'pct fluency-score ' + cls },
    ]);
```

Replace with:

```js
  for (const p of rows.slice(0, 20)) {
    const cls = fluencyScoreCls(p.composite);
    const tip = p.r.description || (p.name && p.name.length > 22 ? p.name : '');
    const tr = mkRow([
      { text: shortName(p.name), tip },
      { text: String(p.composite), cls: 'pct fluency-score ' + cls },
    ]);
```

- [ ] **Step 2: Commit**

```bash
git add templates/dashboard.html
git commit -m "feat(dashboard): show project description tooltip in fluency table"
```

---

### Task 7: Model table tooltip

**Files:**
- Modify: `templates/dashboard.html`

- [ ] **Step 1: Add `modelTip` helper**

Find:

```js
function fmtCacheHit(rate) {
  if (rate == null) return { text: '—', cls: 'pct' };
  const pct = (rate * 100).toFixed(0) + '%';
  const cls = rate >= 0.85 ? 'pct ok' : rate >= 0.5 ? 'pct warn' : 'pct red';
  return { text: pct, cls };
}
```

Replace with:

```js
function fmtCacheHit(rate) {
  if (rate == null) return { text: '—', cls: 'pct' };
  const pct = (rate * 100).toFixed(0) + '%';
  const cls = rate >= 0.85 ? 'pct ok' : rate >= 0.5 ? 'pct warn' : 'pct red';
  return { text: pct, cls };
}

function modelTip(model) {
  const m = (model || '').toLowerCase();
  if (m.includes('opus'))   return "Opus — Anthropic's most capable model. Best for complex reasoning, architecture, and high-stakes work. Highest cost per token.";
  if (m.includes('sonnet')) return "Sonnet — balanced model for everyday coding and analysis. Strong capability at a fraction of Opus's cost.";
  if (m.includes('haiku'))  return "Haiku — fastest, cheapest model. Best for simple, high-volume, or latency-sensitive tasks.";
  return 'Claude model used for this work.';
}
```

- [ ] **Step 2: Update `renderModelTable`**

Find (inside `renderModelTable`):

```js
  for (const r of rows) {
    tbody.appendChild(mkRow([
      r.model,
      fmt(r.total_tokens),
```

Replace with:

```js
  for (const r of rows) {
    tbody.appendChild(mkRow([
      { text: r.model, tip: modelTip(r.model) },
      fmt(r.total_tokens),
```

- [ ] **Step 3: Commit**

```bash
git add templates/dashboard.html
git commit -m "feat(dashboard): show model tier tooltip in by-model table"
```

---

### Task 8: SDLC stage table tooltips

**Files:**
- Modify: `templates/dashboard.html`

- [ ] **Step 1: Add `STAGE_TIPS` map and `stageTip` helper**

Find the `modelTip` function added in Task 7 and add immediately after it:

```js
const STAGE_TIPS = {
  requirements: 'Defining what to build — specs, user stories, requirements docs, roadmaps.',
  design: 'Architecture and design work — system design, data models, diagrams, tradeoffs.',
  test: 'Writing or running tests — unit, integration, e2e, TDD.',
  deploy: 'Shipping and operating — CI/CD, releases, deployments, infrastructure changes.',
  explore: 'Research and Q&A — understanding how something works, without building yet.',
  impl: 'Building and fixing — implementing features, fixing bugs, refactoring code.',
  adhoc: "Catch-all — sessions that didn't clearly match another stage.",
  _tracker_overhead_: "Internal usage-analytics tooling overhead (this dashboard's own sessions).",
};
function stageTip(stage) {
  return STAGE_TIPS[stage] || "SDLC stage classified from the session's first message.";
}
```

- [ ] **Step 2: Update `renderStageTable`**

Find (inside `renderStageTable`):

```js
    const tr = mkRow([
      r.stage, r.sessions, r.turns,
      fmt(totalTokens),
      { text: '$' + (r.cost_subscription ?? r.cost?.total_usd ?? 0).toFixed(2),
        costApi: r.cost_api ?? r.cost?.total_usd ?? 0,
        costConservative: r.cost_conservative ?? r.cost?.total_usd ?? 0,
        costSubscription: r.cost_subscription ?? r.cost?.total_usd ?? 0 },
      fmtCacheHit(r.cache_hit_rate),
      { text: (r.pct_of_total ?? 0).toFixed(1) + '%', cls: 'pct' },
    ], rowCls);
    tr.addEventListener('click', () => toggleBreakdown(tr, 'stage', r.stage, 7));
```

Replace with:

```js
    const tr = mkRow([
      { text: r.stage, tip: stageTip(r.stage) }, r.sessions, r.turns,
      fmt(totalTokens),
      { text: '$' + (r.cost_subscription ?? r.cost?.total_usd ?? 0).toFixed(2),
        costApi: r.cost_api ?? r.cost?.total_usd ?? 0,
        costConservative: r.cost_conservative ?? r.cost?.total_usd ?? 0,
        costSubscription: r.cost_subscription ?? r.cost?.total_usd ?? 0 },
      fmtCacheHit(r.cache_hit_rate),
      { text: (r.pct_of_total ?? 0).toFixed(1) + '%', cls: 'pct' },
    ], rowCls);
    tr.addEventListener('click', () => toggleBreakdown(tr, 'stage', r.stage, 7));
```

- [ ] **Step 3: Update `renderProjectStageTable`**

Find (inside `renderProjectStageTable`):

```js
    const tr = mkRow([
      r.stage, r.sessions, r.turns,
      fmt(totalTokens),
      { text: '$' + (r.cost_subscription ?? r.cost?.total_usd ?? 0).toFixed(2),
        costApi: r.cost_api ?? r.cost?.total_usd ?? 0,
        costConservative: r.cost_conservative ?? r.cost?.total_usd ?? 0,
        costSubscription: r.cost_subscription ?? r.cost?.total_usd ?? 0 },
      fmtCacheHit(r.cache_hit_rate),
      { text: (r.pct_of_total ?? 0).toFixed(1) + '%', cls: 'pct' },
    ], rowCls);
    tr.addEventListener('click', () => drillIntoStage(r.stage));
```

Replace with:

```js
    const tr = mkRow([
      { text: r.stage, tip: stageTip(r.stage) }, r.sessions, r.turns,
      fmt(totalTokens),
      { text: '$' + (r.cost_subscription ?? r.cost?.total_usd ?? 0).toFixed(2),
        costApi: r.cost_api ?? r.cost?.total_usd ?? 0,
        costConservative: r.cost_conservative ?? r.cost?.total_usd ?? 0,
        costSubscription: r.cost_subscription ?? r.cost?.total_usd ?? 0 },
      fmtCacheHit(r.cache_hit_rate),
      { text: (r.pct_of_total ?? 0).toFixed(1) + '%', cls: 'pct' },
    ], rowCls);
    tr.addEventListener('click', () => drillIntoStage(r.stage));
```

- [ ] **Step 4: Commit**

```bash
git add templates/dashboard.html
git commit -m "feat(dashboard): show SDLC stage description tooltips"
```

---

### Task 9: Manual verification in the browser

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend test suite**

Run: `python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 2: Start the dashboard server**

Run: `cu serve` (defaults to `--host 127.0.0.1 --port 7777`, defined in `claude_usage/cli.py`) and open `http://127.0.0.1:7777/`.

- [ ] **Step 3: Verify each tooltip in the browser**

Using the preview tools:
- Hover a project name in "by project" → tooltip shows the description (e.g. claude-usage-analytics shows "Token & cost tracker / analytics dashboard for Claude Code sessions" from its registered `notes`; a project without notes shows its README's first description line, or the path if neither exists).
- Hover a project name in "by fluency" → same description tooltip (or full name if truncated and no description).
- Hover a model name in "by model" → tooltip describes that model tier (Opus/Sonnet/Haiku).
- Hover a stage name in "by SDLC stage" → tooltip describes that SDLC stage (e.g. "impl" → "Building and fixing — …").
- Drill into a project to reach the project-level stage table → hover a stage name there too, same tooltip.

- [ ] **Step 4: Take a screenshot for the record**

Use `preview_screenshot` after hovering one cell in each of the 4 tables (or one combined screenshot per table) to confirm the floating tooltip renders correctly (text wraps within the `260px` max-width, doesn't overflow the viewport).

No commit for this task — it's verification only. If any issue is found, fix it in the relevant task's file and amend that task's commit... actually, per repo convention, create a new commit for the fix rather than amending.
