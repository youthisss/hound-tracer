import shutil
import sys
import json
from argparse import Namespace
from pathlib import Path

import anyio
import pytest

FIXTURES = __import__("pathlib").Path(__file__).resolve().parents[1] / "fixtures"


def test_tui_markdown_rewrites_fences_as_indented_code():
    from hound.tui import _markdown_without_fences

    rendered = _markdown_without_fences("before\n```python\nprint('ok')\n```\nafter")
    assert "```" not in rendered
    assert "    print('ok')" in rendered

    quoted = _markdown_without_fences("> ```\n> print('quoted')\n> ```")
    assert "```" not in quoted
    assert "    > print('quoted')" in quoted


def _run(app):
    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            return app

    return anyio.run(main)


def test_tui_compose(tmp_path):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    shutil.copy(FIXTURES / "build_error.log", tmp_path / "build_error.log")

    from hound.tui import HoundTui

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True, provider="openai")
    assert app.state_path == str((tmp_path / "out" / ".hound" / "state.json").resolve())
    _run(app)
    assert len(app._log_files) == 2
    assert app._selected_log is not None


def test_tui_starts_without_focused_widget(tmp_path):
    from hound.tui import HoundTui

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test(size=(130, 35)) as pilot:
            await pilot.pause()
            assert app.focused is None

    anyio.run(main)


def test_tui_resolves_redacted_raw_log_path(tmp_path):
    from hound.ingest.redact import redact_text
    from hound.tui import HoundTui

    log = tmp_path / "person@example.com.log"
    log.write_text("safe", encoding="utf-8")
    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)
    app._log_files = [log]
    stored = redact_text(str(log.resolve()))[0]
    assert app._resolve_raw_path({"meta": {"log_file": stored}}) == log


def test_tui_rejects_raw_log_path_outside_logs_directory(tmp_path):
    from hound.tui import HoundTui
    from textual.widgets import Static

    logs = tmp_path / "logs"
    logs.mkdir()
    outside = tmp_path / "outside.log"
    outside.write_text("must not be rendered", encoding="utf-8")
    app = HoundTui(logs_dir=str(logs), out_dir=str(tmp_path / "out"), offline=True)
    app._log_files = [outside]

    assert app._resolve_raw_path({"meta": {"log_file": str(outside.resolve())}}) is None

    async def main():
        async with app.run_test() as pilot:
            app._show_raw(outside)
            await pilot.pause()
            assert "must not be rendered" not in str(app.query_one("#raw", Static).renderable)
            assert "unavailable" in str(app.query_one("#raw", Static).renderable)

    anyio.run(main)

def test_tui_rejects_malformed_stored_report_before_opening(tmp_path):
    from hound.output.report import ensure_outdir
    from hound.tui import HoundTui

    output = ensure_outdir(tmp_path / "out")
    run = ensure_outdir(output / "run-invalid")
    (run / "report.json").write_text("{}", encoding="utf-8")
    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(output), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            for _ in range(100):
                if app._run_index:
                    break
                await pilot.pause(0.02)
            assert app._run_index and app._run_index[0]["invalid"] is True
            app._load_run(run)
            await pilot.pause()
            assert app._current_doc is None

    anyio.run(main)


def test_tui_uses_resolved_yaml_provider_settings(tmp_path):
    from hound.tui import HoundTui

    config = tmp_path / "config.yml"
    config.write_text("llm:\n  provider: gemini\n  model: gemini-2.0-flash\n", encoding="utf-8")
    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), config_path=str(config), offline=True)
    assert app.provider == "gemini"
    assert app.model == "gemini-2.0-flash"
    assert "generativelanguage.googleapis.com" in app.base_url


def test_tui_config_preview_uses_bounded_verified_reader(tmp_path, monkeypatch):
    from hound import tui

    config = tmp_path / "oversized.yml"
    config.write_bytes(b"#" * (tui.MAX_CONFIG_BYTES + 1))
    calls = []
    original = tui.read_bounded_text

    def tracked_read(path, limit, **kwargs):
        calls.append((path, limit))
        return original(path, limit, **kwargs)

    monkeypatch.setattr(tui, "read_bounded_text", tracked_read)
    with pytest.raises(ValueError, match="config exceeds"):
        tui.HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), config_path=str(config), offline=True)
    assert any(str(path) == str(config) and limit == tui.MAX_CONFIG_BYTES for path, limit in calls)


def test_tui_log_classification_uses_verified_prefix_reader(tmp_path, monkeypatch):
    from hound import tui

    log = tmp_path / "failure.log"
    log.write_text("FAILED tests/test_cart.py::test_total\n", encoding="utf-8")
    calls = []
    original = tui.open_verified_regular

    def tracked_open(path, **kwargs):
        calls.append(path)
        return original(path, **kwargs)

    monkeypatch.setattr(tui, "open_verified_regular", tracked_open)
    stage, kind = tui.HoundTui._log_classification(log)
    assert stage == "test"
    assert kind == "test_failure"
    assert calls == [log]


def test_tui_analyze(tmp_path):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    from hound.tui import HoundTui
    from textual.widgets import ListView, Static

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            lst = app.query_one("#log-list", ListView)
            assert lst.index == 0
            app.action_analyze()
            overview = app.query_one("#overview", Static)
            for _ in range(200):
                txt = str(overview.renderable) if overview.renderable else ""
                if "severity" in txt and "Analyzing" not in txt:
                    break
                await pilot.pause(0.02)
            assert "severity" in str(overview.renderable)
            reports = list((tmp_path / "out").glob("*/report.md"))
            assert len(reports) == 1
            md = reports[0].read_text(encoding="utf-8")
            assert "Root cause" in md
            for _ in range(100):
                if app._runs:
                    break
                await pilot.pause(0.02)
            assert app._runs  # run list populated after analysis
            assert app.query_one("#home").display is True
            assert app.query_one("#results-workspace").display is False

    anyio.run(main)


def test_tui_no_logs(tmp_path):
    from hound.tui import HoundTui
    from textual.widgets import Button, Static

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._log_files == []
            assert app.query_one("#analyze", Button).disabled
            assert "No analysis selected" in str(app.query_one("#overview", Static).renderable)
            assert "WORKFLOW" in str(app.query_one("#home-workflow", Static).renderable)
            status = str(app.query_one("#workflow-status", Static).renderable)
            assert "READY" in status
            assert "Waiting for supported artifacts" in status
            assert status.startswith("[bold]STATUS[/bold]  [#d8d8d8]○")

    anyio.run(main)


def test_tui_discovers_nested_artifacts_and_ignores_dependencies(tmp_path):
    from hound.tui import HoundTui

    report = tmp_path / "test-results" / "unit" / "junit.xml"
    report.parent.mkdir(parents=True)
    report.write_text(
        "<testsuite tests='1' failures='1'><testcase name='fails'><failure message='boom'/></testcase></testsuite>",
        encoding="utf-8",
    )
    ignored = tmp_path / "node_modules" / "package" / "debug.log"
    ignored.parent.mkdir(parents=True)
    ignored.write_text("not project evidence", encoding="utf-8")

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)
    _run(app)

    assert app._log_files == [report]
    assert app._artifact_display_path(report) == str(report.relative_to(tmp_path))


def test_tui_runs_project_captures_output_and_rescans_artifacts(tmp_path):
    from hound.tui import HoundTui

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.start_project_run([
                sys.executable,
                "-c",
                "from pathlib import Path; "
                "Path('test-results').mkdir(); "
                "Path('test-results/junit.xml').write_text(\"<testsuite tests='1' failures='1'><testcase name='x'><failure message='boom'/></testcase></testsuite>\") ; "
                "print('FAILED generated test')",
            ])
            for _ in range(300):
                await pilot.pause(0.02)
                if not app._running_project and (tmp_path / ".hound" / "captures").is_dir():
                    break

            capture_logs = list((tmp_path / ".hound" / "captures").glob("*.log"))
            report = tmp_path / "test-results" / "junit.xml"
            assert capture_logs
            assert report in app._log_files
            assert capture_logs[0] in app._log_files
            records = list((tmp_path / ".hound" / "runs").glob("*.json"))
            assert len(records) == 1
            record = __import__("json").loads(records[0].read_text(encoding="utf-8"))
            assert record["status"] == "passed"
            assert str(report) in record["artifacts"]
            assert app.query_one("#home").display is True
            assert app.query_one("#project-runs-workspace").display is False

    anyio.run(main)


def test_tui_project_runs_have_separate_workspace(tmp_path):
    from hound.tui import HoundTui
    from textual.widgets import Button

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            assert not list(app.query("#workspace-run-project"))
            app.query_one("#nav-runs", Button).press()
            await pilot.pause()
            assert app.query_one("#project-runs-workspace").display is True
            assert app.query_one("#artifact-workspace").display is False
            assert app.query_one("#project-runs-start", Button).disabled is False

    anyio.run(main)


def test_tui_exit_shortcuts_are_bound_to_quit(tmp_path):
    from hound.tui import HoundTui

    bindings = {binding.key: binding.action for binding in HoundTui.BINDINGS}

    assert bindings["ctrl+c"] == "quit"
    assert bindings["q"] == "exit_tui"


def test_tui_ctrl_c_requests_shell_exit(tmp_path):
    from hound.tui import HoundTui

    app = HoundTui(
        logs_dir=str(tmp_path),
        out_dir=str(tmp_path / "out"),
        offline=True,
        return_to_launcher=True,
    )

    async def main():
        async with app.run_test() as pilot:
            await pilot.press("ctrl+c")

    anyio.run(main)
    assert app.return_value == "shell"


def test_run_project_modal_shows_context_and_recent_commands(tmp_path):
    from hound.tui import HoundTui, RunProjectScreen
    from textual.widgets import Button, Input, Static

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)
    app._project_runs = [
        {"command": ["pytest", "-q"]},
        {"command": ["npm", "test"]},
        {"command": ["pytest", "-q"]},
    ]

    async def main():
        async with app.run_test() as pilot:
            app.push_screen(RunProjectScreen(app))
            await pilot.pause()
            screen = app.screen
            assert screen.query_one("#run-project-directory", Input).value == str(tmp_path)
            assert ".hound" in str(screen.query_one("#run-project-capture", Static).renderable)
            assert len(list(screen.query("#run-project-recent Button"))) == 2
            submit = screen.query_one("#run-project-submit", Button)
            assert submit.disabled
            screen.query_one("#run-project-recent-0", Button).press()
            await pilot.pause()
            assert screen.query_one("#run-project-command", Input).value == "pytest -q"
            assert not submit.disabled

    anyio.run(main)


