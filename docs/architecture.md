# ARCHITECTURE — Hound

## Module map

```
hound/
├── pyproject.toml            # uv; [project.scripts] hound = hound.cli:main
├── src/
│   └── hound/
│       ├── __init__.py       # __version__
│       ├── models.py         # RCA document models and schema validation
│       ├── config.py         # environment and YAML configuration
│       ├── collector.py      # command/stdin capture and redaction
│       ├── service.py        # shared application service for CLI/TUI/server
│       ├── pipeline.py       # core analysis orchestration
│       ├── eval.py           # offline evaluator and confidence calibration
│       ├── ingest/           # logs, artifacts, source, Git, and redaction
│       ├── analyze/          # LLM adapter, prompts, RCA, and fallback
│       ├── triage/           # severity, component, and deduplication
│       ├── qa/               # test history, coverage, SARIF, and quality gates
│       ├── devops/            # deployment timelines and investigations
│       ├── connectors/       # bounded read-only deployment/observability adapters
│       ├── source/            # source context and test impact analysis
│       ├── mcp/              # stdio Model Context Protocol server and linear tools
│       └── output/            # reports, tickets, Slack, and delivery ledger
├── docs/
│   ├── guides/               # usage, GitHub Action, server, and connectors
│   ├── reference/            # log, source, impact, timeline, and migration contracts
│   ├── operations/           # recovery, security, release, and pilot operations
│   └── schema/               # normative RCA JSON schema
├── tests/
│   ├── unit/                 # fast in-process behavior
│   ├── integration/          # stores, connectors, source, and DevOps boundaries
│   ├── e2e/                  # CLI, TUI, Action, and evaluator workflows
│   ├── fixtures/             # reusable local logs and artifacts
│   ├── eval/                 # versioned evaluation corpus and baselines
│   └── golden/               # versioned RCA output fixtures
├── Dockerfile                # containerized runner
└── action.yml                # GitHub Action manifest
```

## Data flow

```
 log ─┐
 repo ─┼─► ingest ──► Artifacts ──► analyze ──► RootCause ──► triage ──► RCA doc ──► output ──► out/
       │                       │        (LLM │ fallback)      │  (severity/     (report +    report.json
       └───────────────────────┘        auto-fallback,        │   component/     ticket.md)  report.md
                               └─► devops timeline ───────────┤
                                         engine tagged)        └─ dedup ───────────► state.json | state.sqlite3
```

