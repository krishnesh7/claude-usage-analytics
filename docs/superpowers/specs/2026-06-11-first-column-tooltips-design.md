# First-Column Tooltips (Project / Model / Stage)

**Date:** 2026-06-11
**Status:** Approved

## Overview

Add hover tooltips to the first column of four dashboard tables, explaining
what each row represents:

1. **by project** — project name → short description (from registry notes or README)
2. **by fluency** — project name → same description as above
3. **by model** — model name → what that model tier is good for
4. **by SDLC stage** (and the project drill-down stage table) — stage name → what that SDLC bucket means

Reuses the existing `[data-tip]` / `#tt` floating-tooltip mechanism (see
`2026-06-09-fluency-panel-tooltips-design.md`). No new endpoints.

---

## Part 1: Project descriptions (backend)

### `claude_usage/_view.py`

New helpers:

```python
_README_NAMES = ("README.md", "Readme.md", "readme.md")

def _readme_description(root_path: str) -> str | None:
    """First non-heading, non-badge line of the project's README, truncated to ~200 chars."""

def _project_description(r: dict, registry: dict) -> str | None:
    """projects.json `notes` (if non-empty) else README description, else None."""
```

`_project_description`:
- Returns `None` if `r["project_name"]` is unset (unregistered/path-based row) — frontend keeps showing the path.
- If the registered `Project.notes` is non-empty (stripped), return it as-is.
- Else call `_readme_description(project.root_path)`.

`_readme_description`:
- Looks for `README.md` / `Readme.md` / `readme.md` in `root_path`.
- Reads up to the first 60 lines.
- Skips blank lines, headings (`#`), badge/image lines (`[![`, `![`), and raw HTML (`<`).
- Returns the first remaining line, with `**bold**` and `[text](url)` markdown stripped to plain text, truncated to 200 chars with `…`.
- Returns `None` if no README or no qualifying line.

### Wiring into `build_view`

In the `by_project` loop (`_view.py` ~line 240-258):
- Load `registry = projects_mod.load_all()` once, before the loop.
- After `r["label"] = _project_label(r)`, add:
  ```python
  r["description"] = _project_description(r, registry)
  ```

This field flows into both `by_project` (project table) and, since the
fluency table is computed client-side from `by_project`, into `p.r.description`
for the fluency table too. The synthetic "system operations" row is built
separately in `_collapse_project_rows` and is untouched — it keeps its
existing hardcoded tooltip.

---

## Part 2: Tooltip wiring (frontend)

### `mkRow` (templates/dashboard.html ~line 522)

Add support for a `tip` field on cell descriptors:

```js
if (c.tip) td.dataset.tip = c.tip;
```

Alongside the existing `c.title` handling (left as-is for any other callers).

### Project table (`renderProjectTable`)

Replace the current `{ text: label, title: tooltip }` first cell with `tip`:

```js
const tooltip = isSysOps
  ? 'Plugin & automation sessions (memory consolidation etc.) — included in grand total'
  : (r.description || r.project_path || '');
...
{ text: label, tip: tooltip },
```

### Fluency table (`renderFluencyTable`)

Replace `{ text: shortName(p.name), title: p.name }` with:

```js
const tip = p.r.description || (p.name && p.name.length > 22 ? p.name : '');
...
{ text: shortName(p.name), tip },
```

(Falls back to showing the untruncated name when there's no description and the name was truncated.)

### Model table (`renderModelTable`)

New helper near the other formatting helpers:

```js
function modelTip(model) {
  const m = (model || '').toLowerCase();
  if (m.includes('opus'))   return "Opus — Anthropic's most capable model. Best for complex reasoning, architecture, and high-stakes work. Highest cost per token.";
  if (m.includes('sonnet')) return 'Sonnet — balanced model for everyday coding and analysis. Strong capability at a fraction of Opus’s cost.';
  if (m.includes('haiku'))  return 'Haiku — fastest, cheapest model. Best for simple, high-volume, or latency-sensitive tasks.';
  return 'Claude model used for this work.';
}
```

First cell becomes `{ text: r.model, tip: modelTip(r.model) }`.

### Stage tables (`renderStageTable`, `renderProjectStageTable`)

New shared map near the other constants:

```js
const STAGE_TIPS = {
  requirements: 'Defining what to build — specs, user stories, requirements docs, roadmaps.',
  design: 'Architecture and design work — system design, data models, diagrams, tradeoffs.',
  test: 'Writing or running tests — unit, integration, e2e, TDD.',
  deploy: 'Shipping and operating — CI/CD, releases, deployments, infrastructure changes.',
  explore: 'Research and Q&A — understanding how something works, without building yet.',
  impl: 'Building and fixing — implementing features, fixing bugs, refactoring code.',
  adhoc: 'Catch-all — sessions that didn’t clearly match another stage.',
  _tracker_overhead_: "Internal usage-analytics tooling overhead (this dashboard's own sessions).",
};
function stageTip(stage) {
  return STAGE_TIPS[stage] || 'SDLC stage classified from the session’s first message.';
}
```

First cell in both tables becomes `{ text: r.stage, tip: stageTip(r.stage) }`
(replacing the bare `r.stage` string).

The category descriptions mirror the buckets defined in
`config/stage_keywords.json` (requirements, design, test, deploy, explore,
impl, plus the `adhoc` fallback and `_tracker_overhead_` synthetic stage).

---

## Files Changed

- `claude_usage/_view.py` — `_readme_description`, `_project_description`, wire into `build_view`
- `templates/dashboard.html` — `mkRow` tip support, `modelTip`, `STAGE_TIPS`/`stageTip`, and updates to `renderProjectTable`, `renderFluencyTable`, `renderModelTable`, `renderStageTable`, `renderProjectStageTable`

## Testing

- Existing pytest suite covers `_view.py` / `build_view` — add a small test that a registered project with `notes` gets `description` set, and that a project without notes but with a README gets the README's first description line.
- Manual check in the dashboard: hover project/fluency/model/stage first-column cells and confirm tooltips render.
