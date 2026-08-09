from __future__ import annotations

import hashlib
import json
import subprocess
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from newsroom.increment5.final_closeout import (
    INCREMENT5E2_FINAL_CLOSEOUT_CASES,
    INCREMENT5E2_FINAL_CLOSEOUT_INVENTORY_DIGEST,
    INCREMENT5E2_FINAL_NON_EFFECTS,
    FinalCloseoutLane,
)
from newsroom.increment5.retrieval_qualification import (
    QUALIFICATION_CORPUS,
    QUALIFICATION_TARGET,
    RetrievalQualificationEvaluator,
    build_qualification_epoch,
    run_fixture_qualification,
)
from newsroom.projection.neo4j import (
    NEO4J_B2_DRIVER_VERSION,
    NEO4J_B2_IMAGE,
    NEO4J_B2_SERVER_VERSION,
)
from scripts.sdlc.emit_evidence import sha256_identity
from scripts.sdlc.increment5e2_closeout_receipt import (
    Increment5E2CloseoutReceiptError,
    _parse_junit,
    build_actual_service_receipt,
    build_final_receipt,
)
from scripts.sdlc.workflow_lane import service_compatibility_digest

ROOT = Path(__file__).resolve().parents[2]


def _tree() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True
    ).strip()


@pytest.fixture(scope="module")
def target_properties() -> dict[str, str]:
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    tree = _tree()
    epoch = build_qualification_epoch(
        target=QUALIFICATION_TARGET,
        corpus=QUALIFICATION_CORPUS,
        code_tree_sha=tree,
    )
    report = RetrievalQualificationEvaluator().evaluate(
        run_id=str(uuid.uuid5(uuid.NAMESPACE_URL, epoch.epoch_digest)),
        target=QUALIFICATION_TARGET,
        corpus=QUALIFICATION_CORPUS,
        epoch=epoch,
        code_tree_sha=tree,
        observations=run_fixture_qualification(
            target=QUALIFICATION_TARGET,
            corpus=QUALIFICATION_CORPUS,
        ),
        started_at="2026-08-08T20:00:00Z",
        completed_at="2026-08-08T20:01:00Z",
    )
    return {
        "increment5e2_epoch_digest": epoch.epoch_digest,
        "increment5e2_epoch_json": json.dumps(
            epoch.canonical_value(), sort_keys=True, separators=(",", ":")
        ),
        "increment5e2_report_digest": report.report_digest,
        "increment5e2_report_json": report.canonical_bytes.decode("utf-8"),
        "increment5e2_closeout_inventory_digest": (
            INCREMENT5E2_FINAL_CLOSEOUT_INVENTORY_DIGEST
        ),
        "increment5e2_closeout_case_count": str(len(INCREMENT5E2_FINAL_CLOSEOUT_CASES)),
        "increment5e2_non_effects": ",".join(INCREMENT5E2_FINAL_NON_EFFECTS),
        "increment5e2_source_head_sha": head,
        "increment5e2_source_tree_sha": tree,
        "increment5e2_neo4j_image": NEO4J_B2_IMAGE,
        "increment5e2_neo4j_server_version": NEO4J_B2_SERVER_VERSION,
        "increment5e2_neo4j_edition": "community",
        "increment5e2_neo4j_driver_version": NEO4J_B2_DRIVER_VERSION,
        "increment5e2_neo4j_database": "neo4j",
        "increment5e2_neo4j_projector_username": "newsroom_projector",
        "increment5e2_service_compatibility_digest": service_compatibility_digest(),
    }


def _junit(
    path: Path,
    lane: FinalCloseoutLane,
    properties: dict[str, str],
    *,
    omitted: str | None = None,
    skipped: str | None = None,
) -> Path:
    suite = ET.Element("testsuite")
    for case in INCREMENT5E2_FINAL_CLOSEOUT_CASES:
        if case.lane is not lane or case.test_id == omitted:
            continue
        owner, name = case.test_id.split("::", 1)
        element = ET.SubElement(suite, "testcase", classname=owner, name=name)
        if case.test_id == skipped:
            ET.SubElement(element, "skipped")
        if name == "test_actual_service_increment5e2_target_and_report":
            container = ET.SubElement(element, "properties")
            for key, value in properties.items():
                ET.SubElement(container, "property", name=key, value=value)
    path.write_bytes(ET.tostring(suite, encoding="utf-8", xml_declaration=True))
    return path


