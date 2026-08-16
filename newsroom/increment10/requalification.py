"""Canonical Increment 10R0 requalification and no-effect entry decision.

The retained packet narrows Increment 10 to a loopback-only fixture canary.  It
creates planning authority only after signed 10R0 closeout; importing it never
performs intake, network, credential, reviewer, publication or production work.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes

REQUALIFICATION_PATH = Path(__file__).with_name("requalification_v1.json")
EXPECTED_REQUALIFICATION_DIGEST = (
    "sha256:0b7bf344c60e7d73490a571f6638ab46acc9194f1eabee68c1158e26da7b5747"
)
EXPECTED_RESIDUAL_GATES = (
    "BASELINE_CREDENTIAL_SCOPES",
    "EFFECTIVE_MANIFEST_CURRENT",
    "EGRESS_ALLOWLIST_ENFORCED",
    "KILL_SWITCH_READY",
    "NO_ACTIVE_HUMAN_EMERGENCY_STOP",
    "PREFUNDED_WALLET_AVAILABLE",
    "PRODUCTION_NONMUTATION_BASELINE",
    "PROSPECTIVE_RUN_AUTHORITY",
    "PROTECTED_STORAGE_READY",
    "PROVIDER_TERMS_CURRENT",
    "RIGHTS_HK-01",
    "RIGHTS_HK-02",
    "RIGHTS_HK-04",
    "RIGHTS_RAD-01",
    "RIGHTS_RAD-02",
    "RIGHTS_UK-01",
    "RIGHTS_UK-02",
    "RIGHTS_UK-03",
    "RIGHTS_UK-05",
    "RIGHTS_UK-10",
)
EXPECTED_ZERO_TOLERANCE = (
    "BUDGET_OVERRUN",
    "DEAD_LETTER",
    "DISTRACTOR_FALSE_MERGE",
    "GAP",
    "PROHIBITED_EFFECT",
    "PROVENANCE_FAILURE",
    "RIGHTS_FAILURE",
    "SCOPE_FAILURE",
    "SILENT_LOSS",
    "TEMPORAL_FAILURE",
    "TRUST_LABEL_FAILURE",
    "UNSUPPORTED_MATERIAL_CLAIM",
)
EXPECTED_REQUIREMENTS = tuple(f"EINT-FX-{number:03d}" for number in range(1, 11))
EXPECTED_OUTCOMES = (
    "REMAIN_BLOCKED",
    "RETURN_TO_BOUNDED_SHADOW",
    "ELIGIBLE_FOR_INCREMENT10_PLAN",
)
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class RequalificationError(ValueError):
    """The Increment 10R0 authority packet is absent, changed or unsafe."""


class RequalificationOutcome(StrEnum):
    REMAIN_BLOCKED = "REMAIN_BLOCKED"
    RETURN_TO_BOUNDED_SHADOW = "RETURN_TO_BOUNDED_SHADOW"
    ELIGIBLE_FOR_INCREMENT10_PLAN = "ELIGIBLE_FOR_INCREMENT10_PLAN"


@dataclass(frozen=True, slots=True)
class ResidualGate:
    gate_id: str
    classification: str
    retained_status: str
    downstream_owner: str
    prospective_evidence_path: str


@dataclass(frozen=True, slots=True)
class Requirement:
    requirement_id: str
    name: str
    authority: str
    text: str


@dataclass(frozen=True, slots=True)
class ZeroTolerancePath:
    finding_id: str
    retained_status: str
    required_observed_count: int
    downstream_owner: str
    prospective_evidence_path: str


@dataclass(frozen=True, slots=True)
class RequalificationPacket:
    schema_version: str
    packet_id: str
    issue_number: int
    parent_issue_number: int
    upstream: Mapping[str, object]
    approval: Mapping[str, object]
    proposed_canary_scope: Mapping[str, object]
    residual_gates: tuple[ResidualGate, ...]
    zero_tolerance_paths: tuple[ZeroTolerancePath, ...]
    operational_admission: Mapping[str, object]
    requirements: tuple[Requirement, ...]
    prerequisite_bindings: Mapping[str, object]
    outcome_vocabulary: tuple[str, ...]
    decision: Mapping[str, object]
    non_effects: Mapping[str, object]
    packet_digest: str

    @property
    def outcome(self) -> RequalificationOutcome:
        return RequalificationOutcome(str(self.decision["outcome"]))

    @property
    def permits_increment10_plan(self) -> bool:
        return (
            self.outcome is RequalificationOutcome.ELIGIBLE_FOR_INCREMENT10_PLAN
            and self.decision["downstream_plan_authorised_after_signed_10r0_close"]
            is True
            and self.decision["runtime_authorised"] is False
        )


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if type(key) is not str or key in result:
            raise RequalificationError(
                "requalification JSON names are invalid or duplicated"
            )
        result[key] = value
    return result


def _object(value: object, field: str) -> dict[str, object]:
    if type(value) is not dict:
        raise RequalificationError(f"{field} must be an object")
    return value


def _keys(value: Mapping[str, object], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise RequalificationError(f"{field} fields differ")


def _strings(value: object, field: str) -> tuple[str, ...]:
    if type(value) is not list or any(
        type(item) is not str or not item for item in value
    ):
        raise RequalificationError(f"{field} must contain bounded strings")
    result = tuple(value)
    if len(result) != len(set(result)):
        raise RequalificationError(f"{field} contains duplicates")
    return result


def _freeze(value: object) -> object:
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


def _mapping(value: object, field: str) -> Mapping[str, object]:
    frozen = _freeze(_object(value, field))
    assert isinstance(frozen, Mapping)
    return frozen


def _residual(value: object) -> ResidualGate:
    raw = _object(value, "residual gate")
    _keys(
        raw,
        {
            "gate_id",
            "classification",
            "retained_status",
            "downstream_owner",
            "prospective_evidence_path",
        },
        "residual gate",
    )
    return ResidualGate(**raw)  # type: ignore[arg-type]


def _requirement(value: object) -> Requirement:
    raw = _object(value, "Evidence Intake requirement")
    _keys(
        raw,
        {"requirement_id", "name", "authority", "text"},
        "Evidence Intake requirement",
    )
    return Requirement(**raw)  # type: ignore[arg-type]


def _zero_path(value: object) -> ZeroTolerancePath:
    raw = _object(value, "zero-tolerance path")
    _keys(
        raw,
        {
            "finding_id",
            "retained_status",
            "required_observed_count",
            "downstream_owner",
            "prospective_evidence_path",
        },
        "zero-tolerance path",
    )
    return ZeroTolerancePath(**raw)  # type: ignore[arg-type]


def _validate(packet: RequalificationPacket) -> None:
    if packet.schema_version != "newsroom.increment10.requalification.v1":
        raise RequalificationError("requalification schema differs")
    if packet.packet_id != "increment10r0-local-fixture-canary-requalification-v1":
        raise RequalificationError("requalification identity differs")
    if (packet.issue_number, packet.parent_issue_number) != (526, 150):
        raise RequalificationError("requalification issue identity differs")
    upstream = packet.upstream
    _keys(
        upstream,
        {
            "closeout_digest",
            "commit",
            "exact_main_run",
            "increment10_eligible",
            "manifest_digest",
            "retained_disposition",
            "tree",
        },
        "upstream",
    )
    if (
        upstream["commit"] != "bd9ce46262a9286080e0dc5d648e33f94a9c6178"
        or upstream["tree"] != "1b3f69d305539432937ce5fdd8242bea83a1d659"
        or upstream["exact_main_run"] != 31927978494
        or upstream["retained_disposition"] != "BLOCKED_ACTIVE_COVERAGE"
        or upstream["increment10_eligible"] is not False
        or not _SHA.fullmatch(str(upstream["commit"]))
        or not _SHA.fullmatch(str(upstream["tree"]))
        or not _DIGEST.fullmatch(str(upstream["closeout_digest"]))
        or not _DIGEST.fullmatch(str(upstream["manifest_digest"]))
    ):
        raise RequalificationError("upstream blocked authority differs")

    approval = packet.approval
    _keys(
        approval,
        {
            "approval_record",
            "approved_at",
            "approved_by",
            "implementation_after_10r0_authorised",
            "live_effect_authorised",
            "status",
        },
        "approval",
    )
    if approval != {
        "approval_record": "https://github.com/fol2/newsroom/issues/526#issuecomment-5306443736",
        "approved_at": "2026-08-16T08:03:08Z",
        "approved_by": "github:fol2",
        "implementation_after_10r0_authorised": False,
        "live_effect_authorised": False,
        "status": "OWNER_APPROVED_FOR_10R0_REQUALIFICATION",
    }:
        raise RequalificationError("10R0 approval differs")

    scope = packet.proposed_canary_scope
    _keys(
        scope,
        {
            "candidate_version_ids",
            "decision_bearing_for",
            "destination",
            "excluded",
            "intake_version",
            "purpose",
            "public_effect",
        },
        "proposed canary scope",
    )
    if (
        scope["purpose"] != "NARROWER_LOCAL_QUALIFICATION_RUN"
        or scope["destination"] != "local://increment10/evidence-intake-fixture-v1"
        or scope["public_effect"] is not False
        or tuple(scope["candidate_version_ids"])
        != (
            "candidate-version:increment10-fixture-001",
            "candidate-version:increment10-fixture-002",
            "candidate-version:increment10-fixture-003",
        )
        or set(scope["excluded"])
        != {
            "EXTERNAL_EVIDENCE_ACQUISITION",
            "LIVE_SOURCE_BYTES",
            "PROVIDER_OR_MODEL_EXECUTION",
            "HUMAN_REVIEW_OF_LIVE_EVIDENCE",
            "PUBLICATION",
            "PRODUCTION_AUTHORITY",
        }
    ):
        raise RequalificationError("local fixture canary scope differs")

    if tuple(item.gate_id for item in packet.residual_gates) != EXPECTED_RESIDUAL_GATES:
        raise RequalificationError("twenty-gate inventory differs")
    if any(
        item.retained_status != "MISSING" or not item.prospective_evidence_path
        for item in packet.residual_gates
    ):
        raise RequalificationError("residual gate truth differs")
    if {item.classification for item in packet.residual_gates} != {
        "BUDGET",
        "CREDENTIAL_EGRESS",
        "OPERATIONAL_ADMISSION",
        "OWNER_DECISION",
        "RIGHTS_LICENCE",
        "TECHNICAL_READINESS",
    }:
        raise RequalificationError("residual gate classifications differ")

    if (
        tuple(item.finding_id for item in packet.zero_tolerance_paths)
        != EXPECTED_ZERO_TOLERANCE
    ):
        raise RequalificationError("zero-tolerance inventory differs")
    if any(
        item.retained_status != "NOT_EVALUATED"
        or item.required_observed_count != 0
        or not item.prospective_evidence_path
        for item in packet.zero_tolerance_paths
    ):
        raise RequalificationError("zero-tolerance prospective path differs")

    if (
        tuple(item.requirement_id for item in packet.requirements)
        != EXPECTED_REQUIREMENTS
    ):
        raise RequalificationError("Evidence Intake requirement inventory differs")
    if any(
        item.authority != "EXPLICIT_OWNER_AUTHORISED_FOR_LOCAL_FIXTURE_CANARY_ONLY"
        for item in packet.requirements
    ):
        raise RequalificationError("Evidence Intake requirement authority differs")

    admission = packet.operational_admission
    if admission != {
        "compatibility": "COMPATIBLE_WITH_LOCAL_FIXTURE_CANARY_PLANNING_ONLY",
        "currentness_rule": "Exact Increment 8 signed admission and all schema, migration, operational-profile and non-effect identities must be rechecked at #527 plan freeze and #532/#533 admission; any drift blocks.",
        "exact_main_run": 31871581163,
        "retained_verdict": "FIXTURE_OPERATIONAL_ADMITTED",
        "subject_digest": "sha256:a59b2359890341b58208d9c8d2c7d641a870b2f87fb1866d254c9b280d74eab3",
    }:
        raise RequalificationError("Operational Admission binding differs")

    if packet.outcome_vocabulary != EXPECTED_OUTCOMES:
        raise RequalificationError("closed outcome vocabulary differs")
    decision = packet.decision
    _keys(
        decision,
        {
            "downstream_plan_authorised_after_signed_10r0_close",
            "outcome",
            "reason_ids",
            "runtime_authorised",
        },
        "decision",
    )
    if (
        decision["outcome"] != "ELIGIBLE_FOR_INCREMENT10_PLAN"
        or decision["downstream_plan_authorised_after_signed_10r0_close"] is not True
        or decision["runtime_authorised"] is not False
        or not tuple(decision["reason_ids"])
    ):
        raise RequalificationError("requalification decision differs")

    non_effects = packet.non_effects
    if set(non_effects) != {
        "credential_use",
        "decision_bearing_canary",
        "evidence_intake",
        "external_egress",
        "external_spend_gbp_minor_units",
        "live_source_call",
        "provider_model_embedding_reviewer_call",
        "publication",
        "production_activation",
        "production_mutation",
        "public_dispatch",
    }:
        raise RequalificationError("non-effect inventory differs")
    if any(value not in (False, 0) for value in non_effects.values()):
        raise RequalificationError("10R0 creates a prohibited effect")
    budgets = packet.prerequisite_bindings.get("budget")
    egress = packet.prerequisite_bindings.get("egress")
    credentials = packet.prerequisite_bindings.get("credentials")
    if (
        not isinstance(budgets, Mapping)
        or any(
            budgets[key] != 0
            for key in (
                "external_requests",
                "gross_gbp_minor_units",
                "model_tokens",
                "non_loopback_bytes",
                "provider_requests",
                "reviewer_minutes",
            )
        )
        or not isinstance(egress, Mapping)
        or egress.get("allowed_hosts") != ()
        or egress.get("loopback_only") is not True
        or not isinstance(credentials, Mapping)
        or credentials.get("allowed_classes") != ()
        or credentials.get("secret_locations") != ()
    ):
        raise RequalificationError("closed-world prerequisite boundary differs")


def load_requalification(path: Path = REQUALIFICATION_PATH) -> RequalificationPacket:
    if not isinstance(path, Path):
        raise RequalificationError("requalification path must be pathlib.Path")
    try:
        raw = path.read_bytes()
        value = json.loads(
            raw.decode("utf-8", errors="strict"), object_pairs_hook=_pairs
        )
    except RequalificationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RequalificationError("cannot read requalification packet") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise RequalificationError("requalification packet is not exact canonical JSON")
    if digest_bytes(raw) != EXPECTED_REQUALIFICATION_DIGEST:
        raise RequalificationError("requalification packet bytes differ")
    _keys(value, {"payload", "schema_version"}, "requalification")
    payload = _object(value["payload"], "payload")
    _keys(
        payload,
        {
            "approval",
            "decision",
            "evidence_intake_requirements",
            "issue_number",
            "non_effects",
            "operational_admission",
            "outcome_vocabulary",
            "packet_id",
            "parent_issue_number",
            "prerequisite_bindings",
            "proposed_canary_scope",
            "residual_gate_inventory",
            "upstream",
            "zero_tolerance_remediation",
        },
        "payload",
    )
    try:
        packet = RequalificationPacket(
            schema_version=str(value["schema_version"]),
            packet_id=str(payload["packet_id"]),
            issue_number=int(payload["issue_number"]),
            parent_issue_number=int(payload["parent_issue_number"]),
            upstream=_mapping(payload["upstream"], "upstream"),
            approval=_mapping(payload["approval"], "approval"),
            proposed_canary_scope=_mapping(
                payload["proposed_canary_scope"], "proposed canary scope"
            ),
            residual_gates=tuple(
                _residual(item) for item in payload["residual_gate_inventory"]
            ),  # type: ignore[union-attr]
            zero_tolerance_paths=tuple(
                _zero_path(item) for item in payload["zero_tolerance_remediation"]
            ),  # type: ignore[union-attr]
            operational_admission=_mapping(
                payload["operational_admission"], "Operational Admission"
            ),
            requirements=tuple(
                _requirement(item) for item in payload["evidence_intake_requirements"]
            ),  # type: ignore[union-attr]
            prerequisite_bindings=_mapping(
                payload["prerequisite_bindings"], "prerequisite bindings"
            ),
            outcome_vocabulary=_strings(
                payload["outcome_vocabulary"], "outcome vocabulary"
            ),
            decision=_mapping(payload["decision"], "decision"),
            non_effects=_mapping(payload["non_effects"], "non-effects"),
            packet_digest=digest_bytes(raw),
        )
    except (TypeError, ValueError, KeyError) as exc:
        if isinstance(exc, RequalificationError):
            raise
        raise RequalificationError("requalification payload is malformed") from exc
    _validate(packet)
    return packet


INCREMENT_10_REQUALIFICATION = load_requalification()
INCREMENT_10_REQUALIFICATION_DIGEST = INCREMENT_10_REQUALIFICATION.packet_digest
