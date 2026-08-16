#!/usr/bin/env python3
"""Seal Increment 9C2 phase outcomes under deterministic stop precedence.

This executable does not inject a fault or perform external I/O.  It consumes a
verified 9B3 campaign bundle.  When 9B3 stopped before first I/O, it emits the
complete comparator/fault inventory as explicitly not run and preserves the
higher-precedence stop.  A non-blocked baseline requires a separate live phase
runner and is rejected here rather than simulated.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.increment9.comparator import (
    EXPECTED_COMPARATOR_ARMS,
    EXPECTED_FAULT_BEHAVIOUR,
    EXPECTED_FAULT_INVENTORY,
    EXPECTED_PHASE_ORDER,
    EXPECTED_STOP_PRECEDENCE,
    StopReason,
)
from newsroom.increment9.plan import INCREMENT_9_SHADOW_PLAN_DIGEST
from scripts.increment9_shadow_campaign import (
    CampaignError,
    LaunchDisposition,
    verify_bundle as verify_campaign_bundle,
)

DEPENDENCY_SCHEMA = "newsroom.increment9.fault-dependency-evidence.v1"
FAULT_BUNDLE_SCHEMA = "newsroom.increment9.fault-evidence-bundle.v1"
FAULT_OUTCOME_SCHEMA = "newsroom.increment9.fault-campaign-outcome.v1"
MAX_RECORD_BYTES = 1_048_576
_TIMESTAMP = re.compile(
    r"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])T"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\.[0-9]{6}Z\Z"
)
EXPECTED_DEPENDENCIES = (490, 491, 492, 493, 494)


class FaultCampaignError(ValueError):
    """9C2 evidence is absent, inconsistent or non-canonical."""


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for name, item in pairs:
        if type(name) is not str or name in value:
            raise FaultCampaignError("fault evidence names are invalid or duplicated")
        value[name] = item
    return value


def _document(raw: bytes, schema: str) -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_RECORD_BYTES:
        raise FaultCampaignError("fault evidence record is absent or unbounded")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
        canonical = canonical_json_bytes(value)
    except FaultCampaignError:
        raise
    except (
        UnicodeError,
        json.JSONDecodeError,
        CanonicalizationError,
        RecursionError,
    ) as exc:
        raise FaultCampaignError("fault evidence is not canonical JSON") from exc
    if canonical != raw or type(value) is not dict:
        raise FaultCampaignError("fault evidence bytes differ")
    if value.get("schema_version") != schema:
        raise FaultCampaignError("fault evidence schema differs")
    return value


def _timestamp(value: object, field: str) -> str:
    if type(value) is not str or not _TIMESTAMP.fullmatch(value):
        raise FaultCampaignError(f"{field} timestamp differs")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise FaultCampaignError(f"{field} timestamp differs") from exc
    return value


def _digest(value: object, field: str) -> str:
    if type(value) is not str:
        raise FaultCampaignError(f"{field} digest differs")
    try:
        return validate_sha256_digest(value, field=field)
    except (CanonicalizationError, TypeError, ValueError) as exc:
        raise FaultCampaignError(f"{field} digest differs") from exc


def _git(repo: Path) -> tuple[str, str, str]:
    def run(*arguments: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(repo), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    head = run("rev-parse", "HEAD")
    tree = run("rev-parse", "HEAD^{tree}")
    comparator_blob = run("rev-parse", "HEAD:newsroom/increment9/comparator.py")
    for value in (head, tree, comparator_blob):
        if not re.fullmatch(r"[0-9a-f]{40}", value):
            raise FaultCampaignError("checkout identity differs")
    if run("status", "--porcelain"):
        raise FaultCampaignError("checkout is not clean")
    return head, tree, comparator_blob


def _dependency_evidence(raw: bytes, *, head: str, tree: str) -> dict[str, object]:
    value = _document(raw, DEPENDENCY_SCHEMA)
    if set(value) != {
        "evidence_digest",
        "exact_main_sha",
        "exact_main_tree",
        "issues",
        "observed_at",
        "schema_version",
    }:
        raise FaultCampaignError("dependency evidence fields differ")
    _timestamp(value["observed_at"], "dependency observed_at")
    if value["exact_main_sha"] != head or value["exact_main_tree"] != tree:
        raise FaultCampaignError("dependency evidence checkout differs")
    issues = value["issues"]
    if type(issues) is not list or len(issues) != len(EXPECTED_DEPENDENCIES):
        raise FaultCampaignError("dependency issue inventory differs")
    observed: list[int] = []
    for issue in issues:
        if type(issue) is not dict or set(issue) != {
            "closed_at",
            "evidence_digest",
            "number",
            "state",
        }:
            raise FaultCampaignError("dependency issue fields differ")
        number = issue["number"]
        if type(number) is not int:
            raise FaultCampaignError("dependency issue number differs")
        observed.append(number)
        _digest(issue["evidence_digest"], "dependency issue evidence")
        _timestamp(issue["closed_at"], "dependency issue closed_at")
        if issue["state"] != "CLOSED":
            raise FaultCampaignError("dependency remains open")
    if tuple(observed) != EXPECTED_DEPENDENCIES:
        raise FaultCampaignError("dependency issue order differs")
    claimed = _digest(value["evidence_digest"], "dependency evidence")
    body = dict(value)
    body.pop("evidence_digest")
    if digest_bytes(canonical_json_bytes(body)) != claimed:
        raise FaultCampaignError("dependency evidence digest differs")
    return value


def _phase_inventory() -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for ordinal, arm in enumerate(EXPECTED_COMPARATOR_ARMS, start=1):
        entries.append(
            {
                "decision_bearing": False,
                "kind": "COMPARATOR",
                "ordinal": ordinal,
                "phase_id": f"comparator-{ordinal:02d}-{arm.value.lower().replace('_', '-')}",
                "phase_identity": arm.value,
                "reason": "HIGHER_PRECEDENCE_9B3_STOP",
                "status": "NOT_RUN_DUE_HIGHER_PRECEDENCE_STOP",
            }
        )
    base = len(entries)
    for offset, fault in enumerate(EXPECTED_FAULT_INVENTORY, start=1):
        expected, containment, recovery = EXPECTED_FAULT_BEHAVIOUR[fault]
        entries.append(
            {
                "decision_bearing": False,
                "expected_observation": expected,
                "kind": "FAULT",
                "mandatory_containment": containment,
                "ordinal": base + offset,
                "phase_id": f"fault-{offset:02d}-{fault.value.lower().replace('_', '-')}",
                "phase_identity": fault.value,
                "reason": "HIGHER_PRECEDENCE_9B3_STOP",
                "recovery_action": recovery,
                "status": "NOT_RUN_DUE_HIGHER_PRECEDENCE_STOP",
            }
        )
    return entries


def build_stopped_bundle(
    *,
    repo: Path,
    campaign_bundle_raw: bytes,
    dependency_evidence_raw: bytes,
    observed_at: str,
) -> dict[str, object]:
    _timestamp(observed_at, "observed_at")
    head, tree, comparator_blob = _git(repo)
    try:
        campaign = verify_campaign_bundle(campaign_bundle_raw)
    except CampaignError as exc:
        raise FaultCampaignError("9B3 campaign bundle is invalid") from exc
    launch = campaign["launch_receipt"]
    outcome = campaign["outcome"]
    if (
        launch["disposition"]
        != LaunchDisposition.BLOCKED_BEFORE_FIRST_IO.value
        or launch["decision_bearing_first_io_authorised"] is not False
        or outcome["outcome"] != "BLOCKED"
        or outcome["decision_bearing"] is not False
        or any(value != 0 for value in outcome["zero_counts"].values())
    ):
        raise FaultCampaignError(
            "non-blocked 9B3 evidence requires the separate live 9C2 runner"
        )
    dependencies = _dependency_evidence(
        dependency_evidence_raw, head=head, tree=tree
    )
    phases = _phase_inventory()
    zero_usage = {
        "embedding_calls": 0,
        "fault_injections": 0,
        "gross_gbp_minor_units": 0,
        "model_calls": 0,
        "provider_requests": 0,
        "public_effects": 0,
        "production_mutations": 0,
        "recovery_runs": 0,
        "source_http_attempts": 0,
    }
    outcome_value = {
        "campaign_outcome": "BLOCKED",
        "chronology_reconciled": True,
        "completed_at": observed_at,
        "containment_outcome": "PREVENTED_FIRST_IO",
        "decision_bearing_phase_count": 0,
        "denominator_complete": True,
        "executed_phase_count": 0,
        "fault_campaign_started": False,
        "finding_ids": list(launch["finding_ids"]),
        "higher_precedence_source_digest": campaign["bundle_digest"],
        "not_run_phase_count": len(phases),
        "original_stop_retained": True,
        "recovery_outcome": "NOT_APPLICABLE_NO_EFFECT",
        "schema_version": FAULT_OUTCOME_SCHEMA,
        "stop_reason": StopReason.RIGHTS_OR_CREDENTIAL.value,
        "zero_usage": zero_usage,
    }
    outcome_digest = digest_bytes(canonical_json_bytes(outcome_value))
    body = {
        "campaign_bundle_digest": campaign["bundle_digest"],
        "campaign_file_digest": digest_bytes(campaign_bundle_raw),
        "comparator_contract_git_blob": comparator_blob,
        "dependency_evidence_digest": dependencies["evidence_digest"],
        "exact_main_sha": head,
        "exact_main_tree": tree,
        "outcome": outcome_value,
        "outcome_digest": outcome_digest,
        "owner_plan_digest": INCREMENT_9_SHADOW_PLAN_DIGEST,
        "phase_inventory": phases,
        "phase_inventory_digest": digest_bytes(canonical_json_bytes(phases)),
        "phase_order": list(EXPECTED_PHASE_ORDER),
        "schema_version": FAULT_BUNDLE_SCHEMA,
        "stop_precedence": [item.value for item in EXPECTED_STOP_PRECEDENCE],
    }
    return {**body, "bundle_digest": digest_bytes(canonical_json_bytes(body))}


def verify_fault_bundle(raw: bytes) -> dict[str, object]:
    value = _document(raw, FAULT_BUNDLE_SCHEMA)
    if set(value) != {
        "bundle_digest",
        "campaign_bundle_digest",
        "campaign_file_digest",
        "comparator_contract_git_blob",
        "dependency_evidence_digest",
        "exact_main_sha",
        "exact_main_tree",
        "outcome",
        "outcome_digest",
        "owner_plan_digest",
        "phase_inventory",
        "phase_inventory_digest",
        "phase_order",
        "schema_version",
        "stop_precedence",
    }:
        raise FaultCampaignError("fault bundle fields differ")
    body = dict(value)
    claimed = _digest(body.pop("bundle_digest"), "bundle_digest")
    if digest_bytes(canonical_json_bytes(body)) != claimed:
        raise FaultCampaignError("fault bundle digest differs")
    phases = value["phase_inventory"]
    outcome = value["outcome"]
    if type(phases) is not list or type(outcome) is not dict:
        raise FaultCampaignError("fault bundle inventory differs")
    if digest_bytes(canonical_json_bytes(phases)) != value["phase_inventory_digest"]:
        raise FaultCampaignError("fault phase inventory digest differs")
    if digest_bytes(canonical_json_bytes(outcome)) != value["outcome_digest"]:
        raise FaultCampaignError("fault outcome digest differs")
    if phases != _phase_inventory():
        raise FaultCampaignError("fault phase inventory is not exact")
    if (
        outcome.get("schema_version") != FAULT_OUTCOME_SCHEMA
        or outcome.get("campaign_outcome") != "BLOCKED"
        or outcome.get("fault_campaign_started") is not False
        or outcome.get("executed_phase_count") != 0
        or outcome.get("not_run_phase_count") != len(phases)
        or any(item.get("status") != "NOT_RUN_DUE_HIGHER_PRECEDENCE_STOP" for item in phases)
        or any(value != 0 for value in outcome.get("zero_usage", {}).values())
    ):
        raise FaultCampaignError("fault stop outcome differs")
    return value


def _write_protected(path: Path, value: Mapping[str, object]) -> None:
    path = path.resolve()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        raise FaultCampaignError("protected evidence parent is too permissive")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_json_bytes(dict(value)))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _self_test() -> None:
    phases = _phase_inventory()
    assert len(phases) == 26
    assert len([item for item in phases if item["kind"] == "COMPARATOR"]) == 8
    assert len([item for item in phases if item["kind"] == "FAULT"]) == 18
    assert [item["ordinal"] for item in phases] == list(range(1, 27))
    assert all(
        item["status"] == "NOT_RUN_DUE_HIGHER_PRECEDENCE_STOP"
        for item in phases
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    seal = subparsers.add_parser("seal-upstream-stop")
    seal.add_argument("--repo", type=Path, required=True)
    seal.add_argument("--campaign-bundle", type=Path, required=True)
    seal.add_argument("--dependency-evidence", type=Path, required=True)
    seal.add_argument("--observed-at", required=True)
    seal.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--bundle", type=Path, required=True)
    subparsers.add_parser("self-test")
    args = parser.parse_args(argv)
    try:
        if args.command == "self-test":
            _self_test()
            print("SELF_TEST_PASS")
            return 0
        if args.command == "verify":
            value = verify_fault_bundle(args.bundle.read_bytes())
            print(
                json.dumps(
                    {
                        "bundle_digest": value["bundle_digest"],
                        "status": "VERIFIED",
                    },
                    sort_keys=True,
                )
            )
            return 0
        value = build_stopped_bundle(
            repo=args.repo,
            campaign_bundle_raw=args.campaign_bundle.read_bytes(),
            dependency_evidence_raw=args.dependency_evidence.read_bytes(),
            observed_at=args.observed_at,
        )
        _write_protected(args.output, value)
        print(
            json.dumps(
                {
                    "bundle_digest": value["bundle_digest"],
                    "outcome": value["outcome"]["campaign_outcome"],
                },
                sort_keys=True,
            )
        )
        return 0
    except (
        CampaignError,
        FaultCampaignError,
        OSError,
        subprocess.CalledProcessError,
    ) as exc:
        print(f"increment9_fault_campaign: {exc}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
