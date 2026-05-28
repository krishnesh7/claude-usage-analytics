"""`cu` CLI entrypoint. Click-based; commands shell out to Node for parsing."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import click

from . import classify as classify_mod
from . import db as dbmod
from . import pricing as pricing_mod
from .paths import DB_PATH, PARSER_PATH


def _format_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


@click.group()
def cli() -> None:
    """Claude Code usage tracker — local analytics over your ~/.claude/projects transcripts."""


@cli.command()
@click.option("--force", is_flag=True, help="Re-parse even unchanged files; re-import all enrichment history.")
@click.option("--verbose", is_flag=True)
@click.option("--no-enrich", is_flag=True, help="Skip the official-analyzer enrichment step.")
def parse(force: bool, verbose: bool, no_enrich: bool) -> None:
    """Run the Node parser then enrich with cache-break and top-prompt data."""
    if not PARSER_PATH.exists():
        click.echo(f"ERROR: parser not found at {PARSER_PATH}", err=True)
        sys.exit(2)

    # Step 1: incremental JSONL → SQLite
    args = ["node", str(PARSER_PATH)]
    if force:
        args.append("--force")
    if verbose:
        args.append("--verbose")
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        click.echo(result.stderr, err=True)
        sys.exit(result.returncode)
    if result.stdout.strip():
        click.echo(result.stdout)

    # Step 2: run official analyzer and import cache_breaks + prompt_costs.
    # Skipped if --no-enrich or the official analyzer isn't installed.
    if not no_enrich:
        from . import _enriched
        from .paths import OFFICIAL_ANALYZER_PATH
        if OFFICIAL_ANALYZER_PATH.exists():
            stats = _enriched.enrich(force=force)
            if "error" in stats:
                click.echo(f"[enrich] warning: {stats['error']}", err=True)
            else:
                click.echo(
                    f"[enrich] +{stats['cache_breaks_added']} breaks, "
                    f"+{stats['prompts_added']} prompts "
                    f"(since={stats['since']}, {stats['elapsed_s']}s)"
                )


@cli.command()
def classify() -> None:
    """Apply the keyword classifier to any sessions still missing a stage."""
    if not DB_PATH.exists():
        click.echo("ERROR: usage.db missing. Run `cu parse` first.", err=True)
        sys.exit(2)
    res = classify_mod.classify_all()
    click.echo(json.dumps({
        "classified": res.classified,
        "by_stage": res.by_stage,
        "skipped_overhead_sessions": res.skipped_overhead,
    }, indent=2))


@cli.command()
@click.option("--project", help="Filter by project substring (LIKE %X%).")
@click.option("--since", default="7d", help="24h | 7d | 30d | all | ISO-8601")
@click.option("--stage", help="Filter to a single stage.")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON instead of text.")
def summary(project: str | None, since: str, stage: str | None, as_json: bool) -> None:
    """Print token + imputed-$ summary, grouped by stage."""
    since_dt = dbmod.parse_since(since)
    prices = pricing_mod.load_prices()

    by_stage_rows = dbmod.totals_by_stage(project=project, since=since_dt)
    by_proj_rows = dbmod.totals_by_project(since=since_dt) if not project else []

    # Imputed cost per stage requires per-model breakdown within that stage.
    cost_by_stage: dict[str, dict] = {}
    for r in by_stage_rows:
        s = r["stage"]
        if stage and s != stage:
            continue
        per_model = dbmod.turns_by_model_for_stage(s, project=project, since=since_dt)
        c = pricing_mod.total_cost(per_model, prices)
        cost_by_stage[s] = pricing_mod.cost_dict(c)

    payload = {
        "filters": {"project": project, "since": since, "stage": stage},
        "by_stage": [{**r, "cost": cost_by_stage.get(r["stage"], {})} for r in by_stage_rows if not stage or r["stage"] == stage],
        "by_project": by_proj_rows,
        "totals": _grand_totals(by_stage_rows, prices, project, since_dt, stage),
    }

    if as_json:
        click.echo(json.dumps(payload, indent=2, default=str))
        return

    _print_summary_text(payload)


def _grand_totals(by_stage_rows, prices, project, since_dt, stage_filter):
    in_tok = cc = cr = out = sess = turns = 0
    for r in by_stage_rows:
        if stage_filter and r["stage"] != stage_filter:
            continue
        in_tok += r["input_tokens"]
        cc += r["cache_creation_tokens"]
        cr += r["cache_read_tokens"]
        out += r["output_tokens"]
        sess += r["sessions"]
        turns += r["turns"]
    per_model = dbmod.turns_by_model(project=project, since=since_dt)
    if stage_filter:
        per_model = dbmod.turns_by_model_for_stage(stage_filter, project=project, since=since_dt)
    c = pricing_mod.total_cost(per_model, prices)
    return {
        "sessions": sess,
        "turns": turns,
        "input_tokens": in_tok,
        "cache_creation_tokens": cc,
        "cache_read_tokens": cr,
        "output_tokens": out,
        "total_tokens": in_tok + cc + cr + out,
        "cost": pricing_mod.cost_dict(c),
    }


def _print_summary_text(payload: dict) -> None:
    f = payload["filters"]
    click.echo(f"Filters: project={f['project'] or '(all)'}  since={f['since']}  stage={f['stage'] or '(all)'}")
    click.echo()
    click.echo("Per stage:")
    click.echo(f"  {'stage':<22} {'sess':>5} {'turns':>6} {'in':>9} {'cc':>9} {'cr':>10} {'out':>9} {'$ total':>10}")
    for r in payload["by_stage"]:
        c = r.get("cost", {})
        click.echo(
            f"  {r['stage']:<22} {r['sessions']:>5} {r['turns']:>6} "
            f"{_format_tokens(r['input_tokens']):>9} "
            f"{_format_tokens(r['cache_creation_tokens']):>9} "
            f"{_format_tokens(r['cache_read_tokens']):>10} "
            f"{_format_tokens(r['output_tokens']):>9} "
            f"${c.get('total_usd', 0):>9.2f}"
        )
    t = payload["totals"]
    click.echo()
    click.echo(
        f"TOTAL: sessions={t['sessions']} turns={t['turns']} "
        f"total_tokens={_format_tokens(t['total_tokens'])} "
        f"imputed_cost=${t['cost']['total_usd']:.2f}"
    )
    if payload["by_project"]:
        click.echo()
        click.echo("Top projects:")
        click.echo(f"  {'project':<60} {'sess':>5} {'tokens':>10}")
        for r in payload["by_project"][:10]:
            total = r["input_tokens"] + r["cache_creation_tokens"] + r["cache_read_tokens"] + r["output_tokens"]
            click.echo(f"  {(r['project_path'] or '')[:60]:<60} {r['sessions']:>5} {_format_tokens(total):>10}")


@cli.command()
@click.option("--session", "session_id", required=True, help="Session UUID to set stage for.")
@click.option("--set", "stage", required=True, help="Stage name.")
def stage(session_id: str, stage: str) -> None:
    """Manually override the stage for a specific session."""
    dbmod.upsert_stage(session_id, stage, "manual")
    click.echo(json.dumps({"session_id": session_id, "stage": stage, "source": "manual"}))


@cli.command("session-resolve")
@click.option("--cwd", default=None, help="Working directory to resolve. Defaults to $PWD.")
@click.option("--session", "session_id", default=None, help="Session ID (used for auto-tagging).")
@click.option("--tag/--no-tag", default=False, help="If set, write project_name to sessions table.")
def session_resolve(cwd: str | None, session_id: str | None, tag: bool) -> None:
    """Resolve a working directory to a registered project with confidence level.

    Outputs JSON: {confidence, project, projects, worktree_branch, hook_action}

    hook_action values (for SessionStart hook logic):
      silent    — EXACT/SUBDIR/WORKTREE: auto-tag, print nothing to the user
      info      — SUBDIR/WORKTREE: tag but emit a short info line
      confirm   — FUZZY: one project matched loosely, ask user to confirm
      choose    — AMBIGUOUS: multiple projects matched, ask user to pick one
      ask       — UNMATCHED: no project found, ask user which product this is
    """
    from . import projects as pm
    target = Path(cwd).expanduser().resolve() if cwd else Path.cwd()
    result = pm.resolve_cwd(target)

    # Map confidence → hook_action
    action_map = {
        pm.Confidence.EXACT:     "silent",
        pm.Confidence.SUBDIR:    "info",
        pm.Confidence.WORKTREE:  "info",
        pm.Confidence.FUZZY:     "confirm",
        pm.Confidence.AMBIGUOUS: "choose",
        pm.Confidence.UNMATCHED: "ask",
    }

    out = result.to_dict()
    out["hook_action"] = action_map[result.confidence]
    out["cwd"] = str(target)

    # Optionally write project_name into the sessions row immediately.
    if tag and session_id and result.project:
        dbmod.tag_session_project(session_id, result.project.name)
        out["tagged"] = True
    else:
        out["tagged"] = False

    click.echo(json.dumps(out))


@cli.command()
@click.option("--project", help="Project substring to filter on (LIKE %X%).")
@click.option("--since", default="all")
@click.option("--out", "out_path", default=None, help="Where to write the HTML.")
@click.option("--kind", default="user", type=click.Choice(["user", "subagent", "tracker", "all"]),
              help="Session kind to include. Default 'user' avoids subagent double-counting.")
def report(project: str | None, since: str, out_path: str | None, kind: str) -> None:
    """Generate a self-contained HTML report and write it to disk."""
    from . import report as report_mod
    p = report_mod.write_report(project=project, since=since, out_path=out_path, kind=kind)
    click.echo(str(p))


@cli.command()
@click.option("--project", required=False, help="Project path. Defaults to current working directory.")
def doc(project: str | None) -> None:
    """Write/update docs/CLAUDE_USAGE.md in the project directory."""
    from . import doc as doc_mod
    target = Path(project) if project else Path.cwd()
    p = doc_mod.write_doc(target)
    click.echo(str(p))


@cli.command()
@click.option("--port", default=7777)
@click.option("--host", default="127.0.0.1")
def serve(port: int, host: str) -> None:
    """Launch the local dashboard at http://host:port/."""
    from . import serve as serve_mod
    serve_mod.run(host=host, port=port)


