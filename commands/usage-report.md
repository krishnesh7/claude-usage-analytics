---
description: Generate a self-contained HTML usage report for the current project (all time).
allowed-tools: Bash
---

!${CLAUDE_PLUGIN_ROOT}/bin/cu parse >/dev/null 2>&1; ${CLAUDE_PLUGIN_ROOT}/bin/cu classify >/dev/null 2>&1; ${CLAUDE_PLUGIN_ROOT}/bin/cu report --project "$(basename "$PWD")" --since all --out "./claude-usage-report-$(date +%Y%m%d-%H%M).html"
