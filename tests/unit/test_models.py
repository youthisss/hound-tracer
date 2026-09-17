from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from hound.analyze.fallback import build_root_cause
from hound.formatters import format_document
from hound.models import SCHEMA_VERSION, Triage, build_doc, build_evidence_items, validate
from hound.output.report import render_md
from hound.output.tickets import build_ticket
from hound.tui import _overview_text
from tests.conftest import make_artifacts


GOLDEN = Path(__file__).resolve().parents[1] / "golden"


@pytest.mark.parametrize("name", ["rca-v1.4.json", "rca-v2.0.json"])
def test_golden_documents_are_readable(name):
    doc = json.loads((GOLDEN / name).read_text(encoding="utf-8"))
    validate(doc)
    assert format_document(doc, "markdown").startswith("# Hound Tracer report")
    assert render_md(doc).startswith("# Root Cause Analysis Report")


def test_current_writer_emits_resolved_structured_evidence():
    artifacts = make_artifacts("pytest_fail.log")
    root_cause = build_root_cause(artifacts)
    triage = Triage(component="tests", dedup_key="a" * 64)
    ticket = build_ticket(artifacts, root_cause, triage)
    doc = build_doc(artifacts, root_cause, triage, ticket, "2026-01-01T00:00:00Z")

    validate(doc)
    assert doc["schema_version"] == SCHEMA_VERSION == "2.0"
    evidence_ids = {item["id"] for item in doc["analysis"]["evidence"]}
    hypothesis = doc["analysis"]["hypotheses"][0]
    assert hypothesis["support_status"] == "supported"
    assert set(hypothesis["supporting_evidence_refs"]).issubset(evidence_ids)
    assert 0.0 <= hypothesis["confidence"]["score"] <= 1.0
    assert hypothesis["confidence"]["reasons"]
    assert "`ev-001`" in render_md(doc)
    assert "`ev-001`" in ticket.body_md
    assert "ev-001" in _overview_text(doc)


def test_overview_identifies_the_viewed_artifact():
    overview = _overview_text({
        "meta": {"log_file": "C:/ci/logs/vitest_fail.log"},
        "failure": {},
        "root_cause": {},
        "triage": {},
    })

    assert "artifact" in overview
    assert "vitest_fail.log" in overview


def test_evidence_ids_do_not_derive_from_sensitive_values():
    artifacts = make_artifacts("pytest_fail.log")
    artifacts.message = "customer-secret-value"
    evidence = build_evidence_items(artifacts, "2026-01-01T00:00:00Z")
    assert [item["id"] for item in evidence] == [f"ev-{index:03d}" for index in range(1, len(evidence) + 1)]
    assert all("customer-secret-value" not in item["id"] for item in evidence)
    assert all(item["provenance"]["observed_at"] == "2026-01-01T00:00:00Z" for item in evidence)


def test_validator_rejects_unresolved_or_vacuously_supported_hypothesis():
    doc = json.loads((GOLDEN / "rca-v2.0.json").read_text(encoding="utf-8"))
    unresolved = copy.deepcopy(doc)
    unresolved["analysis"]["hypotheses"][0]["supporting_evidence_refs"] = ["ev-999"]
    with pytest.raises(ValueError, match="unresolved supporting"):
        validate(unresolved)

    vacuous = copy.deepcopy(doc)
    vacuous["analysis"]["hypotheses"][0]["support_status"] = "supported"
    with pytest.raises(ValueError, match="must reference evidence"):
        validate(vacuous)


def test_validator_closes_deployment_fields_and_customer_impact_enum():
    artifacts = make_artifacts("pytest_fail.log")
    root_cause = build_root_cause(artifacts)
    doc = build_doc(
        artifacts,
        root_cause,
        Triage(component="tests", dedup_key="a" * 64),
        build_ticket(artifacts, root_cause, Triage(component="tests", dedup_key="a" * 64)),
        "2026-01-01T00:00:00Z",
    )

    extra_field = copy.deepcopy(doc)
    extra_field["context"]["deployment"]["unexpected"] = "must reject"
    with pytest.raises(ValueError, match="deployment contains unsupported fields"):
        validate(extra_field)

    invalid_impact = copy.deepcopy(doc)
    invalid_impact["context"]["deployment"]["customer_impact"] = "certain"
    with pytest.raises(ValueError, match="customer_impact invalid"):
        validate(invalid_impact)


def test_validator_rejects_unknown_current_run_context_fields():
    doc = json.loads((GOLDEN / "rca-v2.0.json").read_text(encoding="utf-8"))
    doc["context"]["run"]["unmodeled_field"] = "must reject"

    with pytest.raises(ValueError, match="run contains unsupported fields"):
        validate(doc)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda doc: doc["analysis"]["evidence"][0].__setitem__("id", "ev-forged"), "evidence.id invalid"),
        (lambda doc: doc["analysis"]["evidence"][0]["provenance"].__setitem__("source_type", "untrusted"), "provenance.source_type invalid"),
        (lambda doc: doc["analysis"]["evidence"][0].__setitem__("value", float("nan")), "must contain a finite number"),
        (lambda doc: doc["analysis"]["hypotheses"][0].__setitem__("statement", "forged primary cause"), "primary hypothesis must match"),
    ],
)
def test_validator_rejects_forged_or_non_finite_analysis_values(mutation, message):
    artifacts = make_artifacts("pytest_fail.log")
    root_cause = build_root_cause(artifacts)
    doc = build_doc(
        artifacts,
        root_cause,
        Triage(component="tests", dedup_key="a" * 64),
        build_ticket(artifacts, root_cause, Triage(component="tests", dedup_key="a" * 64)),
        "2026-01-01T00:00:00Z",
    )
    assert doc["analysis"]["evidence"]
    mutation(doc)
    with pytest.raises(ValueError, match=message):
        validate(doc)


def test_schema_document_publishes_v2_analysis_contract():
    schema = json.loads(Path("docs/schema/rca-v2.0.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["schema_version"] == {"const": "2.0"}
    assert schema["additionalProperties"] is False
    for section in ("meta", "failure", "context", "root_cause", "triage", "ticket"):
        assert "$ref" in schema["properties"][section]
    assert {"observed_facts", "evidence", "hypotheses"}.issubset(
        schema["properties"]["analysis"]["required"]
    )


def test_current_writer_matches_published_json_schema():
    schema = json.loads(Path("docs/schema/rca-v2.0.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    artifacts = make_artifacts("pytest_fail.log")
    root_cause = build_root_cause(artifacts)
    triage = Triage(component="tests", dedup_key="a" * 64)
    ticket = build_ticket(artifacts, root_cause, triage)
    doc = build_doc(artifacts, root_cause, triage, ticket, "2026-01-01T00:00:00Z")
    Draft202012Validator(schema).validate(doc)
