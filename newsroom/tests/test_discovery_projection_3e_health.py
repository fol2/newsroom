from __future__ import annotations

import pytest

from newsroom.authority import UtcTimestamp
from newsroom.checks import CheckOutcomeId, CheckOutcomeKind, QuarantineDisposition
from newsroom.projection import (
    CoveragePathHealthInput,
    DiscoveryHealthAssessment,
    DiscoveryHealthContractError,
    DiscoveryHealthDimension,
    DiscoveryHealthState,
    HealthEvidenceReference,
    HealthPolicy,
    ProjectionGenerationId,
    ProjectionGenerationState,
    ProjectionHealthInput,
    SourceObservationHealthInput,
    assess_coverage_availability,
    assess_projection_health,
    assess_source_health,
    summarize_source_path_state,
)
from newsroom.sources import (
    CoverageContribution,
    CoverageResponsibility,
    PortfolioFunction,
    SourceDefinitionId,
    SourceDefinitionVersionId,
)


NOW = UtcTimestamp.parse("2042-03-12T10:05:00.000000Z")
RECENT = UtcTimestamp.parse("2042-03-12T10:00:00.000000Z")
OLD = UtcTimestamp.parse("2042-03-10T10:00:00.000000Z")
POLICY = HealthPolicy("fixture-health", "v1", 3_600)
DEFINITION_ID = SourceDefinitionId.parse(
    "00000000-0000-4000-8000-000000006004"
)
VERSION_ID = SourceDefinitionVersionId.parse(
    "00000000-0000-4000-8000-000000006005"
)
OUTCOME_ID = CheckOutcomeId.parse(
    "00000000-0000-4000-8000-000000006003"
)
VERSION_EVIDENCE = HealthEvidenceReference(
    "SOURCE_DEFINITION_VERSION",
    str(VERSION_ID),
    OLD,
    "sha256:" + "b" * 64,
)
OUTCOME_EVIDENCE = HealthEvidenceReference(
    "CHECK_OUTCOME",
    str(OUTCOME_ID),
    RECENT,
    "sha256:" + "a" * 64,
)
EVIDENCE = tuple(
    sorted(
        (VERSION_EVIDENCE, OUTCOME_EVIDENCE),
        key=lambda item: (
            item.evidence_type,
            item.identifier,
            str(item.observed_at),
            item.digest or "",
        ),
    )
)


def source_input(
    kind: CheckOutcomeKind | None,
    *,
    success_at: UtcTimestamp | None = RECENT,
    complete_at: UtcTimestamp | None = RECENT,
    change_at: UtcTimestamp | None = OLD,
    quarantine: QuarantineDisposition | None = QuarantineDisposition.NONE,
    semantic_valid: bool | None = True,
) -> SourceObservationHealthInput:
    if kind is None:
        if semantic_valid is True:
            semantic_valid = None
        return SourceObservationHealthInput(
            DEFINITION_ID,
            VERSION_ID,
            None,
            None,
            None,
            None,
            complete_at,
            success_at,
            change_at,
            True,
            True,
            semantic_valid,
            (VERSION_EVIDENCE,),
        )
    return SourceObservationHealthInput(
        DEFINITION_ID,
        VERSION_ID,
        OUTCOME_ID,
        kind,
        quarantine,
        RECENT,
        complete_at,
        success_at,
        change_at,
        True,
        True,
        semantic_valid,
        EVIDENCE,
    )


def assessments_by_dimension(value: SourceObservationHealthInput):
    return {
        item.dimension: item
        for item in assess_source_health(value, policy=POLICY, assessed_at=NOW)
    }


def test_health_assessment_rejects_future_evidence() -> None:
    future = UtcTimestamp.parse("2042-03-12T10:06:00.000000Z")
    evidence = HealthEvidenceReference(
        evidence_type="CHECK_OUTCOME",
        identifier="future-outcome",
        observed_at=future,
        digest="sha256:" + "9" * 64,
    )
    with pytest.raises(
        DiscoveryHealthContractError,
        match="evidence cannot follow",
    ):
        DiscoveryHealthAssessment(
            dimension=DiscoveryHealthDimension.CHECK_EXECUTION,
            state=DiscoveryHealthState.HEALTHY,
            scope_type="SOURCE_DEFINITION_VERSION",
            scope_id="future-source",
            reason_code="CHECK_SUCCEEDED",
            policy=POLICY,
            evidence=(evidence,),
            assessed_at=NOW,
        )


