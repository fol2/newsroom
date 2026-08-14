from __future__ import annotations

import json
import uuid
from dataclasses import replace

import pytest

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.increment7.coverage import (
    COVERAGE_LIMITATION_AUTHORITY,
    COVERAGE_PROSPECTIVE_RETROSPECTIVE_BOUNDARY,
    CoverageAssessmentState,
    CoverageAudit,
    CoverageAuditMode,
    CoverageBasisKind,
    CoverageComparator,
    CoverageContractError,
    CoverageGap,
    CoverageGapDecision,
    CoverageGapDisposition,
    CoverageGapScope,
    CoverageGapState,
    CoverageObservation,
    CoverageObservationKind,
    validate_coverage_chain,
)

_D = "sha256:" + "a" * 64


def _id(value: int) -> str:
    return str(uuid.UUID(int=value, version=4))


def _comparator(
    mode: CoverageAuditMode = CoverageAuditMode.PROSPECTIVE_PRE_REGISTERED,
) -> CoverageComparator:
    return CoverageComparator(
        _id(1),
        mode,
        CoverageBasisKind.PLANNED_AGENDA,
        "fixture.policy.decision",
        (_D,),
        ("sha256:" + "b" * 64,),
        ("PUBLIC_BODY_NOTICES",),
        ("sha256:" + "c" * 64,),
        "2026-08-14T01:00:00.000000Z",
        "2026-08-14T02:00:00.000000Z",
        None
        if mode is CoverageAuditMode.PROSPECTIVE_PRE_REGISTERED
        else "sha256:" + "d" * 64,
        ("sha256:" + "e" * 64,),
        (
            "2026-08-14T00:00:00.000000Z"
            if mode is CoverageAuditMode.PROSPECTIVE_PRE_REGISTERED
            else "2026-08-14T03:00:00.000000Z"
        ),
    )


def _chain(
    mode: CoverageAuditMode = CoverageAuditMode.PROSPECTIVE_PRE_REGISTERED,
):
    comparator = _comparator(mode)
    observation = CoverageObservation(
        CoverageObservationKind.EXPECTATION_NOT_OBSERVED,
        _D,
        "2026-08-14T03:00:00.000000Z",
    )
    audit = CoverageAudit(
        _id(2),
        comparator.comparator_id,
        comparator.digest,
        mode,
        (observation,),
        CoverageAssessmentState.COMPLETE_BEST_EFFORT,
        ("KNOWN_SOURCE_LIMITATIONS",),
        "sha256:" + "f" * 64,
        "2026-08-14T04:00:00.000000Z",
    )
    gap = CoverageGap(
        _id(3),
        audit.audit_id,
        audit.digest,
        CoverageGapScope.ISOLATED,
        CoverageGapState.PROPOSED,
        comparator.coverage_unit_digests,
        comparator.expectation_reference_digests,
        (),
        audit.limitation_codes,
        "2026-08-14T05:00:00.000000Z",
    )
    decision = CoverageGapDecision(
        _id(4),
        gap.gap_id,
        gap.digest,
        CoverageGapDisposition.CONFIRMED_BEST_EFFORT_GAP,
        (_D,),
        gap.limitation_codes,
        "sha256:" + "1" * 64,
        ("REVIEWED_EXPECTATION_NOT_OBSERVED",),
        None,
        "2026-08-14T06:00:00.000000Z",
    )
    return comparator, audit, gap, decision


def test_prospective_chain_is_pre_registered_reviewed_and_non_effectful() -> None:
    records = _chain()
    validate_coverage_chain(*records)
    comparator, audit, gap, first = records
    successor = replace(
        first,
        decision_id=_id(5),
        supersedes_decision_digest=first.digest,
        decided_at="2026-08-14T07:00:00.000000Z",
    )
    validate_coverage_chain(comparator, audit, gap, successor, first)
    with pytest.raises(CoverageContractError, match="predecessor"):
        validate_coverage_chain(
            comparator,
            audit,
            gap,
            replace(successor, decision_id=first.decision_id),
            first,
        )
    kinds = (CoverageComparator, CoverageAudit, CoverageGap, CoverageGapDecision)
    for record, kind in zip(records, kinds, strict=True):
        assert kind.from_canonical_bytes(record.canonical_bytes) == record
        assert record.authorises_search is False
        assert record.authorises_evidence is False
        assert record.gap_is_automatic_truth is False
        assert record.creates_watch is False
        assert record.creates_candidate is False
    assert (
        COVERAGE_PROSPECTIVE_RETROSPECTIVE_BOUNDARY
        == "PRE_REGISTERED_VS_LABELLED_HINDSIGHT"
    )
    assert COVERAGE_LIMITATION_AUTHORITY == "BEST_EFFORT_EXPLICIT_OR_DEFERRED"


