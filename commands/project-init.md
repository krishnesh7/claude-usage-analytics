---
description: Register the current directory as a tracked project (auto-detects worktrees). Usage:/project-init <project-name>
allowed-tools: Bash
argument-hint: "<project-name>"
---

!${CLAUDE_PLUGIN_ROOT}/bin/cu project init "$1" --root "$PWD"
