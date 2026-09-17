"""Model Context Protocol (MCP) stdio JSON-RPC 2.0 server for Hound Tracer."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import sys
from typing import Any, TextIO, cast

from hound import __version__
from hound.mcp.tools import (
    tool_analyze,
    tool_check_gate,
    tool_doctor,
    tool_get_insights,
    tool_list_incidents,
    tool_log_command,
)

logger = logging.getLogger("hound.mcp")

PROTOCOL_VERSION = "2024-11-05"

TOOL_DEFINITIONS = [
    {
        "name": "hound_analyze",
        "description": (
            "Investigate CI/CD, build, test, and container failure artifacts (.log, JUnit .xml, .sarif, .json). "
            "Returns root cause analysis (RCA Schema v2.0), stacktrace framing, and remediation advice "
            "with default offline-first deterministic rules and automated secret redaction."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "artifact_path": {
                    "type": "string",
                    "description": "Path to failure log, JUnit XML, SARIF report, or directory of artifacts.",
                },
                "output_dir": {
                    "type": "string",
                    "description": "Directory where analysis artifacts (report.json, ticket.md) will be written.",
                    "default": "hound-output",
                },
                "offline": {
                    "type": "boolean",
                    "description": "If true (default), runs deterministic local rules without calling external LLMs.",
                    "default": True,
                },
                "source_context": {
                    "type": "boolean",
                    "description": "Extract relevant local repository code context (trusted repos only).",
                    "default": False,
                },
                "enrich": {
                    "type": "boolean",
                    "description": "Enrich analysis with git history and blame correlation.",
                    "default": False,
                },
            },
            "required": ["artifact_path"],
        },
    },
    {
        "name": "hound_log_command",
        "description": (
            "Run a test or build command (e.g. ['pytest', 'tests/']), redact secrets on-the-fly, "
            "and automatically perform Hound RCA analysis if the command exits with a failure."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Command and arguments to execute as a list, e.g. ['pytest', 'tests/unit'].",
                },
                "cwd": {
                    "type": "string",
                    "description": "Optional working directory for command execution.",
                },
                "analyze_on_failure": {
                    "type": "boolean",
                    "description": "Whether to auto-run Hound analysis if exit code != 0.",
                    "default": True,
                },
                "output_dir": {
                    "type": "string",
                    "description": "Directory where logs and diagnostic output will be saved.",
                    "default": "hound-output",
                },
                "timeout": {
                    "type": "number",
                    "description": "Maximum execution time in seconds before terminating the command.",
                    "default": 120.0,
                    "minimum": 1,
                    "maximum": 3600,
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "hound_check_gate",
        "description": (
            "Evaluate test evidence, code coverage, and security SARIF reports against a quality gate policy."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_path": {
                    "type": "string",
                    "description": "Path to test artifact or directory containing test results.",
                },
                "baseline": {
                    "type": "string",
                    "description": "Git baseline reference (e.g. 'origin/main' or 'HEAD~1').",
                    "default": "HEAD~1",
                },
                "head": {
                    "type": "string",
                    "description": "Git candidate head reference.",
                    "default": "HEAD",
                },
                "repo_path": {
                    "type": "string",
                    "description": "Path to git repository root.",
                    "default": ".",
                },
                "policy_path": {
                    "type": "string",
                    "description": "Path to custom YAML quality gate policy file.",
                },
                "coverage_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional paths to coverage reports (e.g. coverage.xml).",
                },
                "sarif_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional paths to SARIF vulnerability reports.",
                },
                "enforced": {
                    "type": "boolean",
                    "description": "Whether to enforce strict blocking policy outcome.",
                    "default": False,
                },
            },
            "required": ["source_path"],
        },
    },
    {
        "name": "hound_get_insights",
        "description": (
            "Query test execution history, flakiness rate, failure counts, and p95 duration statistics "
            "from Hound's local SQLite test history database."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["stats", "history", "tests"],
                    "description": "Action to perform: 'stats' (flakiness & duration), 'history' (recent runs), or 'tests' (list tracked).",
                    "default": "stats",
                },
                "test_name": {
                    "type": "string",
                    "description": "Test identifier, e.g. 'test_module.py::test_case'.",
                },
                "window_days": {
                    "type": "integer",
                    "description": "Number of days in the past to query (default 30).",
                    "default": 30,
                },
                "history_store": {
                    "type": "string",
                    "description": "Optional path to SQLite history store file.",
                },
            },
        },
    },
    {
        "name": "hound_doctor",
        "description": (
            "Check local environment readiness for Hound Tracer (Python runtime, git, docker, kubectl, "
            "configuration integrity, and output filesystem accessibility) without leaking credentials."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "output_dir": {
                    "type": "string",
                    "description": "Output directory to test write permissions.",
                    "default": "hound-output",
                },
                "config_path": {
                    "type": "string",
                    "description": "Optional custom config file to validate.",
                },
            },
        },
    },
    {
        "name": "hound_list_incidents",
        "description": (
            "Inspect deduplicated failure incidents, fingerprint hashes, recurrence counts, and cached RCA snapshots."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "state_path": {
                    "type": "string",
                    "description": "Path to dedup state store (.hound/state.sqlite3 or .hound/state.json).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of incidents to return.",
                    "default": 50,
                },
            },
        },
    },
]


def dispatch_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Dispatch tool call linearly to the corresponding Hound service."""
    if name == "hound_analyze":
        return tool_analyze(**arguments)
    elif name == "hound_log_command":
        return tool_log_command(**arguments)
    elif name == "hound_check_gate":
        return tool_check_gate(**arguments)
    elif name == "hound_get_insights":
        return tool_get_insights(**arguments)
    elif name == "hound_doctor":
        return tool_doctor(**arguments)
    elif name == "hound_list_incidents":
        return tool_list_incidents(**arguments)
    else:
        raise ValueError(f"Unknown tool: {name}")