def test_run_project_modal_uses_selected_working_directory(tmp_path):
    from hound.tui import HoundTui, RunProjectScreen
    from textual.widgets import Button, Input, Static

    initial = tmp_path / "initial"
    selected = tmp_path / "selected"
    initial.mkdir()
    selected.mkdir()
    app = HoundTui(logs_dir=str(initial), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            app.push_screen(RunProjectScreen(app))
            await pilot.pause()
            screen = app.screen
            directory = screen.query_one("#run-project-directory", Input)
            command = screen.query_one("#run-project-command", Input)
            submit = screen.query_one("#run-project-submit", Button)

            directory.value = str(selected)
            command.value = f'{sys.executable} -c "print(\"ok\")"'
            await pilot.pause()
            assert not submit.disabled
            assert str(selected / ".hound" / "captures") in str(
                screen.query_one("#run-project-capture", Static).renderable
            )

            screen._submit()
            for _ in range(200):
                await pilot.pause(0.02)
                if not app._running_project:
                    break

            assert app.logs_dir == selected.resolve()
            assert app._project_runs[0]["cwd"] == str(selected.resolve())
            assert __import__("pathlib").Path(app._project_runs[0]["capture"]).parent == selected / ".hound" / "captures"

    anyio.run(main)


def test_run_project_modal_discovers_only_safe_manifest_commands(tmp_path):
    import json

    from hound.tui import HoundTui, RunProjectScreen
    from textual.widgets import Button, Input

    (tmp_path / "package.json").write_text(json.dumps({
        "scripts": {
            "test": "vitest run",
            "build": "vite build",
            "deploy": "publish-production",
            "lint": "eslint . && rm -rf dist",
            "dev": "vite",
        }
    }), encoding="utf-8")
    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            app.push_screen(RunProjectScreen(app))
            await pilot.pause()
            screen = app.screen
            detected = list(screen.query("#run-project-detected Button"))
            assert len(detected) == 2
            labels = {str(button.label) for button in detected}
            assert labels == {"npm test", "npm build"}
            screen.query_one("#run-project-detected-0", Button).press()
            await pilot.pause()
            assert "npm" in screen.query_one("#run-project-command", Input).value
            assert "test" in screen.query_one("#run-project-command", Input).value

    anyio.run(main)


def test_command_discovery_supports_common_project_manifests(tmp_path):
    from hound.tui import _discover_project_commands

    (tmp_path / "Cargo.toml").write_text("[package]\nname='demo'", encoding="utf-8")
    (tmp_path / "go.mod").write_text("module example.test/demo", encoding="utf-8")
    (tmp_path / "Makefile").write_text("test:\n\tpytest\ndeploy:\n\tship\nclean:\n\trm -rf dist\n", encoding="utf-8")

    commands = [command for _label, command in _discover_project_commands(tmp_path)]
    assert ["cargo", "test"] in commands
    assert ["cargo", "build"] in commands
    assert ["go", "test", "./..."] in commands
    assert ["make", "test"] in commands
    assert ["make", "deploy"] not in commands
    assert ["make", "clean"] not in commands


def test_sample_project_exercises_run_discovery_and_all_trace_formats(tmp_path):
    from hound import service
    from hound.tui import HoundTui, _discover_project_commands

    project = tmp_path / "sample-project"
    shutil.copytree(FIXTURES / "sample-project", project)
    suggestions = _discover_project_commands(project)
    labels = {label for label, _command in suggestions}
    assert {"npm test", "npm build", "npm lint", "pytest"} <= labels
    assert "npm deploy" not in labels
    assert "npm clean" not in labels

    app = HoundTui(logs_dir=str(project), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.start_project_run([sys.executable, "scripts/run_checks.py", "test"])
            for _ in range(300):
                await pilot.pause(0.02)
                if not app._running_project and list((project / ".hound" / "runs").glob("*.json")):
                    break

            artifacts = service.discover_artifacts(project)
            suffixes = {path.suffix for path in artifacts}
            assert {".log", ".xml", ".json", ".sarif"} <= suffixes
            assert any(path.parent.name == "captures" for path in artifacts)
            assert (project / "reports" / "coverage.xml").is_file()
            assert (project / "quality.yml").is_file()
            assert app._project_runs[0]["status"] == "failed"
            assert len(app._project_runs[0]["artifacts"]) >= 5

    anyio.run(main)


def test_project_run_persists_only_redacted_command(tmp_path):
    from hound import service

    request = service.prepare_project_run(
        [sys.executable, "-c", "print('ok')", "--token", "do-not-store-this"],
        tmp_path,
        timeout=10,
    )
    result = service.execute_project_run(request)
    serialized = json.dumps(result.record)

    assert "do-not-store-this" not in serialized
    assert "[REDACTED:argument]" in serialized


def test_project_run_request_keeps_immutable_directory(tmp_path):
    from hound import service

    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    request = service.prepare_project_run([sys.executable, "-c", "print('ok')"], first)
    result = service.execute_project_run(request)

    assert result.record["cwd"] == str(first.resolve())
    assert Path(result.record["capture"]).is_relative_to(first.resolve())
    assert not (second / ".hound").exists()


def test_project_run_rejects_symlinked_state_directory(tmp_path):
    from hound import service

    target = tmp_path / "target"
    project = tmp_path / "project"
    target.mkdir()
    project.mkdir()
    try:
        (project / ".hound").symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(ValueError, match="symlink"):
        service.prepare_project_run([sys.executable, "-c", "print('ok')"], project)


def test_corrupt_project_run_is_reported(tmp_path):
    from hound import service

    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "broken.json").write_text("{broken", encoding="utf-8")

    records, errors = service.load_project_runs(runs)

    assert records == []
    assert errors and "broken.json" in errors[0]


def test_tui_workflow_status_animates_analysis_progress(tmp_path):
    from hound.tui import HoundTui
    from textual.widgets import Static

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app._analyzing = True
            app._progress = 0
            app._set_state("loading")
            initial = str(app.query_one("#workflow-status", Static).renderable)
            app._tick_progress()
            updated = str(app.query_one("#workflow-status", Static).renderable)

            assert "ANALYZING" in updated
            assert "Working…" in updated
            assert initial != updated

    anyio.run(main)


def test_tui_ready_status_does_not_repeat_selected_file_name(tmp_path):
    log = tmp_path / "selected.log"
    log.write_text("test failure", encoding="utf-8")

    from hound.tui import HoundTui
    from textual.widgets import Static

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            status = str(app.query_one("#workflow-status", Static).renderable)
            assert "READY" in status
            assert log.name not in status

    anyio.run(main)


def test_tui_workspace_analyze_all_runs_visible_logs(tmp_path):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    shutil.copy(FIXTURES / "build_error.log", tmp_path / "build_error.log")
    from hound.tui import HoundTui
    from textual.widgets import Button, Static

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_show_artifacts()
            await pilot.pause()
            app.query_one("#workspace-analyze-all", Button).press()
            overview = app.query_one("#overview", Static)
            for _ in range(400):
                await pilot.pause(0.02)
                if "Batch analysis complete" in str(overview.renderable):
                    break
            assert "Analyzed [b]2/2[/b]" in str(overview.renderable)
            assert len(list((tmp_path / "out").glob("*/report.json"))) == 2

    anyio.run(main)


def test_tui_stop_action_remains_available_during_analysis(tmp_path, monkeypatch):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    from hound.tui import HoundTui

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            assert not app.query("#stop-analysis")
            app._analyzing = True
            app._set_analysis_enabled()
            app.action_stop_analysis()
            assert app._stop_requested.is_set()
            app._analyzing = False
            app._set_analysis_enabled()

    anyio.run(main)


def test_tui_parallel_analyze_all_respects_llm_call_cap(tmp_path, monkeypatch):
    from types import SimpleNamespace

    for name in "abcdef":
        shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / f"{name}.log")
    from hound.tui import HoundTui
    from textual.widgets import Button, Static

    calls = {"n": 0}

    def create(**_kwargs):
        calls["n"] += 1
        payload = {"hypothesis": "h", "confidence": "high", "evidence_refs": ["ev-001"], "contradicting_evidence_refs": [], "missing_information": [], "recommended_checks": ["check"], "fix_suggestion": "f"}
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=__import__("json").dumps(payload)))],
            usage=None,
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr("hound.analyze.llm._make_client", lambda _config: client)
    monkeypatch.setenv("HOUND_API_KEY", "test-key")
    app = HoundTui(
        logs_dir=str(tmp_path),
        out_dir=str(tmp_path / "out"),
        offline=False,
        model="test-model",
        jobs=6,
        max_llm_calls=1,
        no_dedup=True,
    )

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_show_artifacts()
            await pilot.pause()
            app.query_one("#workspace-analyze-all", Button).press()
            overview = app.query_one("#overview", Static)
            for _ in range(500):
                await pilot.pause(0.02)
                if "Batch analysis complete" in str(overview.renderable):
                    break
            assert calls["n"] == 1
            assert "budget-skipped: 5" in str(overview.renderable)

    anyio.run(main)


def test_tui_labels_deployment_log_and_run(tmp_path):
    shutil.copy(FIXTURES / "kubernetes_rollout.log", tmp_path / "kubernetes_rollout.log")
    from hound.tui import HoundTui
    from textual.widgets import ListView, Static

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            log_list = app.query_one("#log-list", ListView)
            assert "DEPLOY" in str(log_list.children[0].query_one(Static).renderable)
            app.action_analyze()
            for _ in range(400):
                await pilot.pause(0.02)
                run_list = app.query_one("#run-list", ListView)
                if app._runs and any("DEPLOY" in str(item.renderable) for item in run_list.query(Static)):
                    break
            assert app._runs
            assert any("DEPLOY" in str(item.renderable) for item in run_list.query(Static))
            assert "stage" in str(app.query_one("#overview", Static).renderable)

    anyio.run(main)


def test_tui_settings_overlay(tmp_path):
    """Settings opens from sidebar instead of main tab row."""
    from hound.tui import HoundTui, SettingsScreen
    from textual.widgets import Select, Static

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True, provider="openai")

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_open_settings()
            await pilot.pause()
            assert isinstance(app.screen, SettingsScreen)
            sel = app.screen.query_one("#settings-provider", Select)
            assert sel.value == "openai"
            inp = app.screen.query_one("#settings-model", Select)
            assert inp is not None
            # Changing provider updates the status bar mode.
            app.provider = "gemini"
            app.offline = False
            app._update_statusbar()
            sb = app.screen_stack[0].query_one("#statusbar", Static)
            assert "llm:gemini" in str(sb.renderable)

    anyio.run(main)


def test_tui_settings_groups_oauth_and_custom_providers_with_analysis(tmp_path):
    from hound.subscription_auth import NOTICE
    from hound.tui import HoundTui, SettingsScreen
    from textual.widgets import Button, Collapsible, Select, Static

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=False, provider="openai")

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_open_settings()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SettingsScreen)
            provider_section = screen.query_one("#settings-provider-title").parent
            custom = screen.query_one("#settings-custom-provider", Collapsible)
            assert custom.parent is provider_section
            assert NOTICE in str(screen.query_one("#oauth-risk-notice", Static).renderable)
            assert str(screen.query_one("#settings-oauth-openai", Button).label) == "OpenAI / Codex"
            assert str(screen.query_one("#settings-oauth-claude", Button).label) == "Claude Code"
            assert str(screen.query_one("#settings-oauth-gemini", Button).label) == "Gemini CLI"
            protocol = screen.query_one("#custom-provider-protocol", Select)
            assert screen.query_one("#custom-provider-url").placeholder == "https://api.openai.com/v1"
            protocol.value = "anthropic"
            screen.on_select_changed(type("E", (), {"select": protocol, "value": "anthropic"})())
            assert screen.query_one("#custom-provider-url").placeholder == "https://api.anthropic.com/v1"
            assert screen.query_one("#custom-provider-model").placeholder == "e.g. claude-sonnet-4-5"

    anyio.run(main)


def test_tui_settings_overlay_model_default(tmp_path):
    """Selecting a provider enables automatic provider model selection."""
    import anyio as _anyio

    from hound.tui import HoundTui, SettingsScreen
    from textual.widgets import Select

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_open_settings()
            await pilot.pause()
            assert isinstance(app.screen, SettingsScreen)
            sel = app.screen.query_one("#settings-provider", Select)
            # emulate a user picking gemini
            sel.value = "gemini"
            app.screen.on_select_changed(type("E", (), {"select": sel, "value": "gemini"})())
            inp = app.screen.query_one("#settings-model", Select)
            assert inp.value == "auto"

    _anyio.run(main)


def test_tui_settings_provider_hint(tmp_path):
    """Provider hint shows base URL + env vars for the selected provider."""
    from hound.tui import HoundTui

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True, provider="openai")
    _run(app)
    hint = app._provider_hint()
    assert "https://api.openai.com/v1" in hint
    assert "OPENAI_API_KEY" in hint


def test_tui_settings_updates_provider_hint_and_cancels(tmp_path):
    from hound.tui import HoundTui, SettingsScreen
    from textual.widgets import Select, Static

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True, provider="openai")

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_open_settings()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SettingsScreen)
            select = screen.query_one("#settings-provider", Select)
            screen.on_select_changed(type("E", (), {"select": select, "value": "gemini"})())
            hint = screen.query_one("#provider-hint", Static)
            assert hint.styles.margin.top == 0
            assert "generativelanguage.googleapis.com" in str(hint.renderable)
            cancel = screen.query_one("#settings-cancel")
            screen.on_button_pressed(type("E", (), {"button": cancel})())
            await pilot.pause()
            assert not isinstance(app.screen, SettingsScreen)

    anyio.run(main)


def test_tui_settings_offline_toggle_applies_only_after_save(tmp_path, monkeypatch):
    from hound import tui
    from hound.preferences import save_tui_preferences as save_preferences
    from hound.tui import HoundTui, SettingsScreen
    from textual.widgets import Button

    monkeypatch.setattr(
        tui,
        "save_tui_preferences",
        lambda offline, provider, model, **kwargs: save_preferences(offline, provider, model, tmp_path / "tui.yml", **kwargs),
    )
    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=False)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_open_settings()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SettingsScreen)
            offline_toggle = screen.query_one("#settings-offline", Button)
            assert "LLM mode" in str(offline_toggle.label)
            screen.on_button_pressed(type("E", (), {"button": offline_toggle})())
            assert "Offline" in str(offline_toggle.label)
            assert app.offline is False
            save = screen.query_one("#settings-save", Button)
            screen.on_button_pressed(type("E", (), {"button": save})())
            await pilot.pause()
            assert app.offline is True

    anyio.run(main)


def test_tui_directory_metadata_and_filter(tmp_path):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    shutil.copy(FIXTURES / "build_error.log", tmp_path / "build_error.log")
    from hound.tui import HoundTui
    from textual.widgets import Button, Input, Static

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            session = str(app.query_one("#session-summary", Static).renderable)
            assert "2 loaded" in session
            assert "DIRECTORY" in session
            assert str(tmp_path)[:20] in session
            assert not app.query("#dir-meta")
            assert not app.query_one("#analyze", Button).disabled
            app.query_one("#log-filter", Input).value = "pytest"
            await pilot.pause(0.4)
            assert [path.name for path in app._log_files] == ["pytest_fail.log"]
            assert app._selected_log.name == "pytest_fail.log"

    anyio.run(main)


def test_tui_input_typing_does_not_trigger_global_shortcuts(tmp_path):
    from hound.tui import HoundTui
    from textual.widgets import Input

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            log_filter = app.query_one("#log-filter", Input)
            log_filter.focus()
            triggered = []
            app.action_analyze = lambda: triggered.append("analyze")

            await pilot.press("a")
            await pilot.pause(0.25)

            assert log_filter.value == "a"
            assert triggered == []

    anyio.run(main)


