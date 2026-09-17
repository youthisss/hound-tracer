from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from importlib.resources import files
from pathlib import Path
import shutil
import sys
from typing import Any

from platformdirs import user_config_path
import yaml


SUPPORTED_HARNESSES = ("opencode", "claude", "codex", "cursor", "hermes", "antigravity")
SUPPORTED_COMPONENTS = frozenset({"skill", "plugin", "mcp"})


@dataclass(frozen=True)
class IntegrationResult:
    harness: str
    detected: bool
    installed: bool
    changed: list[str]
    warnings: list[str]


def _remove_path(path: Path, *, dry_run: bool) -> bool:
    if not path.exists() and not path.is_symlink():
        return False
    if not dry_run:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    return True


def _home() -> Path:
    return Path.home()


def _asset(*parts: str):
    return files("hound").joinpath("integration_assets", *parts)


def _executable_exists(*names: str) -> bool:
    return any(shutil.which(name) for name in names)


def detect_harnesses() -> dict[str, bool]:
    home = _home()
    return {
        "opencode": _executable_exists("opencode") or (home / ".config" / "opencode").exists(),
        "claude": _executable_exists("claude") or (home / ".claude").exists(),
        "codex": _executable_exists("codex") or (home / ".codex").exists(),
        "cursor": _executable_exists("cursor") or (home / ".cursor").exists(),
        "hermes": _executable_exists("hermes") or (home / ".hermes").exists(),
        "antigravity": _executable_exists("antigravity") or (home / ".gemini" / "antigravity").exists(),
    }


def _skill_directory(harness: str, scope: str, root: Path) -> Path:
    if scope == "project":
        folder = ".opencode" if harness == "opencode" else f".{harness}"
        if harness == "antigravity":
            folder = ".agent"
        return root / folder / "skills" / "hound-tracer"
    locations = {
        "opencode": _home() / ".config" / "opencode" / "skills" / "hound-tracer",
        "claude": _home() / ".claude" / "skills" / "hound-tracer",
        "codex": _home() / ".codex" / "skills" / "hound-tracer",
        "cursor": _home() / ".cursor" / "skills" / "hound-tracer",
        "hermes": _home() / ".hermes" / "skills" / "hound-tracer",
        "antigravity": _home() / ".gemini" / "antigravity" / "skills" / "hound-tracer",
    }
    return locations[harness]


def _backup(path: Path) -> Path:
    candidate = path.with_suffix(path.suffix + ".hound.bak")
    counter = 1
    while candidate.exists():
        candidate = path.with_suffix(path.suffix + f".hound.bak.{counter}")
        counter += 1
    shutil.copy2(path, candidate)
    return candidate


def _write_if_changed(path: Path, content: str, *, dry_run: bool) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return True


def _strip_jsonc(text: str) -> str:
    output: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(text):
        char = text[index]
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            output.append(char)
            index += 1
            continue
        if text[index:index + 2] == "//":
            index = text.find("\n", index)
            if index == -1:
                break
            output.append("\n")
            index += 1
            continue
        if text[index:index + 2] == "/*":
            end = text.find("*/", index + 2)
            index = len(text) if end == -1 else end + 2
            continue
        output.append(char)
        index += 1
    return _remove_trailing_commas("".join(output))


def _remove_trailing_commas(text: str) -> str:
    output: list[str] = []
    in_string = False
    escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            output.append(char)
            index += 1
            continue
        if char == ",":
            lookahead = index + 1
            while lookahead < len(text) and text[lookahead].isspace():
                lookahead += 1
            if lookahead < len(text) and text[lookahead] in "}]":
                index += 1
                continue
        output.append(char)
        index += 1
    return "".join(output)


def _load_json_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(_strip_jsonc(path.read_text(encoding="utf-8")))
    if not isinstance(data, dict):
        raise ValueError(f"configuration root must be an object: {path}")
    return data


