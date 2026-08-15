from __future__ import annotations

import hashlib
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.increment8.admission import build_operational_admission_decision
from newsroom.increment8.closeout import (
    INCREMENT8_FINAL_CLOSEOUT_INVENTORY_DIGEST,
    INCREMENT8_FINAL_NON_EFFECTS,
    INCREMENT8_FINAL_REQUIREMENTS,
    INCREMENT8F_FINAL_CLOSEOUT_CASES,
    Increment8CloseoutLane,
    validate_increment8_closeout_inventory,
)
from newsroom.increment8.qualification_fixture import (
    FIXTURE_ADMISSION_OWNER_DIGEST,
    FIXTURE_DECISION_RECORDED_AT_DIGEST,
    execute_qualification_fixture,
)
from newsroom.tests.test_increment6g_closeout_receipt import (
    _clean_clone,
    _git,
    _RawReport,
    _target_properties,
)
from scripts.sdlc.emit_evidence import sha256_identity
from scripts.sdlc.increment8f_closeout_receipt import (
    BLOCKED_SCHEMA_VERSION,
    FINAL_SCHEMA_VERSION,
    Increment8FCloseoutReceiptError,
    build_final_receipt,
)
from scripts.sdlc.increment8f_signed_subjects import validate_signed_subjects


def _junit(
    path: Path,
    lane: Increment8CloseoutLane,
    properties: dict[str, str],
    *,
    failed: str | None = None,
) -> Path:
    suite = ET.Element("testsuite")
    for item in INCREMENT8F_FINAL_CLOSEOUT_CASES:
        if item.lane is not lane:
            continue
        owner, name = item.test_id.split("::", 1)
        case = ET.SubElement(suite, "testcase", classname=owner, name=name)
        if item.test_id == failed:
            ET.SubElement(case, "failure")
        if item.case_id == "S01_EXISTING_SERVICE":
            container = ET.SubElement(case, "properties")
            for key, value in properties.items():
                ET.SubElement(container, "property", name=key, value=value)
    path.write_bytes(ET.tostring(suite, encoding="utf-8", xml_declaration=True))
    return path


def _stubs(tmp_path: Path, repo: Path):
    head, tree = _git(repo, "HEAD"), _git(repo, "HEAD^{tree}")
    lanes = []
    transports = {}
    properties = _target_properties(head, tree)
    for lane_id, inventory_lane in (
        ("core", Increment8CloseoutLane.DETERMINISTIC),
        ("service", Increment8CloseoutLane.ACTUAL_NEO4J),
    ):
        artifact = tmp_path / lane_id
        artifact.mkdir()
        report = _junit(artifact / "report.xml", inventory_lane, properties)
        payload = report.read_bytes()
        replay = SimpleNamespace(
            head_sha=head,
            replay_identity="sha256:" + lane_id[0] * 64,
        )
        receipt = SimpleNamespace(
            envelope_identity="sha256:" + "e" * 64,
            evaluated_sha=head,
            evaluated_tree_sha=tree,
            raw_reports=(
                _RawReport(
                    "report.xml",
                    len(payload),
                    "sha256:" + hashlib.sha256(payload).hexdigest(),
                ),
            ),
            receipt_identity="sha256:" + "a" * 64,
            route=SimpleNamespace(selected_test_manifest_digest="sha256:" + "b" * 64),
        )
        lane = SimpleNamespace(
            lane_id=lane_id,
            lane_identity="sha256:" + "c" * 64,
            receipt=receipt,
            replay=replay,
        )
        lanes.append(lane)
        transports[lane_id] = SimpleNamespace(
            artifact_root=artifact,
            bundle=SimpleNamespace(transport_identity="sha256:" + "d" * 64),
            replay=replay,
        )
    return (
        SimpleNamespace(
            context=SimpleNamespace(evaluated_sha=head, evaluated_tree_sha=tree),
            decision_identity="sha256:" + "f" * 64,
            lanes=tuple(lanes),
            result="PASS",
        ),
        transports,
    )


def _patch(monkeypatch, decision, transports) -> None:
    monkeypatch.setattr(
        "scripts.sdlc.increment8f_closeout_receipt.load_contract",
        lambda _root: object(),
    )
    monkeypatch.setattr(
        "scripts.sdlc.increment8f_closeout_receipt.validate_shadow_decision",
        lambda _value, contract: decision,
    )
    monkeypatch.setattr(
        "scripts.sdlc.increment8f_closeout_receipt.load_verified_transport",
        lambda path: transports[Path(path).name],
    )
    monkeypatch.setattr(
        "scripts.sdlc.increment8f_closeout_receipt.corrective_gate_authorised",
        lambda _gate: True,
    )


