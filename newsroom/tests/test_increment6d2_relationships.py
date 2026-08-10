from __future__ import annotations

import json
import uuid
from dataclasses import replace

import pytest

from newsroom.increment6.hypotheses import (
    EventHypothesis,
    EventHypothesisVersion,
    HypothesisSourceBinding,
)
from newsroom.increment6.proposals import HypothesisRelationship
from newsroom.increment6.relationships import (
    HYPOTHESIS_RELATIONSHIP_DECISION,
    RELATIONSHIP_DECISION_REASON,
    AssessmentStatus,
    ComparatorEvidence,
    ComparatorSetManifest,
    HypothesisVersionBinding,
    RelationshipAssessment,
    RelationshipContractError,
    RelationshipDecision,
    RelationshipDecisionReason,
    assess_relationships,
)

D1 = "sha256:" + "1" * 64
D2 = "sha256:" + "2" * 64


def _version(
    seed: int,
    *,
    relationship: HypothesisRelationship = HypothesisRelationship.NO_ADEQUATE_PRIOR_MATCH,
) -> EventHypothesisVersion:
    proposal_id = str(uuid.UUID(int=seed))
    hypothesis = EventHypothesis.allocate(proposal_id, f"local-{seed}")
    source = HypothesisSourceBinding(
        D1,
        D2,
        D1,
        D2,
        str(uuid.UUID(int=seed + 100)),
        D1,
        str(uuid.UUID(int=seed + 200)),
        D2,
    )
    return EventHypothesisVersion(
        str(uuid.uuid5(uuid.UUID(hypothesis.hypothesis_id), "version:1")),
        hypothesis.hypothesis_id,
        1,
        None,
        None,
        f"Summary {seed}",
        relationship,
        None,
        None,
        None,
        proposal_id,
        D1,
        D2,
        f"local-{seed}",
        str(uuid.UUID(int=seed + 300)),
        str(uuid.UUID(int=seed + 400)),
        D1,
        str(uuid.UUID(int=seed + 500)),
        D2,
        (source,),
        D1,
        str(uuid.UUID(int=seed + 600)),
        "2042-01-01T00:00:00.000000Z",
    )


def _binding(seed: int) -> HypothesisVersionBinding:
    return HypothesisVersionBinding.from_version(_version(seed))


def _evidence(
    subject: HypothesisVersionBinding,
    comparator: HypothesisVersionBinding,
    **scores: int,
) -> ComparatorEvidence:
    values = {
        "score": 70,
        "correction_reversal_score": 0,
        "development_score": 0,
        "same_state_score": 0,
        "related_distinct_score": 0,
    }
    values.update(scores)
    return ComparatorEvidence(subject, comparator, **values)


@pytest.mark.parametrize(
    ("scores", "decision", "reason"),
    [
        (
            {"same_state_score": 80},
            RelationshipDecision.REL_SAME_STATE,
            RelationshipDecisionReason.SAME_STATE_THRESHOLD_MET,
        ),
        (
            {"development_score": 75},
            RelationshipDecision.REL_DEVELOPMENT_OF,
            RelationshipDecisionReason.DEVELOPMENT_THRESHOLD_MET,
        ),
        (
            {"correction_reversal_score": 80},
            RelationshipDecision.REL_CORRECTION_REVERSAL_OF,
            RelationshipDecisionReason.CORRECTION_REVERSAL_THRESHOLD_MET,
        ),
        (
            {"related_distinct_score": 60},
            RelationshipDecision.REL_RELATED_DISTINCT,
            RelationshipDecisionReason.RELATED_DISTINCT_THRESHOLD_MET,
        ),
        (
            {"score": 59},
            RelationshipDecision.REL_NO_ADEQUATE_PRIOR_MATCH,
            RelationshipDecisionReason.COMPLETE_SET_NO_ADEQUATE_MATCH,
        ),
        (
            {"score": 60},
            RelationshipDecision.REL_UNCERTAIN,
            RelationshipDecisionReason.ADEQUATE_MATCH_CLASSIFICATION_UNCERTAIN,
        ),
    ],
)
def test_six_separate_decisions_and_closed_reason_matrix(
    scores: dict[str, int],
    decision: RelationshipDecision,
    reason: RelationshipDecisionReason,
) -> None:
    subject, comparator = _binding(1), _binding(2)
    result = assess_relationships(
        subject,
        ComparatorSetManifest.complete((comparator,)),
        (_evidence(subject, comparator, **scores),),
    )
    assert result.decision is decision
    assert result.reason is reason
    assert reason in RELATIONSHIP_DECISION_REASON[decision]
    if decision is RelationshipDecision.REL_NO_ADEQUATE_PRIOR_MATCH:
        assert result.comparator is None
    else:
        assert result.comparator == comparator
    assert RelationshipAssessment.from_canonical_bytes(result.canonical_bytes) == result
    assert (
        HYPOTHESIS_RELATIONSHIP_DECISION
        == "newsroom.increment6.hypothesis-relationship-decision.v1"
    )
    assert {item.value for item in RelationshipDecision} == {
        "REL_SAME_STATE",
        "REL_DEVELOPMENT_OF",
        "REL_CORRECTION_REVERSAL_OF",
        "REL_RELATED_DISTINCT",
        "REL_NO_ADEQUATE_PRIOR_MATCH",
        "REL_UNCERTAIN",
    }