def test_actual_service_receipt_binds_exact_report_and_semantics(
    tmp_path: Path, target_properties: dict[str, str]
) -> None:
    report = _junit(
        tmp_path / "service.xml",
        FinalCloseoutLane.ACTUAL_NEO4J,
        target_properties,
    )

    receipt = build_actual_service_receipt(repo_root=ROOT, service_junit_report=report)

    expected_digest = "sha256:" + hashlib.sha256(report.read_bytes()).hexdigest()
    assert receipt["junit_report"]["digest"] == expected_digest
    assert len(receipt["selected_cases"]) == len(
        [
            case
            for case in INCREMENT5E2_FINAL_CLOSEOUT_CASES
            if case.lane is FinalCloseoutLane.ACTUAL_NEO4J
        ]
    )
    assert receipt["service"]["compatibility_digest"] == (
        service_compatibility_digest()
    )
    unsigned = dict(receipt)
    assert unsigned.pop("receipt_identity") == sha256_identity(unsigned)


def test_actual_service_rejects_missing_skipped_and_tampered_properties(
    tmp_path: Path, target_properties: dict[str, str]
) -> None:
    cases = [
        case
        for case in INCREMENT5E2_FINAL_CLOSEOUT_CASES
        if case.lane is FinalCloseoutLane.ACTUAL_NEO4J
    ]
    missing = _junit(
        tmp_path / "missing.xml",
        FinalCloseoutLane.ACTUAL_NEO4J,
        target_properties,
        omitted=cases[0].test_id,
    )
    with pytest.raises(Increment5E2CloseoutReceiptError, match="selected_test_missing"):
        build_actual_service_receipt(repo_root=ROOT, service_junit_report=missing)

    skipped = _junit(
        tmp_path / "skipped.xml",
        FinalCloseoutLane.ACTUAL_NEO4J,
        target_properties,
        skipped=cases[0].test_id,
    )
    with pytest.raises(Increment5E2CloseoutReceiptError, match="not_passed"):
        build_actual_service_receipt(repo_root=ROOT, service_junit_report=skipped)

    changed = dict(target_properties)
    changed["increment5e2_epoch_digest"] = "sha256:" + "0" * 64
    tampered = _junit(
        tmp_path / "tampered.xml",
        FinalCloseoutLane.ACTUAL_NEO4J,
        changed,
    )
    with pytest.raises(Increment5E2CloseoutReceiptError, match="epoch_identity"):
        build_actual_service_receipt(repo_root=ROOT, service_junit_report=tampered)

    unexpected = dict(target_properties)
    unexpected["increment5e2_unreviewed_property"] = "unexpected"
    extra = _junit(
        tmp_path / "extra.xml",
        FinalCloseoutLane.ACTUAL_NEO4J,
        unexpected,
    )
    with pytest.raises(Increment5E2CloseoutReceiptError, match="target_properties"):
        build_actual_service_receipt(repo_root=ROOT, service_junit_report=extra)


@pytest.mark.parametrize("outcome", ("failure", "error"))
def test_actual_service_rejects_unselected_failure_or_error(
    tmp_path: Path,
    target_properties: dict[str, str],
    outcome: str,
) -> None:
    report = _junit(
        tmp_path / f"extra-{outcome}.xml",
        FinalCloseoutLane.ACTUAL_NEO4J,
        target_properties,
    )
    suite = ET.fromstring(report.read_bytes())
    extra = ET.SubElement(
        suite,
        "testcase",
        classname="newsroom.tests.test_unselected",
        name="test_extra",
    )
    ET.SubElement(extra, outcome)
    report.write_bytes(ET.tostring(suite, encoding="utf-8", xml_declaration=True))

    with pytest.raises(
        Increment5E2CloseoutReceiptError,
        match="unselected_test_not_passed",
    ):
        build_actual_service_receipt(repo_root=ROOT, service_junit_report=report)