def _admission_paths(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_REPOSITORY", "fol2/newsroom")
    monkeypatch.setenv(
        "GITHUB_SHA",
        subprocess.check_output(("git", "rev-parse", "HEAD"), text=True).strip(),
    )
    packet = tmp_path / "qualification-packet.json"
    decision = tmp_path / "operational-admission-decision.json"
    qualification_packet = execute_qualification_fixture(
        tmp_path / "qualification-workspace"
    )
    admission = build_operational_admission_decision(
        packet=qualification_packet,
        owner_identity_digest=FIXTURE_ADMISSION_OWNER_DIGEST,
        decision_recorded_at_digest=FIXTURE_DECISION_RECORDED_AT_DIGEST,
    )
    packet.write_bytes(qualification_packet.canonical_bytes)
    decision.write_bytes(admission.canonical_bytes)
    return packet, decision


def test_non_main_checkout_emits_no_final_closeout_claim(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_REF", "refs/pull/484/merge")
    repo = _clean_clone(tmp_path)
    receipt = build_final_receipt(
        repo_root=repo,
        core_transport_bundle_root=tmp_path / "absent-core",
        service_transport_bundle_root=tmp_path / "absent-service",
        decision_path=tmp_path / "absent-decision.json",
        qualification_packet_path=tmp_path / "absent-packet.json",
        operational_admission_decision_path=tmp_path / "absent-admission.json",
    )
    assert receipt["schema_version"] == BLOCKED_SCHEMA_VERSION
    assert receipt["status"] == "BLOCKED"
    assert receipt["blocking_issues"] == []


def test_receipt_binds_exact_lanes_inventory_service_and_self_hash(
    tmp_path, monkeypatch
) -> None:
    repo = _clean_clone(tmp_path)
    decision, transports = _stubs(tmp_path, repo)
    _patch(monkeypatch, decision, transports)
    decision_path = tmp_path / "decision.json"
    decision_path.write_text("{}", encoding="utf-8")
    packet_path, admission_path = _admission_paths(tmp_path, monkeypatch)
    receipt = build_final_receipt(
        repo_root=repo,
        core_transport_bundle_root=tmp_path / "core",
        service_transport_bundle_root=tmp_path / "service",
        decision_path=decision_path,
        qualification_packet_path=packet_path,
        operational_admission_decision_path=admission_path,
    )
    assert receipt["schema_version"] == FINAL_SCHEMA_VERSION
    assert receipt["inventory"]["digest"] == (
        INCREMENT8_FINAL_CLOSEOUT_INVENTORY_DIGEST
    )
    assert len(receipt["selected_cases"]) == len(INCREMENT8F_FINAL_CLOSEOUT_CASES)
    assert {lane["lane_id"] for lane in receipt["lanes"]} == {"core", "service"}
    unsigned = dict(receipt)
    assert unsigned.pop("receipt_identity") == sha256_identity(unsigned)
    receipt_path = tmp_path / "increment8-receipt.json"
    receipt_path.write_bytes(canonical_json_bytes(receipt) + b"\n")
    validate_signed_subjects(
        repo_root=repo,
        packet_path=packet_path,
        decision_path=admission_path,
        receipt_path=receipt_path,
    )


def test_receipt_rejects_a_failed_selected_case(tmp_path, monkeypatch) -> None:
    repo = _clean_clone(tmp_path)
    decision, transports = _stubs(tmp_path, repo)
    core = tmp_path / "core" / "report.xml"
    target = INCREMENT8F_FINAL_CLOSEOUT_CASES[0].test_id
    _junit(core, Increment8CloseoutLane.DETERMINISTIC, {}, failed=target)
    payload = core.read_bytes()
    raw = transports["core"].replay
    lane = next(item for item in decision.lanes if item.lane_id == "core")
    lane.receipt.raw_reports = (  # type: ignore[misc]
        _RawReport(
            "report.xml",
            len(payload),
            "sha256:" + hashlib.sha256(payload).hexdigest(),
        ),
    )
    assert raw.head_sha == _git(repo, "HEAD")
    _patch(monkeypatch, decision, transports)
    decision_path = tmp_path / "decision.json"
    decision_path.write_text("{}", encoding="utf-8")
    packet_path, admission_path = _admission_paths(tmp_path, monkeypatch)
    with pytest.raises(Increment8FCloseoutReceiptError, match="not_passed"):
        build_final_receipt(
            repo_root=repo,
            core_transport_bundle_root=tmp_path / "core",
            service_transport_bundle_root=tmp_path / "service",
            decision_path=decision_path,
            qualification_packet_path=packet_path,
            operational_admission_decision_path=admission_path,
        )


def test_increment8_closeout_inventory_and_contract_are_exact() -> None:
    validate_increment8_closeout_inventory()
    assert len(INCREMENT8F_FINAL_CLOSEOUT_CASES) == 13
    assert {
        case.requirement for case in INCREMENT8F_FINAL_CLOSEOUT_CASES
    } == INCREMENT8_FINAL_REQUIREMENTS
    assert INCREMENT8_FINAL_NON_EFFECTS == tuple(sorted(INCREMENT8_FINAL_NON_EFFECTS))
    assert FINAL_SCHEMA_VERSION == "newsroom.increment8.closeout-receipt.v2"
