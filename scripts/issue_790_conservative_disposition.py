#!/usr/bin/env python3
"""Operate the issue #790 plan or its bounded event-supply path."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from newsroom.control_plane.issue_790_disposition import (
    Issue790DispositionError,
    activate_issue_790_step16_plan,
    apply_issue_790_plan,
    assert_issue_790_paths_disjoint,
    dry_run_issue_790_plan,
    load_issue_790_plan,
    qualify_issue_790_candidate_event,
    qualify_issue_790_step16_readiness,
    require_issue_790_path_outside_git,
    run_issue_790_canary,
    validate_issue_790_step16_candidate,
    write_issue_790_canonical_json,
    write_issue_790_receipt,
)
from newsroom.control_plane.issue_790_event_supply import (
    BoundedEventSupplyError,
    supply_one_graphiti_event,
)
from newsroom.control_plane.issue_790_prepared_canary import (
    prepared_canary_from_record,
)
from newsroom.control_plane.veto import VetoError


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


def _load_object(path: Path, *, field: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Issue790DispositionError(f"{field} is not readable JSON") from exc
    if not isinstance(value, dict):
        raise Issue790DispositionError(f"{field} must be an object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Execute an issue #790 disposition or its bounded one-event supply "
            "path against an explicit store. Mini application remains F4."
        )
    )
    parser.add_argument(
        "mode",
        choices=(
            "dry-run",
            "apply",
            "canary",
            "activate-step16",
            "qualify-event",
            "qualify-step16",
            "supply-event",
        ),
    )
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--observed-at", type=_instant)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument("--proving-store", type=Path)
    parser.add_argument("--canary-event-id")
    parser.add_argument("--canary-ledger-seq", type=int)
    parser.add_argument("--disposition-digest")
    parser.add_argument("--scratch-store", type=Path)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--prepared-canary", type=Path)
    parser.add_argument("--recover-interrupted-canary", action="store_true")
    parser.add_argument("--expected-backup-digest")
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--pre-dispatch", type=Path)
    parser.add_argument("--comment-id", type=int)
    parser.add_argument("--focus-gate-manifest", type=Path)
    parser.add_argument("--review-receipt", type=Path)
    parser.add_argument("--activated-plan", type=Path)
    parser.add_argument("--activation-receipt", type=Path)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--route-state", type=Path)
    parser.add_argument("--circuit-state", type=Path)
    parser.add_argument("--canary-event", type=Path)
    parser.add_argument("--expected-frontier-ledger-seq", type=int)
    args = parser.parse_args(argv)

    try:
        if args.mode == "supply-event":
            return _supply_event(parser, args)
        if args.mode == "activate-step16":
            return _activate_step16(args)
        if args.mode == "qualify-event":
            return _qualify_event(args)
        if args.mode == "qualify-step16":
            return _qualify_step16(args)
        return _legacy_mode(parser, args)
    except (
        BoundedEventSupplyError,
        Issue790DispositionError,
        OSError,
        sqlite3.Error,
        VetoError,
    ) as exc:
        sys.stderr.write(f"{exc}\n")
        return 2


def _supply_event(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> int:
    if (
        args.proving_store is None
        or args.observed_at is None
        or args.expected_frontier_ledger_seq is None
    ):
        parser.error(
            "supply-event requires --proving-store, --observed-at and "
            "--expected-frontier-ledger-seq"
        )
    result = supply_one_graphiti_event(
        proving_store=str(args.proving_store),
        unpublished_store=str(args.store),
        expected_frontier_ledger_seq=args.expected_frontier_ledger_seq,
        clock=lambda: args.observed_at,
    )
    sys.stdout.write(json.dumps(result.as_dict(), sort_keys=True) + "\n")
    return 0


def _legacy_mode(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if args.expected_frontier_ledger_seq is not None:
        parser.error("--expected-frontier-ledger-seq is supply-event only")
    if args.plan is None or args.observed_at is None or args.receipt is None:
        parser.error(f"{args.mode} requires --plan, --observed-at and --receipt")
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
    if args.mode != "canary" and args.prepared_canary is not None:
        parser.error("--prepared-canary is accepted only in canary mode")
    if args.mode != "canary" and args.recover_interrupted_canary:
        parser.error("--recover-interrupted-canary is accepted only in canary mode")
    if args.mode != "canary" and args.expected_backup_digest is not None:
        parser.error("--expected-backup-digest is accepted only in canary mode")
    if args.recover_interrupted_canary and args.expected_backup_digest is None:
        parser.error(
            "--recover-interrupted-canary requires --expected-backup-digest"
        )
    if args.mode == "dry-run" and args.repository_root is not None:
        parser.error("dry-run does not accept --repository-root")
    destination_path = (
        args.scratch_store if args.mode == "dry-run" else args.backup
    )
    assert destination_path is not None
    operation_paths: list[Path] = [
        args.store,
        args.plan,
        args.receipt,
        destination_path,
    ]
    if args.proving_store is not None:
        operation_paths.append(args.proving_store)
    if args.prepared_canary is not None:
        operation_paths.append(args.prepared_canary)
    assert_issue_790_paths_disjoint(*operation_paths)
    plan = load_issue_790_plan(args.plan, store=args.store)
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
        prepared = (
            None
            if args.prepared_canary is None
            else prepared_canary_from_record(
                _load_object(
                    args.prepared_canary,
                    field="prepared canary",
                )
            )
        )
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
            prepared=prepared,
            recover_interrupted=args.recover_interrupted_canary,
            expected_backup_digest=args.expected_backup_digest,
        )
    write_issue_790_receipt(args.receipt, receipt)
    sys.stdout.write(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    if args.mode == "canary" and receipt.get("canary_evidence_passed") is not True:
        return 3
    return 0


def _activate_step16(args: argparse.Namespace) -> int:
    required = (
        args.candidate,
        args.pre_dispatch,
        args.comment_id,
        args.focus_gate_manifest,
        args.review_receipt,
        args.activated_plan,
        args.activation_receipt,
    )
    if any(value is None for value in required):
        raise Issue790DispositionError(
            "activate-step16 requires --candidate, --pre-dispatch, --comment-id, "
            "--focus-gate-manifest, --review-receipt, --activated-plan and "
            "--activation-receipt"
        )
    assert args.candidate is not None
    assert args.pre_dispatch is not None
    assert args.comment_id is not None
    assert args.focus_gate_manifest is not None
    assert args.review_receipt is not None
    assert args.activated_plan is not None
    assert args.activation_receipt is not None
    if isinstance(args.comment_id, bool) or args.comment_id <= 0:
        raise Issue790DispositionError("issue #790 owner comment identity differs")
    require_issue_790_path_outside_git(args.activated_plan, field="activated plan")
    require_issue_790_path_outside_git(
        args.activation_receipt, field="activation receipt"
    )
    assert_issue_790_paths_disjoint(
        args.store,
        args.candidate,
        args.pre_dispatch,
        args.focus_gate_manifest,
        args.review_receipt,
        args.activated_plan,
        args.activation_receipt,
    )
    candidate = validate_issue_790_step16_candidate(
        _load_object(args.candidate, field="checked candidate")
    )
    pre_dispatch = _load_object(args.pre_dispatch, field="pre-dispatch template")
    focus_gate = _load_object(args.focus_gate_manifest, field="focus gate manifest")
    review = _load_object(args.review_receipt, field="feature-complete review receipt")
    activated = activate_issue_790_step16_plan(
        candidate,
        comment_id=args.comment_id,
        pre_dispatch=pre_dispatch,
        store=args.store,
        focus_gate_manifest=focus_gate,
        review_receipt=review,
    )
    plan = write_issue_790_canonical_json(
        args.activated_plan,
        _record_mapping(activated.get("plan"), field="activated plan"),
        field="activated plan",
    )
    receipt = write_issue_790_canonical_json(
        args.activation_receipt,
        _record_mapping(activated.get("activation"), field="activation receipt"),
        field="activation receipt",
    )
    sys.stdout.write(
        json.dumps(
            {"activation": receipt, "plan": plan},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return 0


def _qualify_step16(args: argparse.Namespace) -> int:
    required = (
        args.plan,
        args.proving_store,
        args.evidence,
        args.route_state,
        args.canary_event,
        args.observed_at,
        args.receipt,
    )
    if any(value is None for value in required):
        raise Issue790DispositionError(
            "qualify-step16 requires --plan, --proving-store, --evidence, "
            "--route-state, --canary-event, --observed-at and --receipt"
        )
    assert args.plan is not None
    assert args.proving_store is not None
    assert args.evidence is not None
    assert args.route_state is not None
    assert args.canary_event is not None
    assert args.observed_at is not None
    assert args.receipt is not None
    require_issue_790_path_outside_git(args.receipt, field="readiness receipt")
    paths = [
        args.store,
        args.proving_store,
        args.plan,
        args.evidence,
        args.route_state,
        args.canary_event,
        args.receipt,
    ]
    if args.circuit_state is not None:
        paths.append(args.circuit_state)
    assert_issue_790_paths_disjoint(*paths)
    plan = load_issue_790_plan(args.plan, store=args.store)
    evidence = _load_object(args.evidence, field="operational evidence")
    route_state = _load_object(args.route_state, field="route state")
    canary_event = _load_object(args.canary_event, field="canary event")
    circuit_state = (
        None
        if args.circuit_state is None
        else _load_object(args.circuit_state, field="circuit state")
    )
    receipt = qualify_issue_790_step16_readiness(
        plan=plan,
        store=args.store,
        proving_store=args.proving_store,
        evidence=evidence,
        route_state=route_state,
        circuit_state=circuit_state,
        canary_event=canary_event,
        observed_at=args.observed_at,
    )
    write_issue_790_canonical_json(
        args.receipt, receipt, field="readiness receipt"
    )
    sys.stdout.write(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    return 0


def _qualify_event(args: argparse.Namespace) -> int:
    required = (
        args.proving_store,
        args.canary_event_id,
        args.canary_ledger_seq,
        args.observed_at,
        args.receipt,
    )
    if any(value is None for value in required):
        raise Issue790DispositionError(
            "qualify-event requires --proving-store, --canary-event-id, "
            "--canary-ledger-seq, --observed-at and --receipt"
        )
    assert args.proving_store is not None
    assert args.canary_event_id is not None
    assert args.canary_ledger_seq is not None
    assert args.observed_at is not None
    assert args.receipt is not None
    require_issue_790_path_outside_git(
        args.receipt,
        field="candidate event qualification",
    )
    assert_issue_790_paths_disjoint(args.store, args.proving_store, args.receipt)
    receipt = qualify_issue_790_candidate_event(
        store=args.store,
        proving_store=args.proving_store,
        event_id=args.canary_event_id,
        ledger_seq=args.canary_ledger_seq,
        observed_at=args.observed_at,
    )
    write_issue_790_canonical_json(
        args.receipt,
        receipt,
        field="candidate event qualification",
    )
    sys.stdout.write(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    return 0


def _record_mapping(value: object, *, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise Issue790DispositionError(f"{field} must be an object")
    return dict(value)


if __name__ == "__main__":
    raise SystemExit(main())
