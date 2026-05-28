"""Display-side secret redaction for prompt/text fields.

The SQLite DB stores user-typed prompts verbatim (truncated). Anything pasted
into a Claude session — accidentally or intentionally — is in our `sessions`,
`prompt_costs`, and `cache_breaks` tables. The real disclosure risk is when
that content escapes the local machine via:
  • the dashboard (binds to 127.0.0.1, so safe-by-default — but anyone on the
    box can read it)
  • CLAUDE_USAGE.md committed to a git repo (the genuine leak vector)

This module redacts known secret patterns before content reaches either of
those surfaces. The DB itself is unchanged; redaction is read-time.

Mode is controlled by the CU_REDACT_PROMPTS env var:
  • 'mask'  (default) — replace matches with '[REDACTED-<kind>]'
  • 'hash'           — replace entire text with sha256(text)[:12]
  • 'off'            — pass-through (only choose this on a single-user box you
                       fully control)
"""
from __future__ import annotations

import hashlib
import os
import re

MODE = os.environ.get("CU_REDACT_PROMPTS", "mask").lower()

# Each entry: (label, compiled_pattern). Order matters — more-specific first
# so a generic "bearer .*" doesn't gobble a longer-matching specific token.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("anthropic-key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{40,}")),
    ("openai-key",    re.compile(r"sk-(?!ant-)[A-Za-z0-9]{20,}")),
    ("slack-token",   re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("github-token",  re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("aws-access-id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("aws-secret",    re.compile(r"(?i)(?:aws_secret_access_key|aws_secret)\s*[=:]\s*['\"]?([A-Za-z0-9/+=]{40})['\"]?")),
    ("private-key",   re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP |ENCRYPTED )?PRIVATE KEY-----[\s\S]+?-----END (?:RSA |EC |OPENSSH |DSA |PGP |ENCRYPTED )?PRIVATE KEY-----")),
    ("jwt",           re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")),
    ("bearer-token",  re.compile(r"(?i)\bbearer\s+[A-Za-z0-9_.\-=+/]{20,}")),
    # Generic kv pattern — runs last and only matches assignments with quotes
    # or =/: separators to keep false positives low.
    ("kv-secret",     re.compile(r"(?i)\b(?:password|passwd|pwd|api[_-]?key|secret|token|access[_-]?key)\s*[=:]\s*['\"]([^'\"\s]{8,})['\"]")),
]


def redact(text: str | None) -> str | None:
    """Apply redaction per the CU_REDACT_PROMPTS mode.

    Returns the input unchanged when text is None/empty or mode is 'off'.
    """
    if text is None or text == "":
        return text
    if MODE == "off":
        return text
    if MODE == "hash":
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        return f"[HASHED-{h}]"

    out = text
    for label, pat in _PATTERNS:
        out = pat.sub(f"[REDACTED-{label}]", out)
    return out


def redact_row(row: dict, fields: tuple[str, ...]) -> dict:
    """In-place redact selected string fields of a row dict. Returns the row."""
    for f in fields:
        if f in row and isinstance(row[f], str):
            row[f] = redact(row[f])
    return row
