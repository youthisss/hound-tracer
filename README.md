<div align="center">

<pre>
██╗  ██╗  ██████╗  ██╗   ██╗ ███╗   ██╗ ██████╗         ████████╗ ██████╗   █████╗    ██████╗  ███████╗ ██████╗
██║  ██║ ██╔═══██╗ ██║   ██║ ████╗  ██║ ██╔══██╗        ╚══██╔══╝ ██╔══██╗ ██╔══██╗  ██╔════╝  ██╔════╝ ██╔══██╗
███████║ ██║   ██║ ██║   ██║ ██╔██╗ ██║ ██║  ██║ █████╗    ██║    ██████╔╝ ███████║  ██║       █████╗   ██████╔╝
██╔══██║ ██║   ██║ ██║   ██║ ██║╚██╗██║ ██║  ██║ ╚════╝    ██║    ██╔══██╗ ██╔══██║  ██║       ██╔══╝   ██╔══██╗
██║  ██║ ╚██████╔╝ ╚██████╔╝ ██║ ╚████║ ██████╔╝           ██║    ██║  ██║ ██║  ██║  ╚██████╗  ███████╗ ██║  ██║
╚═╝  ╚═╝  ╚═════╝   ╚═════╝  ╚═╝  ╚═══╝ ╚═════╝            ╚═╝    ╚═╝  ╚═╝ ╚═╝  ╚═╝   ╚═════╝  ╚══════╝ ╚═╝  ╚═╝
</pre>

# Hound Tracer

**Turn failed builds, tests, deployments, and containers into evidence-backed root-cause reports.**