1. **ingest** builds `Artifacts`: extract request correlation IDs from the bounded raw log window, redact secrets (default on), detect stage/kind, extract summary/message, parse stacktrace and failed tests across common runners, and gather git context. For changed files matching repository-contained frames, up to three latest commit subjects become redacted root-cause evidence. Source snippets require explicit `--source-context` for trusted logs.
2. **analyze** produces `RootCause`: LLM if enabled+ok (with retry/backoff + usage capture), else fallback; LLM output merged over rule facts; `engine` recorded. `llm.routing: exclude-kinds` skips the LLM for kinds in `llm.skip_kinds`; dedup-first reuse (`dedup.reuse`) restores a stored root-cause snapshot for well-established recurring incidents instead of spending another call (`meta.reused`).
3. **triage** decorates: `Triage` (severity, component, priority, dedup_key, is_duplicate_of). State lives in a locked, atomic file store, or in a WAL-mode SQLite database when `dedup.backend: sqlite` (atomic `ON CONFLICT` upserts, no whole-file rewrite, safe for concurrent workers; retention + max-entries pruning). Each entry carries a root-cause snapshot used for LLM reuse.
4. **output** renders `report.json`, `report.md`, `ticket.md` into `--output-dir` (default `./hound-output/`). Optional filing: GitHub/Jira/GitLab ticket, Slack alert.
5. **batch** (`hound batch --logs DIR [--jobs N] [--max-llm-calls N] [--max-cost-usd X]`) writes opaque unique run directories and `summary-<batch-id>.json` plus `usage-<batch-id>.json` (LLM calls, reused runs, budget-skipped runs, token totals, estimated cost); dedup state is shared at `<output-dir>/.hound/state.json` (or `state.sqlite3`). Parallel workers keep run ids and summary ordering tied to input order, so output stays deterministic. Call slots are reserved atomically, so `--max-llm-calls` is strict even with parallel workers. The cost limit remains an estimated guardrail because actual token usage is known only after each response.
6. **tui** (`hound console`) calls `service.analyze_log()` in a Textual terminal app: pick a log → analyze → browse overview / report.md / ticket.md / raw log.
7. **server** (`hound serve --port --workers N --max-queue M --rate-limit R --job-ttl T`) calls the same service from a stdlib HTTP endpoint; GET `/health` returns liveness and GET `/stats` returns queued/running/completed/failed counts. Jobs live in a SQLite store under `<output-dir>/.hound/jobs.sqlite3`, so they survive restarts; jobs left running by a previous process are marked failed at startup.
8. **log collector** (`hound log -- COMMAND` or piped stdin) tees raw output to the terminal, persists a redacted `.log` plus JSON metadata, and can explicitly call the shared service with `--analyze`.
9. **trust** resolves the source class (`trusted_branch`/`fork_pr`/`local_artifact`) from `--source-class`, YAML `trust.source_class`, `HOUND_SOURCE_CLASS`, or CI environment detection before any capability runs. `fork_pr` fails closed: offline forced, redaction stays on, and source context, enrichment, LLM, and delivery are never invoked (`meta.trust` records the decision).
10. **feedback** (`hound feedback record/export`) writes reviewed engineer ratings into `<output-dir>/.hound/feedback.sqlite3` — intentionally separate from dedup state — with audit metadata and redacted values. It never mutates classifiers; `export --candidate-fixtures` emits explicit, manual regression-fixture candidate manifests.
11. **QA gate** (`hound gate ARTIFACTS --baseline-ref REF --candidate-ref REF --repo-dir REPO --policy FILE`) delegates to `qa/service.py`, which normalizes tests, coverage, and SARIF under aggregate file/byte/time limits before evaluating an explicit deterministic policy. Its JSON contract keeps `analysis_status` separate from `policy_outcome`; every warn/block includes an evidence-backed reason and a defect draft. Exit `0` means pass/warn, `1` means policy block, `2` means invalid input/policy, and `3` means an internal failure. `--report-only` preserves the computed outcome but disables exit-code enforcement.
12. **DevOps timeline** combines explicit deployment context, CI metadata, and failure events. It orders comparable events by `timestamp_ns`, falls back to `sequence` or source order with explicit uncertainty, preserves partial traces, detects causal-link cycles without failing analysis, and separately records deployment outcome, recovery, customer impact, and release identity comparison. The complete additive contract and legacy-reader behavior are documented in `docs/reference/timeline-schema.md`.
13. **Deployment connectors** run only after explicit operator opt-in, trusted policy approval, a supplied context file, and deploy-stage detection. Kubernetes and Helm commands are constructed as argument lists and checked against read-only verb allowlists; output is redacted and bounded before becoming evidence. Each attempt emits a credential-free `context.connector_audits` record, including partial failures. See `docs/guides/deployment-connectors.md`.
14. **Operational correlation** compares explicitly supplied current/previous release metadata and optionally queries a bounded Prometheus time window plus Tempo trace IDs already present in evidence. The resulting `devops` section keeps static and impact-adjusted severity separately, labels metric evidence as correlation only, estimates a critical path from available parent links, and resolves runbooks only from trusted configuration. See `docs/operations/operational-correlation.md`.
15. **Source intelligence V1** runs only for trusted repositories with explicit `--source-context`. It resolves repository-contained frame files, extracts Python symbols (bounded text fallback for other recognized suffixes), and attaches diff, blame, commit, CODEOWNERS, and direct related-test evidence. Symlinks, hidden/secret files, binaries, oversized files, and traversal paths are excluded. Source evidence stays local and out of LLM payloads unless trusted configuration explicitly sets `source.send_to_llm: true`. See `docs/reference/source-intelligence.md`.
16. **Test impact recommendations** use a depth-limited Python call graph and rank tests from direct references, optional coverage, static dependency candidates, and optional historical correlation. Every graph edge is labeled `static_candidate`; output is advisory and never changes CI selection. Missing coverage remains explicit. See `docs/reference/test-impact.md`.
17. **Delivery reliability and telemetry** use a separate WAL-mode delivery ledger with `pending`, `confirmed`, `failed`, and `unknown` states. Ambiguous outcomes block automatic retries until reconciliation. A bounded process-local telemetry registry exposes payload-free counters and latency percentiles through authenticated `/stats`. See `docs/operations/delivery-reliability.md` and `docs/operations/operations-metrics.md`.
18. **Model Context Protocol (MCP) Server** (`hound mcp`): stdio JSON-RPC 2.0 interface exposing linear tools (`hound_analyze`, `hound_log_command`, `hound_check_gate`, `hound_get_insights`, `hound_doctor`, `hound_list_incidents`). The server validates requests, bounds responses, and restricts file access to configured MCP roots. Command execution requires explicit administrator opt-in. Harness-specific installation remains the responsibility of each MCP client configuration.

