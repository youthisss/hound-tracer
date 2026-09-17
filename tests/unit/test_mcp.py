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
    content = json.loads(resp["result"]["content"][0]["text"])["data"]
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
    assert (Path(res["analysis"]["raw_output_dir"]) / "report.json").is_file()
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
    monkeypatch.setenv("HOUND_MCP_MODE", "execute")
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


@pytest.mark.parametrize("name,arguments", [
    ("hound_log_command", {"command": []}),
    ("hound_log_command", {"command": [""]}),
    ("hound_log_command", {"command": ["pytest"], "timeout": float("nan")}),
    ("hound_get_insights", {"window_days": 0}),
    ("hound_list_incidents", {"limit": -1}),
])
def test_mcp_rejects_invalid_bounds_before_dispatch(name, arguments, monkeypatch):
    def unexpected_dispatch(*args):
        pytest.fail("invalid input reached dispatch")

    monkeypatch.setattr("hound.mcp.server.dispatch_tool", unexpected_dispatch)
    resp = MCPServer().handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    })
    assert resp["result"]["isError"] is True


def test_mcp_schema_covers_service_parameters():
    import inspect
    from hound.mcp import tools
    from hound.mcp.server import TOOL_DEFINITIONS

    for definition in TOOL_DEFINITIONS:
        handler = getattr(tools, definition["name"].replace("hound_", "tool_", 1))
        assert set(definition["inputSchema"]["properties"]) == set(inspect.signature(handler).parameters)


def test_mcp_analysis_repository_is_scoped(tmp_path, monkeypatch):
    monkeypatch.setenv("HOUND_MCP_ROOTS", str(tmp_path))
    resp = MCPServer().handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "hound_analyze", "arguments": {
            "artifact_path": str(tmp_path / "failure.log"), "repo_dir": str(tmp_path.parent),
        }},
    })
    assert resp["result"]["isError"] is True
    assert "repo_dir must be within" in resp["result"]["content"][0]["text"]


def test_hook_script_reads_real_input_without_echoing_secrets():
    import subprocess

    script = "plugins/hound/hooks/post_test_failure.py"
    result = subprocess.run(
        [sys.executable, script],
        input=json.dumps({"command": "pytest --token=private-value", "exit_code": 1}),
        text=True, capture_output=True, check=True,
    )
    assert json.loads(result.stdout)["action"] == "recommend_hound_analysis"
    assert "private-value" not in result.stdout
    success = subprocess.run(
        [sys.executable, script], input='{"command":"pytest","exit_code":0}',
        text=True, capture_output=True, check=True,
    )
    assert success.stdout == ""


def test_engine_report_validation_and_feedback(tmp_path, monkeypatch):
    from hound.mcp.tools import tool_feedback, tool_read_report, tool_validate_report

    output = tmp_path / "run"
    result = tool_analyze("tests/fixtures/pytest_fail.log", output_dir=str(output))
    assert "ticket" in result["available_sections"]
    report = str(output / "report.json")
    selected = tool_read_report(report, section="failure")
    assert set(selected["report"]) == {"failure"}
    assert "ticket" in selected["sections"]
    validation = tool_validate_report(report, output_dir=str(tmp_path))
    assert validation["status"] in {"PASS", "WARN"}
    assert not (tmp_path / ".hound" / "validations.sqlite3").exists()
    store = str(tmp_path / "feedback.sqlite3")
    record = tool_feedback("record", store, report, "run", usefulness="useful")
    assert record["review_status"] == "pending"
    assert tool_feedback("list", store)["count"] == 1
    with pytest.raises(ValueError, match="no section"):
        tool_read_report(report, section="missing")


def test_engine_history_interchange(tmp_path):
    from hound.mcp.tools import tool_history_transfer

    source = tmp_path / "input.json"
    source.write_text(json.dumps({"records": [{"suite": "suite", "test": "test", "status": "passed", "run_id": "run"}]}))
    store = str(tmp_path / "history.sqlite3")
    assert tool_history_transfer("import", store, str(source))["count"] == 1
    target = tmp_path / "export.json"
    assert tool_history_transfer("export", store, str(target))["count"] == 1
    assert json.loads(target.read_text())["records"][0]["status"] == "passed"


def test_engine_evaluation_dispatches_without_cli(monkeypatch):
    from hound.mcp.tools import tool_evaluate

    calls = []

    def evaluate(*, corpus, suite):
        calls.append((corpus, suite))
        return {"evaluated": 1}

    monkeypatch.setattr("hound.eval.evaluate", evaluate)
    assert tool_evaluate("tests/eval/cases", "dev") == {"evaluated": 1}
    assert calls == [(Path("tests/eval/cases"), "dev")]


def test_mcp_exposes_resources_prompts_and_envelope(tmp_path, monkeypatch):
    monkeypatch.setenv("HOUND_MCP_ROOTS", str(tmp_path))
    server = MCPServer()
    initialized = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert set(initialized["result"]["capabilities"]) == {"tools", "resources", "prompts"}
    templates = server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "resources/templates/list"})
    assert templates["result"]["resourceTemplates"][0]["uriTemplate"].startswith("hound://report")
    prompts = server.handle_request({"jsonrpc": "2.0", "id": 3, "method": "prompts/list"})
    assert prompts["result"]["prompts"][0]["name"] == "hound_diagnose_failure"
    doctor = server.handle_request({
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "hound_doctor", "arguments": {"output_dir": str(tmp_path)}},
    })
    envelope = json.loads(doctor["result"]["content"][0]["text"])
    assert set(envelope) == {"status", "summary", "data", "artifacts", "next_actions"}


def test_mcp_capability_modes(tmp_path, monkeypatch):
    monkeypatch.setenv("HOUND_MCP_ROOTS", str(tmp_path))
    monkeypatch.setenv("HOUND_MCP_MODE", "diagnostic")
    denied = MCPServer().handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "hound_history_export", "arguments": {
            "history_store": str(tmp_path / "history.db"), "transfer_path": str(tmp_path / "history.json"),
        }},
    })
    payload = json.loads(denied["result"]["content"][0]["text"])
    assert payload["status"] == "error"
    assert "HOUND_MCP_MODE=write" in payload["summary"]


def test_analyze_directory_artifact_limit(tmp_path):
    from hound.mcp.tools import tool_analyze

    for index in range(2):
        (tmp_path / f"failure-{index}.log").write_text("FAILED test_x - assert 1 == 2")
    with pytest.raises(ValueError, match="maximum is 1"):
        tool_analyze(str(tmp_path), output_dir=str(tmp_path / "out"), max_artifacts=1)


@pytest.mark.parametrize("name,arguments", [
    ("hound_read_report", {"report_path": "outside.json"}),
    ("hound_validate_report", {"report_path": "outside.json"}),
    ("hound_history_transfer", {"action": "import", "history_store": "outside.db", "transfer_path": "outside.json"}),
    ("hound_feedback", {"action": "list", "feedback_store": "outside.db"}),
    ("hound_evaluate", {"corpus_path": "outside"}),
])
def test_engine_tools_enforce_roots(name, arguments, tmp_path, monkeypatch):
    monkeypatch.setenv("HOUND_MCP_ROOTS", str(tmp_path))
    response = MCPServer().handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    })
    assert response["result"]["isError"] is True
    assert "allowed MCP root" in response["result"]["content"][0]["text"]
