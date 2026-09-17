# Engine Surface Matrix

Hound exposes use cases, not every internal Python function.

| Engine capability | Skill | Plugin prompt | MCP | Intentionally internal |
|---|---:|---:|---:|---:|
| Artifact RCA, redaction, triage, ticket | Yes | Yes | `hound_analyze` | No |
| Source context, ownership, test impact | Yes | Yes | via `hound_analyze` | Low-level graph helpers |
| Deployment timeline/correlation | Yes | Yes | via `hound_analyze` | Connector implementation details |
| Command capture | Yes | Yes | `hound_log_command` | Process primitives |
| Quality gate | Yes | Yes | `hound_check_gate` | Parser internals |
| History/incident reads | Yes | Yes | insights/incidents | SQLite primitives |
| History import/export | Yes | Yes | operation-specific tools | Raw upserts |
| Report read/validation | Yes | Yes | resource + tool fallback | Schema implementation |
| Feedback | Yes | Yes | list/record tools | Raw SQL and reviewed promotion workflow |
| Evaluation | Yes | Yes | `hound_evaluate` | Scoring internals |
| Package updates, auth, model catalogs | Documentation only | Update prompt | No | Yes: administrative, not diagnosis |
| HTTP job queue/delivery ledger | Documentation only | No | No | Yes: server operations |

Exclusion keeps the agent action space bounded. New MCP tools require a user-facing diagnostic use case, a capability class, path/resource bounds, a stable envelope, and tests.