def test_tui_raw_header_tracks_selected_log(tmp_path):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    shutil.copy(FIXTURES / "build_error.log", tmp_path / "build_error.log")
    from hound.tui import HoundTui
    from textual.widgets import ListView, Static

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#log-list", ListView).index = app._log_files.index(tmp_path / "build_error.log")
            app.action_select_log()
            header = str(app.query_one("#raw-header", Static).renderable)
            assert "build_error.log" in header

    anyio.run(main)


def test_tui_enter_analyzes_focused_workspace_artifact(tmp_path):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    shutil.copy(FIXTURES / "build_error.log", tmp_path / "build_error.log")

    from hound.tui import HoundTui
    from textual.widgets import ListView

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_show_artifacts()
            await pilot.pause()
            logs = app.query_one("#artifact-workspace-list", ListView)
            logs.focus()
            logs.index = app._visible_log_files.index(tmp_path / "build_error.log")
            analyzed = []
            app._analyze_batch_targets = lambda targets: analyzed.extend(targets)

            await pilot.press("enter")

            assert analyzed == [tmp_path / "build_error.log"]

    anyio.run(main)


def test_tui_click_selects_workspace_artifact_without_analyzing(tmp_path):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    shutil.copy(FIXTURES / "build_error.log", tmp_path / "build_error.log")

    from hound.tui import HoundTui
    from textual.widgets import ListView

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_show_artifacts()
            await pilot.pause()
            logs = app.query_one("#artifact-workspace-list", ListView)
            analyzed = []
            app._analyze_batch_targets = lambda targets: analyzed.extend(targets)

            first_item = logs.children[0]
            await pilot.click(first_item)
            await pilot.pause(0.1)

            assert len(analyzed) == 0
            assert len(app._selected_artifacts) == 1
            assert logs.index == 0

    anyio.run(main)


def test_tui_caps_sidebar_widgets_but_keeps_all_visible_targets(tmp_path, monkeypatch):
    from hound.tui import HoundTui
    from textual.widgets import ListView, Static

    # 201 is the smallest input that proves a third page while keeping this
    # full-suite integration test below Textual's default initialization timeout.
    total = 201
    for index in range(total):
        (tmp_path / f"log-{index:04d}.log").write_text("ERROR build failed", encoding="utf-8")
    monkeypatch.setattr(HoundTui, "_log_classification", staticmethod(lambda _path: ("build", "build")))
    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            assert len(app._visible_log_files) == total
            assert len(app._log_files) == total
            assert len(app.query_one("#log-list", ListView).children) == 101
            assert f"{total} visible" in str(app.query_one("#home-artifacts", Static).renderable)

            # Open artifacts workspace
            await pilot.press("f")
            await pilot.pause()
            # Paginated at 100 per page on workspace list
            assert len(app.query_one("#artifact-workspace-list", ListView).children) == 100
            assert "Page 1/3" in str(app.query_one("#artifact-pagination-label", Static).renderable)

            # Move to the next page with 'n'.
            await pilot.press("n")
            await pilot.pause()
            assert app._artifact_page == 2
            assert "Page 2/3" in str(app.query_one("#artifact-pagination-label", Static).renderable)
            assert len(app.query_one("#artifact-workspace-list", ListView).children) == 100

            # Move to page 3
            await pilot.press("n")
            await pilot.pause()
            assert app._artifact_page == 3
            assert "Page 3/3" in str(app.query_one("#artifact-pagination-label", Static).renderable)
            assert len(app.query_one("#artifact-workspace-list", ListView).children) == 1

            # Test space to toggle artifact selection
            await pilot.press("space")
            await pilot.pause()
            assert len(app._selected_artifacts) == 1
            assert "1 selected" in str(app.query_one("#artifact-workspace-meta", Static).renderable)

            # Toggle off
            await pilot.press("space")
            await pilot.pause()
            assert len(app._selected_artifacts) == 0

    anyio.run(main)


