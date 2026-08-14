from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from newsroom.authority.migrations import (
    EXPECTED_MIGRATION_HISTORY,
    SCHEMA_VERSION,
)
from newsroom.increment7.closeout import (
    INCREMENT7_FINAL_CLOSEOUT_INVENTORY_DIGEST,
    INCREMENT7_FINAL_MIGRATION_HISTORY_DIGEST,
    INCREMENT7_FINAL_NON_EFFECTS,
    INCREMENT7_FINAL_REQUIREMENTS,
    INCREMENT7_FINAL_SCHEMA_FINGERPRINT,
    INCREMENT7_FINAL_SCHEMA_VERSION,
    INCREMENT7G_FINAL_CLOSEOUT_CASES,
    Increment7CloseoutLane,
    Increment7CloseoutError,
    increment7_final_migration_history,
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
from scripts.sdlc.increment6g_closeout_receipt import (
    Increment6GCloseoutReceiptError,
    _service_identities,
)
from scripts.sdlc.shadow_decision import ShadowDecisionError, validate_shadow_decision
from scripts.sdlc.transport_replay import TransportReplayError, load_verified_transport

FINAL_SCHEMA_VERSION = "newsroom.increment7.closeout-receipt.v1"


class Increment7GCloseoutReceiptError(ValueError):
    """Raised when the Increment 7 closed-world evidence is not exact."""


def _inventory() -> dict[str, object]:
    if SCHEMA_VERSION < INCREMENT7_FINAL_SCHEMA_VERSION:
        raise Increment7GCloseoutReceiptError("schema_identity")
    try:
        increment7_final_migration_history(EXPECTED_MIGRATION_HISTORY)
    except Increment7CloseoutError as exc:
        raise Increment7GCloseoutReceiptError("migration_history") from exc
    return {
        "case_count": len(INCREMENT7G_FINAL_CLOSEOUT_CASES),
        "digest": INCREMENT7_FINAL_CLOSEOUT_INVENTORY_DIGEST,
        "migration_history_digest": INCREMENT7_FINAL_MIGRATION_HISTORY_DIGEST,
        "non_effects": list(INCREMENT7_FINAL_NON_EFFECTS),
        "requirements": sorted(INCREMENT7_FINAL_REQUIREMENTS),
        "schema_fingerprint": INCREMENT7_FINAL_SCHEMA_FINGERPRINT,
        "schema_version": INCREMENT7_FINAL_SCHEMA_VERSION,
    }


def _selected_cases(reports, lane: Increment7CloseoutLane):
    observed: dict[str, object] = {}
    for report in reports:
        for case in report.cases:
            if case.test_id in observed:
                raise Increment7GCloseoutReceiptError("duplicate_test_id")
            observed[case.test_id] = case
    selected: list[dict[str, object]] = []
    service_properties = None
    for inventory_case in INCREMENT7G_FINAL_CLOSEOUT_CASES:
        if inventory_case.lane is not lane:
            continue
        case = observed.get(inventory_case.test_id)
        if case is None:
            raise Increment7GCloseoutReceiptError(
                f"selected_test_missing:{inventory_case.case_id}"
            )
        if case.outcome != "passed":
            raise Increment7GCloseoutReceiptError(
                f"selected_test_not_passed:{inventory_case.case_id}:{case.outcome}"
            )
        selected.append({**inventory_case.canonical_value(), "outcome": "passed"})
        if inventory_case.case_id == "S01_EXISTING_SERVICE":
            service_properties = case.properties
    return selected, service_properties


def _reject_failures(reports) -> None:
    for report in reports:
        for case in report.cases:
            if case.outcome in {"failure", "error"}:
                raise Increment7GCloseoutReceiptError(
                    f"test_not_passed:{case.test_id}:{case.outcome}"
                )


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
        raise Increment7GCloseoutReceiptError("validated_input") from exc
    if decision.result != "PASS" or {lane.lane_id for lane in decision.lanes} != {
        "core",
        "service",
    }:
        raise Increment7GCloseoutReceiptError("decision_not_exact_pass")
    if (
        decision.context.evaluated_sha != head
        or decision.context.evaluated_tree_sha != tree
    ):
        raise Increment7GCloseoutReceiptError("checkout_identity")

    lane_map = {lane.lane_id: lane for lane in decision.lanes}
    lane_values: list[dict[str, object]] = []
    report_values: dict[str, list[dict[str, object]]] = {}
    selected_all: list[dict[str, object]] = []
    manifest_digests: set[str] = set()
    service_identity = None
    try:
        for lane_id, inventory_lane in (
            ("core", Increment7CloseoutLane.DETERMINISTIC),
            ("service", Increment7CloseoutLane.ACTUAL_NEO4J),
        ):
            lane = lane_map[lane_id]
            verified = transports[lane_id]
            if (
                lane.receipt.evaluated_sha != head
                or lane.receipt.evaluated_tree_sha != tree
                or verified.replay.head_sha != head
            ):
                raise Increment7GCloseoutReceiptError("lane_checkout_identity")
            reports = _lane_reports(verified, lane)
            _reject_failures(reports)
            selected, properties = _selected_cases(reports, inventory_lane)
            selected_all.extend(selected)
            if inventory_lane is Increment7CloseoutLane.ACTUAL_NEO4J:
                if properties is None:
                    raise Increment7GCloseoutReceiptError("service_properties")
                service_identity = _service_identities(properties, head, tree)[
                    "service"
                ]
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
    except (
        Increment5E2CloseoutReceiptError,
        Increment6GCloseoutReceiptError,
        Increment7CloseoutError,
    ) as exc:
        raise Increment7GCloseoutReceiptError("validated_input") from exc
    if service_identity is None or len(manifest_digests) != 1:
        raise Increment7GCloseoutReceiptError("selected_test_manifest")

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
        "service": service_identity,
    }
    return {**value, "receipt_identity": sha256_identity(value)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Emit the exact Increment 7G closed-world receipt"
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
    except (
        Increment5E2CloseoutReceiptError,
        Increment6GCloseoutReceiptError,
        Increment7GCloseoutReceiptError,
    ) as exc:
        print(f"EVIDENCE_MISMATCH:increment7g-closeout:{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
