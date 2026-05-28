---
description: Manually override the SDLC stage for this session. Usage:/stage <requirements|design|impl|test|deploy|adhoc>
allowed-tools: Bash
argument-hint: "<stage>"
---

!${CLAUDE_PLUGIN_ROOT}/bin/cu stage --session "${CLAUDE_SESSION_ID:-unknown}" --set "$1"
