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

**Offline-first diagnostics for CI/CD, build, test, deployment, and container failures**

[![PyPI](https://img.shields.io/pypi/v/hound-tracer.svg)](https://pypi.org/project/hound-tracer/)
[![Python](https://img.shields.io/badge/Python-3.10%20to%203.12-blue.svg)](pyproject.toml)
[![Status](https://img.shields.io/badge/status-beta-yellow.svg)](#project-status)
[![Security](https://img.shields.io/badge/redaction-default-orange.svg)](#security-and-trust-boundaries)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

</div>

Hound Tracer turns raw failure evidence into a structured root-cause report, triage decision, and ticket draft. It accepts plain logs, JUnit XML, SARIF, and supported test-report JSON; frames stack traces; removes recognized secrets and PII; adds optional Git context; detects recurring incidents; and can use either deterministic offline rules or an explicitly configured LLM.

The analysis is advisory. Hound does not deploy, retry, or roll back infrastructure. Features that explicitly run commands, including `hound log -- <command>`, MCP command execution, and **Run project** in the TUI, execute operator-selected, checkout-controlled code with the Hound process permissions. They are not a sandbox.

## Contents

- [Why Hound](#why-hound)
- [How it works](#how-it-works)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Inputs and outputs](#inputs-and-outputs)
- [Interfaces](#interfaces)
- [Command reference](#command-reference)
- [Configuration and providers](#configuration-and-providers)
- [Quality gates and test insights](#quality-gates-and-test-insights)
- [CI, Docker, and coding-agent integration](#ci-docker-and-coding-agent-integration)
- [Security and trust boundaries](#security-and-trust-boundaries)
- [Supported failures and ecosystems](#supported-failures-and-ecosystems)
- [Operations and state](#operations-and-state)
- [Development and verification](#development-and-verification)
- [Documentation map](#documentation-map)

## Why Hound

🔎 **Evidence first.** Reports retain concrete evidence references, framed stack traces, failed tests, source locations, and uncertainty instead of returning an unsupported diagnosis.

🔒 **Private by default.** Offline mode makes no provider request. Redaction runs before supported content reaches reports, model prompts, dedup snapshots, or delivery connectors.

🧭 **One engine, several interfaces.** The CLI, Textual TUI, HTTP service, GitHub Action, and MCP server use the same analysis pipeline and document schema.

📉 **Controlled model usage.** Deduplication, failure-kind routing, call limits, retry limits, concurrency limits, and USD budgets keep optional LLM use bounded.

🧪 **QA beyond one failure.** Hound stores test history, detects flakiness and duration regressions, compares coverage, reads SARIF, and evaluates versioned quality-gate policies.

📨 **Recoverable delivery.** GitHub, Jira, GitLab, and Slack delivery uses a persistent ledger to distinguish confirmed, failed, pending, and ambiguous outcomes.

## How it works

```text
Failure evidence
  .log | JUnit .xml | SARIF .sarif | supported test-report .json
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ Ingest                                                       │
│ bounded reads · head/tail windows · stack framing · redaction│
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ Context                                                      │
│ metadata · Git diff/blame/commits · CODEOWNERS · source lines│
│ optional read-only Kubernetes, Helm, Prometheus, Tempo data  │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ RCA                                                          │
│ reviewed cache → optional LLM → deterministic fallback       │
│ schema validation · evidence-reference validation · budgets  │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ Triage and output                                            │
│ severity · component · fingerprint · recurrence · flakiness  │
│ report.json · report.md · ticket.md · optional delivery      │
└──────────────────────────────────────────────────────────────┘
```

The primary machine-readable output is RCA Document Schema v2.0. A report includes:

- failure stage, kind, summary, message, failed tests, and stack frames;
- hypotheses, confidence, supporting and contradicting evidence, missing information, and recommended checks;
- root-cause summary and fix suggestion;
- severity, component, fingerprint, recurrence, and flaky-suspect state;
- analysis engine, LLM status, fallback reason, cost information, and context provenance.

See [`docs/architecture.md`](docs/architecture.md) and [`docs/schema/rca-v2.0.schema.json`](docs/schema/rca-v2.0.schema.json) for the complete contract.

## Installation

Hound supports CPython `>=3.10,<3.13`. Windows and Linux are tested surfaces. macOS is expected to be portable, but release-runner evidence is still pending.

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

- `hound`: launcher and full CLI;
- `hound-mcp`: stdio MCP server for coding-agent clients.

## Quick start

```sh
# Open the launcher and choose TUI, persistent CLI, or HTTP server
hound

# Check runtime, configuration, storage, Git, Docker, and kubectl readiness
hound doctor

# Analyze a directory locally with no provider request
hound analyze ./ci-logs --offline

# Add bounded source context from the current Git checkout
hound analyze ./ci-logs --repo-dir . --source-context --offline

# Capture a command and analyze its output if it fails
hound log --analyze --offline -- pytest -q

# Open the TUI directly
hound console --logs ./ci-logs --offline
```

For automation, always use an explicit subcommand. Running bare `hound` requires an interactive TTY.

## Inputs and outputs

### Accepted evidence

| Input | Notes |
|---|---|
| `.log` | Plain build, test, CI, deployment, or container output |
| JUnit `.xml` | Structured suites, cases, failures, errors, skips, and durations |
| `.sarif` | SARIF 2.1.0 findings from tools such as CodeQL, Semgrep, Snyk, ESLint, and Trivy |
| Test-report `.json` | Recognized structured reports in report-bearing paths |
| Piped stdin | Captured through `hound log --name <name>` |
| Git checkout | Optional bounded diff, blame, commit, CODEOWNERS, source, and impact context |

Directory analysis is recursive. Dependency trees, virtual environments, VCS metadata, and common caches are pruned. Symlinked files and directories are not followed.

### Generated files

For each analysis run, Hound writes an isolated run directory under the selected output root:

```text
hound-output/
├── .hound-owned
├── run-<id>/
│   ├── .hound-owned
│   ├── report.json
│   ├── report.md
│   └── ticket.md
└── .hound/
    ├── state.sqlite3       # dedup and cached RCA state, default backend
    ├── feedback.sqlite3
    └── delivery.sqlite3
```

`hound log` also creates a redacted `.log` and JSON sidecar containing sanitized command arguments, working directory, Git metadata, timestamps, duration, and exit status. Original input artifacts are never rewritten.

### Analysis exit codes

| Code | Meaning |
|---:|---|
| `0` | Analysis completed and no actionable failure was detected |
| `1` | Analysis completed and detected a failure |
| `2` | Invalid arguments, configuration, or input |
| `3` | Internal execution, I/O, or required delivery failure |

`hound log` normally preserves the wrapped command exit code. A command timeout uses exit code `124`; explicit cancellation uses `130`.

## Interfaces

### Terminal UI

```sh
hound console --logs ./ci-logs --offline
hound console --logs ./ci-logs --online --jobs 4 --max-llm-calls 20
```

The TUI contains Home, Artifacts, Project Runs, Results, and Quality workspaces. Stored analysis runs expose Overview, Report, Ticket, Context, and Raw log views. Settings manage provider selection, model discovery, credentials through the system keyring, trust mode, and offline mode.

The **Run project** dialog detects likely test, build, lint, and check commands from common manifests. Detection is a convenience, not a safety judgment. npm hooks, Rust build scripts, Maven plugins, Gradle tasks, Make dependencies, compiler plugins, and invoked binaries remain checkout-controlled code. Runs are unsandboxed, use an immutable working-directory request, stop after five minutes by default, support process-tree cancellation, cap captured output at 16 MiB, redact persisted argv and output, and write run records atomically.

Main keyboard controls:

| Key | Action |
|:---:|---|
| `a` / `A` | Analyze the selected artifact / analyze all visible artifacts |
| `Ctrl+R` | Open Run project |
| `x` | Stop active analysis or project execution; otherwise clear the selected result |
| `Ctrl+X` | Stop analysis |
| `r` | Refresh current data |
| `h` | Home |
| `f` / `j` / `l` / `y` | Artifacts / Project Runs / Results / Quality |
| `i` | Current-run overview |
| `b` | Browse directory |
| `s` | Settings |
| `o` | Toggle offline mode, subject to trust policy |
| `space` | Toggle focused selection |
| `z` / `d` | Select all / deselect all in the active workspace |
| `p` / `n` | Previous / next page or opened result |
| `c` / `e` | Copy report / ticket Markdown |
| `v` | Record feedback for the opened run |
| `?` | Help |
| `Escape` / `B` | Back |
| `q` | Return to the launcher, or exit when started with `hound console` |
| `Ctrl+C` | Quit the TUI |

### Persistent Rich CLI

```sh
hound cli
```

Inside the session, omit the executable name: enter `doctor`, `analyze . --offline`, or `runs`. `Ctrl+L` redraws the header. `Ctrl+C` exits immediately. `exit` or `Ctrl+D` returns to the launcher when the session was opened there, or to the shell when started with `hound cli`.

### HTTP service

The built-in service uses Bearer authentication and a persistent SQLite queue. It binds to loopback. Put a controlled reverse proxy in front of it for TLS or remote ingress.

```sh
export HOUND_SERVER_TOKEN="replace-with-a-long-random-token"

hound serve \
  --host 127.0.0.1 \
  --port 8123 \
  --log-root ./ci-logs \
  --output-dir ./server-runs \
  --workers 4 \
  --rate-limit 60
```

| Endpoint | Purpose |
|---|---|
| `POST /analyze` | Submit a bounded analysis job |
| `GET /jobs/<id>` | Read job state and result location |
| `DELETE /jobs/<id>` | Cancel a queued or running job |
| `GET /health` | Process liveness |
| `GET /ready` | Readiness and queue availability |
| `GET /stats` | Authenticated payload-free queue and engine counters |

Use `hound client submit`, `inspect`, `poll`, or `cancel` to operate the service. See [`docs/guides/server-deployment.md`](docs/guides/server-deployment.md) for proxy, service-unit, and recovery guidance.

### GitHub Action

The Docker Action accepts an artifact path, repository path, output directory, and trust options. Action paths must remain under `GITHUB_WORKSPACE`.

```yaml
- name: Run tests
  id: tests
  continue-on-error: true
  run: pytest --junitxml=artifacts/junit.xml | tee artifacts/pytest.log

- name: Investigate failure
  if: steps.tests.outcome == 'failure'
  uses: youthisss/hound-tracer@v0.6.0
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

See [`docs/guides/github-action.md`](docs/guides/github-action.md) for every input, output, permission, and upgrade rule.

### MCP server

```sh
hound-mcp
# Equivalent CLI surface
hound mcp
```

Available tools:

| MCP tool | Purpose |
|---|---|
| `hound_analyze` | Analyze a file or directory |
| `hound_log_command` | Run, capture, redact, and optionally analyze a command |
| `hound_check_gate` | Evaluate a quality-gate policy |
| `hound_get_insights` | Query test history and flakiness |
| `hound_doctor` | Check local readiness |
| `hound_list_incidents` | Inspect deduplicated incidents |

Set `HOUND_MCP_ROOTS` to the allowed filesystem roots. Command execution is disabled unless the MCP administrator explicitly sets `HOUND_MCP_ENABLE_COMMAND_EXECUTION=1`.

## Command reference

| Command | Purpose |
|---|---|
| `hound analyze` | Analyze one artifact or recursively analyze a directory |
| `hound batch` | Process many artifacts with shared budgets and usage records |
| `hound cli` | Open the persistent command session |
| `hound console` | Open the Textual TUI |
| `hound log` | Capture a command or piped stdin and optionally analyze failure |
| `hound gate` | Evaluate tests, coverage, changed-line coverage, and SARIF |
| `hound insights` | Import, export, query, and classify test history |
| `hound serve` | Start the authenticated HTTP job service |
| `hound client` | Submit, inspect, poll, or cancel server jobs |
| `hound doctor` | Validate local readiness without exposing secrets |
| `hound init` | Create project configuration and local Hound workspace |
| `hound config` | Show, set non-secret values, or validate configuration |
| `hound providers` | List built-in provider presets |
| `hound models` | List or refresh a provider model catalog |
| `hound runs` | List stored analysis runs |
| `hound report` | Render a stored report as text, JSON, or Markdown |
| `hound feedback` | Record reviews or export regression candidates |
| `hound delivery` | Inspect and recover delivery-ledger records |
| `hound incidents` | Inspect recurrence or invalidate cached RCA snapshots |
| `hound integrations` | Detect harnesses and install confirmed integrations |
| `hound mcp` | Start the stdio MCP service |
| `hound clean` | Remove only output trees carrying Hound ownership markers |

Run `hound <command> --help` for the authoritative option list.

### Common analysis examples

```sh
# Single artifact
hound analyze failure.log --offline

# Recursive directory, parallel workers
hound analyze ./artifacts --jobs 4 --output-dir ./hound-output

# Preview the bounded LLM prompt without making a provider request
hound analyze failure.log --llm-preview

# JSON presentation
hound analyze failure.log --format json --output ./result.json

# Optional delivery
hound analyze failure.log --gh --slack-webhook
```

### Batch processing

```sh
hound batch \
  --logs ./ci-logs \
  --output-dir ./batch-output \
  --jobs 8 \
  --max-llm-calls 50 \
  --max-cost-usd 5.00
```

Batch mode writes a classification summary and usage record. When a call or cost budget is exhausted, remaining files use deterministic fallback and are marked `budget_skipped`.

### Command capture

```sh
hound log -- npm test
hound log --name unit-tests -- pytest -q
kubectl logs deployment/api -n prod | hound log --name api-deploy
hound log --analyze --offline -- cargo test
```

Commands run without a shell, but the executable and project hooks can still perform arbitrary actions. Captured output is redacted by default and bounded. Supplying raw-console or unredacted options weakens that protection and should be restricted to controlled evidence.

### Administration

```sh
hound runs --output-dir hound-output
hound report <run-directory> --format markdown
hound incidents list --output-dir hound-output --json
hound incidents inspect --output-dir hound-output --key <dedup-key> --json
hound incidents invalidate --output-dir hound-output --key <dedup-key> --yes

hound delivery list --output-dir hound-output --json
hound delivery inspect --output-dir hound-output --incident-key <key> --destination github --json
hound delivery reconcile --output-dir hound-output --incident-key <key> --destination github --external-id <id>
hound delivery mark-failed --output-dir hound-output --incident-key <key> --destination github --error "verified absent" --confirm-absent
hound delivery retry-failed --output-dir hound-output --incident-key <key> --destination jira

hound clean --output-dir hound-output --yes
```

## Configuration and providers

Create `.hound.yml`, then validate it before analysis:

```sh
hound init
hound config validate --config .hound.yml
hound config show
```

Resolution order is:

```text
CLI flags → YAML configuration → generic HOUND_* environment variables
→ provider-specific environment variables → offline fallback rules
```

`hound config set` is intended for non-sensitive values such as provider and model. Store credentials in provider environment variables or the system keyring, not in source-controlled YAML.

### Starter configuration

```yaml
llm:
  provider: gemini
  model: auto
  temperature: 0.2
  timeout: 120.0
  max_retries: 3
  max_concurrency: 4
  routing: exclude-kinds
  skip_kinds: [flaky, timeout]
  pricing:
    default:
      prompt_per_mtok: 0.15
      completion_per_mtok: 0.60

redact: true

trust:
  source_class: local_artifact

components:
  "services/billing/**": team-billing
  "services/auth/**": team-security
  "k8s/**": platform-infra

dedup:
  backend: sqlite
  state_file: .hound/state.sqlite3
  max_entries: 50000
  retention_days: 90
  reuse: true
  reuse_after_occurrences: 3

policy:
  recurrence_threshold: 3
  severity_overrides:
    production:
      deployment_failed: critical
      oom_killed: critical

observability:
  prometheus_url: https://prometheus.internal
  tempo_url: https://tempo.internal
  window_minutes: 15

runbooks:
  api: https://runbooks.internal/services/api.md

github:
  repo: my-org/my-repo
jira:
  url: https://jira.example.com
  project: PROJ
gitlab:
  url: https://gitlab.com
  project: my-org/my-repo
slack:
  webhook_url: https://hooks.slack.com/services/...
```

### Provider presets

Hound talks to OpenAI-compatible endpoints. Anthropic use requires an OpenAI-compatible proxy.

| Preset | Credential | Default endpoint |
|---|---|---|
| `openai` | `OPENAI_API_KEY` | `https://api.openai.com/v1` |
| `anthropic` | `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL` | Proxy supplied by operator |
| `gemini` | `GEMINI_API_KEY` | `https://generativelanguage.googleapis.com/v1beta/openai` |
| `groq` | `GROQ_API_KEY` | `https://api.groq.com/openai/v1` |
| `ollama` | None by default | `http://localhost:11434/v1` |
| `deepseek` | `DEEPSEEK_API_KEY` | `https://api.deepseek.com/v1` |
| `azure` | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_BASE_URL` | Resource-specific |
| `9router` | `NINE_ROUTER_API_KEY` | `http://127.0.0.1:20128/v1` |
| `custom` | `CUSTOM_API_KEY`, `CUSTOM_BASE_URL` | Operator-supplied |

Generic overrides include `HOUND_API_PROVIDER`, `HOUND_API_KEY`, `HOUND_BASE_URL`, `HOUND_MODEL`, `HOUND_TEMPERATURE`, `HOUND_TIMEOUT`, `HOUND_MAX_TOKENS`, `HOUND_MAX_RETRIES`, `HOUND_MAX_CONCURRENCY`, `HOUND_REQUIRE_LLM`, and `HOUND_SOURCE_CLASS`.

```sh
hound providers
hound models --provider groq --refresh
```

If a provider fails, times out, returns an invalid schema, or reaches its retry limit, Hound records `llm_status` and `fallback_reason`, then uses deterministic RCA unless `require_llm` is enabled.

## Quality gates and test insights

### Test history

The local SQLite history store tracks outcomes, durations, branches, commits, environments, failure rates, and p95 duration.

```sh
hound insights import ./junit.xml \
  --test-runner pytest \
  --branch main \
  --commit abc1234 \
  --environment "os=linux;python=3.11"

hound insights stats tests/test_payment.py test_checkout_idempotency
hound insights history tests/test_payment.py test_checkout_idempotency --window-days 30
hound insights tests --suite-prefix tests/unit/
```

### Quality gate

```sh
hound gate ./test-results \
  --repo-dir . \
  --baseline-ref origin/main \
  --candidate-ref HEAD \
  --policy ./quality-gate.yml \
  --coverage ./coverage/coverage.json \
  --baseline-coverage ./coverage/baseline-coverage.json \
  --sarif ./reports/semgrep.sarif \
  --output gate-results.json
```

Example policy:

```yaml
version: "1.0"
rules:
  new_failure: block
  flaky: warn
  coverage_delta:
    outcome: block
    threshold_percent: -2.0
  changed_line_coverage:
    outcome: block
    threshold_percent: 80.0
    include: ["src/**"]
    exclude: ["tests/**", "docs/**"]
  critical_sarif: block
  sarif_warning: warn
```

Gate exit codes are `0` for pass or accepted warning, `1` for a policy block, and `2` for invalid input or policy.

## CI, Docker, and coding-agent integration

### Docker

```sh
docker build -t hound-tracer .
docker run --rm \
  -v "$PWD/ci-logs:/logs:ro" \
  -v "$PWD/hound-output:/out" \
  hound-tracer analyze /logs --output-dir /out --offline
```

The release image runs the main Hound process as a non-root user. Docker availability remains a separate CI or release gate when the local development host has no daemon.

### Coding harnesses

Hound ships a skill, MCP server, and harness-specific examples for OpenCode V2, Hermes Agent, Claude Code, Codex, Cursor, and Antigravity.

```sh
hound integrations detect
hound integrations install --help
```

Installation requires explicit confirmation. The examples under [`integrations/`](integrations/) must be merged into the target harness configuration; [`plugins/hound/plugin.json`](plugins/hound/plugin.json) is a reference bundle, not a universal plugin format. The packaged agent workflow lives at [`skills/hound-tracer/SKILL.md`](skills/hound-tracer/SKILL.md).

## Security and trust boundaries

### What Hound protects

- Redaction is enabled by default before supported content reaches prompts, reports, tickets, dedup snapshots, or delivery payloads.
- Recognized patterns include private keys, bearer tokens, JWTs, provider credentials, passwords, connection strings, email addresses, IPv4 addresses, and IPv6 addresses.
- Artifact and response reads are bounded. XML parsing disables external entities.
- Output paths, sensitive stores, and command captures reject unsafe symlink paths where applicable and use atomic persistence for critical state.
- Fork PR trust mode forces offline analysis, keeps redaction enabled, and disables source context, enrichment, and delivery.
- Provider and delivery clients reject redirects, bound responses, cap retries, and separate external errors from evidence.
- The HTTP server authenticates protected routes, limits requests and queue admission, and binds to loopback.
- `hound clean` removes only directories carrying Hound ownership markers.

### What Hound cannot guarantee

- Pattern redaction cannot identify every encoded, fragmented, novel, or application-specific secret.
- Original artifacts remain unchanged and may still contain sensitive data.
- LLM output remains probabilistic even after schema and evidence-reference validation.
- Command execution is not sandboxed. Child processes can read files, credentials, and network resources available to the Hound process and may modify the checkout.
- Running without `shell=True` prevents a shell-injection class; it does not make a project script safe.
- TLS, public ingress, multi-instance rate limiting, host permissions, backup encryption, and isolation of untrusted checkouts remain operator responsibilities.

Use `--offline` for local-only analysis. Use an external container, VM, restricted account, or disposable runner when executing commands from an untrusted checkout.

### Trust profiles

| Source class | Intended use | Restrictions |
|---|---|---|
| `trusted_branch` | Controlled branch or internal evidence | Optional LLM, source context, enrichment, and delivery allowed by configuration |
| `local_artifact` | Default local evidence | Explicit options control external capabilities |
| `fork_pr` | Untrusted public-fork evidence | Offline only, redaction locked on, no source context, enrichment, or delivery |

### Vulnerability reporting

Do not open a public issue for a suspected vulnerability or credential leak. Use [GitHub Security Advisories](https://github.com/youthisss/hound-tracer/security/advisories/new) or the maintainer contact listed in [`SECURITY.md`](SECURITY.md). Scrub credentials from reproduction artifacts.

## Supported failures and ecosystems

| Stage | Failure kinds and examples |
|---|---|
| Build | `compilation_error`, `import_error`, `dependency_resolution`, `config_missing` |
| Test | `test_failure`, `timeout`, verified rerun-then-pass `flaky` behavior |
| CI | `ci_failure`, `disk_full`, `api_rate_limited`, `permission_error` |
| Deployment | `deployment_failed`, `rollback`, `readiness_timeout`, `migration_failed` |
| Container and Kubernetes | `oom_killed`, `crash_loop`, `image_pull_error`, `registry_auth_failure`, `scheduling_failed`, `quota_exceeded`, `liveness_probe_failed`, `readiness_probe_failed` |
| Network and TLS | `network_failure`, `tls_certificate_error` |

Stack framing covers Python, Go, Rust, Java, JavaScript and TypeScript V8 output, C and C++, C#, plus relevant YAML, Terraform, and template locations. Test ingestion recognizes pytest, Jest, Vitest, Go test, RSpec, Cargo test, dotnet test, and JUnit XML.

Optional deployment context supports bounded read-only Kubernetes and Helm commands. Optional observability context supports Prometheus and Tempo-compatible endpoints. These connectors require explicit configuration, a trusted source classification, and available external runtimes.

## Operations and state

### Deduplication

Normalized failure evidence produces a SHA-256 incident fingerprint. The default SQLite backend uses WAL mode for concurrent workers, recurrence counters, bounded retention, and RCA snapshot reuse. The cache key includes source digest, model, prompt implementation, policy, and project scope.

### Feedback

```sh
hound feedback record \
  --run-id run-abc1234 \
  --usefulness useful \
  --actual-kind test_failure

hound feedback export --candidate-fixtures --output candidate-fixtures.json
```

Reviewed feedback can improve known-issue matching and create candidate regression fixtures. It does not silently retrain a model.

### Delivery reliability

Delivery is opt-in. The SQLite ledger assigns idempotency keys and preserves ambiguous network outcomes so Hound does not blindly create duplicate external tickets. Operators must reconcile unknown outcomes before retrying.

### Server state

The server queue persists in SQLite. Environment controls include `HOUND_SERVER_TOKEN`, `HOUND_SERVER_WORKERS`, `HOUND_SERVER_MAX_QUEUE`, `HOUND_SERVER_RATE_LIMIT`, and `HOUND_SERVER_JOB_TTL`. See [`docs/operations/state-recovery.md`](docs/operations/state-recovery.md) before repairing or replacing state files.

### Bounded operations

Hound caps file reads, provider responses, delivery responses, artifact discovery, prompt evidence, retries, queues, and captured command output. Current limits and benchmark rationale are documented in [`docs/benchmarks/limits.md`](docs/benchmarks/limits.md).

## Development and verification

```sh
git clone https://github.com/youthisss/hound-tracer.git
cd hound-tracer
uv sync --extra dev

# Formatting and static checks
uv run ruff check src tests
uv run mypy src/hound

# Test boundaries
uv run pytest -m "unit and not slow" -q
uv run pytest -m integration -q
uv run pytest -m "e2e and not slow" -q

# Full suite and coverage gate
uv run pytest
uv run pytest --cov=hound --cov-report=term --cov-fail-under=80 -q

# Offline diagnostic accuracy evaluation
uv run python -m hound.eval --offline --check --format json
```

Test markers identify the dominant boundary: `unit`, `integration`, `e2e`, `slow`, and `network`. Localhost HTTP tests are integration tests, not network tests.

Contributions should use type-annotated Python, preserve deterministic offline behavior, keep redaction enabled by default, keep machine-readable stdout clean, and never commit secrets or private logs. Use Conventional Commit prefixes such as `feat:`, `fix:`, `docs:`, and `test:`. Read [`CONTRIBUTING.md`](CONTRIBUTING.md) and the [dependency policy](docs/operations/dependency-policy.md) before opening a pull request.

## Repository structure

```text
src/hound/
├── cli.py             command parsing and adapter dispatch
├── rich_cli.py        persistent Rich command session
├── launcher.py        bare-command interface launcher
├── tui.py             Textual terminal application
├── service.py         shared analysis and project-run services
├── pipeline.py        RCA pipeline orchestration
├── collector.py       bounded subprocess and stdin capture
├── server.py          HTTP service and SQLite job queue
├── config.py          strict configuration and provider presets
├── models.py          RCA Document Schema v2.0 validation
├── trust.py           source trust policies
├── feedback.py        review feedback and fixture export
├── eval.py            diagnostic regression evaluator
├── analyze/           LLM adapter, prompts, fallback, cost control
├── ingest/            parsers, redaction, framing, Git context
├── triage/            severity, component mapping, deduplication
├── qa/                history, coverage, SARIF, quality gates
├── devops/            timeline and incident correlation
├── connectors/        deployment and observability evidence
├── source/            source context and test-impact analysis
├── mcp/               bounded coding-agent tools
└── output/            reports, tickets, connectors, delivery ledger
```

## Documentation map

| Document | Covers |
|---|---|
| [`docs/README.md`](docs/README.md) | Documentation index |
| [`docs/architecture.md`](docs/architecture.md) | Pipeline, contracts, and module boundaries |
| [`docs/support-matrix.md`](docs/support-matrix.md) | Tested runtimes, operating systems, and external gates |
| [`docs/guides/github-action.md`](docs/guides/github-action.md) | Action inputs, outputs, trust, and upgrades |
| [`docs/guides/server-deployment.md`](docs/guides/server-deployment.md) | Reverse proxy, TLS boundary, and service operation |
| [`docs/guides/deployment-connectors.md`](docs/guides/deployment-connectors.md) | Kubernetes, Helm, Prometheus, and Tempo evidence |
| [`docs/reference/log-format.md`](docs/reference/log-format.md) | Collector logs and metadata sidecars |
| [`docs/reference/source-intelligence.md`](docs/reference/source-intelligence.md) | Source context and ownership evidence |
| [`docs/reference/test-impact.md`](docs/reference/test-impact.md) | Advisory test-impact graph contract |
| [`docs/reference/timeline-schema.md`](docs/reference/timeline-schema.md) | Timeline event schema |
| [`docs/reference/schema-migration-v1.4-to-v2.0.md`](docs/reference/schema-migration-v1.4-to-v2.0.md) | RCA schema migration |
| [`docs/operations/threat-model.md`](docs/operations/threat-model.md) | Assets, trust boundaries, controls, residual risk |
| [`docs/operations/delivery-reliability.md`](docs/operations/delivery-reliability.md) | Delivery ledger and recovery |
| [`docs/operations/state-recovery.md`](docs/operations/state-recovery.md) | Persistent state recovery |
| [`docs/operations/operations-metrics.md`](docs/operations/operations-metrics.md) | Operational metrics |
| [`docs/operations/operational-correlation.md`](docs/operations/operational-correlation.md) | Cross-signal correlation |
| [`docs/operations/pilot-readiness.md`](docs/operations/pilot-readiness.md) | Pilot acceptance and evidence |
| [`docs/operations/release-checklist.md`](docs/operations/release-checklist.md) | Release and publication gates |
| [`docs/benchmarks/limits.md`](docs/benchmarks/limits.md) | Resource bounds and benchmark evidence |
| [`CHANGELOG.md`](CHANGELOG.md) | Release history and migrations |
| [`SECURITY.md`](SECURITY.md) | Supported versions and private disclosure |

## Project status

Hound Tracer `0.6.0` is beta software. CPython 3.10, 3.11, and 3.12 are supported. The current support contract, pending platform evidence, and external release gates are maintained in [`docs/support-matrix.md`](docs/support-matrix.md). Version history follows [Semantic Versioning](https://semver.org/) and is recorded in [`CHANGELOG.md`](CHANGELOG.md).

## License

Hound Tracer is distributed under the [MIT License](LICENSE).
