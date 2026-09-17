"""Linear MCP tools wrapping Hound Tracer core services.

Every tool maps directly (1:1) to Hound Tracer's core modules:
- hound_analyze -> hound.service.analyze_log / analyze_directory
- hound_log_command -> hound.collector.collect_command + service.analyze_log
- hound_check_gate -> hound.qa.service.run_quality_gate
- hound_get_insights -> hound.qa.history (stats, history, tests)
- hound_doctor -> hound.cli (environment & readiness checks)
- hound_list_incidents -> hound.triage.dedup.list_incidents
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from hound import __version__
from hound import service
from hound.collector import CollectionTimeoutError, collect_command
from hound.config import load_config
from hound.models import SCHEMA_VERSION
from hound.pathutil import path_has_symlink
from hound.pipeline import default_state_path
from hound.qa import history as qa_history
from hound.triage import dedup


def _safe_config_summary(config: Any) -> dict[str, Any] | None:
    if config is None:
        return None
    return {
        "offline": getattr(config, "offline", True),
        "llm_enabled": getattr(config, "llm_enabled", False),
        "provider": getattr(config, "provider", "none"),
        "model": getattr(config, "model", None),
        "redact": getattr(config, "redact", True),
        "source_class": getattr(config, "source_class", "local_artifact"),
    }


def _bounded_failure(failure: dict[str, Any]) -> dict[str, Any]:
    bounded = dict(failure)
    raw_stack = failure.get("stacktrace", [])
    raw_tests = failure.get("failed_tests", [])

    if len(raw_stack) > 15:
        bounded["stacktrace"] = raw_stack[:15]
        bounded["stacktrace_note"] = f"Showing top 15 of {len(raw_stack)} stack frames. Full trace in report.json"

    if len(raw_tests) > 15:
        bounded["failed_tests"] = raw_tests[:15]
        bounded["failed_tests_note"] = f"Showing top 15 of {len(raw_tests)} failed tests. Full list in report.json"

    return bounded


def tool_analyze(
    artifact_path: str,
    output_dir: str = "hound-output",
    offline: bool = True,
    source_context: bool = False,
    enrich: bool = False,
    repo_dir: str | None = None,
    context_path: str | None = None,
    config_path: str | None = None,
    max_artifacts: int = 100,
) -> dict[str, Any]:
    """Analyze one or more failure artifacts (.log, .xml, .sarif, .json) with secret redaction."""
    path = Path(artifact_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"artifact path does not exist: {artifact_path}")
    if path_has_symlink(path) or path.is_symlink():
        raise ValueError(f"symlinked artifacts are not permitted: {artifact_path}")

    out_path = Path(output_dir).expanduser()
    common_opts = {
        "repo_dir": repo_dir,
        "offline": offline,
        "source_context": source_context,
        "enrich": enrich,
        "context_path": context_path,
        "config_path": config_path,
        "redact": True,
    }

    if path.is_file():
        doc = service.analyze_log(path, out_path, **common_opts)
        return {
            "schema_version": doc.get("schema_version", SCHEMA_VERSION),
            "meta": doc.get("meta", {}),
            "failure": _bounded_failure(doc.get("failure", {})),
            "root_cause": doc.get("root_cause", {}),
            "triage": doc.get("triage", {}),
            "context": doc.get("context", {}),
            "raw_output_dir": str(out_path.resolve()),
            "report_path": str((out_path / "report.json").resolve()),
            "available_sections": list(doc),
        }
    else:
        artifacts = service.discover_artifacts(path)
        if len(artifacts) > max_artifacts:
            raise ValueError(f"artifact directory contains {len(artifacts)} supported files; maximum is {max_artifacts}")
        runs = service.analyze_directory(path, out_path, **common_opts)
        return {
            "schema_version": SCHEMA_VERSION,
            "total_runs": len(runs),
            "runs": [
                {
                    "run_id": r.run_id,
                    "log_path": str(r.log_path),
                    "failure": _bounded_failure(r.document.get("failure", {})),
                    "root_cause": r.document.get("root_cause", {}),
                    "triage": r.document.get("triage", {}),
                    "raw_output_dir": str(r.output_dir.resolve()),
                }
                for r in runs
            ],
            "raw_output_dir": str(out_path.resolve()),
        }


def tool_log_command(
    command: list[str],
    cwd: str | None = None,
    analyze_on_failure: bool = True,
    output_dir: str = "hound-output",
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Execute a test/build command, redact logs on-the-fly, and auto-analyze on failure."""
    from hound.output.report import ensure_outdir

    if not command:
        raise ValueError("command must be a non-empty list of arguments")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool):
        raise ValueError("timeout must be a number")
    if not 1 <= timeout <= 3600:
        raise ValueError("timeout must be between 1 and 3600 seconds")

    output_root = ensure_outdir(output_dir)
    logs_dir = output_root / ".hound" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    try:
        collected = collect_command(
            command=command,
            cwd=cwd,
            output=logs_dir,
            raw_console=False,
            timeout=timeout,
        )
    except CollectionTimeoutError as exc:
        collected = exc.collected
        return {
            "exit_code": 124,
            "timed_out": True,
            "timeout_seconds": timeout,
            "error": str(exc),
            "log_file": str(collected.log_file.resolve()),
            "metadata_file": str(collected.metadata_file.resolve()),
            "metadata": collected.metadata,
        }

    result: dict[str, Any] = {
        "exit_code": collected.exit_code,
        "timed_out": False,
        "log_file": str(collected.log_file.resolve()),
        "metadata_file": str(collected.metadata_file.resolve()),
        "metadata": collected.metadata,
    }

    if collected.exit_code != 0 and analyze_on_failure:
        run_dir = output_root / collected.log_file.stem
        doc = service.analyze_log(collected.log_file, run_dir, offline=True)
        result["analysis"] = {
            "failure": _bounded_failure(doc.get("failure", {})),
            "root_cause": doc.get("root_cause", {}),
            "triage": doc.get("triage", {}),
            "raw_output_dir": str(run_dir.resolve()),
        }

    return result