def _merge_json_config(path: Path, fragment: dict[str, Any], *, dry_run: bool) -> tuple[bool, Path | None]:
    current = _load_json_config(path)
    merged = _deep_merge(current, fragment)
    content = json.dumps(merged, indent=2, ensure_ascii=False) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False, None
    backup = None if dry_run or not path.exists() else _backup(path)
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return True, backup


def _deep_merge(current: dict[str, Any], fragment: dict[str, Any]) -> dict[str, Any]:
    merged = dict(current)
    for key, value in fragment.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def _write_json_config(path: Path, data: dict[str, Any], *, dry_run: bool) -> Path | None:
    backup = None if dry_run or not path.exists() else _backup(path)
    if not dry_run:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return backup


def _mcp_server() -> dict[str, Any]:
    return {
        "hound": {
            "type": "local",
            "command": ["hound-mcp"],
            "cwd": ".",
            "environment": {"PYTHONUNBUFFERED": "1", "HOUND_MCP_ROOTS": "."},
            "codemode": True,
        }
    }


def _install_skill(harness: str, scope: str, root: Path, dry_run: bool) -> list[str]:
    destination = _skill_directory(harness, scope, root) / "SKILL.md"
    content = _asset("skills", "hound-tracer", "SKILL.md").read_text(encoding="utf-8")
    return [str(destination)] if _write_if_changed(destination, content, dry_run=dry_run) else []


def _copy_asset_tree(source: Any, destination: Path, *, dry_run: bool) -> list[str]:
    changed: list[str] = []
    for item in source.iterdir():
        target = destination / item.name
        if item.is_dir():
            changed.extend(_copy_asset_tree(item, target, dry_run=dry_run))
        else:
            content = item.read_bytes()
            if target.exists() and target.read_bytes() == content:
                continue
            changed.append(str(target))
            if not dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
    return changed


def _install_opencode(scope: str, root: Path, dry_run: bool, components: set[str]) -> tuple[list[str], list[str]]:
    changed = _install_skill("opencode", scope, root, dry_run) if "skill" in components else []
    if "mcp" not in components:
        return changed, []
    config = (root / ".opencode" / "opencode.jsonc") if scope == "project" else (_home() / ".config" / "opencode" / "opencode.jsonc")
    fragment = {
        "$schema": "https://opencode.ai/config.json",
        "mcp": {"servers": _mcp_server()},
    }
    did_change, backup = _merge_json_config(config, fragment, dry_run=dry_run)
    if did_change:
        changed.append(str(config))
    warnings = [f"Backup created: {backup}"] if backup else []
    return changed, warnings


def _install_json_mcp(
    harness: str, scope: str, root: Path, dry_run: bool, components: set[str]
) -> tuple[list[str], list[str]]:
    changed = _install_skill(harness, scope, root, dry_run) if "skill" in components else []
    warnings: list[str] = []
    if harness == "claude" and "plugin" in components:
        plugin_dir = (root / ".claude" / "plugins" / "hound") if scope == "project" else (_home() / ".claude" / "plugins" / "hound")
        changed.extend(_copy_asset_tree(_asset("plugins", "hound"), plugin_dir, dry_run=dry_run))
    if "mcp" not in components:
        return changed, warnings
    if harness == "claude":
        config = (root / ".mcp.json") if scope == "project" else (_home() / ".claude.json")
    elif harness == "cursor":
        config = (root / ".cursor" / "mcp.json") if scope == "project" else (_home() / ".cursor" / "mcp.json")
    elif harness == "antigravity":
        config = (root / ".agent" / "mcp_config.json") if scope == "project" else (_home() / ".gemini" / "antigravity" / "mcp_config.json")
    else:
        config = None
    if config is not None:
        server = {"command": "hound-mcp", "args": [], "env": {"HOUND_MCP_ROOTS": "."}}
        fragment = {"mcpServers": {"hound": server}}
        did_change, backup = _merge_json_config(config, fragment, dry_run=dry_run)
        if did_change:
            changed.append(str(config))
        if backup:
            warnings.append(f"Backup created: {backup}")
    elif harness == "codex":
        config = (root / ".codex" / "config.toml") if scope == "project" else (_home() / ".codex" / "config.toml")
        did_change, backup, note = _merge_codex_config(config, dry_run=dry_run)
        if did_change:
            changed.append(str(config))
        if backup:
            warnings.append(f"Backup created: {backup}")
        if note:
            warnings.append(note)
    elif harness == "hermes":
        config = (root / ".hermes" / "config.yaml") if scope == "project" else (_home() / ".hermes" / "config.yaml")
        did_change, backup = _merge_hermes_config(config, dry_run=dry_run)
        if did_change:
            changed.append(str(config))
        if backup:
            warnings.append(f"Backup created: {backup}")
    return changed, warnings