@pytest.mark.parametrize(
    ("property_name", "property_value", "expected_error"),
    (
        ("increment5e2_source_head_sha", "0" * 40, "service_identity"),
        ("increment5e2_source_tree_sha", "0" * 40, "service_identity"),
        ("increment5e2_neo4j_image", "neo4j:changed", "service_identity"),
        ("increment5e2_closeout_case_count", "0", "closeout_inventory"),
    ),
)
def test_actual_service_rejects_changed_checkout_service_or_inventory_identity(
    tmp_path: Path,
    target_properties: dict[str, str],
    property_name: str,
    property_value: str,
    expected_error: str,
) -> None:
    changed = dict(target_properties)
    changed[property_name] = property_value
    report = _junit(
        tmp_path / f"{property_name}.xml",
        FinalCloseoutLane.ACTUAL_NEO4J,
        changed,
    )

    with pytest.raises(Increment5E2CloseoutReceiptError, match=expected_error):
        build_actual_service_receipt(repo_root=ROOT, service_junit_report=report)


def test_actual_service_rejects_self_consistent_forged_qualification_report(
    tmp_path: Path, target_properties: dict[str, str]
) -> None:
    forged_value = json.loads(target_properties["increment5e2_report_json"])
    forged_value.update(
        {
            "target_manifest_digest": "sha256:" + "1" * 64,
            "corpus_spec_digest": "sha256:" + "2" * 64,
            "dataset_manifest_digest": "sha256:" + "3" * 64,
            "vector_quality_scope": "FABRICATED_VECTOR_SCOPE",
        }
    )
    for name in (
        "systems",
        "mandatory_families",
        "required_slices",
        "triage_error_classes",
        "branch_contributions",
    ):
        forged_value["metrics"][name] = []
    evidence = {
        "metrics": forged_value["metrics"],
        "blockers": forged_value["blockers"],
        "observation_count": forged_value["observation_count"],
        "expected_observation_count": forged_value["expected_observation_count"],
    }
    evidence_payload = json.dumps(
        evidence, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    evidence_digest = "sha256:" + hashlib.sha256(evidence_payload).hexdigest()
    forged_value["report_id"] = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            "|".join(
                (
                    forged_value["run_id"],
                    forged_value["epoch_digest"],
                    forged_value["decision"],
                    forged_value["reason"],
                    evidence_digest,
                )
            ),
        )
    )
    forged_text = json.dumps(forged_value, sort_keys=True, separators=(",", ":"))
    forged = dict(target_properties)
    forged["increment5e2_report_json"] = forged_text
    forged["increment5e2_report_digest"] = (
        "sha256:" + hashlib.sha256(forged_text.encode("utf-8")).hexdigest()
    )
    report = _junit(
        tmp_path / "forged-report.xml",
        FinalCloseoutLane.ACTUAL_NEO4J,
        forged,
    )

    with pytest.raises(
        Increment5E2CloseoutReceiptError,
        match="qualification_report_semantics",
    ):
        build_actual_service_receipt(repo_root=ROOT, service_junit_report=report)


def test_junit_parser_preserves_exact_parameter_node_ids(tmp_path: Path) -> None:
    path = tmp_path / "parameter.xml"
    path.write_text(
        '<testsuite><testcase classname="newsroom.tests.test_example" '
        'name="test_exact[node-a]"/></testsuite>',
        encoding="utf-8",
    )

    parsed = _parse_junit(path)

    assert parsed.cases[0].test_id == (
        "newsroom.tests.test_example::test_exact[node-a]"
    )


def test_junit_parser_accepts_bounded_long_unselected_parameter_id(
    tmp_path: Path,
) -> None:
    parameter = "x" * (16 * 1024)
    path = tmp_path / "long-parameter.xml"
    path.write_text(
        '<testsuite><testcase classname="newsroom.tests.test_example" '
        f'name="test_exact[{parameter}]"/></testsuite>',
        encoding="utf-8",
    )

    parsed = _parse_junit(path)

    assert parsed.cases[0].test_id.endswith(f"test_exact[{parameter}]")


