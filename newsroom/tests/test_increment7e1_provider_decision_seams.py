from __future__ import annotations

import json
import uuid
from dataclasses import replace

import pytest

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.increment7.provider_qualification import (
    PROVIDER_CURRENT_POSTURE,
    PROVIDER_QUALIFICATION_AUTHORITY,
    ProviderDecision,
    ProviderKind,
    ProviderPrerequisite,
    ProviderPrerequisiteAssessment,
    ProviderPrerequisiteOutcome,
    ProviderProposal,
    ProviderQualificationError,
    ProviderQualificationStatus,
    validate_provider_decision,
)

_AT = "2026-08-14T00:00:00.000000Z"
_D = "sha256:" + "a" * 64


def _id(value: int) -> str:
    return str(uuid.UUID(int=value, version=4))


def _posture(kind: ProviderKind) -> ProviderQualificationStatus:
    return ProviderQualificationStatus(PROVIDER_CURRENT_POSTURE[kind.value])


def _proposal(kind: ProviderKind, value: int = 1) -> ProviderProposal:
    return ProviderProposal(
        _id(value),
        f"fixture-provider-{value}",
        kind,
        f"Fixture {kind.value}",
        _posture(kind),
        ("PUBLIC_NEWS_SEARCH",),
        "research-snapshot-v1",
        (_D,),
        "sha256:" + "b" * 64,
        _AT,
    )


def _assessments(
    missing: ProviderPrerequisite = ProviderPrerequisite.RIGHTS_BASIS,
) -> tuple[ProviderPrerequisiteAssessment, ...]:
    return tuple(
        ProviderPrerequisiteAssessment(
            prerequisite,
            (
                ProviderPrerequisiteOutcome.MISSING
                if prerequisite is missing
                else ProviderPrerequisiteOutcome.SATISFIED
            ),
            None if prerequisite is missing else "sha256:" + "c" * 64,
        )
        for prerequisite in ProviderPrerequisite
    )


def _decision(proposal: ProviderProposal, value: int = 20) -> ProviderDecision:
    return ProviderDecision(
        _id(value),
        proposal.proposal_id,
        proposal.digest,
        proposal.proposed_posture,
        _assessments(),
        None,
        "sha256:" + "d" * 64,
        ("CURRENT_POSTURE_RETAINED",),
        "2026-08-14T00:00:01.000000Z",
    )


def test_current_provider_postures_roundtrip_without_activation() -> None:
    for kind, expected in (
        (ProviderKind.GDELT, ProviderQualificationStatus.HELD),
        (
            ProviderKind.BRAVE_SEARCH,
            ProviderQualificationStatus.RIGHTS_REVIEW_REQUIRED,
        ),
        (ProviderKind.SEARXNG, ProviderQualificationStatus.RESEARCH),
        (ProviderKind.UNOFFICIAL_WRAPPER, ProviderQualificationStatus.RESEARCH),
    ):
        proposal = _proposal(kind, list(ProviderKind).index(kind) + 1)
        decision = _decision(proposal, list(ProviderKind).index(kind) + 20)
        validate_provider_decision(proposal, decision)
        assert proposal.proposed_posture is expected
        assert (
            ProviderProposal.from_canonical_bytes(proposal.canonical_bytes) == proposal
        )
        assert (
            ProviderDecision.from_canonical_bytes(decision.canonical_bytes) == decision
        )
        for record in (proposal, decision):
            assert record.authorises_provider is False
            assert record.authorises_credentials is False
            assert record.authorises_egress is False
            assert record.authorises_spend is False
            assert record.production_activation_authorised is False
    assert PROVIDER_QUALIFICATION_AUTHORITY == "DECISION_RECORD_ONLY_NO_ACTIVATION"


