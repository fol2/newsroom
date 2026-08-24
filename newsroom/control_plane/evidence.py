"""CONT-001 Evidence Package for unpublished staging."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Literal

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.control_plane.editorial import StoryCandidateRecord

EVID_012_POLICY_VERSION = "newsroom.evid-012.v1"
GOVERNED_CLAIM_POLICY_VERSION = "newsroom.governed-claim.v1"
EVIDENCE_GATE_POLICY_VERSION = "newsroom.evidence-gates.v1"
GOVERNED_INPUT_SCHEMA_VERSION = "newsroom.governed-input.v1"
EVIDENCE_APPROVAL_POLICY_VERSION = "newsroom.evidence-approval.v1"
EVIDENCE_APPROVAL_PRINCIPAL = "HERMES_EVIDENCE_CONTROLLER"
ORIGINALITY_POLICY_VERSION = "newsroom.cont-originality.v1"


class Evid012QualificationTest(StrEnum):
    LAW_RIGHT_STATUS_POLICY = "LAW_RIGHT_STATUS_POLICY"
    SAFETY_OR_PUBLIC_HEALTH = "SAFETY_OR_PUBLIC_HEALTH"
    ESSENTIAL_SERVICE_DISRUPTION = "ESSENTIAL_SERVICE_DISRUPTION"
    HOUSEHOLD_PRACTICAL_EFFECT = "HOUSEHOLD_PRACTICAL_EFFECT"
    OFFICIAL_ACTION_OR_DEADLINE = "OFFICIAL_ACTION_OR_DEADLINE"
    EXCEPTIONAL_PUBLIC_IMPORTANCE = "EXCEPTIONAL_PUBLIC_IMPORTANCE"


class GovernedClaimStatus(StrEnum):
    CONFIRMED_FACT = "CONFIRMED_FACT"
    EXPRESSLY_PROVISIONAL_FACT = "EXPRESSLY_PROVISIONAL_FACT"
    ATTRIBUTED_CLAIM_OR_OPINION = "ATTRIBUTED_CLAIM_OR_OPINION"
    PUBLISHED_ANALYSIS_OR_FORECAST = "PUBLISHED_ANALYSIS_OR_FORECAST"
    CONTEXTUAL_BACKGROUND = "CONTEXTUAL_BACKGROUND"


class ClaimAuthorityClass(StrEnum):
    RESPONSIBLE_PRIMARY = "RESPONSIBLE_PRIMARY"
    INDEPENDENT_RELIABLE = "INDEPENDENT_RELIABLE"


@dataclass(frozen=True, slots=True)
class GovernedClaimEvidence:
    claim_id: str
    claim: str
    passage_index: int
    supporting_excerpt: str
    source_ids: tuple[str, ...]
    source_record_ids: tuple[str, ...]
    source_authority_decision_ids: tuple[str, ...]
    rights_decision_ids: tuple[str, ...]
    dependency_evidence_ids: tuple[str, ...]
    evidential_origin_ids: tuple[str, ...]
    authority_class: ClaimAuthorityClass
    authority_scope: str
    status: GovernedClaimStatus
    attribution: str
    rendered_assertion_zh_hant_hk: str
    claim_role: Literal["HEADLINE", "SUBSTANTIVE", "CONTEXT"]
    named_entities: tuple[str, ...] = ()
    quotations: tuple[str, ...] = ()
    certainty: Literal["CONFIRMED"] = "CONFIRMED"
    originality_basis: Literal["FACTUAL_REWRITE_REQUIRED"] = "FACTUAL_REWRITE_REQUIRED"
    admitted_use: Literal["PUBLICATION_EVIDENCE"] = "PUBLICATION_EVIDENCE"
    policy_version: str = GOVERNED_CLAIM_POLICY_VERSION

    def __post_init__(self) -> None:
        required = (
            self.claim_id,
            self.claim,
            self.supporting_excerpt,
            self.authority_scope,
            self.attribution,
            self.rendered_assertion_zh_hant_hk,
        )
        if any(not value.strip() for value in required):
            raise ValueError("governed claim evidence fields are required")
        if self.passage_index < 0:
            raise ValueError("governed claim passage index must be non-negative")
        if any(
            not values
            for values in (
                self.source_ids,
                self.source_record_ids,
                self.source_authority_decision_ids,
                self.rights_decision_ids,
                self.dependency_evidence_ids,
                self.evidential_origin_ids,
            )
        ):
            raise ValueError(
                "governed claim requires source, authority, rights and dependency provenance"
            )
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("governed claim source IDs must be unique")
        if any(
            len(set(values)) != len(values)
            for values in (
                self.source_record_ids,
                self.source_authority_decision_ids,
                self.rights_decision_ids,
                self.dependency_evidence_ids,
            )
        ):
            raise ValueError("governed claim provenance IDs must be unique")
        if len(set(self.evidential_origin_ids)) != len(self.evidential_origin_ids):
            raise ValueError("governed claim evidential origins must be unique")
        if self.admitted_use != "PUBLICATION_EVIDENCE":
            raise ValueError("governed claim is not admitted for publication evidence")
        if self.policy_version != GOVERNED_CLAIM_POLICY_VERSION:
            raise ValueError("governed claim policy version is not supported")
        if self.rendered_assertion_zh_hant_hk in {
            self.claim,
            self.supporting_excerpt,
        }:
            raise ValueError("governed claim rendering must be an original assertion")


@dataclass(frozen=True, slots=True)
class EvidenceGateEvidence:
    gate: Literal["CLAIM_TRACEABILITY", "EVIDENCE_SUFFICIENCY", "SOURCE_AUTHORITY"]
    result: Literal["PASS"]
    governed_claim_ids: tuple[str, ...]
    policy_version: str = EVIDENCE_GATE_POLICY_VERSION

    def __post_init__(self) -> None:
        if not self.governed_claim_ids:
            raise ValueError("evidence gate requires governed claim provenance")
        if len(set(self.governed_claim_ids)) != len(self.governed_claim_ids):
            raise ValueError("evidence gate claim provenance must be unique")
        if self.policy_version != EVIDENCE_GATE_POLICY_VERSION:
            raise ValueError("evidence gate policy version is not supported")


@dataclass(frozen=True, slots=True)
class QualificationEvidence:
    test: Evid012QualificationTest
    governed_claim_id: str
    test_evidence: tuple[tuple[str, str], ...]
    policy_version: str = EVID_012_POLICY_VERSION

    def __post_init__(self) -> None:
        try:
            canonical_test = Evid012QualificationTest(self.test)
        except ValueError:
            raise ValueError("qualification test is not in EVID-012") from None
        object.__setattr__(self, "test", canonical_test)
        if not self.governed_claim_id.strip():
            raise ValueError("qualification governed claim is required")
        if self.policy_version != EVID_012_POLICY_VERSION:
            raise ValueError("qualification policy version is not supported")
        evidence = dict(self.test_evidence)
        if len(evidence) != len(self.test_evidence) or any(
            not key.strip() or not value.strip() for key, value in self.test_evidence
        ):
            raise ValueError("qualification test evidence must be unique and complete")
        allowed: dict[Evid012QualificationTest, dict[str, frozenset[str] | None]] = {
            Evid012QualificationTest.LAW_RIGHT_STATUS_POLICY: {
                "change_kind": frozenset(
                    {"LAW", "RIGHT", "STATUS", "OFFICIAL_DEADLINE", "PUBLIC_POLICY"}
                ),
                "new_state": None,
            },
            Evid012QualificationTest.SAFETY_OR_PUBLIC_HEALTH: {
                "effect_class": frozenset(
                    {
                        "INJURY_RISK",
                        "PUBLIC_HEALTH_WARNING",
                        "EVACUATION",
                        "MATERIAL_EXPOSURE",
                    }
                ),
                "affected_group": None,
            },
            Evid012QualificationTest.ESSENTIAL_SERVICE_DISRUPTION: {
                "service_kind": frozenset(
                    {"TRANSPORT", "UTILITY", "SCHOOL", "WORKPLACE", "LOCALITY"}
                ),
                "duration_minutes": None,
                "affected_group": None,
            },
            Evid012QualificationTest.HOUSEHOLD_PRACTICAL_EFFECT: {
                "domain": frozenset(
                    {
                        "MONEY",
                        "WORK",
                        "HOUSING",
                        "EDUCATION",
                        "HEALTHCARE",
                        "UK_HONG_KONG_TRAVEL",
                    }
                ),
                "practical_effect": None,
            },
            Evid012QualificationTest.OFFICIAL_ACTION_OR_DEADLINE: {
                "action_class": frozenset(
                    {"INSTRUCTION", "PROCESS", "OFFICIAL_DEADLINE"}
                ),
                "reader_action": None,
            },
            Evid012QualificationTest.EXCEPTIONAL_PUBLIC_IMPORTANCE: {
                "importance_class": frozenset(
                    {
                        "HONG_KONG_WIDE",
                        "INTERNATIONAL_EMERGENCY",
                        "CONSTITUTIONAL_CHANGE",
                    }
                ),
                "affected_group": None,
            },
        }
        required = allowed[canonical_test]
        if set(evidence) != set(required) or any(
            permitted is not None and evidence[field] not in permitted
            for field, permitted in required.items()
        ):
            raise ValueError("qualification test evidence does not satisfy EVID-012")
        if canonical_test is Evid012QualificationTest.ESSENTIAL_SERVICE_DISRUPTION:
            try:
                duration_minutes = int(evidence["duration_minutes"])
            except ValueError:
                raise ValueError(
                    "qualification disruption duration must be an integer"
                ) from None
            if duration_minutes < 60:
                raise ValueError(
                    "qualification disruption is below the material duration floor"
                )


@dataclass(frozen=True, slots=True)
class EvidencePackage:
    candidate_id: str
    hypothesis_id: str
    signal_ids: tuple[str, ...]
    lead_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    observation_digests: tuple[str, ...]
    passages: tuple[str, ...]
    substantive_new_information: tuple[str, ...] = ()
    governed_claims: tuple[GovernedClaimEvidence, ...] = ()
    qualification_evidence: tuple[QualificationEvidence, ...] = ()
    selection_rationale: str = ""
    geography: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    evidence_gate_results: tuple[tuple[str, str], ...] = ()
    evidence_gate_evidence: tuple[EvidenceGateEvidence, ...] = ()
    freshness_result: str = "MISSING"
    integrity_result: str = "MISSING"
    explicit_exclusions: tuple[str, ...] = ()
    resolved_evidence_records: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.signal_ids or not self.lead_ids or not self.observation_digests:
            raise ValueError(
                "Evidence Package requires Signal, Lead and retained observations"
            )
        if not self.passages:
            raise ValueError("Evidence Package requires at least one retained passage")
        gate_names = tuple(name for name, _result in self.evidence_gate_results)
        if len(set(gate_names)) != len(gate_names):
            raise ValueError("Evidence Package gate names must be unique")
        if any(
            result not in {"PASS", "HOLD", "FAIL", "MISSING"}
            for _name, result in self.evidence_gate_results
        ):
            raise ValueError("Evidence Package gate result is not canonical")
        claim_ids = tuple(item.claim_id for item in self.governed_claims)
        if len(set(claim_ids)) != len(claim_ids):
            raise ValueError("Evidence Package governed claim IDs must be unique")

    @property
    def digest(self) -> str:
        return digest_bytes(
            canonical_json_bytes(
                {
                    "candidate_id": self.candidate_id,
                    "hypothesis_id": self.hypothesis_id,
                    "signal_ids": list(self.signal_ids),
                    "lead_ids": list(self.lead_ids),
                    "source_ids": list(self.source_ids),
                    "observation_digests": list(self.observation_digests),
                    "passages": list(self.passages),
                    "substantive_new_information": list(
                        self.substantive_new_information
                    ),
                    "governed_claims": [
                        {
                            "claim_id": item.claim_id,
                            "claim": item.claim,
                            "passage_index": item.passage_index,
                            "supporting_excerpt": item.supporting_excerpt,
                            "source_ids": list(item.source_ids),
                            "source_record_ids": list(item.source_record_ids),
                            "source_authority_decision_ids": list(
                                item.source_authority_decision_ids
                            ),
                            "rights_decision_ids": list(item.rights_decision_ids),
                            "dependency_evidence_ids": list(
                                item.dependency_evidence_ids
                            ),
                            "evidential_origin_ids": list(item.evidential_origin_ids),
                            "authority_class": item.authority_class.value,
                            "authority_scope": item.authority_scope,
                            "status": item.status.value,
                            "attribution": item.attribution,
                            "rendered_assertion_zh_hant_hk": (
                                item.rendered_assertion_zh_hant_hk
                            ),
                            "claim_role": item.claim_role,
                            "named_entities": list(item.named_entities),
                            "quotations": list(item.quotations),
                            "certainty": item.certainty,
                            "originality_basis": item.originality_basis,
                            "admitted_use": item.admitted_use,
                            "policy_version": item.policy_version,
                        }
                        for item in self.governed_claims
                    ],
                    "qualification_evidence": [
                        {
                            "test": item.test.value,
                            "governed_claim_id": item.governed_claim_id,
                            "test_evidence": [
                                list(value) for value in item.test_evidence
                            ],
                            "policy_version": item.policy_version,
                        }
                        for item in self.qualification_evidence
                    ],
                    "selection_rationale": self.selection_rationale,
                    "geography": list(self.geography),
                    "categories": list(self.categories),
                    "evidence_gate_results": [
                        list(item) for item in self.evidence_gate_results
                    ],
                    "evidence_gate_evidence": [
                        {
                            "gate": item.gate,
                            "result": item.result,
                            "governed_claim_ids": list(item.governed_claim_ids),
                            "policy_version": item.policy_version,
                        }
                        for item in self.evidence_gate_evidence
                    ],
                    "freshness_result": self.freshness_result,
                    "integrity_result": self.integrity_result,
                    "explicit_exclusions": list(self.explicit_exclusions),
                    "resolved_evidence_records": [
                        list(item) for item in self.resolved_evidence_records
                    ],
                }
            )
        )


def package_for(candidate: StoryCandidateRecord) -> EvidencePackage:
    passages = tuple(
        f"{item.source_id}: {item.headline}\n{item.body}".strip()
        for item in candidate.items
    )
    return EvidencePackage(
        candidate_id=candidate.candidate_id,
        hypothesis_id=candidate.hypothesis_id,
        signal_ids=tuple(signal.signal_id for signal in candidate.signals),
        lead_ids=tuple(lead.lead_id for lead in candidate.leads),
        source_ids=tuple(sorted({item.source_id for item in candidate.items})),
        observation_digests=tuple(
            signal.observation_digest for signal in candidate.signals
        ),
        passages=passages,
    )


def _decode_governed_package(
    candidate: StoryCandidateRecord,
    base: EvidencePackage,
    raw: str,
) -> EvidencePackage:
    try:
        value = json.loads(raw)
        if (
            value["schema_version"] != GOVERNED_INPUT_SCHEMA_VERSION
            or value["candidate_id"] != candidate.candidate_id
            or value["hypothesis_id"] != candidate.hypothesis_id
            or value["base_package_digest"] != base.digest
            or canonical_json_bytes(value).decode("utf-8") != raw
        ):
            return base
        claims = tuple(
            GovernedClaimEvidence(
                claim_id=item["claim_id"],
                claim=item["claim"],
                passage_index=item["passage_index"],
                supporting_excerpt=item["supporting_excerpt"],
                source_ids=tuple(item["source_ids"]),
                source_record_ids=tuple(item["source_record_ids"]),
                source_authority_decision_ids=tuple(
                    item["source_authority_decision_ids"]
                ),
                rights_decision_ids=tuple(item["rights_decision_ids"]),
                dependency_evidence_ids=tuple(item["dependency_evidence_ids"]),
                evidential_origin_ids=tuple(item["evidential_origin_ids"]),
                authority_class=ClaimAuthorityClass(item["authority_class"]),
                authority_scope=item["authority_scope"],
                status=GovernedClaimStatus(item["status"]),
                attribution=item["attribution"],
                rendered_assertion_zh_hant_hk=item["rendered_assertion_zh_hant_hk"],
                claim_role=item["claim_role"],
                named_entities=tuple(item.get("named_entities", ())),
                quotations=tuple(item.get("quotations", ())),
            )
            for item in value["governed_claims"]
        )
        return EvidencePackage(
            candidate_id=base.candidate_id,
            hypothesis_id=base.hypothesis_id,
            signal_ids=base.signal_ids,
            lead_ids=base.lead_ids,
            source_ids=base.source_ids,
            observation_digests=base.observation_digests,
            passages=base.passages,
            substantive_new_information=tuple(value["substantive_new_information"]),
            governed_claims=claims,
            qualification_evidence=tuple(
                QualificationEvidence(
                    Evid012QualificationTest(item["test"]),
                    item["governed_claim_id"],
                    tuple(tuple(value) for value in item["test_evidence"]),
                )
                for item in value["qualification_evidence"]
            ),
            selection_rationale=value["selection_rationale"],
            geography=tuple(value["geography"]),
            categories=tuple(value["categories"]),
            evidence_gate_results=tuple(
                tuple(item) for item in value["evidence_gate_results"]
            ),
            evidence_gate_evidence=tuple(
                EvidenceGateEvidence(
                    item["gate"],
                    item["result"],
                    tuple(item["governed_claim_ids"]),
                    item["policy_version"],
                )
                for item in value["evidence_gate_evidence"]
            ),
            freshness_result=value["freshness_result"],
            integrity_result=value["integrity_result"],
            explicit_exclusions=tuple(value.get("explicit_exclusions", ())),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return base


def retained_package_for(
    candidate: StoryCandidateRecord,
    *,
    proving_store: str,
) -> EvidencePackage:
    """Load one controller-approved sidecar package; source content cannot mint it."""

    base = package_for(candidate)
    approval_key = os.environ.get("NEWSROOM_EVIDENCE_APPROVAL_KEY", "").encode("utf-8")
    if len(approval_key) < 32:
        return base
    connection = sqlite3.connect(proving_store)
    try:
        connection.execute("PRAGMA query_only=ON")
        existing_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
                "('proving_write_evidence_packages','proving_write_evidence_records')"
            )
        }
        if existing_tables != {
            "proving_write_evidence_packages",
            "proving_write_evidence_records",
        }:
            return base
        row = connection.execute(
            "SELECT package_json, package_json_digest, approval_status, "
            "approval_record_json, approval_signature "
            "FROM proving_write_evidence_packages WHERE candidate_id=?",
            (candidate.candidate_id,),
        ).fetchone()
        if row is None or row[2] != "APPROVED" or not isinstance(row[0], str):
            return base
        raw = row[0]
        approval_raw = row[3]
        if (
            not isinstance(approval_raw, str)
            or row[1] != digest_bytes(raw.encode("utf-8"))
            or not hmac.compare_digest(
                str(row[4]),
                hmac.new(
                    approval_key,
                    approval_raw.encode("utf-8"),
                    hashlib.sha256,
                ).hexdigest(),
            )
        ):
            return base
        try:
            approval = json.loads(approval_raw)
        except json.JSONDecodeError:
            return base
        package = _decode_governed_package(candidate, base, raw)
        if package is base:
            return base
        records = _resolve_governed_records(connection, candidate, base, package)
        if records is None:
            return base
        record_set_digest = digest_bytes(
            canonical_json_bytes({"records": [list(item) for item in records]})
        )
        if canonical_json_bytes(approval).decode(
            "utf-8"
        ) != approval_raw or approval != {
            "base_package_digest": base.digest,
            "candidate_id": candidate.candidate_id,
            "controller_principal": EVIDENCE_APPROVAL_PRINCIPAL,
            "decision": "APPROVED",
            "evidence_record_set_digest": record_set_digest,
            "hypothesis_id": candidate.hypothesis_id,
            "package_json_digest": row[1],
            "policy_version": EVIDENCE_APPROVAL_POLICY_VERSION,
        }:
            return base
        return replace(package, resolved_evidence_records=records)
    finally:
        connection.close()


def _resolve_governed_records(
    connection: sqlite3.Connection,
    candidate: StoryCandidateRecord,
    base: EvidencePackage,
    package: EvidencePackage,
) -> tuple[tuple[str, str], ...] | None:
    def record_id_set(value: object) -> set[str] | None:
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            return None
        return set(value)

    expected_types: dict[str, str] = {}
    for claim in package.governed_claims:
        for record_type, record_ids in (
            ("SOURCE_RECORD", claim.source_record_ids),
            ("SOURCE_AUTHORITY_DECISION", claim.source_authority_decision_ids),
            ("RIGHTS_DECISION", claim.rights_decision_ids),
            ("DEPENDENCY_EVIDENCE", claim.dependency_evidence_ids),
        ):
            for record_id in record_ids:
                existing_type = expected_types.setdefault(record_id, record_type)
                if existing_type != record_type:
                    return None
    if not expected_types:
        return None
    placeholders = ",".join("?" for _item in expected_types)
    rows = connection.execute(
        "SELECT record_id, record_type, record_json, record_digest "
        f"FROM proving_write_evidence_records WHERE record_id IN ({placeholders})",
        tuple(sorted(expected_types)),
    ).fetchall()
    if len(rows) != len(expected_types):
        return None
    records: dict[str, dict[str, object]] = {}
    digests: list[tuple[str, str]] = []
    for record_id, record_type, record_raw, record_digest in rows:
        if (
            expected_types.get(record_id) != record_type
            or not isinstance(record_raw, str)
            or record_digest != digest_bytes(record_raw.encode("utf-8"))
        ):
            return None
        try:
            record = json.loads(record_raw)
        except json.JSONDecodeError:
            return None
        if (
            canonical_json_bytes(record).decode("utf-8") != record_raw
            or record.get("record_id") != record_id
            or record.get("record_type") != record_type
            or record.get("candidate_id") != candidate.candidate_id
            or record.get("base_package_digest") != base.digest
            or record.get("status") != "CURRENT"
        ):
            return None
        records[record_id] = record
        digests.append((record_id, record_digest))
    source_urls = {(item.source_id, item.canonical_url) for item in candidate.items}
    required_source_record_fields = (
        "publisher",
        "responsible_body",
        "source_type",
        "authority_class",
        "publication_time",
        "retrieval_time",
        "geography",
        "language",
        "rights_decision_id",
        "originating_report_id",
        "dependency_evidence_ids",
    )
    for claim in package.governed_claims:
        if any(
            (
                records[record_id].get("source_id"),
                records[record_id].get("canonical_url"),
            )
            not in source_urls
            or records[record_id].get("extraction_status") != "COMPLETE"
            or any(
                not records[record_id].get(field)
                for field in required_source_record_fields
            )
            or records[record_id].get("authority_class") != claim.authority_class.value
            or records[record_id].get("rights_decision_id")
            not in claim.rights_decision_ids
            or record_id_set(
                records[record_id].get("dependency_evidence_ids")
            )
            != set(claim.dependency_evidence_ids)
            for record_id in claim.source_record_ids
        ):
            return None
        if any(
            records[record_id].get("source_id") not in claim.source_ids
            or records[record_id].get("decision") != "ADMITTED"
            or records[record_id].get("authority_class") != claim.authority_class.value
            or records[record_id].get("authority_scope") != claim.authority_scope
            or records[record_id].get("governed_claim_id") != claim.claim_id
            or records[record_id].get("claim_digest")
            != digest_bytes(claim.claim.encode("utf-8"))
            for record_id in claim.source_authority_decision_ids
        ):
            return None
        if any(
            records[record_id].get("source_id") not in claim.source_ids
            or records[record_id].get("decision") != "PERMITTED"
            or records[record_id].get("permitted_use") != "PUBLICATION_EVIDENCE"
            for record_id in claim.rights_decision_ids
        ):
            return None
        if any(
            records[record_id].get("source_id") not in claim.source_ids
            or records[record_id].get("dependency_status") != "RESOLVED"
            or records[record_id].get("evidential_origin_id")
            not in claim.evidential_origin_ids
            or not records[record_id].get("originating_report_id")
            for record_id in claim.dependency_evidence_ids
        ):
            return None
        resolved_origins = {
            records[record_id].get("evidential_origin_id")
            for record_id in claim.dependency_evidence_ids
        }
        if resolved_origins != set(claim.evidential_origin_ids):
            return None
    return tuple(sorted(digests))