def tool_check_gate(
    source_path: str,
    baseline: str = "HEAD~1",
    head: str = "HEAD",
    repo_path: str = ".",
    policy_path: str | None = None,
    coverage_paths: list[str] | None = None,
    sarif_paths: list[str] | None = None,
    history_store: str | None = None,
    enforced: bool = False,
) -> dict[str, Any]:
    """Evaluate test results, coverage, and security SARIF evidence against a quality gate policy."""
    from hound.qa.service import run_quality_gate

    repo = Path(repo_path).resolve()
    resolved_policy = policy_path
    if not resolved_policy:
        default_policy = repo / ".hound" / "gate-policy.yml"
        if default_policy.is_file():
            resolved_policy = str(default_policy)
        else:
            raise ValueError(
                "policy_path is required or .hound/gate-policy.yml must exist in repo_path"
            )

    coverage_input: list[str | Path] | None = (
        [Path(p) for p in coverage_paths] if coverage_paths is not None else None
    )
    sarif_input: list[str | Path] | None = (
        [Path(p) for p in sarif_paths] if sarif_paths is not None else None
    )

    gate_res = run_quality_gate(
        source_path=source_path,
        baseline=baseline,
        head=head,
        repo_path=repo,
        policy_path=resolved_policy,
        coverage_paths=coverage_input,
        sarif_paths=sarif_input,
        history_store=history_store,
        enforced=enforced,
    )

    return gate_res.to_dict()