def _invalid_request(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _validate_value(value: Any, schema: dict[str, Any], field: str) -> None:
    expected = schema.get("type")
    expected_key = expected if isinstance(expected, str) else ""
    valid = {
        "string": isinstance(value, str),
        "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "array": isinstance(value, list),
        "object": isinstance(value, dict),
    }.get(expected_key, True)
    if not valid:
        raise ValueError(f"{field} must be of type {expected}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{field} must be one of {schema['enum']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise ValueError(f"{field} must be at least {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            raise ValueError(f"{field} must be at most {schema['maximum']}")
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            _validate_value(item, schema["items"], f"{field}[{index}]")


def _validate_tool_arguments(name: str, arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be an object")
    definition = next((item for item in TOOL_DEFINITIONS if item["name"] == name), None)
    if definition is None:
        raise ValueError(f"Unknown tool: {name}")
    schema = cast(dict[str, Any], definition["inputSchema"])
    properties = schema.get("properties", {})
    missing = [key for key in schema.get("required", []) if key not in arguments]
    if missing:
        raise ValueError(f"missing required argument: {missing[0]}")
    unknown = sorted(set(arguments) - set(properties))
    if unknown:
        raise ValueError(f"unknown argument: {unknown[0]}")
    for key, value in arguments.items():
        _validate_value(value, properties[key], key)
    _enforce_mcp_boundaries(name, arguments)
    return arguments


def _allowed_roots() -> tuple[Path, ...]:
    configured = os.environ.get("HOUND_MCP_ROOTS")
    values = configured.split(os.pathsep) if configured else [str(Path.cwd())]
    return tuple(Path(value).expanduser().resolve() for value in values if value)


def _path_is_allowed(value: str, roots: tuple[Path, ...]) -> bool:
    candidate = Path(value).expanduser().resolve()
    return any(candidate == root or root in candidate.parents for root in roots)


def _enforce_mcp_boundaries(name: str, arguments: dict[str, Any]) -> None:
    if name == "hound_log_command" and os.environ.get("HOUND_MCP_ENABLE_COMMAND_EXECUTION") != "1":
        raise PermissionError(
            "command execution is disabled; set HOUND_MCP_ENABLE_COMMAND_EXECUTION=1 in the MCP server environment"
        )

    path_fields = {
        "artifact_path", "output_dir", "cwd", "source_path", "repo_path",
        "policy_path", "history_store", "config_path", "state_path",
    }
    roots = _allowed_roots()
    for field in path_fields:
        value = arguments.get(field)
        if isinstance(value, str) and not _path_is_allowed(value, roots):
            raise PermissionError(f"{field} must be within an allowed MCP root")
    for field in ("coverage_paths", "sarif_paths"):
        for value in arguments.get(field) or []:
            if not _path_is_allowed(value, roots):
                raise PermissionError(f"{field} entries must be within an allowed MCP root")


def _bounded_result(value: Any, depth: int = 0) -> Any:
    if depth >= 8:
        return "[truncated: maximum nesting depth]"
    if isinstance(value, str):
        return value if len(value) <= 4000 else value[:4000] + "...[truncated]"
    if isinstance(value, list):
        items = [_bounded_result(item, depth + 1) for item in value[:50]]
        if len(value) > 50:
            items.append({"truncated_items": len(value) - 50})
        return items
    if isinstance(value, dict):
        return {
            str(key): _bounded_result(item, depth + 1)
            for key, item in list(value.items())[:100]
        }
    return value


class MCPServer:
    """Stdio JSON-RPC 2.0 Model Context Protocol Server for Hound Tracer."""

    def __init__(self, stdin: TextIO | None = None, stdout: TextIO | None = None) -> None:
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout

    def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(request, dict):
            return _invalid_request(None, -32600, "Invalid Request: expected an object")
        req_id = request.get("id")
        method = request.get("method")
        raw_params = request.get("params")
        params = {} if raw_params is None else raw_params

        if request.get("jsonrpc") != "2.0" or not isinstance(method, str):
            return _invalid_request(req_id, -32600, "Invalid Request")
        if not isinstance(params, dict):
            return _invalid_request(req_id, -32602, "Invalid params: expected an object")

        # Handle notifications (requests without an ID)
        if req_id is None:
            if method == "notifications/initialized":
                logger.info("MCP client acknowledged initialized notification")
            return None

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {
                        "tools": {},
                    },
                    "serverInfo": {
                        "name": "hound-tracer",
                        "version": __version__,
                    },
                },
            }

        elif method == "ping":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {},
            }

        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": TOOL_DEFINITIONS,
                },
            }

        elif method == "tools/call":
            tool_name = params.get("name")
            if not isinstance(tool_name, str):
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32602,
                        "message": "Missing or invalid tool name",
                    },
                }
            raw_arguments = params.get("arguments")
            arguments = {} if raw_arguments is None else raw_arguments
            try:
                arguments = _validate_tool_arguments(tool_name, arguments)
                result_data = dispatch_tool(tool_name, arguments)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(_bounded_result(result_data), indent=2, ensure_ascii=False),
                            }
                        ],
                        "isError": False,
                    },
                }
            except (TypeError, ValueError, FileNotFoundError, PermissionError) as exc:
                logger.info("Rejected tool call %s: %s", tool_name, exc)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Invalid tool request: {exc}"}],
                        "isError": True,
                    },
                }
            except Exception:
                logger.exception("Error executing tool %s", tool_name)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": f"Error executing {tool_name}. Check the local Hound diagnostic log.",
                            }
                        ],
                        "isError": True,
                    },
                }

        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}",
                },
            }

    def run(self) -> int:
        """Run the main event loop reading line-delimited JSON-RPC from stdin."""
        for line in self.stdin:
            clean_line = line.strip()
            if not clean_line:
                continue

            try:
                request = json.loads(clean_line)
            except json.JSONDecodeError as exc:
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": f"Parse error: {exc}",
                    },
                }
                self.stdout.write(json.dumps(err_resp) + "\n")
                self.stdout.flush()
                continue

            response = self.handle_request(request)
            if response is not None:
                self.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                self.stdout.flush()

        return 0


def run_server(stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    """Start and run the Hound MCP stdio service."""
    if stdin is None and hasattr(sys.stdin, "reconfigure"):
        try:
            sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if stdout is None and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    server = MCPServer(stdin=stdin, stdout=stdout)
    return server.run()
