"""Post-execution hook: intercepts test/build failures and suggests running Hound Tracer."""
from __future__ import annotations

import os
import json
from pathlib import Path
import shlex
import sys
from typing import Any

DIRECT_RUNNERS = {"pytest", "jest", "vitest", "ctest", "cargo-test"}
SUBCOMMAND_RUNNERS = {"cargo", "go", "dotnet", "npm", "yarn", "pnpm", "bun"}
WRAPPERS = {"uv", "poetry", "pipenv", "npx"}


def _executable(token: str) -> str:
    name = Path(token.strip("\"'")).name.lower()
    return name[:-4] if name.endswith(".exe") else name


def _is_test_command(command: str) -> bool:
    try:
        tokens = shlex.split(command, posix=os.name != "nt")
    except ValueError:
        return False
    if not tokens:
        return False

    while tokens and "=" in tokens[0] and not tokens[0].startswith(("./", ".\\")):
        tokens.pop(0)
    if not tokens:
        return False

    first_token = _executable(tokens[0])
    if first_token == "env":
        return _is_test_command(" ".join(tokens[1:]))
    if first_token in {"uv", "poetry", "pipenv"} and len(tokens) > 1 and tokens[1] == "run":
        return _is_test_command(" ".join(tokens[2:]))
    if first_token == "npx":
        return _is_test_command(" ".join(tokens[1:]))
    if first_token in {"pnpm", "yarn", "npm"} and len(tokens) > 1 and tokens[1] == "exec":
        return _is_test_command(" ".join(tokens[2:]))
    if first_token in {"pnpm", "yarn", "npm"} and len(tokens) > 1 and tokens[1] == "run":
        return any(part.lower().startswith(("test", "build")) for part in tokens[2:3])

    if first_token in DIRECT_RUNNERS:
        return True

    if first_token in SUBCOMMAND_RUNNERS:
        return any(tok.lower() in {"test", "build"} for tok in tokens[1:3])

    if first_token == "mvn":
        return any(tok.lower() in {"test", "verify", "package"} for tok in tokens[1:])

    if first_token in {"gradle", "gradlew", "gradlew.bat", "make"}:
        return any(tok.lower() in {"test", "check", "build"} for tok in tokens[1:])

    if first_token in {"python", "python3", "py"} and len(tokens) >= 3 and tokens[1] == "-m":
        return tokens[2].lower() in {"pytest", "unittest"}

    return False


def on_post_execution(context: dict[str, Any]) -> dict[str, Any] | None:
    """Invoked by coding agent harnesses after a terminal command finishes."""
    command = context.get("command", "")
    exit_code = context.get("exit_code", 0)
    if not isinstance(command, str) or not isinstance(exit_code, int) or isinstance(exit_code, bool):
        return None

    if exit_code != 0 and _is_test_command(command):
        suggestion = (
            f"[Hound Tracer] Test/build command exited with code {exit_code}.\n"
            "Tip: You can use `/hound:analyze` or `hound analyze <log> --offline` "
            "to extract root cause, scrubbed stacktraces, and fix recommendations without token waste."
        )
        return {
            "intercepted": True,
            "suggestion": suggestion,
            "action": "recommend_hound_analysis",
        }

    return None


if __name__ == "__main__":
    try:
        context = json.load(sys.stdin)
    except (ValueError, OSError):
        context = {}
    result = on_post_execution(context) if isinstance(context, dict) else None
    if result:
        print(json.dumps(result))
