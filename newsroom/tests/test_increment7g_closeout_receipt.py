from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

from newsroom.increment7.closeout import (
    INCREMENT7_FINAL_CLOSEOUT_INVENTORY_DIGEST,
    INCREMENT7G_FINAL_CLOSEOUT_CASES,
    Increment7CloseoutLane,
)
from newsroom.authority.migrations import EXPECTED_MIGRATION_HISTORY
from newsroom.tests.test_increment6g_closeout_receipt import (
    _RawReport,
    _clean_clone,
    _git,
    _target_properties,
)
from scripts.sdlc.emit_evidence import sha256_identity
from scripts.sdlc.increment7g_closeout_receipt import (
    FINAL_SCHEMA_VERSION,
    Increment7GCloseoutReceiptError,
    build_final_receipt,
)


def _junit(
    path: Path,
    lane: Increment7CloseoutLane,
    properties: dict[str, str],
    *,
    failed: str | None = None,
) -> Path:
    suite = ET.Element("testsuite")
    for item in INCREMENT7G_FINAL_CLOSEOUT_CASES:
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
        ("core", Increment7CloseoutLane.DETERMINISTIC),
        ("service", Increment7CloseoutLane.ACTUAL_NEO4J),
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
        "scripts.sdlc.increment7g_closeout_receipt.load_contract",
        lambda _root: object(),
    )
    monkeypatch.setattr(
        "scripts.sdlc.increment7g_closeout_receipt.validate_shadow_decision",
        lambda _value, contract: decision,
    )
    monkeypatch.setattr(
        "scripts.sdlc.increment7g_closeout_receipt.load_verified_transport",
        lambda path: transports[Path(path).name],
    )


def test_receipt_binds_exact_lanes_inventory_service_and_self_hash(
    tmp_path, monkeypatch
) -> None:
    repo = _clean_clone(tmp_path)
    decision, transports = _stubs(tmp_path, repo)
    _patch(monkeypatch, decision, transports)
    decision_path = tmp_path / "decision.json"
    decision_path.write_text("{}", encoding="utf-8")
    receipt = build_final_receipt(
        repo_root=repo,
        core_transport_bundle_root=tmp_path / "core",
        service_transport_bundle_root=tmp_path / "service",
        decision_path=decision_path,
    )
    assert receipt["schema_version"] == FINAL_SCHEMA_VERSION
    assert receipt["inventory"]["digest"] == (
        INCREMENT7_FINAL_CLOSEOUT_INVENTORY_DIGEST
    )
    assert len(receipt["selected_cases"]) == len(INCREMENT7G_FINAL_CLOSEOUT_CASES)
    assert {lane["lane_id"] for lane in receipt["lanes"]} == {"core", "service"}
    unsigned = dict(receipt)
    assert unsigned.pop("receipt_identity") == sha256_identity(unsigned)


def test_receipt_rejects_a_failed_selected_case(tmp_path, monkeypatch) -> None:
    repo = _clean_clone(tmp_path)
    decision, transports = _stubs(tmp_path, repo)
    core = tmp_path / "core" / "report.xml"
    target = INCREMENT7G_FINAL_CLOSEOUT_CASES[0].test_id
    _junit(core, Increment7CloseoutLane.DETERMINISTIC, {}, failed=target)
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
    with pytest.raises(Increment7GCloseoutReceiptError, match="not_passed"):
        build_final_receipt(
            repo_root=repo,
            core_transport_bundle_root=tmp_path / "core",
            service_transport_bundle_root=tmp_path / "service",
            decision_path=decision_path,
        )


def test_receipt_preserves_the_v29_prefix_after_a_future_migration(
    monkeypatch,
) -> None:
    import scripts.sdlc.increment7g_closeout_receipt as receipt_module

    monkeypatch.setattr(receipt_module, "SCHEMA_VERSION", 30)
    monkeypatch.setattr(
        receipt_module,
        "EXPECTED_MIGRATION_HISTORY",
        (*EXPECTED_MIGRATION_HISTORY, (30, "future_authorised", "sha256:x")),
    )
    inventory = receipt_module._inventory()
    assert inventory["schema_version"] == 29
    assert inventory["digest"] == INCREMENT7_FINAL_CLOSEOUT_INVENTORY_DIGEST
