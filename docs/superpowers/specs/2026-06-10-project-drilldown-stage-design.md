# Project Drill-Down: Stage → User/Subagent → Sessions

## Context

Today, clicking a project row in `#t-project` calls `drillIntoProject(label, projectKey)`, which fetches `/api/sessions?project=X` and renders the user/subagent kind panel (`#panel-kind`) directly. The "subagent sessions" card in that panel is always empty, because `db.sessions_for_project` excludes every subagent session.

This spec adds a per-project **SDLC stage** breakdown as a new step between the project row and the kind panel, reusing the existing `#t-stage` table layout scoped to one project, and fixes the subagent-sessions gap as part of the same backend change (both the new stage-scoped flow and the existing unscoped flow need subagent sessions to work).

New flow: `~overview → project → stage → user/subagent → sessions` (4-level breadcrumb).

## Backend Changes

### `db.sessions_for_project(project, stage=None, since=None, until=None, limit=200)`

Replaces the current implementation ([claude_usage/db.py:196-234](../../../claude_usage/db.py#L196-L234)), which only returns root sessions (`parent_session_id IS NULL AND session_id NOT LIKE '%::agent-%'`).

New behavior: return root sessions for the project **plus** their subagent children, each row tagged with an *effective stage* — a root's own stage, or its parent's stage for a subagent child (same inheritance rule already used by `totals_by_stage`, [claude_usage/db.py:129-149](../../../claude_usage/db.py#L129-L149)).

Approach: a CTE `matched_roots(session_id, eff_stage)` selects root sessions matching the project filter (current WHERE clause, lines 220-223) joined to `session_stage` for their own stage. The main query then joins `sessions` to `matched_roots` on `s.session_id = mr.session_id` (root case) **or** `s.parent_session_id = mr.session_id` (subagent-child case), giving every returned row `mr.eff_stage` as its `stage`. If `stage` is passed, filter `mr.eff_stage = ?` — this naturally filters both roots and their children together, since they share `mr.eff_stage`.

All other columns (turns, token sums via `LEFT JOIN turns`, `ai_title`, `first_user_message`, `agent_type`, `parent_session_id`, `subagent_description`, etc.) stay as today, grouped by `s.session_id`.

### `/api/sessions` — new optional `stage` param

[claude_usage/serve.py:122-127](../../../claude_usage/serve.py#L122-L127): add `stage: str | None = Query(default=None)`. Pass through to `dbmod.sessions_for_project(project, stage=stage, since=since_dt, until=until_dt)`. For `project == "__system_ops__"`, ignore `stage` (system-ops sessions have no stage data) — `sessions_for_system_ops` call is unchanged.

### Stage panel data — no new endpoint

`/api/summary?project=X` already returns `by_stage` scoped to the project via `totals_by_stage(project=project, ...)` ([claude_usage/_view.py:221](../../../claude_usage/_view.py#L221)), including `pct_of_total` computed against that project's grand total ([claude_usage/_view.py:235-238](../../../claude_usage/_view.py#L235-L238)).

One detail: the default `/api/summary` call uses `kind="user"`, which makes `totals_by_stage` filter out subagent rows from its token sums entirely (via `_where_clauses`'s `kind` branch). For the stage panel we want totals that include subagent contribution (per the stage-inheritance docstring: "token SUMs span the whole tree" — true only when `kind` is unfiltered). So the frontend's stage-panel fetch must call `/api/summary?project=X&kind=all&...` (→ `kind_arg=None` → no kind filter in `totals_by_stage`).

## Frontend Changes

### New panel: `#panel-stage`

New `<div id="panel-stage" style="display:none">` between `#panel-overview` and `#panel-kind`, containing a table `#t-project-stage` with the same columns/headers as `#t-stage` (stage, sess, turns, tokens, cost, cache·hit, %) — a separate table id so its sort state and `rowCache` entry don't collide with the global `#t-stage`. New renderer `renderProjectStageTable(rows)`, structurally like `renderStageTable` ([templates/dashboard.html:643-663](../../../templates/dashboard.html#L643-L663)) but each row's click handler calls `drillIntoStage(stage)` instead of `toggleBreakdown`.

### `drillIntoProject(label, projectKey)` — rewrite

1. Fetch `/api/summary?project=X&kind=all&since=...&until=...` for `by_stage`.
2. **If `by_stage` is empty** (covers `__system_ops__`, and any project with no classified sessions): fall back to today's behavior — fetch `/api/sessions?project=X` + `/api/attribution?project=X`, call `renderKindPanel([...2-level breadcrumb...], sessions)` directly, skipping the stage panel entirely.
3. **Otherwise**: render `#t-project-stage` from `by_stage`, show `#panel-stage`, set breadcrumb to `~overview / project`. Store `currentProjectKey = projectKey`, `currentProjectLabel = label`.

### New function: `drillIntoStage(stage)`

- Fetch `/api/sessions?project=<currentProjectKey>&stage=<stage>&since=...&until=...`, with `since`/`until` resolved from the active filters the same way `drillIntoProject` does it today ([templates/dashboard.html:1039-1046](../../../templates/dashboard.html#L1039-L1046)) — `since=all` for the "all" preset, otherwise `exactSince || from` / `exactUntil || to`. Also fetch `/api/attribution?project=<currentProjectKey>` unchanged — attribution stays project-scoped, not stage-scoped; out of scope for this spec.
- Call `renderKindPanel(breadcrumbPrefix, sessions)` where `breadcrumbPrefix = [{label:'~ overview', onClick: showOverview}, {label: currentProjectLabel, onClick: showStagePanel}, {label: stage}]`.
- Store `currentStage = stage`.

### `renderKindPanel` signature change

[templates/dashboard.html:873-934](../../../templates/dashboard.html#L873-L934): change from `renderKindPanel(label, allSessions)` to `renderKindPanel(breadcrumbSegments, allSessions)`. Internals (building `user`/`subagent` cards from `allSessions`) are unchanged — `allSessions` now naturally contains subagent rows because of the `sessions_for_project` fix, so the "subagent sessions" card populates for real. Replace the hardcoded 2-segment breadcrumb with `renderBreadcrumb(breadcrumbSegments)`. Store `breadcrumbSegments` as `currentKindBreadcrumb` for `drillIntoKind` to extend.

For the no-stage-panel case (step 2 above), `breadcrumbSegments = [{label:'~ overview', onClick: showOverview}, {label}]` — same 2-level breadcrumb as today.

### `drillIntoKind(kindLabel, kindSessions)`

[templates/dashboard.html:936-948](../../../templates/dashboard.html#L936-L948): build breadcrumb as `[...currentKindBreadcrumb, {label: kindLabel}]`, where the last segment of `currentKindBreadcrumb` (currently label-only, "current page") gets an `onClick: showKindPanel` added so it becomes a back-link.

Generalize the existing `showKindPanel()` ([templates/dashboard.html:1071-1078](../../../templates/dashboard.html#L1071-L1078)) to: hide `#panel-sessions`, show `#panel-kind`, and call `renderBreadcrumb(currentKindBreadcrumb)` — it no longer needs to hardcode the 2-segment `[~overview, currentProjectLabel]` breadcrumb, since `currentKindBreadcrumb` (set by `renderKindPanel`) already holds the correct 2- or 3-segment prefix for either case.

### New function: `showStagePanel()`

Analogous to `showKindPanel` ([templates/dashboard.html:1071-1078](../../../templates/dashboard.html#L1071-L1078)): hides `#panel-kind`/`#panel-sessions`, shows `#panel-stage`, rebuilds breadcrumb as `~overview / project`.

### Breadcrumb summary

| Panel | Breadcrumb |
|---|---|
| `#panel-stage` | `~ overview / project` |
| `#panel-kind` (stage-scoped) | `~ overview / project / stage` |
| `#panel-kind` (no stage data, e.g. `__system_ops__`) | `~ overview / project` *(unchanged from today)* |
| `#panel-sessions` | `~ overview / project / stage / kind` *(or `~ overview / project / kind` for the no-stage case)* |

## Edge Cases

- **`__system_ops__`**: `totals_by_stage(project="__system_ops__", ...)` matches no rows (system-ops sessions aren't matched by the generic project filter), so `by_stage` is empty → stage panel skipped, flow identical to today.
- **Unclassified sessions**: `totals_by_stage` already buckets sessions with no `session_stage` row under `'unclassified'` — appears as a normal clickable row in the stage panel.
- **Stage with only subagent sessions** (no qualifying root in that stage): shouldn't occur given inheritance (every subagent's effective stage comes from a root that has that stage), but if `kindSessions` ends up empty for both kinds, the existing "none"/disabled card rendering handles it.

## Out of Scope

- Skill attribution (`/api/attribution`) remains project-scoped, not stage-scoped.
- No changes to `computeFluency`/fluency panel (covered by a separate spec).

## Testing

- `db.sessions_for_project`: `stage=None` returns root sessions **plus** their subagent children (currently returns roots only); `stage=<X>` filters both by inherited effective stage.
- `/api/sessions?project=X&stage=Y` integration test.
- Manual click-through: project → stage → user/subagent (both populated) → sessions, verifying breadcrumb and back-navigation at each level, and that `__system_ops__` skips straight to the kind panel.