def test_healthy_assessment_requires_positive_evidence() -> None:
    with pytest.raises(
        DiscoveryHealthContractError,
        match="requires positive evidence",
    ):
        DiscoveryHealthAssessment(
            dimension=DiscoveryHealthDimension.CHECK_EXECUTION,
            state=DiscoveryHealthState.HEALTHY,
            scope_type="SOURCE_DEFINITION_VERSION",
            scope_id=str(VERSION_ID),
            reason_code="CHECK_SUCCEEDED",
            policy=POLICY,
            evidence=(),
            assessed_at=NOW,
        )


def test_source_health_requires_exact_version_and_outcome_evidence() -> None:
    with pytest.raises(
        DiscoveryHealthContractError,
        match="definition-version evidence",
    ):
        SourceObservationHealthInput(
            DEFINITION_ID,
            VERSION_ID,
            OUTCOME_ID,
            CheckOutcomeKind.SUCCESS_UNCHANGED,
            QuarantineDisposition.NONE,
            RECENT,
            RECENT,
            RECENT,
            OLD,
            True,
            True,
            True,
            (OUTCOME_EVIDENCE,),
        )

    wrong_outcome = HealthEvidenceReference(
        "CHECK_OUTCOME",
        "00000000-0000-4000-8000-000000009999",
        RECENT,
        "sha256:" + "9" * 64,
    )
    with pytest.raises(
        DiscoveryHealthContractError,
        match="exact Check outcome evidence",
    ):
        SourceObservationHealthInput(
            DEFINITION_ID,
            VERSION_ID,
            OUTCOME_ID,
            CheckOutcomeKind.SUCCESS_UNCHANGED,
            QuarantineDisposition.NONE,
            RECENT,
            RECENT,
            RECENT,
            OLD,
            True,
            True,
            True,
            tuple(
                sorted(
                    (VERSION_EVIDENCE, wrong_outcome),
                    key=lambda item: (
                        item.evidence_type,
                        item.identifier,
                        str(item.observed_at),
                        item.digest or "",
                    ),
                )
            ),
        )


def test_projection_health_without_positive_status_and_validation_is_unknown() -> None:
    generation = ProjectionGenerationId.parse(
        "00000000-0000-4000-8000-000000008099"
    )
    assessed = assess_projection_health(
        ProjectionHealthInput(
            family_id="graph.discovery_lineage",
            generation_id=generation,
            generation_state=ProjectionGenerationState.ACTIVE,
            service_available=True,
            query_valid=True,
            contracts_current=True,
            reconciliation_valid=True,
            contiguous_ledger_seq=20,
            authority_watermark_ledger_seq=20,
            open_gap_count=0,
            dead_letter_count=0,
            evidence=(
                HealthEvidenceReference(
                    "PROJECTION_STATUS",
                    str(generation),
                    RECENT,
                    "sha256:" + "8" * 64,
                ),
            ),
        ),
        policy=POLICY,
        assessed_at=NOW,
    )
    assert assessed.state is DiscoveryHealthState.UNKNOWN
    assert assessed.reason_code == "PROJECTION_POSITIVE_EVIDENCE_NOT_ESTABLISHED"


def test_successful_unchanged_is_healthy_and_quiet_history_is_not_stale() -> None:
    assessed = assessments_by_dimension(
        source_input(
            CheckOutcomeKind.SUCCESS_UNCHANGED,
            success_at=RECENT,
            complete_at=RECENT,
            change_at=OLD,
        )
    )

    assert assessed[DiscoveryHealthDimension.SOURCE_ACCESS].state is DiscoveryHealthState.HEALTHY
    assert assessed[DiscoveryHealthDimension.PARSER].state is DiscoveryHealthState.HEALTHY
    assert assessed[DiscoveryHealthDimension.CHECK_EXECUTION].state is DiscoveryHealthState.HEALTHY
    assert assessed[DiscoveryHealthDimension.OBSERVATION_FRESHNESS].state is DiscoveryHealthState.HEALTHY
    assert assessed[DiscoveryHealthDimension.OBSERVATION_FRESHNESS].last_source_change_at == OLD