def tool_get_insights(
    action: str = "stats",
    test_name: str | None = None,
    window_days: int = 30,
    history_store: str | None = None,
    output_dir: str = "hound-output",
) -> dict[str, Any]:
    """Query test flakiness, duration stats, and history from the QA SQLite store."""
    store_path = (
        Path(history_store)
        if history_store
        else qa_history.default_history_store(output_dir)
    )

    if not store_path.exists():
        return {
            "exists": False,
            "message": f"QA history store does not exist at {store_path}. Run 'hound insights import' first.",
            "store_path": str(store_path),
        }

    suite_name = ""
    test_func = test_name or ""
    if test_name and "::" in test_name:
        parts = test_name.split("::", 1)
        suite_name = parts[0]
        test_func = parts[1]

    if action == "tests":
        tests = qa_history.list_tests(store_path, limit=200)
        return {
            "exists": True,
            "total_tracked_tests": len(tests),
            "tests": tests,
        }
    elif action == "history":
        if not test_func:
            raise ValueError("test_name is required for action='history'")
        history_rows = qa_history.history_for_test(
            store_path, suite_name, test_func, limit=20
        )
        return {
            "exists": True,
            "test_name": test_name,
            "history": history_rows,
        }
    elif action == "stats":
        if test_func:
            rate = qa_history.failure_rate(store_path, suite_name, test_func, days=window_days)
            duration = qa_history.duration_stats(store_path, suite_name, test_func, days=window_days)
            status_counts = qa_history.count_by_status(store_path, suite_name, test_func, days=window_days)
            return {
                "exists": True,
                "test_name": test_name,
                "window_days": window_days,
                "failure_rate": rate,
                "duration_stats": duration,
                "status_counts": status_counts,
            }
        else:
            tests = qa_history.list_tests(store_path, limit=200)
            return {
                "exists": True,
                "window_days": window_days,
                "tracked_test_count": len(tests),
                "summary": "Provide a test_name to get detailed flakiness rate and duration statistics.",
            }
    else:
        raise ValueError(f"unknown insights action: {action}. Supported: stats, history, tests")


def tool_doctor(
    output_dir: str = "hound-output",
    config_path: str | None = None,
) -> dict[str, Any]:
    """Check local environment readiness and tool dependencies without leaking secrets."""
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    python_supported = (3, 10) <= (sys.version_info.major, sys.version_info.minor) < (3, 14)
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    add("python", python_supported, py_ver if python_supported else f"{py_ver} (requires >=3.10,<3.14)")
    add("hound", True, __version__)

    config = None
    try:
        config = load_config(config_path=config_path)
        add("config", True, config_path or "default / environment")
    except Exception as exc:
        add("config", False, str(exc))

    out_p = Path(output_dir).expanduser()
    try:
        out_p.mkdir(parents=True, exist_ok=True)
        probe = out_p / ".hound-mcp-doctor-probe"
        probe.write_text("ok", encoding="ascii")
        probe.unlink()
        add("output", True, str(out_p.resolve()))
    except OSError as exc:
        add("output", False, str(exc))

    for tool in ("git", "docker", "kubectl"):
        location = shutil.which(tool)
        add(tool, location is not None, location or "not installed (optional)")

    return {
        "schema_version": SCHEMA_VERSION,
        "ok": all(c["ok"] for c in checks if c["name"] not in {"docker", "kubectl"}),
        "checks": checks,
        "config": _safe_config_summary(config),
    }


def tool_list_incidents(
    state_path: str | None = None,
    output_dir: str = "hound-output",
    limit: int = 50,
) -> dict[str, Any]:
    """Inspect deduplicated failure incidents and cached RCA snapshots."""
    resolved_state = state_path
    if not resolved_state:
        state_p = default_state_path(Path(output_dir), config_state=None, no_dedup=False)
        resolved_state = str(state_p) if state_p else str(Path(output_dir) / ".hound" / "state.sqlite3")

    incidents = dedup.list_incidents(resolved_state, limit=limit)
    return {
        "state_path": resolved_state,
        "total_incidents": len(incidents),
        "incidents": incidents,
    }