`service.analyze_log()` is the adapter-facing entry point for CLI, TUI, server, and collector. It delegates to the single `pipeline.analyze()` core.

## RCA document schema (v2.0; v1.4 reader compatible)

```json
{
  "schema_version": "2.0",
  "meta": { "engine": "llm|fallback|merged", "model": null, "log_file": "...", "generated_at": "ISO8601",
            "redacted": false, "usage": { "prompt_tokens": 0, "completion_tokens": 0 },
            "reused": false, "reused_from_key": null },
  "failure": {
     "stage": "ci|build|test|deploy|unknown",
     "kind": "ci_failure|compilation_error|test_failure|import_error|timeout|flaky|deployment_failed|rollback|health_check_failed|image_pull_error|migration_failed|permission_error|readiness_timeout|oom_killed|crash_loop|liveness_probe_failed|readiness_probe_failed|scheduling_failed|quota_exceeded|network_failure|registry_auth_failure|config_missing|dependency_resolution|disk_full|tls_certificate_error|api_rate_limited|unknown",
    "summary": "...",
    "message": "core error line",
    "stacktrace": [{ "file": "...", "line": 0, "function": "...", "code": "2 | total = 5.0" }],
     "failed_tests": [{ "name": "...", "file": "...", "line": 0, "assertion": "..." }],
      "events": [{ "event_id": "ev-001", "stage": "build", "kind": "compilation_error", "message": "...", "role": "primary|downstream", "trace_id": "", "span_id": "", "parent_span_id": null, "timestamp_ns": null, "sequence": 1 }]
   },
   "context": {
      "run": { "provider": "github-actions", "run_id": "...", "job_name": "...", "pr_number": "...", "base_sha": "...", "head_sha": "..." },
       "deployment": { "platform": "kubernetes", "environment": "production", "service": "api", "workload": "deployment/api", "release": "api-42", "commit": "...", "image_digest": "sha256:...", "outcome": "failed", "recovery": "", "customer_impact": "" },
      "request": { "request_id": "req_123", "trace_id": "trace_123", "session_id": "", "user_id": "u_123", "users": ["u_123"], "method": "POST", "path": "/api/checkout" },
      "owners": ["@platform"]
   },
  "root_cause": {
    "hypothesis": "...",
    "confidence": "high|medium|low",
    "evidence": ["..."],
    "fix_suggestion": "..."
  },
  "analysis": {
    "observed_facts": [{ "id": "fact-001", "kind": "failure_classification", "value": {}, "evidence_refs": ["ev-001"] }],
    "evidence": [{
      "id": "ev-001",
      "kind": "failure_message",
      "value": "...",
      "provenance": { "source_type": "artifact", "artifact": "...", "locator": "failure.message", "collector": "ingest.logs", "observed_at": "ISO8601" }
    }],
    "hypotheses": [{
      "id": "hyp-001",
      "statement": "...",
      "source": "deterministic|llm",
      "support_status": "supported|unsupported|insufficient_evidence",
      "supporting_evidence_refs": ["ev-001"],
      "contradicting_evidence_refs": [],
      "confidence": { "band": "high|medium|low", "score": 0.75, "reasons": ["deterministic observation"] },
      "missing_information": [],
      "recommended_checks": []
    }],
    "missing_information": [],
    "recommended_checks": []
  },
   "triage": {
    "severity": "critical|high|medium|low",
    "component": "...",
    "priority": 1,
    "dedup_key": "sha256hex",
    "is_duplicate_of": null,
     "flaky_suspect": false,
     "recurring_incident": false,
     "occurrence_count": 1
  },
  "ticket": { "title": "...", "body_md": "...", "labels": ["severity:high"] },
  "timeline": {
    "grouping": "runtime|pipeline|mixed|none",
    "ordering_basis": "timestamp_ns|sequence|log_order|mixed",
    "has_cycles": false,
    "primary_event_id": "ev-001",
    "downstream_event_ids": ["ev-002"],
    "recovery_event_ids": [],
    "customer_impact": "unknown|none|degraded|outage",
    "release_changed": null,
    "entries": []
  }
}
```