def test_no_attempt_partial_parser_failure_and_outage_remain_distinct() -> None:
    no_attempt = assessments_by_dimension(
        source_input(None, success_at=None, complete_at=None, change_at=None, quarantine=None)
    )
    partial = assessments_by_dimension(source_input(CheckOutcomeKind.SUCCESS_PARTIAL))
    malformed = assessments_by_dimension(source_input(CheckOutcomeKind.MALFORMED))
    outage = assessments_by_dimension(
        source_input(
            CheckOutcomeKind.TRANSPORT_FAILED,
            success_at=None,
            complete_at=None,
        )
    )

    assert no_attempt[DiscoveryHealthDimension.CHECK_EXECUTION].state is DiscoveryHealthState.UNKNOWN
    assert partial[DiscoveryHealthDimension.PARSER].state is DiscoveryHealthState.DEGRADED
    assert malformed[DiscoveryHealthDimension.PARSER].state is DiscoveryHealthState.BLOCKED
    assert outage[DiscoveryHealthDimension.SOURCE_ACCESS].state is DiscoveryHealthState.UNAVAILABLE
    assert outage[DiscoveryHealthDimension.PARSER].state is DiscoveryHealthState.UNKNOWN


def test_source_health_keeps_semantic_integrity_separate_from_access() -> None:
    assessed = assessments_by_dimension(
        source_input(CheckOutcomeKind.SUCCESS_CHANGED, semantic_valid=False)
    )

    assert assessed[DiscoveryHealthDimension.SOURCE_ACCESS].state is DiscoveryHealthState.HEALTHY
    assert assessed[DiscoveryHealthDimension.SEMANTIC_LINEAGE].state is DiscoveryHealthState.QUARANTINED


def test_projection_health_attributes_service_gap_lag_and_tamper_separately() -> None:
    generation = ProjectionGenerationId.parse(
        "00000000-0000-4000-8000-000000008001"
    )
    base = dict(
        family_id="graph.discovery_lineage",
        generation_id=generation,
        generation_state=ProjectionGenerationState.ACTIVE,
        service_available=True,
        query_valid=True,
        contracts_current=True,
        reconciliation_valid=True,
        contiguous_ledger_seq=20,
        authority_watermark_ledger_seq=20,
        open_gap_count=0,
        dead_letter_count=0,
        evidence=(
            HealthEvidenceReference(
                "PROJECTION_STATUS",
                str(generation),
                RECENT,
                "sha256:" + "c" * 64,
            ),
            HealthEvidenceReference(
                "PROJECTION_VALIDATION",
                "sha256:" + "d" * 64,
                RECENT,
                "sha256:" + "e" * 64,
            ),
        ),
    )
    healthy = assess_projection_health(
        ProjectionHealthInput(**base), policy=POLICY, assessed_at=NOW
    )
    unavailable = assess_projection_health(
        ProjectionHealthInput(**{**base, "service_available": False}),
        policy=POLICY,
        assessed_at=NOW,
    )
    unknown = assess_projection_health(
        ProjectionHealthInput(**{**base, "service_available": None}),
        policy=POLICY,
        assessed_at=NOW,
    )
    blocked = assess_projection_health(
        ProjectionHealthInput(**{**base, "open_gap_count": 1}),
        policy=POLICY,
        assessed_at=NOW,
    )
    stale = assess_projection_health(
        ProjectionHealthInput(
            **{
                **base,
                "contiguous_ledger_seq": 19,
                "authority_watermark_ledger_seq": 20,
            }
        ),
        policy=POLICY,
        assessed_at=NOW,
    )
    quarantined = assess_projection_health(
        ProjectionHealthInput(**{**base, "reconciliation_valid": False}),
        policy=POLICY,
        assessed_at=NOW,
    )

    assert healthy.state is DiscoveryHealthState.HEALTHY
    assert unavailable.state is DiscoveryHealthState.UNAVAILABLE
    assert unknown.state is DiscoveryHealthState.UNKNOWN
    assert unknown.reason_code == "PROJECTION_SERVICE_NOT_ASSESSED"
    assert blocked.state is DiscoveryHealthState.BLOCKED
    assert stale.state is DiscoveryHealthState.STALE
    assert quarantined.state is DiscoveryHealthState.QUARANTINED


def path(
    name: str,
    function: PortfolioFunction,
    state: DiscoveryHealthState,
    *,
    substitute: bool = False,
) -> CoveragePathHealthInput:
    return CoveragePathHealthInput(
        name,
        "COV-021",
        (
            CoverageResponsibility.OPERATIONAL_RESILIENCE
            if substitute
            else CoverageResponsibility.ACTIVE
        ),
        CoverageContribution.DETECTION_PATH,
        frozenset({function}),
        state,
        substitute,
        (
            HealthEvidenceReference(
                "COVERAGE_PATH",
                name,
                RECENT,
                "sha256:" + "f" * 64,
            ),
        ),
    )


