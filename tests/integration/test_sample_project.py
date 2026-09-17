import json
from pathlib import Path
import shutil
import subprocess
import sys

from hound.qa.coverage import parse_coverage_artifact
from hound.qa.gate import evaluate_gate, load_gate_policy
from hound.qa.normalize import import_artifact
from hound.qa.sarif import parse_sarif_artifact
from hound.service import analyze_directory, discover_artifacts


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sample-project"


def _copy_project(tmp_path: Path) -> Path:
    project = tmp_path / "sample-project"
    shutil.copytree(FIXTURE, project)
    return project


def test_sample_project_supports_rca_batch_and_dedup(tmp_path: Path) -> None:
    project = _copy_project(tmp_path)
    completed = subprocess.run(
        [sys.executable, "scripts/run_checks.py", "test"],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 1

    artifacts = discover_artifacts(project)
    assert {path.name for path in artifacts} >= {
        "application.log", "junit.xml", "test-report.json", "security.sarif"
    }
    runs = analyze_directory(project, tmp_path / "output", offline=True, jobs=2)
    assert runs
    assert all((run.output_dir / "report.json").is_file() for run in runs)
    assert all((run.output_dir / "ticket.md").is_file() for run in runs)


def test_sample_project_supports_history_coverage_sarif_and_gate(tmp_path: Path) -> None:
    project = _copy_project(tmp_path)
    subprocess.run(
        [sys.executable, "scripts/run_checks.py", "artifacts"],
        cwd=project,
        check=True,
        capture_output=True,
    )

    junit = import_artifact(project / "test-results" / "junit.xml", "sample", "", "", "")
    passing = import_artifact(project / "test-results" / "junit-pass.xml", "sample-pass", "", "", "")
    flaky = import_artifact(project / "test-results" / "junit-flaky.xml", "sample-flaky", "", "", "")
    assert junit and passing and flaky

    coverage = parse_coverage_artifact(project / "reports" / "coverage.xml")
    sarif = parse_sarif_artifact(project / "reports" / "security.sarif")
    assert coverage is not None and coverage.line_rate == 0.5
    assert sarif is not None and sarif.warning_count == 1

    policy = load_gate_policy(project / "quality.yml")
    gate = evaluate_gate(policy, [], coverage, {"src/calculator.py": [1, 2]}, sarif)
    payload = gate.to_dict()
    assert payload["policy_outcome"] == "block"
    assert {reason["rule"] for reason in payload["reasons"]} >= {
        "history_evidence", "sarif_warning", "changed_line_coverage"
    }
    json.dumps(payload)
