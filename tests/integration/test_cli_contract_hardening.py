from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from hound.cli import main
from hound.output.report import ensure_outdir
from hound.output.delivery import DeliveryLedger
from hound.models import Artifacts
from hound.triage import dedup


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_cli_history_export_round_trips_through_insights_import(tmp_path, capsys) -> None:
    source = FIXTURES / "junit_flaky.xml"
    first = tmp_path / "first"
    second = tmp_path / "second"
    export_path = tmp_path / "history.json"

    assert main([
        "insights", "import", str(source), "--run-id", "run-one",
        "--output-dir", str(first), "--test-runner", "junit",
    ]) == 0
    capsys.readouterr()
    assert main([
        "insights", "export", "--output-dir", str(first), "--output", str(export_path),
    ]) == 0
    capsys.readouterr()
    assert main([
        "insights", "import", str(export_path), "--run-id", "manifest-run",
        "--output-dir", str(second),
    ]) == 0
    imported = json.loads(capsys.readouterr().out)

    assert imported["imported"] >= 1
    assert (second / ".hound" / "history.sqlite3").is_file()


def test_clean_accepts_hound_qa_and_delivery_stores(tmp_path) -> None:
    output = ensure_outdir(tmp_path / "output")
    state = output / ".hound"
    state.mkdir()
    for name in (
        "history.sqlite3", "history.sqlite3-wal", "history.sqlite3-shm",
        "deliveries.sqlite3", "deliveries.sqlite3-wal", "deliveries.sqlite3-shm",
    ):
        (state / name).write_bytes(b"")
    recovery = state / "history.sqlite3.corrupt-123"
    recovery.mkdir()
    (recovery / "history.sqlite3").write_bytes(b"")

    assert main(["clean", "--output-dir", str(output), "--yes"]) == 0
    assert not output.exists()


def test_doctor_rejects_python_outside_supported_range(tmp_path, monkeypatch, capsys) -> None:
    import hound.cli as cli

    monkeypatch.setattr(cli.sys, "version_info", SimpleNamespace(major=3, minor=14, micro=0))

    assert main(["doctor", "--output-dir", str(tmp_path / "doctor"), "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    python_check = next(item for item in payload["checks"] if item["name"] == "python")
    assert python_check["ok"] is False
    assert "requires >=3.10,<3.14" in python_check["detail"]


def test_cli_delivery_admin_commands_are_explicit(tmp_path, capsys) -> None:
    output = ensure_outdir(tmp_path / "output")
    ledger = DeliveryLedger(output / ".hound" / "deliveries.sqlite3")
    assert ledger.reserve("incident", "jira") is True
    ledger.fail("incident", "jira", "known rejection")

    assert main(["delivery", "list", "--output-dir", str(output), "--json"]) == 0
    listing = json.loads(capsys.readouterr().out)
    assert listing["records"][0]["state"] == "failed"

    assert main([
        "delivery", "retry-failed", "--output-dir", str(output),
        "--incident-key", "incident", "--destination", "jira", "--json",
    ]) == 0
    retried = json.loads(capsys.readouterr().out)
    assert retried["state"] == "pending"


def test_cli_mark_failed_requires_explicit_absence_confirmation(tmp_path, capsys) -> None:
    output = ensure_outdir(tmp_path / "output")
    ledger = DeliveryLedger(output / ".hound" / "deliveries.sqlite3")
    assert ledger.reserve("incident", "slack") is True
    ledger.mark_unknown("incident", "slack", "ambiguous")

    assert main([
        "delivery", "mark-failed", "--output-dir", str(output),
        "--incident-key", "incident", "--destination", "slack",
        "--error", "checked remote and object is absent", "--json",
    ]) == 2
    assert "confirm-absent" in capsys.readouterr().err

    assert main([
        "delivery", "mark-failed", "--output-dir", str(output),
        "--incident-key", "incident", "--destination", "slack",
        "--error", "checked remote and object is absent", "--confirm-absent", "--json",
    ]) == 0
    marked = json.loads(capsys.readouterr().out)
    assert marked["state"] == "failed"


def test_cli_incident_admin_preserves_history_and_invalidates_snapshot(tmp_path, capsys) -> None:
    output = ensure_outdir(tmp_path / "output")
    state = output / ".hound" / "state.json"
    dedup.configure_store("file")
    artifacts = Artifacts(stage="test", kind="test_failure", message="assert 1 == 2")
    triage = dedup.check_duplicate(artifacts, state, project_scope="admin-test")
    dedup.record_triage(
        state,
        triage,
        "team-test",
        "failure",
        {"hypothesis": "cached", "engine": "fallback"},
        artifacts,
        context_key="cache-key",
    )
    assert main(["incidents", "inspect", "--output-dir", str(output), "--key", triage.dedup_key, "--json"]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["count"] == 1
    assert inspected["root_cause"]["hypothesis"] == "cached"

    assert main([
        "incidents", "invalidate", "--output-dir", str(output),
        "--key", triage.dedup_key, "--yes", "--json",
    ]) == 0
    capsys.readouterr()
    remaining = dedup.lookup_incident(state, triage.dedup_key)
    assert remaining is not None
    assert remaining.get("root_cause") in (None, {})