def _merge_codex_config(path: Path, *, dry_run: bool) -> tuple[bool, Path | None, str | None]:
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    if "[mcp_servers.hound]" in content:
        return False, None, None
    block = '\n[mcp_servers.hound]\ncommand = "hound-mcp"\nargs = []\nenv = { PYTHONUNBUFFERED = "1", HOUND_MCP_ROOTS = "." }\n'
    updated = content.rstrip() + block
    backup = None if dry_run or not path.exists() else _backup(path)
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(updated, encoding="utf-8")
    return True, backup, None


def _merge_hermes_config(path: Path, *, dry_run: bool) -> tuple[bool, Path | None]:
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"configuration root must be a mapping: {path}")
    else:
        loaded = {}
    current = loaded.get("mcp_servers")
    servers = dict(current) if isinstance(current, dict) else {}
    desired = {"command": "hound-mcp", "args": [], "env": {"PYTHONUNBUFFERED": "1", "HOUND_MCP_ROOTS": "."}}
    if servers.get("hound") == desired:
        return False, None
    servers["hound"] = desired
    loaded["mcp_servers"] = servers
    backup = None if dry_run or not path.exists() else _backup(path)
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(loaded, sort_keys=False), encoding="utf-8")
    return True, backup


def install_integrations(
    harnesses: list[str], *, scope: str, root: Path, dry_run: bool = False,
    components: set[str] | None = None,
) -> list[IntegrationResult]:
    components = set(SUPPORTED_COMPONENTS if components is None else components)
    unsupported_components = components - SUPPORTED_COMPONENTS
    if unsupported_components:
        raise ValueError(f"unsupported component: {', '.join(sorted(unsupported_components))}")
    detected = detect_harnesses()
    results: list[IntegrationResult] = []
    for harness in harnesses:
        if harness not in SUPPORTED_HARNESSES:
            raise ValueError(f"unsupported harness: {harness}")
        try:
            if harness == "opencode":
                changed, warnings = _install_opencode(scope, root, dry_run, components)
            else:
                changed, warnings = _install_json_mcp(harness, scope, root, dry_run, components)
            results.append(IntegrationResult(harness, detected[harness], not dry_run, changed, warnings))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            results.append(IntegrationResult(harness, detected[harness], False, [], [str(exc)]))
    if not dry_run:
        _write_manifest(results, scope)
    return results


def _json_config_path(harness: str, scope: str, root: Path) -> Path | None:
    if harness == "opencode":
        return (root / ".opencode" / "opencode.jsonc") if scope == "project" else (_home() / ".config" / "opencode" / "opencode.jsonc")
    if harness == "claude":
        return (root / ".mcp.json") if scope == "project" else (_home() / ".claude.json")
    if harness == "cursor":
        return (root / ".cursor" / "mcp.json") if scope == "project" else (_home() / ".cursor" / "mcp.json")
    if harness == "antigravity":
        return (root / ".agent" / "mcp_config.json") if scope == "project" else (_home() / ".gemini" / "antigravity" / "mcp_config.json")
    return None


