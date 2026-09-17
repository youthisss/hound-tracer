# MCP SDK Migration Decision

The current stdio server remains a small, dependency-free compatibility adapter for the repository's existing Python and packaging contract. It now exposes tools, report resources, prompts, structured output schemas, capability policy, and protocol lifecycle tests.

The official Python SDK v2 is the target adapter. Its 2026 line requires a protocol/transport migration and adds a runtime dependency, so it should not be mixed into the same behavioral refactor without compatibility fixtures for every supported harness. Engine handlers in `src/hound/mcp/tools.py` are transport-independent to keep that migration mechanical.

Migration exit criteria:

1. Pin an official `mcp` v2 range compatible with Python 3.10-3.13.
2. Run the official SDK client against stdio and Streamable HTTP adapters.
3. Preserve tool names, schemas, response envelopes, resources, prompts, and capability gates.
4. Validate OpenCode, Claude, Codex, Cursor, Hermes, and Antigravity fixtures.
5. Remove the manual JSON-RPC adapter only after the same compatibility suite passes.

Until then, the manual adapter is explicitly compatibility code, not an independent engine implementation.
