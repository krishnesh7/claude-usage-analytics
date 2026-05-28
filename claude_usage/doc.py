"""In-project documentation generator. Writes `<project_root>/<docs_relpath>/CLAUDE_USAGE.md`.

There are two code paths:
  - **Registered project**: uses _project_view (rich audit-trail format).
  - **Ad-hoc directory**: falls back to the simpler claude_usage.md.j2 template.
"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from . import _project_view
from . import _view
from . import projects as projects_mod
from .paths import DB_PATH, PRICES_PATH


def _template_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "templates"


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_template_dir())),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def write_doc(target: str | Path) -> Path:
    """Write the doc for a project. `target` may be:
      - A registered project name (matched in projects.json)
      - A filesystem path (cwd of a session) — we look up the matching project
        and, if none found, fall back to the simple template.
    """
    target_str = str(target)
    all_projects = projects_mod.load_all()

    # 1) Exact name match in registry.
    if target_str in all_projects:
        return _write_project_doc(all_projects[target_str])

    # 2) Path → registered project by pattern match.
    target_path = Path(target_str).expanduser()
    if target_path.exists():
        project = projects_mod.find_for_cwd(target_path.resolve())
        if project:
            return _write_project_doc(project)

        # 3) Fallback to simple template using the dir name as a substring filter.
        return _write_simple_doc(target_path.resolve())

    # 4) Best-effort: treat target_str as a substring filter for the simple template.
    return _write_simple_doc(Path.cwd())


def _write_project_doc(project: projects_mod.Project) -> Path:
    ctx = _project_view.build_project_view(project.name)
    root = Path(project.root_path)
    out_dir = root / project.docs_relpath
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "CLAUDE_USAGE.md"
    tpl = _env().get_template("project_usage.md.j2")
    out.write_text(tpl.render(**ctx), encoding="utf-8")
    return out


def _write_simple_doc(project_dir: Path) -> Path:
    docs_dir = project_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    out = docs_dir / "CLAUDE_USAGE.md"

    project_name = project_dir.name or str(project_dir)
    ctx = _view.build(project=project_name, since="all")
    ctx["project_name"] = project_name
    ctx["db_path"] = str(DB_PATH)
    ctx["prices_path"] = str(PRICES_PATH)

    tpl = _env().get_template("claude_usage.md.j2")
    out.write_text(tpl.render(**ctx), encoding="utf-8")
    return out
