#!/usr/bin/env python3
"""Fail-closed authority and evidence sealer for Increment 9B3.

The program performs no network, provider, model, embedding, publication or
production write.  It verifies retained first-I/O gate records and either emits
an immutable launch authority or an explicit pre-I/O BLOCKED campaign outcome.
A separate controller may consume an AUTHORISED_TO_LAUNCH receipt; absence or
failure of any gate never becomes authority.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Mapping, Sequence

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.increment9.credential_scopes import (
    CredentialScopeError,
    bind_campaign_credential_classes,
)
from newsroom.increment9.egress_allowlist import (
    EgressAllowlistError,
    bind_campaign_egress_allowlist,
)
from newsroom.increment9.plan import (
    INCREMENT_9_SHADOW_PLAN,
    INCREMENT_9_SHADOW_PLAN_DIGEST,
)
from newsroom.increment9.prefunded_wallet import (
    PrefundedWalletError,
    bind_campaign_prefunded_wallet,
)
from newsroom.increment9.protected_storage import write_protected_artefact

GATE_RECORD_SCHEMA = "newsroom.increment9.campaign-gate.v1"
CAMPAIGN_BUNDLE_SCHEMA = "newsroom.increment9.campaign-evidence-bundle.v1"
LAUNCH_RECEIPT_SCHEMA = "newsroom.increment9.campaign-launch-receipt.v1"
OUTCOME_SCHEMA = "newsroom.increment9.campaign-outcome.v1"
MAX_RECORD_BYTES = 1_048_576
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/\-]{0,255}\Z")
_TIMESTAMP = re.compile(
    r"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])T"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\.[0-9]{6}Z\Z"
)

DEPENDENCY_GATES = (
    "ISSUE_488_OWNER_PLAN",
    "ISSUE_489_SHADOW_CONTRACT",
    "ISSUE_490_ISOLATED_DEPLOYMENT",
    "ISSUE_491_FROZEN_EPOCH",
    "ISSUE_492_CONTROLLER_QUALIFICATION",
)
RUNTIME_GATES = (
    "EFFECTIVE_MANIFEST_CURRENT",
    "PROSPECTIVE_RUN_AUTHORITY",
    "PROVIDER_TERMS_CURRENT",
    "BASELINE_CREDENTIAL_SCOPES",
    "EGRESS_ALLOWLIST_ENFORCED",
    "PREFUNDED_WALLET_AVAILABLE",
    "PROTECTED_STORAGE_READY",
    "KILL_SWITCH_READY",
    "NO_ACTIVE_HUMAN_EMERGENCY_STOP",
    "PRODUCTION_NONMUTATION_BASELINE",
)


class CampaignError(ValueError):
    """Untrusted campaign input or evidence failed closed."""


class GateStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    MISSING = "MISSING"
    EXPIRED = "EXPIRED"


class LaunchDisposition(StrEnum):
    AUTHORISED_TO_LAUNCH = "AUTHORISED_TO_LAUNCH"
    BLOCKED_BEFORE_FIRST_IO = "BLOCKED_BEFORE_FIRST_IO"


class CampaignOutcome(StrEnum):
    COMPLETED = "COMPLETED"
    EARLY_STOPPED = "EARLY_STOPPED"
    FAILED = "FAILED"
    INCONCLUSIVE = "INCONCLUSIVE"
    BLOCKED = "BLOCKED"


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if type(name) is not str or name in result:
            raise CampaignError("campaign JSON names are invalid or duplicated")
        result[name] = value
    return result


def _token(value: object, field: str) -> str:
    if type(value) is not str or not _TOKEN.fullmatch(value):
        raise CampaignError(f"{field} token differs")
    return value


def _timestamp(value: object, field: str) -> str:
    if type(value) is not str or not _TIMESTAMP.fullmatch(value):
        raise CampaignError(f"{field} timestamp differs")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise CampaignError(f"{field} timestamp differs") from exc
    return value


def _instant(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def _digest(value: object, field: str) -> str:
    if type(value) is not str:
        raise CampaignError(f"{field} digest differs")
    try:
        return validate_sha256_digest(value, field=field)
    except (CanonicalizationError, TypeError, ValueError) as exc:
        raise CampaignError(f"{field} digest differs") from exc


def _exact_document(raw: bytes, *, schema: str) -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_RECORD_BYTES:
        raise CampaignError("campaign record is absent or unbounded")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
        canonical = canonical_json_bytes(value)
    except CampaignError:
        raise
    except (
        UnicodeError,
        json.JSONDecodeError,
        CanonicalizationError,
        RecursionError,
    ) as exc:
        raise CampaignError("campaign record is not canonical JSON") from exc
    if canonical != raw or type(value) is not dict:
        raise CampaignError("campaign record bytes are not exact canonical JSON")
    if value.get("schema_version") != schema:
        raise CampaignError("campaign record schema differs")
    return value


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _git(repo: Path) -> tuple[str, str]:
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
    if not re.fullmatch(r"[0-9a-f]{40}", head) or not re.fullmatch(
        r"[0-9a-f]{40}", tree
    ):
        raise CampaignError("checkout identity differs")
    if run("status", "--porcelain"):
        raise CampaignError("checkout is not clean")
    return head, tree


def _source_records() -> Mapping[str, Mapping[str, object]]:
    decisions = {
        item.decision_id: item.selection
        for item in INCREMENT_9_SHADOW_PLAN.owner_decisions
    }
    records = decisions["OD-001"]["rights_record_version_per_source"]
    endpoints = decisions["OD-001"]["source_ids_and_exact_endpoints"]
    if (
        not isinstance(records, Mapping)
        or not isinstance(endpoints, Mapping)
        or set(records) != set(endpoints)
    ):
        raise CampaignError("OD-001 source authority differs")
    return records


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def required_gate_ids() -> tuple[str, ...]:
    rights = tuple(f"RIGHTS_{source_id}" for source_id in sorted(_source_records()))
    return tuple(sorted((*DEPENDENCY_GATES, *RUNTIME_GATES, *rights)))


@dataclass(frozen=True, slots=True)
class GateRecord:
    gate_id: str
    observed_at: str
    expires_at: str
    exact_main_sha: str
    exact_main_tree: str
    subject_digest: str
    evidence_digest: str
    issuer_id: str
    status: GateStatus
    credential_classes: tuple[str, ...] = ()
    reviewer_families: tuple[str, ...] = ()

    @classmethod
    def from_bytes(cls, raw: bytes) -> "GateRecord":
        value = _exact_document(raw, schema=GATE_RECORD_SCHEMA)
        fields = {
            "credential_classes",
            "evidence_digest",
            "exact_main_sha",
            "exact_main_tree",
            "expires_at",
            "gate_id",
            "issuer_id",
            "observed_at",
            "reviewer_families",
            "schema_version",
            "status",
            "subject_digest",
        }
        if set(value) != fields:
            raise CampaignError("campaign gate fields differ")
        credentials = value["credential_classes"]
        reviewers = value["reviewer_families"]
        if type(credentials) is not list or type(reviewers) is not list:
            raise CampaignError("campaign gate arrays differ")
        credential_values = tuple(
            _token(item, "credential class") for item in credentials
        )
        reviewer_values = tuple(_token(item, "reviewer family") for item in reviewers)
        if credential_values != tuple(sorted(set(credential_values))):
            raise CampaignError("credential classes are not unique and sorted")
        if reviewer_values != tuple(sorted(set(reviewer_values))):
            raise CampaignError("reviewer families are not unique and sorted")
        try:
            status = GateStatus(value["status"])
        except (TypeError, ValueError) as exc:
            raise CampaignError("campaign gate status differs") from exc
        return cls(
            gate_id=_token(value["gate_id"], "gate_id"),
            observed_at=_timestamp(value["observed_at"], "observed_at"),
            expires_at=_timestamp(value["expires_at"], "expires_at"),
            exact_main_sha=_token(value["exact_main_sha"], "exact_main_sha"),
            exact_main_tree=_token(value["exact_main_tree"], "exact_main_tree"),
            subject_digest=_digest(value["subject_digest"], "subject_digest"),
            evidence_digest=_digest(value["evidence_digest"], "evidence_digest"),
            issuer_id=_token(value["issuer_id"], "issuer_id"),
            status=status,
            credential_classes=credential_values,
            reviewer_families=reviewer_values,
        )

    def primitive(self) -> dict[str, object]:
        return {
            "credential_classes": list(self.credential_classes),
            "evidence_digest": self.evidence_digest,
            "exact_main_sha": self.exact_main_sha,
            "exact_main_tree": self.exact_main_tree,
            "expires_at": self.expires_at,
            "gate_id": self.gate_id,
            "issuer_id": self.issuer_id,
            "observed_at": self.observed_at,
            "reviewer_families": list(self.reviewer_families),
            "schema_version": GATE_RECORD_SCHEMA,
            "status": self.status.value,
            "subject_digest": self.subject_digest,
        }

    @property
    def digest(self) -> str:
        return digest_bytes(canonical_json_bytes(self.primitive()))


def _read_gates(directory: Path) -> tuple[dict[str, GateRecord], list[str]]:
    records: dict[str, GateRecord] = {}
    invalid: list[str] = []
    if not directory.exists():
        return records, invalid
    if not directory.is_dir():
        raise CampaignError("gate path is not a directory")
    for path in sorted(directory.iterdir()):
        if path.name.startswith("."):
            continue
        if not path.is_file() or path.suffix != ".json":
            invalid.append(f"INVALID_GATE_PATH:{path.name}")
            continue
        try:
            record = GateRecord.from_bytes(path.read_bytes())
        except (CampaignError, OSError):
            invalid.append(f"INVALID_GATE_RECORD:{path.name}")
            continue
        if record.gate_id in records:
            invalid.append(f"DUPLICATE_GATE:{record.gate_id}")
            continue
        records[record.gate_id] = record
    return records, invalid


def _gate_findings(
    records: Mapping[str, GateRecord], *, head: str, tree: str, observed_at: str
) -> list[str]:
    required = set(required_gate_ids())
    findings: list[str] = []
    for extra in sorted(set(records) - required):
        findings.append(f"UNEXPECTED_GATE:{extra}")
    now = _instant(observed_at)
    for gate_id in sorted(required):
        record = records.get(gate_id)
        if record is None:
            findings.append(f"MISSING_GATE:{gate_id}")
            continue
        if record.status is not GateStatus.PASS:
            findings.append(f"NONPASS_GATE:{gate_id}:{record.status.value}")
        if record.exact_main_sha != head or record.exact_main_tree != tree:
            findings.append(f"STALE_CHECKOUT_GATE:{gate_id}")
        if _instant(record.observed_at) > now or _instant(record.expires_at) <= now:
            findings.append(f"EXPIRED_OR_FUTURE_GATE:{gate_id}")
        if gate_id.startswith("RIGHTS_"):
            source_id = gate_id.removeprefix("RIGHTS_")
            expected = _source_records()[source_id]
            if record.subject_digest != digest_bytes(
                canonical_json_bytes(dict(expected))
            ):
                findings.append(f"RIGHTS_SUBJECT_MISMATCH:{source_id}")
            if len(record.reviewer_families) != 3:
                findings.append(f"RIGHTS_REVIEW_INDEPENDENCE_MISSING:{source_id}")
        if gate_id == "BASELINE_CREDENTIAL_SCOPES":
            try:
                bind_campaign_credential_classes(record.credential_classes)
            except CredentialScopeError:
                findings.append("BASELINE_CREDENTIAL_CLASSES_DIFFER")
        if gate_id == "EGRESS_ALLOWLIST_ENFORCED":
            try:
                bind_campaign_egress_allowlist()
            except EgressAllowlistError:
                findings.append("EGRESS_ALLOWLIST_UNBOUND")
        if gate_id == "PREFUNDED_WALLET_AVAILABLE":
            try:
                bind_campaign_prefunded_wallet()
            except PrefundedWalletError:
                findings.append("PREFUNDED_WALLET_UNBOUND")
    return sorted(set(findings))


def build_bundle(
    *, repo: Path, gate_directory: Path, campaign_id: str, observed_at: str
) -> dict[str, object]:
    _token(campaign_id, "campaign_id")
    _timestamp(observed_at, "observed_at")
    head, tree = _git(repo)
    records, invalid = _read_gates(gate_directory)
    findings = sorted(
        set(
            (
                *invalid,
                *_gate_findings(
                    records, head=head, tree=tree, observed_at=observed_at
                ),
            )
        )
    )
    authorised = not findings
    disposition = (
        LaunchDisposition.AUTHORISED_TO_LAUNCH
        if authorised
        else LaunchDisposition.BLOCKED_BEFORE_FIRST_IO
    )
    gate_inventory = [
        {"gate_id": gate_id, "record_digest": records[gate_id].digest}
        for gate_id in sorted(records)
    ]
    launch = {
        "authorises_canary": False,
        "authorises_evidence_intake": False,
        "authorises_production_activation": False,
        "authorises_production_mutation": False,
        "authorises_publication": False,
        "campaign_id": campaign_id,
        "decision_bearing_first_io_authorised": authorised,
        "disposition": disposition.value,
        "exact_main_sha": head,
        "exact_main_tree": tree,
        "finding_ids": findings,
        "gate_inventory": gate_inventory,
        "observed_at": observed_at,
        "plan_digest": INCREMENT_9_SHADOW_PLAN_DIGEST,
        "schema_version": LAUNCH_RECEIPT_SCHEMA,
    }
    launch_digest = digest_bytes(canonical_json_bytes(launch))
    required_exposure = next(
        item.selection["minimum_exposure"]
        for item in INCREMENT_9_SHADOW_PLAN.owner_decisions
        if item.decision_id == "OD-008"
    )
    zero_counts = {
        "decision_bearing_cases": 0,
        "embedding_calls": 0,
        "gross_gbp_minor_units": 0,
        "model_calls": 0,
        "provider_requests": 0,
        "public_effects": 0,
        "production_mutations": 0,
        "source_http_attempts": 0,
        "stored_bytes": 0,
    }
    outcome = {
        "campaign_id": campaign_id,
        "completed_at": observed_at,
        "decision_bearing": False,
        "denominator_complete": True,
        "finding_ids": findings,
        "inventory_reconciled": True,
        "launch_receipt_digest": launch_digest,
        "outcome": (
            CampaignOutcome.INCONCLUSIVE
            if authorised
            else CampaignOutcome.BLOCKED
        ).value,
        "reason": (
            "LAUNCH_AUTHORITY_ISSUED_CAMPAIGN_NOT_YET_EXECUTED"
            if authorised
            else "MISSING_OR_NONPASS_FIRST_IO_GATE"
        ),
        "run_attempt_inventory": [],
        "schema_version": OUTCOME_SCHEMA,
        "zero_counts": zero_counts,
    }
    outcome_digest = digest_bytes(canonical_json_bytes(outcome))
    report = {
        "budget_usage": zero_counts,
        "exposure_observed": {key: 0 for key in sorted(required_exposure)},
        "exposure_required": _plain(required_exposure),
        "minimum_exposure_met": False,
        "no_public_effect": True,
        "production_nonmutation_observed": True,
        "source_count": len(_source_records()),
    }
    body = {
        "campaign_id": campaign_id,
        "evidence_digests": {
            "launch_receipt": launch_digest,
            "outcome": outcome_digest,
            "report": digest_bytes(canonical_json_bytes(report)),
        },
        "launch_receipt": launch,
        "outcome": outcome,
        "plan_digest": INCREMENT_9_SHADOW_PLAN_DIGEST,
        "report": report,
        "schema_version": CAMPAIGN_BUNDLE_SCHEMA,
    }
    return {**body, "bundle_digest": digest_bytes(canonical_json_bytes(body))}


def verify_bundle(raw: bytes) -> dict[str, object]:
    value = _exact_document(raw, schema=CAMPAIGN_BUNDLE_SCHEMA)
    if set(value) != {
        "bundle_digest",
        "campaign_id",
        "evidence_digests",
        "launch_receipt",
        "outcome",
        "plan_digest",
        "report",
        "schema_version",
    }:
        raise CampaignError("campaign bundle fields differ")
    body = dict(value)
    claimed = _digest(body.pop("bundle_digest", None), "bundle_digest")
    if digest_bytes(canonical_json_bytes(body)) != claimed:
        raise CampaignError("campaign bundle digest differs")
    if body.get("plan_digest") != INCREMENT_9_SHADOW_PLAN_DIGEST:
        raise CampaignError("campaign bundle plan differs")
    launch = body.get("launch_receipt")
    outcome = body.get("outcome")
    report = body.get("report")
    digests = body.get("evidence_digests")
    if not all(type(item) is dict for item in (launch, outcome, report, digests)):
        raise CampaignError("campaign bundle contents differ")
    expected = {
        "launch_receipt": digest_bytes(canonical_json_bytes(launch)),
        "outcome": digest_bytes(canonical_json_bytes(outcome)),
        "report": digest_bytes(canonical_json_bytes(report)),
    }
    if digests != expected:
        raise CampaignError("campaign component digests differ")
    if (
        launch.get("schema_version") != LAUNCH_RECEIPT_SCHEMA
        or outcome.get("schema_version") != OUTCOME_SCHEMA
    ):
        raise CampaignError("campaign component schema differs")
    if (
        launch.get("campaign_id") != body.get("campaign_id")
        or outcome.get("campaign_id") != body.get("campaign_id")
    ):
        raise CampaignError("campaign identity chain differs")
    blocked = (
        launch.get("disposition")
        == LaunchDisposition.BLOCKED_BEFORE_FIRST_IO.value
    )
    if blocked:
        counts = outcome.get("zero_counts")
        if (
            launch.get("decision_bearing_first_io_authorised") is not False
            or outcome.get("outcome") != CampaignOutcome.BLOCKED.value
            or outcome.get("decision_bearing") is not False
            or type(counts) is not dict
            or any(value != 0 for value in counts.values())
            or report.get("no_public_effect") is not True
            or report.get("production_nonmutation_observed") is not True
        ):
            raise CampaignError("blocked campaign non-effect proof differs")
    return value


def _write_protected(path: Path, value: Mapping[str, object]) -> None:
    from newsroom.increment9.protected_storage import ProtectedStorageError

    path = path.resolve()
    try:
        write_protected_artefact(
            path.parent,
            artefact_class="CAMPAIGN_EVIDENCE",
            artefact_id=path.name,
            payload=dict(value),
            target_path=path,
        )
    except ProtectedStorageError as exc:
        raise CampaignError(f"protected storage write failed: {exc}")


def _self_test() -> None:
    assert len(required_gate_ids()) == 25
    assert len(_source_records()) == 10
    sample = GateRecord(
        gate_id="ISSUE_488_OWNER_PLAN",
        observed_at="2026-08-16T00:00:00.000000Z",
        expires_at="2026-08-17T00:00:00.000000Z",
        exact_main_sha="a" * 40,
        exact_main_tree="b" * 40,
        subject_digest="sha256:" + "c" * 64,
        evidence_digest="sha256:" + "d" * 64,
        issuer_id="fixture",
        status=GateStatus.PASS,
    )
    restored = GateRecord.from_bytes(canonical_json_bytes(sample.primitive()))
    assert restored == sample
    tampered = bytearray(canonical_json_bytes(sample.primitive()))
    tampered[-2] ^= 1
    try:
        GateRecord.from_bytes(bytes(tampered))
    except CampaignError:
        pass
    else:  # pragma: no cover - executable self-check
        raise AssertionError("tampered record accepted")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    assess = subparsers.add_parser("assess")
    assess.add_argument("--repo", type=Path, required=True)
    assess.add_argument("--gate-directory", type=Path, required=True)
    assess.add_argument("--campaign-id", required=True)
    assess.add_argument("--observed-at", default=None)
    assess.add_argument("--output", type=Path, required=True)
    assess.add_argument("--accept-blocked", action="store_true")
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
            value = verify_bundle(args.bundle.read_bytes())
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
        observed_at = args.observed_at or _utc_now()
        bundle = build_bundle(
            repo=args.repo,
            gate_directory=args.gate_directory,
            campaign_id=args.campaign_id,
            observed_at=observed_at,
        )
        _write_protected(args.output, bundle)
        disposition = bundle["launch_receipt"]["disposition"]
        print(
            json.dumps(
                {
                    "bundle_digest": bundle["bundle_digest"],
                    "disposition": disposition,
                },
                sort_keys=True,
            )
        )
        if (
            disposition == LaunchDisposition.BLOCKED_BEFORE_FIRST_IO.value
            and not args.accept_blocked
        ):
            return 3
        return 0
    except (CampaignError, OSError, subprocess.CalledProcessError) as exc:
        print(f"increment9_shadow_campaign: {exc}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
