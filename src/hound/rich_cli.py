"""Persistent Rich command shell for Hound subcommands."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import sys
from collections.abc import Callable

from platformdirs import user_state_path
from prompt_toolkit import PromptSession
from prompt_toolkit.application import run_in_terminal
from prompt_toolkit.completion import NestedCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from hound import BRAND_NAME, __version__
from hound.presentation import DOG_MARK, DOG_MARK_STYLE, console

INTERNAL_COMMANDS = {"help", "status", "clear", "history", "exit", "quit"}
INTERRUPTED_EXIT_CODE = 130


def _command_tree(parser: argparse.ArgumentParser) -> dict[str, object]:
    tree: dict[str, object] = {name: None for name in INTERNAL_COMMANDS}
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, child in action.choices.items():
                nested: dict[str, object] = {}
                for child_action in child._actions:
                    if isinstance(child_action, argparse._SubParsersAction):
                        nested.update({key: None for key in child_action.choices})
                tree[name] = nested or None
    return tree


def _session_panel() -> Panel:
    workspace = Path.cwd() / ".hound"
    title = Text()
    title.append(BRAND_NAME.upper(), style="bold white")
    title.append(f"  v{__version__}\n", style="dim white")
    title.append("Command line\n\n", style="bold white")
    info = Table.grid(padding=(0, 2))
    info.add_column(style="bold white", no_wrap=True)
    info.add_column(style="white", overflow="fold")
    info.add_row("Project", str(Path.cwd()))
    info.add_row("Workspace", str(workspace) if workspace.is_dir() else "Not initialized")
    info.add_row("Input", "Hound commands only. Type `help` for usage.")
    layout = Table.grid(padding=(0, 3))
    layout.add_column(no_wrap=True)
    layout.add_column(overflow="fold")
    layout.add_row(Text("\n".join(DOG_MARK), style=DOG_MARK_STYLE), Group(title, info))
    return Panel(layout, border_style="white", width=76, padding=(1, 2))


def _show_help(parser: argparse.ArgumentParser) -> None:
    table = Table(title="HOUND COMMANDS", border_style="white", header_style="bold white")
    table.add_column("Command", style="bold white", no_wrap=True)
    table.add_column("Purpose")
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            purposes = {
                choice.dest: choice.help
                for choice in action._choices_actions
                if choice.help is not argparse.SUPPRESS
            }
            for name, child in action.choices.items():
                if name != "cli":
                    table.add_row(name, purposes.get(name) or child.description or child.prog)
    table.add_row("status", "Show the current command-line session context")
    table.add_row("history", "Show commands entered in this session")
    table.add_row("clear", "Clear the screen and redraw the session header")
    table.add_row("exit", "Return to the launcher or shell")
    console().print(table)


def _show_status() -> None:
    console().print(_session_panel())


def _redraw_header() -> None:
    output = console()
    output.clear()
    output.print(_session_panel())


def _key_bindings() -> KeyBindings:
    bindings = KeyBindings()

    @bindings.add("c-l")
    async def redraw(event) -> None:
        await run_in_terminal(_redraw_header, render_cli_done=True)
        event.app.invalidate()

    return bindings


def run_repl(
    parser: argparse.ArgumentParser,
    dispatch: Callable[[argparse.Namespace, argparse.ArgumentParser], int],
    *,
    return_to_launcher: bool = False,
    session: PromptSession | None = None,
) -> int:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("error: Hound command line requires an interactive TTY", file=sys.stderr)
        return 2
    history_path = Path(user_state_path("hound-tracer")) / "cli-history"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_session = session or PromptSession(
        history=FileHistory(str(history_path)),
        completer=NestedCompleter.from_nested_dict(_command_tree(parser)),
        complete_while_typing=False,
        key_bindings=_key_bindings(),
    )
    entered: list[str] = []
    output = console()
    output.clear()
    output.print(_session_panel())
    while True:
        try:
            raw = prompt_session.prompt("hound> ").strip()
        except KeyboardInterrupt:
            return INTERRUPTED_EXIT_CODE
        except EOFError:
            return 0
        if not raw:
            continue
        entered.append(raw)
        try:
            argv = shlex.split(raw, posix=os.name != "nt")
        except ValueError as exc:
            output.print(f"[bold red]Invalid command:[/bold red] {exc}")
            continue
        if argv and argv[0].lower() == "hound":
            argv = argv[1:]
        if not argv:
            continue
        command = argv[0].lower()
        if command in {"exit", "quit"}:
            return 0
        if command == "clear":
            _redraw_header()
            continue
        if command == "help":
            _show_help(parser)
            continue
        if command == "status":
            _show_status()
            continue
        if command == "history":
            for index, item in enumerate(entered[:-1], 1):
                output.print(f"{index:>3}  {item}")
            continue
        if command == "cli":
            output.print("[dim]Already in the Hound command line.[/dim]")
            continue
        try:
            args = parser.parse_args(argv)
        except SystemExit:
            continue
        try:
            code = dispatch(args, parser)
        except KeyboardInterrupt:
            output.print("\n[bold yellow]Command interrupted.[/bold yellow]")
            continue
        if code:
            output.print(f"[dim]Command exited with code {code}.[/dim]")


def run_cli(args: argparse.Namespace, parser: argparse.ArgumentParser, dispatch) -> int:
    return run_repl(parser, dispatch, return_to_launcher=getattr(args, "return_to_launcher", False))
