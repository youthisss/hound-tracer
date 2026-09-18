"""Interactive first-run and interface launcher for bare ``hound``."""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from hound import BRAND_NAME, __version__
from hound.presentation import brand_header, console

CHOICES = (
    ("Terminal UI", "Inspect artifacts, runs, results, and quality."),
    ("Command Line", "Enter Hound commands in a persistent Rich session."),
    ("HTTP API Server", "Accept analysis requests on http://127.0.0.1:8123."),
    ("Exit", "Return to the shell without starting Hound."),
)


def _read_key() -> str:
    if os.name == "nt":
        import msvcrt

        getwch = getattr(msvcrt, "getwch")
        key = getwch()
        if key in {"\x00", "\xe0"}:
            return {"H": "up", "P": "down"}.get(getwch(), "")
        return {"\r": "enter", "\x1b": "escape", "\x03": "escape"}.get(key, key)
    import termios  # type: ignore[import-not-found]
    import tty  # type: ignore[import-not-found]

    fd = sys.stdin.fileno()
    previous = termios.tcgetattr(fd)  # type: ignore[attr-defined]
    try:
        tty.setraw(fd)  # type: ignore[attr-defined]
        key = sys.stdin.read(1)
        if key == "\x1b":
            sequence = sys.stdin.read(2)
            return {"[A": "up", "[B": "down"}.get(sequence, "escape")
        return {"\r": "enter", "\n": "enter", "\x03": "escape"}.get(key, key)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, previous)  # type: ignore[attr-defined]


def _launcher_width(terminal_width: int) -> int:
    return max(38, min(96, terminal_width - 2))


def _launcher_view(selected: int, terminal_width: int = 98) -> Panel:
    width = _launcher_width(terminal_width)
    if width >= 60:
        header = brand_header(__version__)
    else:
        header = Text()
        header.append(BRAND_NAME.upper(), style="bold white")
        header.append(f"  v{__version__}\n", style="dim white")
        header.append("Following the evidence", style="dim white")

    menu = Table.grid(padding=(0, 2), expand=True)
    menu.add_column(width=2, no_wrap=True)
    menu.add_column(width=18, no_wrap=True)
    menu.add_column(overflow="fold")
    for index, (label, detail) in enumerate(CHOICES):
        active = index == selected
        marker = Text("›" if active else "", style="bold white")
        name = Text(label, style="reverse bold" if active else "bold white")
        description = Text(detail, style="white" if active else "dim white")
        menu.add_row(marker, name, description)
        if index < len(CHOICES) - 1:
            menu.add_row("", "", "")
    footer = Text("↑/↓ Move    Enter Select    Esc Exit", style="dim white")
    return Panel(
        Group(header, Text("Choose how you want to run Hound\n", style="bold white"), menu, Text(""), footer),
        border_style="white",
        width=width,
        padding=(1, 2),
    )


def choose_interface(*, read_key: Callable[[], str] = _read_key) -> str:
    selected = 0
    output = console()
    while True:
        output.clear()
        output.print(_launcher_view(selected, getattr(output, "width", 98)))
        key = read_key()
        if key == "up":
            selected = (selected - 1) % len(CHOICES)
        elif key == "down":
            selected = (selected + 1) % len(CHOICES)
        elif key == "enter":
            return ("console", "cli", "serve", "exit")[selected]
        elif key == "escape":
            return "exit"


def launch(
    parser,
    *,
    dispatch: Callable[[argparse.Namespace, argparse.ArgumentParser], int],
    run_tui: Callable[[argparse.Namespace], int],
    run_server: Callable[[argparse.Namespace], int],
) -> int:
    while True:
        selection = choose_interface()
        console().clear()
        if selection == "exit":
            return 0
        args = parser.parse_args([selection])
        if selection == "console":
            args.return_to_launcher = True
            code = run_tui(args)
            if code:
                return code
            continue
        if selection == "cli":
            args.return_to_launcher = True
            code = dispatch(args, parser)
            if code:
                return code
            continue
        return run_server(args)