def tool_read_report(report_path: str, section: str = "all") -> dict[str, Any]:
    """Read validated engine output, including timeline, source impact, and ticket data."""
    from hound.fsio import read_bounded_text
    from hound.ingest.redact import redact_text
    from hound.models import validate
    from hound.validation import MAX_REPORT_BYTES

    path = Path(report_path)
    if path_has_symlink(path):
        raise ValueError("report must not use symlinks")
    document = json.loads(read_bounded_text(path, MAX_REPORT_BYTES, encoding="utf-8"))
    validate(document)
    if section != "all" and section not in document:
        raise ValueError(f"report has no section: {section}")
    selected = document if section == "all" else {section: document[section]}

    def scrub(value: Any) -> Any:
        if isinstance(value, str):
            return redact_text(value)[0]
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items()}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value

    return {"report_path": str(path.resolve()), "sections": list(document), "report": scrub(selected)}


def tool_validate_report(report_path: str, output_dir: str = "hound-output", persist: bool = False) -> dict[str, Any]:
    """Validate schema, trust, timeline, and evidence using the shared audit engine."""
    from hound.validation import validate_report

    return validate_report(report_path, output_root=output_dir, persist=persist).to_dict()


def tool_history_transfer(action: str, history_store: str, transfer_path: str) -> dict[str, Any]:
    """Import or export the engine's bounded test-history interchange format."""
    if action == "import":
        count = qa_history.import_history(history_store, transfer_path)
    elif action == "export":
        count = qa_history.export_history(history_store, transfer_path)["count"]
    else:
        raise ValueError("action must be import or export")
    return {"action": action, "count": count, "history_store": history_store, "transfer_path": transfer_path}


def tool_feedback(
    action: str, feedback_store: str, report_path: str | None = None, run_id: str | None = None,
    usefulness: str = "unknown", notes: str = "", reviewed_only: bool = False,
) -> dict[str, Any]:
    """Deprecated compatibility adapter; use hound_feedback_record/list."""

    if action == "list":
        return tool_feedback_list(feedback_store, reviewed_only=reviewed_only)
    if action != "record":
        raise ValueError("action must be record or list")
    if not report_path or not run_id:
        raise ValueError("report_path and run_id are required to record feedback")
    return tool_feedback_record(feedback_store, report_path, run_id, usefulness=usefulness, notes=notes)


def tool_feedback_record(
    feedback_store: str, report_path: str, run_id: str,
    usefulness: str = "unknown", notes: str = "",
) -> dict[str, Any]:
    """Record pending diagnostic feedback."""
    from hound.feedback import record_feedback

    return record_feedback(feedback_store, report_path, run_id, usefulness=usefulness, notes=notes)


def tool_feedback_list(feedback_store: str, reviewed_only: bool = False, limit: int = 50) -> dict[str, Any]:
    """List bounded diagnostic feedback."""
    from hound.feedback import read_feedback

    records = read_feedback(feedback_store, reviewed_only=reviewed_only)
    return {"count": min(len(records), limit), "total": len(records), "records": records[:limit]}


def tool_history_import(history_store: str, transfer_path: str) -> dict[str, Any]:
    count = qa_history.import_history(history_store, transfer_path)
    return {"count": count, "history_store": history_store, "transfer_path": transfer_path}


def tool_history_export(history_store: str, transfer_path: str) -> dict[str, Any]:
    count = qa_history.export_history(history_store, transfer_path)["count"]
    return {"count": count, "history_store": history_store, "transfer_path": transfer_path}


def tool_evaluate(corpus_path: str, suite: str = "all", max_cases: int = 500, timeout: float = 300.0) -> dict[str, Any]:
    """Run the deterministic diagnostic regression evaluator over a local corpus."""
    from hound.eval import evaluate

    corpus = Path(corpus_path)
    if suite not in {"qa-history", "test-impact"}:
        case_count = sum(1 for _ in corpus.rglob("*.json"))
        if case_count > max_cases:
            raise ValueError(f"evaluation corpus contains {case_count} JSON files; maximum is {max_cases}")
    started = time.monotonic()
    result = evaluate(corpus=corpus, suite=suite)
    if time.monotonic() - started > timeout:
        raise ValueError(f"evaluation exceeded the {timeout:g}s result deadline")
    return result
