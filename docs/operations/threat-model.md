# Threat Model

Hound is an advisory failure-analysis tool. Its analysis and infrastructure
connectors are observational and read-only, while explicit local command runners execute
operator-selected, checkout-controlled code with the Hound process permissions. Logs,
repositories, structured artifacts, provider responses, delivery responses, and
fork pull requests are separate trust boundaries. Offline analysis is the safest
default and requires no outbound network access.

## Assets

- failure artifacts and repository source, which may contain credentials or PII
- provider, tracker, webhook, cluster, and server bearer credentials
- reports and SQLite state under the configured output directory
- CI identities, OIDC publication authority, and immutable release artifacts

## Threats And Controls

| Threat | Boundary and controls | Evidence | Residual risk |
|---|---|---|---|
| Malicious or oversized logs | Inputs are size-bounded, parsed without code execution, redacted before reports or prompts, and terminal control characters are sanitized. | `tests/unit/test_production.py`, `tests/unit/test_review_fixes.py` | Novel secret formats may require new redactors. |
| Structured artifact abuse | XML disables external entities; JSON/XML/SARIF reads are bounded; malformed encodings fail safely. | `tests/unit/test_tests.py`, `tests/integration/test_qa_gate.py`, `tests/e2e/test_eval.py` | Compressed archives are not accepted. |
| Path traversal and symlinks | Server, source, config, and connector paths are resolved under trusted roots; escaping symlinks are rejected. | `tests/integration/test_server_http.py`, `tests/integration/test_source_context.py` | Operators must choose trusted roots. |
| Untrusted fork artifacts | `fork_pr` trust policy disables LLM, source context, enrichment, and delivery before optional work begins. | `tests/unit/test_trust.py` | CI must classify fork provenance correctly. |
| Prompt injection | Artifact text is delimited, redacted, bounded, and treated as evidence rather than instruction; deterministic facts constrain merging. | `tests/unit/test_cost_control.py`, `tests/unit/test_rca.py` | Model output is probabilistic and remains advisory. |
| Provider response injection | Provider output is schema-validated and bounded; redirects are blocked; retries and calls are capped; raw responses are not persisted. | `tests/unit/test_providers.py`, `tests/unit/test_cost_control.py` | A trusted provider still receives the explicitly enabled prompt. |
| Delivery response injection or ambiguity | Delivery is opt-in; external errors are not report evidence; a WAL ledger distinguishes confirmed, failed, pending, and unknown outcomes and blocks ambiguous retries. | `tests/integration/test_delivery_ledger.py`, `tests/unit/test_output.py` | Unknown outcomes require operator reconciliation. |
| Server exposure | HTTP binds only to loopback, authenticates before workload rate limiting, bounds requests and queues, and exposes payload-free authenticated statistics. TLS and shared rate limiting belong at the proxy. | `tests/integration/test_server_http.py`, `docs/guides/server-deployment.md` | Process-local rate limits reset on restart. |
| Persistent-state exposure or corruption | SQLite uses WAL and bounded retention; raw logs are excluded; corrupt legacy state is preserved for recovery. Backups remain operator-controlled sensitive data. | `tests/integration/test_dedup.py`, `tests/integration/test_qa_history.py` | Host filesystem permissions and backup encryption are external controls. |
| CI/release authority abuse | Actions are SHA-pinned, default permissions are read-only, publication uses isolated OIDC jobs and environments, and tag/version equality is enforced. | `.github/workflows/ci.yml`, `.github/workflows/release.yml` | Environment reviewers and tag rulesets are GitHub settings. |
| Container escape or credential inclusion | Main runtime is non-root, build context excludes local secrets/state, base images are digest-pinned, and images are scanned before release. | `Dockerfile`, `Dockerfile.action`, `.dockerignore` | The Action starts as root only to normalize mounted workspace ownership, then executes Hound as UID 10001. |
| Project command execution | Explicit operator action; no shell; immutable cwd and command request; mandatory timeout; process-tree cancellation; aggregate output cap; redacted argv and output; atomic non-symlink run records. | `tests/integration/test_log_collector.py`, `tests/e2e/test_tui.py` | Execution is not sandboxed. Project hooks and child processes can access ambient files, credentials, and network with the caller's permissions. Run only trusted checkouts or isolate Hound externally. |
| Scheduled provider canary | Manual or scheduled protected workflow | Sanitized fixture and generic protected provider credential | Separate workflow, no production logs; repository variables select the provider endpoint and model. |

## Outbound Network Inventory

| Path | Opt-in condition | Data and credentials | Protections |
|---|---|---|---|
| OpenAI-compatible provider | LLM enabled, trusted source, not `--offline` | Redacted bounded prompt; provider API key from environment/keyring | HTTPS or loopback, redirect block, timeout, strict attempt cap |
| Provider model discovery | Explicit provider listing/discovery | Provider credential; no artifact body | Same URL and redirect policy |
| GitHub/Jira/GitLab delivery | Explicit destination and delivery command | Redacted ticket draft; destination credential | Trust policy, idempotency ledger, bounded timeout |
| Slack delivery | Explicit webhook delivery | Redacted bounded summary; webhook secret | HTTPS validation and delivery ledger |
| Prometheus/Tempo connector | Explicit enrichment, trusted source, configured endpoint | Bounded query identifiers; endpoint credentials | Read-only queries, timeout, response bounds, redirect block |
| Kubernetes/Helm connector | Explicit enrichment and trusted repository | Read-only subprocess arguments and cluster credential inherited from environment | Command allowlist, trusted executable resolution, bounded output |

`--offline` prevents provider and delivery traffic. The `fork_pr` trust profile
also disables all optional outbound paths. Hound emits no product analytics or
background telemetry.
