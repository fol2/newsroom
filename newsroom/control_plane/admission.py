"""Deterministic pre-write admission for retained Evidence Packages."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Protocol

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.control_plane.editorial import StoryCandidateRecord
from newsroom.control_plane.evidence import (
    EVIDENCE_GATE_POLICY_VERSION,
    ClaimAuthorityClass,
    EvidencePackage,
    GovernedClaimEvidence,
    GovernedClaimStatus,
)
from newsroom.control_plane.zh_hant import contains_simplified_variant

WRITE_ADMISSION_POLICY_VERSION = "newsroom.write-admission.v1"
WRITE_SELECTION_POLICY_VERSION = "newsroom.write-selection.v1"

WriteAdmissionResult = Literal["WRITE_READY", "HOLD", "REJECT"]

_REQUIRED_EVIDENCE_GATES = frozenset(
    {"CLAIM_TRACEABILITY", "EVIDENCE_SUFFICIENCY", "SOURCE_AUTHORITY"}
)
_CANONICAL_PASS_GATES = tuple(
    (gate, "PASS") for gate in sorted(_REQUIRED_EVIDENCE_GATES)
)
_APPROVED_GEOGRAPHIES = frozenset({"UK", "Hong Kong", "Global"})
_APPROVED_CATEGORIES = frozenset(
    {
        "Politics and law",
        "Immigration and status",
        "Safety and crime",
        "Weather and disasters",
        "Transport and infrastructure",
        "Health and healthcare",
        "Education and campuses",
        "Tax and welfare",
        "Work and employment",
        "Housing and local life",
        "Economy and finance",
        "Consumer rights and scams",
        "Technology and cyber security",
        "War and international affairs",
        "Community and public services",
    }
)
_QUALIFICATION_CLASSIFIER_FIELDS = frozenset(
    {
        "change_kind",
        "effect_class",
        "service_kind",
        "domain",
        "action_class",
        "importance_class",
    }
)


def _valid_zh_hant_hk_rendering(claim: GovernedClaimEvidence) -> bool:
    rendered = claim.rendered_assertion_zh_hant_hk
    without_entities = rendered
    for entity in claim.named_entities:
        without_entities = without_entities.replace(entity, "")
    return (
        any("\u3400" <= character <= "\u9fff" for character in rendered)
        and not re.search(r"[A-Za-z]", without_entities)
        and not contains_simplified_variant(rendered)
        and all(
            len(value) < 8 or value not in rendered
            for value in (claim.claim, claim.supporting_excerpt)
        )
    )


@dataclass(frozen=True, slots=True)
class WriteAdmissionDecision:
    decision_id: str
    candidate_id: str
    evidence_package_digest: str
    decision: WriteAdmissionResult
    substantive_new_information: tuple[str, ...]
    qualification_tests: tuple[str, ...]
    selection_rationale: str
    geography: tuple[str, ...]
    categories: tuple[str, ...]
    evidence_gate_results: tuple[tuple[str, str], ...]
    freshness_result: str
    integrity_result: str
    stable_reason_codes: tuple[str, ...]
    policy_version: str
    decided_at: str

    def __post_init__(self) -> None:
        if self.decision not in {"WRITE_READY", "HOLD", "REJECT"}:
            raise ValueError("invalid write-admission result")
        expected = _decision_id(
            candidate_id=self.candidate_id,
            evidence_package_digest=self.evidence_package_digest,
            decision=self.decision,
            substantive_new_information=self.substantive_new_information,
            qualification_tests=self.qualification_tests,
            selection_rationale=self.selection_rationale,
            geography=self.geography,
            categories=self.categories,
            evidence_gate_results=self.evidence_gate_results,
            freshness_result=self.freshness_result,
            integrity_result=self.integrity_result,
            stable_reason_codes=self.stable_reason_codes,
            policy_version=self.policy_version,
        )
        if self.decision_id != expected:
            raise ValueError("write-admission decision identity is not canonical")

    def as_record(self) -> dict[str, object]:
        return {
            "decision_id": self.decision_id,
            "candidate_id": self.candidate_id,
            "evidence_package_digest": self.evidence_package_digest,
            "decision": self.decision,
            "substantive_new_information": list(self.substantive_new_information),
            "qualification_tests": list(self.qualification_tests),
            "selection_rationale": self.selection_rationale,
            "geography": list(self.geography),
            "categories": list(self.categories),
            "evidence_gate_results": [
                list(item) for item in self.evidence_gate_results
            ],
            "freshness_result": self.freshness_result,
            "integrity_result": self.integrity_result,
            "stable_reason_codes": list(self.stable_reason_codes),
            "policy_version": self.policy_version,
            "decided_at": self.decided_at,
        }


class WriteAdmissionPort(Protocol):
    def decide(
        self,
        candidate: StoryCandidateRecord,
        package: EvidencePackage,
        *,
        decided_at: str,
    ) -> WriteAdmissionDecision: ...


@dataclass(frozen=True, slots=True)
class WriteSelectionRecord:
    selection_id: str
    decision_id: str
    candidate_id: str
    evidence_package_digest: str
    rank: int
    quality_score: tuple[int, int, int, int]
    ordering_evidence: tuple[str, ...]
    policy_version: str
    selected_at: str

    def as_record(self) -> dict[str, object]:
        return {
            "selection_id": self.selection_id,
            "decision_id": self.decision_id,
            "candidate_id": self.candidate_id,
            "evidence_package_digest": self.evidence_package_digest,
            "rank": self.rank,
            "quality_score": list(self.quality_score),
            "ordering_evidence": list(self.ordering_evidence),
            "policy_version": self.policy_version,
            "selected_at": self.selected_at,
        }


def _decision_id(**record: object) -> str:
    return digest_bytes(canonical_json_bytes(record))


def _make_decision(
    package: EvidencePackage,
    *,
    decision: WriteAdmissionResult,
    reason_codes: tuple[str, ...],
    decided_at: str,
) -> WriteAdmissionDecision:
    values: dict[str, object] = {
        "candidate_id": package.candidate_id,
        "evidence_package_digest": package.digest,
        "decision": decision,
        "substantive_new_information": package.substantive_new_information,
        "qualification_tests": tuple(
            sorted({item.test.value for item in package.qualification_evidence})
        ),
        "selection_rationale": package.selection_rationale,
        "geography": package.geography,
        "categories": package.categories,
        "evidence_gate_results": package.evidence_gate_results,
        "freshness_result": package.freshness_result,
        "integrity_result": package.integrity_result,
        "stable_reason_codes": reason_codes,
        "policy_version": WRITE_ADMISSION_POLICY_VERSION,
    }
    return WriteAdmissionDecision(
        decision_id=_decision_id(**values),
        decided_at=decided_at,
        **values,  # type: ignore[arg-type]
    )


class DeterministicWriteAdmission:
    """Fail-closed admission over exact, already-retained package fields."""

    def decide(
        self,
        candidate: StoryCandidateRecord,
        package: EvidencePackage,
        *,
        decided_at: str,
    ) -> WriteAdmissionDecision:
        if (candidate.candidate_id, candidate.hypothesis_id) != (
            package.candidate_id,
            package.hypothesis_id,
        ):
            raise ValueError("candidate and Evidence Package identity differ")
        if package.explicit_exclusions:
            return _make_decision(
                package,
                decision="REJECT",
                reason_codes=tuple(
                    sorted(
                        f"EXPLICIT_EXCLUSION_{item}"
                        for item in package.explicit_exclusions
                    )
                ),
                decided_at=decided_at,
            )
        missing: list[str] = []
        if not package.geography:
            missing.append("MISSING_GEOGRAPHY")
        elif not set(package.geography).issubset(_APPROVED_GEOGRAPHIES):
            missing.append("UNRECOGNISED_GEOGRAPHY")
        if not package.categories:
            missing.append("MISSING_CATEGORY")
        elif not set(package.categories).issubset(_APPROVED_CATEGORIES):
            missing.append("UNRECOGNISED_CATEGORY")
        if not package.selection_rationale.strip():
            missing.append("MISSING_SELECTION_RATIONALE")
        if not package.resolved_evidence_records:
            missing.append("UNRESOLVED_GOVERNED_EVIDENCE_RECORDS")
        governed_claims = {item.claim_id: item for item in package.governed_claims}
        invalid_claims = tuple(
            item
            for item in package.governed_claims
            if item.passage_index >= len(package.passages)
            or item.claim not in package.passages[item.passage_index]
            or item.supporting_excerpt not in package.passages[item.passage_index]
            or not set(item.source_ids).issubset(package.source_ids)
            or item.status is not GovernedClaimStatus.CONFIRMED_FACT
            or not _valid_zh_hant_hk_rendering(item)
            or any(
                entity not in item.claim and entity not in item.supporting_excerpt
                for entity in item.named_entities
            )
            or any(
                quotation not in item.supporting_excerpt
                for quotation in item.quotations
            )
            or (
                item.authority_class is ClaimAuthorityClass.INDEPENDENT_RELIABLE
                and len(item.evidential_origin_ids) < 2
            )
        )
        if not governed_claims:
            missing.append("MISSING_GOVERNED_CLAIMS")
        elif invalid_claims:
            missing.append("INVALID_GOVERNED_CLAIM_EVIDENCE")
        if sum(item.claim_role == "HEADLINE" for item in package.governed_claims) != 1:
            missing.append("INVALID_HEADLINE_CLAIM_INVENTORY")
        if any(
            not any(
                claim.claim == fact and claim.claim_role == "SUBSTANTIVE"
                for claim in package.governed_claims
            )
            for fact in package.substantive_new_information
        ):
            missing.append("INVALID_SUBSTANTIVE_CLAIM_INVENTORY")
        expected_claim_ids = frozenset(governed_claims)
        gate_evidence = {item.gate: item for item in package.evidence_gate_evidence}
        if len(gate_evidence) != len(package.evidence_gate_evidence):
            missing.append("DUPLICATE_EVIDENCE_GATE_PROVENANCE")
        for gate in sorted(_REQUIRED_EVIDENCE_GATES):
            provenance = gate_evidence.get(gate)
            if (
                provenance is None
                or provenance.result != "PASS"
                or provenance.policy_version != EVIDENCE_GATE_POLICY_VERSION
                or frozenset(provenance.governed_claim_ids) != expected_claim_ids
            ):
                missing.append(f"{gate}_PROVENANCE_NOT_PASS")
        if package.evidence_gate_results != _CANONICAL_PASS_GATES:
            missing.append("EVIDENCE_GATE_RESULTS_NOT_COMPUTED")
        if package.freshness_result != "PASS":
            missing.append("FRESHNESS_NOT_PASS")
        if package.integrity_result != "PASS":
            missing.append("INTEGRITY_NOT_PASS")
        if missing:
            return _make_decision(
                package,
                decision="HOLD",
                reason_codes=tuple(sorted(set(missing))),
                decided_at=decided_at,
            )
        if not package.substantive_new_information:
            return _make_decision(
                package,
                decision="REJECT",
                reason_codes=("NO_SUBSTANTIVE_NEW_INFORMATION",),
                decided_at=decided_at,
            )
        if any(
            fact not in {item.claim for item in package.governed_claims}
            for fact in package.substantive_new_information
        ):
            return _make_decision(
                package,
                decision="HOLD",
                reason_codes=("SUBSTANTIVE_INFORMATION_NOT_EXACT",),
                decided_at=decided_at,
            )
        if not package.qualification_evidence:
            return _make_decision(
                package,
                decision="REJECT",
                reason_codes=("NO_QUALIFICATION_TEST",),
                decided_at=decided_at,
            )
        unsupported = tuple(
            item
            for item in package.qualification_evidence
            if item.governed_claim_id not in governed_claims
            or any(
                field not in _QUALIFICATION_CLASSIFIER_FIELDS
                and value not in governed_claims[item.governed_claim_id].claim
                and value
                not in governed_claims[item.governed_claim_id].supporting_excerpt
                for field, value in item.test_evidence
            )
        )
        if unsupported:
            return _make_decision(
                package,
                decision="HOLD",
                reason_codes=("QUALIFICATION_EVIDENCE_NOT_EXACT",),
                decided_at=decided_at,
            )
        return _make_decision(
            package,
            decision="WRITE_READY",
            reason_codes=("QUALIFIED_WRITE_READY",),
            decided_at=decided_at,
        )


def validate_admission_binding(
    decision: WriteAdmissionDecision,
    candidate: StoryCandidateRecord,
    package: EvidencePackage,
) -> None:
    if decision.candidate_id != candidate.candidate_id:
        raise ValueError("write admission binds another candidate")
    if decision.evidence_package_digest != package.digest:
        raise ValueError("write admission binds another Evidence Package")
    if decision.substantive_new_information != package.substantive_new_information:
        raise ValueError("write admission substantive facts differ from package")
    if decision.qualification_tests != tuple(
        sorted({item.test.value for item in package.qualification_evidence})
    ):
        raise ValueError("write admission qualification differs from package")
    if (
        decision.selection_rationale,
        decision.geography,
        decision.categories,
        decision.evidence_gate_results,
        decision.freshness_result,
        decision.integrity_result,
    ) != (
        package.selection_rationale,
        package.geography,
        package.categories,
        package.evidence_gate_results,
        package.freshness_result,
        package.integrity_result,
    ):
        raise ValueError("write admission governed fields differ from package")


def select_write_ready(
    admitted: tuple[
        tuple[StoryCandidateRecord, EvidencePackage, WriteAdmissionDecision], ...
    ],
    *,
    limit: int,
    selected_at: str,
) -> tuple[
    tuple[
        StoryCandidateRecord,
        EvidencePackage,
        WriteAdmissionDecision,
        WriteSelectionRecord,
    ],
    ...,
]:
    """Select by retained evidence quality; candidate ID is only a final tie-break."""

    if limit < 0:
        raise ValueError("write-ready selection limit must be non-negative")

    def quality(
        item: tuple[StoryCandidateRecord, EvidencePackage, WriteAdmissionDecision],
    ) -> tuple[int, int, int, int]:
        _candidate, package, _decision = item
        origins = {
            origin
            for claim in package.governed_claims
            for origin in claim.evidential_origin_ids
        }
        authority_score = sum(
            2 if claim.authority_class is ClaimAuthorityClass.RESPONSIBLE_PRIMARY else 1
            for claim in package.governed_claims
        )
        return (
            len(package.qualification_evidence),
            authority_score,
            len(origins),
            len(package.substantive_new_information),
        )

    ready = [item for item in admitted if item[2].decision == "WRITE_READY"]
    ready.sort(
        key=lambda item: (
            tuple(-value for value in quality(item)) + (item[0].candidate_id,)
        )
    )
    selected = []
    for rank, item in enumerate(ready[:limit], start=1):
        candidate, package, decision = item
        score = quality(item)
        identity = {
            "decision_id": decision.decision_id,
            "candidate_id": candidate.candidate_id,
            "evidence_package_digest": package.digest,
            "rank": rank,
            "quality_score": score,
            "policy_version": WRITE_SELECTION_POLICY_VERSION,
        }
        record = WriteSelectionRecord(
            selection_id=digest_bytes(canonical_json_bytes(identity)),
            decision_id=decision.decision_id,
            candidate_id=candidate.candidate_id,
            evidence_package_digest=package.digest,
            rank=rank,
            quality_score=score,
            ordering_evidence=(
                f"qualification_tests={score[0]}",
                f"claim_authority_score={score[1]}",
                f"independent_evidential_origins={score[2]}",
                f"substantive_new_information={score[3]}",
            ),
            policy_version=WRITE_SELECTION_POLICY_VERSION,
            selected_at=selected_at,
        )
        selected.append((*item, record))
    return tuple(selected)
