#!/usr/bin/env python3
"""Reconcile poll-amplified backlog identities onto effective revisions.

This command is the read-only planning boundary. Live mutation belongs to the
composed ControlPlaneCommandService, not a self-configuring shell process.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from newsroom.control_plane.backlog_reconciliation import (
    BacklogReconciliationError,
    parse_evaluated_at,
    reconcile_effective_revision_backlog,
)


def parse_evaluated_at_or_now(text: str | None) -> datetime | None:
    if text is None:
        return None
    return parse_evaluated_at(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only plan for remapping amplified SourceRevision identities "
            "onto effective revisions. Live mutation belongs to the composed "
            "Control Plane command-service."
        )
    )
    parser.add_argument("mode", choices=("dry-run",))
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
        "--evaluated-at",
        help="UTC instant for the seven-day retention window (default: now)",
    )
    args = parser.parse_args(argv)
    try:
        evaluated_at = parse_evaluated_at_or_now(args.evaluated_at)
        receipt = reconcile_effective_revision_backlog(
            proving_store=args.proving,
            unpublished_store=args.unpublished,
            mode="dry-run",
            receipt_path=Path(args.receipt),
            evaluated_at=evaluated_at,
        )
    except BacklogReconciliationError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    sys.stdout.write(
        json.dumps(receipt.as_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
