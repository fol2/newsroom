from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.migrations import (
    EXPECTED_MIGRATION_HISTORY,
    EXPECTED_SCHEMA_FINGERPRINT,
    SCHEMA_VERSION,
)
from newsroom.increment6.closeout import (
    INCREMENT6_FINAL_REQUIREMENTS,
    INCREMENT6G_FINAL_CLOSEOUT_CASES,
    INCREMENT6G_FINAL_CLOSEOUT_INVENTORY_DIGEST,
    INCREMENT6G_FINAL_NON_EFFECTS,
    Increment6CloseoutLane,
)
from newsroom.projection.neo4j import (
    NEO4J_B2_DRIVER_VERSION,
    NEO4J_B2_IMAGE,
    NEO4J_B2_SERVER_VERSION,
)
from scripts.sdlc.contracts import ContractError, load_contract
from scripts.sdlc.emit_evidence import sha256_identity
from scripts.sdlc.increment5e2_closeout_receipt import (
    Increment5E2CloseoutReceiptError,
    _decision_payload,
    _git_identity,
    _lane_reports,
    _require_git_identity,
    _write_output,
)
from scripts.sdlc.shadow_decision import (
    ShadowDecisionError,
    validate_shadow_decision,
)
from scripts.sdlc.transport_replay import (
    TransportReplayError,
    load_verified_transport,
)
from scripts.sdlc.workflow_lane import service_compatibility_digest

FINAL_SCHEMA_VERSION = "newsroom.increment6g.final-closeout-receipt.v1"
_TARGET_TEST_ID = (
    "newsroom.tests.test_increment6g_neo4j_service::"
    "test_actual_service_increment6g_identity_and_closeout_inventory"
)
_TARGET_PROPERTIES = {
    "increment6g_closeout_case_count",
    "increment6g_closeout_inventory_digest",
    "increment6g_migration_history_json",
    "increment6g_neo4j_database",
    "increment6g_neo4j_driver_version",
    "increment6g_neo4j_edition",
    "increment6g_neo4j_image",
    "increment6g_neo4j_projector_username",
    "increment6g_neo4j_server_version",
    "increment6g_non_effects",
    "increment6g_schema_fingerprint",
    "increment6g_schema_version",
    "increment6g_service_compatibility_digest",
    "increment6g_source_head_sha",
    "increment6g_source_tree_sha",
}


class Increment6GCloseoutReceiptError(ValueError):
    """Raised when the Increment 6 closed-world evidence is not exact."""


def _inventory() -> dict[str, object]:
    migration_history_digest = digest_bytes(
        canonical_json_bytes([list(item) for item in EXPECTED_MIGRATION_HISTORY])
    )
    return {
        "case_count": len(INCREMENT6G_FINAL_CLOSEOUT_CASES),
        "digest": INCREMENT6G_FINAL_CLOSEOUT_INVENTORY_DIGEST,
        "non_effects": list(INCREMENT6G_FINAL_NON_EFFECTS),
        "requirements": sorted(INCREMENT6_FINAL_REQUIREMENTS),
        "migration_history_digest": migration_history_digest,
        "schema_version": SCHEMA_VERSION,
        "schema_fingerprint": EXPECTED_SCHEMA_FINGERPRINT,
    }


def _selected_cases(
    reports: Sequence[object], lane: Increment6CloseoutLane
) -> tuple[list[dict[str, object]], Mapping[str, str]]:
    observed: dict[str, object] = {}
    for report in reports:
        for case in report.cases:
            if case.test_id in observed:
                raise Increment6GCloseoutReceiptError("duplicate_test_id")
            observed[case.test_id] = case
    selected: list[dict[str, object]] = []
    properties: Mapping[str, str] = {}
    for item in INCREMENT6G_FINAL_CLOSEOUT_CASES:
        if item.lane is not lane:
            continue
        case = observed.get(item.test_id)
        if case is None:
            raise Increment6GCloseoutReceiptError(
                f"selected_test_missing:{item.case_id}"
            )
        if case.outcome != "passed":
            raise Increment6GCloseoutReceiptError(
                f"selected_test_not_passed:{item.case_id}:{case.outcome}"
            )
        selected.append({**item.canonical_value(), "outcome": "passed"})
        if item.test_id == _TARGET_TEST_ID:
            properties = case.properties
    return selected, properties


