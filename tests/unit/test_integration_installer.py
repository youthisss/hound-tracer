import json
from pathlib import Path

import yaml

from hound import integrations
from hound.cli import main


def _use_home(monkeypatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(integrations, "_home", lambda: home)
    monkeypatch.setattr(integrations, "_manifest_path", lambda: home / ".config" / "hound-tracer" / "integrations.json")
    return home


def test_opencode_install_preserves_existing_servers_and_creates_backup(tmp_path, monkeypatch):
    home = _use_home(monkeypatch, tmp_path)
    config = home / ".config" / "opencode" / "opencode.jsonc"
    config.parent.mkdir(parents=True)
    config.write_text(
        '{\n  // retained setting\n  "model": "example/model",\n  "mcp": {"servers": {"other": {"type": "remote", "url": "https://example.test",},},},\n}\n',
        encoding="utf-8",
    )

    results = integrations.install_integrations(["opencode"], scope="global", root=tmp_path)

    assert results[0].installed is True
    installed = json.loads(config.read_text(encoding="utf-8"))
    assert installed["model"] == "example/model"
    assert installed["mcp"]["servers"]["other"]["url"] == "https://example.test"
    assert installed["mcp"]["servers"]["hound"]["command"] == ["hound-mcp"]
    assert (home / ".config" / "opencode" / "skills" / "hound-tracer" / "SKILL.md").is_file()
    assert config.with_suffix(".jsonc.hound.bak").is_file()


def test_opencode_install_is_idempotent(tmp_path, monkeypatch):
    _use_home(monkeypatch, tmp_path)
    integrations.install_integrations(["opencode"], scope="global", root=tmp_path)

    results = integrations.install_integrations(["opencode"], scope="global", root=tmp_path)

    assert results[0].changed == []


def test_project_dry_run_does_not_write(tmp_path, monkeypatch):
    _use_home(monkeypatch, tmp_path)

    results = integrations.install_integrations(["opencode"], scope="project", root=tmp_path, dry_run=True)

    assert results[0].changed
    assert not (tmp_path / ".opencode").exists()


def test_integrations_cli_requires_target(capsys):
    assert main(["integrations", "install", "--yes"]) == 2
    assert "select a harness" in capsys.readouterr().err


def test_integrations_detect_json(monkeypatch, capsys):
    monkeypatch.setattr(integrations, "detect_harnesses", lambda: {name: name == "opencode" for name in integrations.SUPPORTED_HARNESSES})

    assert main(["integrations", "detect", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["opencode"] is True


def test_first_run_decline_is_not_repeated(tmp_path, monkeypatch, capsys):
    home = _use_home(monkeypatch, tmp_path)
    monkeypatch.setattr(integrations, "detect_harnesses", lambda: {name: name == "opencode" for name in integrations.SUPPORTED_HARNESSES})
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")

    integrations.first_run_offer()

    manifest = home / ".config" / "hound-tracer" / "integrations.json"
    assert json.loads(manifest.read_text(encoding="utf-8"))["skipped"] is True
    assert "Skipped" in capsys.readouterr().out


def test_jsonc_parser_accepts_trailing_commas():
    assert integrations._strip_jsonc('{"commands": {"test": true,},}') == '{"commands": {"test": true}}'


def test_all_harnesses_receive_mcp_configuration(tmp_path, monkeypatch):
    home = _use_home(monkeypatch, tmp_path)

    results = integrations.install_integrations(
        ["claude", "codex", "cursor", "hermes", "antigravity"],
        scope="global",
        root=tmp_path,
    )

    assert all(result.installed for result in results)
    assert json.loads((home / ".claude.json").read_text(encoding="utf-8"))["mcpServers"]["hound"]["command"] == "hound-mcp"
    assert '[mcp_servers.hound]' in (home / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert yaml.safe_load((home / ".hermes" / "config.yaml").read_text(encoding="utf-8"))["mcp_servers"]["hound"]["command"] == "hound-mcp"
    assert json.loads((home / ".cursor" / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]["hound"]["command"] == "hound-mcp"
    antigravity = home / ".gemini" / "antigravity" / "mcp_config.json"
    assert json.loads(antigravity.read_text(encoding="utf-8"))["mcpServers"]["hound"]["command"] == "hound-mcp"
    assert (home / ".claude" / "plugins" / "hound" / "plugin.json").is_file()


def test_uninstall_integrations_preserves_unrelated_configuration(tmp_path, monkeypatch):
    home = _use_home(monkeypatch, tmp_path)
    integrations.install_integrations(["opencode", "claude", "codex", "hermes"], scope="global", root=tmp_path)

    opencode = home / ".config" / "opencode" / "opencode.jsonc"
    payload = json.loads(opencode.read_text(encoding="utf-8"))
    payload["model"] = "example/model"
    payload["mcp"]["servers"]["other"] = {"type": "remote", "url": "https://example.test"}
    opencode.write_text(json.dumps(payload), encoding="utf-8")

    results = integrations.uninstall_integrations(
        ["opencode", "claude", "codex", "hermes"], scope="global", root=tmp_path
    )

    assert all(result.installed for result in results)
    remaining = json.loads(opencode.read_text(encoding="utf-8"))
    assert remaining["model"] == "example/model"
    assert set(remaining["mcp"]["servers"]) == {"other"}
    assert "hound-analyze" not in remaining["commands"]
    assert not (home / ".config" / "opencode" / "skills" / "hound-tracer").exists()
    assert "hound" not in json.loads((home / ".claude.json").read_text(encoding="utf-8"))["mcpServers"]
    assert "[mcp_servers.hound]" not in (home / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert "hound" not in yaml.safe_load((home / ".hermes" / "config.yaml").read_text(encoding="utf-8"))["mcp_servers"]


def test_integrations_uninstall_dry_run_keeps_files(tmp_path, monkeypatch):
    home = _use_home(monkeypatch, tmp_path)
    integrations.install_integrations(["opencode"], scope="global", root=tmp_path)

    results = integrations.uninstall_integrations(["opencode"], scope="global", root=tmp_path, dry_run=True)

    assert results[0].changed
    assert (home / ".config" / "opencode" / "skills" / "hound-tracer").exists()
    assert "hound" in json.loads((home / ".config" / "opencode" / "opencode.jsonc").read_text(encoding="utf-8"))["mcp"]["servers"]


def test_uninstall_cli_dry_run_does_not_invoke_package_manager(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".hound").mkdir()
    (tmp_path / ".hound.yml").write_text("redact: true\n", encoding="utf-8")
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not run")))

    assert main(["uninstall", "--package-manager", "pipx", "--purge-project", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "would remove" in output
    assert "pipx uninstall hound-tracer" in output
    assert (tmp_path / ".hound").exists()


def test_uninstall_cli_runs_selected_package_manager(monkeypatch):
    calls = []
    monkeypatch.setattr("subprocess.run", lambda command, check: calls.append((command, check)) or type("Result", (), {"returncode": 0})())

    assert main(["uninstall", "--package-manager", "uv", "--yes"]) == 0
    assert calls == [(["uv", "tool", "uninstall", "hound-tracer"], False)]