def test_prerequisites_are_complete_referenced_and_never_self_qualifying() -> None:
    proposal = _proposal(ProviderKind.BRAVE_SEARCH)
    with pytest.raises(ProviderQualificationError, match="current posture"):
        replace(
            proposal,
            proposed_posture=ProviderQualificationStatus.QUALIFIED_FOR_SEPARATE_ADMISSION_REVIEW,
        )
    with pytest.raises(ProviderQualificationError, match="exact reference"):
        ProviderPrerequisiteAssessment(
            ProviderPrerequisite.RIGHTS_BASIS,
            ProviderPrerequisiteOutcome.SATISFIED,
            None,
        )
    with pytest.raises(ProviderQualificationError, match="assessments"):
        replace(_decision(proposal), prerequisite_assessments=_assessments()[:-1])
    all_satisfied = tuple(
        ProviderPrerequisiteAssessment(
            prerequisite,
            ProviderPrerequisiteOutcome.SATISFIED,
            "sha256:" + "e" * 64,
        )
        for prerequisite in ProviderPrerequisite
    )
    qualified = ProviderDecision(
        _id(99),
        proposal.proposal_id,
        proposal.digest,
        ProviderQualificationStatus.QUALIFIED_FOR_SEPARATE_ADMISSION_REVIEW,
        all_satisfied,
        None,
        "sha256:" + "f" * 64,
        ("PREREQUISITES_RECORDED",),
        "2026-08-14T00:00:01.000000Z",
    )
    with pytest.raises(ProviderQualificationError, match="current posture"):
        validate_provider_decision(proposal, qualified)
    retained = replace(
        qualified,
        status=proposal.proposed_posture,
        reason_codes=("SATISFIED_BUT_NOT_ADMITTED",),
    )
    validate_provider_decision(proposal, retained)
    with pytest.raises(TypeError):
        PROVIDER_CURRENT_POSTURE[ProviderKind.BRAVE_SEARCH.value] = "RESEARCH"  # type: ignore[index]


def test_decision_binds_exact_proposal_predecessor_and_chronology() -> None:
    proposal = _proposal(ProviderKind.GDELT)
    first = _decision(proposal)
    validate_provider_decision(proposal, first)
    second = replace(
        first,
        decision_id=_id(21),
        supersedes_decision_digest=first.digest,
        decided_at="2026-08-14T00:00:02.000000Z",
    )
    validate_provider_decision(proposal, second, first)
    third = replace(
        second,
        decision_id=_id(22),
        supersedes_decision_digest=second.digest,
        decided_at="2026-08-14T00:00:03.000000Z",
    )
    validate_provider_decision(proposal, third, (first, second))
    with pytest.raises(ProviderQualificationError, match="predecessor"):
        validate_provider_decision(
            proposal,
            replace(third, decision_id=first.decision_id),
            (first, second),
        )
    with pytest.raises(ProviderQualificationError, match="Proposal"):
        validate_provider_decision(
            proposal,
            replace(first, proposal_digest="sha256:" + "0" * 64),
        )
    with pytest.raises(ProviderQualificationError, match="predecessor"):
        validate_provider_decision(
            proposal,
            replace(second, supersedes_decision_digest=_D),
            first,
        )
    with pytest.raises(ProviderQualificationError, match="predecessor"):
        validate_provider_decision(
            proposal,
            replace(second, decision_id=first.decision_id),
            first,
        )


def test_unknown_duplicate_and_noncanonical_bytes_fail_closed() -> None:
    proposal = _proposal(ProviderKind.SEARXNG)
    value = json.loads(proposal.canonical_bytes)
    value["credential"] = "TOKEN"
    with pytest.raises(ProviderQualificationError, match="fields"):
        ProviderProposal.from_canonical_bytes(canonical_json_bytes(value))
    duplicate = proposal.canonical_bytes.replace(
        b'"provider_id":', b'"provider_id":"other","provider_id":', 1
    )
    with pytest.raises(ProviderQualificationError, match="duplicate"):
        ProviderProposal.from_canonical_bytes(duplicate)
    with pytest.raises(ProviderQualificationError, match="canonical JSON"):
        ProviderProposal.from_canonical_bytes(proposal.canonical_bytes + b" ")
    malformed = json.loads(proposal.canonical_bytes)
    malformed["capability_scope"] = None
    with pytest.raises(ProviderQualificationError, match="must be an array"):
        ProviderProposal.from_canonical_bytes(canonical_json_bytes(malformed))


def test_rejection_is_a_record_not_provider_or_editorial_authority() -> None:
    proposal = _proposal(ProviderKind.UNOFFICIAL_WRAPPER)
    rejected = replace(
        _decision(proposal),
        status=ProviderQualificationStatus.REJECTED,
        reason_codes=("UNOFFICIAL_ACCESS_PATH",),
    )
    validate_provider_decision(proposal, rejected)
    assert rejected.authorises_query_execution is False
    assert rejected.authorises_evidence is False
    assert rejected.authorises_publication is False
    assert rejected.creates_signal is False
    assert rejected.creates_lead is False
    assert rejected.creates_candidate is False
