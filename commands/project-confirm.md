---
description: Show which project this session is tagged to, and re-run project resolution for the current directory. Use this if the session-start hook tagged the wrong project.
allowed-tools: Bash
---

Show the current session's project assignment and confidence, then offer to correct it if needed.

Run the following and present the results clearly:

```bash
CU=${CLAUDE_PLUGIN_ROOT}/bin/cu

# Resolve the current directory
echo "=== Project resolution for: $(pwd) ===" && \
$CU session-resolve --cwd "$(pwd)"
```

After showing the output, explain:
- **EXACT/SUBDIR/WORKTREE** — correctly auto-tagged, no action needed
- **FUZZY** — loosely matched; ask: "Is this correct? If not, which registered project should it be?" Then run: `$CU project tag --session $CLAUDE_SESSION_ID --name <correct-name>`
- **AMBIGUOUS** — multiple matches; ask: "Which of these projects does this session belong to?" Then run: `$CU project tag --session $CLAUDE_SESSION_ID --name <chosen-name>`
- **UNMATCHED** — ask: "What project is this session for?" Options:
  1. Tag an existing project: `$CU project tag --session $CLAUDE_SESSION_ID --name <name>`
  2. Register & tag a new one: run `cu project init <name>` in the terminal, then tag

Also show registered projects with: `$CU project list`