def test_tui_browse_directory_loads_selected_folder(tmp_path, monkeypatch):
    initial = tmp_path / "initial"
    selected = tmp_path / "selected"
    initial.mkdir()
    selected.mkdir()
    shutil.copy(FIXTURES / "pytest_fail.log", selected / "pytest_fail.log")

    from hound import tui
    from textual.widgets import Input

    monkeypatch.setattr(tui, "_choose_directory", lambda _initial: str(selected))
    app = tui.HoundTui(logs_dir=str(initial), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("b")
            for _ in range(100):
                await pilot.pause(0.01)
                if app.logs_dir == selected:
                    break
            assert app.logs_dir == selected
            assert app.query_one("#dir-input", Input).value == str(selected)
            assert [path.name for path in app._log_files] == ["pytest_fail.log"]

    anyio.run(main)


def test_tui_artifact_workspace_browse_loads_selected_folder(tmp_path, monkeypatch):
    initial = tmp_path / "initial"
    selected = tmp_path / "selected"
    initial.mkdir()
    selected.mkdir()
    shutil.copy(FIXTURES / "pytest_fail.log", selected / "pytest_fail.log")

    from hound import tui
    from textual.widgets import Button, Input

    monkeypatch.setattr(tui, "_choose_directory", lambda _initial: str(selected))
    app = tui.HoundTui(logs_dir=str(initial), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#nav-artifacts", Button).press()
            await pilot.pause()
            app.query_one("#workspace-browse", Button).press()
            for _ in range(100):
                await pilot.pause(0.01)
                if app.logs_dir == selected:
                    break
            assert app.logs_dir == selected
            assert app.query_one("#dir-input", Input).value == str(selected)
            assert [path.name for path in app._visible_log_files] == ["pytest_fail.log"]

    anyio.run(main)


def test_tui_browse_directory_cancel_keeps_current_folder(tmp_path, monkeypatch):
    shutil.copy(FIXTURES / "build_error.log", tmp_path / "build_error.log")

    from hound import tui

    monkeypatch.setattr(tui, "_choose_directory", lambda _initial: "")
    app = tui.HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("b")
            await pilot.pause(0.05)
            assert app.logs_dir == tmp_path
            assert [path.name for path in app._log_files] == ["build_error.log"]

    anyio.run(main)


def test_tui_settings_follows_workflow_and_shortcut_opens_overlay(tmp_path):
    from hound.tui import HoundTui, SettingsScreen
    from textual.widgets import Button, Static

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            sidebar = app.query_one("#sidebar")
            children = list(sidebar.children)
            settings = app.query_one("#open-settings", Button)
            workflow = next(
                widget for widget in sidebar.query(Static)
                if "WORKFLOW" in str(widget.renderable)
            )
            assert children.index(workflow) < children.index(settings)

            await pilot.press("escape", "s")
            await pilot.pause()
            assert isinstance(app.screen, SettingsScreen)

    anyio.run(main)


def test_tui_main_content_uses_scrollbars_only_when_needed(tmp_path):
    from hound.tui import HoundTui, ResultScroll
    from textual.widgets import Static

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            overview = app.query_one("#overview", Static)
            scroller = app.query_one("#overview-scroll", ResultScroll)
            assert str(scroller.styles.overflow_y) == "auto"
            assert str(scroller.styles.overflow_x) == "auto"
            assert scroller.styles.scrollbar_size_vertical == 0
            assert scroller.styles.scrollbar_size_horizontal == 0
            assert scroller.can_focus

            app._show_results()
            overview.update("\n".join(f"line {line}" for line in range(100)))
            scroller.focus()
            await pilot.pause()
            await pilot.press("end")
            await pilot.pause()
            assert scroller.scroll_y > 0

    anyio.run(main)


def test_tui_sidebar_starts_closed_and_can_toggle(tmp_path):
    from hound.tui import HoundTui
    from textual.widgets import Button, Static

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test(size=(130, 35)) as pilot:
            await pilot.pause()
            sidebar = app.query_one("#sidebar")
            assert app.has_class("sidebar-collapsed")
            assert sidebar.display is False
            show_sidebar = app.query_one("#show-sidebar", Button)
            assert show_sidebar.display is True
            assert str(show_sidebar.label) == "≡"

            show_sidebar.press()
            await pilot.pause()
            assert not app.has_class("sidebar-collapsed")
            assert sidebar.display is True
            assert app.query_one("#show-sidebar", Button).display is False
            assert app.query_one("#log-list").display is True

            app.action_toggle_sidebar()
            await pilot.pause()
            assert app.has_class("sidebar-collapsed")
            assert sidebar.display is False

            shortcutbar = str(app.query_one("#shortcutbar", Static).renderable)
            assert "sidebar" in shortcutbar
            assert not app.query("#sidebar-toggle")

    anyio.run(main)


@pytest.mark.parametrize("size", [(160, 50), (100, 35), (70, 24)])
def test_tui_navigation_highlight_fills_to_idle_border_bounds(tmp_path, size):
    from hound.tui import HoundTui
    from textual.geometry import Region

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test(size=size) as pilot:
            app._show_results("pane-report")
            if not app.has_class("sidebar-collapsed"):
                app.action_toggle_sidebar()
            await pilot.pause()
            for selector in ("#show-sidebar", "#back-button"):
                button = app.query_one(selector)
                app.set_focus(None)
                await pilot.hover("#statusbar")
                await pilot.pause()
                region = button.region
                crop = Region(0, 0, region.width, region.height)
                idle = [list(strip) for strip in button.render_lines(crop)]
                assert "".join(segment.text for segment in idle[0]) == "┌─────┐"
                assert "".join(segment.text for segment in idle[-1]) == "└─────┘"
                for state in ("hover", "focus", "active"):
                    if state == "hover":
                        await pilot.hover(button)
                    elif state == "focus":
                        await pilot.hover("#statusbar")
                        button.focus()
                    else:
                        app.set_focus(None)
                        button.add_class("-active")
                    await pilot.pause()
                    rendered = [list(strip) for strip in button.render_lines(crop)]
                    assert button.region == region
                    assert "".join(segment.text for segment in rendered[0]) == "▗▄▄▄▄▄▖"
                    assert "".join(segment.text for segment in rendered[-1]) == "▝▀▀▀▀▀▘"
                    assert rendered[1][0].text == "▐"
                    assert rendered[1][-1].text == "▌"
                    edges = rendered[0] + rendered[-1] + [rendered[1][0], rendered[1][-1]]
                    assert all(segment.style.color.triplet == (255, 255, 255) for segment in edges)
                    assert all(segment.style.bgcolor.triplet == (0, 0, 0) for segment in edges)
                    interior = rendered[1][1:-1]
                    assert sum(segment.cell_length for segment in interior) == region.width - 2
                    assert all(not segment.style.reverse for segment in interior)
                    assert all(segment.style.bgcolor.triplet == (255, 255, 255) for segment in interior)
                    assert all(segment.style.color.triplet == (0, 0, 0) for segment in interior)
                    assert "".join(segment.text for segment in interior) == str(button.label).center(region.width - 2)
                button.remove_class("-active")

    anyio.run(main)


def test_tui_artifact_workspace_multi_select_and_batch_analyze(tmp_path, monkeypatch):
    from hound.tui import HoundTui
    from textual.widgets import Button, ListView, Static

    for index in range(5):
        (tmp_path / f"log-{index:02d}.log").write_text("ERROR build failed", encoding="utf-8")
    monkeypatch.setattr(HoundTui, "_log_classification", staticmethod(lambda _path: ("build", "build")))
    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            # Open artifacts workspace
            await pilot.press("f")
            await pilot.pause()
            assert app.query_one("#workspace-analyze", Button).disabled
            assert app.query_one("#workspace-deselect-all", Button).disabled

            # Select all shortcut
            await pilot.press("z")
            await pilot.pause()
            assert len(app._selected_artifacts) == 5
            assert "5 selected" in str(app.query_one("#artifact-workspace-meta", Static).renderable)
            assert str(app.query_one("#workspace-analyze", Button).label) == "Analyze 5 selected"
            assert not app.query_one("#workspace-analyze", Button).disabled

            # Deselect all shortcut
            await pilot.press("d")
            await pilot.pause()
            assert len(app._selected_artifacts) == 0
            assert "selected" not in str(app.query_one("#artifact-workspace-meta", Static).renderable)
            assert str(app.query_one("#workspace-analyze", Button).label) == "Analyze selected"
            assert app.query_one("#workspace-analyze", Button).disabled

            # Space selection
            artifact_list = app.query_one("#artifact-workspace-list", ListView)
            first_item = artifact_list.children[0]
            artifact_list.focus()
            artifact_list.index = 0
            await pilot.press("space")
            await pilot.pause()
            assert len(app._selected_artifacts) == 1
            assert "1 selected" in str(app.query_one("#artifact-workspace-meta", Static).renderable)
            assert artifact_list.children[0] is first_item
            assert artifact_list.index == 0

            # A later selection stays after the first in batch analysis order.
            artifact_list.index = 3
            await pilot.press("space")
            await pilot.pause()
            expected_order = [app._visible_log_files[0], app._visible_log_files[3]]
            assert app._selected_artifact_order == expected_order
            captured: list = []
            app._analyze_batch_targets = lambda targets: captured.extend(targets)
            app.query_one("#workspace-analyze", Button).press()
            await pilot.pause()
            assert captured == expected_order

            # Enter analyzes the focused artifact without changing batch selection.
            captured.clear()
            artifact_list.index = 0
            await pilot.press("enter")
            await pilot.pause()
            artifact_list.index = 3
            await pilot.press("enter")
            await pilot.pause()
            assert captured == [app._visible_log_files[0], app._visible_log_files[3]]
            assert len(app._selected_artifacts) == 2

    anyio.run(main)


def test_tui_help_and_offline_toggle(tmp_path, monkeypatch):
    from hound import tui
    from hound.preferences import save_tui_preferences as save_preferences
    from hound.tui import HelpScreen, HoundTui

    monkeypatch.setattr(
        tui,
        "save_tui_preferences",
        lambda offline, provider, model, **kwargs: save_preferences(offline, provider, model, tmp_path / "tui.yml", **kwargs),
    )
    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=False)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_show_help()
            await pilot.pause()
            assert isinstance(app.screen, HelpScreen)
            await pilot.press("escape")
            app.action_toggle_offline()
            assert app.offline is True

    anyio.run(main)


def test_tui_recent_run_loads_all_panes(tmp_path):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    from hound.pipeline import analyze
    from hound.tui import HoundTui
    from textual.widgets import Markdown, Static

    out = tmp_path / "out"
    analyze(tmp_path / "pytest_fail.log", out, offline=True)
    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(out), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._runs == [out]
            app._load_run(out)
            await pilot.pause(0.1)
            assert "STATUS" in str(app.query_one("#overview", Static).renderable)
            assert any(
                "Investigation summary" in str(header.renderable)
                for header in app.query(".result-header").results(Static)
            )
            report = app.query_one("#report", Markdown)
            ticket = app.query_one("#ticket", Markdown)
            for _ in range(100):
                if any("Root cause" in str(block._text) for block in report.query("MarkdownBlock")) and list(ticket.query("MarkdownBlock")):
                    break
                await pilot.pause(0.02)
            assert any("Root cause" in str(block._text) for block in report.query("MarkdownBlock"))
            assert list(ticket.query("MarkdownBlock"))
            assert "AssertionError" in str(app.query_one("#raw", Static).renderable)

    anyio.run(main)


def test_tui_workspace_shortcuts(tmp_path):
    from hound.tui import HoundTui

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            # Press 'f' to open artifacts
            await pilot.press("f")
            await pilot.pause()
            assert app.query_one("#artifact-workspace").display is True
            assert app.query_one("#results-workspace").display is False

            # Press 'l' to open results
            await pilot.press("l")
            await pilot.pause()
            assert app.query_one("#results-workspace").display is True
            assert app.query_one("#artifact-workspace").display is False

            # Press 'j' to open project runs
            await pilot.press("j")
            await pilot.pause()
            assert app.query_one("#project-runs-workspace").display is True
            assert app.query_one("#results-workspace").display is False

            # Press 'h' to go home
            await pilot.press("h")
            await pilot.pause()
            assert app.query_one("#home").display is True
            assert app.query_one("#artifact-workspace").display is False
            assert app.query_one("#results-workspace").display is False

    anyio.run(main)


def test_tui_workspace_filters_sync_and_filter(tmp_path):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    shutil.copy(FIXTURES / "build_error.log", tmp_path / "build_error.log")
    from hound.tui import HoundTui
    from textual.widgets import Button, Input, Select

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#nav-artifacts", Button).press()
            await pilot.pause()
            assert app.query_one("#artifact-workspace").display is True

            # Filter via workspace input
            app.query_one("#workspace-artifact-filter", Input).value = "build"
            await pilot.pause(0.3)
            assert [p.name for p in app._visible_log_files] == ["build_error.log"]
            assert app.query_one("#log-filter", Input).value == "build"

            # Filter via workspace type select
            app.query_one("#workspace-artifact-filter", Input).value = ""
            await pilot.pause(0.3)
            app.query_one("#workspace-artifact-type", Select).value = "build"
            await pilot.pause()
            assert [p.name for p in app._visible_log_files] == ["build_error.log"]
            assert app.query_one("#type-filter", Select).value == "build"

            # Results workspace filters
            app.query_one("#nav-results", Button).press()
            await pilot.pause()
            assert app.query_one("#results-workspace").display is True

            app._apply_run_index([
                {"path": tmp_path / "old", "report": tmp_path / "old.json", "modified": 1,
                 "artifact": "pytest.log", "stage": "test", "severity": "high",
                 "summary": "assertion failed", "hypothesis": "database timeout", "invalid": False},
                {"path": tmp_path / "new", "report": tmp_path / "new.json", "modified": 2,
                 "artifact": "deploy.log", "stage": "deploy", "severity": "low",
                 "summary": "rollout failed", "hypothesis": "image missing", "invalid": False},
            ])
            app.query_one("#workspace-run-filter", Input).value = "database"
            await pilot.pause(0.3)
            assert app._runs == [tmp_path / "old"]
            assert app.query_one("#workspace-run-filter", Input).value == "database"

            app.query_one("#workspace-run-filter", Input).value = ""
            app.query_one("#workspace-run-stage", Select).value = "deploy"
            await pilot.pause()
            assert app._runs == [tmp_path / "new"]
            assert app.query_one("#workspace-run-stage", Select).value == "deploy"

    anyio.run(main)


def test_tui_workspace_results_open_with_enter(tmp_path):
    import json
    from hound.analyze.fallback import build_root_cause
    from hound.models import Triage, build_doc
    from hound.output.tickets import build_ticket
    from hound.triage.severity import classify
    from hound.tui import HoundTui
    from tests.conftest import make_artifacts
    from textual.widgets import Button, ListItem, ListView

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    artifacts = make_artifacts("pytest_fail.log")
    rc = build_root_cause(artifacts)
    severity, priority = classify(artifacts)
    triage = Triage(severity=severity, priority=priority, component="tests", dedup_key="abc")
    ticket = build_ticket(artifacts, rc, triage)
    doc = build_doc(artifacts, rc, triage, ticket, generated_at="2026-01-01T00:00:00Z")

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#nav-results", Button).press()
            await pilot.pause()

            report_file = tmp_path / "out" / "run-1" / "report.json"
            report_file.parent.mkdir(parents=True)
            report_file.write_text(json.dumps(doc), encoding="utf-8")

            app._apply_run_index([
                {
                    "path": tmp_path / "out" / "run-1",
                    "report": report_file,
                    "modified": 100,
                    "artifact": "pytest_fail.log",
                    "stage": "test",
                    "severity": "high",
                    "summary": "fail",
                    "hypothesis": "bug",
                    "invalid": False,
                }
            ])
            # Wait for the list to render fully before sending click events.
            for _ in range(20):
                await pilot.pause(0.05)
                results_list = app.query_one("#results-workspace-list", ListView)
                if results_list.children:
                    break
            results_list.focus()
            results_list.index = 0
            # Clicking toggles selection but must not open the result.
            results_list.post_message(ListItem._ChildClicked(results_list.children[0]))
            await pilot.pause(0.2)
            assert report_file.parent in app._selected_runs
            assert app.query_one("#tabs").display is False
            # Pressing Enter on the selected item opens it.
            await pilot.press("enter")
            await pilot.pause()
            assert app.query_one("#tabs").display is True

    anyio.run(main)


def test_tui_result_tabs_cycle_with_left_and_right_arrows(tmp_path):
    from hound.tui import HoundTui
    from textual.widgets import TabbedContent

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app._show_results("pane-report")

            await pilot.press("right")
            assert app.query_one("#tabs", TabbedContent).active == "pane-ticket"

            await pilot.press("right")
            assert app.query_one("#tabs", TabbedContent).active == "pane-raw"

            await pilot.press("left")
            assert app.query_one("#tabs", TabbedContent).active == "pane-ticket"

            await pilot.press("left")
            assert app.query_one("#tabs", TabbedContent).active == "pane-report"

    anyio.run(main)


def test_tui_opened_results_can_navigate_previous_and_next(tmp_path):
    import json

    from hound.analyze.fallback import build_root_cause
    from hound.models import Triage, build_doc
    from hound.output.report import ensure_outdir
    from hound.output.tickets import build_ticket
    from hound.triage.severity import classify
    from hound.tui import HoundTui
    from tests.conftest import make_artifacts
    from textual.containers import Horizontal
    from textual.widgets import Button, Static

    artifacts = make_artifacts("pytest_fail.log")
    root_cause = build_root_cause(artifacts)
    severity, priority = classify(artifacts)
    triage = Triage(severity=severity, priority=priority, component="tests", dedup_key="abc")
    document = build_doc(artifacts, root_cause, triage, build_ticket(artifacts, root_cause, triage), generated_at="2026-01-01T00:00:00Z")

    output_dir = ensure_outdir(tmp_path / "out")
    run_dirs = [output_dir / "run-one", output_dir / "run-two"]
    for run_dir in run_dirs:
        run_dir.mkdir(parents=True)
        (run_dir / "report.json").write_text(json.dumps(document), encoding="utf-8")

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(output_dir), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app._apply_run_index([
                {
                    "path": run_dirs[0], "report": run_dirs[0] / "report.json", "modified": 1,
                    "artifact": "one.log", "stage": "test", "severity": "high",
                    "summary": "first", "hypothesis": "first", "invalid": False,
                },
                {
                    "path": run_dirs[1], "report": run_dirs[1] / "report.json", "modified": 2,
                    "artifact": "two.log", "stage": "test", "severity": "high",
                    "summary": "second", "hypothesis": "second", "invalid": False,
                },
            ])
            app._show_workspace("results")
            app._add_selected_run(app._runs[1])
            app._add_selected_run(app._runs[0])
            app._refresh_results_selection()
            assert app._selected_run_order == [app._runs[1], app._runs[0]]
            app.query_one("#open-workspace-result", Button).press()
            await pilot.pause()

            navigation = app.query_one("#result-navigation", Horizontal)
            previous = app.query_one("#previous-result", Button)
            next_result = app.query_one("#next-result", Button)
            position = app.query_one("#result-position", Static)
            assert navigation.display is True
            assert str(position.renderable) == "Result 1 of 2"
            assert app._current_run_dir == app._runs[1]
            assert previous.disabled is True
            assert next_result.disabled is False

            next_result.press()
            await pilot.pause()
            assert app._current_run_dir == app._runs[0]
            assert str(position.renderable) == "Result 2 of 2"
            assert previous.disabled is False
            assert next_result.disabled is True

            await pilot.press("p")
            await pilot.pause()
            assert app._current_run_dir == app._runs[1]

            # Opening one result does not create a group to navigate.
            app._load_run(app._runs[1])
            await pilot.pause()
            assert navigation.display is False
            await pilot.press("n")
            await pilot.pause()
            assert app._current_run_dir == app._runs[1]

    anyio.run(main)


def test_tui_workspace_results_selection_toggle(tmp_path):
    from hound.tui import HoundTui
    from textual.widgets import Button, ListView, Static

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.press("l")
            await pilot.pause()

            run_dir = tmp_path / "out" / "run-1"
            app._apply_run_index([
                {
                    "path": run_dir,
                    "report": run_dir / "report.json",
                    "modified": 100,
                    "artifact": "pytest_fail.log",
                    "stage": "test",
                    "severity": "high",
                    "summary": "fail",
                    "hypothesis": "bug",
                    "invalid": False,
                }
            ])
            await pilot.pause(0.2)
            assert run_dir not in app._selected_runs
            assert not app.query_one("#open-workspace-result", Button).disabled
            assert app.query_one("#clear-selected", Button).disabled

            # Select and deselect all result shortcuts.
            await pilot.press("z")
            assert run_dir in app._selected_runs
            await pilot.press("d")
            assert run_dir not in app._selected_runs

            # Trigger list item selection (mouse click / space toggle)
            results_list = app.query_one("#results-workspace-list", ListView)
            results_list.focus()
            results_list.index = 0
            shortcuts = str(app.query_one("#shortcutbar", Static).renderable)
            assert "enter" in shortcuts
            assert "space" in shortcuts
            first_item = results_list.children[0]
            await pilot.press("space")
            assert run_dir in app._selected_runs
            assert results_list.children[0] is first_item
            assert results_list.index == 0
            assert not app.query_one("#open-workspace-result", Button).disabled
            assert not app.query_one("#clear-selected", Button).disabled

            # Toggle again
            await pilot.press("space")
            assert run_dir not in app._selected_runs
            assert not app.query_one("#open-workspace-result", Button).disabled
            assert app.query_one("#clear-selected", Button).disabled

    anyio.run(main)


def test_tui_settings_save_roundtrips_before_applying(tmp_path, monkeypatch):
    from hound import tui
    from hound.preferences import load_tui_preferences, save_tui_preferences as save_preferences
    from hound.tui import HoundTui, SettingsScreen
    from textual.widgets import Button, Input

    keyring: dict[str, str] = {}
    monkeypatch.setattr(tui, "get_api_key", lambda provider: keyring.get(provider, ""))
    monkeypatch.setattr(tui, "set_api_key", lambda provider, key: keyring.__setitem__(provider, key))
    monkeypatch.setattr(tui, "delete_api_key", lambda provider: keyring.pop(provider, None))
    monkeypatch.setattr(
        tui,
        "save_tui_preferences",
        lambda offline, provider, model, **kwargs: save_preferences(offline, provider, model, tmp_path / "tui.yml", **kwargs),
    )
    app = HoundTui(
        logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=False,
        provider="openai", model="initial-model",
    )

    async def main():
        async with app.run_test() as pilot:
            app.action_open_settings()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SettingsScreen)
            screen.query_one("#settings-model-manual", Input).value = "team/new-model"
            screen.query_one("#settings-base-url", Input).value = "https://models.example/v1"
            screen.query_one("#settings-api-key", Input).value = "test-key"
            screen.query_one("#settings-repo-dir", Input).value = "repo"
            screen.query_one("#settings-context-path", Input).value = "context.json"
            screen.query_one("#settings-jobs", Input).value = "3"
            screen.query_one("#settings-max-llm-calls", Input).value = "12"
            screen.query_one("#settings-max-cost", Input).value = "1.5"
            screen.query_one("#settings-max-retries", Input).value = "2"
            screen.query_one("#settings-redact", Button).press()
            screen.query_one("#settings-dedup", Button).press()
            screen.query_one("#settings-save", Button).press()
            await pilot.pause()

            assert app.model == "team/new-model"
            assert app.base_url == "https://models.example/v1"
            assert app.jobs == 3
            assert app.redact is False
            assert app.no_dedup is True
            assert app.max_retries == 2
            assert app.state_path is None
            assert keyring == {"openai": "test-key"}
            persisted = load_tui_preferences(tmp_path / "tui.yml")
            assert persisted["model"] == "team/new-model"
            assert persisted["base_url"] == "https://models.example/v1"
            assert persisted["repo_dir"] == "repo"
            assert persisted["context_path"] == "context.json"
            assert persisted["jobs"] == 3
            assert persisted["max_llm_calls"] == 12
            assert persisted["max_cost_usd"] == 1.5
            assert persisted["redact"] is False
            assert persisted["no_dedup"] is True
            assert persisted["max_retries"] == 2

    anyio.run(main)