def _uninstall_json_config(harness: str, scope: str, root: Path, dry_run: bool) -> tuple[list[str], list[str]]:
    path = _json_config_path(harness, scope, root)
    if path is None or not path.exists():
        return [], []
    data = _load_json_config(path)
    changed = False
    warnings: list[str] = []
    if harness == "opencode":
        servers = data.get("mcp", {}).get("servers") if isinstance(data.get("mcp"), dict) else None
        if isinstance(servers, dict) and "hound" in servers:
            if servers["hound"] == _mcp_server()["hound"]:
                del servers["hound"]
                changed = True
            else:
                warnings.append(f"Kept modified Hound MCP entry: {path}")
        commands = data.get("commands")
        if isinstance(commands, dict):
            for name in ("hound-analyze", "hound-update"):
                if name in commands:
                    del commands[name]
                    changed = True
    else:
        servers = data.get("mcpServers")
        expected = {"command": "hound-mcp", "args": [], "env": {"HOUND_MCP_ROOTS": "."}}
        if isinstance(servers, dict) and "hound" in servers:
            if servers["hound"] == expected:
                del servers["hound"]
                changed = True
            else:
                warnings.append(f"Kept modified Hound MCP entry: {path}")
    if changed:
        backup = _write_json_config(path, data, dry_run=dry_run)
        if backup:
            warnings.append(f"Backup created: {backup}")
        return [str(path)], warnings
    return [], warnings


def _uninstall_codex(scope: str, root: Path, dry_run: bool) -> tuple[list[str], list[str]]:
    path = (root / ".codex" / "config.toml") if scope == "project" else (_home() / ".codex" / "config.toml")
    if not path.exists():
        return [], []
    content = path.read_text(encoding="utf-8")
    pattern = re.compile(r"\n?\[mcp_servers\.hound\]\ncommand = \"hound-mcp\"\nargs = \[\]\nenv = \{ PYTHONUNBUFFERED = \"1\", HOUND_MCP_ROOTS = \"\.\" \}\n?")
    updated, count = pattern.subn("\n", content)
    if not count:
        warning = [f"Kept missing or modified Hound MCP block: {path}"] if "[mcp_servers.hound]" in content else []
        return [], warning
    backup = None if dry_run else _backup(path)
    if not dry_run:
        path.write_text(updated.lstrip("\n"), encoding="utf-8")
    return [str(path)], [f"Backup created: {backup}"] if backup else []


def _uninstall_hermes(scope: str, root: Path, dry_run: bool) -> tuple[list[str], list[str]]:
    path = (root / ".hermes" / "config.yaml") if scope == "project" else (_home() / ".hermes" / "config.yaml")
    if not path.exists():
        return [], []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"configuration root must be a mapping: {path}")
    servers = data.get("mcp_servers")
    expected = {"command": "hound-mcp", "args": [], "env": {"PYTHONUNBUFFERED": "1", "HOUND_MCP_ROOTS": "."}}
    if not isinstance(servers, dict) or "hound" not in servers:
        return [], []
    if servers["hound"] != expected:
        return [], [f"Kept modified Hound MCP entry: {path}"]
    del servers["hound"]
    backup = None if dry_run else _backup(path)
    if not dry_run:
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return [str(path)], [f"Backup created: {backup}"] if backup else []


def uninstall_integrations(
    harnesses: list[str], *, scope: str, root: Path, dry_run: bool = False,
    components: set[str] | None = None,
) -> list[IntegrationResult]:
    components = set(SUPPORTED_COMPONENTS if components is None else components)
    unsupported_components = components - SUPPORTED_COMPONENTS
    if unsupported_components:
        raise ValueError(f"unsupported component: {', '.join(sorted(unsupported_components))}")
    detected = detect_harnesses()
    results: list[IntegrationResult] = []
    for harness in harnesses:
        if harness not in SUPPORTED_HARNESSES:
            raise ValueError(f"unsupported harness: {harness}")
        changed: list[str] = []
        warnings: list[str] = []
        try:
            if "skill" in components:
                skill_dir = _skill_directory(harness, scope, root)
                if _remove_path(skill_dir, dry_run=dry_run):
                    changed.append(str(skill_dir))
            if "mcp" not in components:
                config_changed, config_warnings = [], []
            elif harness == "codex":
                config_changed, config_warnings = _uninstall_codex(scope, root, dry_run)
            elif harness == "hermes":
                config_changed, config_warnings = _uninstall_hermes(scope, root, dry_run)
            else:
                config_changed, config_warnings = _uninstall_json_config(harness, scope, root, dry_run)
            changed.extend(config_changed)
            warnings.extend(config_warnings)
            if harness == "claude" and "plugin" in components:
                plugin_dir = (root / ".claude" / "plugins" / "hound") if scope == "project" else (_home() / ".claude" / "plugins" / "hound")
                if _remove_path(plugin_dir, dry_run=dry_run):
                    changed.append(str(plugin_dir))
            results.append(IntegrationResult(harness, detected[harness], not dry_run, changed, warnings))
        except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
            results.append(IntegrationResult(harness, detected[harness], False, changed, warnings + [str(exc)]))
    if not dry_run and components == SUPPORTED_COMPONENTS and _manifest_path().exists():
        _manifest_path().unlink()
    return results


