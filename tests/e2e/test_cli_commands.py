import json
from pathlib import Path
import sys

import anyio
import pytest

from hound import service
from hound.cli import build_parser, main
from hound.models import RootCause, Ticket, Triage, build_doc
from tests.conftest import make_artifacts


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _document(*, failure: bool) -> dict:
    artifacts = make_artifacts("pytest_fail.log")
    if not failure:
        artifacts.stage = "unknown"
        artifacts.kind = "unknown"
    root_cause = RootCause(
        hypothesis="Assertion mismatch" if failure else "No supported failure found",
        confidence="high",
        fix_suggestion="Fix expected total" if failure else "No action required",
    )
    return build_doc(
        artifacts,
        root_cause,
        Triage(severity="medium", component="tests", priority=3),
        Ticket(title="test", body_md="body"),
        "2026-08-11T00:00:00+00:00",
    )


def test_no_args_opens_launcher_only_on_tty(monkeypatch):
    called = []
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("hound.integrations.first_run_offer", lambda: None)
    monkeypatch.setattr("hound.launcher.launch", lambda parser, **kwargs: called.append((parser, kwargs)) or 0)

    assert main([]) == 0
    assert len(called) == 1


def test_no_args_non_tty_is_actionable(monkeypatch, capsys):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)

    assert main([]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "hound analyze <log-directory>" in captured.err


def test_cli_subcommand_opens_command_line_without_launcher(monkeypatch):
    called = []
    monkeypatch.setattr("hound.rich_cli.run_cli", lambda args, parser, dispatch: called.append(args.command) or 0)
    monkeypatch.setattr("hound.launcher.launch", lambda *args, **kwargs: pytest.fail("launcher should not open"))

    assert main(["cli"]) == 0
    assert called == ["cli"]


@pytest.mark.parametrize(
    "argv",
    [
        ["analyze", "logs", "--jobs", "0"],
        ["batch", "--logs", "logs", "--max-llm-calls", "0"],
        ["batch", "--logs", "logs", "--max-cost-usd", "-1"],
        ["tui", "--max-retries", "-1"],
    ],
)
def test_numeric_options_reject_invalid_values(argv):
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(argv)
    assert exc.value.code == 2


def test_config_show_masks_secrets(monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-value")
    assert main(["config", "show", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["api_key"] == "configured"
    assert "secret-value" not in json.dumps(payload)


def test_doctor_json_is_machine_readable(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    assert main(["doctor", "--out", str(tmp_path / "out"), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["config"]["api_key"] == "configured"


@pytest.mark.parametrize("path_kind", ["missing", "empty"])
def test_analyze_validates_directory(tmp_path, path_kind, capsys):
    path = tmp_path / path_kind
    if path_kind == "file":
        path.write_text("failure", encoding="utf-8")
    elif path_kind == "empty":
        path.mkdir()

    assert main(["analyze", str(path), "--offline"]) == 2
    assert "error:" in capsys.readouterr().err


def test_analyze_accepts_single_artifact_file(tmp_path):
    artifact = tmp_path / "artifact.log"
    artifact.write_text("pytest\nFAILED tests/test_a.py::test_a - AssertionError: mismatch\n", encoding="utf-8")
    assert main(["analyze", str(artifact), "--offline", "--out", str(tmp_path / "out")]) == 1


def test_json_output_is_valid_and_quiet(tmp_path, capsys):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "failure.log").write_text(
        (FIXTURES / "pytest_fail.log").read_text(encoding="utf-8"), encoding="utf-8"
    )

    assert main(["analyze", str(logs), "--offline", "--format", "json", "--out", str(tmp_path / "out")]) == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert captured.err == ""
    assert payload["count"] == 1
    assert payload["runs"][0]["analysis"]["failure"]["kind"] == "test_failure"


def test_output_file_follows_format(tmp_path, monkeypatch, capsys):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "clean.log").write_text("job complete", encoding="utf-8")
    output = tmp_path / "result.json"

    assert main(["analyze", str(logs), "--offline", "--format", "json", "--output", str(output)]) == 0
    assert capsys.readouterr().out == ""
    assert json.loads(output.read_text(encoding="utf-8"))["count"] == 1


def test_text_analysis_result_uses_panel_in_tty(tmp_path, monkeypatch, capsys):
    artifact = tmp_path / "failure.log"
    artifact.write_text("pytest\nFAILED tests/test_a.py::test_a - AssertionError: mismatch\n", encoding="utf-8")
    monkeypatch.setattr("hound.cli.rich_enabled", lambda _stream: True)

    assert main(["analyze", str(artifact), "--offline", "--out", str(tmp_path / "out")]) == 1

    output = capsys.readouterr().out
    assert "ANALYSIS RESULT" in output
    assert "severity:" in output


def test_init_list_runs_and_clean(tmp_path, capsys):
    config = tmp_path / ".hound.yml"
    assert main(["init", "--config", str(config)]) == 0
    assert config.exists()
    assert (tmp_path / ".hound" / "artifacts").is_dir()
    assert (tmp_path / ".hound" / "captures").is_dir()
    assert (tmp_path / ".hound" / "runs").is_dir()
    assert (tmp_path / ".hound" / "results").is_dir()
    assert (tmp_path / ".hound" / "state").is_dir()
    assert main(["init", "--config", str(config)]) == 0
    capsys.readouterr()

    out = tmp_path / "out"
    from hound.output.report import ensure_outdir

    ensure_outdir(out)
    run = out / "sample"
    ensure_outdir(run)
    (run / "report.json").write_text(json.dumps(_document(failure=True)), encoding="utf-8")
    assert main(["list-runs", "--out", str(out), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["run_id"] == "sample"
    assert main(["clean", "--out", str(out)]) == 2
    assert main(["clean", "--out", str(out), "--yes"]) == 0
    assert not out.exists()


def test_analyze_without_path_uses_initialized_workspace(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 0
    capsys.readouterr()
    capture = tmp_path / ".hound" / "captures" / "failed.log"
    capture.write_text(
        "pytest\nFAILED tests/test_a.py::test_a - AssertionError: mismatch\n",
        encoding="utf-8",
    )

    assert main(["analyze", "--offline"]) == 1
    run_dirs = [path for path in (tmp_path / ".hound" / "results").iterdir() if path.name.startswith("run-")]
    assert len(run_dirs) == 1


def test_log_uses_initialized_capture_and_result_directories(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 0

    assert main([
        "log", "--analyze", "--offline", "--",
        sys.executable, "-c", "raise RuntimeError('boom')",
    ]) != 0
    assert list((tmp_path / ".hound" / "captures").glob("*.log"))
    assert any(path.is_dir() for path in (tmp_path / ".hound" / "results").iterdir())


def test_run_project_captures_output_and_record(tmp_path, capsys):
    assert main([
        "run", "--directory", str(tmp_path), "--json", "--",
        sys.executable, "-c", "print('project output')",
    ]) == 0

    record = json.loads(capsys.readouterr().out)
    assert record["status"] == "passed"
    assert Path(record["capture"]).read_text(encoding="utf-8").strip() == "project output"
    assert (tmp_path / ".hound" / "runs" / f"{record['run_id']}.json").is_file()


def test_run_project_preserves_child_exit_code(tmp_path, capsys):
    assert main([
        "run", "--directory", str(tmp_path), "--",
        sys.executable, "-c", "raise SystemExit(7)",
    ]) == 7
    assert "status   : failed" in capsys.readouterr().out


def test_run_project_result_uses_panel_in_tty(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("hound.cli.rich_enabled", lambda _stream: True)

    assert main([
        "run", "--directory", str(tmp_path), "--",
        sys.executable, "-c", "print('project output')",
    ]) == 0

    output = capsys.readouterr().out
    assert "PROJECT RUN RESULT" in output
    assert "Status" in output
    assert "passed" in output


def test_run_detect_lists_shared_manifest_suggestions(tmp_path, capsys):
    (tmp_path / "pyproject.toml").write_text('[tool.pytest.ini_options]\ntestpaths = ["tests"]\n', encoding="utf-8")

    assert main(["run", "--directory", str(tmp_path), "--detect", "--json"]) == 0

    suggestions = json.loads(capsys.readouterr().out)
    assert {item["label"] for item in suggestions} == {"pytest"}
    assert suggestions[0]["command"] == ["pytest", "-q"]


def test_run_rejects_timeout_above_service_limit(tmp_path, capsys):
    assert main([
        "run", "--directory", str(tmp_path), "--timeout", "3601", "--",
        sys.executable, "-c", "print('not run')",
    ]) == 2
    assert "timeout must be between 1 and 3600 seconds" in capsys.readouterr().err


def test_exit_codes_success_failure_and_internal_error(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "run.log").write_text("content", encoding="utf-8")

    def fake_runs(failure):
        return [service.AnalysisRun("run", logs / "run.log", tmp_path / "out" / "run", _document(failure=failure))]

    monkeypatch.setattr("hound.cli.service.analyze_directory", lambda *args, **kwargs: fake_runs(False))
    assert main(["analyze", str(logs), "--offline"]) == 0
    monkeypatch.setattr("hound.cli.service.analyze_directory", lambda *args, **kwargs: fake_runs(True))
    assert main(["analyze", str(logs), "--offline"]) == 1
    monkeypatch.setattr("hound.cli.service.analyze_directory", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    assert main(["analyze", str(logs), "--offline"]) == 3


def test_ci_stage_with_unknown_kind_returns_success_exit(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "run.log").write_text("pipeline failed", encoding="utf-8")
    document = _document(failure=False)
    document["failure"]["stage"] = "ci"
    document["failure"]["kind"] = "unknown"
    monkeypatch.setattr(
        "hound.cli.service.analyze_directory",
        lambda *args, **kwargs: [service.AnalysisRun("run", logs / "run.log", tmp_path / "out" / "run", document)],
    )

    assert main(["analyze", str(logs), "--offline"]) == 0


def test_deploy_stage_returns_failure_exit(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "run.log").write_text("deployment failed", encoding="utf-8")
    document = _document(failure=False)
    document["failure"]["stage"] = "deploy"
    document["failure"]["kind"] = "deployment_failed"
    monkeypatch.setattr(
        "hound.cli.service.analyze_directory",
        lambda *args, **kwargs: [service.AnalysisRun("run", logs / "run.log", tmp_path / "out" / "run", document)],
    )

    assert main(["analyze", str(logs), "--offline"]) == 1


def test_deploy_unknown_kind_is_not_a_failure_exit(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    logs.mkdir()
    document = _document(failure=False)
    document["failure"]["stage"] = "deploy"
    document["failure"]["kind"] = "unknown"
    monkeypatch.setattr(
        "hound.cli.service.analyze_directory",
        lambda *args, **kwargs: [service.AnalysisRun("run", logs / "run.log", tmp_path / "out" / "run", document)],
    )
    assert main(["analyze", str(logs), "--offline"]) == 0


def test_batch_offline_rejects_network_integrations(tmp_path, capsys):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "run.log").write_text("FAILED", encoding="utf-8")
    assert main(["batch", "--logs", str(logs), "--offline", "--gh"]) == 2
    assert "cannot be combined" in capsys.readouterr().err


def test_clean_rejects_current_working_directory(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["clean", "--out", ".", "--yes"]) == 2
    assert "unsafe output path" in capsys.readouterr().err


def test_list_runs_reports_missing_and_malformed_output(tmp_path, capsys):
    assert main(["list-runs", "--out", str(tmp_path / "missing")]) == 2
    root = tmp_path / "out"
    report = root / "run" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text("not-json", encoding="utf-8")
    assert main(["list-runs", "--out", str(root), "--json"]) == 3
    assert "malformed" in capsys.readouterr().err


def test_explicit_cli_does_not_import_tui(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "clean.log").write_text("job complete", encoding="utf-8")
    sys.modules.pop("hound.tui", None)

    assert main(["analyze", str(logs), "--offline"]) == 0
    assert "hound.tui" not in sys.modules


def test_directory_run_ids_and_formatted_paths_do_not_leak_log_name(tmp_path, capsys):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "person@example.com.log").write_text("12 passed", encoding="utf-8")
    out = tmp_path / "out"
    assert main(["analyze", str(logs), "--offline", "--format", "json", "--out", str(out)]) == 0
    rendered = capsys.readouterr().out
    assert "person@example.com" not in rendered
    run_dirs = [path for path in out.iterdir() if path.is_dir() and path.name.startswith("run-")]
    assert len(run_dirs) == 1


def test_integration_reload_preserves_cli_provider_override(tmp_path, monkeypatch, capsys):
    config = tmp_path / "config.yml"
    config.write_text("llm:\n  provider: anthropic\n", encoding="utf-8")
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "run.log").write_text("12 passed", encoding="utf-8")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GH_REPO", raising=False)
    assert main([
        "analyze", str(logs), "--out", str(tmp_path / "out"), "--config", str(config),
        "--provider", "openai", "--gh",
    ]) == 3
    assert "requires GH_REPO and GH_TOKEN" in capsys.readouterr().err


def test_offline_rejects_network_integrations(tmp_path, capsys):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "run.log").write_text("failure", encoding="utf-8")

    assert main(["analyze", str(logs), "--offline", "--gh"]) == 2
    assert "cannot be combined" in capsys.readouterr().err


def test_config_set_model_preserves_config(tmp_path, capsys):
    config = tmp_path / ".hound.yml"
    config.write_text("redact: true\ncomponents:\n  src/*: core\n", encoding="utf-8")

    assert main(["config", "set", "model", "gemini", "--config", str(config)]) == 0
    text = config.read_text(encoding="utf-8")
    assert "components:" in text
    assert "model: gemini" in text
    assert "provider: gemini" not in text
    assert "API" not in capsys.readouterr().out


def test_models_refresh_discovers_and_caches_catalog(monkeypatch, capsys):
    from hound.cli import main

    cached = {}
    monkeypatch.setattr("hound.providers.discover_models", lambda _url, _key: ["team/model-b", "team/model-a"])
    monkeypatch.setattr(
        "hound.providers.cache_models",
        lambda provider, base_url, models: cached.update(provider=provider, base_url=base_url, models=models),
    )

    assert main([
        "models", "--provider", "openai", "--base-url", "https://models.example/v1",
        "--api-key", "key", "--refresh",
    ]) == 0
    assert cached == {
        "provider": "openai", "base_url": "https://models.example/v1",
        "models": ["team/model-b", "team/model-a"],
    }
    assert capsys.readouterr().out.splitlines() == ["team/model-b", "team/model-a"]


def test_report_reads_run_by_id(tmp_path, capsys):
    run_dir = tmp_path / "runs" / "build"
    run_dir.mkdir(parents=True)
    (run_dir / "report.json").write_text(json.dumps(_document(failure=True)), encoding="utf-8")

    assert main(["report", "build", "--out", str(tmp_path / "runs"), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["root_cause"]["confidence"] == "high"


def test_tui_and_cli_use_shared_service(tmp_path, monkeypatch):
    from hound.tui import HoundTui
    from textual.widgets import ListView

    log = tmp_path / "run.log"
    log.write_text("failure", encoding="utf-8")
    calls = []

    def fake_analyze(log_path, output_dir, **kwargs):
        calls.append(Path(log_path))
        return _document(failure=True)

    monkeypatch.setattr("hound.service.analyze_log", fake_analyze)
    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def exercise():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#log-list", ListView).index = 0
            app.action_analyze()
            for _ in range(100):
                if calls and not app._analyzing:
                    break
                await pilot.pause(0.02)

    anyio.run(exercise)
    assert calls == [log]
