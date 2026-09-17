# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.7.1] - 2026-09-17

### Added
- Added `hound run` for bounded project-command execution, manifest-based command
  suggestions, redacted capture, artifact discovery, persistent run records, and
  optional immediate analysis.

### Changed
- Shared project-command discovery between the CLI and TUI.

## [0.7.0] - 2026-09-17

### Added
- Expanded the bounded MCP engine with report reading and validation, offline
  evaluation, test-history transfer, feedback operations, resources, prompts,
  capability classes, stable envelopes, and stricter input validation.
- Added shared diagnostic-engine guidance and packaged integration assets for
  OpenCode, Hermes Agent, Codex, Cursor, Antigravity, and Claude-compatible
  plugin workflows.
- Added a dedicated Python 3.13 CLI and TUI workflow alongside the compatibility
  matrix.

### Changed
- Reworked the README around fast installation, real report evidence, common
  workflows, progressive disclosure, and focused documentation links.
- Extended supported runtimes to CPython 3.13 and made TUI button rendering
  compatible with newer Textual content labels.
- Upgraded GitHub workflow actions to Node.js 24-compatible releases and disabled
  Trivy's legacy transitive Node.js 20 cache action.
- Made integration installation copy complete skill asset trees, including
  report, security, native fallback, and tool references.

### Security
- Added MCP capability levels for read-only, diagnostic, write, and execute
  operations, with explicit filesystem roots and command-execution opt-in.

## [0.6.0] - 2026-09-17

### Added
- An interactive launcher for choosing the terminal UI, persistent command line,
  or local HTTP API when `hound` runs without a subcommand.
- A persistent Rich command session with completion, history, status, and help.
- Project workspaces under `.hound` for captured logs, discovered artifacts,
  project-run records, analysis results, and local state.
- TUI project command execution with explicit confirmation, a five-minute default
  timeout, process-tree cancellation, redacted bounded capture, and run history.
- Recursive artifact discovery for logs, JUnit XML, SARIF, and supported JSON test
  reports while excluding dependency, cache, generated-result, state, and symlinked paths.
- Explicit-risk subscription authentication adapters for the official Codex, Claude,
  and Gemini CLIs, plus custom OpenAI-compatible and Anthropic-compatible providers.

### Changed
- Bare `hound` now opens the interface launcher instead of starting the TUI directly.
- `hound init` now creates an idempotent project configuration and `.hound` workspace.
- `hound analyze` and `hound log` use initialized workspace paths by default.
- Human-facing TTY output now uses shared Rich panels and tables while JSON and
  redirected text output retain machine-readable formats.
- The TUI class is named `HoundTui`; `RcaTui` remains available as a compatibility alias.
- The MCP server identity and version output now use the `hound-tracer` and
  `Hound Tracer` product names.

### Security
- Project commands run without a shell and use bounded capture, argument and output
  redaction, timeout enforcement, process-tree cancellation, and non-symlink state paths.
- Project command execution remains unsandboxed and retains the Hound process permissions;
  the threat model now documents this boundary.

## [0.5.2] - 2026-09-12

### Added
- A first-run integration prompt and `hound integrations` installer for detecting
  coding harnesses, installing the packaged Hound skill, configuring OpenCode and
  Cursor MCP access, and installing the Claude plugin bundle.
- A dedicated `hound-mcp` executable for MCP clients using an isolated `uv tool`
  installation.
- Explicit delivery, incident, and authenticated server-client administration
  commands, including reconciliation, verified-absence failure marking, retry of
  known failures, job polling, and cancellation.
- A runtime/support matrix and bounded-operation limits documenting tested
  platform boundaries, local Docker limitations, and external release gates.
- Persistence hardening for symlinked/corrupt feedback and history stores, plus
  idempotent QA-history imports and URL-boundary regression coverage.
- Diagnostic regression quality gates for PR CI, including healthy-log false-positive
  rate, failure detection recall, and explicit sample-support thresholds.
- Synthetic adversarial corpus cases and IPv6 redaction coverage.
- Standard Open Source documentation: `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md`.
- Issue and PR templates for GitHub.
- Comprehensive distribution and production maturity roadmap.

### Changed
- Clarified the advisory scope of root-cause hypotheses, pattern-based privacy
  limits, and the distinction between synthetic regression metrics and pilot evidence.
- Corrected TUI surface documentation and acceptance status: QA history import is
  a bounded local write, active gate rules are previewed before execution, and
  Context validates stored report readiness as a read-only surface rather than
  acting as an interactive connector workflow.
- Reorganized the package into `src/hound`, grouped tests by runtime boundary,
  and grouped documentation under purpose-specific directories.
- Refreshed README navigation and added a documentation hub.
- Made canonical CLI command and option spellings primary while retaining legacy
  spellings as compatibility aliases.
- Renamed the distribution, import package, persisted paths, generated filenames,
  container/action identity, and public URLs to Hound. This is a breaking rename;
  legacy Python imports and distribution names are not provided.

## [0.5.1] - 2026-09-11