def test_comparator_count_cannot_repair_a_failed_anchor() -> None:
    assessed = assess_coverage_availability(
        (
            path("anchor", PortfolioFunction.ANCHOR, DiscoveryHealthState.UNAVAILABLE),
            path("comparator-a", PortfolioFunction.COMPARATOR, DiscoveryHealthState.HEALTHY),
            path("comparator-b", PortfolioFunction.COMPARATOR, DiscoveryHealthState.HEALTHY),
        ),
        obligation_id="COV-021",
        policy=POLICY,
        assessed_at=NOW,
    )

    assert assessed.state is DiscoveryHealthState.BLOCKED
    assert assessed.reason_code == "COVERAGE_ACTIVE_ANCHOR_UNAVAILABLE"


def test_only_explicit_contingency_can_degrade_instead_of_block() -> None:
    assessed = assess_coverage_availability(
        (
            path("anchor", PortfolioFunction.ANCHOR, DiscoveryHealthState.UNAVAILABLE),
            path(
                "contingency",
                PortfolioFunction.EXPLICIT_CONTINGENCY,
                DiscoveryHealthState.HEALTHY,
                substitute=True,
            ),
        ),
        obligation_id="COV-021",
        policy=POLICY,
        assessed_at=NOW,
    )

    assert assessed.state is DiscoveryHealthState.DEGRADED
    assert assessed.reason_code == "COVERAGE_EXPLICIT_CONTINGENCY_ACTIVE"


def test_review_quarantine_is_not_reported_as_healthy() -> None:
    assessed = assessments_by_dimension(
        source_input(
            CheckOutcomeKind.SHAPE_DRIFT,
            quarantine=QuarantineDisposition.REVIEW,
        )
    )

    assert assessed[DiscoveryHealthDimension.SOURCE_ACCESS].state is DiscoveryHealthState.QUARANTINED
    assert assessed[DiscoveryHealthDimension.PARSER].state is DiscoveryHealthState.QUARANTINED
    assert assessed[DiscoveryHealthDimension.CHECK_EXECUTION].state is DiscoveryHealthState.QUARANTINED


def test_source_path_collapse_requires_positive_health_in_every_dimension() -> None:
    healthy = tuple(assessments_by_dimension(source_input(CheckOutcomeKind.SUCCESS_UNCHANGED)).values())
    assert summarize_source_path_state(healthy) is DiscoveryHealthState.HEALTHY

    quarantined = tuple(
        assessments_by_dimension(
            source_input(
                CheckOutcomeKind.SHAPE_DRIFT,
                quarantine=QuarantineDisposition.REVIEW,
            )
        ).values()
    )
    assert summarize_source_path_state(quarantined) is DiscoveryHealthState.QUARANTINED


def test_empty_coverage_path_set_is_unknown_not_healthy() -> None:
    assessed = assess_coverage_availability(
        (),
        obligation_id="COV-EMPTY",
        policy=POLICY,
        assessed_at=NOW,
    )

    assert assessed.state is DiscoveryHealthState.UNKNOWN
    assert assessed.reason_code == "COVERAGE_ANCHOR_NOT_DEFINED"


def test_coverage_substitute_requires_retained_contingency_contract() -> None:
    with pytest.raises(
        DiscoveryHealthContractError,
        match="operational-resilience contingency",
    ):
        path(
            "self-declared-substitute",
            PortfolioFunction.COMPARATOR,
            DiscoveryHealthState.HEALTHY,
            substitute=True,
        )


def test_coverage_path_evidence_is_canonical() -> None:
    evidence = HealthEvidenceReference(
        "COVERAGE_PATH",
        "duplicate-evidence",
        RECENT,
        "sha256:" + "f" * 64,
    )
    with pytest.raises(DiscoveryHealthContractError, match="sorted and unique"):
        CoveragePathHealthInput(
            "duplicate-evidence",
            "COV-021",
            CoverageResponsibility.ACTIVE,
            CoverageContribution.DETECTION_PATH,
            frozenset({PortfolioFunction.ANCHOR}),
            DiscoveryHealthState.HEALTHY,
            False,
            (evidence, evidence),
        )