def _reject_failures(reports: Sequence[object]) -> None:
    for report in reports:
        for case in report.cases:
            if case.outcome in {"failure", "error"}:
                raise Increment6GCloseoutReceiptError(
                    f"test_not_passed:{case.test_id}:{case.outcome}"
                )


def _service_identities(
    properties: Mapping[str, str], head: str, tree: str
) -> dict[str, object]:
    if set(properties) != _TARGET_PROPERTIES:
        raise Increment6GCloseoutReceiptError("target_properties")
    try:
        history = json.loads(properties["increment6g_migration_history_json"])
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Increment6GCloseoutReceiptError("migration_history_json") from exc
    expected_history = [list(item) for item in EXPECTED_MIGRATION_HISTORY]
    if (
        history != expected_history
        or properties["increment6g_migration_history_json"]
        != canonical_json_bytes(expected_history).decode("utf-8")
        or SCHEMA_VERSION != 25
        or properties["increment6g_schema_version"] != "25"
        or properties["increment6g_schema_fingerprint"] != EXPECTED_SCHEMA_FINGERPRINT
    ):
        raise Increment6GCloseoutReceiptError("migration_identity")
    if (
        properties["increment6g_closeout_inventory_digest"]
        != INCREMENT6G_FINAL_CLOSEOUT_INVENTORY_DIGEST
        or properties["increment6g_closeout_case_count"]
        != str(len(INCREMENT6G_FINAL_CLOSEOUT_CASES))
        or properties["increment6g_non_effects"]
        != ",".join(INCREMENT6G_FINAL_NON_EFFECTS)
    ):
        raise Increment6GCloseoutReceiptError("closeout_inventory")
    expected = {
        "increment6g_neo4j_database": "neo4j",
        "increment6g_neo4j_driver_version": NEO4J_B2_DRIVER_VERSION,
        "increment6g_neo4j_edition": "community",
        "increment6g_neo4j_image": NEO4J_B2_IMAGE,
        "increment6g_neo4j_projector_username": "newsroom_projector",
        "increment6g_neo4j_server_version": NEO4J_B2_SERVER_VERSION,
        "increment6g_service_compatibility_digest": service_compatibility_digest(),
        "increment6g_source_head_sha": head,
        "increment6g_source_tree_sha": tree,
    }
    if any(properties[name] != value for name, value in expected.items()):
        raise Increment6GCloseoutReceiptError("service_identity")
    return {
        "migration": {
            "history": expected_history,
            "history_digest": digest_bytes(canonical_json_bytes(expected_history)),
            "schema_fingerprint": EXPECTED_SCHEMA_FINGERPRINT,
            "schema_version": SCHEMA_VERSION,
        },
        "service": {
            "compatibility_digest": service_compatibility_digest(),
            "database": "neo4j",
            "driver_version": NEO4J_B2_DRIVER_VERSION,
            "edition": "community",
            "image": NEO4J_B2_IMAGE,
            "projector_username": "newsroom_projector",
            "server_version": NEO4J_B2_SERVER_VERSION,
        },
    }


