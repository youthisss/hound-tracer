"""TTY-aware Rich presentation shared by Hound's human-facing CLI."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Iterable

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from hound import BRAND_NAME

DOG_MARK = (
    "  ▄██ ████████ ██▄  ",
    "▄██▀▄██████████▄▀██▄",
    "███ ██ ██████ ██ ███",
    "███ █████▀▀█████ ███",
    " ▀  █████▄▄█████  ▀ ",
    "     ▀▀▀▀▀▀▀▀▀▀     ",
)
DOG_MARK_STYLE = "not bold #ffffff on #0a0a0a"


def rich_enabled(stream=None) -> bool:
    stream = stream or sys.stdout
    return bool(
        getattr(stream, "isatty", lambda: False)()
        and os.environ.get("NO_COLOR") is None
        and os.environ.get("TERM", "").lower() != "dumb"
    )


def console(*, stderr: bool = False) -> Console:
    stream = sys.stderr if stderr else sys.stdout
    return Console(file=stream, no_color=not rich_enabled(stream), highlight=False, soft_wrap=False)


def brand_header(version: str, subtitle: str = "Following the evidence") -> Text:
    text = Text()
    lines = list(DOG_MARK)
    for index, line in enumerate(lines):
        text.append(line, style=DOG_MARK_STYLE)
        if index == 1:
            text.append(f"   {BRAND_NAME.upper()}  v{version}", style="bold white")
        elif index == 2:
            text.append(f"   {subtitle}", style="dim white")
        text.append("\n")
    return text


def show_panel(title: str, rows: Iterable[tuple[str, object]], *, subtitle: str | None = None) -> None:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold white", no_wrap=True)
    table.add_column(style="white", overflow="fold")
    for label, value in rows:
        table.add_row(label, str(value))
    console().print(Panel(table, title=title, subtitle=subtitle, border_style="white", expand=False))


def show_table(title: str, columns: list[str], rows: Iterable[Iterable[object]]) -> None:
    table = Table(title=title, border_style="white", header_style="bold white", show_lines=False)
    for column in columns:
        table.add_column(column)
    for row in rows:
        table.add_row(*(str(value) for value in row))
    console().print(table)


class TaskMessage:
    """Live task details for long-running commands in the interactive CLI."""

    def __init__(self, title: str, rows: Iterable[tuple[str, object]], message: str, *, enabled: bool) -> None:
        self.title = title
        self.rows = [(label, str(value)) for label, value in rows]
        self.message = message
        self.enabled = enabled and rich_enabled(sys.stdout)
        self.started = 0.0
        self._spinner = Spinner("dots", style="bold white")
        self._live: Live | None = None

    def _render(self) -> Panel:
        details = Table.grid(padding=(0, 2))
        details.add_column(style="bold white", no_wrap=True)
        details.add_column(style="white", overflow="fold")
        for label, value in self.rows:
            details.add_row(label, value)
        elapsed = max(0.0, time.monotonic() - self.started)
        activity = Table.grid(padding=(0, 1))
        activity.add_column(width=2)
        activity.add_column(style="white", overflow="fold")
        activity.add_column(style="dim white", justify="right", no_wrap=True)
        activity.add_row(self._spinner, self.message, f"{elapsed:,.1f}s")
        return Panel(
            Group(details, Text(""), activity),
            title=self.title,
            subtitle="IN PROGRESS",
            border_style="white",
            width=max(40, min(96, console().width - 2)),
            padding=(1, 2),
        )

    def __rich__(self) -> Panel:
        return self._render()

    def __enter__(self) -> "TaskMessage":
        if self.enabled:
            self.started = time.monotonic()
            self._live = Live(self, console=console(), refresh_per_second=10, transient=True)
            self._live.start()
        return self

    def update(self, message: str) -> None:
        self.message = message
        if self._live is not None:
            self._live.refresh()

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._live is not None:
            self._live.stop()


def show_error(message: str, *, next_step: str | None = None) -> None:
    if not rich_enabled(sys.stderr):
        print(f"error: {message}" + (f" Next action: {next_step}." if next_step else ""), file=sys.stderr)
        return
    body = Text(message, style="white")
    if next_step:
        body.append("\n\nNext step\n", style="bold white")
        body.append(next_step, style="white")
    console(stderr=True).print(Panel(body, title="COMMAND FAILED", border_style="red", expand=False))


def path_display(path: str | Path) -> str:
    try:
        return str(Path(path).expanduser().resolve())
    except OSError:
        return str(path)
