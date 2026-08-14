from __future__ import annotations

import json
import uuid
from dataclasses import replace

import pytest

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.increment7.locality_qualification import (
    LOCALITY_ACTIVATION,
    LOCALITY_COMPLETENESS,
    LocalityCompletenessClass,
    LocalityCoverageDecision,
    LocalityCoverageProposal,
    LocalityCoverageUnit,
    LocalityDecisionOutcome,
    LocalityKind,
    LocalityProposalPosture,
    LocalityQualificationError,
    LocalityReference,
    LocalityServiceBoundary,
    validate_locality_coverage_chain,
)

_AT = "2026-08-14T00:00:00.000000Z"
_D = "sha256:" + "a" * 64


def _id(value: int) -> str:
    return str(uuid.UUID(int=value, version=4))


def _chain():
    reference = LocalityReference(
        locality_reference_id=_id(1),
        locality_kind=LocalityKind.ADMINISTRATIVE_AREA,
        canonical_code="FIXTURE:AREA:001",
        display_label="Fixture Area",
        canonical_alias_set_digest="sha256:" + "1" * 64,
        parent_geography_digest="sha256:" + "2" * 64,
        boundary_definition_version="fixture-boundary-v1",
        boundary_digest=_D,
        authoritative_boundary_source_digest="sha256:" + "3" * 64,
        validity_interval_digest="sha256:" + "4" * 64,
        overlap_assessment_digest="sha256:" + "5" * 64,
        uncertainty_assessment_digest="sha256:" + "6" * 64,
        provenance_digests=(_D,),
        recorded_at=_AT,
    )
    unit = LocalityCoverageUnit(
        coverage_unit_id=_id(2),
        locality_reference_id=reference.locality_reference_id,
        locality_reference_digest=reference.digest,
        service_boundary=LocalityServiceBoundary.CIVIC_AND_PUBLIC_BODIES,
        obligation_scope_digest="sha256:" + "1" * 64,
        source_class_scope=("PUBLIC_BODY_NOTICES", "PUBLIC_MEETINGS"),
        population_service_event_scope_digest="sha256:" + "2" * 64,
        language_scope_digest="sha256:" + "3" * 64,
        source_role_scope_digest="sha256:" + "4" * 64,
        portfolio_function_scope_digest="sha256:" + "5" * 64,
        explicit_exclusions=("PRIVATE_COMMUNITY_GROUPS",),
        known_gap_codes=("MISSING_SMALL_PUBLISHERS",),
        completeness_class=LocalityCompletenessClass.BEST_EFFORT_WITH_EXPLICIT_GAPS,
        rights_basis_digest="sha256:" + "b" * 64,
        governing_evaluation_version_digest="sha256:" + "6" * 64,
        operational_profile_digest="sha256:" + "c" * 64,
        recorded_at="2026-08-14T00:00:01.000000Z",
    )
    proposal = LocalityCoverageProposal(
        proposal_id=_id(3),
        coverage_unit_id=unit.coverage_unit_id,
        coverage_unit_digest=unit.digest,
        posture=LocalityProposalPosture.RESEARCH_ONLY,
        qualification_basis_digests=(
            "sha256:" + "7" * 64,
            "sha256:" + "8" * 64,
        ),
        provider_decision_digests=("sha256:" + "9" * 64,),
        proposed_source_reference_digests=("sha256:" + "d" * 64,),
        permanent_monitoring_rationale_digest="sha256:" + "1" * 64,
        expected_contribution_digest="sha256:" + "2" * 64,
        evaluation_design_digest="sha256:" + "3" * 64,
        alternatives_assessment_digest="sha256:" + "4" * 64,
        non_selection_consequence_digest="sha256:" + "5" * 64,
        unresolved_gap_codes=("MISSING_SMALL_PUBLISHERS",),
        owner_identity_digest="sha256:" + "e" * 64,
        proposed_at="2026-08-14T00:00:02.000000Z",
    )
    decision = LocalityCoverageDecision(
        _id(4),
        proposal.proposal_id,
        proposal.digest,
        LocalityDecisionOutcome.RETAIN_RESEARCH_ONLY,
        proposal.unresolved_gap_codes,
        ("GAPS_REMAIN_EXPLICIT",),
        "sha256:" + "f" * 64,
        None,
        "2026-08-14T00:00:03.000000Z",
    )
    return reference, unit, proposal, decision


def test_exact_locality_chain_roundtrips_without_completeness_or_activation() -> None:
    records = _chain()
    validate_locality_coverage_chain(*records)
    kinds = (
        LocalityReference,
        LocalityCoverageUnit,
        LocalityCoverageProposal,
        LocalityCoverageDecision,
    )
    for record, kind in zip(records, kinds, strict=True):
        assert kind.from_canonical_bytes(record.canonical_bytes) == record
        assert record.authorises_locality is False
        assert record.authorises_source_portfolio is False
        assert record.claims_completeness is False
        assert record.production_activation_authorised is False
    assert LOCALITY_COMPLETENESS == "BEST_EFFORT_EXPLICIT_GAPS_NO_COMPLETENESS_CLAIM"
    assert LOCALITY_ACTIVATION == "DECISION_RECORD_ONLY_NO_SELECTION_OR_ENABLEMENT"


def test_reference_unit_and_proposal_bind_exact_boundaries_and_gaps() -> None:
    reference, unit, proposal, decision = _chain()
    with pytest.raises(LocalityQualificationError, match="lineage"):
        validate_locality_coverage_chain(
            reference,
            replace(unit, locality_reference_digest="sha256:" + "0" * 64),
            proposal,
            decision,
        )
    with pytest.raises(LocalityQualificationError, match="lineage"):
        validate_locality_coverage_chain(
            reference,
            unit,
            replace(proposal, unresolved_gap_codes=("OTHER_GAP",)),
            decision,
        )
    with pytest.raises(LocalityQualificationError, match="lineage"):
        validate_locality_coverage_chain(
            reference,
            unit,
            proposal,
            replace(decision, assessed_gap_codes=("UNASSESSED_GAP",)),
        )


