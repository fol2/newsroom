"""Execute and retain the closed-world Increment 8 qualification fixture."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from newsroom.increment8.admission import build_operational_admission_decision
from newsroom.increment8.closeout import Increment8CloseoutLane
from newsroom.increment8.qualification_fixture import (
    FIXTURE_ADMISSION_OWNER_DIGEST,
    FIXTURE_DECISION_RECORDED_AT_DIGEST,
    execute_qualification_fixture,
)
from scripts.sdlc.contracts import load_contract
from scripts.sdlc.increment5e2_closeout_receipt import (
    _decision_payload,
    _git_identity,
    _lane_reports,
)
from scripts.sdlc.increment8f_closeout_receipt import _reject_failures, _selected_cases
from scripts.sdlc.shadow_decision import validate_shadow_decision
from scripts.sdlc.transport_replay import load_verified_transport


class Increment8FixtureQualificationError(ValueError):
    """The deterministic qualification fixture did not produce exact artifacts."""


def execute_fixture_qualification(
    *,
    repo_root: Path,
    core_transport_bundle_root: Path,
    service_transport_bundle_root: Path,
    sdlc_decision_path: Path,
    workspace: Path,
    packet_path: Path,
    decision_path: Path,
) -> tuple[str, str]:
    for path in (workspace, packet_path.parent, decision_path.parent):
        path.mkdir(parents=True, exist_ok=True)
    if packet_path.exists() or decision_path.exists():
        raise Increment8FixtureQualificationError("qualification output already exists")
    root, head, tree = _git_identity(repo_root)
    sdlc_decision = validate_shadow_decision(
        _decision_payload(sdlc_decision_path), contract=load_contract(root)
    )
    if (
        sdlc_decision.result != "PASS"
        or sdlc_decision.context.evaluated_sha != head
        or sdlc_decision.context.evaluated_tree_sha != tree
    ):
        raise Increment8FixtureQualificationError("SDLC decision identity differs")
    lanes = {lane.lane_id: lane for lane in sdlc_decision.lanes}
    if set(lanes) != {"core", "service"}:
        raise Increment8FixtureQualificationError("qualification lanes differ")
    selected = []
    for lane_id, inventory_lane, bundle_root in (
        ("core", Increment8CloseoutLane.DETERMINISTIC, core_transport_bundle_root),
        ("service", Increment8CloseoutLane.ACTUAL_NEO4J, service_transport_bundle_root),
    ):
        verified = load_verified_transport(bundle_root)
        reports = _lane_reports(verified, lanes[lane_id])
        _reject_failures(reports)
        cases, _ = _selected_cases(reports, inventory_lane)
        selected.extend(cases)
    if len(selected) != 13:
        raise Increment8FixtureQualificationError(
            "qualification case inventory differs"
        )

    packet = execute_qualification_fixture(workspace)
    decision = build_operational_admission_decision(
        packet=packet,
        owner_identity_digest=FIXTURE_ADMISSION_OWNER_DIGEST,
        decision_recorded_at_digest=FIXTURE_DECISION_RECORDED_AT_DIGEST,
    )
    packet_path.write_bytes(packet.canonical_bytes)
    decision_path.write_bytes(decision.canonical_bytes)
    return packet.digest, decision.digest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--core-transport-bundle-root", required=True, type=Path)
    parser.add_argument("--service-transport-bundle-root", required=True, type=Path)
    parser.add_argument("--sdlc-decision", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--decision", required=True, type=Path)
    arguments = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        packet_digest, decision_digest = execute_fixture_qualification(
            repo_root=arguments.repo_root,
            core_transport_bundle_root=arguments.core_transport_bundle_root,
            service_transport_bundle_root=arguments.service_transport_bundle_root,
            sdlc_decision_path=arguments.sdlc_decision,
            workspace=arguments.workspace,
            packet_path=arguments.packet,
            decision_path=arguments.decision,
        )
    except (OSError, ValueError) as exc:
        print(f"EVIDENCE_MISMATCH:increment8-qualification:{exc}", file=sys.stderr)
        return 1
    print(f"qualification_packet_digest={packet_digest}")
    print(f"operational_admission_decision_digest={decision_digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