# ---------------------------------------------------------------------------
# Project registry sub-commands
# ---------------------------------------------------------------------------
@cli.group()
def project() -> None:
    """Manage registered projects/products."""


@project.command("init")
@click.argument("name")
@click.option("--root", "root", default=None, help="Project root path. Defaults to current working directory.")
@click.option("--notes", default="", help="Free-form notes.")
def project_init(name: str, root: str | None, notes: str) -> None:
    """Register the current directory (or --root) as a project.

    Auto-detects existing worktrees by name pattern and includes them.
    """
    from . import projects as projects_mod
    target = Path(root) if root else Path.cwd()
    p = projects_mod.init_project(name=name, root_path=target, notes=notes)
    # Force a re-parse so sessions get linked to this project.
    subprocess.run(["node", str(PARSER_PATH), "--force"], capture_output=True)
    click.echo(json.dumps({
        "name": p.name,
        "root_path": p.root_path,
        "match_patterns": p.match_patterns,
        "docs_relpath": p.docs_relpath,
    }, indent=2))


@project.command("list")
def project_list() -> None:
    """List registered projects with lifetime totals."""
    from . import _view, projects as projects_mod
    all_p = projects_mod.load_all()
    if not all_p:
        click.echo("(no projects registered — try `cu project init <name>` in a project directory)")
        return
    click.echo(f"{'name':<30} {'sess':>5} {'tokens':>10} {'cost':>10} {'patterns'}")
    for p in all_p.values():
        with dbmod.connect() as c:
            row = c.execute(
                "SELECT COUNT(DISTINCT s.session_id) AS sess, "
                "       COALESCE(SUM(t.input_tokens+t.cache_creation_tokens+t.cache_read_tokens+t.output_tokens),0) AS tok "
                "FROM sessions s LEFT JOIN turns t ON t.session_id=s.session_id "
                "WHERE s.project_name = ?",
                (p.name,),
            ).fetchone()
        view = _view.build(project=None, since="all")  # for total tokens reference only
        # Imputed cost for the project:
        per_model = dbmod.turns_by_model(project=p.name, since=None)
        cost = pricing_mod.total_cost(per_model, pricing_mod.load_prices())
        click.echo(
            f"{p.name:<30} {row['sess']:>5} {_format_tokens(row['tok']):>10} "
            f"${cost.total_usd:>9.2f}  {', '.join(p.match_patterns[:3])}{'…' if len(p.match_patterns) > 3 else ''}"
        )


