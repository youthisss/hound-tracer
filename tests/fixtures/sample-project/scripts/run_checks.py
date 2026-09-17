from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def write_test_artifacts() -> None:
    results = ROOT / "test-results"
    reports = ROOT / "reports"
    logs = ROOT / "logs"
    results.mkdir(exist_ok=True)
    reports.mkdir(exist_ok=True)
    logs.mkdir(exist_ok=True)
    (results / "junit.xml").write_text(
        "<testsuite name='sample' tests='1' failures='1'>"
        "<testcase classname='tests.test_calculator' name='test_divide'>"
        "<failure message='expected 5, got 4'>AssertionError</failure>"
        "</testcase></testsuite>",
        encoding="utf-8",
    )
    (results / "test-report.json").write_text(
        json.dumps({"status": "failed", "name": "test_divide", "message": "expected 5, got 4"}),
        encoding="utf-8",
    )
    (reports / "security.sarif").write_text(
        json.dumps({
            "version": "2.1.0",
            "runs": [{
                "tool": {"driver": {"name": "sample-scanner", "rules": []}},
                "results": [{"level": "warning", "message": {"text": "Unsafe sample configuration"}}],
            }],
        }),
        encoding="utf-8",
    )
    (logs / "application.log").write_text(
        "ERROR calculator validation failed: expected 5, got 4\n",
        encoding="utf-8",
    )
    (reports / "coverage.xml").write_text(
        "<coverage line-rate='0.5' branch-rate='0.5' version='sample'>"
        "<packages><package name='src' line-rate='0.5' branch-rate='0.5'><classes>"
        "<class name='calculator' filename='src/calculator.py' line-rate='0.5' branch-rate='0.5'>"
        "<lines><line number='1' hits='1'/><line number='2' hits='0'/></lines>"
        "</class></classes></package></packages></coverage>",
        encoding="utf-8",
    )


def write_pass_artifacts() -> None:
    results = ROOT / "test-results"
    results.mkdir(exist_ok=True)
    (results / "junit-pass.xml").write_text(
        "<testsuite name='sample' tests='1' failures='0'>"
        "<testcase classname='tests.test_calculator' name='test_divide' time='0.01'/>"
        "</testsuite>",
        encoding="utf-8",
    )


def write_flaky_artifacts() -> None:
    results = ROOT / "test-results"
    results.mkdir(exist_ok=True)
    (results / "junit-flaky.xml").write_text(
        "<testsuite name='sample' tests='2' failures='1'>"
        "<testcase classname='tests.test_calculator' name='test_divide' time='0.01'/>"
        "<testcase classname='tests.test_calculator' name='test_unstable' time='1.25'>"
        "<failure message='intermittent timeout'>TimeoutError</failure>"
        "</testcase></testsuite>",
        encoding="utf-8",
    )


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "test"
    if action == "test":
        write_test_artifacts()
        print("FAILED tests/test_calculator.py::test_divide - AssertionError: expected 5, got 4")
        return 1
    if action == "pass":
        write_pass_artifacts()
        print("1 passed")
        return 0
    if action == "flaky":
        write_flaky_artifacts()
        print("1 passed, 1 failed: intermittent timeout")
        return 1
    if action == "artifacts":
        write_test_artifacts()
        write_pass_artifacts()
        write_flaky_artifacts()
        print("Sample artifacts generated")
        return 0
    if action in {"build", "lint"}:
        print(f"{action} completed")
        return 0
    print(f"Refusing destructive sample action: {action}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
