---
command: "/hound:analyze"
description: "Diagnose a failure log, JUnit XML, or directory of artifacts using Hound Tracer."
usage: "/hound:analyze [artifact-path]"
---

# Hound Analyze Command

Follow the host harness's rules and discovered tools. Hound CLI examples are optional. Without an engine backend, inspect bounded evidence using native tools and label the diagnosis native/advisory; no Hound report is required. Never launch the TUI or install Hound just to use this prompt.

When the user runs `/hound:analyze [artifact-path]`:

1. If `[artifact-path]` is omitted, check the default output directory (`hound-output/`), `.hound/logs/`, or ask the user which log/report file to diagnose.
2. If MCP tools are available:
   - Call `hound_analyze(artifact_path="<path>", offline=True)`.
3. Otherwise, execute via shell:
   ```bash
   hound analyze "<path>" --offline --output-dir .hound-run
   ```
4. For MCP, use the returned diagnostic fields and `raw_output_dir`; for CLI, read `.hound-run/report.json`. Directory analysis returns multiple runs, so report each distinct failure and use its run directory rather than assuming a root report exists.
5. Confirm the cited source location before proposing edits. After a fix, rerun the affected test/build and report its actual exit status.