`models.validate(doc) -> None` reads both v1.4 and v2.0 and raises on missing fields/types. New writes use v2.0. `root_cause` remains the compatibility projection; v2.0 consumers use `analysis` for typed facts, provenance, citations, missing information, and checks.

Evidence IDs are deterministic counters scoped to one report (`ev-001`, `ev-002`, ...), never hashes of evidence values. The numeric observation score measures evidence completeness, not a calibrated probability of root-cause correctness. Hypothesis confidence is separately constrained by available support and contradictions. Unknown, overlapping, or otherwise malformed LLM references invalidate the LLM result and trigger deterministic fallback. The normative machine contract and reader fixtures are in `docs/schema/rca-v2.0.schema.json` and `tests/golden/rca-v*.json`.

## Contracts between stages

| Stage | In | Out |
|---|---|---|
| ingest | raw log text, optional repo dir | `Artifacts` |
| analyze | `Artifacts` | `RootCause` |
| triage | `Artifacts` + `RootCause` | `Triage` |
| output | full RCA doc | files in out dir |

## Config

- Env: `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL` (default `gpt-4o-mini`); generic overrides `HOUND_*` (legacy `TH_*` aliases are accepted).
- Env (GitHub, used with `--gh`): `GH_TOKEN`, `GH_REPO` (owner/name), `GH_API_BASE` (default `https://api.github.com`).
- Env (trackers): `JIRA_URL`/`JIRA_PROJECT`/`JIRA_TOKEN`, `GITLAB_URL`/`GITLAB_PROJECT`/`GITLAB_TOKEN`, `SLACK_WEBHOOK_URL`.
- Optional YAML supplied explicitly with `--config`: `llm` (incl. `max_retries`, `max_concurrency`), `trust` (`source_class`), `components`, `redact`, `dedup` (`backend`, `path`/`state_file`, `max_entries`, `retention_days`), `github`, `jira`, `gitlab`, `slack`.
- Trust: `trust.source_class` (`trusted_branch`/`fork_pr`/`local_artifact`) or `HOUND_SOURCE_CLASS`; resolved from explicit/configured value first, then CI environment detection. `fork_pr` forces `offline`, keeps redaction on, and disables source context, enrichment, LLM, and delivery before any connector runs.
- Feedback store: `<out>/.hound/feedback.sqlite3` (WAL, separate from dedup state) written by `hound feedback record`; read by `hound feedback export`. Values are redacted before persistence; `--candidate-fixtures` exports explicit manual regression-fixture candidates.
- Repository-local config is not auto-discovered because analyzed repositories are untrusted input.
- Redaction: on by default; `--allow-unredacted` or `redact: false` disables.
- Dedup store: `file` (locked JSON at `<out>/.hound/state.json`, atomic `os.replace`, bounded to 1000 entries) or `sqlite` (`<out>/.hound/state.sqlite3`, WAL, atomic upserts, bounded by `max_entries` (default 50000) + `retention_days` (default 90)). HTTP state is disabled until conditional writes are supported.
- Incident keys and RCA cache validity are independent: versioned project-scoped identities preserve assertion differences; context fingerprints reject snapshots when analysis inputs change. Legacy unscoped entries remain historical records and cannot authorize automatic reuse. See the [migration contract](reference/schema-migration-v1.4-to-v2.0.md).
- LLM resilience: `max_retries` (default 3) with exponential backoff on 429/5xx; token usage captured into `meta.usage`; `max_concurrency` (default 4, `HOUND_MAX_CONCURRENCY`) throttles simultaneous in-process LLM calls during parallel `--jobs` runs.
- Server limits: `--workers` (default 4), `--max-queue` (default 64), `--rate-limit` (default 60/min/client), `--job-ttl` (default 3600s); each also settable via `HOUND_SERVER_WORKERS`/`HOUND_SERVER_MAX_QUEUE`/`HOUND_SERVER_RATE_LIMIT`/`HOUND_SERVER_JOB_TTL`.