def build_final_receipt(
    *,
    repo_root: str | Path,
    core_transport_bundle_root: str | Path,
    service_transport_bundle_root: str | Path,
    decision_path: str | Path,
) -> dict[str, object]:
    try:
        root, head, tree = _git_identity(repo_root)
        _require_git_identity(root, head, tree)
        contract = load_contract(root)
        decision = validate_shadow_decision(
            _decision_payload(decision_path), contract=contract
        )
        transports = {
            "core": load_verified_transport(core_transport_bundle_root),
            "service": load_verified_transport(service_transport_bundle_root),
        }
    except (
        ContractError,
        Increment5E2CloseoutReceiptError,
        ShadowDecisionError,
        TransportReplayError,
    ) as exc:
        raise Increment6GCloseoutReceiptError("validated_input") from exc
    if decision.result != "PASS" or {lane.lane_id for lane in decision.lanes} != {
        "core",
        "service",
    }:
        raise Increment6GCloseoutReceiptError("decision_not_exact_pass")
    if (
        decision.context.evaluated_sha != head
        or decision.context.evaluated_tree_sha != tree
    ):
        raise Increment6GCloseoutReceiptError("checkout_identity")

    lane_map = {lane.lane_id: lane for lane in decision.lanes}
    lane_values: list[dict[str, object]] = []
    report_values: dict[str, list[dict[str, object]]] = {}
    selected_all: list[dict[str, object]] = []
    manifest_digests: set[str] = set()
    identities: dict[str, object] | None = None
    try:
        for lane_id, inventory_lane in (
            ("core", Increment6CloseoutLane.DETERMINISTIC),
            ("service", Increment6CloseoutLane.ACTUAL_NEO4J),
        ):
            lane = lane_map[lane_id]
            verified = transports[lane_id]
            if (
                lane.receipt.evaluated_sha != head
                or lane.receipt.evaluated_tree_sha != tree
                or verified.replay.head_sha != head
            ):
                raise Increment6GCloseoutReceiptError("lane_checkout_identity")
            reports = _lane_reports(verified, lane)
            _reject_failures(reports)
            selected, properties = _selected_cases(reports, inventory_lane)
            selected_all.extend(selected)
            if inventory_lane is Increment6CloseoutLane.ACTUAL_NEO4J:
                identities = _service_identities(properties, head, tree)
            report_values[lane_id] = [
                {
                    "digest": raw.digest,
                    "path": raw.path,
                    "size_bytes": raw.size_bytes,
                }
                for raw in lane.receipt.raw_reports
            ]
            manifest_digests.add(lane.receipt.route.selected_test_manifest_digest)
            lane_values.append(
                {
                    "envelope_identity": lane.receipt.envelope_identity,
                    "lane_id": lane_id,
                    "lane_identity": lane.lane_identity,
                    "receipt_identity": lane.receipt.receipt_identity,
                    "replay_identity": verified.replay.replay_identity,
                    "transport_identity": verified.bundle.transport_identity,
                }
            )
        _require_git_identity(root, head, tree)
    except Increment5E2CloseoutReceiptError as exc:
        raise Increment6GCloseoutReceiptError("validated_input") from exc
    if identities is None or len(manifest_digests) != 1:
        raise Increment6GCloseoutReceiptError("selected_test_manifest")

    value = {
        "decision_identity": decision.decision_identity,
        "evaluated_sha": head,
        "evaluated_tree_sha": tree,
        "inventory": _inventory(),
        "junit_reports": report_values,
        "lanes": lane_values,
        "schema_version": FINAL_SCHEMA_VERSION,
        "selected_cases": sorted(selected_all, key=lambda item: str(item["case_id"])),
        "selected_test_manifest_digest": manifest_digests.pop(),
        **identities,
    }
    return {**value, "receipt_identity": sha256_identity(value)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Emit the exact Increment 6G closed-world receipt"
    )
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--core-transport-bundle-root", required=True)
    parser.add_argument("--service-transport-bundle-root", required=True)
    parser.add_argument("--decision", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        receipt = build_final_receipt(
            repo_root=arguments.repo_root,
            core_transport_bundle_root=arguments.core_transport_bundle_root,
            service_transport_bundle_root=arguments.service_transport_bundle_root,
            decision_path=arguments.decision,
        )
        _write_output(arguments.output, receipt)
    except (Increment5E2CloseoutReceiptError, Increment6GCloseoutReceiptError) as exc:
        print(f"EVIDENCE_MISMATCH:increment6g-closeout:{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
