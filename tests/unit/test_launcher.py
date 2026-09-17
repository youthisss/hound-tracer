from hound import launcher


def test_interface_chooser_selects_server(monkeypatch):
    keys = iter(("down", "down", "enter"))
    monkeypatch.setattr("hound.launcher.console", lambda: _ConsoleStub())

    assert launcher.choose_interface(read_key=lambda: next(keys)) == "serve"


def test_interface_chooser_wraps_and_escape_exits(monkeypatch):
    keys = iter(("up", "enter"))
    monkeypatch.setattr("hound.launcher.console", lambda: _ConsoleStub())
    assert launcher.choose_interface(read_key=lambda: next(keys)) == "exit"

    monkeypatch.setattr("hound.launcher.console", lambda: _ConsoleStub())
    assert launcher.choose_interface(read_key=lambda: "escape") == "exit"


def test_launcher_dispatches_parser_defaults(monkeypatch):
    from hound.cli import build_parser

    called = []
    monkeypatch.setattr("hound.launcher.choose_interface", lambda: "serve")
    monkeypatch.setattr("hound.launcher.console", lambda: _ConsoleStub())

    code = launcher.launch(
        build_parser(),
        dispatch=lambda args, parser: called.append(("dispatch", args)) or 0,
        run_tui=lambda args: called.append(("console", args)) or 0,
        run_server=lambda args: called.append(("serve", args)) or 7,
    )

    assert code == 7
    assert called[0][0] == "serve"
    assert called[0][1].host == "127.0.0.1"
    assert called[0][1].port == 8123


def test_launcher_dispatches_command_line(monkeypatch):
    from hound.cli import build_parser

    called = []
    selections = iter(("cli", "exit"))
    monkeypatch.setattr("hound.launcher.choose_interface", lambda: next(selections))
    monkeypatch.setattr("hound.launcher.console", lambda: _ConsoleStub())

    assert launcher.launch(
        build_parser(),
        dispatch=lambda args, parser: called.append((args, parser)) or 0,
        run_tui=lambda args: 0,
        run_server=lambda args: 0,
    ) == 0
    assert called[0][0].command == "cli"
    assert called[0][0].return_to_launcher is True


def test_launcher_returns_to_menu_after_tui(monkeypatch):
    from hound.cli import build_parser

    called = []
    selections = iter(("console", "exit"))
    monkeypatch.setattr("hound.launcher.choose_interface", lambda: next(selections))
    monkeypatch.setattr("hound.launcher.console", lambda: _ConsoleStub())

    assert launcher.launch(
        build_parser(),
        dispatch=lambda args, parser: 0,
        run_tui=lambda args: called.append(args) or 0,
        run_server=lambda args: 0,
    ) == 0
    assert called[0].return_to_launcher is True


def test_launcher_ctrl_c_from_tui_returns_to_shell(monkeypatch):
    from hound.cli import build_parser

    monkeypatch.setattr("hound.launcher.choose_interface", lambda: "console")
    monkeypatch.setattr("hound.launcher.console", lambda: _ConsoleStub())

    assert launcher.launch(
        build_parser(),
        dispatch=lambda args, parser: 0,
        run_tui=lambda args: 130,
        run_server=lambda args: 0,
    ) == 130


def test_launcher_ctrl_c_from_command_line_returns_to_shell(monkeypatch):
    from hound.cli import build_parser
    from hound.rich_cli import INTERRUPTED_EXIT_CODE

    monkeypatch.setattr("hound.launcher.choose_interface", lambda: "cli")
    monkeypatch.setattr("hound.launcher.console", lambda: _ConsoleStub())

    assert launcher.launch(
        build_parser(),
        dispatch=lambda args, parser: INTERRUPTED_EXIT_CODE,
        run_tui=lambda args: 0,
        run_server=lambda args: 0,
    ) == INTERRUPTED_EXIT_CODE


class _ConsoleStub:
    def clear(self):
        pass

    def print(self, *args, **kwargs):
        pass
