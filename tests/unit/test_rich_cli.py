import argparse
from io import StringIO

import anyio
import pytest
from rich.console import Console

from hound.rich_cli import (
    INTERRUPTED_EXIT_CODE,
    _command_task,
    _key_bindings,
    _session_panel,
    _show_command_help,
    _show_help,
    run_repl,
)


class _Session:
    def __init__(self, commands):
        self.commands = iter(commands)

    def prompt(self, _prompt):
        item = next(self.commands)
        if isinstance(item, BaseException):
            raise item
        return item


class _Console:
    def __init__(self):
        self.values = []
        self.width = 120

    def clear(self):
        self.values.append("clear")

    def print(self, value="", *args, **kwargs):
        self.values.append(str(value))


def _parser():
    parser = argparse.ArgumentParser(prog="hound")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("doctor", help="check local readiness")
    sub.add_parser("cli", help="open the persistent command line")
    return parser


def test_help_shows_command_purpose_instead_of_program_name(monkeypatch):
    stream = StringIO()
    output = Console(file=stream, force_terminal=False, width=120)
    monkeypatch.setattr("hound.rich_cli.console", lambda: output)

    _show_help(_parser())

    rendered = stream.getvalue()
    assert "check local readiness" in rendered
    assert "hound doctor" not in rendered
    assert "open the persistent command line" not in rendered


def test_session_panel_uses_available_width_and_adapts_to_narrow_terminals():
    assert _session_panel(120).width == 96
    narrow = _session_panel(60)
    assert narrow.width == 58


@pytest.mark.parametrize(
    ("argv", "title"),
    [
        (["batch", "--logs", "logs"], "BATCH ANALYSIS"),
        (["log", "--", "pytest", "-q"], "CAPTURE COMMAND"),
        (
            ["gate", "artifacts", "--baseline-ref", "main", "--repo-dir", ".", "--policy", "gate.yml"],
            "QUALITY GATE",
        ),
        (["insights", "analyze", "results.xml"], "INSIGHTS ANALYZE"),
        (["models", "--provider", "openai", "--refresh"], "REFRESH MODELS"),
        (["client", "poll", "--url", "https://example.test", "job-1"], "CLIENT POLL"),
        (["install", "all", "--for", "opencode", "--yes"], "INSTALL"),
        (["integrations", "install", "opencode", "--yes"], "INSTALL INTEGRATIONS"),
    ],
)
def test_long_running_cli_commands_get_task_panels(argv, title):
    from hound.cli import build_parser

    task = _command_task(build_parser().parse_args(argv))

    assert task is not None
    assert task.title == title


def test_fast_and_json_commands_do_not_get_task_panels():
    from hound.cli import build_parser

    parser = build_parser()
    assert _command_task(parser.parse_args(["results"])) is None
    assert _command_task(parser.parse_args(["models", "--provider", "openai"])) is None
    assert _command_task(
        parser.parse_args(["client", "poll", "--url", "https://example.test", "job-1", "--json"])
    ) is None


def test_command_help_shows_usage_and_options(monkeypatch):
    stream = StringIO()
    output = Console(file=stream, force_terminal=False, width=120)
    monkeypatch.setattr("hound.rich_cli.console", lambda: output)

    assert _show_command_help(_parser(), ["doctor"]) is True

    rendered = stream.getvalue()
    assert "HOW TO USE: DOCTOR" in rendered
    assert "usage: hound doctor" in rendered


def test_help_prompts_for_command_and_shows_guide(monkeypatch):
    stream = StringIO()
    output = Console(file=stream, force_terminal=False, width=120)
    monkeypatch.setattr("hound.rich_cli.console", lambda: output)
    monkeypatch.setattr("hound.rich_cli.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("hound.rich_cli.sys.stdout.isatty", lambda: True)

    assert run_repl(
        _parser(),
        lambda args, parser: 0,
        session=_Session(("help", "doctor", "exit")),
    ) == 0
    assert "HOW TO USE: DOCTOR" in stream.getvalue()


def test_repl_dispatches_hound_commands_and_exits(monkeypatch):
    output = _Console()
    called = []
    monkeypatch.setattr("hound.rich_cli.console", lambda: output)
    monkeypatch.setattr("hound.rich_cli.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("hound.rich_cli.sys.stdout.isatty", lambda: True)

    assert run_repl(
        _parser(),
        lambda args, parser: called.append(args.command) or 0,
        session=_Session(("hound doctor", "exit")),
    ) == 0
    assert called == ["doctor"]


def test_ctrl_c_exits_repl_immediately(monkeypatch):
    output = _Console()
    called = []
    monkeypatch.setattr("hound.rich_cli.console", lambda: output)
    monkeypatch.setattr("hound.rich_cli.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("hound.rich_cli.sys.stdout.isatty", lambda: True)

    assert run_repl(
        _parser(),
        lambda args, parser: called.append(args.command) or 0,
        session=_Session((KeyboardInterrupt(), "doctor")),
    ) == INTERRUPTED_EXIT_CODE
    assert called == []


def test_repl_internal_commands_do_not_dispatch(monkeypatch):
    output = _Console()
    called = []
    monkeypatch.setattr("hound.rich_cli.console", lambda: output)
    monkeypatch.setattr("hound.rich_cli._show_help", lambda parser: output.print("help"))
    monkeypatch.setattr("hound.rich_cli._show_status", lambda: output.print("status"))
    monkeypatch.setattr("hound.rich_cli.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("hound.rich_cli.sys.stdout.isatty", lambda: True)

    run_repl(
        _parser(),
        lambda args, parser: called.append(args.command) or 0,
        session=_Session(("help", "", "status", "history", "clear", EOFError())),
    )
    assert called == []
    assert "help" in output.values
    assert "status" in output.values


def test_repl_requires_tty(monkeypatch, capsys):
    monkeypatch.setattr("hound.rich_cli.sys.stdin.isatty", lambda: False)
    assert run_repl(_parser(), lambda args, parser: 0, session=_Session(())) == 2
    assert "requires an interactive TTY" in capsys.readouterr().err


def test_ctrl_l_redraws_session_header(monkeypatch):
    output = _Console()
    monkeypatch.setattr("hound.rich_cli.console", lambda: output)
    async def run_now(callback, **kwargs):
        callback()

    monkeypatch.setattr("hound.rich_cli.run_in_terminal", run_now)
    binding = next(binding for binding in _key_bindings().bindings if binding.keys == ("c-l",))

    class App:
        invalidated = False

        def invalidate(self):
            self.invalidated = True

    event = type("Event", (), {"app": App()})()
    anyio.run(binding.handler, event)

    assert output.values[0] == "clear"
    assert output.values[1].startswith("<rich.panel.Panel")
    assert event.app.invalidated is True
