from pathlib import Path

import pytest

from hound.cli import main
from hound.models import validate

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures"


def test_cli_analyze_offline(tmp_path):
    out = tmp_path / "out"
    code = main(
        [
            "analyze",
            "--log",
            str(FIXTURE_ROOT / "pytest_fail.log"),
            "--out",
            str(out),
            "--offline",
        ]
    )
    assert code == 1
    assert (out / "report.json").exists()
    assert (out / "report.md").exists()
    assert (out / "ticket.md").exists()
    assert (out / ".hound" / "state.json").exists()


def test_cli_analyze_with_repo(tmp_path, fake_repo):
    repo, path = fake_repo
    out = tmp_path / "out"
    code = main(
        [
            "analyze",
            "--log",
            str(FIXTURE_ROOT / "pytest_fail.log"),
            "--repo",
            str(path),
            "--out",
            str(out),
            "--offline",
        ]
    )
    assert code == 1
    doc = __import__("json").loads((out / "report.json").read_text(encoding="utf-8"))
    validate(doc)
    assert doc["meta"]["engine"] == "fallback"


def test_cli_dedup_across_runs(tmp_path):
    out = tmp_path / "out"
    args = ["analyze", "--log", str(FIXTURE_ROOT / "pytest_fail.log"), "--out", str(out), "--offline"]
    main(args)
    doc1 = __import__("json").loads((out / "report.json").read_text(encoding="utf-8"))
    out2 = tmp_path / "out2"
    args2 = ["analyze", "--log", str(FIXTURE_ROOT / "pytest_fail.log"), "--out", str(out2), "--offline"]
    main(args2)
    doc2 = __import__("json").loads((out2 / "report.json").read_text(encoding="utf-8"))
    # different out dirs => separate state stores, so keys still equal but not dup
    assert doc1["triage"]["dedup_key"] == doc2["triage"]["dedup_key"]

    # same out dir => second run flagged duplicate
    main(args)
    doc3 = __import__("json").loads((out / "report.json").read_text(encoding="utf-8"))
    assert doc3["triage"]["is_duplicate_of"] == doc1["triage"]["dedup_key"]


def test_cli_missing_log(tmp_path):
    code = main(["analyze", "--log", str(tmp_path / "nope.log"), "--offline"])
    assert code == 2


def test_cli_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "Hound Tracer" in capsys.readouterr().out


def test_analyze_handles_single_file_positional_or_flag(tmp_path):
    fixtures = Path(__file__).resolve().parents[1] / "fixtures"
    fail_log = fixtures / "pytest_fail.log"
    out1 = tmp_path / "out1"
    out2 = tmp_path / "out2"
    assert main(["analyze", str(fail_log), "--output-dir", str(out1), "--offline"]) == 1
    assert (out1 / "report.json").exists()
    assert main(["analyze", "--log", str(fail_log), "--output-dir", str(out2), "--offline"]) == 1
    assert (out2 / "report.json").exists()


def test_action_offline_input_is_forwarded():
    action = (Path(__file__).resolve().parents[2] / "action.yml").read_text(encoding="utf-8")
    assert "--offline-value" in action
    assert "${{ inputs.offline }}" in action
    assert "    - --repo-dir" in action
    assert "    - --output-dir" in action


def test_action_safe_optional_inputs_are_value_forwarded():
    action = (Path(__file__).resolve().parents[2] / "action.yml").read_text(encoding="utf-8")
    for name, option in (
        ("provider", "--provider"),
        ("model", "--model"),
        ("source-context", "--source-context-value"),
        ("context", "--context"),
        ("enrich", "--enrich-value"),
        ("redact", "--redact-value"),
    ):
        assert f"  {name}:" in action
        assert f"    - {option}" in action
        assert f"${{{{ inputs.{name} }}}}" in action
