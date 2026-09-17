---
command: "/hound:engine"
description: "Use Hound's shared diagnostic engine through the host harness's connected tools."
usage: "/hound:engine <goal and evidence paths>"
---

# Hound Engine

Follow the host harness's instructions, tool discovery, permissions, and response format. This command is a portable workflow prompt; adapters may rename its slash command. Do not launch the Hound CLI or TUI as a prerequisite.

Discover connected Hound MCP tools and choose the smallest workflow matching the user's goal:

| Goal | Engine tools |
|---|---|
| RCA, parsing, redaction, triage, ticket drafting | `hound_analyze` |
| Source context, ownership, test impact | `hound_analyze` with `repo_dir` and `source_context=true` |
| Deployment timeline and correlation | `hound_analyze` with operator-supplied `context_path`; enrichment only when requested and configured |
| Capture a test/build failure | `hound_log_command` |
| Coverage, SARIF, regression policy | `hound_check_gate` |
| History and incident recurrence | `hound_get_insights`, `hound_list_incidents` |
| History interchange | `hound_history_import`, `hound_history_export` |
| Inspect full engine output or one section | `hound_read_report` |
| Audit report integrity | `hound_validate_report` |
| Diagnostic feedback | `hound_feedback_list`, `hound_feedback_record` |
| Regression corpus evaluation | `hound_evaluate` |
| Engine readiness | `hound_doctor` |

Use discovered JSON schemas, not guessed arguments. Paths refer to the MCP server filesystem. Read `sections` from `hound_read_report` before requesting an unfamiliar section. Large results are bounded; retrieve the needed section rather than repeating the full report.

Report the engine outcome, evidence, artifact locations, and actual verification status. Tool success does not mean test/gate success. If MCP is unavailable, continue with permitted native evidence inspection and clearly label it native/advisory; do not claim the engine ran. An already installed CLI is optional if permitted by the harness. Never bypass a denied action by switching backends.
