---
description: Re-run the offline parser and stage classifier (use after a long session to refresh the DB).
allowed-tools: Bash
---

!${CLAUDE_PLUGIN_ROOT}/bin/cu parse && ${CLAUDE_PLUGIN_ROOT}/bin/cu classify
