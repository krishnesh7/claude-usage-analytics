"""Project registry — load/save ~/.claude/usage/projects.json and resolve sessions.

A "project" is a named product that may span multiple Claude Code working
directories — including worktrees and subdirs. Worktrees are auto-detected via
the `--claude-worktrees-<branch>` suffix pattern in the encoded directory name.

The registry is the authoritative configuration (projects.json on disk).
SQLite mirrors it for SQL joins but is not the source of truth.

Resolution confidence tiers (highest → lowest):
  EXACT    — cwd is exactly the project's root_path
  SUBDIR   — cwd is a subdirectory of root_path
  WORKTREE — cwd encodes a git worktree of the project
  FUZZY    — a match_pattern substring appears in the cwd (single project)
  AMBIGUOUS — multiple projects match at any of the above tiers
  UNMATCHED — no project matches at all
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Iterable

from .paths import PROJECTS_DIR as TRANSCRIPTS_DIR
from .paths import USAGE_DIR

PROJECTS_PATH = USAGE_DIR / "projects.json"
WORKTREE_RE = re.compile(r"^(.+?)-{1,2}claude-worktrees-(.+)$")


class Confidence(str, Enum):
    EXACT = "EXACT"
    SUBDIR = "SUBDIR"
    WORKTREE = "WORKTREE"
    FUZZY = "FUZZY"
    AMBIGUOUS = "AMBIGUOUS"
    UNMATCHED = "UNMATCHED"


@dataclass
class ResolveResult:
    confidence: Confidence
    projects: list["Project"] = field(default_factory=list)
    # For WORKTREE matches: the branch name extracted from the encoded dir.
    worktree_branch: str = ""

    @property
    def project(self) -> "Project | None":
        """Convenience accessor when exactly one project matched."""
        return self.projects[0] if len(self.projects) == 1 else None

    def to_dict(self) -> dict:
        return {
            "confidence": self.confidence.value,
            "project": self.project.name if self.project else None,
            "projects": [p.name for p in self.projects],
            "worktree_branch": self.worktree_branch,
        }


@dataclass
class Project:
    name: str
    root_path: str
    match_patterns: list[str] = field(default_factory=list)
    docs_relpath: str = "docs/usage"
    created_at: str = ""
    notes: str = ""

    def to_json(self) -> dict:
        return {
            "root_path": self.root_path,
            "match_patterns": self.match_patterns,
            "docs_relpath": self.docs_relpath,
            "created_at": self.created_at,
            "notes": self.notes,
        }


def _read() -> dict:
    if not PROJECTS_PATH.exists():
        return {"_comment": "Registered Claude Code projects.", "projects": {}}
    with open(PROJECTS_PATH) as f:
        return json.load(f)


def _write(data: dict) -> None:
    PROJECTS_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_all() -> dict[str, Project]:
    data = _read()
    out: dict[str, Project] = {}
    for name, cfg in (data.get("projects") or {}).items():
        if name.startswith("_"):
            continue
        out[name] = Project(
            name=name,
            root_path=cfg.get("root_path", ""),
            match_patterns=list(cfg.get("match_patterns") or []),
            docs_relpath=cfg.get("docs_relpath", "docs/usage"),
            created_at=cfg.get("created_at", ""),
            notes=cfg.get("notes", ""),
        )
    return out


def save(project: Project) -> None:
    data = _read()
    data.setdefault("projects", {})[project.name] = project.to_json()
    _write(data)


def derive_match_patterns(root_path: Path) -> list[str]:
    """Default match patterns from the cwd: basename + encoded basename.

    For `/Users/me/work/myproj`, patterns include:
      - `myproj`
      - `-Users-me-work-myproj`  (encoded form)
    Plus auto-detection of any existing worktrees under ~/.claude/projects/.
    """
    basename = root_path.name
    encoded = "-" + str(root_path).strip("/").replace("/", "-")
    patterns = [basename, encoded]
    # Look for worktrees that share the encoded prefix.
    if TRANSCRIPTS_DIR.exists():
        for entry in TRANSCRIPTS_DIR.iterdir():
            if not entry.is_dir():
                continue
            m = WORKTREE_RE.match(entry.name)
            if m and m.group(1) == encoded:
                patterns.append(entry.name)
    # Dedupe while preserving order.
    seen, out = set(), []
    for p in patterns:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def init_project(name: str, root_path: Path, notes: str = "") -> Project:
    """Register a new project. Idempotent — if name exists, patterns are
    re-derived and merged (existing patterns preserved)."""
    root = Path(root_path).expanduser().resolve()
    existing = load_all().get(name)
    derived = derive_match_patterns(root)
    if existing:
        merged = list(dict.fromkeys(existing.match_patterns + derived))
        p = Project(
            name=name,
            root_path=str(root),
            match_patterns=merged,
            docs_relpath=existing.docs_relpath,
            created_at=existing.created_at,
            notes=notes or existing.notes,
        )
    else:
        p = Project(
            name=name,
            root_path=str(root),
            match_patterns=derived,
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            notes=notes,
        )
    save(p)
    return p


def find_for_cwd(cwd: Path | str) -> Project | None:
    """Return the project whose match patterns include the given cwd."""
    return resolve_cwd(cwd).project


def resolve_cwd(cwd: Path | str) -> ResolveResult:
    """Resolve a cwd to a project with a tiered confidence level.

    Tiers (checked in priority order):
      EXACT    → cwd == root_path (same path, no suffix)
      SUBDIR   → cwd.startswith(root_path + "/")
      WORKTREE → encoded cwd matches a worktree pattern in match_patterns
      FUZZY    → any match_pattern is a substring of cwd or its encoded form
      AMBIGUOUS → multiple distinct projects matched at any tier
      UNMATCHED → nothing matched
    """
    cwd_path = Path(str(cwd)).expanduser().resolve()
    cwd_str = str(cwd_path)
    # Encoded form: replicate Claude Code's path→dir encoding (/ → -)
    encoded = "-" + cwd_str.strip("/").replace("/", "-")

    exact: list[Project] = []
    subdir: list[Project] = []
    worktree: list[tuple[Project, str]] = []  # (project, branch)
    fuzzy: list[Project] = []

    for p in load_all().values():
        root = Path(p.root_path).expanduser().resolve()

        # EXACT: same directory
        if cwd_path == root:
            exact.append(p)
            continue

        # SUBDIR: cwd is strictly inside root
        try:
            cwd_path.relative_to(root)
            subdir.append(p)
            continue
        except ValueError:
            pass

        # Pattern-based matching
        matched = False
        for needle in p.match_patterns:
            if not needle:
                continue
            if needle in cwd_str or needle in encoded:
                # If the matching needle itself looks like a worktree path,
                # or the encoded cwd contains the worktree marker, classify
                # as WORKTREE so the hook can report the branch name.
                m_needle = WORKTREE_RE.match(needle.lstrip("-"))
                m_encoded = WORKTREE_RE.match(encoded.lstrip("-"))
                branch = ""
                if m_needle:
                    branch = m_needle.group(2)
                elif m_encoded:
                    branch = m_encoded.group(2)

                if branch:
                    worktree.append((p, branch))
                else:
                    fuzzy.append(p)
                matched = True
                break

    # --- Collect all high-confidence matches and check for ambiguity ---
    high: list[Project] = exact + subdir + [p for p, _ in worktree]

    if len(high) > 1:
        return ResolveResult(Confidence.AMBIGUOUS, high)

    if len(exact) == 1:
        return ResolveResult(Confidence.EXACT, exact)
    if len(subdir) == 1:
        return ResolveResult(Confidence.SUBDIR, subdir)
    if len(worktree) == 1:
        p, branch = worktree[0]
        return ResolveResult(Confidence.WORKTREE, [p], worktree_branch=branch)

    if len(fuzzy) > 1:
        return ResolveResult(Confidence.AMBIGUOUS, fuzzy)
    if len(fuzzy) == 1:
        return ResolveResult(Confidence.FUZZY, fuzzy)

    return ResolveResult(Confidence.UNMATCHED, [])
