from __future__ import annotations

import shutil

import anyio


FIXTURES = __import__("pathlib").Path(__file__).resolve().parents[1] / "fixtures"


def test_tui_imports_qa_artifacts_into_history_with_retention(tmp_path) -> None:
    shutil.copy(FIXTURES / "junit_flaky.xml", tmp_path / "junit_flaky.xml")

    from hound.tui import HoundTui
    from textual.widgets import Button, Input, Static

    output = tmp_path / "out"
    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(output), offline=True)

    async def main() -> None:
        async with app.run_test() as pilot:
            await pilot.press("y")
            await pilot.pause()
            app.query_one("#qa-run-id", Input).value = "tui-import-run"
            app.query_one("#qa-retention-days", Input).value = "30"
            app.query_one("#qa-import-history", Button).press()
            for _ in range(250):
                await pilot.pause(0.02)
                if app._qa_result and app._qa_result.get("type") == "import":
                    break

            assert app._qa_result is not None
            assert app._qa_result["type"] == "import"
            assert app._qa_result["imported"] >= 1
            assert app._qa_result["retained"] == 0
            assert (output / ".hound" / "history.sqlite3").is_file()
            rendered = str(app.query_one("#qa-result", Static).renderable)
            assert "HISTORY IMPORT COMPLETE" in rendered
            assert "tui-import-run" in rendered

    anyio.run(main)


def test_tui_qa_form_rejects_invalid_retention_days(tmp_path) -> None:
    from hound.tui import HoundTui
    from textual.widgets import Input

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main() -> None:
        async with app.run_test() as pilot:
            await pilot.press("y")
            await pilot.pause()
            app.query_one("#qa-retention-days", Input).value = "0"
            try:
                app._qa_form_values()
            except ValueError as exc:
                assert "retention days must be at least 1" in str(exc)
            else:
                raise AssertionError("invalid retention days were accepted")

    anyio.run(main)
