---
name: vs-session-report
description: >
  Use when the user asks how claude-usage-tracker differs from the official
  session-report plugin, asks "why should I use this instead of session-report",
  asks what features are unique to this plugin, or wants to understand which
  plugin to use for a given task.
---

Display the full feature comparison between claude-usage-tracker and the official
session-report plugin.

Run the following command and render the output as formatted Markdown:

```bash
cat "${CLAUDE_PLUGIN_ROOT}/docs/COMPARISON.md"
```

After displaying it, summarise the three most relevant differences for the user's
specific situation:

- If they mentioned **cost / money / dollars** → lead with cost imputation +
  persistent history
- If they mentioned **project / product** → lead with named project registry +
  CLAUDE_USAGE.md
- If they mentioned **history / all time / last month** → lead with SQLite
  persistence + unlimited time window
- If they mentioned **cache** → lead with the enrichment pipeline section
- Default → lead with the at-a-glance table and the "when to use which" section

Do not recommend removing session-report — the two plugins are complementary.
