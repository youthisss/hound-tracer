from __future__ import annotations

import pytest

from hound import __version__
from hound.cli import build_parser, main
from hound.config import load_config


def test_package_metadata_version_matches_init():
    # hatch dynamic version resolves hound.__version__
    assert __version__ == "0.7.0"


def test_canonical_command_names_and_legacy_aliases(monkeypatch):
    parser = build_parser()
    help_text = parser.format_help()
    assert all(name in help_text for name in ("console", "serve", "providers", "runs", "insights"))
    assert all(name not in help_text for name in ("tui", "server", "list-providers", "list-runs"))

    args_insights = parser.parse_args(["insights", "tests", "--output-dir", "out"])
    assert args_insights.command == "insights"

    args_gate = parser.parse_args([
        "gate", "tests/fixtures/pytest_fail.log",
        "--baseline-ref", "main",
        "--repo-dir", ".",
        "--policy", "tests/fixtures/pytest_fail.log",
    ])
    assert args_gate.qa_command == "gate"
    assert args_gate.baseline == "main"
    assert args_gate.repo == "."

    args_console = parser.parse_args(["console", "--output-dir", "out"])
    assert args_console.command == "console"

    args_serve = parser.parse_args(["serve", "--output-dir", "server-out"])
    assert args_serve.command == "serve"

    args_providers = parser.parse_args(["providers", "--json"])
    assert args_providers.command == "providers"

    args_runs = parser.parse_args(["runs", "--output-dir", "out", "--json"])
    assert args_runs.command == "runs"

    legacy_options = parser.parse_args([
        "analyze", "logs", "--out", "out", "--repo", "repo", "--no-redact",
    ])
    assert legacy_options.out == "out"
    assert legacy_options.repo == "repo"
    assert legacy_options.no_redact is True

    legacy_commands = parser.parse_args(["qa", "history", "suite", "test", "--store", "history.db", "--days", "7"])
    assert legacy_commands.command == "insights"
    assert legacy_commands.store == "history.db"
    assert legacy_commands.days == 7
    assert parser.parse_args(["tui"]).command == "console"
    assert parser.parse_args(["server"]).command == "serve"
    assert parser.parse_args(["list-providers"]).command == "providers"
    assert parser.parse_args(["list-runs"]).command == "runs"
    monkeypatch.setattr("sys.argv", ["hound", "qa", "tests"])
    assert parser.parse_args().command == "insights"

    # Legacy spellings must not rewrite positional values after the command.
    assert parser.parse_args(["analyze", "qa"]).log_directory == "qa"
    assert parser.parse_args(["insights", "history", "qa", "test"]).suite == "qa"
    assert parser.parse_args(["log", "--", "echo", "--out"]).command_args == ["--", "echo", "--out"]


def test_config_validation_detects_unknown_keys(tmp_path, capsys):
    cfg = tmp_path / "bad.yml"
    cfg.write_text("llm:\n  providr: openai\n", encoding="utf-8")

    # default load_config warns with suggestion
    load_config(config_path=str(cfg), offline=True)
    assert "unknown config key llm.providr; did you mean llm.provider?" in capsys.readouterr().err

    # strict mode fails
    with pytest.raises(ValueError, match="unknown config key"):
        load_config(config_path=str(cfg), offline=True, strict=True)

    # CLI validate strict
    assert main(["config", "validate", "--config", str(cfg)]) == 2
    err = capsys.readouterr().err
    assert "error: configuration:" in err

    # CLI validate warn-only
    assert main(["config", "validate", "--config", str(cfg), "--warn-only"]) == 0


def test_allow_unredacted_emits_warning(tmp_path, capsys):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "clean.log").write_text("job finished", encoding="utf-8")
    assert main(["analyze", str(logs), "--offline", "--allow-unredacted", "--output-dir", str(tmp_path / "out")]) == 0
    assert "warning: unredacted mode" in capsys.readouterr().err


def test_hound_env_variable_canonical_and_deprecated_warning(monkeypatch, capsys):
    monkeypatch.setenv("TH_MODEL", "legacy-model")
    cfg = load_config(offline=True)
    assert cfg.model == "legacy-model"
    assert "TH_MODEL is deprecated; use HOUND_MODEL" in capsys.readouterr().err

    monkeypatch.setenv("HOUND_MODEL", "canonical-model")
    cfg2 = load_config(offline=True)
    assert cfg2.model == "canonical-model"
