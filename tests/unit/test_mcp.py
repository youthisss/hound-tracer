"""Unit tests for Hound Tracer Model Context Protocol (MCP) server and tools."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from hound import __version__
from hound.mcp.server import PROTOCOL_VERSION, MCPServer
from hound.mcp.tools import (
    tool_analyze,
    tool_get_insights,
    tool_list_incidents,
    tool_log_command,
)


def test_mcp_server_initialize():
    server = MCPServer()
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0"},
        },
    }
    resp = server.handle_request(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    assert resp["result"]["protocolVersion"] == PROTOCOL_VERSION
    assert resp["result"]["serverInfo"]["name"] == "hound-tracer"
    assert resp["result"]["serverInfo"]["version"] == __version__
    assert "tools" in resp["result"]["capabilities"]


def test_mcp_server_ping():
    server = MCPServer()
    req = {"jsonrpc": "2.0", "id": 42, "method": "ping"}
    resp = server.handle_request(req)
    assert resp == {"jsonrpc": "2.0", "id": 42, "result": {}}


def test_mcp_server_notification():
    server = MCPServer()
    req = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    resp = server.handle_request(req)
    assert resp is None


def test_mcp_server_tools_list():
    server = MCPServer()
    req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    resp = server.handle_request(req)
    tools = resp["result"]["tools"]
    tool_names = {t["name"] for t in tools}
    expected = {
        "hound_analyze",
        "hound_log_command",
        "hound_check_gate",
        "hound_get_insights",
        "hound_doctor",
        "hound_list_incidents",
    }
    assert expected.issubset(tool_names)
    for tool in tools:
        assert "name" in tool
        assert "description" in tool
        assert "inputSchema" in tool
        assert tool["inputSchema"]["type"] == "object"


def test_mcp_server_tools_call_doctor(tmp_path, monkeypatch):
    monkeypatch.setenv("HOUND_MCP_ROOTS", str(tmp_path))
    server = MCPServer()
    req = {
        "jsonrpc": "2.0",
        "id": 10,
        "method": "tools/call",
        "params": {
            "name": "hound_doctor",
            "arguments": {"output_dir": str(tmp_path)},
        },
    }
    resp = server.handle_request(req)
    assert resp["id"] == 10
    assert resp["result"]["isError"] is False
    content = json.loads(resp["result"]["content"][0]["text"])
    assert content["schema_version"] == "2.0"
    assert "checks" in content
    check_names = {c["name"] for c in content["checks"]}
    assert "hound" in check_names
    assert "python" in check_names


def test_mcp_server_tools_call_unknown_tool():
    server = MCPServer()
    req = {
        "jsonrpc": "2.0",
        "id": 99,
        "method": "tools/call",
        "params": {"name": "non_existent_tool", "arguments": {}},
    }
    resp = server.handle_request(req)
    assert resp["id"] == 99
    assert resp["result"]["isError"] is True
    assert "Unknown tool: non_existent_tool" in resp["result"]["content"][0]["text"]


def test_mcp_server_unknown_method():
    server = MCPServer()
    req = {"jsonrpc": "2.0", "id": 5, "method": "unsupported_method"}
    resp = server.handle_request(req)
    assert resp["id"] == 5
    assert resp["error"]["code"] == -32601


def test_mcp_server_run_loop():
    input_data = (
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}) + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}) + "\n"
    )
    in_stream = io.StringIO(input_data)
    out_stream = io.StringIO()

    server = MCPServer(stdin=in_stream, stdout=out_stream)
    exit_code = server.run()
    assert exit_code == 0

    lines = [json.loads(line) for line in out_stream.getvalue().strip().split("\n")]
    assert len(lines) == 2
    assert lines[0]["id"] == 1
    assert lines[1]["id"] == 2


def test_mcp_server_run_parse_error():
    input_data = "this is not json\n"
    in_stream = io.StringIO(input_data)
    out_stream = io.StringIO()

    server = MCPServer(stdin=in_stream, stdout=out_stream)
    exit_code = server.run()
    assert exit_code == 0

    resp = json.loads(out_stream.getvalue().strip())
    assert resp["error"]["code"] == -32700


def test_tool_analyze_single_file(tmp_path):
    fixture = Path("tests/fixtures/pytest_fail.log")
    assert fixture.exists()

    result = tool_analyze(
        artifact_path=str(fixture),
        output_dir=str(tmp_path / "hound_out"),
        offline=True,
    )
    assert result["schema_version"] == "2.0"
    assert result["failure"]["kind"] == "test_failure"
    assert "assert 5.0 == 10.0" in result["failure"]["message"]
    assert result["root_cause"]["hypothesis"]
    assert result["triage"]["severity"] == "medium"


def test_tool_analyze_non_existent():
    with pytest.raises(FileNotFoundError):
        tool_analyze(artifact_path="non_existent_file.log")


def test_tool_log_command_success(tmp_path):
    cmd = [sys.executable, "-c", "print('hello from test'); import sys; sys.exit(0)"]
    res = tool_log_command(command=cmd, output_dir=str(tmp_path))
    assert res["exit_code"] == 0
    assert Path(res["log_file"]).exists()
    assert "analysis" not in res


def test_tool_log_command_failure_analyzed(tmp_path):
    cmd = [sys.executable, "-c", "print('error occurred'); raise RuntimeError('boom')"]
    res = tool_log_command(command=cmd, output_dir=str(tmp_path), analyze_on_failure=True)
    assert res["exit_code"] != 0
    assert Path(res["log_file"]).exists()
    assert "analysis" in res
    assert res["analysis"]["failure"]["kind"] in {"test_failure", "compilation_error", "unknown", "ci_failure"}


def test_tool_get_insights_missing_store(tmp_path):
    missing_store = tmp_path / "non_existent.sqlite3"
    res = tool_get_insights(history_store=str(missing_store))
    assert res["exists"] is False
    assert "does not exist" in res["message"]


def test_tool_list_incidents_empty(tmp_path):
    empty_state = tmp_path / "state.sqlite3"
    res = tool_list_incidents(state_path=str(empty_state))
    assert "total_incidents" in res
    assert res["total_incidents"] == 0


def test_tool_log_command_timeout(tmp_path):
    cmd = [sys.executable, "-c", "import time; time.sleep(3)"]
    res = tool_log_command(command=cmd, output_dir=str(tmp_path), timeout=1)
    assert res["timed_out"] is True
    assert res["exit_code"] == 124
    assert "timed out after 1" in res["error"]
    assert Path(res["log_file"]).exists()
    assert Path(res["metadata_file"]).exists()
    assert res["metadata"]["timed_out"] is True


@pytest.mark.parametrize("payload", [[], "hello", {"jsonrpc": "1.0", "id": 1, "method": "ping"}])
def test_mcp_server_rejects_invalid_request_without_crashing(payload):
    server = MCPServer()
    resp = server.handle_request(payload)
    assert resp["error"]["code"] == -32600


@pytest.mark.parametrize("params", ["bad", []])
def test_mcp_server_rejects_non_object_params(params):
    server = MCPServer()
    resp = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": params})
    assert resp["error"]["code"] == -32602


def test_mcp_server_validates_tool_arguments():
    server = MCPServer()
    resp = server.handle_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "hound_log_command", "arguments": {"command": "pytest"}},
    })
    assert resp["result"]["isError"] is True
    assert "command must be of type array" in resp["result"]["content"][0]["text"]


def test_mcp_command_execution_requires_opt_in(monkeypatch):
    monkeypatch.delenv("HOUND_MCP_ENABLE_COMMAND_EXECUTION", raising=False)
    server = MCPServer()
    resp = server.handle_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "hound_log_command", "arguments": {"command": ["pytest"]}},
    })
    assert resp["result"]["isError"] is True
    assert "command execution is disabled" in resp["result"]["content"][0]["text"]


def test_mcp_rejects_path_outside_allowed_roots(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.log"
    outside.write_text("failure", encoding="utf-8")
    monkeypatch.setenv("HOUND_MCP_ROOTS", str(allowed))
    server = MCPServer()
    resp = server.handle_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "hound_analyze", "arguments": {"artifact_path": str(outside)}},
    })
    assert resp["result"]["isError"] is True
    assert "allowed MCP root" in resp["result"]["content"][0]["text"]


def test_bounded_failure_truncation():
    from hound.mcp.tools import _bounded_failure

    dummy_failure = {
        "kind": "test_failure",
        "stacktrace": [{"file": f"test_{i}.py", "line": i} for i in range(30)],
        "failed_tests": [{"name": f"test_{i}"} for i in range(25)],
    }
    bounded = _bounded_failure(dummy_failure)
    assert len(bounded["stacktrace"]) == 15
    assert len(bounded["failed_tests"]) == 15
    assert "Showing top 15 of 30 stack frames" in bounded["stacktrace_note"]
    assert "Showing top 15 of 25 failed tests" in bounded["failed_tests_note"]


def test_hook_post_test_failure_filtering():
    from plugins.hound.hooks.post_test_failure import on_post_execution

    # Legitimate test runner failures must trigger
    pytest_res = on_post_execution({"command": "pytest tests/unit", "exit_code": 1})
    assert pytest_res is not None
    assert pytest_res["intercepted"] is True

    npm_res = on_post_execution({"command": "npm test", "exit_code": 1})
    assert npm_res is not None
    assert npm_res["intercepted"] is True

    py_res = on_post_execution({"command": "python -m pytest tests/", "exit_code": 2})
    assert py_res is not None
    assert py_res["intercepted"] is True

    for wrapped in ("uv run pytest", "npx jest", "pnpm exec vitest", "env CI=1 pytest", "npm run test:unit"):
        wrapped_res = on_post_execution({"command": wrapped, "exit_code": 1})
        assert wrapped_res is not None, wrapped

    # False-positive candidates must NOT trigger
    grep_res = on_post_execution({"command": "grep -rn 'pytest' src/", "exit_code": 1})
    assert grep_res is None

    git_res = on_post_execution({"command": "git commit -m 'fix pytest issue'", "exit_code": 1})
    assert git_res is None

    # Success exit code must never trigger
    success_res = on_post_execution({"command": "pytest tests/", "exit_code": 0})
    assert success_res is None
