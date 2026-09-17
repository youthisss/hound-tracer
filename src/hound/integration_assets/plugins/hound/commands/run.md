---
command: "/hound:run"
description: "Execute a command under Hound's secret-scrubbing collector, auto-analyzing failures."
usage: "/hound:run <command...>"
---

# Hound Run Command

Follow the host harness's execution policy. Prefer connected MCP or its authorized native test runner; the Hound CLI below is optional. Native execution does not imply Hound redaction or automatic RCA. If execution is unavailable, report verification as not run.

When the user runs `/hound:run <command...>`:

1. Wrap and run the command with Hound collector:
   ```bash
   hound log --analyze --offline -- <command...>
   ```
   Or invoke the MCP tool `hound_log_command(command=["..."])`.
2. Inspect `exit_code` and `timed_out` in the MCP payload; `isError=false` only means the tool call completed. If the command exits with `0`, report success.
3. If the command exits with a non-zero status code:
    - Use the returned `analysis` and its `raw_output_dir` to locate `report.json`. On timeout, use `log_file` for a separate offline analysis; do not rerun the command automatically.
    - Present the primary error event, failing assertions, and recommended fix.
4. If MCP execution is disabled, respect the harness command permission policy. Do not enable it or switch to shell to bypass a denied execution request.
