from __future__ import annotations

import hashlib
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.authority.migrations import (
    EXPECTED_MIGRATION_HISTORY,
)
from newsroom.increment6.closeout import (
    INCREMENT6G_FINAL_CLOSEOUT_CASES,
    INCREMENT6G_FINAL_CLOSEOUT_INVENTORY_DIGEST,
    INCREMENT6G_FINAL_NON_EFFECTS,
    INCREMENT6G_FINAL_SCHEMA_FINGERPRINT,
    INCREMENT6G_FINAL_SCHEMA_VERSION,
    Increment6CloseoutLane,
    increment6g_final_migration_history,
)
from newsroom.projection.neo4j import (
    NEO4J_B2_DRIVER_VERSION,
    NEO4J_B2_IMAGE,
    NEO4J_B2_SERVER_VERSION,
)
from scripts.sdlc.emit_evidence import sha256_identity
from scripts.sdlc.increment5e2_closeout_receipt import _parse_junit
from scripts.sdlc.increment6g_closeout_receipt import (
    Increment6GCloseoutReceiptError,
    _selected_cases,
    _service_identities,
    build_final_receipt,
)
from scripts.sdlc.workflow_lane import service_compatibility_digest

ROOT = Path(__file__).resolve().parents[2]


def _clean_clone(tmp_path: Path) -> Path:
    clone = tmp_path / "clean-repository"
    subprocess.run(
        ["git", "clone", "--quiet", "--no-hardlinks", str(ROOT), str(clone)],
        check=True,
    )
    return clone


def _git(root: Path, expression: str) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", expression], cwd=root, text=True
    ).strip()


def _target_properties(head: str, tree: str) -> dict[str, str]:
    return {
        "increment6g_closeout_case_count": str(len(INCREMENT6G_FINAL_CLOSEOUT_CASES)),
        "increment6g_closeout_inventory_digest": (
            INCREMENT6G_FINAL_CLOSEOUT_INVENTORY_DIGEST
        ),
        "increment6g_migration_history_json": canonical_json_bytes(
            [
                list(item)
                for item in increment6g_final_migration_history(
                    EXPECTED_MIGRATION_HISTORY
                )
            ]
        ).decode("utf-8"),
        "increment6g_neo4j_database": "neo4j",
        "increment6g_neo4j_driver_version": NEO4J_B2_DRIVER_VERSION,
        "increment6g_neo4j_edition": "community",
        "increment6g_neo4j_image": NEO4J_B2_IMAGE,
        "increment6g_neo4j_projector_username": "newsroom_projector",
        "increment6g_neo4j_server_version": NEO4J_B2_SERVER_VERSION,
        "increment6g_non_effects": ",".join(INCREMENT6G_FINAL_NON_EFFECTS),
        "increment6g_schema_fingerprint": INCREMENT6G_FINAL_SCHEMA_FINGERPRINT,
        "increment6g_schema_version": str(INCREMENT6G_FINAL_SCHEMA_VERSION),
        "increment6g_service_compatibility_digest": service_compatibility_digest(),
        "increment6g_source_head_sha": head,
        "increment6g_source_tree_sha": tree,
    }


def _junit(
    path: Path,
    lane: Increment6CloseoutLane,
    properties: dict[str, str],
    *,
    skipped: str | None = None,
) -> Path:
    suite = ET.Element("testsuite")
    for item in INCREMENT6G_FINAL_CLOSEOUT_CASES:
        if item.lane is not lane:
            continue
        owner, name = item.test_id.split("::", 1)
        case = ET.SubElement(suite, "testcase", classname=owner, name=name)
        if item.test_id == skipped:
            ET.SubElement(case, "skipped")
        if item.test_id.endswith(
            "::test_actual_service_increment6g_identity_and_closeout_inventory"
        ):
            container = ET.SubElement(case, "properties")
            for key, value in properties.items():
                ET.SubElement(container, "property", name=key, value=value)
    path.write_bytes(ET.tostring(suite, encoding="utf-8", xml_declaration=True))
    return path


@dataclass(frozen=True)
class _RawReport:
    path: str
    size_bytes: int
    digest: str


def _final_stubs(
    tmp_path: Path, repo: Path
) -> tuple[SimpleNamespace, dict[str, SimpleNamespace]]:
    head, tree = _git(repo, "HEAD"), _git(repo, "HEAD^{tree}")
    lanes = []
    transports: dict[str, SimpleNamespace] = {}
    properties = _target_properties(head, tree)
    for lane_id, inventory_lane in (
        ("core", Increment6CloseoutLane.DETERMINISTIC),
        ("service", Increment6CloseoutLane.ACTUAL_NEO4J),
    ):
        artifact = tmp_path / lane_id
        artifact.mkdir()
        report = _junit(artifact / "report.xml", inventory_lane, properties)
        payload = report.read_bytes()
        replay = SimpleNamespace(
            head_sha=head, replay_identity="sha256:" + lane_id[0] * 64
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
            receipt_identity="sha256:" + "r" * 64,
            route=SimpleNamespace(selected_test_manifest_digest="sha256:" + "a" * 64),
        )
        lane = SimpleNamespace(
            lane_id=lane_id,
            lane_identity="sha256:" + "l" * 64,
            receipt=receipt,
            replay=replay,
        )
        lanes.append(lane)
        transports[lane_id] = SimpleNamespace(
            artifact_root=artifact,
            bundle=SimpleNamespace(transport_identity="sha256:" + "t" * 64),
            replay=replay,
        )
    decision = SimpleNamespace(
        context=SimpleNamespace(evaluated_sha=head, evaluated_tree_sha=tree),
        decision_identity="sha256:" + "d" * 64,
        lanes=tuple(lanes),
        result="PASS",
    )
    return decision, transports


