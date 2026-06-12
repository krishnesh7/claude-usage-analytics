"""Project-scoped view-model for the audit-trail doc.

Builds the rich view used by the in-project CLAUDE_USAGE.md. Derives
work_mode / surface / branch_type categories from the source signals
(tool counts, cwds, branches) at query time so the rules can evolve
without re-parsing the JSONL transcripts.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from . import db as dbmod
from . import pricing as pricing_mod
from . import projects as projects_mod
from .paths import DB_PATH, PRICES_PATH


def _fmt(n: int | float) -> str:
    n = int(n or 0)
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _total_tokens(row: dict) -> int:
    return (
        row.get("input_tokens", 0)
        + row.get("cache_creation_tokens", 0)
        + row.get("cache_read_tokens", 0)
        + row.get("output_tokens", 0)
    )


# ---------------------------------------------------------------------------
# Derived dimensions (rules-driven; no LLM)
# ---------------------------------------------------------------------------
WORK_MODE_RULES = [
    # (label, predicate)
    ("subagent-orchestration", lambda counts: counts.get("Agent", 0) + counts.get("Task", 0) >= 5),
    ("implementation",         lambda counts: counts.get("Edit", 0) + counts.get("Write", 0) >= max(5, sum(counts.values()) * 0.4)),
    ("ops/debug",              lambda counts: counts.get("Bash", 0) >= max(5, sum(counts.values()) * 0.5)),
    ("exploration",            lambda counts: counts.get("Read", 0) + counts.get("Grep", 0) + counts.get("Glob", 0) >= max(3, sum(counts.values()) * 0.5)),
    ("skill-driven",           lambda counts: counts.get("Skill", 0) >= 3),
]


def classify_work_mode(tool_counts: dict[str, int]) -> str:
    if not tool_counts:
        return "(none)"
    for label, pred in WORK_MODE_RULES:
        if pred(tool_counts):
            return label
    return "mixed"


BRANCH_TYPE_RULES = [
    ("main",   re.compile(r"^(main|master|HEAD)$")),
    ("feat",   re.compile(r"^(feat|feature)[\/-]")),
    ("fix",    re.compile(r"^(fix|bugfix|hotfix)[\/-]")),
    ("spike",  re.compile(r"^(spike|exp|experiment)[\/-]")),
    ("chore",  re.compile(r"^(chore|refactor|docs|test)[\/-]")),
    ("release", re.compile(r"^(release|rc|v\d)")),
]


def classify_branch(branch: str | None) -> str:
    if not branch:
        return "(none)"
    for label, pat in BRANCH_TYPE_RULES:
        if pat.match(branch):
            return label
    return "other"


# ---------------------------------------------------------------------------
# View-model
# ---------------------------------------------------------------------------
def build_project_view(project_name: str) -> dict[str, Any]:
    """Build the audit-trail view-model for one registered project."""
    prices = pricing_mod.load_prices()

    # Pull every session in this project (main + subagent).
    sessions = dbmod.project_sessions_audit(project_name, limit=10_000)
    main_sessions = [s for s in sessions if not s["parent_session_id"]]
    subagent_sessions = [s for s in sessions if s["parent_session_id"]]

    # Lifetime totals across every session, including tracker-overhead ones —
    # this is the basis for the Summary's token/session/cost figures so they
    # all describe the same population.
    raw_total_tokens = sum(_total_tokens(s) for s in sessions) or 1

    # Lifetime totals via the standard per-stage rollup filtered to this project.
    # `_tracker_overhead_`-classified sessions are excluded here so the SDLC
    # breakdown reflects real project work; the gap vs. raw_total_tokens is
    # reported separately as "tracker overhead" below.
    by_stage_rows = dbmod.totals_by_stage(project=project_name, since=None)
    for r in by_stage_rows:
        per_model = dbmod.turns_by_model_for_stage(r["stage"], project=project_name, since=None)
        r["cost"] = pricing_mod.cost_dict(pricing_mod.total_cost(per_model, prices))
        for k in ("input_tokens", "cache_creation_tokens", "cache_read_tokens", "output_tokens"):
            r[k + "_h"] = _fmt(r[k])
        r["total_tokens"] = _total_tokens(r)
        r["total_tokens_h"] = _fmt(r["total_tokens"])

    # A subagent whose root is `_tracker_overhead_` but which lacks its own
    # stage row can surface as a `_tracker_overhead_` bucket here too (with
    # sessions=0). Strip it so the SDLC breakdown only shows real project work.
    by_stage_rows = [r for r in by_stage_rows if r["stage"] != "_tracker_overhead_"]

    stage_classified_tokens = sum(r["total_tokens"] for r in by_stage_rows)
    for r in by_stage_rows:
        r["pct_of_total"] = 100.0 * r["total_tokens"] / (stage_classified_tokens or 1)

    overhead_tokens = max(raw_total_tokens - stage_classified_tokens, 0)
    overhead_pct = (100.0 * overhead_tokens / raw_total_tokens) if raw_total_tokens else 0.0

    # Lifetime cost across all turns in this project.
    per_model_all = dbmod.turns_by_model(project=project_name, since=None)
    grand_cost = pricing_mod.cost_dict(pricing_mod.total_cost(per_model_all, prices))

    # Daily timeline (last 30 days), with per-day cost.
    daily = dbmod.daily_timeline(project=project_name, days=30)
    for d in daily:
        per_model_day = dbmod.turns_by_model_for_day(d["day"], project=project_name)
        d["cost"] = pricing_mod.cost_dict(pricing_mod.total_cost(per_model_day, prices))
        d["total_tokens"] = _total_tokens(d)
        d["total_tokens_h"] = _fmt(d["total_tokens"])

    # Subagent rollup.
    by_agent = dbmod.totals_by_agent_type(project=project_name, since=None)
    for r in by_agent:
        r["total_tokens"] = _total_tokens(r)
        r["total_tokens_h"] = _fmt(r["total_tokens"])
        r["avg_per_session_h"] = _fmt(r["total_tokens"] / r["sessions"]) if r["sessions"] else "0"

    # Model mix.
    by_model = []
    for row in per_model_all:
        cost = pricing_mod.cost_dict(pricing_mod.total_cost([row], prices))
        by_model.append({
            "model": row["model"],
            "turns": row["turns"],
            "input_tokens": row["input_tokens"],
            "cache_creation_tokens": row["cache_creation_tokens"],
            "cache_read_tokens": row["cache_read_tokens"],
            "output_tokens": row["output_tokens"],
            "total_tokens": _total_tokens(row),
            "total_tokens_h": _fmt(_total_tokens(row)),
            "cost_usd": cost["total_usd"],
        })
    by_model.sort(key=lambda r: r["total_tokens"], reverse=True)

    # Tools, surfaces, branches, attribution — direct rollups.
    tools = dbmod.tool_counts_for_project(project_name)
    cwds = dbmod.cwds_for_project(project_name)
    branches = dbmod.branches_for_project(project_name)
    attribution = dbmod.attribution_for_project(project_name)

    # Derived: work_mode per session, then aggregate.
    by_work_mode: dict[str, dict[str, int]] = {}
    for sess in main_sessions:
        tc = dict(sess.get("top_tools") or [])
        # Get full tool counts (top_tools is just top 5); supplement from DB if needed.
        mode = classify_work_mode(tc)
        slot = by_work_mode.setdefault(mode, {"sessions": 0, "total_tokens": 0})
        slot["sessions"] += 1
        slot["total_tokens"] += _total_tokens(sess)
    by_work_mode_rows = sorted(
        [{"mode": k, "sessions": v["sessions"], "total_tokens": v["total_tokens"], "total_tokens_h": _fmt(v["total_tokens"])} for k, v in by_work_mode.items()],
        key=lambda r: r["total_tokens"], reverse=True,
    )

    # Derived: branch_type rollup.
    by_branch_type: dict[str, dict[str, int]] = {}
    for sess in main_sessions:
        for b in (sess.get("branches") or []) or ["(none)"]:
            bt = classify_branch(b)
            slot = by_branch_type.setdefault(bt, {"sessions": 0, "total_tokens": 0})
            slot["sessions"] += 1
            slot["total_tokens"] += _total_tokens(sess)
    by_branch_type_rows = sorted(
        [{"branch_type": k, "sessions": v["sessions"], "total_tokens": v["total_tokens"], "total_tokens_h": _fmt(v["total_tokens"])} for k, v in by_branch_type.items()],
        key=lambda r: r["total_tokens"], reverse=True,
    )

    # Annotate each session row for the audit trail.
    for s in sessions:
        s["total_tokens"] = _total_tokens(s)
        s["total_tokens_h"] = _fmt(s["total_tokens"])
        # Cost imputation by joining each session's per-model breakdown is expensive;
        # approximate using project-average $/token (acceptable for audit display).
        s["cost_usd_approx"] = round(grand_cost["total_usd"] * s["total_tokens"] / raw_total_tokens, 4)
        # Pretty top-tools string.
        tt = s.get("top_tools") or []
        s["top_tools_str"] = ", ".join(f"{name}×{count}" for name, count in tt[:4]) or "—"
        s["branches_str"] = ", ".join(s.get("branches") or []) or "—"
        from . import _labels, _redact
        _redact.redact_row(s, ("first_user_message", "ai_title", "subagent_description"))
        s["label"] = _labels.clean_label(
            s.get("ai_title"), s.get("first_user_message"),
            agent_type=s.get("agent_type"),
            parent_session_id=s.get("parent_session_id"),
            subagent_description=s.get("subagent_description"),
        )
        s["kind"] = "subagent" if s.get("parent_session_id") else "main"

    # Enriched data from the official analyzer (cache breaks, subagent-rollup prompts).
    # Gracefully absent if enrichment hasn't been run yet.
    try:
        from . import _enriched
        cache_breaks = _enriched.cache_breaks_for_project(project_name, limit=20)
        top_prompts = _enriched.top_prompts_for_project(project_name, limit=10)
    except Exception:
        cache_breaks = []
        top_prompts = []

    return {
        "project_name": project_name,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "db_path": str(DB_PATH),
        "prices_path": str(PRICES_PATH),
        "totals": {
            "sessions_total": len(sessions),
            "sessions_main": len(main_sessions),
            "sessions_subagent": len(subagent_sessions),
            "turns": sum(s["turns"] for s in sessions),
            "input_tokens_h": _fmt(sum(s["input_tokens"] for s in sessions)),
            "cache_creation_tokens_h": _fmt(sum(s["cache_creation_tokens"] for s in sessions)),
            "cache_read_tokens_h": _fmt(sum(s["cache_read_tokens"] for s in sessions)),
            "output_tokens_h": _fmt(sum(s["output_tokens"] for s in sessions)),
            "total_tokens": raw_total_tokens,
            "total_tokens_h": _fmt(raw_total_tokens),
            "cost": grand_cost,
            "overhead_tokens_h": _fmt(overhead_tokens),
            "overhead_pct": round(overhead_pct, 2),
            "first_session_at": min((s["started_at"] for s in sessions if s["started_at"]), default=None),
            "last_session_at": max((s["ended_at"] or s["started_at"] for s in sessions if s["started_at"]), default=None),
            "days_active": len(set((d["day"] for d in daily if d["total_tokens"] > 0))),
        },
        "by_stage": by_stage_rows,
        "by_agent_type": by_agent,
        "by_model": by_model,
        "by_work_mode": by_work_mode_rows,
        "by_branch_type": by_branch_type_rows,
        "tools": tools[:20],
        "cwds": cwds[:20],
        "branches": branches[:20],
        "attribution": attribution[:20],
        "daily": daily,
        "sessions_audit": sessions,
        "cache_breaks": cache_breaks,
        "top_prompts": top_prompts,
    }
