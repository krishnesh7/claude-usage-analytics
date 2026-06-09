"""Deterministic SDLC stage classifier. No LLM. Runs in milliseconds.

The classifier scans the first user message of each unclassified session and
applies the keyword rules from stage_keywords.json. Ties are broken by the
explicit tie_break_order. Sessions with no keyword hits fall to 'adhoc'.

Tracker-overhead sessions are excluded — the parser already classifies those.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass

from .db import (
    clear_classifier_stages,
    connect,
    get_sessions_missing_stage,
    upsert_stage,
)
from .paths import STAGE_KEYWORDS_PATH


@dataclass
class ClassifyResult:
    classified: int
    by_stage: dict[str, int]
    skipped_overhead: int


# Content signatures of the .remember background agents. These sessions are
# tracker overhead but don't begin with a slash-command, so the parser's
# TRACKER_CMD_RE misses them. Keep in sync with parser/parse.mjs OVERHEAD_MSG_RE.
_OVERHEAD_MSG_RE = re.compile(
    r"^\s*(?:"
    r"You are summarizing a Claude Code session"
    r"|Apply maximum non-destructive compression"
    r"|You are a memory consolidation agent"
    r")",
    re.IGNORECASE,
)


def is_overhead_message(text: str | None) -> bool:
    """True when the first user message is a memory/tracker background agent."""
    return bool(text) and _OVERHEAD_MSG_RE.search(text) is not None


def load_keywords() -> tuple[dict[str, list[str]], list[str]]:
    with open(STAGE_KEYWORDS_PATH) as f:
        data = json.load(f)
    rules = data.get("rules", {})
    order = data.get("tie_break_order", list(rules.keys()))
    return rules, order


def _compile_patterns(rules: dict[str, list[str]]) -> dict[str, list[re.Pattern]]:
    compiled = {}
    for stage, keywords in rules.items():
        patterns = []
        for kw in keywords:
            kw_re = re.escape(kw.strip())
            if " " in kw or "-" in kw:
                patterns.append(re.compile(kw_re, re.IGNORECASE))
            else:
                patterns.append(re.compile(rf"\b{kw_re}\b", re.IGNORECASE))
        compiled[stage] = patterns
    return compiled


def classify_text(text: str, compiled: dict[str, list[re.Pattern]], order: list[str]) -> str:
    """Return the stage with the most keyword hits; break ties by `order`."""
    if not text:
        return "adhoc"
    scores: Counter[str] = Counter()
    for stage, patterns in compiled.items():
        for pat in patterns:
            if pat.search(text):
                scores[stage] += 1
    if not scores:
        return "adhoc"
    top = scores.most_common()
    max_score = top[0][1]
    tied = [stage for stage, score in top if score == max_score]
    if len(tied) == 1:
        return tied[0]
    for s in order:
        if s in tied:
            return s
    return tied[0]


def classify_all(reclassify: bool = False) -> ClassifyResult:
    if reclassify:
        clear_classifier_stages()
    rules, order = load_keywords()
    compiled = _compile_patterns(rules)
    rows = get_sessions_missing_stage()
    counts: Counter[str] = Counter()
    skipped = 0
    for row in rows:
        if row.get("is_tracker_overhead"):
            skipped += 1
            continue
        text = row.get("first_user_message") or ""
        if is_overhead_message(text):
            upsert_stage(row["session_id"], "_tracker_overhead_", "classifier")
            counts["_tracker_overhead_"] += 1
            continue
        stage = classify_text(text, compiled, order)
        upsert_stage(row["session_id"], stage, "classifier")
        counts[stage] += 1
    return ClassifyResult(
        classified=sum(counts.values()),
        by_stage=dict(counts),
        skipped_overhead=skipped,
    )
