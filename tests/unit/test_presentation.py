import io

from hound import presentation


def test_rich_output_requires_interactive_terminal(monkeypatch):
    stream = io.StringIO()
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert presentation.rich_enabled(stream) is False


def test_no_color_disables_rich_color(monkeypatch):
    class Tty(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setenv("NO_COLOR", "1")
    assert presentation.rich_enabled(Tty()) is False


def test_dog_mark_is_compact_and_consistent():
    assert len(presentation.DOG_MARK) == 6
    assert len({len(line) for line in presentation.DOG_MARK}) == 1
    assert len(presentation.DOG_MARK[0]) == 20
    assert presentation.DOG_MARK[2] == "███ ██ ██████ ██ ███"
    assert presentation.DOG_MARK[5] == "     ▀▀▀▀▀▀▀▀▀▀     "
    assert set("".join(presentation.DOG_MARK)) <= {" ", "█", "▄", "▀"}
