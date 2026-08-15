"""Independently reconstruct the exact signed Increment 8 admission subjects."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.increment8.admission import (
    OperationalAdmissionDecision,
    QualificationPacket,
    SubstantiveReviewEvidence,
)
from scripts.sdlc.emit_evidence import sha256_identity
from scripts.sdlc.increment5e2_closeout_receipt import _git_identity
from scripts.sdlc.increment8f_closeout_receipt import FINAL_SCHEMA_VERSION


class Increment8SignedSubjectError(ValueError):
    """A signed Increment 8 subject differs from exact reconstructed evidence."""


def validate_signed_subjects(
    *,
    repo_root: Path,
    packet_path: Path,
    decision_path: Path,
    receipt_path: Path,
    substantive_review_path: Path,
) -> None:
    _, head, tree = _git_identity(repo_root)
    packet = QualificationPacket.from_canonical_bytes(packet_path.read_bytes())
    decision = OperationalAdmissionDecision.from_canonical_bytes(
        decision_path.read_bytes(), packet=packet
    )
    substantive_review = SubstantiveReviewEvidence.from_canonical_bytes(
        substantive_review_path.read_bytes()
    )
    if (
        substantive_review.merge_sha != head
        or canonical_json_bytes(packet.retained_evidence["substantive_review"])
        != substantive_review.canonical_bytes
        or packet.evidence_digests["substantive_review_digest"]
        != substantive_review.digest
    ):
        raise Increment8SignedSubjectError("substantive review binding differs")
    receipt_raw = receipt_path.read_bytes()
    receipt = json.loads(receipt_raw.decode("utf-8", errors="strict"))
    if receipt_raw != canonical_json_bytes(receipt) + b"\n":
        raise Increment8SignedSubjectError("receipt is not canonical JSON")
    if not isinstance(receipt, dict):
        raise Increment8SignedSubjectError("receipt is not an object")
    unsigned = dict(receipt)
    claimed = unsigned.pop("receipt_identity", None)
    if (
        claimed != sha256_identity(unsigned)
        or receipt.get("schema_version") != FINAL_SCHEMA_VERSION
        or receipt.get("evaluated_sha") != head
        or receipt.get("evaluated_tree_sha") != tree
        or receipt.get("qualification_packet_digest") != packet.digest
        or receipt.get("substantive_review_digest")
        != packet.evidence_digests["substantive_review_digest"]
        or receipt.get("operational_admission_decision_digest") != decision.digest
        or receipt.get("handoff_anchor_digest")
        != packet.evidence_digests["handoff_anchor_digest"]
        or receipt.get("operational_admission_verdict") != decision.verdict.value
        or receipt.get("increment9_eligibility")
        != decision.increment9_eligibility.value
    ):
        raise Increment8SignedSubjectError("receipt admission binding differs")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--decision", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--substantive-review", required=True, type=Path)
    arguments = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        validate_signed_subjects(
            repo_root=arguments.repo_root,
            packet_path=arguments.packet,
            decision_path=arguments.decision,
            receipt_path=arguments.receipt,
            substantive_review_path=arguments.substantive_review,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"EVIDENCE_MISMATCH:increment8-signed-subjects:{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
