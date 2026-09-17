---
name: hound-tracer
description: Offline-first diagnostic, RCA (Root Cause Analysis), and quality gate agent for CI/CD, build, test, and container failures.
version: 0.6.0
license: MIT
slash: true
metadata:
  opencode/slash: true
  hermes:
    tags: [ci-cd, diagnostics, testing, quality-gate]
triggers:
  - CI/CD pipeline failure (GitHub Actions, GitLab CI, Jenkins, Argo)
  - Test runner failure (pytest, jest, vitest, go test, cargo test, maven, dotnet test)
  - Build or compilation failure (webpack, tsc, cargo build, go build, pip conflict)
  - Container or Kubernetes crash (CrashLoopBackOff, OOMKilled exit 137, failed readiness probe)
  - Quality gate check or flakiness audit before PR merge
---

# Hound Tracer Diagnostic Skill

Use this skill when diagnosing build errors, failed test suites, crashed deployments, or evaluating quality gates. Hound analyzes raw execution logs, JUnit XML, and SARIF reports offline, extracts framed stacktraces, scrubs secrets automatically, and produces structured Root Cause Analysis (Schema v2.0).

---

## 1. Golden Rules for AI Coding Agents

1. **Never read raw multi-megabyte log files directly into context:**
   Always run Hound first to ingest, window, redact, and parse the failure. Read `hound-output/report.json` instead of raw `.log` files.
2. **Default to `--offline` mode:**
   You (the coding agent) are already the LLM. Do not consume external LLM provider quota or network calls. Hound's deterministic fallback rules extract precise stacktraces, failure kinds, and evidence offline.
3. **Strict Secret Redaction:**
   Hound automatically sanitizes credentials, tokens, passwords, private keys, emails, and IP addresses. Never bypass redaction.
4. **Actionable Remediation:**
   Map the extracted `stacktrace` and `failed_tests` directly to local workspace files, inspect the exact lines with your code editor tools, and apply code-first fixes.
5. **Verify Before Editing:**
   Treat Hound hypotheses as diagnostic proposals. Confirm the cited evidence and workspace location before changing code, especially when confidence is low.
6. **Respect MCP Permissions:**
   MCP paths are restricted to `HOUND_MCP_ROOTS`. Command execution is disabled unless the MCP administrator explicitly sets `HOUND_MCP_ENABLE_COMMAND_EXECUTION=1`.

---

## 2. Environment Verification & Executable Resolution

Always resolve the Hound command in this priority order:

1. **Native MCP Tools (Preferred when MCP server is connected):**
   Use `hound_analyze`, `hound_log_command`, `hound_check_gate`, `hound_get_insights`, `hound_doctor`, or `hound_list_incidents`.
2. **Local Virtual Environment Binary (if `.venv` exists in the repository):**
   - Linux/macOS: `./.venv/bin/hound` or `venv/bin/hound`
   - Windows: `.\.venv\Scripts\hound.exe`
3. **Module Invocation with Active Python:**
   `python -m hound.cli <command...>`
4. **Global System Binary:**
   `hound <command...>`
5. **On-Demand Runner (if uv is available):**
   `uvx hound-tracer <command...>`

---

## 3. Core Workflows

### Workflow A: Diagnose an Existing Failure Artifact (.log, .xml, .sarif)
When a log file or test result file is available:

```bash
# Analyze a single failure log or JUnit XML
hound analyze <path/to/failure.log> --offline --output-dir .hound-run

# Or inspect a whole directory of artifacts
hound analyze <path/to/artifacts_dir> --offline --output-dir .hound-run
```

**Next step:** Read `.hound-run/report.json`.

---

### Workflow B: Run and Intercept a Failing Test or Build Command
When a command is failing in the terminal and you need to capture and diagnose it cleanly:

```bash
# Executes command, tees output, auto-redacts secrets, and runs offline RCA on failure:
hound log --analyze --offline --output-dir .hound-run -- <command...>

# Examples:
hound log --analyze --offline -- pytest tests/
hound log --analyze --offline -- npm test
hound log --analyze --offline -- cargo test
```

---

### Workflow C: Evaluate Quality Gate Before PR or Commit
Before committing code or submitting a PR, verify test impact and quality gate policies:

```bash
hound gate <test-results.xml> \
  --baseline-ref origin/main \
  --candidate-ref HEAD \
  --repo-dir . \
  --policy .hound/gate-policy.yml
```

**Exit Codes:**
- `0`: Passed or acceptable warning.
- `1`: Blocked by policy (coverage dropped, high-severity CVE, or regressions).
- `2`: Invalid input or malformed policy.

---

### Workflow D: Investigate Flaky Tests
When a test fails intermittently or needs history inspection:

```bash
# Query failure rate and duration percentiles (p95)
hound insights stats --test "<test_file.py::test_func>" --window-days 30

# List recent execution history
hound insights history --test "<test_file.py::test_func>" --limit 10
```

---

## 4. Interpreting `report.json` (Schema v2.0)

When inspecting `.hound-run/report.json`, focus on these fields:

```json
{
  "failure": {
    "stage": "build | test | deploy | ci",
    "kind": "compilation_error | test_failure | oom_killed | import_error | ...",
    "summary": "High-level one-line summary",
    "message": "Specific assertion or crash message",
    "stacktrace": [
      {
        "file": "path/to/file.py",
        "line": 42,
        "function": "function_name",
        "code": "assert actual == expected"
      }
    ],
    "failed_tests": [
      {
        "name": "tests/test_api.py::test_login",
        "file": "tests/test_api.py",
        "assertion": "Status code 401 != 200"
      }
    ]
  },
  "root_cause": {
    "hypothesis": "Concrete explanation of why the failure occurred",
    "confidence": "high | medium | low",
    "evidence": ["ev-001: ...", "ev-002: ..."],
    "fix_suggestion": "Prescriptive remediation step"
  },
  "triage": {
    "severity": "critical | high | medium | low",
    "component": "affected module / directory",
    "dedup_key": "incident-v2:sha256_hash",
    "flaky_suspect": false
  }
}
```

---

## 5. Standard Agent Response Format

After analyzing an incident with Hound Tracer, summarize your findings to the user using this 4-section layout:

```markdown
### 1. Root Cause Summary
- **Stage & Kind:** [e.g. `test` / `test_failure` or `deploy` / `oom_killed`]
- **Hypothesis:** [Brief, precise description from `root_cause.hypothesis`]
- **Severity & Component:** [e.g. `high` | `services/auth`]

### 2. Evidence & Locations
- **Failing Location:** `<file>:<line>`
- **Failing Assertion / Error:** `<message>`

### 3. Recommended Fix
[Specific code-level change to address the issue]

### 4. Verification Step
[Exact test command to run and verify the fix]
```
