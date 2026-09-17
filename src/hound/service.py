"""Shared application service used by CLI and TUI adapters."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import threading
from uuid import uuid4
from hound.collector import CollectionTimeoutError, CollectedLog, collect_command
from hound.config import load_config
from hound.fsio import atomic_write, read_bounded_text
from hound.pipeline import default_state_path

from hound.pipeline import analyze as _analyze_pipeline
from hound.output.report import ensure_outdir
from hound.pathutil import path_has_symlink


SUPPORTED_LOG_SUFFIXES = {".log", ".xml", ".sarif", ".json"}

# Repository-wide discovery must avoid dependency trees and generated source
# while retaining the report directories that commonly contain useful evidence.
ARTIFACT_SCAN_IGNORED_DIRS = {
    ".git", ".hg", ".svn", ".idea", ".vscode",
    ".venv", "venv", "env", "node_modules", "vendor",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".tox", ".nox", ".cache", ".next", ".nuxt",
}
MAX_DISCOVERED_ARTIFACTS = 10_000
STRUCTURED_ARTIFACT_HINTS = {
    "artifact", "junit", "pytest", "test-result", "test_results", "testresults",
    "surefire", "failsafe", "playwright", "cypress", "vitest", "jest", "go-test",
}
DEFAULT_PROJECT_TIMEOUT_SECONDS = 300.0
MAX_PROJECT_RUN_RECORD_BYTES = 1024 * 1024
_UNSAFE_COMMAND_TERMS = {
    "clean", "deploy", "destroy", "drop", "migrate", "migration", "prod",
    "production", "publish", "release", "remove", "reset", "rm", "rollback",
}
_SAFE_PACKAGE_SCRIPTS = {"build", "check", "lint", "test", "typecheck", "type-check", "verify"}
_MAX_MANIFEST_BYTES = 2 * 1024 * 1024


class AnalysisInputError(ValueError):
    """Raised when an analysis input path is invalid or unusable."""


@dataclass(frozen=True)
class AnalysisRun:
    run_id: str
    log_path: Path
    output_dir: Path
    document: dict


@dataclass(frozen=True)
class ProjectRunRequest:
    command: tuple[str, ...]
    cwd: Path
    capture_directory: Path
    runs_directory: Path
    timeout: float
    started_at: datetime
    artifacts_before: dict[Path, tuple[int, int]]


@dataclass(frozen=True)
class ProjectRunResult:
    request: ProjectRunRequest
    collected: CollectedLog
    record: dict
    error: str | None = None


def artifact_signatures(directory: Path) -> dict[Path, tuple[int, int]]:
    try:
        paths = discover_artifacts(directory)
    except AnalysisInputError:
        return {}
    signatures: dict[Path, tuple[int, int]] = {}
    for path in paths:
        try:
            file_stat = path.stat()
            signatures[path] = (file_stat.st_size, file_stat.st_mtime_ns)
        except OSError:
            continue
    return signatures


def prepare_project_run(command: list[str], cwd: str | Path, *, timeout: float = DEFAULT_PROJECT_TIMEOUT_SECONDS) -> ProjectRunRequest:
    directory = Path(cwd).expanduser().resolve()
    if not command or not all(isinstance(item, str) and item for item in command):
        raise ValueError("command must contain non-empty arguments")
    if not directory.is_dir() or path_has_symlink(directory) or directory.is_symlink():
        raise ValueError("project directory must be an existing non-symlink directory")
    if timeout <= 0 or timeout > 3600:
        raise ValueError("timeout must be between 1 and 3600 seconds")
    state_root = directory if directory.name == ".hound" else directory / ".hound"
    if path_has_symlink(state_root) or state_root.is_symlink():
        raise ValueError("project run state directory must not contain symlinks")
    return ProjectRunRequest(
        command=tuple(command), cwd=directory, capture_directory=state_root / "captures",
        runs_directory=state_root / "runs", timeout=timeout,
        started_at=datetime.now(timezone.utc), artifacts_before=artifact_signatures(directory),
    )


def execute_project_run(request: ProjectRunRequest, *, cancel_event: threading.Event | None = None) -> ProjectRunResult:
    if path_has_symlink(request.capture_directory) or path_has_symlink(request.runs_directory):
        raise ValueError("project run state directories must not contain symlinks")
    request.capture_directory.mkdir(parents=True, exist_ok=True)
    if path_has_symlink(request.capture_directory):
        raise ValueError("project capture directory must not contain symlinks")
    error = None
    try:
        with open(os.devnull, "w", encoding="utf-8") as sink:
            collected = collect_command(
                list(request.command), output=request.capture_directory, cwd=request.cwd,
                stream=sink, timeout=request.timeout, cancel_event=cancel_event,
            )
    except CollectionTimeoutError as exc:
        collected = exc.collected
        error = str(exc)
    after = artifact_signatures(request.cwd)
    changed = sorted(str(path) for path, signature in after.items() if request.artifacts_before.get(path) != signature)
    run_id = f"run-{request.started_at.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    record = {
        "schema_version": "1.0", "run_id": run_id,
        "command": list(collected.metadata.get("command", [])), "cwd": str(request.cwd),
        "status": "timed_out" if collected.exit_code == 124 else "cancelled" if collected.metadata.get("cancelled") else "passed" if collected.exit_code == 0 else "failed",
        "exit_code": collected.exit_code, "started_at": request.started_at.isoformat(),
        "duration_ms": int(collected.metadata.get("duration_ms", 0)), "capture": str(collected.log_file),
        "artifacts": changed, "output_truncated": bool(collected.metadata.get("output_truncated", False)),
    }
    request.runs_directory.mkdir(parents=True, exist_ok=True)
    if path_has_symlink(request.runs_directory):
        raise ValueError("project run directory must not contain symlinks")
    atomic_write(request.runs_directory / f"{run_id}.json", json.dumps(record, indent=2, ensure_ascii=False))
    return ProjectRunResult(request, collected, record, error)


def discover_project_commands(root: str | Path) -> list[tuple[str, list[str]]]:
    """Return bounded, non-mutating command suggestions from project manifests."""
    directory = Path(root).expanduser().resolve()
    if not directory.is_dir() or directory.is_symlink() or path_has_symlink(directory):
        raise ValueError("project directory must be an existing non-symlink directory")
    suggestions: list[tuple[str, list[str]]] = []

    def suggestible(parts: list[str]) -> bool:
        words = {word.lower() for part in parts for word in re.findall(r"[A-Za-z0-9_-]+", part)}
        return not bool(words & _UNSAFE_COMMAND_TERMS)

    def add(label: str, command: list[str]) -> None:
        if suggestible(command) and command not in [item[1] for item in suggestions]:
            suggestions.append((label, command))

    package = directory / "package.json"
    if package.is_file() and not package.is_symlink():
        try:
            data = json.loads(read_bounded_text(package, _MAX_MANIFEST_BYTES, encoding="utf-8"))
            scripts = data.get("scripts", {}) if isinstance(data, dict) else {}
            if isinstance(scripts, dict):
                runner = "npm.cmd" if os.name == "nt" else "npm"
                for name, body in scripts.items():
                    if isinstance(name, str) and isinstance(body, str) and name.lower() in _SAFE_PACKAGE_SCRIPTS and suggestible([body]):
                        add(f"npm {name}", [runner, "run", name])
        except (OSError, ValueError):
            pass
    pyproject = directory / "pyproject.toml"
    if pyproject.is_file() and not pyproject.is_symlink():
        try:
            if "pytest" in read_bounded_text(pyproject, _MAX_MANIFEST_BYTES, encoding="utf-8").lower():
                add("pytest", ["pytest", "-q"])
        except (OSError, ValueError):
            pass
    if (directory / "Cargo.toml").is_file():
        add("cargo test", ["cargo", "test"])
        add("cargo build", ["cargo", "build"])
    if (directory / "go.mod").is_file():
        add("go test", ["go", "test", "./..."])
    if (directory / "pom.xml").is_file():
        runner = "mvn.cmd" if os.name == "nt" else "mvn"
        add("mvn test", [runner, "test"])
        add("mvn package", [runner, "package"])
    if (directory / "gradlew").is_file() or (directory / "gradlew.bat").is_file():
        wrapper = "gradlew.bat" if os.name == "nt" else "./gradlew"
        add("gradle test", [wrapper, "test"])
        add("gradle build", [wrapper, "build"])
    makefile = directory / "Makefile"
    if makefile.is_file() and not makefile.is_symlink():
        try:
            text = read_bounded_text(makefile, _MAX_MANIFEST_BYTES, encoding="utf-8")
            targets = {
                match.group(1) for line in text.splitlines()
                if (match := re.match(r"^([A-Za-z0-9_.-]+)\s*:(?![=])", line))
            }
            for target in sorted(targets & _SAFE_PACKAGE_SCRIPTS):
                add(f"make {target}", ["make", target])
        except (OSError, ValueError):
            pass
    return suggestions[:6]


def load_project_runs(directory: Path) -> tuple[list[dict], list[str]]:
    if not directory.exists():
        return [], []
    if path_has_symlink(directory) or directory.is_symlink() or not directory.is_dir():
        return [], [f"unsafe run directory: {directory}"]
    runs: list[dict] = []
    errors: list[str] = []
    for path in directory.glob("*.json"):
        try:
            record = json.loads(read_bounded_text(path, MAX_PROJECT_RUN_RECORD_BYTES, encoding="utf-8"))
            command = record.get("command") if isinstance(record, dict) else None
            if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
                raise ValueError("invalid command field")
            record["record_path"] = str(path)
            runs.append(record)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{path.name}: {exc}")
    return sorted(runs, key=lambda item: str(item.get("started_at", "")), reverse=True), errors


def find_logs(log_directory: str | Path) -> list[Path]:
    """Return supported logs from one directory without recursive scanning."""
    directory = Path(log_directory).expanduser()
    if path_has_symlink(directory) or directory.is_symlink():
        raise AnalysisInputError(f"log directory must not contain symlinked path components: {directory}")
    if not directory.exists():
        raise AnalysisInputError(f"log directory does not exist: {directory}")
    if not directory.is_dir():
        raise AnalysisInputError(f"expected a log directory, got file: {directory}")
    if not os.access(directory, os.R_OK):
        raise AnalysisInputError(f"log directory is not readable: {directory}")
    root = directory.resolve()
    try:
        logs = sorted(
            (
                path
                for path in directory.iterdir()
                if path.is_file()
                and not path.is_symlink()
                and path.resolve().is_relative_to(root)
                and path.suffix.lower() in SUPPORTED_LOG_SUFFIXES
                and not _is_sidecar(path)
            ),
            key=lambda path: path.name.lower(),
        )
    except OSError as exc:
        raise AnalysisInputError(f"cannot read log directory {directory}: {exc}") from exc
    if not logs:
        raise AnalysisInputError(
                f"no supported artifacts found in {directory}; add a .log, JUnit .xml, or .sarif file"
        )
    return logs


def discover_artifacts(
    root_directory: str | Path,
    *,
    ignored_dirs: set[str] | None = None,
    limit: int = MAX_DISCOVERED_ARTIFACTS,
) -> list[Path]:
    """Recursively find supported artifacts beneath a trusted local directory.

    Symlinked files and directories are never followed. Dependency and cache
    directories are pruned, but report-bearing build directories remain visible.
    """
    directory = Path(root_directory).expanduser()
    if path_has_symlink(directory) or directory.is_symlink():
        raise AnalysisInputError(f"artifact directory must not contain symlinked path components: {directory}")
    if not directory.exists():
        raise AnalysisInputError(f"artifact directory does not exist: {directory}")
    if not directory.is_dir():
        raise AnalysisInputError(f"expected an artifact directory, got file: {directory}")
    if not os.access(directory, os.R_OK):
        raise AnalysisInputError(f"artifact directory is not readable: {directory}")
    if limit < 1:
        raise ValueError("artifact discovery limit must be positive")

    root = directory.resolve()
    ignored = set(ARTIFACT_SCAN_IGNORED_DIRS if ignored_dirs is None else ignored_dirs)
    if directory.name == ".hound":
        ignored.update({"results", "state"})
    artifacts: list[Path] = []
    from hound.ingest.structured import parse_structured_artifact

    try:
        for current, dirnames, filenames in os.walk(root, followlinks=False):
            current_path = Path(current)
            current_ignored = ignored | ({"results", "state"} if current_path.name == ".hound" else set())
            dirnames[:] = sorted(
                name for name in dirnames
                if name not in current_ignored and not (current_path / name).is_symlink()
            )
            for name in sorted(filenames):
                path = current_path / name
                if (
                    path.suffix.lower() not in SUPPORTED_LOG_SUFFIXES
                    or path.is_symlink()
                    or not path.is_file()
                    or _is_sidecar(path)
                ):
                    continue
                if path.suffix.lower() in {".xml", ".json"}:
                    relative_text = path.relative_to(root).as_posix().lower()
                    if not any(hint in relative_text for hint in STRUCTURED_ARTIFACT_HINTS):
                        continue
                    if parse_structured_artifact(path) is None:
                        continue
                artifacts.append(path)
                if len(artifacts) >= limit:
                    return artifacts
    except OSError as exc:
        raise AnalysisInputError(f"cannot scan artifact directory {directory}: {exc}") from exc
    return artifacts


def is_sidecar(path: Path) -> bool:
    """Collector writes `<log>.json`; it is context, never an input artifact."""
    return path.suffix.lower() == ".json" and path.with_suffix(".log").is_file()


# Back-compat alias (used to be private; CLI/TUI import the public name now).
_is_sidecar = is_sidecar


def analyze_log(log_path: str | Path, output_dir: str | Path, **kwargs) -> dict:
    """Run shared analysis pipeline for one log."""
    return _analyze_pipeline(log_path, output_dir, **kwargs)


def analyze_directory(
    log_directory: str | Path,
    output_root: str | Path,
    **kwargs,
) -> list[AnalysisRun]:
    """Analyze supported logs in one directory using isolated run directories.

    ``jobs`` controls parallel analysis workers (default 1 = sequential).
    Run IDs are derived from input order, so results stay deterministic
    regardless of completion order.
    """
    jobs = max(1, int(kwargs.pop("jobs", 1) or 1))
    logs = discover_artifacts(log_directory)
    if not logs:
        raise AnalysisInputError(
            f"no supported artifacts found in {Path(log_directory).expanduser()}; "
            "add a .log, JUnit .xml, .sarif, or supported test-report .json file"
        )
    root = ensure_outdir(output_root)
    config = load_config(
        offline=bool(kwargs.get("offline", False)),
        config_path=kwargs.get("config_path"),
        provider=kwargs.get("provider"),
        model=kwargs.get("model"),
        base_url=kwargs.get("base_url"),
        api_key=kwargs.get("api_key"),
        redact=kwargs.get("redact"),
        max_retries=kwargs.get("max_retries"),
        require_llm=kwargs.get("require_llm"),
        source_class=kwargs.get("source_class"),
    )
    state_path = default_state_path(root, config.state_file, bool(kwargs.get("no_dedup", False)), backend=config.state_backend)
    kwargs.setdefault("feedback_output_root", root)
    kwargs.setdefault("feedback_store_path", root / ".hound" / "feedback.sqlite3")

    def _one(item: tuple[int, Path]) -> AnalysisRun:
        index, log_path = item
        run_id = f"run-{uuid4().hex[:12]}-{index:04d}"
        run_output = root / run_id
        document = analyze_log(log_path, run_output, state_path=state_path, _config=config, **kwargs)
        return AnalysisRun(run_id, log_path, run_output, document)

    if jobs > 1:
        with ThreadPoolExecutor(max_workers=jobs, thread_name_prefix="hound_analyze") as executor:
            runs = list(executor.map(_one, enumerate(logs)))
    else:
        runs = [_one(item) for item in enumerate(logs)]
    return runs


def has_ci_failure(runs: list[AnalysisRun]) -> bool:
    """Return whether completed analysis found a CI/CD failure."""
    return any(run.document.get("failure", {}).get("kind") != "unknown" for run in runs)
