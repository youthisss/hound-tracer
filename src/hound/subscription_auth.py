"""Explicitly gated adapters for provider subscription sessions via official CLIs."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TypedDict

from platformdirs import user_config_path

from hound.fsio import atomic_write

NOTICE = (
    "This provider uses a subscription/OAuth session not officially licensed for "
    "proxy/router use. Account may be restricted or banned. Use at your own risk."
)

class ProviderDefinition(TypedDict):
    executable: str
    login: list[str]


PROVIDERS: dict[str, ProviderDefinition] = {
    "openai-oauth": {"executable": "codex", "login": ["codex", "login"]},
    "claude-oauth": {"executable": "claude", "login": ["claude", "auth", "login"]},
    "gemini-oauth": {"executable": "gemini", "login": ["gemini"]},
}
CONSENT_PATH = user_config_path("hound") / "subscription-auth.json"


def accept_risk(provider: str, path: Path | None = None) -> None:
    path = path or CONSENT_PATH
    if provider not in PROVIDERS:
        raise ValueError(f"{provider!r} is not a subscription provider")
    accepted: list[str] = []
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("accepted"), list):
                accepted = [item for item in loaded["accepted"] if isinstance(item, str)]
        except (OSError, ValueError):
            pass
    data = {"version": 1, "accepted": sorted({*accepted, provider})}
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, json.dumps(data, indent=2))


def risk_accepted(provider: str, path: Path | None = None) -> bool:
    path = path or CONSENT_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return provider in data.get("accepted", [])
    except (OSError, ValueError, AttributeError):
        return False


def login(provider: str) -> int:
    definition = PROVIDERS.get(provider)
    if definition is None:
        raise ValueError(f"{provider!r} is not a subscription provider")
    if not shutil.which(definition["executable"]):
        raise RuntimeError(f"{definition['executable']} CLI is not installed or not on PATH")
    return subprocess.run(definition["login"], check=False).returncode


def invoke(provider: str, model: str, prompt: str, schema: dict, timeout: float) -> str:
    definition = PROVIDERS.get(provider)
    if definition is None:
        raise ValueError(f"{provider!r} is not a subscription provider")
    if not risk_accepted(provider):
        raise RuntimeError(f"risk notice not accepted; run: hound auth login {provider} --accept-risk")
    if not shutil.which(definition["executable"]):
        raise RuntimeError(f"{definition['executable']} CLI is not installed or not on PATH")

    full_prompt = "Return only JSON matching the supplied schema.\n\n" + prompt
    with tempfile.TemporaryDirectory(prefix="hound-auth-") as directory:
        root = Path(directory)
        schema_path = root / "schema.json"
        output_path = root / "result.json"
        schema_path.write_text(json.dumps(schema), encoding="utf-8")
        if provider == "openai-oauth":
            command = [
                "codex", "exec", "--ephemeral", "--sandbox", "read-only",
                "--ignore-rules", "--skip-git-repo-check", "--output-schema", str(schema_path),
                "--output-last-message", str(output_path),
            ]
            if model != "auto":
                command.extend(["--model", model])
            command.append("-")
        elif provider == "claude-oauth":
            command = [
                "claude", "--print", "--safe-mode", "--no-session-persistence",
                "--tools", "", "--output-format", "text", "--json-schema", json.dumps(schema),
            ]
            if model != "auto":
                command.extend(["--model", model])
            command.append(full_prompt)
        else:
            command = ["gemini", "--output-format", "json", "--allowed-tools", ""]
            if model != "auto":
                command.extend(["--model", model])
            command.append(full_prompt)

        completed = subprocess.run(
            command,
            input=full_prompt if provider == "openai-oauth" else None,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        if completed.returncode:
            message = (completed.stderr or completed.stdout or "provider CLI failed").strip()
            raise RuntimeError(message[-1000:])
        if provider == "openai-oauth":
            return output_path.read_text(encoding="utf-8")
        if provider == "gemini-oauth":
            envelope = json.loads(completed.stdout)
            return str(envelope.get("response") or envelope.get("result") or completed.stdout)
        return completed.stdout