def test_tui_results_list_selection_event_opens_the_indexed_result(tmp_path):
    from hound.tui import HoundTui
    from textual.widgets import ListView

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)
    opened: list[bool] = []
    app._open_workspace_result = lambda **_kwargs: opened.append(True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.press("l")
            await pilot.pause()

            run_dir = tmp_path / "out" / "run-1"
            app._apply_run_index([
                {
                    "path": run_dir,
                    "report": run_dir / "report.json",
                    "modified": 100,
                    "artifact": "pytest_fail.log",
                    "stage": "test",
                    "severity": "high",
                    "summary": "fail",
                    "hypothesis": "bug",
                    "invalid": False,
                }
            ])
            await pilot.pause()

            results_list = app.query_one("#results-workspace-list", ListView)
            results_list.index = 0
            app._add_selected_run(run_dir)
            app._refresh_results_selection()
            app.on_list_view_selected(ListView.Selected(results_list, results_list.children[0]))
            assert opened == [True]
            assert run_dir in app._selected_runs

    anyio.run(main)


def test_tui_results_workspace_filters_recent_runs(tmp_path):
    from hound.tui import HoundTui
    from textual.widgets import Input, Select

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            app._apply_run_index([
                {"path": tmp_path / "old", "report": tmp_path / "old.json", "modified": 1,
                 "artifact": "pytest.log", "stage": "test", "severity": "high",
                 "summary": "assertion failed", "hypothesis": "database timeout", "invalid": False},
                {"path": tmp_path / "new", "report": tmp_path / "new.json", "modified": 2,
                 "artifact": "deploy.log", "stage": "deploy", "severity": "low",
                 "summary": "rollout failed", "hypothesis": "image missing", "invalid": False},
            ])
            app.query_one("#workspace-run-filter", Input).value = "database"
            await pilot.pause(0.3)
            assert app._runs == [tmp_path / "old"]
            app.query_one("#workspace-run-filter", Input).value = ""
            app.query_one("#workspace-run-stage", Select).value = "deploy"
            await pilot.pause()
            assert app._runs == [tmp_path / "new"]

    anyio.run(main)


def test_clear_managed_results_only_removes_valid_runs(tmp_path):
    from hound.output.report import ensure_outdir
    from hound.tui import clear_managed_results

    output = ensure_outdir(tmp_path / "out")
    valid = ensure_outdir(output / "run-valid")
    (valid / "report.json").write_text("{}", encoding="utf-8")
    invalid = output / "run-invalid"
    invalid.mkdir()
    (invalid / "report.json").write_text("{}", encoding="utf-8")
    outside = ensure_outdir(tmp_path / "outside")
    (outside / "report.json").write_text("{}", encoding="utf-8")

    cleared, failed = clear_managed_results(output, [valid, invalid, outside])

    assert (cleared, failed) == (1, 2)
    assert not valid.exists()
    assert invalid.exists()
    assert outside.exists()
    assert (output / ".hound-owned").is_file()


def test_clear_managed_root_result_preserves_state_and_marker(tmp_path):
    from hound.output.report import ensure_outdir
    from hound.tui import clear_managed_results

    output = ensure_outdir(tmp_path / "out")
    for filename in ("report.json", "report.md", "ticket.md"):
        (output / filename).write_text("result", encoding="utf-8")
    state_dir = output / ".hound"
    state_dir.mkdir()
    (state_dir / "state.json").write_text("[]", encoding="utf-8")

    assert clear_managed_results(output, [output]) == (1, 0)
    assert not (output / "report.json").exists()
    assert (output / ".hound-owned").is_file()
    assert (state_dir / "state.json").is_file()


def test_tui_clear_all_requires_typed_confirmation(tmp_path):
    from hound.output.report import ensure_outdir
    from hound.tui import ClearResultsScreen, HoundTui
    from textual.widgets import Button, Input

    output = ensure_outdir(tmp_path / "out")
    run = ensure_outdir(output / "run-one")
    (run / "report.json").write_text("{}", encoding="utf-8")
    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(output), offline=True)

    async def main():
        async with app.run_test() as pilot:
            app.push_screen(ClearResultsScreen(app, [run], clear_all=True))
            await pilot.pause()
            confirm = app.screen.query_one("#clear-confirm", Button)
            assert confirm.disabled
            app.screen.query_one("#clear-confirmation", Input).value = "CLEAR"
            await pilot.pause()
            assert not confirm.disabled

    anyio.run(main)


def test_tui_clear_all_removes_indexed_results(tmp_path):
    from hound.output.report import ensure_outdir
    from hound.tui import ClearResultsScreen, HoundTui
    from textual.widgets import Button, Input

    output = ensure_outdir(tmp_path / "out")
    run = ensure_outdir(output / "run-one")
    (run / "report.json").write_text("{}", encoding="utf-8")
    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(output), offline=True)

    async def main():
        async with app.run_test() as pilot:
            app._apply_run_index([
                {
                    "path": run,
                    "report": run / "report.json",
                    "modified": 100,
                    "artifact": "pytest_fail.log",
                    "stage": "test",
                    "severity": "high",
                    "summary": "fail",
                    "hypothesis": "bug",
                    "invalid": False,
                }
            ])
            await pilot.pause()

            clear_all = app.query_one("#clear-all", Button)
            assert not clear_all.disabled
            clear_all.press()
            await pilot.pause()

            assert isinstance(app.screen, ClearResultsScreen)
            app.screen.query_one("#clear-confirmation", Input).value = "CLEAR"
            await pilot.pause()
            app.screen.query_one("#clear-confirm", Button).press()
            await pilot.pause()
            assert not run.exists()

    anyio.run(main)


def test_tui_clear_selected_removes_selected_result(tmp_path):
    from hound.output.report import ensure_outdir
    from hound.tui import ClearResultsScreen, HoundTui
    from textual.widgets import Button

    output = ensure_outdir(tmp_path / "out")
    run = ensure_outdir(output / "run-one")
    (run / "report.json").write_text("{}", encoding="utf-8")
    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(output), offline=True)

    async def main():
        async with app.run_test() as pilot:
            app._apply_run_index([
                {
                    "path": run,
                    "report": run / "report.json",
                    "modified": 100,
                    "artifact": "pytest_fail.log",
                    "stage": "test",
                    "severity": "high",
                    "summary": "fail",
                    "hypothesis": "bug",
                    "invalid": False,
                }
            ])
            app._add_selected_run(run)
            app._refresh_results_selection()
            await pilot.pause()

            clear_selected = app.query_one("#clear-selected", Button)
            assert not clear_selected.disabled
            clear_selected.press()
            await pilot.pause()

            assert isinstance(app.screen, ClearResultsScreen)
            app.screen.query_one("#clear-confirm", Button).press()
            await pilot.pause()
            assert not run.exists()

    anyio.run(main)


def test_run_tui_forwards_no_redact(monkeypatch):
    from hound.cli import run_tui
    import hound.tui

    captured = {}

    class FakeApp:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self):
            pass

    monkeypatch.setattr(hound.tui, "HoundTui", FakeApp)
    args = Namespace(
        logs=None,
        repo=None,
        out="out",
        offline=True,
        config=None,
        provider=None,
        model=None,
        base_url=None,
        api_key=None,
        no_redact=True,
    )
    assert run_tui(args) == 0
    assert captured["redact"] is False


def test_tui_focus_file_list_shortcut(tmp_path):
    from hound.tui import HoundTui
    from textual.widgets import ListView

    (tmp_path / "a.log").write_text("ERROR 1", encoding="utf-8")
    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            # Press 'g' to focus sidebar file list
            await pilot.press("g")
            assert app.focused == app.query_one("#log-list", ListView)

            # Switch to artifacts workspace and press 'g'
            await pilot.press("f")
            await pilot.pause()
            await pilot.press("g")
            assert app.focused == app.query_one("#artifact-workspace-list", ListView)

            # Switch to results workspace and press 'g'
            await pilot.press("l")
            await pilot.pause()
            await pilot.press("g")
            assert app.focused == app.query_one("#results-workspace-list", ListView)

    anyio.run(main)


def test_tui_workspace_pagination_buttons(tmp_path, monkeypatch):
    from hound.tui import HoundTui, PAGE_SIZE
    from textual.widgets import Button, Static

    # Create enough log files to span 3 pages
    for i in range(PAGE_SIZE * 2 + 10):
        (tmp_path / f"log-{i:03d}.log").write_text(f"ERROR {i}", encoding="utf-8")

    monkeypatch.setattr(HoundTui, "_log_classification", staticmethod(lambda _path: ("build", "build")))
    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("f")
            await pilot.pause()

            # Verify page 1
            assert app._artifact_page == 1
            label = str(app.query_one("#artifact-pagination-label", Static).renderable)
            assert "Page 1/3" in label
            assert app.query_one("#artifact-prev", Button).disabled is True
            assert app.query_one("#artifact-next", Button).disabled is False

            # Click next button
            app.query_one("#artifact-next", Button).press()
            await pilot.pause()
            assert app._artifact_page == 2
            assert app.query_one("#artifact-prev", Button).disabled is False
            assert app.query_one("#artifact-next", Button).disabled is False

            # Click prev button
            app.query_one("#artifact-prev", Button).press()
            await pilot.pause()
            assert app._artifact_page == 1

            # Test keyboard shortcuts p and n.
            await pilot.press("n")
            await pilot.pause()
            assert app._artifact_page == 2
            await pilot.press("p")
            await pilot.pause()
            assert app._artifact_page == 1

    anyio.run(main)


def test_run_tui_forwards_context_path(monkeypatch):
    from hound.cli import run_tui
    import hound.tui

    captured = {}

    class FakeApp:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self):
            pass

    monkeypatch.setattr(hound.tui, "HoundTui", FakeApp)
    args = Namespace(
        logs=None,
        repo=None,
        out="out",
        offline=True,
        config=None,
        provider=None,
        model=None,
        base_url=None,
        api_key=None,
        no_redact=False,
        context="context.json",
    )
    assert run_tui(args) == 0
    assert captured["context_path"] == "context.json"


def test_tui_explicit_false_empty_paths_and_one_override_saved_preferences(tmp_path, monkeypatch):
    from hound import tui
    from hound.tui import HoundTui

    monkeypatch.setattr(tui, "load_tui_preferences", lambda: {
        "offline": True,
        "provider": None,
        "model": None,
        "base_url": None,
        "repo_dir": str(tmp_path / "saved-repo"),
        "context_path": str(tmp_path / "saved-context.json"),
        "source_class": "local_artifact",
        "source_context": True,
        "enrich": True,
        "jobs": 8,
        "max_llm_calls": None,
        "max_cost_usd": None,
    })

    app = HoundTui(
        logs_dir=str(tmp_path),
        out_dir=str(tmp_path / "out"),
        offline=True,
        repo_dir="",
        context_path="",
        source_context=False,
        enrich=False,
        jobs=1,
    )

    assert app.repo_dir is None
    assert app.context_path is None
    assert app.source_context is False
    assert app.enrich is False
    assert app.jobs == 1