def test_junit_parser_rejects_unbounded_parameter_id(tmp_path: Path) -> None:
    parameter = "x" * (64 * 1024)
    path = tmp_path / "unbounded-parameter.xml"
    path.write_text(
        '<testsuite><testcase classname="newsroom.tests.test_example" '
        f'name="test_exact[{parameter}]"/></testsuite>',
        encoding="utf-8",
    )

    with pytest.raises(Increment5E2CloseoutReceiptError, match="test_name"):
        _parse_junit(path)


def test_junit_parser_rejects_utf16_dtd_and_entity(tmp_path: Path) -> None:
    path = tmp_path / "utf16-entity.xml"
    path.write_bytes(
        (
            '<!DOCTYPE testsuite [<!ENTITY owner "newsroom.tests.test_example">]>'
            '<testsuite><testcase classname="&owner;" name="test_exact"/>'
            "</testsuite>"
        ).encode("utf-16")
    )

    with pytest.raises(
        Increment5E2CloseoutReceiptError,
        match="junit_xml_encoding",
    ):
        _parse_junit(path)


@dataclass(frozen=True)
class _RawReport:
    path: str
    size_bytes: int
    digest: str


def test_final_receipt_binds_validated_decision_transports_and_both_lanes(
    tmp_path: Path,
    target_properties: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    tree = _tree()
    lane_inputs = {}
    lanes = []
    for lane_id, inventory_lane in (
        ("core", FinalCloseoutLane.DETERMINISTIC),
        ("service", FinalCloseoutLane.ACTUAL_NEO4J),
    ):
        artifact = tmp_path / lane_id
        artifact.mkdir()
        report_path = _junit(artifact / "report.xml", inventory_lane, target_properties)
        payload = report_path.read_bytes()
        replay = SimpleNamespace(
            head_sha=head, replay_identity=f"sha256:{lane_id[0] * 64}"
        )
        raw = _RawReport(
            "report.xml",
            len(payload),
            "sha256:" + hashlib.sha256(payload).hexdigest(),
        )
        receipt = SimpleNamespace(
            evaluated_sha=head,
            evaluated_tree_sha=tree,
            raw_reports=(raw,),
            route=SimpleNamespace(selected_test_manifest_digest="sha256:" + "a" * 64),
            receipt_identity="sha256:" + ("b" if lane_id == "core" else "c") * 64,
            envelope_identity="sha256:" + ("d" if lane_id == "core" else "e") * 64,
        )
        lane = SimpleNamespace(
            lane_id=lane_id,
            replay=replay,
            receipt=receipt,
            lane_identity="sha256:" + ("f" if lane_id == "core" else "9") * 64,
        )
        verified = SimpleNamespace(
            replay=replay,
            artifact_root=artifact,
            bundle=SimpleNamespace(
                transport_identity="sha256:" + ("1" if lane_id == "core" else "2") * 64
            ),
        )
        lanes.append(lane)
        lane_inputs[lane_id] = verified
    decision = SimpleNamespace(
        result="PASS",
        lanes=tuple(lanes),
        context=SimpleNamespace(evaluated_sha=head, evaluated_tree_sha=tree),
        decision_identity="sha256:" + "3" * 64,
    )
    monkeypatch.setattr(
        "scripts.sdlc.increment5e2_closeout_receipt.load_contract",
        lambda _root: object(),
    )
    monkeypatch.setattr(
        "scripts.sdlc.increment5e2_closeout_receipt.validate_shadow_decision",
        lambda _value, contract: decision,
    )
    monkeypatch.setattr(
        "scripts.sdlc.increment5e2_closeout_receipt.load_verified_transport",
        lambda path: lane_inputs[Path(path).name],
    )
    decision_path = tmp_path / "decision.json"
    decision_path.write_text("{}", encoding="utf-8")

    receipt = build_final_receipt(
        repo_root=ROOT,
        core_transport_bundle_root=tmp_path / "core",
        service_transport_bundle_root=tmp_path / "service",
        decision_path=decision_path,
    )

    assert receipt["decision_identity"] == decision.decision_identity
    assert len(receipt["selected_cases"]) == len(INCREMENT5E2_FINAL_CLOSEOUT_CASES)
    assert {lane["lane_id"] for lane in receipt["lanes"]} == {"core", "service"}
    assert receipt["inventory"]["digest"] == (
        INCREMENT5E2_FINAL_CLOSEOUT_INVENTORY_DIGEST
    )