def test_retrospective_investigation_remains_explicit_hindsight() -> None:
    records = _chain(CoverageAuditMode.RETROSPECTIVE_INVESTIGATION)
    validate_coverage_chain(*records)
    comparator, audit, gap, decision = records
    assert comparator.retrospective_trigger_digest is not None
    for record in records:
        assert record.hindsight_promoted_to_prospective is False
    with pytest.raises(CoverageContractError, match="pre-registered"):
        replace(
            comparator,
            audit_mode=CoverageAuditMode.PROSPECTIVE_PRE_REGISTERED,
            retrospective_trigger_digest=None,
        )
    with pytest.raises(CoverageContractError, match="lineage"):
        validate_coverage_chain(
            comparator,
            replace(audit, audit_mode=CoverageAuditMode.PROSPECTIVE_PRE_REGISTERED),
            gap,
            decision,
        )


def test_deferred_assessment_cannot_receive_conclusive_gap_disposition() -> None:
    comparator, audit, gap, decision = _chain()
    deferred_audit = replace(
        audit,
        assessment_state=CoverageAssessmentState.DEFERRED,
    )
    deferred_gap = replace(
        gap,
        audit_digest=deferred_audit.digest,
        gap_scope=CoverageGapScope.UNDETERMINED,
        gap_state=CoverageGapState.DEFERRED_ASSESSMENT,
    )
    deferred = replace(
        decision,
        gap_digest=deferred_gap.digest,
        disposition=CoverageGapDisposition.DEFERRED_INSUFFICIENT_BASIS,
    )
    validate_coverage_chain(comparator, deferred_audit, deferred_gap, deferred)
    with pytest.raises(CoverageContractError, match="conclusive"):
        validate_coverage_chain(
            comparator,
            deferred_audit,
            deferred_gap,
            replace(
                deferred, disposition=CoverageGapDisposition.CONFIRMED_BEST_EFFORT_GAP
            ),
        )


def test_isolated_systemic_and_limitation_boundaries_fail_closed() -> None:
    comparator, audit, gap, decision = _chain()
    with pytest.raises(CoverageContractError, match="isolated"):
        replace(
            gap,
            affected_coverage_unit_digests=("sha256:" + "2" * 64, "sha256:" + "3" * 64),
        )
    with pytest.raises(CoverageContractError, match="systemic"):
        replace(
            gap,
            gap_scope=CoverageGapScope.SYSTEMIC,
            affected_coverage_unit_digests=("sha256:" + "2" * 64, "sha256:" + "3" * 64),
        )
    with pytest.raises(CoverageContractError, match="review basis"):
        validate_coverage_chain(
            comparator,
            audit,
            gap,
            replace(decision, acknowledged_limitation_codes=("OTHER_LIMIT",)),
        )


def test_unknown_duplicate_and_noncanonical_coverage_bytes_are_rejected() -> None:
    comparator, *_ = _chain()
    value = json.loads(comparator.canonical_bytes)
    value["automatic_gap_truth"] = True
    with pytest.raises(CoverageContractError, match="fields"):
        CoverageComparator.from_canonical_bytes(canonical_json_bytes(value))
    duplicate = comparator.canonical_bytes.replace(
        b'"subject_key":', b'"subject_key":"other","subject_key":', 1
    )
    with pytest.raises(CoverageContractError, match="duplicate"):
        CoverageComparator.from_canonical_bytes(duplicate)
    with pytest.raises(CoverageContractError, match="canonical JSON"):
        CoverageComparator.from_canonical_bytes(comparator.canonical_bytes + b" ")
