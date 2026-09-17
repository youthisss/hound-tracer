---
command: "/hound:doctor"
description: "Verify local environment readiness for Hound Tracer without exposing sensitive data."
usage: "/hound:doctor"
---

# Hound Doctor Command

Prefer connected `hound_doctor`. The CLI below is optional; if Hound is absent, inspect only the available harness/runtime capabilities and identify the missing engine connection. Do not install Hound or open its TUI as a prerequisite for other diagnostic workflows.

When the user runs `/hound:doctor`:

1. Run:
   ```bash
   hound doctor --json
   ```
   Or invoke the MCP tool `hound_doctor()`.
2. Inspect readiness checks: Python compatibility, Hound installation, config integrity, write permissions, and CLI tools (`git`, `docker`, `kubectl`).
3. Summarize any missing requirements.
