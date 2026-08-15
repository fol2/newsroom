"""Execute and retain the closed-world Increment 8 qualification fixture."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from newsroom.increment8.admission import build_operational_admission_decision
from newsroom.tests.test_increment8f_admission import _D, _D3, _packet


class Increment8FixtureQualificationError(ValueError):
    """The deterministic qualification fixture did not produce exact artifacts."""


def execute_fixture_qualification(
    *, workspace: Path, packet_path: Path, decision_path: Path
) -> tuple[str, str]:
    for path in (workspace, packet_path.parent, decision_path.parent):
        path.mkdir(parents=True, exist_ok=True)
    if packet_path.exists() or decision_path.exists():
        raise Increment8FixtureQualificationError("qualification output already exists")
    packet = _packet(workspace)
    decision = build_operational_admission_decision(
        packet=packet,
        owner_identity_digest=_D3,
        decision_recorded_at_digest=_D,
    )
    packet_path.write_bytes(packet.canonical_bytes)
    decision_path.write_bytes(decision.canonical_bytes)
    return packet.digest, decision.digest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--decision", required=True, type=Path)
    arguments = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        packet_digest, decision_digest = execute_fixture_qualification(
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