## Failure policy

- No key / `--offline` / LLM error / malformed JSON → run fallback, tag `engine:"fallback"`, note in report.
- LLM retry exhaustion after `max_retries` → fallback.
- `analyze` exits `0` for a completed clean result, `1` for a completed result containing a CI/CD/build/test failure, `2` for invalid input/config, and `3` for internal errors.
- GitHub/Jira/GitLab ticket creation or Slack delivery failure (missing creds, HTTP error, network) → warn to stderr and return exit 3 when explicitly requested.
- Unsupported dedup backend -> configuration error before analysis.

## Fallback rules (deterministic)

- Severity: import/compile/image-pull/migration/dependency-resolution failure → critical; deployment, rollback, permission, health-check, readiness, disk-full, or TLS-certificate failure → high; API rate limiting, assertion, or timeout → medium; flaky → low.
- Priority: critical=1, high=2, medium=3, low=4; `flaky_suspect` (recurring ≥3) = 5.
- Component: match stack paths + git changed files against glob map; else `unowned`.
- Confidence: high if frame hits changed file; medium if generic match; low if unknown. See "Confidence bands and calibration" below.

## Trust policy

Every run is bound to a source class resolved from `--source-class`, YAML
`trust.source_class`, `HOUND_SOURCE_CLASS`, or CI environment detection. Profiles are
fail-closed (`src/hound/trust.py`):

| Source class | Detection | Source context | Enrichment | LLM | Delivery |
|---|---|---|---|---|---|
| `trusted_branch` | explicit, GitHub base-repo PR, or same-project GitLab MR | ✓ | ✓ | ✓ | ✓ |
| `local_artifact` | default when no CI signal | ✓ | ✓ | ✓ | ✓ |
| `fork_pr` | GitHub head-repo ≠ base-repo (missing/malformed event ⇒ fork), or cross-project GitLab MR | ✗ | ✗ | ✗ | ✗ |

`fork_pr` forces `offline`, keeps redaction on, rejects `llm.require`, and blocked
capabilities are never invoked (`meta.trust` in the report). The pipeline gates
source context, enrichment, LLM, and delivery through `Config` flags derived from
the policy.

## Feedback

`hound feedback record/export` stores reviewed engineer ratings (usefulness,
kind/severity/owner/duplicate correctness, confirmed actual outcome) in
`<out>/.hound/feedback.sqlite3` — intentionally separate from dedup state —
with `run_id`, `report_sha256`, `dedup_key`, reviewer, and timestamps for audit.
Values are redacted before persistence. Feedback never changes future
classification; `hound feedback export --candidate-fixtures` emits explicit
regression-fixture candidate manifests (`requires_manual_sanitized_artifact:
true`) that require a manual, sanitized artifact before they may join the
evaluation corpus.

## Confidence bands and calibration

