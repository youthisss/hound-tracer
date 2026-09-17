from __future__ import annotations

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_json_harness_examples_are_valid() -> None:
    paths = [
        ROOT / "integrations" / "opencode" / "opencode.jsonc",
        ROOT / "integrations" / "claude-code" / ".mcp.json",
        ROOT / "integrations" / "cursor" / "mcp.json",
        ROOT / "integrations" / "antigravity" / "mcp_config.example.json",
    ]
    for path in paths:
        assert isinstance(json.loads(path.read_text(encoding="utf-8")), dict), path


def test_codex_example_contains_hound_mcp_command() -> None:
    path = ROOT / "integrations" / "codex" / "config.toml"
    content = path.read_text(encoding="utf-8")
    assert "[mcp_servers.hound]" in content
    assert 'command = "hound-mcp"' in content


def test_hermes_example_is_valid_yaml() -> None:
    path = ROOT / "integrations" / "hermes" / "config.example.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert config["mcp_servers"]["hound"]["command"] == "hound-mcp"


def test_reference_plugin_commands_exist() -> None:
    path = ROOT / "plugins" / "hound" / "plugin.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for command in manifest["commands"]:
        assert (path.parent / command["file"]).is_file(), command["name"]


def test_packaged_integration_assets_match_reference() -> None:
    packaged = ROOT / "src" / "hound" / "integration_assets"
    for folder in ("skills", "plugins"):
        for target in (packaged / folder).rglob("*"):
            if target.is_file() and target.suffix in {".md", ".json", ".py"}:
                source = ROOT / target.relative_to(packaged)
                assert target.read_text(encoding="utf-8") == source.read_text(encoding="utf-8"), source