[![PyPI](https://img.shields.io/pypi/v/hound-tracer.svg)](https://pypi.org/project/hound-tracer/)
[![Python](https://img.shields.io/badge/Python-3.10%20to%203.13-blue.svg)](pyproject.toml)
[![Status](https://img.shields.io/badge/status-beta-yellow.svg)](#project-status)
[![Security](https://img.shields.io/badge/redaction-default-orange.svg)](#security-boundary)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

[Install](#install) · [Quick start](#quick-start) · [Workflows](#common-workflows) · [Interfaces](#interfaces) · [Documentation](#documentation)

</div>

Hound Tracer converts raw failure evidence into a structured investigation: failure classification, cited evidence, root-cause hypotheses, triage, recommended checks, and a reviewable ticket draft. It reads plain logs, JUnit XML, SARIF, and supported test-report JSON.

The deterministic engine works offline. LLM analysis, repository source context, deployment enrichment, and external ticket delivery are separate capabilities that you enable explicitly.

| What Hound does | What that gives you |
|---|---|
| Frames stack traces and failed tests | A focused failure record instead of another raw log stream |
| Cites supporting and contradicting evidence | A diagnosis that can be checked against the source artifact |
| Redacts recognized secrets and PII by default | Safer reports, prompts, state snapshots, and delivery payloads |
| Fingerprints recurring incidents | Recurrence counts and optional reuse of reviewed RCA snapshots |
| Tracks test history, coverage, and SARIF | Flakiness, duration regressions, and versioned quality gates |
| Exposes CLI, TUI, HTTP, GitHub Action, and MCP surfaces | One analysis pipeline across local, CI, service, and coding-agent workflows |

> [!IMPORTANT]
> Hound is advisory. It does not deploy, retry, roll back, or edit infrastructure. Features that explicitly run commands execute operator-selected, checkout-controlled code with the Hound process permissions. They are not a sandbox.

## See the result

This excerpt comes from an offline report generated from a failing Cargo test in [`demo-output`](demo-output/):

```text
Failure
  Stage: test
  Kind: test_failure
  Summary: test totals::adds_tax ... FAILED

Root cause
  Hypothesis: Test assertion failed; the code under test diverges from expectations.
  Confidence: medium
  Evidence score: 0.75
  Support status: supported

Evidence
  Failed test: totals::adds_tax
  Location: src/totals.rs:13
  Assertion: left 10, right 11

Triage
  Severity: medium
  Component: src
  Priority: 3
```

Each analysis writes:

```text
run-<id>/
├── report.json   # RCA Document Schema v2.0 for automation
├── report.md     # investigation for humans
└── ticket.md     # reviewable issue draft
```

The complete contract includes evidence provenance, hypotheses, missing information, recommended checks, timeline data, source impact, recurrence, engine status, fallback reason, and cost information. See the [architecture guide](docs/architecture.md) and [RCA JSON Schema](docs/schema/rca-v2.0.schema.json).

## How it works

```text
Failure evidence
  .log · JUnit XML · SARIF · supported test-report JSON
       │
       ▼
Ingest
  bounded reads · stack framing · test parsing · redaction
       │
       ▼
Context, when enabled
  Git diff/blame · CODEOWNERS · source lines · deployment signals
       │
       ▼
Root-cause analysis
  reviewed cache → optional LLM → deterministic fallback
  schema validation · evidence-reference validation · budgets
       │
       ▼
Triage and output
  severity · component · fingerprint · recurrence · ticket draft
```

The CLI, TUI, HTTP service, GitHub Action, and MCP server call the same application service and analysis pipeline.

## Install

Hound supports CPython `>=3.10,<3.14`. Windows and Linux are tested. macOS is expected to be portable, but release-runner evidence is still pending. See the [support matrix](docs/support-matrix.md).

### uv tool, recommended

```sh
uv tool install hound-tracer
hound --version
hound doctor
```

### pipx or pip

```sh
pipx install hound-tracer

# Or inside an existing Python environment
python -m pip install hound-tracer
```

### Source checkout

```sh
git clone https://github.com/youthisss/hound-tracer.git
cd hound-tracer
uv sync --extra dev
uv run hound doctor
```

Installed entry points:

- `hound` opens the launcher or runs a CLI command.
- `hound-mcp` starts the stdio MCP server for coding-agent clients.

## Quick start

### Analyze an existing failure

```sh
hound analyze failure.log --offline
```

Hound writes `report.json`, `report.md`, and `ticket.md` under `hound-output/`. Offline mode makes no provider request.

### Capture and analyze a command

```sh
hound log --analyze --offline -- pytest -q
```

The command output is redacted while it is captured. Hound preserves the wrapped command's exit code and analyzes the capture when requested.

### Initialize a project workspace

```sh
hound init
hound doctor
hound analyze --offline
```

`hound init` creates `.hound.yml` and an idempotent `.hound/` workspace for artifacts, captures, project runs, results, and local state. An existing configuration is preserved.

> [!TIP]
> Use an explicit subcommand in automation. Bare `hound` requires an interactive TTY and opens the interface launcher.

## Common workflows

### Add source and Git evidence

```sh
hound analyze ./ci-logs \
  --repo-dir . \
  --source-context \
  --offline
```

Source context is opt-in and intended for trusted checkouts. It can add bounded snippets, diff context, blame, commit subjects, CODEOWNERS, and advisory test-impact information.

### Process a directory with bounded model usage

```sh
hound batch \
  --logs ./ci-logs \
  --output-dir ./batch-output \
  --jobs 8 \
  --max-llm-calls 50 \
  --max-cost-usd 5.00
```

When a call or cost budget is exhausted, remaining artifacts use deterministic fallback and record `budget_skipped`.

### Build test history and evaluate a quality gate

```sh
hound insights import ./junit.xml \
  --test-runner pytest \
  --branch main \
  --commit abc1234 \
  --environment "os=linux;python=3.11"

hound gate ./test-results \
  --repo-dir . \
  --baseline-ref origin/main \
  --candidate-ref HEAD \
  --policy ./quality-gate.yml \
  --coverage ./coverage/coverage.json \
  --sarif ./reports/semgrep.sarif \
  --output gate-results.json
```

The local SQLite history store tracks outcomes, durations, branches, commits, and environments. Gate policies can evaluate new failures, flakiness, coverage delta, changed-line coverage, severity, and SARIF findings.

### Run in GitHub Actions

```yaml
- name: Run tests
  id: tests
  continue-on-error: true
  run: pytest --junitxml=artifacts/junit.xml | tee artifacts/pytest.log

- name: Investigate failure
  if: steps.tests.outcome == 'failure'
  uses: youthisss/hound-tracer@v0.7.0
  with:
    log: artifacts/pytest.log
    repo: ${{ github.workspace }}
    out: ${{ github.workspace }}/hound-output
    offline: "true"

- name: Upload report
  if: steps.tests.outcome == 'failure'
  uses: actions/upload-artifact@v4
  with:
    name: hound-report
    path: hound-output/
```

Action paths must stay under `GITHUB_WORKSPACE`. The [GitHub Action guide](docs/guides/github-action.md) documents inputs, outputs, permissions, and upgrades.

### Run with Docker

```sh
docker build -t hound-tracer .
docker run --rm \
  -v "$PWD/ci-logs:/logs:ro" \
  -v "$PWD/hound-output:/out" \
  hound-tracer analyze /logs --output-dir /out --offline
```

The release image runs the main Hound process as a non-root user.

## Interfaces

| Interface | Start it | Intended use |
|---|---|---|
| Launcher | `hound` | Choose the TUI, persistent CLI, or local HTTP service |
| CLI | `hound analyze ...` | Scripts, CI, and direct artifact analysis |
| Persistent CLI | `hound cli` | Command completion, history, help, and repeated local work |
| Terminal UI | `hound console` | Browse artifacts, run projects, inspect reports, and review QA history |
| HTTP service | `hound serve` | Authenticated queued analysis behind a controlled reverse proxy |
| GitHub Action | `uses: youthisss/hound-tracer@v0.7.0` | Failure investigation in GitHub workflows |
| MCP server | `hound-mcp` or `hound mcp` | Bounded diagnostic tools for coding agents |

### Terminal UI

```sh
hound console --logs ./ci-logs --offline
```

The Textual UI has Home, Artifacts, Project Runs, Results, and Quality workspaces. Stored runs expose Overview, Report, Ticket, Context, and Raw log views. The **Run project** action requires confirmation and uses a bounded timeout and output capture, but the invoked project remains unsandboxed.

### HTTP service

```sh
export HOUND_SERVER_TOKEN="replace-with-a-long-random-token"

hound serve \
  --host 127.0.0.1 \
  --port 8123 \
  --log-root ./ci-logs \
  --output-dir ./server-runs
```

The service binds to loopback, uses Bearer authentication, and persists its queue in SQLite. It provides job submission, inspection, cancellation, health, readiness, and authenticated statistics endpoints. Put a controlled reverse proxy in front of it for TLS or remote ingress. See [server deployment](docs/guides/server-deployment.md).

### Coding agents and MCP

```sh
hound-mcp
```

The MCP surface exposes bounded tools for:

- artifact analysis and command capture;
- quality gates and test insights;
- incident and report inspection;
- report integrity validation;
- history transfer and engineer feedback;
- offline diagnostic evaluation.

`HOUND_MCP_ROOTS` confines filesystem access. `HOUND_MCP_MODE` selects `readonly`, `diagnostic`, `write`, or `execute` capability classes. Command execution also requires `HOUND_MCP_ENABLE_COMMAND_EXECUTION=1`.

Hound packages skills, plugin prompts, and MCP configuration for OpenCode V2, Hermes Agent, Claude Code, Codex, Cursor, and Antigravity:

```sh
hound install skill --for claude --scope global --yes
hound install mcp --for opencode --scope global --yes
hound install all --for claude --scope global --yes
```

The [engine surface matrix](docs/reference/engine-surface.md) shows what is exposed to agents and what remains internal. Harness-specific setup examples live under [`integrations/`](integrations/).

<details>
<summary><strong>Command index</strong></summary>

| Command | Purpose |
|---|---|
| `hound analyze` | Analyze one artifact or recursively analyze a directory |
| `hound batch` | Process artifacts with shared call and cost budgets |
| `hound log` | Capture a command or piped stdin and optionally analyze it |
| `hound console` | Open the Textual terminal UI |
| `hound cli` | Open the persistent Rich command session |
| `hound gate` | Evaluate tests, coverage, changed lines, and SARIF |
| `hound insights` | Import, export, classify, and query test history |
| `hound serve` / `hound client` | Operate the HTTP job service |
| `hound runs` / `hound report` | Inspect stored analyses |
| `hound incidents` | Inspect recurrence and invalidate cached RCA snapshots |
| `hound feedback` | Record reviews or export regression candidates |
| `hound delivery` | Inspect and recover delivery-ledger records |
| `hound providers` / `hound models` | Inspect provider presets and model catalogs |
| `hound auth` | Start an explicitly accepted provider CLI login |
| `hound config` / `hound doctor` | Configure and validate the local environment |
| `hound install` / `hound uninstall` | Manage Hound and harness integrations |
| `hound mcp` | Start the stdio MCP service |
| `hound clean` | Remove only Hound-owned output trees |

Run `hound <command> --help` for the authoritative options.

</details>

## Analysis contract

### Accepted evidence

| Input | Notes |
|---|---|
| `.log` | Build, test, CI, deployment, or container output |
| JUnit `.xml` | Suites, cases, failures, errors, skips, and durations |
| `.sarif` | SARIF 2.1.0 findings from supported producers |
| Test-report `.json` | Recognized structured reports in report-bearing paths |
| Piped stdin | Captured through `hound log --name <name>` |
| Git checkout | Optional diff, blame, commits, CODEOWNERS, source, and impact context |

Directory analysis is recursive. Hound prunes dependency trees, virtual environments, VCS metadata, generated results, state, common caches, and symlinked paths.

### Exit codes

| Code | Analysis meaning |
|---:|---|
| `0` | Analysis completed and no actionable failure was detected |
| `1` | Analysis completed and detected a failure |
| `2` | Invalid arguments, configuration, or input |
| `3` | Internal execution, I/O, or required delivery failure |

`hound log` normally preserves the wrapped command's exit code. A timeout uses `124`; cancellation uses `130`. Quality-gate exit codes are documented in [architecture](docs/architecture.md#qa-quality-gate).

### Supported failure areas

Hound classifies failures across build, test, CI, deployment, containers, Kubernetes, network, and TLS workflows. Stack framing covers Python, Go, Rust, Java, JavaScript and TypeScript V8 output, C and C++, C#, YAML, Terraform, and template locations. Test ingestion recognizes pytest, Jest, Vitest, Go test, RSpec, Cargo test, dotnet test, and JUnit XML.

Optional connectors collect bounded read-only Kubernetes, Helm, Prometheus, and Tempo-compatible evidence after explicit configuration and trust checks. See [deployment connectors](docs/guides/deployment-connectors.md) and [operational correlation](docs/operations/operational-correlation.md).

## Configuration and model providers

Start with an offline project configuration:

```sh
hound init
hound config validate --config .hound.yml
hound config show
```

Configuration resolves in this order:

```text
CLI flags → YAML configuration → HOUND_* environment variables
          → provider-specific environment variables → offline fallback
```

Hound supports built-in presets for OpenAI, Anthropic-compatible endpoints, Gemini, Groq, Ollama, DeepSeek, Azure OpenAI, 9router, and custom endpoints. It can also invoke explicitly accepted Codex, Claude Code, or Gemini CLI subscription sessions. Subscription use may conflict with provider terms or account policies, so Hound requires explicit risk acceptance.

```sh
hound providers
hound models --provider groq --refresh
```

Store credentials in provider environment variables or the system keyring, not in source-controlled YAML. If a provider fails, times out, exhausts retries, or returns an invalid result, Hound records the status and uses deterministic fallback unless `require_llm` is enabled.

<details>
<summary><strong>Minimal online configuration</strong></summary>

```yaml
llm:
  provider: gemini
  model: auto
  temperature: 0.2
  timeout: 120.0
  max_retries: 3
  max_concurrency: 4

redact: true

trust:
  source_class: local_artifact

dedup:
  backend: sqlite
  state_file: .hound/state.sqlite3
  retention_days: 90
  reuse: true
  reuse_after_occurrences: 3
```

`model: auto` uses configured or cached catalog data. It does not make an unexpected discovery request during analysis.

</details>

## Security boundary

Hound treats artifacts, repositories, model output, and external services as separate trust boundaries.

### Protections built into Hound

- Offline mode makes no provider request.
- Redaction runs before supported content reaches prompts, reports, tickets, dedup snapshots, or delivery payloads.
- Artifact, command-output, provider-response, and connector reads are bounded.
- XML parsing disables external entities.
- Fork PR trust mode forces offline analysis, keeps redaction enabled, and disables source context, enrichment, and delivery.
- Output and sensitive state paths reject unsafe symlinks where applicable and use atomic persistence for critical state.
- Provider and delivery clients reject redirects, bound responses, and cap retries.
- `hound clean` removes only directories carrying Hound ownership markers.

### Limits you must account for

- Pattern redaction cannot identify every encoded, fragmented, novel, or application-specific secret.
- Original artifacts are not rewritten and may still contain sensitive data.
- LLM output remains probabilistic after schema and evidence-reference validation.
- Command execution is not sandboxed. Child processes inherit the Hound process permissions.
- TLS, public ingress, host permissions, backup encryption, and untrusted-checkout isolation remain operator responsibilities.

Use an external container, VM, restricted account, or disposable runner when executing commands from an untrusted checkout. Read the [threat model](docs/operations/threat-model.md) and [bounded-operation limits](docs/benchmarks/limits.md) before production deployment.

| Source class | Intended use | Enforced behavior |
|---|---|---|
| `trusted_branch` | Controlled internal evidence | Configured external capabilities may run |
| `local_artifact` | Default local evidence | Explicit options control external capabilities |
| `fork_pr` | Untrusted public-fork evidence | Offline, redacted, no source context, enrichment, or delivery |

Report suspected vulnerabilities through [GitHub Security Advisories](https://github.com/youthisss/hound-tracer/security/advisories/new), not a public issue. See [`SECURITY.md`](SECURITY.md).

## Documentation

| Document | Covers |
|---|---|
| [Documentation index](docs/README.md) | Entry point for guides, references, and operations |
| [Architecture](docs/architecture.md) | Pipeline, contracts, failure policy, and test strategy |
| [Support matrix](docs/support-matrix.md) | Tested runtimes, operating systems, and external gates |
| [GitHub Action guide](docs/guides/github-action.md) | Action inputs, outputs, permissions, and upgrades |
| [Server deployment](docs/guides/server-deployment.md) | Reverse proxy, TLS boundary, backup, and recovery |
| [Deployment connectors](docs/guides/deployment-connectors.md) | Kubernetes and Helm collection boundaries |
| [Engine surface matrix](docs/reference/engine-surface.md) | Skill, plugin, MCP, and internal capabilities |
| [MCP SDK migration](docs/reference/mcp-sdk-migration.md) | Current protocol boundary and official SDK exit criteria |
| [Source intelligence](docs/reference/source-intelligence.md) | Source, ownership, and Git evidence |
| [Test impact](docs/reference/test-impact.md) | Advisory test-impact graph contract |
| [Timeline schema](docs/reference/timeline-schema.md) | Timeline and causal-link fields |
| [Threat model](docs/operations/threat-model.md) | Assets, controls, outbound network, and residual risk |
| [Delivery reliability](docs/operations/delivery-reliability.md) | Idempotency, ambiguous outcomes, and recovery |
| [State recovery](docs/operations/state-recovery.md) | Backup and restoration of persistent state |
| [Changelog](CHANGELOG.md) | Releases, migrations, and compatibility changes |

## Development

```sh
git clone https://github.com/youthisss/hound-tracer.git
cd hound-tracer
uv sync --extra dev

uv run ruff check src tests
uv run mypy src/hound
uv run pytest -m "unit and not slow" -q
uv run pytest -m integration -q
uv run pytest -m "e2e and not slow" -q
uv run pytest --cov=hound --cov-report=term --cov-fail-under=80 -q
uv run python -m hound.eval --offline --check --format json
```

Contributions should preserve deterministic offline behavior, default redaction, bounded operations, and clean machine-readable output. Read [`CONTRIBUTING.md`](CONTRIBUTING.md) and the [dependency policy](docs/operations/dependency-policy.md) before opening a pull request.

## Project status

Hound Tracer `0.7.0` is beta software. CPython 3.10, 3.11, 3.12, and 3.13 are supported. Platform evidence and external release gates are tracked in the [support matrix](docs/support-matrix.md). Releases follow [Semantic Versioning](https://semver.org/) and are recorded in the [changelog](CHANGELOG.md).

## License

Hound Tracer is distributed under the [MIT License](LICENSE).
