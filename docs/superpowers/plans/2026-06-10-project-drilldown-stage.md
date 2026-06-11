# Project Drill-Down: Stage → User/Subagent → Sessions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Insert a per-project SDLC-stage breakdown between the project row and the user/subagent kind panel, and fix the long-standing bug where the "subagent sessions" card is always empty.

**Architecture:** Backend: rewrite `db.sessions_for_project` to return root sessions plus their subagent children (each tagged with an inherited "effective stage"), and add an optional `stage` filter to it and to `/api/sessions`. Frontend: add a new `#panel-stage` (reusing the `#t-stage` table layout, scoped to one project), rewrite `drillIntoProject` to show it (falling back to today's behavior when a project has no stage data, e.g. `__system_ops__`), add `drillIntoStage`, and generalize `renderKindPanel`/`drillIntoKind`/`showKindPanel` to work with a variable-length breadcrumb.

**Tech Stack:** Python/FastAPI/SQLite backend (`claude_usage/db.py`, `claude_usage/serve.py`), pytest for backend tests; vanilla JS single-file template (`templates/dashboard.html`), no build step or JS test runner — verification is via `node --check` for syntax and the Claude Preview tools for rendering.

---

## Reference: spec

See [docs/superpowers/specs/2026-06-10-project-drilldown-stage-design.md](../specs/2026-06-10-project-drilldown-stage-design.md) for the full design rationale.

## Reference: JS syntax check helper

Several steps verify JS syntax by extracting the inline `<script>` block and running `node --check` on it. Use this command (the script is delimited by lines that are exactly `<script>` and `</script>`):

```bash
sed -n '/^<script>$/,/^<\/script>$/p' templates/dashboard.html | sed '1d;$d' > /tmp/dashboard.js && node --check /tmp/dashboard.js && echo OK
```

Expected output: `OK`

---

### Task 1: Rewrite `db.sessions_for_project` to include subagent children with an effective stage

**Files:**
- Modify: `claude_usage/db.py:196-234`
- Test: `tests/test_sessions_for_project.py` (new file)

- [ ] **Step 1: Write failing tests**

Create `tests/test_sessions_for_project.py`:

```python
"""Tests for sessions_for_project: root sessions plus their subagent children,
each tagged with an effective SDLC stage (own stage for roots, parent's for children).
"""
import sqlite3 as _sql
from claude_usage.db import parse_until, sessions_for_project


def _seed(db, sessions, stages=None, turns=None):
    """Insert sessions, optional stage rows, optional turn rows.

    sessions: list of dicts with keys: session_id, project_name (opt),
              parent_session_id (opt), started_at (opt)
    stages:   list of (session_id, stage)
    turns:    list of (session_id, input_tokens)
    """
    conn = _sql.connect(str(db))
    for s in sessions:
        conn.execute(
            "INSERT INTO sessions(session_id, project_name, parent_session_id, started_at) "
            "VALUES (:session_id, :project_name, :parent_session_id, :started_at)",
            {
                "session_id": s["session_id"],
                "project_name": s.get("project_name", "myproj"),
                "parent_session_id": s.get("parent_session_id"),
                "started_at": s.get("started_at", "2026-06-01T00:00:00"),
            },
        )
    for session_id, stage in (stages or []):
        conn.execute(
            "INSERT INTO session_stage(session_id, stage, source) VALUES (?,?,?)",
            (session_id, stage, "classifier"),
        )
    for session_id, tokens in (turns or []):
        conn.execute(
            "INSERT INTO turns(session_id, input_tokens) VALUES (?,?)",
            (session_id, tokens),
        )
    conn.commit()
    conn.close()


def test_includes_subagent_children(db):
    _seed(db, [
        {"session_id": "root1"},
        {"session_id": "root1::agent-abc123", "parent_session_id": "root1"},
    ], stages=[("root1", "build")])
    rows = sessions_for_project("myproj")
    ids = {r["session_id"] for r in rows}
    assert ids == {"root1", "root1::agent-abc123"}


def test_child_inherits_parent_stage(db):
    _seed(db, [
        {"session_id": "root1"},
        {"session_id": "root1::agent-abc123", "parent_session_id": "root1"},
    ], stages=[("root1", "build")])
    rows = {r["session_id"]: r for r in sessions_for_project("myproj")}
    assert rows["root1"]["stage"] == "build"
    assert rows["root1::agent-abc123"]["stage"] == "build"


def test_unclassified_root_gets_unclassified_stage(db):
    _seed(db, [{"session_id": "root1"}])
    rows = sessions_for_project("myproj")
    assert rows[0]["stage"] == "unclassified"


def test_stage_filter_includes_matching_children(db):
    _seed(db, [
        {"session_id": "root1"},
        {"session_id": "root1::agent-abc123", "parent_session_id": "root1"},
        {"session_id": "root2"},
    ], stages=[("root1", "build"), ("root2", "fix")])
    rows = sessions_for_project("myproj", stage="build")
    ids = {r["session_id"] for r in rows}
    assert ids == {"root1", "root1::agent-abc123"}


def test_stage_filter_unclassified(db):
    _seed(db, [
        {"session_id": "root1"},
        {"session_id": "root2"},
    ], stages=[("root2", "build")])
    rows = sessions_for_project("myproj", stage="unclassified")
    ids = {r["session_id"] for r in rows}
    assert ids == {"root1"}


def test_child_tokens_counted_on_own_row(db):
    _seed(
        db,
        sessions=[
            {"session_id": "root1"},
            {"session_id": "root1::agent-abc123", "parent_session_id": "root1"},
        ],
        stages=[("root1", "build")],
        turns=[("root1", 100), ("root1::agent-abc123", 400)],
    )
    rows = {r["session_id"]: r for r in sessions_for_project("myproj")}
    assert rows["root1"]["input_tokens"] == 100
    assert rows["root1::agent-abc123"]["input_tokens"] == 400


def test_until_excludes_later_sessions(db):
    _seed(db, [
        {"session_id": "sfp1", "started_at": "2026-05-20T10:00:00"},
        {"session_id": "sfp2", "started_at": "2026-05-25T10:00:00"},
    ])
    rows = sessions_for_project("myproj", until=parse_until("2026-05-21"))
    ids = {r["session_id"] for r in rows}
    assert ids == {"sfp1"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sessions_for_project.py -v`
Expected: FAIL — `sessions_for_project()` doesn't accept a `stage` kwarg yet, and the current query excludes subagent children entirely (so `test_includes_subagent_children`, `test_child_inherits_parent_stage`, `test_stage_filter_includes_matching_children`, `test_child_tokens_counted_on_own_row` fail; `test_unclassified_root_gets_unclassified_stage` and `test_stage_filter_unclassified` fail because `stage` is `None`/`TypeError`).

- [ ] **Step 3: Rewrite `sessions_for_project`**

Find this exact block in `claude_usage/db.py` (lines 196-234):

```python
def sessions_for_project(project: str, since: datetime | None = None, limit: int = 200, until: datetime | None = None) -> list[dict]:
    """Return individual sessions for a named project, newest first."""
    sql = """
        SELECT
          s.session_id,
          s.project_name,
          s.project_path,
          s.started_at,
          s.ended_at,
          s.is_tracker_overhead,
          s.ai_title,
          s.first_user_message,
          s.agent_type,
          s.parent_session_id,
          s.subagent_description,
          ss.stage AS stage,
          COUNT(t.id) AS turns,
          COALESCE(SUM(t.input_tokens), 0) AS input_tokens,
          COALESCE(SUM(t.cache_creation_tokens), 0) AS cache_creation_tokens,
          COALESCE(SUM(t.cache_read_tokens), 0) AS cache_read_tokens,
          COALESCE(SUM(t.output_tokens), 0) AS output_tokens
        FROM sessions s
        LEFT JOIN turns t ON t.session_id = s.session_id
        LEFT JOIN session_stage ss ON ss.session_id = s.session_id
        WHERE (s.project_name = ? OR s.project_path LIKE ? OR s.project_dir LIKE ?)
          AND s.parent_session_id IS NULL
          AND s.session_id NOT LIKE '%::agent-%'
    """
    params: list = [project, f"%{project}%", f"%{project}%"]
    if since:
        sql += " AND s.started_at >= ?"
        params.append(since.isoformat())
    if until:
        sql += " AND s.started_at <= ?"
        params.append(until.isoformat())
    sql += " GROUP BY s.session_id ORDER BY s.started_at DESC LIMIT ?"
    params.append(limit)
    with connect() as c:
        return [dict(r) for r in c.execute(sql, params)]
```

Replace it with:

```python
def sessions_for_project(
    project: str,
    stage: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 200,
) -> list[dict]:
    """Return root sessions for a project plus their subagent children, newest first.

    Each row is tagged with an effective `stage`: a root session's own stage
    (or 'unclassified' if it has none), or its parent's effective stage for a
    subagent child — the same inheritance rule used by totals_by_stage().
    """
    sql = """
        WITH matched_roots AS (
          SELECT s.session_id AS session_id,
                 COALESCE(ss.stage, 'unclassified') AS eff_stage
          FROM sessions s
          LEFT JOIN session_stage ss ON ss.session_id = s.session_id
          WHERE (s.project_name = ? OR s.project_path LIKE ? OR s.project_dir LIKE ?)
            AND s.parent_session_id IS NULL
            AND s.session_id NOT LIKE '%::agent-%'
        )
        SELECT
          s.session_id,
          s.project_name,
          s.project_path,
          s.started_at,
          s.ended_at,
          s.is_tracker_overhead,
          s.ai_title,
          s.first_user_message,
          s.agent_type,
          s.parent_session_id,
          s.subagent_description,
          mr.eff_stage AS stage,
          COUNT(t.id) AS turns,
          COALESCE(SUM(t.input_tokens), 0) AS input_tokens,
          COALESCE(SUM(t.cache_creation_tokens), 0) AS cache_creation_tokens,
          COALESCE(SUM(t.cache_read_tokens), 0) AS cache_read_tokens,
          COALESCE(SUM(t.output_tokens), 0) AS output_tokens
        FROM sessions s
        JOIN matched_roots mr
          ON s.session_id = mr.session_id OR s.parent_session_id = mr.session_id
        LEFT JOIN turns t ON t.session_id = s.session_id
        WHERE 1=1
    """
    params: list = [project, f"%{project}%", f"%{project}%"]
    if stage:
        sql += " AND mr.eff_stage = ?"
        params.append(stage)
    if since:
        sql += " AND s.started_at >= ?"
        params.append(since.isoformat())
    if until:
        sql += " AND s.started_at <= ?"
        params.append(until.isoformat())
    sql += " GROUP BY s.session_id ORDER BY s.started_at DESC LIMIT ?"
    params.append(limit)
    with connect() as c:
        return [dict(r) for r in c.execute(sql, params)]
```

- [ ] **Step 4: Run the new tests and the existing `until` regression test**

Run: `pytest tests/test_sessions_for_project.py tests/test_db_until.py -v`
Expected: all PASS, including the pre-existing `test_sessions_for_project_until_excludes_later` in `tests/test_db_until.py`.

- [ ] **Step 5: Commit**

```bash
git add claude_usage/db.py tests/test_sessions_for_project.py
git commit -m "feat(db): sessions_for_project returns subagent children with inherited stage"
```

---

### Task 2: Add `stage` query param to `/api/sessions`

**Files:**
- Modify: `claude_usage/serve.py:122-134`
- Test: `tests/test_api_until.py`

- [ ] **Step 1: Write a failing test**

Add to `tests/test_api_until.py` (after `test_sessions_until_filters`):

```python
def test_sessions_stage_param_filters(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    _seed(db_path)
    conn = _sqlite3.connect(str(db_path))
    conn.execute("INSERT INTO session_stage(session_id, stage, source) VALUES ('a1','build','classifier')")
    conn.execute("INSERT INTO session_stage(session_id, stage, source) VALUES ('a2','fix','classifier')")
    conn.commit()
    conn.close()
    client = _get_client(monkeypatch, db_path)
    resp = client.get("/api/sessions?project=alpha&stage=build")
    assert resp.status_code == 200
    ids = [s["session_id"] for s in resp.json()["sessions"]]
    assert ids == ["a1"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_until.py::test_sessions_stage_param_filters -v`
Expected: FAIL — `/api/sessions` ignores an unknown `stage` query param today (FastAPI drops unrecognized query params silently), so both `a1` and `a2` are returned.

- [ ] **Step 3: Add the `stage` param**

Find this exact block in `claude_usage/serve.py` (lines 122-134):

```python
    @app.get("/api/sessions")
    def api_sessions(
        project: str = Query(...),
        since: str = Query(default="all"),
        until: str | None = Query(default=None),
    ) -> JSONResponse:
        since_dt = dbmod.parse_since(since)
        until_dt = dbmod.parse_until(until)
        prices = pricing_mod.load_prices()
        if project == "__system_ops__":
            rows = dbmod.sessions_for_system_ops(since=since_dt, until=until_dt)
        else:
            rows = dbmod.sessions_for_project(project, since=since_dt, until=until_dt)
```

Replace it with:

```python
    @app.get("/api/sessions")
    def api_sessions(
        project: str = Query(...),
        since: str = Query(default="all"),
        until: str | None = Query(default=None),
        stage: str | None = Query(default=None),
    ) -> JSONResponse:
        since_dt = dbmod.parse_since(since)
        until_dt = dbmod.parse_until(until)
        prices = pricing_mod.load_prices()
        if project == "__system_ops__":
            rows = dbmod.sessions_for_system_ops(since=since_dt, until=until_dt)
        else:
            rows = dbmod.sessions_for_project(project, stage=stage, since=since_dt, until=until_dt)
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/test_api_until.py -v`
Expected: all PASS, including `test_sessions_stage_param_filters`.

- [ ] **Step 5: Commit**

```bash
git add claude_usage/serve.py tests/test_api_until.py
git commit -m "feat(api): add optional stage filter to /api/sessions"
```

---

### Task 3: Add `#panel-stage` HTML, `#t-project-stage` table, and column-width CSS

**Files:**
- Modify: `templates/dashboard.html` (CSS column widths, lines 51-53; new panel markup, lines 282-284)

- [ ] **Step 1: Add `#t-project-stage` to the column-width selectors**

Find this exact block:

```css
  #t-project col.c-name, #t-stage col.c-name, #t-agent col.c-name, #t-sessions col.c-name { width: auto; }
  #t-project col.c-num, #t-stage col.c-num, #t-agent col.c-num, #t-sessions col.c-num { width: 78px; }
  #t-project col.c-pct, #t-stage col.c-pct { width: 56px; }
```

Replace it with:

```css
  #t-project col.c-name, #t-stage col.c-name, #t-project-stage col.c-name, #t-agent col.c-name, #t-sessions col.c-name { width: auto; }
  #t-project col.c-num, #t-stage col.c-num, #t-project-stage col.c-num, #t-agent col.c-num, #t-sessions col.c-num { width: 78px; }
  #t-project col.c-pct, #t-stage col.c-pct, #t-project-stage col.c-pct { width: 56px; }
```

- [ ] **Step 2: Insert the new panel between `#panel-overview` and `#panel-kind`**

Find this exact block (lines 282-285):

```html
    </div>

    <!-- Kind selector panel (middle layer) -->
    <div id="panel-kind">
```

Replace it with:

```html
    </div>

    <!-- Project SDLC-stage panel -->
    <div id="panel-stage" style="display:none">
      <h2>by stage</h2>
      <p class="hint">Click a row to see the user/subagent breakdown for that stage.</p>
      <table id="t-project-stage">
        <colgroup>
          <col class="c-name"><col class="c-num"><col class="c-num"><col class="c-num"><col class="c-num"><col class="c-pct"><col class="c-pct">
        </colgroup>
        <thead><tr>
          <th>stage</th>
          <th data-tip="Number of conversation sessions">sess</th>
          <th data-tip="Number of back-and-forth exchanges (user message + assistant response = 1 turn)">turns</th>
          <th data-tip="Total tokens consumed (input + cache creation + cache read + output)">tokens</th>
          <th data-tip="Estimated cost under the selected pricing mode">cost</th>
          <th data-tip="% of input-side tokens served from cache. Green ≥ 85%, yellow ≥ 50%, red < 50%.">cache·hit</th>
          <th data-tip="This stage's share of this project's total tokens">%</th>
        </tr></thead>
        <tbody></tbody>
      </table>
    </div>

    <!-- Kind selector panel (middle layer) -->
    <div id="panel-kind">
```

- [ ] **Step 3: Commit**

```bash
git add templates/dashboard.html
git commit -m "feat(dashboard): add panel-stage markup for per-project SDLC breakdown"
```

---

### Task 4: Add drill-down state vars and `renderProjectStageTable`

**Files:**
- Modify: `templates/dashboard.html` (state vars currently around line 856-858; new function inserted after `renderStageTable`, currently lines 643-663)

- [ ] **Step 1: Add new drill-down state variables**

Find this exact block (currently around line 856-858):

```js
let currentSessions = [];
let currentKindSessions = [];  // sessions for the currently-selected kind
let currentProjectLabel = '';
```

Replace it with:

```js
let currentSessions = [];
let currentKindSessions = [];  // sessions for the currently-selected kind
let currentProjectLabel = '';
let currentProjectKey = '';
let currentStage = null;
let currentKindBreadcrumb = [];
```

- [ ] **Step 2: Add `renderProjectStageTable` after `renderStageTable`**

Find this exact block (currently around lines 660-665):

```js
    tr.addEventListener('click', () => toggleBreakdown(tr, 'stage', r.stage, 7));
    tbody.appendChild(tr);
  }
}

function renderProjectTable(rows, priorRows) {
```

Replace it with:

```js
    tr.addEventListener('click', () => toggleBreakdown(tr, 'stage', r.stage, 7));
    tbody.appendChild(tr);
  }
}

function renderProjectStageTable(rows) {
  const tbody = $('#t-project-stage tbody');
  clearKids(tbody);
  for (const r of rows) {
    const totalTokens = (r.input_tokens || 0) + (r.cache_creation_tokens || 0)
                      + (r.cache_read_tokens || 0) + (r.output_tokens || 0);
    const tr = mkRow([
      r.stage, r.sessions, r.turns,
      fmt(totalTokens),
      { text: '$' + (r.cost_subscription ?? r.cost?.total_usd ?? 0).toFixed(2),
        costApi: r.cost_api ?? r.cost?.total_usd ?? 0,
        costConservative: r.cost_conservative ?? r.cost?.total_usd ?? 0,
        costSubscription: r.cost_subscription ?? r.cost?.total_usd ?? 0 },
      fmtCacheHit(r.cache_hit_rate),
      { text: (r.pct_of_total ?? 0).toFixed(1) + '%', cls: 'pct' },
    ], 'clickable');
    tr.addEventListener('click', () => drillIntoStage(r.stage));
    tbody.appendChild(tr);
  }
  renderCosts(activeCostMode);
}

function renderProjectTable(rows, priorRows) {
```

(`drillIntoStage` is added in Task 6 — the file will not be functionally complete until then, but `node --check` passes now since `drillIntoStage` is referenced only inside a closure, not called at parse time.)

- [ ] **Step 3: Verify JS syntax**

Run the syntax check command from the "Reference" section above.
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add templates/dashboard.html
git commit -m "feat(dashboard): add renderProjectStageTable and drill-down state vars"
```

---

### Task 5: Generalize `renderKindPanel`/`drillIntoKind`/`showKindPanel`/`showOverview` for a variable-length breadcrumb

**Files:**
- Modify: `templates/dashboard.html` (`renderKindPanel`/`drillIntoKind`, currently lines 873-948; `showOverview`/`showKindPanel`, currently lines 1063-1078)

- [ ] **Step 1: Rewrite `renderKindPanel` and `drillIntoKind`**

Find this exact block (currently lines 873-948):

```js
function renderKindPanel(label, allSessions) {
  const user = allSessions.filter(s => !s.parent_session_id);
  const subagent = allSessions.filter(s => !!s.parent_session_id);

  const cards = $('#kind-cards');
  clearKids(cards);

  for (const [kindLabel, kindSessions] of [['user', user], ['subagent', subagent]]) {
    const card = document.createElement('div');
    card.className = 'kind-card' + (kindSessions.length === 0 ? ' kc-disabled' : '');

    const lbl = document.createElement('div');
    lbl.className = 'kc-label';
    lbl.textContent = kindLabel + ' sessions';
    card.appendChild(lbl);

    if (kindSessions.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'kc-empty';
      empty.textContent = 'none';
      card.appendChild(empty);
    } else {
      const st = _sessionStats(kindSessions);
      for (const [statLabel, val, costMeta] of [
        ['sessions', st.count, null],
        ['tokens', fmt(st.tokens), null],
        ['cost', '$' + st.cost.toFixed(3), { api: st.costApi, conservative: st.costConservative, subscription: st.cost }],
        ['cache hit', st.cacheHit.toFixed(1) + '%', null],
      ]) {
        const row = document.createElement('div');
        row.className = 'kc-stat';
        const kEl = document.createElement('span');
        kEl.textContent = statLabel;
        const vEl = document.createElement('span');
        vEl.className = 'v';
        if (costMeta) {
          vEl.dataset.costApi = costMeta.api.toFixed(4);
          vEl.dataset.costConservative = costMeta.conservative.toFixed(4);
          vEl.dataset.costSubscription = costMeta.subscription.toFixed(4);
          vEl.dataset.costPrec = '3';
        }
        vEl.textContent = val;
        row.appendChild(kEl);
        row.appendChild(vEl);
        card.appendChild(row);
      }
      card.addEventListener('click', () => drillIntoKind(kindLabel, kindSessions));
    }
    cards.appendChild(card);
  }

  $('#drill-project-label-kind').textContent = label;
  currentProjectLabel = label;
  renderBreadcrumb([
    { label: '~ overview', onClick: showOverview },
    { label },
  ]);
  $('#panel-overview').style.display = 'none';
  $('#panel-kind').style.display = 'block';
  $('#panel-sessions').style.display = 'none';
  renderCosts(activeCostMode);
}

function drillIntoKind(kindLabel, kindSessions) {
  currentKindSessions = kindSessions;
  const projectLabel = $('#drill-project-label-kind').textContent;
  renderBreadcrumb([
    { label: '~ overview', onClick: showOverview },
    { label: projectLabel, onClick: showKindPanel },
    { label: kindLabel },
  ]);
  if ($('#f-session-search')) $('#f-session-search').value = '';
  $('#panel-kind').style.display = 'none';
  $('#panel-sessions').style.display = 'block';
  renderSessions(kindSessions);
}
```

Replace it with:

```js
function renderKindPanel(breadcrumbSegments, allSessions) {
  const user = allSessions.filter(s => !s.parent_session_id);
  const subagent = allSessions.filter(s => !!s.parent_session_id);

  const cards = $('#kind-cards');
  clearKids(cards);

  for (const [kindLabel, kindSessions] of [['user', user], ['subagent', subagent]]) {
    const card = document.createElement('div');
    card.className = 'kind-card' + (kindSessions.length === 0 ? ' kc-disabled' : '');

    const lbl = document.createElement('div');
    lbl.className = 'kc-label';
    lbl.textContent = kindLabel + ' sessions';
    card.appendChild(lbl);

    if (kindSessions.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'kc-empty';
      empty.textContent = 'none';
      card.appendChild(empty);
    } else {
      const st = _sessionStats(kindSessions);
      for (const [statLabel, val, costMeta] of [
        ['sessions', st.count, null],
        ['tokens', fmt(st.tokens), null],
        ['cost', '$' + st.cost.toFixed(3), { api: st.costApi, conservative: st.costConservative, subscription: st.cost }],
        ['cache hit', st.cacheHit.toFixed(1) + '%', null],
      ]) {
        const row = document.createElement('div');
        row.className = 'kc-stat';
        const kEl = document.createElement('span');
        kEl.textContent = statLabel;
        const vEl = document.createElement('span');
        vEl.className = 'v';
        if (costMeta) {
          vEl.dataset.costApi = costMeta.api.toFixed(4);
          vEl.dataset.costConservative = costMeta.conservative.toFixed(4);
          vEl.dataset.costSubscription = costMeta.subscription.toFixed(4);
          vEl.dataset.costPrec = '3';
        }
        vEl.textContent = val;
        row.appendChild(kEl);
        row.appendChild(vEl);
        card.appendChild(row);
      }
      card.addEventListener('click', () => drillIntoKind(kindLabel, kindSessions));
    }
    cards.appendChild(card);
  }

  currentKindBreadcrumb = breadcrumbSegments;
  renderBreadcrumb(breadcrumbSegments);
  $('#panel-overview').style.display = 'none';
  $('#panel-stage').style.display = 'none';
  $('#panel-kind').style.display = 'block';
  $('#panel-sessions').style.display = 'none';
  renderCosts(activeCostMode);
}

function drillIntoKind(kindLabel, kindSessions) {
  currentKindSessions = kindSessions;
  const prefix = currentKindBreadcrumb.slice(0, -1);
  const last = currentKindBreadcrumb[currentKindBreadcrumb.length - 1];
  renderBreadcrumb([
    ...prefix,
    { label: last.label, onClick: showKindPanel },
    { label: kindLabel },
  ]);
  if ($('#f-session-search')) $('#f-session-search').value = '';
  $('#panel-kind').style.display = 'none';
  $('#panel-sessions').style.display = 'block';
  renderSessions(kindSessions);
}
```

- [ ] **Step 2: Rewrite `showOverview`/`showKindPanel` and add `showStagePanel`**

Find this exact block (currently lines 1063-1078):

```js
function showOverview() {
  renderBreadcrumb([{ label: '~ overview' }]);
  renderAttributionPanel([]);
  $('#panel-sessions').style.display = 'none';
  $('#panel-kind').style.display = 'none';
  $('#panel-overview').style.display = '';
}

function showKindPanel() {
  renderBreadcrumb([
    { label: '~ overview', onClick: showOverview },
    { label: currentProjectLabel },
  ]);
  $('#panel-sessions').style.display = 'none';
  $('#panel-kind').style.display = 'block';
}
```

Replace it with:

```js
function showOverview() {
  renderBreadcrumb([{ label: '~ overview' }]);
  renderAttributionPanel([]);
  $('#panel-sessions').style.display = 'none';
  $('#panel-kind').style.display = 'none';
  $('#panel-stage').style.display = 'none';
  $('#panel-overview').style.display = '';
}

function showKindPanel() {
  renderBreadcrumb(currentKindBreadcrumb);
  $('#panel-sessions').style.display = 'none';
  $('#panel-stage').style.display = 'none';
  $('#panel-kind').style.display = 'block';
}

function showStagePanel() {
  renderBreadcrumb([
    { label: '~ overview', onClick: showOverview },
    { label: currentProjectLabel },
  ]);
  $('#panel-sessions').style.display = 'none';
  $('#panel-kind').style.display = 'none';
  $('#panel-stage').style.display = 'block';
}
```

- [ ] **Step 3: Verify JS syntax**

Run the syntax check command from the "Reference" section above.
Expected: `OK`

(`drillIntoProject` still calls `renderKindPanel(label, currentSessions)` with the old single-`label` signature at this point — that's fixed in Task 6. The mismatch doesn't break syntax checking.)

- [ ] **Step 4: Commit**

```bash
git add templates/dashboard.html
git commit -m "refactor(dashboard): generalize kind panel for variable-length breadcrumbs"
```

---

### Task 6: Rewrite `drillIntoProject`, add `loadKindPanel` and `drillIntoStage`

**Files:**
- Modify: `templates/dashboard.html` (`drillIntoProject`, currently lines 1023-1061; remove the now-unused `#drill-project-label-kind` span, currently line 286)

- [ ] **Step 1: Remove the unused `#drill-project-label-kind` span**

Find this exact block (currently around lines 285-287):

```html
    <div id="panel-kind">
      <span id="drill-project-label-kind" style="display:none"></span>
      <h2>session breakdown</h2>
```

Replace it with:

```html
    <div id="panel-kind">
      <h2>session breakdown</h2>
```

- [ ] **Step 2: Replace `drillIntoProject` with the new flow plus helper functions**

Find this exact block (currently lines 1023-1061):

```js
async function drillIntoProject(label, projectKey) {
  const from = $('#f-from').value;
  const to = $('#f-to').value;
  // Show loading state in the kind panel while fetching
  $('#drill-project-label-kind').textContent = label;
  clearKids($('#kind-cards'));
  const loadEl = document.createElement('div');
  loadEl.style.cssText = 'color:var(--dim);font-size:11px;margin-top:10px';
  loadEl.textContent = 'loading…';
  $('#kind-cards').appendChild(loadEl);
  $('#panel-overview').style.display = 'none';
  $('#panel-kind').style.display = 'block';
  $('#panel-sessions').style.display = 'none';

  try {
    let sesUrl = '/api/sessions?project=' + encodeURIComponent(projectKey);
    if (activePreset === 'all') {
      sesUrl += '&since=all';
    } else {
      const sp = exactSince || from;
      const up = exactUntil || to;
      if (sp) sesUrl += '&since=' + encodeURIComponent(sp);
      if (up) sesUrl += '&until=' + encodeURIComponent(up);
    }
    const attrUrl = '/api/attribution?project=' + encodeURIComponent(projectKey);
    const [sesResp, attrResp] = await Promise.all([fetch(sesUrl), fetch(attrUrl)]);
    const [d, attrD] = await Promise.all([sesResp.json(), attrResp.json()]);
    currentSessions = d.sessions || [];
    renderKindPanel(label, currentSessions);
    renderAttributionPanel(attrD.attribution || []);
  } catch(e) {
    renderAttributionPanel([]);
    clearKids($('#kind-cards'));
    const errEl = document.createElement('div');
    errEl.style.cssText = 'color:var(--red);font-size:11px;margin-top:10px';
    errEl.textContent = 'error: ' + e.message;
    $('#kind-cards').appendChild(errEl);
  }
}
```

Replace it with:

```js
function sinceUntilQuery() {
  const from = $('#f-from').value;
  const to = $('#f-to').value;
  if (activePreset === 'all') return '&since=all';
  const sp = exactSince || from;
  const up = exactUntil || to;
  let q = '';
  if (sp) q += '&since=' + encodeURIComponent(sp);
  if (up) q += '&until=' + encodeURIComponent(up);
  return q;
}

function sessionsUrl(projectKey, stage) {
  let url = '/api/sessions?project=' + encodeURIComponent(projectKey);
  if (stage) url += '&stage=' + encodeURIComponent(stage);
  return url + sinceUntilQuery();
}

async function loadKindPanel(breadcrumbSegments, sesUrl) {
  // Show loading state in the kind panel while fetching
  clearKids($('#kind-cards'));
  const loadEl = document.createElement('div');
  loadEl.style.cssText = 'color:var(--dim);font-size:11px;margin-top:10px';
  loadEl.textContent = 'loading…';
  $('#kind-cards').appendChild(loadEl);
  $('#panel-overview').style.display = 'none';
  $('#panel-stage').style.display = 'none';
  $('#panel-kind').style.display = 'block';
  $('#panel-sessions').style.display = 'none';

  try {
    const attrUrl = '/api/attribution?project=' + encodeURIComponent(currentProjectKey);
    const [sesResp, attrResp] = await Promise.all([fetch(sesUrl), fetch(attrUrl)]);
    const [d, attrD] = await Promise.all([sesResp.json(), attrResp.json()]);
    currentSessions = d.sessions || [];
    renderKindPanel(breadcrumbSegments, currentSessions);
    renderAttributionPanel(attrD.attribution || []);
  } catch(e) {
    renderAttributionPanel([]);
    clearKids($('#kind-cards'));
    const errEl = document.createElement('div');
    errEl.style.cssText = 'color:var(--red);font-size:11px;margin-top:10px';
    errEl.textContent = 'error: ' + e.message;
    $('#kind-cards').appendChild(errEl);
  }
}

async function drillIntoProject(label, projectKey) {
  currentProjectKey = projectKey;
  currentProjectLabel = label;
  clearKids($('#t-project-stage tbody'));
  $('#panel-overview').style.display = 'none';
  $('#panel-stage').style.display = 'block';
  $('#panel-kind').style.display = 'none';
  $('#panel-sessions').style.display = 'none';
  renderBreadcrumb([
    { label: '~ overview', onClick: showOverview },
    { label },
  ]);

  let byStage = [];
  try {
    const sumResp = await fetch('/api/summary?project=' + encodeURIComponent(projectKey) + '&kind=all' + sinceUntilQuery());
    const sumD = await sumResp.json();
    byStage = sumD.by_stage || [];
  } catch (e) {
    byStage = [];
  }

  if (byStage.length === 0) {
    await loadKindPanel(
      [{ label: '~ overview', onClick: showOverview }, { label }],
      sessionsUrl(projectKey, null),
    );
    return;
  }

  renderProjectStageTable(byStage);
}

function drillIntoStage(stage) {
  currentStage = stage;
  loadKindPanel(
    [
      { label: '~ overview', onClick: showOverview },
      { label: currentProjectLabel, onClick: showStagePanel },
      { label: stage },
    ],
    sessionsUrl(currentProjectKey, stage),
  );
}
```

- [ ] **Step 3: Verify JS syntax**

Run the syntax check command from the "Reference" section above.
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add templates/dashboard.html
git commit -m "feat(dashboard): wire up project -> stage -> kind drill-down flow"
```

---

### Task 7: Manual verification in the browser

**Files:** none (verification only)

- [ ] **Step 1: Start the dashboard server**

Use `preview_start` (or confirm it's already running) to serve the dashboard so it's reachable in the browser preview.

- [ ] **Step 2: Project with stage data**

Reload the page (`preview_eval: window.location.reload()`), then `preview_click` a project row in `#t-project` for a project that has classified sessions. Use `preview_snapshot` to confirm:
- Breadcrumb shows `~ overview / <project>`.
- `#panel-stage` is visible with `#t-project-stage` populated (stage, sess, turns, tokens, cost, cache·hit, %).
- `#panel-kind` and `#panel-sessions` are hidden.

- [ ] **Step 3: Stage → kind panel**

`preview_click` a stage row. Use `preview_snapshot` to confirm:
- Breadcrumb shows `~ overview / <project> / <stage>`.
- `#panel-kind` is visible with both "user sessions" and "subagent sessions" cards. If the project has subagent sessions in that stage, the "subagent sessions" card must show non-zero counts (this is the bug fix).
- `#panel-stage` is hidden.

- [ ] **Step 4: Kind → sessions, and back-navigation**

`preview_click` the "subagent sessions" card (or "user sessions" if subagent is empty). Use `preview_snapshot` to confirm:
- Breadcrumb shows `~ overview / <project> / <stage> / <kind>`.
- `#t-sessions` is populated.

`preview_click` each breadcrumb segment in turn (stage, then project, then `~ overview`) and `preview_snapshot` after each click to confirm the correct panel becomes visible and the breadcrumb shortens correctly.

- [ ] **Step 5: `__system_ops__` fallback**

`preview_click` the `__system_ops__` project row (if present in `#t-project`). Use `preview_snapshot` to confirm:
- `#panel-stage` is skipped — `#panel-kind` is shown directly.
- Breadcrumb shows the 2-level `~ overview / system ops` form (no stage segment).

- [ ] **Step 6: Take a screenshot for the record**

Use `preview_screenshot` of the stage panel and the kind panel (stage-scoped) to confirm the visual result matches the existing `#t-stage`/kind-card styling.