def test_exact_version_source_actor_comparator_and_disposition_binding() -> None:
    version = _version(3)
    binding = HypothesisVersionBinding.from_version(version)
    assert binding.hypothesis_id == version.hypothesis_id
    assert binding.version_id == version.version_id
    assert binding.version_digest == version.canonical_digest
    assert binding.actor_identity_digest == version.actor_identity_digest
    assert binding.source_bindings == version.source_bindings
    assert (
        HypothesisVersionBinding.from_canonical_bytes(binding.canonical_bytes)
        == binding
    )
    with pytest.raises(RelationshipContractError):
        replace(binding, source_bindings=())

    comparator = _binding(30)
    manifest = ComparatorSetManifest.complete((comparator,))
    evidence = _evidence(binding, comparator, same_state_score=80)
    assert (
        ComparatorSetManifest.from_canonical_bytes(manifest.canonical_bytes) == manifest
    )
    assert ComparatorEvidence.from_canonical_bytes(evidence.canonical_bytes) == evidence
    assessment = assess_relationships(binding, manifest, (evidence,))
    assert assessment.comparator_manifest_digest == manifest.canonical_digest


def test_threshold_edges_precedence_tie_permutation_and_replay() -> None:
    subject, a, b = _binding(4), _binding(5), _binding(6)
    manifest = ComparatorSetManifest.complete((a, b))
    ea = _evidence(subject, a, score=90, same_state_score=99, development_score=75)
    eb = _evidence(
        subject, b, score=70, correction_reversal_score=80, development_score=99
    )
    result = assess_relationships(subject, manifest, (ea, eb))
    assert result.decision is RelationshipDecision.REL_CORRECTION_REVERSAL_OF
    assert result.comparator == b
    assert result == assess_relationships(subject, manifest, (eb, ea))

    tied = ComparatorSetManifest.complete(
        tuple(sorted((a, b), key=lambda item: item.version_id))
    )
    first = min((a, b), key=lambda item: item.version_id)
    tie_result = assess_relationships(
        subject,
        tied,
        (
            _evidence(subject, b, score=80, related_distinct_score=60),
            _evidence(subject, a, score=80, related_distinct_score=60),
        ),
    )
    assert tie_result.comparator == first
    score_result = assess_relationships(
        subject,
        tied,
        (
            _evidence(subject, a, score=70, related_distinct_score=60),
            _evidence(subject, b, score=90, related_distinct_score=60),
        ),
    )
    assert score_result.comparator == b


def test_false_merge_split_and_temporal_correction_precedence() -> None:
    subject, comparator = _binding(7), _binding(8)
    manifest = ComparatorSetManifest.complete((comparator,))
    distinct = assess_relationships(
        subject,
        manifest,
        (
            _evidence(
                subject, comparator, same_state_score=79, related_distinct_score=60
            ),
        ),
    )
    assert distinct.decision is RelationshipDecision.REL_RELATED_DISTINCT
    correction = assess_relationships(
        subject,
        manifest,
        (
            _evidence(
                subject, comparator, correction_reversal_score=80, development_score=100
            ),
        ),
    )
    assert correction.decision is RelationshipDecision.REL_CORRECTION_REVERSAL_OF


@pytest.mark.parametrize(
    "status", [AssessmentStatus.INCOMPLETE, AssessmentStatus.UNAVAILABLE]
)
def test_partial_or_unavailable_comparator_sets_never_become_uncertain_or_positive(
    status: AssessmentStatus,
) -> None:
    subject, comparator = _binding(9), _binding(29)
    partial = (comparator,) if status is AssessmentStatus.INCOMPLETE else ()
    result = assess_relationships(subject, ComparatorSetManifest(status, partial), ())
    assert result.status is status
    assert result.decision is result.reason is result.comparator is None
    assert result.authorises_relationship is False
    if status is AssessmentStatus.UNAVAILABLE:
        with pytest.raises(RelationshipContractError):
            ComparatorSetManifest(status, (comparator,))