def _manifest_path() -> Path:
    return Path(user_config_path("hound-tracer")) / "integrations.json"


def _write_manifest(results: list[IntegrationResult], scope: str) -> None:
    path = _manifest_path()
    payload = {"scope": scope, "results": [asdict(result) for result in results]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def has_completed_setup() -> bool:
    return _manifest_path().is_file()


def print_results(
    results: list[IntegrationResult], *, as_json: bool = False, dry_run: bool = False, action: str = "install"
) -> int:
    if as_json:
        print(json.dumps([asdict(result) for result in results], indent=2))
    elif sys.stdout.isatty():
        from hound.presentation import show_table

        rows = []
        for result in results:
            success = "REMOVED" if action == "uninstall" else "CONFIGURED"
            status = "PLANNED" if dry_run else (success if result.installed else "FAILED")
            detail = ", ".join(result.changed) or ("; ".join(result.warnings) or "Already configured")
            rows.append((result.harness, "YES" if result.detected else "NO", status, detail))
        show_table("INTEGRATION SETUP", ["Harness", "Detected", "Status", "Changes"], rows)
    else:
        heading = "Planned integration changes" if dry_run else (
            "Integration removal" if action == "uninstall" else "Integration setup"
        )
        print(heading)
        for result in results:
            state = "detected" if result.detected else "not detected"
            print(f"  {result.harness}: {state}")
            for path in result.changed:
                verb = "would remove" if dry_run and action == "uninstall" else (
                    "would write" if dry_run else ("removed" if action == "uninstall" else "wrote")
                )
                print(f"    {verb} {path}")
            if not result.changed and not result.warnings:
                print("    no Hound-owned changes found" if action == "uninstall" else "    already configured")
            for warning in result.warnings:
                print(f"    note: {warning}", file=sys.stderr)
    return 0 if all(result.installed or dry_run for result in results) else 1


def first_run_offer() -> None:
    if has_completed_setup() or os.environ.get("HOUND_SKIP_SETUP") == "1":
        return
    detected = [name for name, present in detect_harnesses().items() if present]
    if not detected:
        return
    from hound import __version__
    from hound.presentation import brand_header, console
    from rich.console import Group
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold white")
    table.add_column(style="white")
    for name in SUPPORTED_HARNESSES:
        table.add_row("FOUND" if name in detected else "SKIP", f"{name}  " + ("Skill + MCP integration" if name in detected else "Not detected"))
    body = Group(
        brand_header(__version__, "First-time setup"),
        Text("Hound can configure detected coding harnesses. Existing configuration is preserved and backed up before changes.\n", style="white"),
        table,
        Text("\nInstall the detected integrations?", style="bold white"),
    )
    console().print(Panel(body, title="WELCOME TO HOUND", border_style="white", width=76))
    try:
        answer = input("Install integrations? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if answer not in {"y", "yes"}:
        path = _manifest_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"skipped": True}, indent=2) + "\n", encoding="utf-8")
        console().print("[dim]Skipped. Run `hound install all --for <harness>` later.[/dim]")
        return
    results = install_integrations(detected, scope="global", root=Path.cwd())
    print_results(results)