def test_coverage_unit_identity_commits_every_qualified_scope_dimension() -> None:
    _, unit, *_ = _chain()
    for field, value in (
        ("obligation_scope_digest", "sha256:" + "a" * 64),
        ("population_service_event_scope_digest", "sha256:" + "b" * 64),
        ("language_scope_digest", "sha256:" + "c" * 64),
        ("source_role_scope_digest", "sha256:" + "d" * 64),
        ("portfolio_function_scope_digest", "sha256:" + "e" * 64),
        ("governing_evaluation_version_digest", "sha256:" + "f" * 64),
    ):
        assert replace(unit, **{field: value}).digest != unit.digest


def test_locality_reference_identity_commits_boundary_ambiguity_dimensions() -> None:
    reference, *_ = _chain()
    for field, value in (
        ("canonical_alias_set_digest", "sha256:" + "a" * 64),
        ("parent_geography_digest", "sha256:" + "b" * 64),
        ("authoritative_boundary_source_digest", "sha256:" + "c" * 64),
        ("validity_interval_digest", "sha256:" + "d" * 64),
        ("overlap_assessment_digest", "sha256:" + "e" * 64),
        ("uncertainty_assessment_digest", "sha256:" + "f" * 64),
    ):
        assert replace(reference, **{field: value}).digest != reference.digest


def test_proposal_requires_multiple_qualification_bases_and_full_assessment() -> None:
    _, _, proposal, _ = _chain()
    with pytest.raises(LocalityQualificationError, match="bounded array"):
        replace(
            proposal,
            qualification_basis_digests=(proposal.qualification_basis_digests[0],),
        )
    for field, value in (
        ("permanent_monitoring_rationale_digest", "sha256:" + "a" * 64),
        ("expected_contribution_digest", "sha256:" + "b" * 64),
        ("evaluation_design_digest", "sha256:" + "c" * 64),
        ("alternatives_assessment_digest", "sha256:" + "d" * 64),
        ("non_selection_consequence_digest", "sha256:" + "e" * 64),
    ):
        assert replace(proposal, **{field: value}).digest != proposal.digest


def test_decisions_only_retain_defer_or_reject_and_chain_exactly() -> None:
    reference, unit, proposal, first = _chain()
    assert {item.value for item in LocalityDecisionOutcome} == {
        "DEFERRED",
        "REJECTED",
        "RETAIN_RESEARCH_ONLY",
    }
    second = replace(
        first,
        decision_id=_id(5),
        outcome=LocalityDecisionOutcome.DEFERRED,
        supersedes_decision_digest=first.digest,
        decided_at="2026-08-14T00:00:04.000000Z",
    )
    validate_locality_coverage_chain(reference, unit, proposal, second, first)
    third = replace(
        second,
        decision_id=_id(6),
        supersedes_decision_digest=second.digest,
        decided_at="2026-08-14T00:00:05.000000Z",
    )
    validate_locality_coverage_chain(reference, unit, proposal, third, (first, second))
    with pytest.raises(LocalityQualificationError, match="predecessor"):
        validate_locality_coverage_chain(reference, unit, proposal, third, second)
    with pytest.raises(LocalityQualificationError, match="predecessor"):
        validate_locality_coverage_chain(
            reference,
            unit,
            proposal,
            replace(second, decision_id=first.decision_id),
            first,
        )
    with pytest.raises(LocalityQualificationError, match="predecessor"):
        validate_locality_coverage_chain(
            reference,
            unit,
            proposal,
            replace(second, supersedes_decision_digest=_D),
            first,
        )


def test_unknown_duplicate_noncanonical_and_unbounded_arrays_fail_closed() -> None:
    reference, unit, *_ = _chain()
    value = json.loads(reference.canonical_bytes)
    value["selected_permanently"] = True
    with pytest.raises(LocalityQualificationError, match="fields"):
        LocalityReference.from_canonical_bytes(canonical_json_bytes(value))
    duplicate = reference.canonical_bytes.replace(
        b'"canonical_code":', b'"canonical_code":"OTHER","canonical_code":', 1
    )
    with pytest.raises(LocalityQualificationError, match="duplicate"):
        LocalityReference.from_canonical_bytes(duplicate)
    with pytest.raises(LocalityQualificationError, match="canonical JSON"):
        LocalityReference.from_canonical_bytes(reference.canonical_bytes + b" ")
    with pytest.raises(LocalityQualificationError, match="bounded array"):
        replace(
            unit, source_class_scope=tuple(f"SOURCE_{value:03d}" for value in range(65))
        )
    malformed = json.loads(unit.canonical_bytes)
    malformed["source_class_scope"] = None
    with pytest.raises(LocalityQualificationError, match="must be an array"):
        LocalityCoverageUnit.from_canonical_bytes(canonical_json_bytes(malformed))


def test_locality_records_create_no_watch_editorial_or_external_effect() -> None:
    for record in _chain():
        assert record.authorises_provider is False
        assert record.authorises_credentials is False
        assert record.authorises_egress is False
        assert record.authorises_spend is False
        assert record.authorises_search is False
        assert record.authorises_evidence is False
        assert record.authorises_publication is False
        assert record.creates_watch is False
        assert record.creates_signal is False
        assert record.creates_lead is False
        assert record.creates_candidate is False
        assert record.permanent_locality_selected is False
