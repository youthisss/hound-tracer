---
command: "/hound:insights"
description: "Inspect historical test stability, flakiness rate, and duration percentiles."
usage: "/hound:insights [test-name]"
---

# Hound Insights Command

Follow host permissions and prefer connected MCP or native CI/history tools. CLI examples are optional. If no history source is available, report insufficient evidence rather than requiring a Hound install or inventing flakiness statistics.

When the user runs `/hound:insights [test-name]`:

1. If a test name is provided:
   ```bash
   hound insights stats --test "<test-name>" --window-days 30
   ```
   Or invoke the MCP tool `hound_get_insights(action="stats", test_name="<test-name>")`.
2. If no test name is provided, list tracked tests:
   ```bash
   hound insights tests --window-days 30
   ```
   Or invoke the MCP tool `hound_get_insights(action="tests")`.
3. Present failure rates, flakiness suspicion, and p95 duration metrics.
