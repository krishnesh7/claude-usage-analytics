---
description: Write or refresh docs/CLAUDE_USAGE.md in the current project directory.
allowed-tools: Bash
---

!${CLAUDE_PLUGIN_ROOT}/bin/cu parse >/dev/null 2>&1; ${CLAUDE_PLUGIN_ROOT}/bin/cu classify >/dev/null 2>&1; ${CLAUDE_PLUGIN_ROOT}/bin/cu doc --project "$PWD"
