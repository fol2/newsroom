#!/usr/bin/env python3
"""Dry-run or apply the exact owner-approved issue #790 disposition plan."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from newsroom.control_plane.issue_790_disposition import (
    Issue790DispositionError,
    apply_issue_790_plan,
    dry_run_issue_790_plan,
    load_issue_790_plan,
    write_issue_790_receipt,
)


def _instant(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "observed-at must be an ISO-8601 instant"
        ) from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("observed-at must include a timezone")
    return parsed.astimezone(UTC)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Execute the content-addressed issue #790 disposition against an "
            "isolated copy or its explicitly backed-up target store."
        )
    )
    parser.add_argument("mode", choices=("dry-run", "apply"))
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--observed-at", type=_instant, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--scratch-store", type=Path)
    destination.add_argument("--backup", type=Path)
    args = parser.parse_args(argv)
    if args.mode == "dry-run" and args.scratch_store is None:
        parser.error("dry-run requires --scratch-store")
    if args.mode == "apply" and args.backup is None:
        parser.error("apply requires --backup")

    try:
        plan = load_issue_790_plan(args.plan)
        if args.mode == "dry-run":
            receipt = dry_run_issue_790_plan(
                source_store=args.store,
                scratch_store=args.scratch_store,
                plan=plan,
                observed_at=args.observed_at,
            )
        else:
            receipt = apply_issue_790_plan(
                store=args.store,
                backup_path=args.backup,
                plan=plan,
                observed_at=args.observed_at,
            )
        write_issue_790_receipt(args.receipt, receipt)
    except (Issue790DispositionError, OSError, sqlite3.Error) as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    sys.stdout.write(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