def _patch_inputs(
    monkeypatch: pytest.MonkeyPatch,
    decision: SimpleNamespace,
    transports: dict[str, SimpleNamespace],
) -> None:
    monkeypatch.setattr(
        "scripts.sdlc.increment6g_closeout_receipt.load_contract",
        lambda _root: object(),
    )
    monkeypatch.setattr(
        "scripts.sdlc.increment6g_closeout_receipt.validate_shadow_decision",
        lambda _value, contract: decision,
    )
    monkeypatch.setattr(
        "scripts.sdlc.increment6g_closeout_receipt.load_verified_transport",
        lambda path: transports[Path(path).name],
    )


def test_final_receipt_binds_exact_decision_transports_inventory_and_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _clean_clone(tmp_path)
    decision, transports = _final_stubs(tmp_path, repo)
    _patch_inputs(monkeypatch, decision, transports)
    decision_path = tmp_path / "decision.json"
    decision_path.write_text("{}", encoding="utf-8")

    receipt = build_final_receipt(
        repo_root=repo,
        core_transport_bundle_root=tmp_path / "core",
        service_transport_bundle_root=tmp_path / "service",
        decision_path=decision_path,
    )

    assert receipt["schema_version"] == (
        "newsroom.increment6g.final-closeout-receipt.v1"
    )
    assert len(receipt["selected_cases"]) == len(INCREMENT6G_FINAL_CLOSEOUT_CASES)
    assert {lane["lane_id"] for lane in receipt["lanes"]} == {"core", "service"}
    assert receipt["inventory"]["digest"] == (
        INCREMENT6G_FINAL_CLOSEOUT_INVENTORY_DIGEST
    )
    unsigned = dict(receipt)
    assert unsigned.pop("receipt_identity") == sha256_identity(unsigned)


def test_service_identity_rejects_changed_history_service_and_inventory() -> None:
    properties = _target_properties("a" * 40, "b" * 40)
    identity = _service_identities(properties, "a" * 40, "b" * 40)
    assert identity["migration"]["schema_version"] == 25

    mutations = {
        "increment6g_schema_version": "24",
        "increment6g_source_head_sha": "c" * 40,
        "increment6g_closeout_case_count": "0",
    }
    for field, changed in mutations.items():
        tampered = dict(properties)
        tampered[field] = changed
        with pytest.raises(Increment6GCloseoutReceiptError):
            _service_identities(tampered, "a" * 40, "b" * 40)


def test_receipt_preserves_v25_prefix_after_an_authorised_future_migration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.sdlc.increment6g_closeout_receipt as receipt_module

    appended = (
        *EXPECTED_MIGRATION_HISTORY,
        (26, "future_authorised", "sha256:x"),
    )
    monkeypatch.setattr(receipt_module, "SCHEMA_VERSION", 26)
    monkeypatch.setattr(receipt_module, "EXPECTED_MIGRATION_HISTORY", appended)

    properties = _target_properties("a" * 40, "b" * 40)
    identity = receipt_module._service_identities(properties, "a" * 40, "b" * 40)
    assert identity["migration"]["schema_version"] == 25
    assert len(identity["migration"]["history"]) == 25


def test_selected_case_must_be_present_and_pass_without_skip(tmp_path: Path) -> None:
    properties = _target_properties("a" * 40, "b" * 40)
    target = next(
        case
        for case in INCREMENT6G_FINAL_CLOSEOUT_CASES
        if case.lane is Increment6CloseoutLane.ACTUAL_NEO4J
    )
    report = _parse_junit(
        _junit(
            tmp_path / "service.xml",
            Increment6CloseoutLane.ACTUAL_NEO4J,
            properties,
            skipped=target.test_id,
        )
    )
    with pytest.raises(Increment6GCloseoutReceiptError, match="not_passed"):
        _selected_cases((report,), Increment6CloseoutLane.ACTUAL_NEO4J)


def test_final_receipt_rechecks_clean_checkout_before_emission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _clean_clone(tmp_path)
    decision, transports = _final_stubs(tmp_path, repo)
    _patch_inputs(monkeypatch, decision, transports)
    decision_path = tmp_path / "decision.json"
    decision_path.write_text("{}", encoding="utf-8")
    (repo / "README.md").write_text(
        (repo / "README.md").read_text(encoding="utf-8") + "\ntracked drift\n",
        encoding="utf-8",
    )

    with pytest.raises(Increment6GCloseoutReceiptError, match="validated_input"):
        build_final_receipt(
            repo_root=repo,
            core_transport_bundle_root=tmp_path / "core",
            service_transport_bundle_root=tmp_path / "service",
            decision_path=decision_path,
        )