### Added
- **Multi-Harness Integration Examples**: Added configuration templates in `integrations/` for OpenCode V2, Hermes Agent, Claude Code, Codex, Cursor, and Antigravity to simplify workspace-scoped MCP and skill setup.
- **Safe Update Command**: Added `/hound:update` reference command specification and OpenCode `hound-update` command template to inspect Hound installations and prepare confirmed updates without altering uncommitted repositories.
- **Harness Integration Test Suite**: Added `tests/unit/test_harness_integrations.py` validating syntax, command references, and structure of all integration configs.

## [0.5.0] - 2026-09-11

### Added
- **Model Context Protocol (MCP) Server**: Added stdio JSON-RPC 2.0 server (`hound mcp`) exposing linear diagnostic tools: `hound_analyze`, `hound_log_command`, `hound_check_gate`, `hound_get_insights`, `hound_doctor`, and `hound_list_incidents` with bounded outputs, path confinement (`HOUND_MCP_ROOTS`), and explicit administrator opt-in for command execution (`HOUND_MCP_ALLOW_COMMANDS`).
- **Coding Agent Plugin Bundle**: Added `plugins/hound/` manifest, slash commands (`/hound-analyze`, `/hound-doctor`, `/hound-gate`, `/hound-incidents`, `/hound-insights`, `/hound-run`), and a failure triage hook (`post_test_failure.py`).
- **Coding Agent Skill**: Added `skills/hound-tracer/SKILL.md` providing step-by-step diagnostic workflows, triage playbooks, and evidence requirements for autonomous coding agents.
- **Command Collection Timeout**: Added `timeout` and `CollectionTimeoutError` to `hound.collector.collect_command` for bounding long-running commands while preserving partial redacted logs.

### Fixed
- **TUI Artifact Selection**: In `ArtifactListView`, mouse clicks toggle artifact selection and update raw log preview without triggering premature batch analysis.

## [0.4.1] - 2026-09-11

### Added
- **Configuration Flexibility**: Enhanced `hound config set` to configure both `provider` and `model` explicitly (`set_llm_config_value`).
- **Interactive TUI Enhancements**:
  - Live progress animation and responsive workflow status in the sidebar.
  - Left/right arrow navigation to cycle through results workspace tabs.
  - Symmetrical spacing and layout alignment for context and connector summaries.
  - Dedicated stop-analysis keybinding (`x` / `ctrl+x`) and dynamic shortcut bar indication.
  - Direct artifact analysis from focused item via `Enter` key.
  - Dedicated Back button (`<--`) behavior and modal screen dismissal with `Escape`.

### Changed
- Clarified CLI `analyze` and `batch` help strings for supported artifact files and recursive directory scanning.
- Streamlined QA and Results workspace filters and test history list display.

## [0.4.0] - 2026-08-07

### Added
- **Dynamic Packaging & Canonical CLI Aliases**: Added dynamic Hatch version resolution, canonical CLI subcommands (`insights`, `gate`, `console`, `serve`, `providers`, `runs`), and `--output-dir` / `--repo-dir` options.
- **Strict Configuration Validation**: Added `hound config validate` command with fuzzy key suggestion and `--warn-only` mode.
- **Persistent Delivery Ledger & Bounded Telemetry (M12)**: Added SQLite-backed idempotent delivery ledger with ambiguous-outcome recovery and process-local zero-payload telemetry registry.
- **Known-Issue Matching & LLM Preview (M3 Addendum)**: Added pre-LLM fingerprint resolution against reviewed feedback and `--llm-preview` dry-run export.
- **QA Enrichment & General Severity Policy**: Added CODEOWNERS and related incident feedback correlation to QA classifications and `critical_severity` / `high_severity` policy rules in quality gate.
- **Multi-Provider LLM Engine**: Native support for OpenAI, Anthropic Claude, Google Gemini, Groq, Ollama, DeepSeek, Azure OpenAI, and custom OpenAI-compatible endpoints.
- **Interactive Terminal UI (TUI)**: Built with Textual for interactive log browsing, triage filtering, live log inspection, and configuration settings.
- **Log Stream Capture & Tee (`hound log`)**: Intercept and tee child processes with automatic sidecar metadata and immediate analysis on failure.
- **QA History & Flakiness Tracking (`hound insights`)**: Queryable SQLite database for test runs across branches and commits, tracking duration regressions and intermittent failures.
- **High-Throughput Batch Processing (`hound batch`)**: Parallel log analysis with explicit spending guardrails (`--max-cost-usd`, `--max-llm-calls`) and SQLite WAL deduplication.
- **HTTP Server / Webhook Receiver (`hound serve`)**: Lightweight stdlib-based webhook receiver with Bearer token authentication and persistent SQLite job queue.
- **Smart Privacy & Redaction**: Automated pre-analysis scrubbing for API tokens, passwords, private keys, JWTs, and sensitive connection strings.
- **Structured Test Ingestion**: Native parsing for JUnit XML, SARIF, and JSON test outputs without heuristic regex degradation.
- **Docker & GitHub Action Integration**: Ready-to-use Dockerfile and `action.yml` for automated failure investigation in CI/CD pipelines.
