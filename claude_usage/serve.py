"""Local-only FastAPI dashboard.

Endpoints:
  GET /                  -> HTML page that polls /api/summary every 30s
  GET /api/summary       -> JSON: {by_stage, by_project, totals, ...}
  GET /api/sessions      -> JSON: per-session drill-down
  GET /api/projects-for  -> JSON: project distribution for a given stage/agent
  GET /api/parse-status  -> JSON: last auto-parse tick info

Background: while serving, ticks the Node parser every AUTO_PARSE_SEC seconds
so live sessions appear without a manual refresh. Pure local file/SQL work —
no LLM, no tokens.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse

from . import _labels
from . import _redact
from . import _view
from . import db as dbmod
from . import pricing as pricing_mod
from .paths import PARSER_PATH

AUTO_PARSE_SEC = int(os.environ.get("CU_SERVE_AUTO_PARSE_SEC", "60"))


def _index_path() -> Path:
    return Path(__file__).resolve().parent.parent / "templates" / "dashboard.html"


async def _auto_parse_loop(state: dict) -> None:
    if AUTO_PARSE_SEC <= 0 or not PARSER_PATH.exists():
        return
    while True:
        try:
            await asyncio.sleep(AUTO_PARSE_SEC)
            proc = await asyncio.create_subprocess_exec(
                "node", str(PARSER_PATH),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, err = await proc.communicate()
            state["last_parse_ts"] = time.time()
            state["last_parse_ok"] = proc.returncode == 0
            if proc.returncode != 0:
                state["last_parse_err"] = (err or b"").decode("utf-8", "replace")[:500]
            else:
                state["last_parse_err"] = None
        except asyncio.CancelledError:
            raise
        except Exception as e:
            state["last_parse_ok"] = False
            state["last_parse_err"] = str(e)[:500]


def make_app() -> FastAPI:
    app = FastAPI(title="claude-usage-analytics dashboard")
    app.state.parse_state = {"last_parse_ts": None, "last_parse_ok": None, "last_parse_err": None}

    @app.on_event("startup")
    async def _start_loop() -> None:
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, pricing_mod.ensure_prices)
        app.state.parse_task = asyncio.create_task(_auto_parse_loop(app.state.parse_state))

    @app.on_event("shutdown")
    async def _stop_loop() -> None:
        task = getattr(app.state, "parse_task", None)
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    @app.get("/api/parse-status")
    def api_parse_status() -> JSONResponse:
        return JSONResponse({
            "interval_sec": AUTO_PARSE_SEC,
            **app.state.parse_state,
        })

    @app.get("/api/prices/refresh")
    def api_prices_refresh() -> JSONResponse:
        try:
            count, last_fetched = pricing_mod.refresh_prices()
            return JSONResponse({"ok": True, "last_fetched": last_fetched, "model_count": count})
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    @app.get("/api/plan-hint")
    def api_plan_hint() -> JSONResponse:
        if os.environ.get("ANTHROPIC_API_KEY"):
            return JSONResponse({"mode": "api", "reason": "ANTHROPIC_API_KEY is set"})
        return JSONResponse({"mode": "subscription", "reason": "No API key detected"})

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(
            _index_path(), media_type="text/html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    @app.get("/api/summary")
    def api_summary(
        project: str | None = Query(default=None),
        since: str = Query(default="7d"),
        until: str | None = Query(default=None),
        kind: str | None = Query(default="user"),
    ) -> JSONResponse:
        kind_arg = None if kind in (None, "", "all") else kind
        view = _view.build(project=project, since=since, kind=kind_arg, until=until)
        return JSONResponse(view)

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
        # Impute cost per session
        for r in rows:
            per_model = dbmod.turns_by_model(
                project=r["session_id"],  # pass session_id for per-session query
                since=None,
            )
            # per-session cost: query turns directly
            with dbmod.connect() as c:
                turns = [dict(t) for t in c.execute(
                    "SELECT model, input_tokens, cache_creation_tokens, cache_creation_1h_tokens, cache_read_tokens, output_tokens FROM turns WHERE session_id = ?",
                    (r["session_id"],),
                )]
            all_costs = pricing_mod.total_cost_all_modes(turns, prices)
            r["cost"] = pricing_mod.cost_dict(all_costs["subscription"])
            r["cost_api"] = round(all_costs["api"].total_usd, 4)
            r["cost_conservative"] = round(all_costs["conservative"].total_usd, 4)
            r["cost_subscription"] = round(all_costs["subscription"].total_usd, 4)
            r["total_tokens"] = (
                r["input_tokens"] + r["cache_creation_tokens"]
                + r["cache_read_tokens"] + r["output_tokens"]
            )
            # Redact before label-building so even the dashboard tooltip is safe.
            # Try sys-ops pattern first (before redacting destroys the signal)
            sys_label = _labels.sys_ops_label(r.get("first_user_message"))
            _redact.redact_row(r, ("first_user_message", "ai_title", "subagent_description"))
            r["display_label"] = sys_label or _labels.clean_label(
                r.get("ai_title"), r.get("first_user_message"),
                agent_type=r.get("agent_type"),
                parent_session_id=r.get("parent_session_id"),
                subagent_description=r.get("subagent_description"),
            )
        return JSONResponse({"project": project, "sessions": rows})

    @app.get("/api/attribution")
    def api_attribution(project: str = Query(...)) -> JSONResponse:
        return JSONResponse({"attribution": dbmod.attribution_for_project(project)})

    @app.get("/api/projects-for")
    def api_projects_for(
        dim: str = Query(...),
        key: str = Query(...),
        since: str = Query(default="7d"),
    ) -> JSONResponse:
        """Project breakdown filtered by stage or agent_type. dim ∈ {stage, agent_type}."""
        since_dt = dbmod.parse_since(since)
        prices = pricing_mod.load_prices()
        rows = dbmod.projects_by_dim(dim, key, since=since_dt)
        grand_tokens = 0
        grand_cost = 0.0
        for r in rows:
            r["total_tokens"] = (
                r["input_tokens"] + r["cache_creation_tokens"]
                + r["cache_read_tokens"] + r["output_tokens"]
            )
            grand_tokens += r["total_tokens"]
            per_turns = []
            with dbmod.connect() as c:
                per_turns = [dict(t) for t in c.execute(
                    """
                    SELECT t.model, t.input_tokens, t.cache_creation_tokens,
                           t.cache_creation_1h_tokens, t.cache_read_tokens, t.output_tokens
                    FROM turns t JOIN sessions s ON s.session_id = t.session_id
                    LEFT JOIN session_stage ss ON ss.session_id = s.session_id
                    WHERE COALESCE(s.project_name, s.project_path) = COALESCE(?, ?)
                      AND (
                        (? = 'stage' AND COALESCE(ss.stage, 'unclassified') = ?)
                        OR (? = 'agent_type' AND COALESCE(s.agent_type, '(main)') = ?)
                      )
                    """,
                    (r["project_name"], r["project_path"], dim, key, dim, key),
                )]
            all_costs = pricing_mod.total_cost_all_modes(per_turns, prices)
            r["cost"] = pricing_mod.cost_dict(all_costs["subscription"])
            r["cost_api"] = round(all_costs["api"].total_usd, 4)
            r["cost_conservative"] = round(all_costs["conservative"].total_usd, 4)
            r["cost_subscription"] = round(all_costs["subscription"].total_usd, 4)
            grand_cost += r["cost"]["total_usd"]
        for r in rows:
            r["pct_of_total"] = (
                (r["total_tokens"] / grand_tokens * 100.0) if grand_tokens else 0.0
            )
        return JSONResponse({
            "dim": dim, "key": key,
            "projects": rows,
            "grand_total_tokens": grand_tokens,
            "grand_total_cost": grand_cost,
        })

    return app


def run(host: str = "127.0.0.1", port: int = 7777) -> None:
    app = make_app()
    uvicorn.run(app, host=host, port=port, log_level="warning")
