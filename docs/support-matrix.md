# Support matrix

This matrix describes the tested contract, not an unverified guarantee for every
host or provider. External provider, cluster, Docker, and publication checks are
separate release gates.

| Surface | Python / runtime | Operating system | Required external runtime | Status |
|---|---|---|---|---|
| CLI and library | CPython `>=3.10,<3.14` | Windows, Linux | None for `--offline` | Supported by targeted local tests; compatibility matrix is defined in CI |
| CLI and library | CPython `>=3.10,<3.14` | macOS | None for `--offline` | Expected portable; macOS runner evidence pending |
| TUI | CPython `>=3.10,<3.14` | Windows, Linux | Terminal with text input and color support | Supported; headless Textual tests cover critical paths |
| HTTP server | CPython `>=3.10,<3.14` | Windows, Linux | Reverse proxy for TLS when remote | Supported on loopback; multi-instance limiting is not provided |
| Docker runtime | Python 3.11 image | Linux container host | Docker or compatible OCI runtime | CI/release gate; Docker is unavailable in the current workspace |
| GitHub Action | Docker-capable Linux runner | GitHub-hosted or self-hosted Linux | `GITHUB_WORKSPACE`, `GITHUB_OUTPUT` | Contract documented; image execution is CI/release gated |
| LLM providers | Any supported Python runtime | Windows, Linux, macOS | Explicit endpoint and credentials | Optional; provider availability and model behavior are not local release evidence |
| Kubernetes/Helm enrichment | Any supported Python runtime | Windows, Linux | `kubectl`/`helm`, trusted context | Optional read-only collector; live-cluster sandbox is not a default gate |

## Boundaries and limits

- Offline analysis does not require network access, credentials, Docker, Git, or
  a cluster.
- The built-in server binds to loopback only. TLS, public ingress, and shared
  rate limiting belong to a controlled reverse proxy.
- GitHub Action inputs and output paths must remain under `GITHUB_WORKSPACE`.
- The supported Python range is intentionally strict because dependency and TUI
  compatibility outside it is not tested.
- A platform is not marked release-verified merely because the implementation is
  expected to be portable; its runner evidence must be attached to the release
  record.