def test_tui_forwards_context_and_enrichment_to_single_analysis(tmp_path, monkeypatch):
    from hound.tui import HoundTui

    log = tmp_path / "failure.log"
    log.write_text("ERROR deployment failed", encoding="utf-8")
    context = tmp_path / "context.json"
    context.write_text("{}", encoding="utf-8")
    captured = {}
    app = HoundTui(
        logs_dir=str(tmp_path),
        out_dir=str(tmp_path / "out"),
        offline=True,
        context_path=str(context),
        source_context=True,
        enrich=True,
    )

    async def fake_analyze(path, request):
        captured["path"] = path
        captured.update(request)
        app._analyzing = False

    monkeypatch.setattr(app, "_analyze", fake_analyze)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app._selected_log = log
            app.action_analyze()
            for _ in range(100):
                if captured:
                    break
                await pilot.pause(0.02)

    anyio.run(main)
    assert captured["path"] == log
    assert captured["context_path"] == str(context)
    assert captured["source_context"] is True
    assert captured["enrich"] is True


def test_tui_overview_evidence_has_no_mojibake():
    from hound.tui import _overview_text

    text = _overview_text({
        "failure": {}, "root_cause": {}, "triage": {}, "meta": {},
        "analysis": {
            "hypotheses": [{"supporting_evidence_refs": ["ev-1"]}],
            "evidence": [{"id": "ev-1", "value": "compiler output"}],
        },
    })
    assert "• ev-1 compiler output" in text
    assert "â" not in text


def test_tui_overview_uses_semantic_colors_for_severity_and_confidence():
    from hound.tui import SEMANTIC_ERROR, SEMANTIC_SUCCESS, _overview_text

    text = _overview_text({
        "failure": {},
        "root_cause": {"confidence": "high"},
        "triage": {"severity": "high"},
        "meta": {},
    })

    assert f"[bold {SEMANTIC_ERROR}]HIGH" in text
    assert f"[{SEMANTIC_SUCCESS}]high" in text


def test_tui_settings_provider_change_updates_base_url(tmp_path):
    from hound.tui import HoundTui, SettingsScreen
    from textual.widgets import Input, Select

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True, provider="openai")

    async def main():
        async with app.run_test() as pilot:
            app.action_open_settings()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SettingsScreen)
            screen.query_one("#settings-provider", Select).value = "gemini"
            await pilot.pause()
            assert "generativelanguage.googleapis.com" in screen.query_one("#settings-base-url", Input).value

    anyio.run(main)


def test_tui_settings_connection_runs_without_blocking_ui(tmp_path, monkeypatch):
    import time

    from hound import tui
    from hound.tui import HoundTui, SettingsScreen
    from textual.widgets import Button, Static

    def discover(_base_url, _key):
        time.sleep(0.15)
        return ["model-a"]

    monkeypatch.setattr(tui, "discover_models", discover)
    monkeypatch.setattr(tui, "cache_models", lambda *_args: None)
    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True, provider="openai")

    async def main():
        async with app.run_test() as pilot:
            app.action_open_settings()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SettingsScreen)
            screen.query_one("#settings-offline", Button).press()
            await pilot.pause()
            connect = screen.query_one("#settings-connect", Button)
            connect.press()
            await pilot.pause(0.02)
            assert connect.disabled
            assert "Connecting" in str(connect.label)
            for _ in range(50):
                await pilot.pause(0.02)
                if not connect.disabled:
                    break
            assert not connect.disabled
            assert "1 models discovered" in str(screen.query_one("#auth-status", Static).renderable)

    anyio.run(main)


def test_tui_compact_workspace_controls_do_not_overflow_horizontally(tmp_path):
    from hound.tui import HoundTui

    (tmp_path / "a.log").write_text("ERROR build failed", encoding="utf-8")
    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test(size=(60, 20)) as pilot:
            await pilot.press("f")
            await pilot.pause()
            workspace = app.query_one("#artifact-workspace").region
            for selector in (
                "#workspace-artifact-filter", "#workspace-artifact-type", "#workspace-artifact-sort",
                "#artifact-prev", "#artifact-pagination-label", "#artifact-next",
                "#workspace-analyze", "#workspace-analyze-all", "#workspace-select-all",
                "#workspace-deselect-all", "#workspace-browse", "#workspace-refresh",
            ):
                region = app.query_one(selector).region
                assert region.x >= workspace.x
                assert region.right <= workspace.right

    anyio.run(main)


def test_tui_refresh_prunes_stale_result_selection(tmp_path):
    from hound.tui import HoundTui

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)
    stale = tmp_path / "out" / "deleted-run"

    async def main():
        async with app.run_test() as pilot:
            app._add_selected_run(stale)
            app._apply_run_index([])
            await pilot.pause()
            assert not app._selected_runs

    anyio.run(main)


def test_tui_failed_analysis_clears_previous_report_and_ticket(tmp_path, monkeypatch):
    from hound import tui
    from hound.tui import HoundTui
    from textual.widgets import Static

    log = tmp_path / "failure.log"
    log.write_text("ERROR build failed", encoding="utf-8")
    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    def fail(*_args, **_kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(tui.service, "analyze_log", fail)

    async def main():
        async with app.run_test() as pilot:
            app._update_markdown("#report", "# Old report")
            app._update_markdown("#ticket", "# Old ticket")
            app.action_analyze()
            for _ in range(100):
                await pilot.pause(0.02)
                if "Analysis failed" in str(app.query_one("#overview", Static).renderable):
                    break
            assert "Old report" not in app._report_markdown
            assert "Old ticket" not in app._ticket_markdown
            assert "analysis failed" in app._report_markdown

    anyio.run(main)


def test_tui_copy_shortcut_is_scoped_to_report_and_ticket_tabs(tmp_path, monkeypatch):
    from hound.tui import HoundTui

    copied = []
    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)
    monkeypatch.setattr(app, "copy_to_clipboard", copied.append)

    async def main():
        async with app.run_test() as pilot:
            app._update_markdown("#report", "# Current report")
            app._update_markdown("#ticket", "# Current ticket")

            app._show_results("pane-report")
            await pilot.pause()
            await pilot.press("c")
            assert copied == ["# Current report"]

            app._show_results("pane-ticket")
            await pilot.pause()
            await pilot.press("c")
            assert copied == ["# Current report", "# Current ticket"]

            for pane in ("pane-overview", "pane-raw", "pane-context"):
                app._show_results(pane)
                await pilot.pause()
                await pilot.press("c")
            assert copied == ["# Current report", "# Current ticket"]

            app._show_home()
            await pilot.pause()
            await pilot.press("c")
            assert copied == ["# Current report", "# Current ticket"]

    anyio.run(main)


def test_tui_stop_after_current_keeps_completed_result(tmp_path):
    from hound.tui import HoundTui
    from textual.widgets import Static

    log = tmp_path / "failure.log"
    log.write_text("ERROR build failed", encoding="utf-8")
    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True, no_dedup=True)

    async def main():
        async with app.run_test() as pilot:
            app.action_analyze()
            app.action_stop_analysis()
            for _ in range(200):
                await pilot.pause(0.02)
                if not app._analyzing:
                    break
            assert list((tmp_path / "out").glob("run-*/report.json"))
            assert "result was saved" in str(app.query_one("#overview", Static).renderable)

    anyio.run(main)


def test_tui_settings_connection_error_is_recoverable(tmp_path, monkeypatch):
    from hound import tui
    from hound.tui import HoundTui, SettingsScreen
    from textual.widgets import Button, Static

    monkeypatch.setattr(tui, "discover_models", lambda *_args: (_ for _ in ()).throw(ValueError("authentication failed")))
    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True, provider="openai")

    async def main():
        async with app.run_test() as pilot:
            app.action_open_settings()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SettingsScreen)
            screen.query_one("#settings-offline", Button).press()
            await pilot.pause()
            connect = screen.query_one("#settings-connect", Button)
            connect.press()
            for _ in range(50):
                await pilot.pause(0.02)
                if not connect.disabled:
                    break
            assert not connect.disabled
            assert "Connection failed" in str(screen.query_one("#auth-status", Static).renderable)

    anyio.run(main)


def test_tui_settings_opens_when_custom_provider_registry_is_invalid(tmp_path, monkeypatch):
    from hound import tui
    from hound.tui import HoundTui, SettingsScreen
    from textual.widgets import Select

    monkeypatch.setattr(tui, "load_custom_providers", lambda: (_ for _ in ()).throw(ValueError("invalid registry")))
    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True, provider="openai")

    async def main():
        async with app.run_test() as pilot:
            app.action_open_settings()
            await pilot.pause()
            assert isinstance(app.screen, SettingsScreen)
            assert app.screen.query_one("#settings-provider", Select).value == "openai"

    anyio.run(main)


def test_tui_home_and_settings_expose_trust_capabilities(tmp_path):
    from hound.tui import HoundTui, SettingsScreen
    from textual.widgets import Button, Static

    app = HoundTui(
        logs_dir=str(tmp_path),
        out_dir=str(tmp_path / "out"),
        offline=True,
        source_class="local_artifact",
    )

    async def main():
        async with app.run_test(size=(130, 35)) as pilot:
            await pilot.pause()
            assert "TRUST" in str(app.query_one("#home-capabilities", Static).renderable)
            assert "local_artifact" in str(app.query_one("#home-capabilities", Static).renderable)
            assert "DIAGNOSTICS" in str(app.query_one("#home-diagnostics", Static).renderable)

            app.query_one("#nav-qa", Button).press()
            await pilot.pause()
            assert app.query_one("#qa-workspace").display
            assert app.query_one("#nav-qa", Button).has_class("is-active")
            assert "SARIF" in str(app.query_one("#qa-workspace").query(".qa-description").first(Static).renderable)

            app.action_show_overview()
            await pilot.pause()
            assert app.query_one("#results-workspace").display
            assert app.query_one("#nav-results", Button).has_class("is-active")
            assert not app.query_one("#nav-qa", Button).has_class("is-active")
            assert "Connector collection remains" in str(app.query_one("#investigation-workspace-meta", Static).renderable)
            assert "No report selected" in str(app.query_one("#investigation", Static).renderable)
            assert app.query_one("#context-validate", Button).disabled

            app.action_open_settings()
            await pilot.pause()
            assert isinstance(app.screen, SettingsScreen)
            for selector in (
                "#settings-repo-dir", "#settings-context-path", "#settings-source-class",
                "#settings-evidence-options", "#settings-source-context", "#settings-enrich", "#settings-jobs",
                "#settings-max-llm-calls", "#settings-max-cost", "#settings-trust",
                "#settings-redact", "#settings-dedup", "#settings-max-retries",
                "#settings-session-summary", "#settings-session-paths",
            ):
                assert app.screen.query_one(selector)
            assert "Evidence collection options" in str(app.screen.query_one("#settings-evidence-options", Static).renderable)
            source_class = app.screen.query_one("#settings-source-class")
            source_context = app.screen.query_one("#settings-source-context")
            enrichment = app.screen.query_one("#settings-enrich")
            assert source_context.region.y > source_class.region.y
            assert enrichment.region.y == source_context.region.y
            assert source_context.region.right <= enrichment.region.x
            assert "TRUST PROFILE" in str(app.screen.query_one("#settings-trust", Static).renderable)
            assert "Output:" in str(app.screen.query_one("#settings-session-paths", Static).renderable)

    anyio.run(main)


def test_tui_context_validation_readiness_legacy_and_fork_trust(tmp_path):
    import copy
    import json

    from hound.models import validate
    from hound.output.report import ensure_outdir
    from hound.pipeline import analyze
    from hound.tui import HoundTui
    from textual.widgets import Button, Static

    log = tmp_path / "deployment_timeline.log"
    shutil.copy(FIXTURES / "deployment_timeline.log", log)
    output = ensure_outdir(tmp_path / "out")
    run_dir = output / "run-context"
    document = analyze(log, run_dir, offline=True)
    deployment = document["context"]["deployment"]
    deployment.update({
        "platform": "kubernetes",
        "environment": "production",
        "service": "api",
        "workload": "deployment/api",
        "target": "deployment/api",
        "namespace": "default",
        "revision": "release-42",
        "previous_revision": "release-41",
        "customer_impact": "degraded",
    })
    document["context"]["connector_audits"] = [
        {
            "connector": "kubernetes",
            "operation": "workload_state",
            "resource": "deployment/api",
            "namespace": "default",
            "status": "collected",
            "observed_at": "2026-01-01T00:00:00+00:00",
            "duration_ms": 2,
            "output_bytes": 42,
            "returncode": 0,
            "error": "",
        },
        {
            "connector": "kubernetes",
            "operation": "related_events",
            "resource": "deployment/api",
            "namespace": "default",
            "status": "command_failed",
            "observed_at": "2026-01-01T00:00:01+00:00",
            "duration_ms": 3,
            "output_bytes": 0,
            "returncode": 1,
            "error": "bounded command failed",
        },
    ]
    document["devops"].update({
        "metric_samples": [{"metric": "http_5xx_rate", "value": 0.2}],
        "trace_spans": [{"trace_id": "trace-1", "span_id": "span-1", "service": "api"}],
        "release_changes": [{"field": "revision", "current": "release-42", "previous": "release-41", "status": "changed"}],
        "static_severity": "high",
        "effective_severity": "critical",
    })
    validate(document)
    (run_dir / "report.json").write_text(json.dumps(document), encoding="utf-8")

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(output), offline=True)

    async def main():
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._apply_run_index([{
                "path": run_dir,
                "report": run_dir / "report.json",
                "modified": 1,
                "artifact": log.name,
                "stage": "deploy",
                "severity": "critical",
                "summary": "rollout failed",
                "hypothesis": "readiness probe failed",
                "invalid": False,
            }])
            app._load_run(run_dir)
            await pilot.pause(0.1)
            app.action_show_overview()
            await pilot.pause()

            assert app.query_one("#tabs").active == "pane-overview"
            app.query_one("#tabs").active = "pane-context"
            await pilot.pause()

            status = str(app.query_one("#context-status", Static).renderable)
            rendered = str(app.query_one("#investigation", Static).renderable)
            assert "[PASS]" in status
            assert not app.query_one("#context-validate", Button).disabled
            for expected in (
                "Context validation & readiness",
                "schema: 2.0",
                "connector readiness:",
                "audit(s) collected",
                "observability: present",
                "static=high",
                "effective=critical",
                "customer impact: degraded",
                "Release comparison",
                "missing evidence:",
            ):
                assert expected in rendered

            await pilot.press("u")
            await pilot.pause()

            legacy = copy.deepcopy(document)
            legacy["schema_version"] = "1.4"
            app._current_doc = legacy
            app._refresh_current_context()
            await pilot.pause()
            assert "legacy 1.4 accepted" in str(app.query_one("#investigation", Static).renderable)

            invalid = copy.deepcopy(document)
            invalid["context"]["deployment"]["namespace"] = 7
            app._current_doc = invalid
            app._refresh_current_context()
            await pilot.pause()
            assert "[FAIL]" in str(app.query_one("#context-status", Static).renderable)
            assert "invalid:" in str(app.query_one("#investigation", Static).renderable)

            fork = copy.deepcopy(document)
            fork["meta"]["trust"]["source_class"] = "fork_pr"
            app._current_doc = fork
            app._refresh_current_context()
            await pilot.pause()
            assert "BLOCKED (fork_pr fail-closed)" in str(app.query_one("#investigation", Static).renderable)

    anyio.run(main)


