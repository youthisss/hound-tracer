# Harness Integration

Hound Tracer uses three portable surfaces:

- `skills/hound-tracer/SKILL.md` for agent instructions.
- `hound-mcp` for MCP tools installed through the Python package.
- `plugins/hound/commands/engine.md` for a capability-routed prompt that adapters can map to their native command format.

The skill is usable with native harness tools alone; CLI and TUI sessions are not prerequisites. Actual engine execution uses MCP services directly, with the Hound package installed on the server host. Native-only diagnosis must be labeled advisory rather than presented as an engine result. Respect each harness's instruction hierarchy, tool discovery, permissions, and output format.

The files in this directory are configuration examples, not interchangeable plugin manifests. Copy or merge only the example for the harness you use. Keep existing settings when merging.

## Support matrix

| Harness | Skill | MCP | Hound commands |
|---|---|---|---|
| OpenCode V2 | Native | Native | Configured prompt commands |
| Claude Code | Native | Native | Plugin command files |
| Hermes Agent | Native | Native | Skill slash command |
| Codex | Agent Skills compatible | Native | Invoke skill by name |
| Cursor | Agent Skills compatible where enabled | Native | Invoke skill by name |
| Antigravity | Install skill using its current skill directory | MCP config varies by release | Invoke skill by name |

## Security defaults

All examples restrict Hound to the current workspace with `HOUND_MCP_ROOTS=.`. They do not enable `hound_log_command`. Add `HOUND_MCP_ENABLE_COMMAND_EXECUTION=1` only when the harness permission policy asks before running MCP tools.

## MCP and hook contracts

The MCP tools map to existing Hound services. Analysis accepts `repo_dir` for
source/git context; quality gates accept `history_store`; insights and incidents
accept `output_dir` for locating stores from non-default runs. Command capture
returns the analysis directory on failure. Check `exit_code` and `timed_out`
before interpreting a successful MCP response as a successful command.

The reference plugin hook accepts a JSON object on stdin with `command` (string)
and `exit_code` (integer). It emits a JSON recommendation only for failed
test/build commands, without echoing command arguments. Harness adapters must
map their native event payload to this contract.

## Updating

- Git checkout: update the repository normally. Harnesses that reference `./skills` see the new skill immediately or after reload.
- Hermes registry or URL install: run `/skills update` or `hermes skills update`.
- Published Python package: use the same package manager that installed Hound. Review the target version before upgrading.
- Do not let an agent replace harness configuration or update packages without user confirmation.

## Installer

After installing the Python package, detect and configure supported harnesses:

```console
hound install all --for opencode --dry-run
hound install all --for opencode
```

Use `--scope project` to write project-local skills and configuration. The default
scope is global. Existing JSON or JSONC configuration is backed up before Hound
merges its entries. Hound also offers this setup once before opening its terminal
interface for the first time.
