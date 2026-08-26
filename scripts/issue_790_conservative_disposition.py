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
    assert_issue_790_paths_disjoint,
    dry_run_issue_790_plan,
    load_issue_790_plan,
    run_issue_790_canary,
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
    parser.add_argument("mode", choices=("dry-run", "apply", "canary"))
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--observed-at", type=_instant, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument("--proving-store", type=Path)
    parser.add_argument("--canary-event-id")
    parser.add_argument("--canary-ledger-seq", type=int)
    parser.add_argument("--disposition-digest")
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--scratch-store", type=Path)
    destination.add_argument("--backup", type=Path)
    args = parser.parse_args(argv)
    if args.mode == "dry-run" and args.scratch_store is None:
        parser.error("dry-run requires --scratch-store")
    if args.mode in {"apply", "canary"} and args.backup is None:
        parser.error(f"{args.mode} requires --backup")
    if args.mode in {"apply", "canary"} and args.repository_root is None:
        parser.error(f"{args.mode} requires --repository-root")
    canary_values = (
        args.proving_store,
        args.canary_event_id,
        args.canary_ledger_seq,
        args.disposition_digest,
    )
    if args.mode == "canary" and any(value is None for value in canary_values):
        parser.error(
            "canary requires --proving-store, --canary-event-id, "
            "--canary-ledger-seq and --disposition-digest"
        )
    if args.mode != "canary" and any(value is not None for value in canary_values):
        parser.error("canary arguments are accepted only in canary mode")
    if args.mode == "dry-run" and args.repository_root is not None:
        parser.error("dry-run does not accept --repository-root")
    destination_path = (
        args.scratch_store if args.mode == "dry-run" else args.backup
    )
    assert destination_path is not None

    try:
        operation_paths: list[Path] = [
            args.store,
            args.plan,
            args.receipt,
            destination_path,
        ]
        if args.proving_store is not None:
            operation_paths.append(args.proving_store)
        assert_issue_790_paths_disjoint(*operation_paths)
        plan = load_issue_790_plan(args.plan)
        if args.mode == "dry-run":
            assert args.scratch_store is not None
            receipt = dry_run_issue_790_plan(
                source_store=args.store,
                scratch_store=args.scratch_store,
                plan=plan,
                observed_at=args.observed_at,
            )
        elif args.mode == "apply":
            assert args.backup is not None
            assert args.repository_root is not None
            receipt = apply_issue_790_plan(
                store=args.store,
                backup_path=args.backup,
                plan=plan,
                observed_at=args.observed_at,
                repository_root=args.repository_root,
            )
        else:
            assert args.backup is not None
            assert args.repository_root is not None
            assert args.proving_store is not None
            assert args.canary_event_id is not None
            assert args.canary_ledger_seq is not None
            assert args.disposition_digest is not None
            receipt = run_issue_790_canary(
                store=args.store,
                proving_store=args.proving_store,
                backup_path=args.backup,
                plan=plan,
                observed_at=args.observed_at,
                repository_root=args.repository_root,
                event_id=args.canary_event_id,
                ledger_seq=args.canary_ledger_seq,
                disposition_digest=args.disposition_digest,
            )
        write_issue_790_receipt(args.receipt, receipt)
    except (Issue790DispositionError, OSError, sqlite3.Error) as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    sys.stdout.write(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    if args.mode == "canary" and receipt.get("canary_evidence_passed") is not True:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
