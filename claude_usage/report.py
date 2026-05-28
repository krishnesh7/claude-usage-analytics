"""HTML report generator. Renders templates/report.html.j2 from the shared view model."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import _view
from .paths import DB_PATH


def _template_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "templates"


def write_report(
    project: str | None = None,
    since: str = "all",
    out_path: str | None = None,
    kind: str | None = "user",
) -> Path:
    env = Environment(
        loader=FileSystemLoader(str(_template_dir())),
        autoescape=select_autoescape(["html"]),
    )
    tpl = env.get_template("report.html.j2")
    kind_arg = None if kind in (None, "", "all") else kind
    ctx = _view.build(project=project, since=since, kind=kind_arg)
    html = tpl.render(**ctx)

    if out_path is None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        out_path = f"./claude-usage-report-{stamp}.html"
    p = Path(out_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(html, encoding="utf-8")
    return p