@project.command("tag")
@click.option("--session", "session_id", required=True, help="Session UUID to tag.")
@click.option("--name", "project_name", required=True, help="Registered project name.")
def project_tag(session_id: str, project_name: str) -> None:
    """Tag an existing session row with a project name.

    The project must already be registered (via `cu project init`).
    If the project isn't found in the registry, exits with an error.
    """
    from . import projects as projects_mod
    all_p = projects_mod.load_all()
    if project_name not in all_p:
        available = ", ".join(all_p.keys()) or "(none)"
        click.echo(
            json.dumps({"error": f"Unknown project '{project_name}'. Registered: {available}. "
                                  "Run `cu project init <name>` to register it first."}),
            err=True,
        )
        raise SystemExit(1)
    dbmod.tag_session_project(session_id, project_name)
    click.echo(json.dumps({"session_id": session_id, "project_name": project_name, "status": "tagged"}))


@project.command("relink")
def project_relink() -> None:
    """Recompute project_name for every session using current projects.json.

    Useful after adding patterns or registering a new project.
    """
    subprocess.run(["node", str(PARSER_PATH), "--force"], capture_output=True)
    with dbmod.connect() as c:
        row = c.execute(
            "SELECT COUNT(*) AS total, "
            "       SUM(CASE WHEN project_name IS NOT NULL THEN 1 ELSE 0 END) AS linked "
            "FROM sessions"
        ).fetchone()
    click.echo(json.dumps(dict(row), indent=2))


if __name__ == "__main__":
    cli()
