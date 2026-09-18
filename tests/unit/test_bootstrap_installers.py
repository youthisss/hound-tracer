from __future__ import annotations

import subprocess
import shutil
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_posix_installer_uses_uv_tool_and_verifies_hound() -> None:
    script = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert '"$UV" tool install --force "$SPEC"' in script
    assert 'HOUND="$BIN_DIR/hound"' in script
    assert '"$HOUND" --version' in script
    assert "curl -LsSf https://astral.sh/uv/install.sh | sh" in script


def test_posix_installer_has_valid_shell_syntax() -> None:
    shell = shutil.which("sh")
    if shell is None:
        pytest.skip("POSIX shell is unavailable on this runner")

    result = subprocess.run(
        [shell, "-n", str(ROOT / "install.sh")],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_windows_installer_blocks_locked_hound_before_installing() -> None:
    script = (ROOT / "install.ps1").read_text(encoding="utf-8")
    process_check = script.index("Get-CimInstance Win32_Process")
    install = script.index("tool install --force")

    assert process_check < install
    assert "Close the listed process or its host application" in script
    assert 'Join-Path $binDir "hound.exe"' in script
    assert "& $houndPath --version" in script
