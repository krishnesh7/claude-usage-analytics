---
description: Show token usage and imputed $ cost for the current project (last 7 days).
allowed-tools: Bash
---

!${CLAUDE_PLUGIN_ROOT}/bin/cu parse >/dev/null 2>&1; ${CLAUDE_PLUGIN_ROOT}/bin/cu classify >/dev/null 2>&1; ${CLAUDE_PLUGIN_ROOT}/bin/cu summary --project "$(basename "$PWD")" --since 7d