def test_empty_complete_set_is_no_match_and_manifest_integrity_is_strict() -> None:
    subject, comparator = _binding(10), _binding(11)
    result = assess_relationships(subject, ComparatorSetManifest.complete(()), ())
    assert result.decision is RelationshipDecision.REL_NO_ADEQUATE_PRIOR_MATCH
    with pytest.raises(RelationshipContractError):
        ComparatorSetManifest.complete((comparator, comparator))
    with pytest.raises(RelationshipContractError):
        assess_relationships(subject, ComparatorSetManifest.complete((comparator,)), ())
    with pytest.raises(RelationshipContractError):
        assess_relationships(
            subject,
            ComparatorSetManifest.complete((comparator,)),
            (_evidence(_binding(12), comparator),),
        )
    with pytest.raises(RelationshipContractError):
        assess_relationships(
            subject,
            ComparatorSetManifest.complete((comparator,)),
            (
                _evidence(subject, comparator),
                _evidence(subject, comparator),
            ),
        )
    stale = replace(comparator, actor_identity_digest=D2)
    with pytest.raises(RelationshipContractError):
        assess_relationships(
            subject,
            ComparatorSetManifest.complete((comparator,)),
            (_evidence(subject, stale),),
        )


def test_legal_maximum_comparator_producer_round_trips() -> None:
    from newsroom.increment6 import relationships as module

    subject = _binding(1000)
    comparators = tuple(
        _binding(seed) for seed in range(1001, 1001 + module.MAX_COMPARATORS)
    )
    manifest = ComparatorSetManifest.complete(comparators)
    evidence = tuple(
        _evidence(subject, comparator, score=59) for comparator in comparators
    )
    result = assess_relationships(subject, manifest, evidence)
    assert result.decision is RelationshipDecision.REL_NO_ADEQUATE_PRIOR_MATCH
    assert RelationshipAssessment.from_canonical_bytes(result.canonical_bytes) == result


def test_integer_only_scores_bounds_and_no_effects() -> None:
    subject, comparator = _binding(13), _binding(14)
    for score in (True, 1.0, -1, 101, 2**100):
        with pytest.raises(RelationshipContractError):
            _evidence(subject, comparator, score=score)  # type: ignore[arg-type]
    result = assess_relationships(subject, ComparatorSetManifest.complete(()), ())
    for name in (
        "authorises_authority",
        "authorises_persistence",
        "authorises_external_effect",
        "authorises_publication",
        "authorises_evidence",
        "authorises_egress",
        "creates_candidate",
        "creates_lineage",
        "creates_relationship",
        "authorises_relationship",
    ):
        assert getattr(result, name) is False


@pytest.mark.parametrize(
    "raw",
    [
        b"[]",
        b"true",
        b"1.0",
        b'{"x":9223372036854775808}',
        b'{"schema_version":"x","schema_version":"x"}',
        b'{ "schema_version":"x"}',
        b'{"schema_version":"\\ud800"}',
        b'{"schema_version":"x","unknown":1}',
    ],
)
def test_noncanonical_unknown_huge_float_duplicate_and_surrogate_inputs_fail_closed(
    raw: bytes,
) -> None:
    with pytest.raises(RelationshipContractError):
        RelationshipAssessment.from_canonical_bytes(raw)


def test_oversize_deep_cycle_typed_impostor_and_uninitialised_are_total() -> None:
    from newsroom.increment6 import relationships as module

    with pytest.raises(RelationshipContractError):
        RelationshipAssessment.from_canonical_bytes(
            b"{" + b" " * module.MAX_RELATIONSHIP_CANONICAL_BYTES + b"}"
        )
    deep: object = None
    for _ in range(30):
        deep = [deep]
    with pytest.raises(RelationshipContractError):
        RelationshipAssessment.from_canonical_bytes(
            json.dumps({"x": deep}, separators=(",", ":")).encode()
        )

    class TupleImpostor(tuple):
        pass

    with pytest.raises(RelationshipContractError):
        ComparatorSetManifest(AssessmentStatus.COMPLETE, TupleImpostor())
    value = object.__new__(RelationshipAssessment)
    with pytest.raises(RelationshipContractError):
        _ = value.canonical_bytes
    cyclic: list[object] = []
    cyclic.append(cyclic)
    with pytest.raises(RelationshipContractError):
        module._canonical(cyclic, "cycle")


def test_ordinary_exceptions_are_normalised_and_base_exceptions_preserved() -> None:
    from newsroom.increment6 import relationships as module

    for exc in (RuntimeError(), KeyError(), AttributeError()):
        with pytest.raises(RelationshipContractError):
            module._normalise(lambda exc=exc: (_ for _ in ()).throw(exc), "failed")
    for exc_type in (KeyboardInterrupt, SystemExit):
        with pytest.raises(exc_type):
            module._normalise(
                lambda exc_type=exc_type: (_ for _ in ()).throw(exc_type()), "failed"
            )
