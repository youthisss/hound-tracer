"""Integration tests for Hound Tracer MCP CLI over subprocess stdio."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


def test_mcp_cli_stdio_lifecycle(tmp_path):
    env = dict(sys.modules["os"].environ)
    env["PYTHONPATH"] = "src"
    env["HOUND_MCP_ROOTS"] = os.pathsep.join([str(Path.cwd()), str(tmp_path)])

    cmd = [sys.executable, "-m", "hound.cli", "mcp"]
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    # 1. initialize
    init_msg = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-agent", "version": "1.0"},
        },
    }) + "\n"
    proc.stdin.write(init_msg)
    proc.stdin.flush()

    init_line = proc.stdout.readline()
    init_resp = json.loads(init_line)
    assert init_resp["id"] == 1
    assert init_resp["result"]["serverInfo"]["name"] == "hound-tracer"

    # 2. notification initialized
    notif_msg = json.dumps({
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
    }) + "\n"
    proc.stdin.write(notif_msg)
    proc.stdin.flush()

    # 3. tools/call hound_doctor
    doc_msg = json.dumps({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "hound_doctor",
            "arguments": {"output_dir": str(tmp_path / "doctor_out")},
        },
    }) + "\n"
    proc.stdin.write(doc_msg)
    proc.stdin.flush()

    doc_line = proc.stdout.readline()
    doc_resp = json.loads(doc_line)
    assert doc_resp["id"] == 2
    assert doc_resp["result"]["isError"] is False
    doc_content = json.loads(doc_resp["result"]["content"][0]["text"])["data"]
    assert doc_content["schema_version"] == "2.0"

    # 4. tools/call hound_analyze on pytest_fail.log
    analyze_msg = json.dumps({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "hound_analyze",
            "arguments": {
                "artifact_path": "tests/fixtures/pytest_fail.log",
                "output_dir": str(tmp_path / "hound_out"),
                "offline": True,
            },
        },
    }) + "\n"
    proc.stdin.write(analyze_msg)
    proc.stdin.flush()

    analyze_line = proc.stdout.readline()
    analyze_resp = json.loads(analyze_line)
    assert analyze_resp["id"] == 3
    assert analyze_resp["result"]["isError"] is False
    analysis = json.loads(analyze_resp["result"]["content"][0]["text"])["data"]
    assert analysis["failure"]["kind"] == "test_failure"

    # Close stdin to terminate loop
    proc.stdin.close()
    proc.wait(timeout=5)
    assert proc.returncode == 0