def test_tui_qa_history_and_show_test_statistics(tmp_path):
    shutil.copy(FIXTURES / "junit_flaky.xml", tmp_path / "junit_flaky.xml")
    from hound.qa.history import default_history_store, upsert_results
    from hound.qa.normalize import import_artifact
    from hound.tui import HoundTui
    from textual.widgets import Button, ListView, Static

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)
    history = default_history_store(app.out_dir)
    upsert_results(history, import_artifact(tmp_path / "junit_flaky.xml", "cli-run", "", "", ""))

    async def main():
        async with app.run_test() as pilot:
            await pilot.press("y")
            await pilot.pause()
            assert app.query_one("#qa-history-list", ListView).display is False
            app.query_one("#qa-load-history", Button).press()
            for _ in range(200):
                await pilot.pause(0.02)
                if app._qa_result and app._qa_result.get("type") == "history":
                    break
            assert app._qa_result["type"] == "history"
            assert app._qa_history_tests
            history_list = app.query_one("#qa-history-list", ListView)
            assert history_list.display is True
            history_list.index = 0
            app.on_list_view_selected(ListView.Selected(history_list, history_list.children[0]))
            for _ in range(200):
                await pilot.pause(0.02)
                if app._qa_result and app._qa_result.get("type") == "stats":
                    break
            assert app._qa_result["type"] == "stats"
            assert history_list.display is True
            rendered = str(app.query_one("#qa-result", Static).renderable)
            assert "TEST STATISTICS" in rendered
            assert "total_eventually_returns" in rendered
            assert not app.query("#qa-import")

    anyio.run(main)


def test_tui_imports_qa_history_from_workspace(tmp_path):
    import sqlite3

    shutil.copy(FIXTURES / "junit_flaky.xml", tmp_path / "junit_flaky.xml")
    from hound.tui import HoundTui
    from textual.widgets import Button, ListView, Static

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.press("y")
            await pilot.pause()
            app.query_one("#qa-import-history", Button).press()
            for _ in range(250):
                await pilot.pause(0.02)
                if app._qa_result and app._qa_result.get("type") == "import":
                    break
            assert app._qa_result and app._qa_result["type"] == "import"
            assert app._qa_result["imported"] > 0
            assert "HISTORY IMPORT COMPLETE" in str(app.query_one("#qa-result", Static).renderable)
            assert app.query_one("#qa-history-list", ListView).display is False

            app.query_one("#qa-load-history", Button).press()
            for _ in range(250):
                await pilot.pause(0.02)
                if app._qa_result and app._qa_result.get("type") == "history":
                    break
            assert app._qa_result and app._qa_result["type"] == "history"
            assert app._qa_history_tests
            assert app.query_one("#qa-history-list", ListView).display is True
            assert "TRACKED TESTS" in str(app.query_one("#qa-result", Static).renderable)
            with sqlite3.connect(app.out_dir / ".hound" / "history.sqlite3") as connection:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(test_results)")}
            assert "log_text" not in columns
            assert "raw_log" not in columns

    anyio.run(main)


def test_tui_qa_analyze_without_history_is_explicitly_insufficient(tmp_path):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    from hound.tui import HoundTui
    from textual.widgets import Button, ListView, Static

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.press("y")
            await pilot.pause()
            app.query_one("#qa-analyze", Button).press()
            for _ in range(250):
                await pilot.pause(0.02)
                if app._qa_result and app._qa_result.get("type") == "insights":
                    break
            assert app._qa_result["type"] == "insights"
            classifications = app._qa_result["classifications"]
            assert classifications
            assert classifications[0]["decision"] == "insufficient_history"
            assert app.query_one("#qa-history-list", ListView).display is False
            assert "insufficient_history" in str(app.query_one("#qa-result", Static).renderable)

    anyio.run(main)


def test_tui_quality_gate_distinguishes_policy_block_from_analysis_status(tmp_path):
    import subprocess

    repo = tmp_path / "repo"
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "qa@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "QA"], check=True)
    (repo / "app.py").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "app.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "base"], check=True, capture_output=True)
    baseline = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    shutil.copy(FIXTURES / "pytest_fail.log", artifacts / "pytest_fail.log")
    policy = tmp_path / "quality.yml"
    policy.write_text("version: '1.0'\nrules:\n  new_failure: block\n", encoding="utf-8")

    from hound.tui import HoundTui
    from textual.widgets import Button, Input, ListView, Static

    app = HoundTui(
        logs_dir=str(artifacts),
        repo_dir=str(repo),
        out_dir=str(tmp_path / "out"),
        offline=True,
    )

    async def main():
        async with app.run_test() as pilot:
            await pilot.press("y")
            await pilot.pause()
            app.query_one("#qa-repo-dir", Input).value = str(repo)
            app.query_one("#qa-baseline", Input).value = baseline
            app.query_one("#qa-head", Input).value = baseline
            app.query_one("#qa-policy", Input).value = str(policy)
            await pilot.pause()
            preview = str(app.query_one("#qa-policy-preview", Static).renderable)
            assert "ACTIVE QUALITY POLICY" in preview
            assert "new_failure" in preview
            app.query_one("#qa-gate", Button).press()
            for _ in range(300):
                await pilot.pause(0.02)
                if app._qa_result and app._qa_result.get("type") == "gate":
                    break
            assert app._qa_result["type"] == "gate"
            gate = app._qa_result["result"]
            assert gate["policy_outcome"] == "block"
            assert gate["analysis_status"] == "insufficient_evidence"
            assert app.query_one("#qa-history-list", ListView).display is False
            rendered = str(app.query_one("#qa-result", Static).renderable)
            assert "QUALITY GATE: BLOCK" in rendered
            assert "analysis status" in rendered

            invalid_policy = tmp_path / "invalid-quality.yml"
            invalid_policy.write_text("version: '0.1'\nrules: {}\n", encoding="utf-8")
            app.query_one("#qa-policy", Input).value = str(invalid_policy)
            await pilot.pause()
            app.query_one("#qa-gate", Button).press()
            await pilot.pause()
            assert not app._qa_busy
            assert "invalid" in str(app.query_one("#qa-status", Static).renderable).lower()
            assert "Invalid policy" in str(app.query_one("#qa-policy-preview", Static).renderable)

    anyio.run(main)


def test_tui_feedback_modal_records_review_for_loaded_run(tmp_path):
    from hound.output.report import ensure_outdir
    from hound.pipeline import analyze
    from hound.tui import FeedbackScreen, HoundTui
    from textual.widgets import Button

    log = tmp_path / "pytest_fail.log"
    shutil.copy(FIXTURES / "pytest_fail.log", log)
    output = ensure_outdir(tmp_path / "out")
    run_dir = output / "run-one"
    analyze(log, run_dir, offline=True)
    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(output), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app._load_run(run_dir)
            await pilot.pause(0.05)
            app.action_open_feedback()
            await pilot.pause()
            assert isinstance(app.screen, FeedbackScreen)
            await pilot.press("right")
            assert isinstance(app.screen, FeedbackScreen)
            app.screen.query_one("#feedback-save", Button).press()
            for _ in range(250):
                await pilot.pause(0.02)
                if not isinstance(app.screen, FeedbackScreen):
                    break
            assert not isinstance(app.screen, FeedbackScreen)
            assert (output / ".hound" / "feedback.sqlite3").is_file()

    anyio.run(main)


def test_tui_investigation_renderer_keeps_structured_evidence_distinct():
    from hound.tui import _investigation_text

    rendered = _investigation_text({
        "meta": {"log_file": "deploy.log"},
        "context": {
            "deployment": {"service": "checkout", "release": "r2", "outcome": "rolled_back"},
            "run": {"workflow": "deploy", "commit_sha": "abc123"},
            "owners": ["payments"],
            "source_evidence": [{"file": "src/app.py", "line": 12, "symbol": {"name": "charge"}, "changed": True}],
            "connector_audits": [{"connector": "kubectl", "operation": "get", "status": "collected", "duration_ms": 4}],
        },
        "timeline": {
            "grouping": "pipeline", "ordering_basis": "sequence", "customer_impact": "degraded",
            "entries": [{"event_id": "ev-1", "stage": "deploy", "role": "primary", "message": "rollout failed", "sequence": 1}],
        },
        "devops": {
            "release_changes": [{"field": "revision", "previous": "r1", "current": "r2", "status": "changed"}],
            "metric_samples": [], "trace_spans": [], "critical_path": {},
            "slo": {"target": "99.9%", "error_budget_remaining": "5%"}, "runbook": {"url": "https://runbooks/checkout"},
            "effective_severity": "high", "severity_reasons": ["degraded impact"],
        },
        "test_impact": {"missing_coverage": True, "recommendations": [{"test": "test_charge", "score": 0.8}]},
        "triage": {"dedup_key": "k"},
    })
    assert "Deployment & impact" in rendered
    assert "Release comparison" in rendered
    assert "rollout failed" in rendered
    assert "owners: payments" in rendered
    assert "test impact: advisory only" in rendered
    assert "Delivery status" in rendered


def test_tui_statusbar_single_analyze_lifecycle(tmp_path):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    from hound.tui import HoundTui
    from textual.widgets import Static

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            sb = app.query_one("#statusbar", Static)
            assert "idle" in str(sb.renderable)

            # 1. action_analyze starts analysis and updates statusbar to analyzing…
            app.action_analyze()
            assert app._analyzing is True
            assert "analyzing…" in str(sb.renderable)

            # Wait for completion -> returns to idle
            for _ in range(200):
                await pilot.pause(0.02)
                if not app._analyzing:
                    break
            assert not app._analyzing
            assert "idle" in str(sb.renderable)

            # 2. _analyze_selected alias starts analysis and updates statusbar to analyzing…
            app._analyze_selected()
            assert app._analyzing is True
            assert "analyzing…" in str(sb.renderable)

            for _ in range(200):
                await pilot.pause(0.02)
                if not app._analyzing:
                    break
            assert not app._analyzing
            assert "idle" in str(sb.renderable)

    anyio.run(main)


def test_tui_statusbar_single_analyze_failure_and_stop(tmp_path, monkeypatch):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    from hound import service
    from hound.tui import HoundTui
    from textual.widgets import Static

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            sb = app.query_one("#statusbar", Static)
            assert "idle" in str(sb.renderable)

            # 1. Failure during analysis: statusbar must update to idle
            def failing_analyze(*_args, **_kwargs):
                raise RuntimeError("Simulated analysis error")

            monkeypatch.setattr(service, "analyze_log", failing_analyze)
            app.action_analyze()
            assert app._analyzing is True
            assert "analyzing…" in str(sb.renderable)

            for _ in range(200):
                await pilot.pause(0.02)
                if not app._analyzing:
                    break
            assert not app._analyzing
            assert "idle" in str(sb.renderable)
            assert "Analysis failed" in str(app.query_one("#overview", Static).renderable)

            # 2. Stop requested: statusbar must update to idle
            monkeypatch.undo()
            app.action_analyze()
            assert app._analyzing is True
            assert "analyzing…" in str(sb.renderable)
            app.action_stop_analysis()
            for _ in range(200):
                await pilot.pause(0.02)
                if not app._analyzing:
                    break
            assert not app._analyzing
            assert "idle" in str(sb.renderable)

            # 3. Worker spawning failure: statusbar must reset to idle
            def failing_run_worker(*_args, **_kwargs):
                raise RuntimeError("Spawn failure")

            monkeypatch.setattr(app, "run_worker", failing_run_worker)
            app.action_analyze()
            assert not app._analyzing
            assert "idle" in str(sb.renderable)

    anyio.run(main)