Bands derive deterministically: `high` when a stack frame hits a changed file,
`medium` for a generic match, `low` otherwise. The evaluator
(`hound.eval`) calibrates the bands against the labeled corpus: for each
band it reports support, empirical stage-and-kind accuracy, mean deterministic
score, and the gap between them. Bands with zero support are provisional, and
classification correctness is a proxy until reviewed outcomes (M3 feedback)
become available. The committed `tests/eval/baseline-v1.0.json` records the
calibration snapshot.

## QA history store

`hound insights import/history/tests/stats/export` maintain a cross-run test history
in `<output-dir>/.hound/history.sqlite3`, separate from dedup and feedback
state. Rows are keyed by `(suite, leaf test, run_id, attempt)` with atomic
`ON CONFLICT DO UPDATE` upserts under WAL; concurrent writers cannot lose
updates. The `qa/model.py` identity is runner-agnostic: pytest `path::test`,
JUnit `class.method`, and JSON reports all reduce to the same leaf, so the same
logical test is tracked consistently across runners. JUnit flaky/rerun metadata
expands into attempt-numbered rows (`failed(1)` + `passed(2)`). Raw logs are
never stored — rows reference `run_id`/`evidence_id`. Retention prunes whole
rows only, so aggregates recompute without corruption; queries return
`insufficient_history` (`failure_rate=None`) until enough samples exist. Import
rejects DOCTYPE XML and symlinked sources, and import/export round-trips
sanitized records for CI cache / shared-volume workflows.

## QA quality gate

Coverage inputs are bounded and reject symlinks/DOCTYPE XML. Cobertura (including
coverage.py XML), JaCoCo, LCOV, Istanbul JSON, and dotnet/OpenCover inputs reduce
to one line/branch model. Changed-line coverage is computed only from an explicit
Git baseline and repository; missing diff evidence is represented as unavailable,
not as invented 100% coverage. SARIF results retain tool, rule, level, location,
and suppression status.

Quality policies use a versioned YAML/JSON mapping with deterministic outcomes:

```yaml
version: "1.0"
rules:
  new_failure: block
  likely_regression: block
  flaky: warn
  duration_regression: warn
  critical_sarif: block
  sarif_error: block
  sarif_warning: warn
  changed_line_coverage:
    minimum: 0.80
    outcome: block
    include: ["src/*.py"]
    exclude: ["src/generated/*"]
    max_unmapped_lines: 0
  coverage_delta:
    minimum: -0.01
    outcome: block
environments:
  staging:
    sarif_error: warn
```

Allowed outcomes are `pass`, `warn`, and `block`. Environment entries override
only named rules, and a requested environment must exist in the policy. A
configured rule whose required evidence is unavailable produces
`analysis_status: insufficient_evidence` and uses that rule's warn/block outcome;
missing or malformed evidence never becomes an implicit pass. History is used
only when `--history-db` explicitly identifies a SQLite database; Hound takes a
consistent SQLite backup and records its SHA-256 before classification. Symbolic
baseline/head refs are resolved once and the immutable commit IDs are recorded
in the result. Coverage evaluates only files selected by the policy's explicit
include/exclude globs. Unmapped lines fail closed beyond `max_unmapped_lines`;
summary-only reports cannot satisfy changed-line rules. Repeated `--coverage`
inputs form candidate coverage, while repeated `--baseline-coverage` inputs form
an independent baseline used by `coverage_delta`; they are never unioned. The
machine result reserves `analysis_status`,
`policy_outcome`, `enforced`, `reasons`, `summary`, and `defect_draft`; analysis
can succeed while policy blocks a release.

## Test strategy

- Fixtures only; no live API.
- Git tests use a fake repo fixture (committed, no network).
- LLM tested with mocked client (deterministic JSON response).
- Determinism assert: same input → same dedup_key.
- CI: `uv run pytest` (WORKFLOW verify gate).
- Evaluation corpus: versioned JSON cases in `tests/eval/cases/dev` and
  `tests/eval/cases/held_out`. `python -m hound.eval --offline --format
  json` validates labels, runs only deterministic ingest/triage code, and reports
  per-case results plus classification, extraction, dedup, redaction, throughput,
  and peak-memory baselines. Held-out labels are kept separate from development
  fixtures and are not used to tune rules in the same change.
