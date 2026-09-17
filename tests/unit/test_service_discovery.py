from pathlib import Path

from hound.service import discover_artifacts


def test_discover_artifacts_recurses_and_prunes_ignored_directories(tmp_path: Path):
    artifact = tmp_path / "reports" / "nested" / "failure.log"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("failed", encoding="utf-8")
    ignored = tmp_path / ".venv" / "package" / "failure.log"
    ignored.parent.mkdir(parents=True)
    ignored.write_text("ignored", encoding="utf-8")

    assert discover_artifacts(tmp_path) == [artifact]


def test_discover_artifacts_skips_collector_sidecars(tmp_path: Path):
    log = tmp_path / "captured.log"
    sidecar = tmp_path / "captured.json"
    log.write_text("failed", encoding="utf-8")
    sidecar.write_text("{}", encoding="utf-8")

    assert discover_artifacts(tmp_path) == [log]


def test_discover_artifacts_honors_limit(tmp_path: Path):
    for index in range(3):
        (tmp_path / f"{index}.log").write_text("failed", encoding="utf-8")

    assert len(discover_artifacts(tmp_path, limit=2)) == 2


def test_discover_artifacts_rejects_project_manifests(tmp_path: Path):
    (tmp_path / "package.json").write_text('{"scripts": {"test": "pytest"}}', encoding="utf-8")
    (tmp_path / "pom.xml").write_text("<project/>", encoding="utf-8")

    assert discover_artifacts(tmp_path) == []


def test_discover_artifacts_only_parses_structured_files_with_report_hints(tmp_path: Path, monkeypatch):
    from hound.ingest import structured

    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")
    report = tmp_path / "test-results" / "failed.json"
    report.parent.mkdir()
    report.write_text('{"status": "failed", "name": "case"}', encoding="utf-8")
    parsed = []
    original = structured.parse_structured_artifact

    def tracked(path):
        parsed.append(path)
        return original(path)

    monkeypatch.setattr(structured, "parse_structured_artifact", tracked)

    assert discover_artifacts(tmp_path) == [report]
    assert parsed == [report]


def test_discover_workspace_skips_generated_results_and_state(tmp_path: Path):
    workspace = tmp_path / ".hound"
    capture = workspace / "captures" / "failure.log"
    result = workspace / "results" / "run-1" / "failure.log"
    state = workspace / "state" / "failure.log"
    for path in (capture, result, state):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("failed", encoding="utf-8")

    assert discover_artifacts(workspace) == [capture]


def test_discover_project_keeps_captures_but_skips_hound_outputs(tmp_path: Path):
    capture = tmp_path / ".hound" / "captures" / "command.log"
    result = tmp_path / ".hound" / "results" / "run-1" / "copied.log"
    state = tmp_path / ".hound" / "state" / "database.log"
    for path in (capture, result, state):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("failed", encoding="utf-8")

    assert discover_artifacts(tmp_path) == [capture]
