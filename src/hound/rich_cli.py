"""Persistent Rich command shell for Hound subcommands."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys
from collections.abc import Callable
from urllib.parse import urlsplit

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
from hound.ingest.redact import redact_text
from hound.presentation import DOG_MARK, DOG_MARK_STYLE, console
from hound.presentation import TaskMessage

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


def _panel_width(terminal_width: int) -> int:
    return max(40, min(96, terminal_width - 2))


def _session_panel(terminal_width: int = 98) -> Panel:
    workspace = Path.cwd() / ".hound"
    title = Text()
    title.append(BRAND_NAME.upper(), style="bold white")
    title.append(f"  v{__version__}\n", style="dim white")
    title.append("Command line", style="bold white")
    info = Table.grid(padding=(0, 2))
    info.add_column(style="bold white", no_wrap=True)
    info.add_column(style="white", overflow="fold")
    info.add_row("Project", str(Path.cwd()))
    info.add_row("Workspace", str(workspace) if workspace.is_dir() else "Not initialized")
    info.add_row("Help", "Type `help` to browse commands and usage.")
    details = Group(title, Text(""), info)
    width = _panel_width(terminal_width)
    content: Group | Table
    if width < 78:
        content = details
    else:
        layout = Table.grid(padding=(0, 3))
        layout.add_column(no_wrap=True)
        layout.add_column(overflow="fold")
        layout.add_row(Text("\n".join(DOG_MARK), style=DOG_MARK_STYLE), details)
        content = layout
    return Panel(content, border_style="white", width=width, padding=(1, 2))


def _available_commands(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return {name: child for name, child in action.choices.items() if name != "cli"}
    return {}


def _show_command_help(parser: argparse.ArgumentParser, command_path: list[str]) -> bool:
    current = parser
    for command in command_path:
        choices: dict[str, argparse.ArgumentParser] = {}
        for action in current._actions:
            if isinstance(action, argparse._SubParsersAction):
                choices = action.choices
                break
        if command not in choices:
            console().print(f"[bold red]Unknown command:[/bold red] {' '.join(command_path)}")
            return False
        current = choices[command]

    title = f"HOW TO USE: {' '.join(command_path).upper()}"
    console().print(Panel(current.format_help().rstrip(), title=title, border_style="white", padding=(1, 2)))
    return True


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


def _prompt_for_command_help(parser: argparse.ArgumentParser, prompt_session: PromptSession) -> None:
    commands = _available_commands(parser)
    if not commands:
        return
    console().print(
        Panel(
            "Enter a command name to see its usage, arguments, and options.\n"
            "Press Enter to return to the command line.",
            title="COMMAND HELP",
            border_style="white",
            width=_panel_width(console().width),
            padding=(0, 1),
        )
    )
    try:
        selection = prompt_session.prompt("help> ").strip()
    except KeyboardInterrupt:
        return
    except EOFError:
        return
    if selection:
        _show_command_help(parser, selection.split())


def _show_status() -> None:
    output = console()
    output.print(_session_panel(output.width))


def _redraw_header() -> None:
    output = console()
    output.clear()
    output.print(_session_panel(output.width))


def _key_bindings() -> KeyBindings:
    bindings = KeyBindings()

    @bindings.add("c-l")
    async def redraw(event) -> None:
        await run_in_terminal(_redraw_header, render_cli_done=True)
        event.app.invalidate()

    return bindings


def _safe_command_display(command: list[str]) -> str:
    if command and command[0] == "--":
        command = command[1:]
    return redact_text(subprocess.list2cmdline(command))[0] if command else "piped stdin"


def _safe_url_display(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = f":{parsed.port}" if parsed.port is not None else ""
    except ValueError:
        return redact_text(value)[0]
    if not parsed.scheme or not parsed.hostname:
        return redact_text(value)[0]
    return f"{parsed.scheme}://{parsed.hostname}{port}{parsed.path.rstrip('/')}"


def _command_task(args: argparse.Namespace) -> TaskMessage | None:
    """Build a live task panel for long-running commands in the REPL only."""
    if getattr(args, "json", False) or getattr(args, "format", "text") == "json":
        return None
    command = args.command
    if command in {"analyze", "run"}:
        return None
    if command == "batch":
        return TaskMessage(
            "BATCH ANALYSIS",
            (
                ("Input", getattr(args, "logs", "")),
                ("Output", getattr(args, "out", "")),
                ("Workers", getattr(args, "jobs", 1)),
                ("Mode", "Offline rules" if getattr(args, "offline", False) else "Configured provider"),
            ),
            "Processing analysis artifacts",
            enabled=True,
        )
    if command == "log":
        return TaskMessage(
            "CAPTURE COMMAND",
            (
                ("Command", _safe_command_display(list(getattr(args, "command_args", [])))),
                ("Capture", getattr(args, "output", None) or ".hound/captures"),
                ("Analyze", "Yes" if getattr(args, "analyze", False) else "No"),
            ),
            "Capturing and redacting command output",
            enabled=True,
        )
    qa_command = getattr(args, "qa_command", None)
    if command == "gate" or (command == "insights" and qa_command == "gate"):
        return TaskMessage(
            "QUALITY GATE",
            (
                ("Evidence", getattr(args, "path", "")),
                ("Baseline", getattr(args, "baseline", "")),
                ("Candidate", getattr(args, "head", "HEAD")),
                ("Policy", getattr(args, "policy", "")),
            ),
            "Evaluating evidence against policy",
            enabled=True,
        )
    if command == "insights" and qa_command in {"analyze", "import", "export"}:
        title = f"INSIGHTS {qa_command.upper()}"
        source = getattr(args, "path", None) or getattr(args, "store", None) or "History store"
        return TaskMessage(
            title,
            (
                ("Source", source),
                ("History", getattr(args, "store", None) or "Default history store"),
                ("Output", getattr(args, "out", None) or getattr(args, "output", None) or "Default output"),
            ),
            {
                "analyze": "Classifying test evidence",
                "import": "Normalizing and importing test evidence",
                "export": "Exporting sanitized test history",
            }[qa_command],
            enabled=True,
        )
    if command == "models" and getattr(args, "refresh", False):
        return TaskMessage(
            "REFRESH MODELS",
            (("Provider", args.provider), ("Endpoint", _safe_url_display(args.base_url or "Provider default"))),
            "Fetching provider model catalog",
            enabled=True,
        )
    client_command = getattr(args, "client_command", None)
    if command == "client" and (client_command == "poll" or (client_command == "submit" and args.wait)):
        identity = getattr(args, "job_id", None) or getattr(args, "log", "")
        return TaskMessage(
            f"CLIENT {client_command.upper()}",
            (
                ("Server", _safe_url_display(args.url)),
                ("Job", identity),
                ("Timeout", getattr(args, "wait_timeout", None) or "Server default"),
            ),
            "Waiting for remote job status",
            enabled=True,
        )
    if command in {"install", "uninstall"} and getattr(args, "yes", False):
        return TaskMessage(
            command.upper(),
            (
                ("Component", getattr(args, "component", None) or "Package"),
                ("Targets", ", ".join(getattr(args, "harnesses", None) or []) or "Current environment"),
                ("Scope", getattr(args, "scope", "global")),
            ),
            f"{command.title()}ing Hound components",
            enabled=True,
        )
    if (
        command == "integrations"
        and getattr(args, "integrations_command", None) == "install"
        and getattr(args, "yes", False)
    ):
        return TaskMessage(
            "INSTALL INTEGRATIONS",
            (
                ("Targets", ", ".join(args.harnesses) if args.harnesses else "Detected harnesses"),
                ("Scope", args.scope),
            ),
            "Installing harness integrations",
            enabled=True,
        )
    return None


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
    output.print(_session_panel(output.width))
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
            if len(argv) > 1:
                _show_command_help(parser, argv[1:])
            else:
                _show_help(parser)
                _prompt_for_command_help(parser, prompt_session)
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
        args.interactive_cli = True
        try:
            task = _command_task(args)
            if task is None:
                code = dispatch(args, parser)
            else:
                with task:
                    code = dispatch(args, parser)
        except KeyboardInterrupt:
            output.print("\n[bold yellow]Command interrupted.[/bold yellow]")
            continue
        if code:
            output.print(f"[dim]Command exited with code {code}.[/dim]")


def run_cli(args: argparse.Namespace, parser: argparse.ArgumentParser, dispatch) -> int:
    return run_repl(parser, dispatch, return_to_launcher=getattr(args, "return_to_launcher", False))
