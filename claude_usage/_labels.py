"""Session label sanitization.

Claude Code wraps slash commands and hook output in pseudo-XML tags like
<command-message>...</command-message>, <command-name>, <local-command-stdout>,
<system-reminder>, <bash-input>, etc. These dominate first_user_message when a
session is opened with a slash command, producing useless labels like
"<command-message>foo</command-message>".

We strip those wrappers, drop common prefixes, take the first sentence,
and cap at MAX_LEN. Result is deterministic and token-free.
"""
from __future__ import annotations

import re

MAX_LEN = 60

# "You are [a/an/the] <role>." — captures up to the first sentence boundary
_YOU_ARE_RE = re.compile(
    r"^You are (?:a |an |the )?(.+?)(?:\.|,|\n|$)", re.IGNORECASE
)
# Imperative opener: "Apply maximum non-destructive compression."
# Allows hyphenated words like "non-destructive"
_IMPERATIVE_RE = re.compile(
    r"^([A-Z][a-z]+(?:-[a-z]+)*(?:\s+[a-z]+(?:-[a-z]+)*){0,5})\.",
    re.MULTILINE,
)


def sys_ops_label(first_user_message: str | None) -> str | None:
    """Auto-derive a short label for automation/plugin sessions from the
    structure of their system prompt — no hardcoded patterns needed.

    Handles two common prompt styles:
      "You are a memory consolidation agent. ..."  → "memory consolidation agent"
      "You are summarizing a Claude Code session"  → "summarizing claude code session"
      "Apply maximum non-destructive compression." → "apply maximum non-destructive compression"

    Returns None when the message doesn't look like an automation system prompt
    (too short, or starts with a real user sentence).
    """
    raw = (first_user_message or "").strip()
    if not raw or len(raw) < 40:
        return None

    # Style 1: "You are [a/an/the] <role>."
    m = _YOU_ARE_RE.match(raw)
    if m:
        role = m.group(1).strip()
        # Drop clauses after stopwords: "agent who ...", "agent that ..."
        role = re.split(r"\s+(?:who|that|and|with|your)\b", role, flags=re.IGNORECASE)[0]
        # Keep first 5 words so very long role phrases don't blow the label
        words = role.split()[:5]
        return _truncate(" ".join(words).lower())

    # Style 2: Leading imperative verb phrase (≥3 words before the first ".")
    m = _IMPERATIVE_RE.match(raw)
    if m:
        phrase = m.group(1).strip()
        if len(phrase.split()) >= 3:
            return _truncate(phrase.lower())

    return None

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_LEADING_NOISE_RE = re.compile(
    r"^(?:please\s+|can\s+you\s+|could\s+you\s+|run\s+|execute\s+|the\s+user\s+)",
    re.IGNORECASE,
)
_COMMAND_NAME_RE = re.compile(r"<command-name>\s*/?([^<\s]+)\s*</command-name>", re.IGNORECASE)
_COMMAND_MSG_RE = re.compile(r"<command-message>\s*([^<]+?)\s*</command-message>", re.IGNORECASE)
_COMMAND_ARGS_RE = re.compile(r"<command-args>\s*([^<]*?)\s*</command-args>", re.IGNORECASE)


def clean_label(
    ai_title: str | None,
    first_user_message: str | None,
    *,
    agent_type: str | None = None,
    parent_session_id: str | None = None,
    subagent_description: str | None = None,
) -> str:
    """Return a short, human-readable session label.

    Order of preference:
      1. explicit ai_title
      2. subagent sessions →
           'subagent[<agent_type>]: <description>'  (if description present)
           'subagent: <agent_type>'                  (fallback)
      3. slash-command sessions → '/<command> [args]'
      4. sanitized free-text first_user_message
      5. '(no title)'
    """
    if ai_title:
        title = ai_title.strip()
        if title:
            return _truncate(title)

    raw = (first_user_message or "").strip()
    is_subagent = bool(parent_session_id) or (agent_type and agent_type != "(main)")
    if is_subagent:
        desc = (subagent_description or "").strip()
        if desc:
            return _truncate(f"{agent_type or 'subagent'}: {desc}")
        return _truncate(f"subagent: {agent_type or 'unknown'}")

    if not raw:
        return "(no title)"

    slash = _extract_slash_command(raw)
    if slash:
        return _truncate(slash)

    # Free-text path: strip any leftover tags, take first sentence.
    text = _TAG_RE.sub(" ", raw)
    text = _WS_RE.sub(" ", text).strip()
    if not text:
        return "(no title)"
    sentence = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
    sentence = _LEADING_NOISE_RE.sub("", sentence).strip()
    return _truncate(sentence) if sentence else "(no title)"


def _extract_slash_command(raw: str) -> str | None:
    """If the message is a slash-command invocation, return '/<cmd> [args]'.

    Claude Code wraps slash commands as:
      <command-message>plugin:cmd</command-message>
      <command-name>/plugin:cmd</command-name>
      <command-args>...</command-args>
    """
    name_m = _COMMAND_NAME_RE.search(raw)
    msg_m = _COMMAND_MSG_RE.search(raw)
    if not (name_m or msg_m):
        return None
    name = (name_m.group(1) if name_m else msg_m.group(1)).strip()
    # Drop a leading namespace 'unknown:' or duplicate plugin prefix.
    name = name.removeprefix("unknown:")
    args_m = _COMMAND_ARGS_RE.search(raw)
    args = (args_m.group(1).strip() if args_m else "")
    return f"/{name} {args}".strip()


def _truncate(s: str) -> str:
    if len(s) <= MAX_LEN:
        return s
    return s[: MAX_LEN - 1].rstrip() + "…"