def test_tui_statusbar_batch_analyze_lifecycle(tmp_path, monkeypatch):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    shutil.copy(FIXTURES / "build_error.log", tmp_path / "build_error.log")
    from hound import service
    from hound.tui import HoundTui
    from textual.widgets import Static

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            sb = app.query_one("#statusbar", Static)
            assert "idle" in str(sb.renderable)

            # 1. Batch analysis start via action_analyze_all updates statusbar to analyzing…
            app.action_analyze_all()
            assert app._analyzing is True
            assert "analyzing…" in str(sb.renderable)
            assert app.query_one("#home").display is True

            for _ in range(400):
                await pilot.pause(0.02)
                if not app._analyzing:
                    break
            assert not app._analyzing
            assert "idle" in str(sb.renderable)
            assert app.query_one("#home").display is True

            # 2. Batch analysis stopped updates statusbar to idle
            app.action_analyze_all()
            assert app._analyzing is True
            assert "analyzing…" in str(sb.renderable)
            app.action_stop_analysis()
            for _ in range(400):
                await pilot.pause(0.02)
                if not app._analyzing:
                    break
            assert not app._analyzing
            assert "idle" in str(sb.renderable)

            # 3. Batch analysis failure updates statusbar to idle
            def failing_analyze(*_args, **_kwargs):
                raise RuntimeError("Batch target error")

            monkeypatch.setattr(service, "analyze_log", failing_analyze)
            app.action_analyze_all()
            assert app._analyzing is True
            assert "analyzing…" in str(sb.renderable)

            for _ in range(400):
                await pilot.pause(0.02)
                if not app._analyzing:
                    break
            assert not app._analyzing
            assert "idle" in str(sb.renderable)

            # 4. Batch worker spawning failure resets statusbar to idle
            monkeypatch.undo()

            def failing_run_worker(*_args, **_kwargs):
                raise RuntimeError("Batch spawn failure")

            monkeypatch.setattr(app, "run_worker", failing_run_worker)
            app.action_analyze_all()
            assert not app._analyzing
            assert "idle" in str(sb.renderable)

    anyio.run(main)


def test_tui_context_validation_persistence_and_cards(tmp_path):
    from hound.output.report import ensure_outdir
    from hound.pipeline import analyze
    from hound.tui import HoundTui
    from hound.validation import default_validation_store, get_latest_validation
    from textual.widgets import Static

    log = tmp_path / "pytest_fail.log"
    shutil.copy(FIXTURES / "pytest_fail.log", log)
    output = ensure_outdir(tmp_path / "out")
    run_dir = output / "run-val"
    analyze(log, run_dir, offline=True)
    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(output), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app._load_run(run_dir)
            await pilot.pause(0.05)
            app._show_workspace("investigation")
            await pilot.pause()

            # Verify context cards exist and are populated
            card_integrity = app.query_one("#context-card-integrity", Static)
            card_trust = app.query_one("#context-card-trust", Static)
            card_impact = app.query_one("#context-card-impact", Static)
            assert "REPORT INTEGRITY" in str(card_integrity.renderable)
            assert "TRUST & CAPABILITIES" in str(card_trust.renderable)
            assert "OPERATIONAL IMPACT" in str(card_impact.renderable)

            # Verify symmetrical spacing around connector text
            header = app.query("#pane-context .result-header").first()
            meta = app.query_one("#investigation-workspace-meta")
            grid = app.query("#pane-context .metadata-grid").first()
            gap_above = meta.region.y - (header.region.y + header.region.height)
            gap_below = grid.region.y - (meta.region.y + meta.region.height)
            assert gap_above == gap_below == 1

            # Trigger validation via key 'u'
            await pilot.press("u")
            await pilot.pause(0.1)

            # Check database persistence
            val_store = default_validation_store(output)
            assert val_store.is_file()
            latest = get_latest_validation(val_store, "run-val")
            assert latest is not None
            assert latest.status in {"PASS", "WARN"}

            # Verify integrity card reflects status
            assert latest.status in str(card_integrity.renderable)

            # Test clipboard copy of validation summary
            app.action_copy_validation_summary()
            assert "Report Validation Summary" in app._clipboard

    anyio.run(main)


def test_tui_context_stale_detection(tmp_path):
    import json
    from hound.output.report import ensure_outdir
    from hound.pipeline import analyze
    from hound.tui import HoundTui
    from textual.widgets import Static

    log = tmp_path / "pytest_fail.log"
    shutil.copy(FIXTURES / "pytest_fail.log", log)
    output = ensure_outdir(tmp_path / "out")
    run_dir = output / "run-stale"
    analyze(log, run_dir, offline=True)
    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(output), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app._load_run(run_dir)
            await pilot.pause(0.05)
            app._show_workspace("investigation")
            await pilot.press("u")
            await pilot.pause(0.05)

            # Now tamper report.json
            report_file = run_dir / "report.json"
            data = json.loads(report_file.read_text(encoding="utf-8"))
            data["failure"]["summary"] = "Tampered after validation"
            report_file.write_text(json.dumps(data), encoding="utf-8")

            # Refresh context
            app._refresh_current_context()
            await pilot.pause(0.05)

            card_integrity = app.query_one("#context-card-integrity", Static)
            rendered = str(card_integrity.renderable)
            assert "STALE" in rendered

    anyio.run(main)


def test_tui_quality_workspace_cards_and_policy_preview(tmp_path):
    from hound.tui import HoundTui
    from textual.widgets import Static

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.press("y")
            await pilot.pause()

            # Verify the 3 top status cards in QA workspace
            card_hist = app.query_one("#qa-card-history", Static)
            card_gate = app.query_one("#qa-card-gate", Static)
            card_sig = app.query_one("#qa-card-signal", Static)
            assert "TEST HISTORY DATABASE" in str(card_hist.renderable)
            assert "RELEASE QUALITY GATE" in str(card_gate.renderable)
            assert "REGRESSION SIGNAL" in str(card_sig.renderable)

            # Verify active policy preview section
            preview = app.query_one("#qa-policy-preview", Static)
            assert "gate policy:" in str(preview.renderable).lower()

    anyio.run(main)


def test_tui_feedback_modal_blocks_reviewed_on_failing_report(tmp_path):
    import json
    from hound.output.report import ensure_outdir
    from hound.pipeline import analyze
    from hound.tui import FeedbackScreen, HoundTui
    from textual.widgets import Button, Select

    log = tmp_path / "pytest_fail.log"
    shutil.copy(FIXTURES / "pytest_fail.log", log)
    output = ensure_outdir(tmp_path / "out")
    run_dir = output / "run-fail"
    analyze(log, run_dir, offline=True)

    # Invalidate the report by injecting a trust policy violation
    report_file = run_dir / "report.json"
    doc = json.loads(report_file.read_text(encoding="utf-8"))
    doc["meta"]["trust"] = {
        "source_class": "fork_pr",
        "source_context": False,
        "enrichment": False,
        "llm": True,  # Violation: fork_pr cannot enable LLM
        "delivery": False,
    }
    report_file.write_text(json.dumps(doc), encoding="utf-8")

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(output), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app._load_run(run_dir)
            await pilot.pause(0.05)
            app.action_open_feedback()
            await pilot.pause()

            assert isinstance(app.screen, FeedbackScreen)
            # Select 'reviewed'
            app.screen.query_one("#feedback-review-status", Select).value = "reviewed"
            await pilot.pause()

            # Try to save
            app.screen.query_one("#feedback-save", Button).press()
            await pilot.pause(0.1)

            # Modal must NOT dismiss because saving 'reviewed' on failing report is blocked
            assert isinstance(app.screen, FeedbackScreen)

    anyio.run(main)



def test_tui_back_navigation_and_shortcuts(tmp_path):
    """Verify Back button, keyboard shortcuts, and unfocus behavior across views and modals."""
    from hound.tui import HoundTui
    from textual.widgets import Button, Static

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.pause()
            back_btn = app.query_one("#back-button", Button)
            assert str(back_btn.label).strip() == "←"
            shortcutbar = app.query_one("#shortcutbar", Static)

            # 1. Initial Home state
            assert app._current_view_state() == ("home", None)
            assert not app.has_class("has-back-nav")
            assert back_btn.disabled is True

            # 2. Navigate to Artifacts workspace
            await pilot.press("f")
            await pilot.pause()
            assert app._current_view_state() == ("workspace", "artifacts")
            assert app.has_class("has-back-nav")
            assert back_btn.disabled is False
            assert "esc" in str(shortcutbar.renderable) and "back" in str(shortcutbar.renderable)

            # 3. Navigate to Results workspace
            await pilot.press("l")
            await pilot.pause()
            assert app._current_view_state() == ("workspace", "results")

            # 4. Click Back button -> returns to Artifacts workspace
            await pilot.click("#back-button")
            await pilot.pause()
            assert app._current_view_state() == ("workspace", "artifacts")

            # 5. 'k' only clears focus and never changes the current view.
            await pilot.press("k")
            await pilot.pause()
            assert app._current_view_state() == ("workspace", "artifacts")
            assert app.focused is None

            # Escape performs Back navigation.
            await pilot.press("escape")
            await pilot.pause()
            assert app._current_view_state() == ("home", None)
            assert not app.has_class("has-back-nav")
            assert back_btn.disabled is True

            # 6. Navigate to QA workspace and press 'B' -> returns to Home
            await pilot.press("y")
            await pilot.pause()
            assert app._current_view_state() == ("workspace", "qa")
            await pilot.press("B")
            await pilot.pause()
            assert app._current_view_state() == ("home", None)
            assert not app.has_class("has-back-nav")
            assert back_btn.disabled is True

            # 7. 'k' unfocuses, while Escape always navigates back.
            await pilot.press("f")
            await pilot.pause()
            app.query_one("#log-filter").focus()
            await pilot.pause()
            assert app.focused is not None
            await pilot.press("k")
            await pilot.pause()
            assert app.focused is None
            assert app._current_view_state() == ("workspace", "artifacts")
            await pilot.press("escape")
            await pilot.pause()
            assert app._current_view_state() == ("home", None)

            # 8. Results tab view back navigation
            app._show_results("pane-report")
            await pilot.pause()
            assert app._current_view_state() == ("results_tab", "pane-report")
            assert app.has_class("has-back-nav")
            assert back_btn.disabled is False
            await pilot.click("#back-button")
            await pilot.pause()
            assert app._current_view_state() == ("home", None)

            # 9. Modal screen dismissal via action_back / escape
            await pilot.press("?")
            await pilot.pause()
            assert len(app.screen_stack) > 1
            help_text = str(app.screen.query_one("#help-dialog Static", Static).renderable)
            for expected in (
                "Artifacts",
                "Quality & gates",
                "Current run overview",
                "Overview · Report · Ticket · Raw log · Context",
                "space",
                "Validate Context",
            ):
                assert expected in help_text
            await pilot.press("escape")
            await pilot.pause()
            assert len(app.screen_stack) == 1

    anyio.run(main)


def test_tui_workflow_status_placement_and_stop_shortcut(tmp_path):
    from hound.tui import HoundTui
    from textual.widgets import Static

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.pause()

            # 1. Verify engine and workflow status share one sidebar summary box.
            sidebar = app.query_one("#sidebar")
            summary = app.query_one("#engine-status")
            assert summary in sidebar.children
            assert [child.id for child in summary.children] == ["engine-summary", "workflow-status"]
            status_text = str(app.query_one("#workflow-status", Static).renderable)
            assert "STATUS" in status_text
            assert "READY" in status_text

            # 2. Verify home keyboard guide includes stop analyze shortcut
            home_kb = str(app.query_one("#home-keyboard", Static).renderable)
            assert "stop analyze" in home_kb
            assert "q" in home_kb
            assert "exit" in home_kb
            assert home_kb.count("\n") == 5

            # 3. Verify shortcut bar updates dynamically when analyzing
            shortcutbar = app.query_one("#shortcutbar", Static)
            assert "analyze" in str(shortcutbar.renderable)
            assert "stop analyze" not in str(shortcutbar.renderable)

            app._analyzing = True
            app._set_analysis_enabled()
            await pilot.pause()
            assert "stop analyze" in str(shortcutbar.renderable)

            # 4. Pressing x during analysis triggers stop request
            assert not app._stop_requested.is_set()
            await pilot.press("x")
            await pilot.pause()
            assert app._stop_requested.is_set()

            # 4b. Verify ctrl+x also triggers stop
            app._stop_requested.clear()
            await pilot.press("ctrl+x")
            await pilot.pause()
            assert app._stop_requested.is_set()

            # 5. Reset and verify shortcut bar returns to normal when idle
            app._analyzing = False
            app._set_analysis_enabled()
            await pilot.pause()
            assert "stop analyze" not in str(shortcutbar.renderable)
            assert "analyze" in str(shortcutbar.renderable)

    anyio.run(main)
