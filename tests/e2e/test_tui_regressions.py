"""TUI workflow regressions that must stay outside the unit-test suite."""
from __future__ import annotations

import anyio
import shutil
from pathlib import Path


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

JUNIT_XML = (
    "<testsuite name='suite' tests='1' failures='1'>"
    "<testcase classname='pkg' name='test_total'><failure message='boom'>"
    "assert 2 == 3\nAssertionError: boom</failure></testcase>"
    "</testsuite>"
)


def test_tui_analyze_all_processes_visible_logs(tmp_path):
    from textual.widgets import Static

    from hound.tui import HoundTui

    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "a.log")
    shutil.copy(FIXTURES / "flaky.log", tmp_path / "b.log")
    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            assert len(app._log_files) == 2
            app.action_show_artifacts()
            await pilot.pause()
            await pilot.press("A")
            for _ in range(600):
                await pilot.pause(0.02)
                if not app._analyzing and len(app._runs) >= 2:
                    break
            assert not app._analyzing
            reports = list((tmp_path / "out").glob("*/report.md"))
            assert len(reports) == 2
            overview = str(app.query_one("#overview", Static).renderable)
            assert "Batch analysis complete" in overview
            assert "Analyzed [b]2/2[/b]" in overview

    anyio.run(main)


def test_tui_analyze_all_empty_selection_is_noop(tmp_path):
    from textual.widgets import Button, Static

    from hound.tui import HoundTui

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_analyze_all()
            await pilot.pause()
            assert not app._analyzing
            assert "No visible logs" in str(app.query_one("#workflow-status", Static).renderable)
            assert app.query_one("#workspace-analyze-all", Button).disabled

    anyio.run(main)


def test_tui_lists_structured_artifacts_alongside_logs(tmp_path):
    from textual.widgets import ListView, Static

    from hound.tui import HoundTui

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            (tmp_path / "junit.xml").write_text(JUNIT_XML, encoding="utf-8")
            app.action_refresh()
            await app.workers.wait_for_complete()
            for _ in range(400):
                await pilot.pause(0.05)
                items = app.query_one("#log-list", ListView)
                if items.children and "TEST" in str(items.children[0].query_one(Static).renderable):
                    break
            items = app.query_one("#log-list", ListView)
            names = {str(child.query_one(Static).renderable).splitlines()[0].split()[0] for child in items.children}
            assert names == {"junit.xml"}
            assert "TEST" in str(items.children[0].query_one(Static).renderable)

    anyio.run(main)


def test_tui_artifact_refresh_ignores_unmounted_workspace(tmp_path):
    from hound.tui import HoundTui

    app = HoundTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    app._refresh_artifact_selection()
