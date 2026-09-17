---
command: "/hound:update"
description: "Inspect the Hound installation and prepare a confirmed update command."
usage: "/hound:update [check]"
---

# Hound Update Command

Updates are separate from diagnostic use. For skill-only installs, use the host harness's skill update mechanism; do not require a Hound executable. For MCP, inspect server version/status through the client and update only the server's actual installation source. The CLI checks below apply only to local package installs.

When the user runs `/hound:update`:

1. Run `hound --version` and identify whether Hound came from a Git checkout, `pip`, `pipx`, `uv tool`, or another package manager.
2. Determine the available target version using that installation source. Do not query unrelated registries.
3. Show the current version, target version, source, exact update command, and affected skill or harness configuration.
4. Ask for confirmation before changing packages, Git state, skills, or configuration.
5. After approval, use the original package manager. Never replace uncommitted repository files.
6. Verify with `hound --version`, `hound doctor --json`, and the harness MCP status command.

For Hermes skill installs tracked by URL or registry, use `/skills update`. For a local checkout referenced by OpenCode, Codex, Cursor, Claude Code, or Antigravity, update the checkout and reload the harness.
