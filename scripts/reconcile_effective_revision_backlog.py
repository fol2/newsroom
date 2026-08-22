#!/usr/bin/env python3
"""Reconcile poll-amplified backlog identities onto effective revisions.

Repair means remap, never delete. Dry-run mutates nothing. Live refuses to
mutate unless G1–G5 pass and the command-service issues an authenticated
command whose version fence matches the dry-run receipt. Writable opens of
the canonical stores also require --mutate-canonical after the live daemon
is stopped.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from newsroom.control_plane.backlog_reconciliation import (
    BacklogReconciliationError,
    CanonicalStoreGuardError,
    ReconciliationCommandError,
    load_receipt,
    parse_evaluated_at,
    reconcile_effective_revision_backlog,
)
from newsroom.control_plane.command_service import ControlPlaneCommandService


def parse_evaluated_at_or_now(text: str | None) -> datetime | None:
    if text is None:
        return None
    return parse_evaluated_at(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "No-loss remap of amplified SourceRevision identities onto "
            "effective revisions. Does not open canonical stores for writing "
            "unless --mutate-canonical is set. Live mutation is issued only "
            "through the Control Plane command-service."
        )
    )
    parser.add_argument("mode", choices=("dry-run", "live"))
    parser.add_argument("--proving", required=True, help="Path to the proving store")
    parser.add_argument(
        "--unpublished", required=True, help="Path to the unpublished store"
    )
    parser.add_argument(
        "--receipt",
        required=True,
        help="Where to write the reconciliation receipt JSON",
    )
    parser.add_argument(
        "--dry-run-receipt",
        help="Dry-run receipt that live mode must match (G2)",
    )
    parser.add_argument(
        "--backup-dir",
        help="Directory for pre-mutation store backups (required for live)",
    )
    parser.add_argument(
        "--evaluated-at",
        help="UTC instant for the seven-day retention window (default: now)",
    )
    parser.add_argument(
        "--mutate-canonical",
        action="store_true",
        help=(
            "Allow writable opens of the host canonical stores. Orchestrator "
            "only, after the Hermes daemon is stopped and backups are taken."
        ),
    )
    parser.add_argument(
        "--idempotency-key",
        default="",
        help="Idempotency identity for this live command (required for live)",
    )
    parser.add_argument(
        "--expected-mapping-digest",
        default="",
        help="Version fence; must match the dry-run mapping digest (required for live)",
    )
    args = parser.parse_args(argv)
    try:
        evaluated_at = parse_evaluated_at_or_now(args.evaluated_at)
        if args.mode == "live":
            if not args.dry_run_receipt:
                parser.error("live mode requires --dry-run-receipt")
            if not args.backup_dir:
                parser.error("live mode requires --backup-dir")
            if not (args.idempotency_key and args.expected_mapping_digest):
                parser.error(
                    "live mode requires --idempotency-key and "
                    "--expected-mapping-digest"
                )
            receipt = ControlPlaneCommandService().reconcile_effective_revision_backlog(
                proving_store=args.proving,
                unpublished_store=args.unpublished,
                dry_run_receipt=load_receipt(Path(args.dry_run_receipt)),
                receipt_path=Path(args.receipt),
                backup_dir=Path(args.backup_dir),
                allow_canonical_mutation=args.mutate_canonical,
                evaluated_at=evaluated_at,
                idempotency_key=args.idempotency_key,
                expected_mapping_digest=args.expected_mapping_digest,
            )
        else:
            receipt = reconcile_effective_revision_backlog(
                proving_store=args.proving,
                unpublished_store=args.unpublished,
                mode="dry-run",
                receipt_path=Path(args.receipt),
                backup_dir=None if args.backup_dir is None else Path(args.backup_dir),
                allow_canonical_mutation=args.mutate_canonical,
                evaluated_at=evaluated_at,
            )
    except (
        BacklogReconciliationError,
        CanonicalStoreGuardError,
        ReconciliationCommandError,
    ) as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    sys.stdout.write(
        json.dumps(receipt.as_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
