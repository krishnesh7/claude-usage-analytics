"""Shared view-model construction. Both the HTML report and the in-project doc
render from this same dict, so they stay in sync."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import db as dbmod
from . import pricing as pricing_mod


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


def _project_label(r: dict) -> str:
    """Human label for a project row: registered name, else shortened path + '(path)'."""
    if r.get("project_name"):
        return r["project_name"]
    path = r.get("project_path") or "(unknown)"
    if path.startswith("/"):
        parts = [p for p in path.split("/") if p]
        if len(parts) > 2:
            return "…/" + "/".join(parts[-2:]) + " (path)"
    return path + " (path)"


def _fmt_short(n: float) -> str:
    n = n or 0
    if n >= 1e9: return f"{n/1e9:.1f}B"
    if n >= 1e6: return f"{n/1e6:.1f}M"
    if n >= 1e3: return f"{n/1e3:.0f}k"
    return str(int(n))


def _stacked_trend_svg(rows: list[dict]) -> str:
    """Render a static (no-JS) stacked daily bar chart: user (blue) + subagent (orange),
    with y-axis peak label, x-axis date ticks, an average baseline, and a legend.
    Returns an SVG string (safe to inline) or '' when there's no data.
    """
    if not rows:
        return ""
    W, H = 720, 150
    ml, mr, mt, mb = 48, 12, 14, 26  # margins
    plot_w = W - ml - mr
    plot_h = H - mt - mb
    n = len(rows)
    peak = max((r["total"] for r in rows), default=0) or 1
    avg = sum(r["total"] for r in rows) / n if n else 0
    gap = 2
    bw = max(1.0, (plot_w / n) - gap)
    blue, orange, dim, grid = "#64a0ff", "#FB8C00", "rgb(136,136,136)", "rgba(255,255,255,0.08)"

    def y_of(v: float) -> float:
        return mt + plot_h - (v / peak) * plot_h

    parts = [f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="JetBrains Mono, monospace">']
    # y-axis gridlines + labels at 0, 50%, 100%
    for frac in (0, 0.5, 1.0):
        val = peak * frac
        yy = y_of(val)
        parts.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{W-mr}" y2="{yy:.1f}" stroke="{grid}" stroke-width="1"/>')
        parts.append(f'<text x="{ml-6}" y="{yy+3:.1f}" fill="{dim}" font-size="9" text-anchor="end">{_fmt_short(val)}</text>')
    # bars
    for i, r in enumerate(rows):
        x = ml + i * (plot_w / n) + gap / 2
        uh = (r["user"] / peak) * plot_h
        sh = (r["subagent"] / peak) * plot_h
        uy = mt + plot_h - uh
        sy = uy - sh
        if uh > 0:
            parts.append(f'<rect x="{x:.1f}" y="{uy:.1f}" width="{bw:.1f}" height="{uh:.1f}" fill="{blue}"/>')
        if sh > 0:
            parts.append(f'<rect x="{x:.1f}" y="{sy:.1f}" width="{bw:.1f}" height="{sh:.1f}" fill="{orange}"/>')
    # average baseline (dashed)
    ay = y_of(avg)
    parts.append(f'<line x1="{ml}" y1="{ay:.1f}" x2="{W-mr}" y2="{ay:.1f}" stroke="{dim}" stroke-width="1" stroke-dasharray="3,3"/>')
    parts.append(f'<text x="{W-mr}" y="{ay-3:.1f}" fill="{dim}" font-size="9" text-anchor="end">avg {_fmt_short(avg)}</text>')
    # x-axis date ticks: first, middle, last
    for idx in {0, n // 2, n - 1}:
        if 0 <= idx < n:
            x = ml + idx * (plot_w / n) + bw / 2
            label = rows[idx]["day"][5:]  # MM-DD
            parts.append(f'<text x="{x:.1f}" y="{H-8}" fill="{dim}" font-size="9" text-anchor="middle">{label}</text>')
    # legend
    parts.append(f'<rect x="{ml}" y="2" width="9" height="9" fill="{blue}"/>')
    parts.append(f'<text x="{ml+13}" y="10" fill="{dim}" font-size="9">user</text>')
    parts.append(f'<rect x="{ml+52}" y="2" width="9" height="9" fill="{orange}"/>')
    parts.append(f'<text x="{ml+65}" y="10" fill="{dim}" font-size="9">subagent</text>')
    parts.append("</svg>")
    return "".join(parts)


def _cache_hit_rate(row: dict) -> float | None:
    """cache_read / (cache_read + cache_creation + input). None if no input/cache traffic."""
    cr = row.get("cache_read_tokens", 0) or 0
    cc = row.get("cache_creation_tokens", 0) or 0
    inp = row.get("input_tokens", 0) or 0
    total = cr + cc + inp
    return (cr / total) if total else None


def build(project: str | None, since: str, kind: str | None = None) -> dict:
    since_dt = dbmod.parse_since(since)
    prices = pricing_mod.load_prices()

    by_stage = dbmod.totals_by_stage(project=project, since=since_dt, kind=kind)
    for r in by_stage:
        per_model = dbmod.turns_by_model_for_stage(r["stage"], project=project, since=since_dt)
        r["cost"] = pricing_mod.cost_dict(pricing_mod.total_cost(per_model, prices))
        for k in ("input_tokens", "cache_creation_tokens", "cache_read_tokens", "output_tokens"):
            r[k + "_h"] = _fmt(r[k])
        r["total_tokens"] = _total_tokens(r)
        r["total_tokens_h"] = _fmt(r["total_tokens"])
        r["cache_hit_rate"] = _cache_hit_rate(r)

    grand_total = sum(r["total_tokens"] for r in by_stage)
    grand_cost = sum(r["cost"]["total_usd"] for r in by_stage)
    for r in by_stage:
        r["pct_of_total"] = (100.0 * r["total_tokens"] / grand_total) if grand_total else 0.0

    by_project = []
    if not project:
        by_project = dbmod.totals_by_project(since=since_dt, kind=kind)
        for r in by_project[:30]:
            lookup_key = r.get("project_name") or r.get("project_path", "")
            per_model = dbmod.turns_by_model(project=lookup_key, since=since_dt)
            r["cost"] = pricing_mod.cost_dict(pricing_mod.total_cost(per_model, prices))
            for k in ("input_tokens", "cache_creation_tokens", "cache_read_tokens", "output_tokens"):
                r[k + "_h"] = _fmt(r[k])
            r["total_tokens"] = _total_tokens(r)
            r["total_tokens_h"] = _fmt(r["total_tokens"])
            r["pct_of_total"] = (100.0 * r["total_tokens"] / grand_total) if grand_total else 0.0
            r["cache_hit_rate"] = _cache_hit_rate(r)
            r["label"] = _project_label(r)
        by_project = by_project[:30]

    by_agent_type = dbmod.totals_by_agent_type(project=project, since=since_dt, kind=kind)
    for r in by_agent_type:
        r["total_tokens"] = _total_tokens(r)
        r["total_tokens_h"] = _fmt(r["total_tokens"])
        r["avg_per_session_h"] = _fmt(r["total_tokens"] / r["sessions"]) if r["sessions"] else "0"
        r["cache_hit_rate"] = _cache_hit_rate(r)

    # by-model rollup — total tokens and cost per Claude model used in window
    by_model_rows = dbmod.turns_by_model(project=project, since=since_dt)
    by_model = {}
    for t in by_model_rows:
        m = t.get("model") or "unknown"
        agg = by_model.setdefault(m, {
            "model": m, "input_tokens": 0, "cache_creation_tokens": 0,
            "cache_read_tokens": 0, "output_tokens": 0,
        })
        for k in ("input_tokens", "cache_creation_tokens", "cache_read_tokens", "output_tokens"):
            agg[k] += t.get(k, 0) or 0
    by_model_list = [v for v in by_model.values()
                     if _total_tokens(v) > 0 and v["model"] not in ("<synthetic>", "unknown")]
    for r in by_model_list:
        r["total_tokens"] = _total_tokens(r)
        r["total_tokens_h"] = _fmt(r["total_tokens"])
        for k in ("input_tokens", "cache_creation_tokens", "cache_read_tokens", "output_tokens"):
            r[k + "_h"] = _fmt(r[k])
        single = [{"model": r["model"], **{k: r[k] for k in (
            "input_tokens", "cache_creation_tokens", "cache_read_tokens", "output_tokens"
        )}}]
        r["cost"] = pricing_mod.cost_dict(pricing_mod.total_cost(single, prices))
        r["cache_hit_rate"] = _cache_hit_rate(r)
    by_model_list.sort(key=lambda x: x["total_tokens"], reverse=True)

    # stacked trend (user vs subagent tokens per day), respects the since filter
    timeline_rows = dbmod.daily_timeline_by_kind(project=project, since=since_dt)
    sparkline = [{
        "day": r["day"],
        "user": r["user_tokens"],
        "subagent": r["subagent_tokens"],
        "total": r["user_tokens"] + r["subagent_tokens"],
    } for r in timeline_rows if r["day"]]

    top_skills = dbmod.top_skills(project=project, since=since_dt, limit=15)

    # Grand totals + cache hit-rate
    total_input = sum(r["input_tokens"] for r in by_stage)
    total_cc = sum(r["cache_creation_tokens"] for r in by_stage)
    total_cr = sum(r["cache_read_tokens"] for r in by_stage)
    total_out = sum(r["output_tokens"] for r in by_stage)
    total_sessions = sum(r["sessions"] for r in by_stage)
    total_turns = sum(r["turns"] for r in by_stage)
    cache_total = total_cc + total_cr + total_input
    cache_hit = (total_cr / cache_total) if cache_total else None

    per_model = dbmod.turns_by_model(project=project, since=since_dt)
    grand_cost_obj = pricing_mod.cost_dict(pricing_mod.total_cost(per_model, prices))

    takes = _build_takes(by_stage, by_project, grand_total, grand_cost_obj["total_usd"])

    return {
        "filters": {"project": project, "since": since, "kind": kind or "all"},
        "by_stage": by_stage,
        "by_project": by_project,
        "by_agent_type": by_agent_type,
        "by_model": by_model_list,
        "sparkline": sparkline,
        "sparkline_svg": _stacked_trend_svg(sparkline),
        "top_skills": top_skills,
        "takes": takes,
        "totals": {
            "sessions": total_sessions,
            "turns": total_turns,
            "input_tokens": total_input,
            "cache_creation_tokens": total_cc,
            "cache_read_tokens": total_cr,
            "output_tokens": total_out,
            "total_tokens": grand_total,
            "input_tokens_h": _fmt(total_input),
            "cache_creation_tokens_h": _fmt(total_cc),
            "cache_read_tokens_h": _fmt(total_cr),
            "output_tokens_h": _fmt(total_out),
            "total_tokens_h": _fmt(grand_total),
            "cost": grand_cost_obj,
            "cache_hit_rate": cache_hit,
            "since_label": since,
            "last_session_at": None,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _build_takes(by_stage, by_project, grand_total, grand_cost) -> list[dict[str, Any]]:
    """3-5 one-line headlines mirroring the session-report skill's style."""
    takes: list[dict[str, Any]] = []
    if grand_total <= 0:
        return takes

    overhead = next((r for r in by_stage if r["stage"] == "_tracker_overhead_"), None)
    if overhead:
        pct = 100.0 * overhead["total_tokens"] / grand_total
        cls = "good" if pct < 0.5 else "warn" if pct < 2.0 else "bad"
        takes.append({
            "fig": f"{pct:.2f}%",
            "txt": f"<b>tracker overhead</b> is {pct:.2f}% of total tokens (target &lt;0.5%)",
            "cls": cls,
        })

    if by_stage:
        top = max(by_stage, key=lambda r: r["total_tokens"])
        pct = 100.0 * top["total_tokens"] / grand_total
        if pct > 40:
            takes.append({
                "fig": f"{pct:.0f}%",
                "txt": f"<b>{top['stage']}</b> consumed {pct:.0f}% of all tokens — consider whether work is balanced across stages",
                "cls": "warn",
            })

    if by_project:
        biggest = max(by_project, key=lambda r: r["total_tokens"])
        pct = 100.0 * biggest["total_tokens"] / grand_total
        if pct > 50:
            takes.append({
                "fig": f"{pct:.0f}%",
                "txt": f"<b>{biggest['project_path']}</b> is {pct:.0f}% of total tokens",
                "cls": "warn",
            })

    if grand_cost > 100:
        takes.append({
            "fig": f"${grand_cost:.0f}",
            "txt": f"imputed API cost is <b>${grand_cost:.2f}</b> — strong ROI versus Pro plan if &gt;$20/$100",
            "cls": "good",
        })

    return takes
