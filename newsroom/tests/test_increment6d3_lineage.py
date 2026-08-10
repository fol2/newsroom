from __future__ import annotations

import json
import uuid
from dataclasses import replace

import pytest

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.increment6.hypotheses import (
    EventHypothesis,
    EventHypothesisVersion,
    HypothesisSourceBinding,
)
from newsroom.increment6.lineage import (
    HYPOTHESIS_CONSOLIDATION,
    HYPOTHESIS_LINEAGE,
    HYPOTHESIS_REVERSAL_LINEAGE,
    HYPOTHESIS_SPLIT,
    HypothesisLineageContractError,
    HypothesisLineageHead,
    HypothesisLineageKind,
    HypothesisLineageNodeBinding,
    HypothesisLineageReceipt,
    HypothesisLineageRelationshipBinding,
    HypothesisLineageRelationshipProof,
    HypothesisLineageTarget,
    replay_hypothesis_lineage,
    verify_hypothesis_lineage_receipt,
)
from newsroom.increment6.outcomes import CanonicalOutcome
from newsroom.increment6.proposals import HypothesisRelationship
from newsroom.increment6.relationships import (
    AssessmentStatus,
    ComparatorEvidence,
    ComparatorSetManifest,
    HypothesisVersionBinding,
    RelationshipAssessment,
    assess_relationships,
)

D1 = "sha256:" + "1" * 64
D2 = "sha256:" + "2" * 64
_VERSIONS: dict[str, EventHypothesisVersion] = {}
_PROOFS: dict[str, HypothesisLineageRelationshipProof] = {}


def _version(seed: int) -> EventHypothesisVersion:
    proposal_id = str(uuid.UUID(int=seed))
    hypothesis = EventHypothesis.allocate(proposal_id, f"local-{seed}")
    source = HypothesisSourceBinding(
        "sha256:" + f"{seed:064x}",
        D2,
        D1,
        D2,
        str(uuid.UUID(int=seed + 10_000)),
        D1,
        str(uuid.UUID(int=seed + 20_000)),
        D2,
    )
    version = EventHypothesisVersion(
        str(uuid.uuid5(uuid.UUID(hypothesis.hypothesis_id), "version:1")),
        hypothesis.hypothesis_id,
        1,
        None,
        None,
        f"Summary {seed}",
        HypothesisRelationship.NO_ADEQUATE_PRIOR_MATCH,
        None,
        None,
        None,
        proposal_id,
        D1,
        D2,
        f"local-{seed}",
        f"work-{seed}",
        f"work-version-{seed}",
        D1,
        f"context-{seed}",
        D2,
        (source,),
        D1,
        str(uuid.UUID(int=seed + 30_000)),
        "2042-01-01T00:00:00.000000Z",
    )
    _VERSIONS[version.version_id] = version
    return version


def _successor(version: EventHypothesisVersion, seed: int) -> EventHypothesisVersion:
    ordinal = version.ordinal + 1
    successor = replace(
        version,
        version_id=str(
            uuid.uuid5(uuid.UUID(version.hypothesis_id), f"version:{ordinal}")
        ),
        ordinal=ordinal,
        previous_version_id=version.version_id,
        previous_version_digest=version.canonical_digest,
        proposed_summary=f"Restored {seed}",
        proposed_relationship=HypothesisRelationship.CORRECTION_REVERSAL_OF,
        proposed_target_hypothesis_id=version.hypothesis_id,
        target_version_id=version.version_id,
        target_version_digest=version.canonical_digest,
        proposal_id=f"proposal-{seed}",
        proposal_local_id=f"restore-{seed}",
        authority_event_id=str(uuid.UUID(int=seed + 40_000)),
    )
    _VERSIONS[successor.version_id] = successor
    return successor


def _decision(
    subject_version: EventHypothesisVersion,
    comparator_versions: tuple[EventHypothesisVersion, ...],
    outcome: CanonicalOutcome,
) -> tuple[RelationshipAssessment, tuple[ComparatorEvidence, ...]]:
    subject = HypothesisVersionBinding.from_version(subject_version)
    comparators = tuple(
        HypothesisVersionBinding.from_version(version)
        for version in comparator_versions
    )
    evidence: list[ComparatorEvidence] = []
    for comparator in comparators:
        scores = {
            "score": 59,
            "correction_reversal_score": 0,
            "development_score": 0,
            "same_state_score": 0,
            "related_distinct_score": 0,
        }
        if outcome is CanonicalOutcome.REL_SAME_STATE:
            scores["same_state_score"] = 80
        elif outcome is CanonicalOutcome.REL_RELATED_DISTINCT:
            scores["related_distinct_score"] = 60
        elif outcome is CanonicalOutcome.REL_CORRECTION_REVERSAL_OF:
            scores["correction_reversal_score"] = 80
        else:  # pragma: no cover - test helper guard
            raise AssertionError(outcome)
        evidence.append(ComparatorEvidence(subject, comparator, **scores))
    result = assess_relationships(
        subject, ComparatorSetManifest.complete(comparators), tuple(evidence)
    )
    assert result.decision is outcome
    return result, tuple(evidence)


def _assessment(
    subject: EventHypothesisVersion,
    comparator: EventHypothesisVersion,
    outcome: CanonicalOutcome,
) -> RelationshipAssessment:
    return _decision(subject, (comparator,), outcome)[0]


def _proof(
    subject: EventHypothesisVersion,
    comparators: tuple[EventHypothesisVersion, ...],
    outcome: CanonicalOutcome,
) -> HypothesisLineageRelationshipProof:
    assessment, evidence = _decision(subject, comparators, outcome)
    proof = HypothesisLineageRelationshipProof.from_assessment(assessment, evidence)
    _PROOFS[proof.binding.assessment_digest] = proof
    return proof


def _consolidation(
    inputs: tuple[EventHypothesisVersion, ...],
    output: EventHypothesisVersion,
    generation: int = 0,
) -> HypothesisLineageReceipt:
    return HypothesisLineageReceipt.consolidation(
        expected_generation=generation,
        inputs=inputs,
        output=output,
        relationship_proofs=(_proof(output, inputs, CanonicalOutcome.REL_SAME_STATE),),
    )


def _split(
    source: EventHypothesisVersion,
    outputs: tuple[EventHypothesisVersion, ...],
    generation: int = 0,
) -> HypothesisLineageReceipt:
    return HypothesisLineageReceipt.split(
        expected_generation=generation,
        source=source,
        outputs=outputs,
        relationship_proofs=tuple(
            _proof(
                output,
                (source, *(item for item in outputs if item != output)),
                CanonicalOutcome.REL_RELATED_DISTINCT,
            )
            for output in outputs
        ),
    )


def _heads(*versions: EventHypothesisVersion) -> tuple[HypothesisLineageHead, ...]:
    return tuple(HypothesisLineageHead.from_version(version) for version in versions)


def _replay(
    receipts: tuple[HypothesisLineageReceipt, ...],
    initial_heads: tuple[HypothesisLineageHead, ...],
) -> object:
    nodes = {
        node.version_id: node
        for receipt in receipts
        for node in (*receipt.inputs, *receipt.outputs)
    }
    nodes.update({head.node.version_id: head.node for head in initial_heads})
    proofs = {
        binding.assessment_digest: _PROOFS[binding.assessment_digest]
        for receipt in receipts
        for binding in receipt.relationships
    }
    return replay_hypothesis_lineage(
        receipts,
        initial_heads=initial_heads,
        versions=tuple(_VERSIONS[version_id] for version_id in nodes),
        relationship_proofs=tuple(proofs.values()),
    )


def test_public_contract_roundtrip_identity_and_no_effect_boundary() -> None:
    left, right, output = _version(1), _version(2), _version(3)
    receipt = _consolidation((right, left), output)
    replayed = HypothesisLineageReceipt.from_canonical_bytes(receipt.canonical_bytes)

    assert replayed == receipt
    assert replayed.canonical_digest.startswith("sha256:")
    assert receipt.inputs == tuple(
        sorted(
            receipt.inputs,
            key=lambda item: (item.hypothesis_id, item.version_id, item.version_digest),
        )
    )
    assert HYPOTHESIS_LINEAGE == "newsroom.increment6.hypothesis-lineage.v1"
    assert {
        HYPOTHESIS_CONSOLIDATION,
        HYPOTHESIS_SPLIT,
        HYPOTHESIS_REVERSAL_LINEAGE,
    } == {item.value for item in HypothesisLineageKind}
    for name in (
        "authorises_authority",
        "authorises_persistence",
        "authorises_external_effect",
        "authorises_publication",
        "authorises_evidence",
        "authorises_egress",
        "authorises_relationship",
        "creates_candidate",
        "creates_hypothesis",
        "creates_version",
        "creates_relationship",
    ):
        assert getattr(receipt, name) is False


def test_semantic_id_excludes_outputs_and_basis_but_divergent_retry_fails() -> None:
    left, right = _version(10), _version(11)
    first = _consolidation((left, right), _version(12))
    divergent = _consolidation((left, right), _version(13))
    assert first.lineage_id == divergent.lineage_id
    assert first.canonical_bytes != divergent.canonical_bytes

    initial = _heads(left, right)
    result = _replay((first, first), initial_heads=initial)
    assert result.history == (first,)
    assert len(result.edges) == 2
    with pytest.raises(HypothesisLineageContractError, match="divergent"):
        _replay((first, divergent), initial_heads=initial)


def test_valid_consolidation_consumes_heads_without_mutating_predecessors() -> None:
    left, right, output = _version(20), _version(21), _version(22)
    left_bytes, right_bytes = left.canonical_bytes, right.canonical_bytes
    receipt = _consolidation((left, right), output)
    result = _replay((receipt,), initial_heads=_heads(left, right))

    assert result.active_heads == (HypothesisLineageHead.from_version(output, 1),)
    assert {item.version_id for item in result.consumed} == {
        left.version_id,
        right.version_id,
    }
    assert left.canonical_bytes == left_bytes
    assert right.canonical_bytes == right_bytes


def test_mixed_generation_replay_fails_and_retained_result_is_immutable() -> None:
    left, right, merged, unrelated = (
        _version(30),
        _version(31),
        _version(32),
        _version(33),
    )
    first = _consolidation((left, right), merged)
    retained = _replay((first,), initial_heads=_heads(left, right, unrelated))
    before = retained.active_heads
    mixed = _consolidation((merged, unrelated), _version(34), generation=1)
    with pytest.raises(HypothesisLineageContractError, match="mixed-generation"):
        _replay((first, mixed), initial_heads=_heads(left, right, unrelated))
    assert retained.active_heads == before


def test_valid_split_and_exact_32_way_pair_coverage_envelope() -> None:
    source = _version(100)
    outputs = tuple(_version(seed) for seed in range(101, 133))
    receipt = _split(source, outputs)
    assert len(receipt.relationships) == 32
    assert sum(len(item.evidence) for item in receipt.relationships) == 1_024
    assert len({item.subject.version_id for item in receipt.relationships}) == 32
    assert len(receipt.canonical_bytes) < 1_048_576
    result = _replay((receipt,), initial_heads=_heads(source))
    assert len(result.active_heads) == 32
    assert {head.generation for head in result.active_heads} == {1}


def test_split_rejects_missing_extra_wrong_or_incomplete_decision_basis() -> None:
    source, left, right = _version(200), _version(201), _version(202)
    valid = _split(source, (left, right))
    cases = (
        valid.relationships[:-1],
        valid.relationships
        + (_proof(source, (left,), CanonicalOutcome.REL_RELATED_DISTINCT).binding,),
        tuple(
            replace(item, outcome=CanonicalOutcome.REL_SAME_STATE)
            if index == 0
            else item
            for index, item in enumerate(valid.relationships)
        ),
        (
            replace(
                valid.relationships[0], evidence=valid.relationships[0].evidence[:-1]
            ),
        )
        + valid.relationships[1:],
    )
    for relationships in cases:
        with pytest.raises(HypothesisLineageContractError):
            HypothesisLineageReceipt._build(
                HypothesisLineageKind.SPLIT,
                0,
                valid.inputs,
                valid.outputs,
                tuple(
                    sorted(
                        relationships,
                        key=lambda item: (
                            item.subject.version_id,
                            item.assessment_digest,
                        ),
                    )
                ),
            )


def test_valid_reversal_restores_exact_hypothesis_identities_with_new_versions() -> (
    None
):
    left, right, merged = _version(300), _version(301), _version(302)
    consolidation = _consolidation((left, right), merged)
    restored = (_successor(left, 303), _successor(right, 304))
    reversal = HypothesisLineageReceipt.reversal(
        expected_generation=1,
        target=consolidation,
        outputs=restored,
        relationship_proofs=tuple(
            _proof(output, (merged,), CanonicalOutcome.REL_CORRECTION_REVERSAL_OF)
            for output in restored
        ),
    )
    result = _replay((consolidation, reversal), initial_heads=_heads(left, right))
    assert {head.node.hypothesis_id for head in result.active_heads} == {
        left.hypothesis_id,
        right.hypothesis_id,
    }
    assert {head.generation for head in result.active_heads} == {2}
    assert result.history == (consolidation, reversal)


def test_split_reversal_uses_one_subject_for_all_superseded_outputs() -> None:
    source = _version(305)
    split_outputs = (_version(306), _version(307))
    split = _split(source, split_outputs)
    restored = _successor(source, 308)
    proof = _proof(
        restored,
        split_outputs,
        CanonicalOutcome.REL_CORRECTION_REVERSAL_OF,
    )
    reversal = HypothesisLineageReceipt.reversal(
        expected_generation=1,
        target=split,
        outputs=(restored,),
        relationship_proofs=(proof,),
    )
    assert len(reversal.relationships) == 1
    assert len(reversal.relationships[0].evidence) == 2
    assert (
        verify_hypothesis_lineage_receipt(
            reversal,
            versions=(*split_outputs, restored),
            relationship_proofs=(proof,),
            reversal_target=split,
        )
        == reversal
    )
    result = _replay((split, reversal), initial_heads=_heads(source))
    assert result.active_heads == (HypothesisLineageHead.from_version(restored, 2),)


def test_reversal_rejects_wrong_target_stale_target_and_wrong_restoration() -> None:
    left, right, merged = _version(400), _version(401), _version(402)
    target = _consolidation((left, right), merged)
    restored = (_successor(left, 403), _successor(right, 404))
    reversal = HypothesisLineageReceipt.reversal(
        expected_generation=1,
        target=target,
        outputs=restored,
        relationship_proofs=tuple(
            _proof(item, (merged,), CanonicalOutcome.REL_CORRECTION_REVERSAL_OF)
            for item in restored
        ),
    )
    with pytest.raises(HypothesisLineageContractError, match="target"):
        _replay((reversal,), initial_heads=_heads(merged))

    later_left, later_right = _version(405), _version(406)
    advance = _split(merged, (later_left, later_right), generation=1)
    with pytest.raises(HypothesisLineageContractError, match="active head|consumed"):
        _replay((target, advance, reversal), initial_heads=_heads(left, right))

    wrong = _version(407)
    wrong_reversal = HypothesisLineageReceipt.reversal(
        expected_generation=1,
        target=target,
        outputs=(wrong,),
        relationship_proofs=(
            _proof(wrong, (merged,), CanonicalOutcome.REL_CORRECTION_REVERSAL_OF),
        ),
    )
    with pytest.raises(HypothesisLineageContractError, match="restore"):
        _replay((target, wrong_reversal), initial_heads=_heads(left, right))


def test_seen_output_consumed_reuse_and_self_edge_fail_closed() -> None:
    left, right, merged = _version(500), _version(501), _version(502)
    first = _consolidation((left, right), merged)
    reuse = _split(left, (_version(503), _version(504)), generation=1)
    with pytest.raises(HypothesisLineageContractError, match="consumed"):
        _replay((first, reuse), initial_heads=_heads(left, right))

    source, output = _version(505), _version(506)
    seen = _split(source, (output, left))
    with pytest.raises(HypothesisLineageContractError, match="seen|already active"):
        _replay((seen,), initial_heads=_heads(source, left))

    node = HypothesisLineageNodeBinding.from_version(left)
    relation = first.relationships[0]
    with pytest.raises(HypothesisLineageContractError, match="self edge"):
        HypothesisLineageReceipt._build(
            HypothesisLineageKind.CONSOLIDATION,
            0,
            tuple(
                sorted(
                    (node, HypothesisLineageNodeBinding.from_version(right)),
                    key=lambda item: (
                        item.hypothesis_id,
                        item.version_id,
                        item.version_digest,
                    ),
                )
            ),
            (node,),
            (relation,),
        )


@pytest.mark.parametrize(
    "raw",
    [
        b"[]",
        b"true",
        b"1.0",
        b'{"x":9007199254740992}',
        b'{"schema_version":"x","schema_version":"x"}',
        b'{ "schema_version":"x"}',
        b'{"schema_version":"\\ud800"}',
        b'{"schema_version":"x","unknown":1}',
    ],
)
def test_parser_rejects_noncanonical_or_unsafe_json(raw: bytes) -> None:
    with pytest.raises(HypothesisLineageContractError):
        HypothesisLineageReceipt.from_canonical_bytes(raw)


def test_parser_unknown_nested_fields_and_derived_identity_tamper_fail_closed() -> None:
    receipt = _consolidation((_version(600), _version(601)), _version(602))
    value = json.loads(receipt.canonical_bytes)
    value["inputs"][0]["unknown"] = True
    with pytest.raises(HypothesisLineageContractError):
        HypothesisLineageReceipt.from_canonical_bytes(canonical_json_bytes(value))
    value = json.loads(receipt.canonical_bytes)
    value["lineage_id"] = str(uuid.uuid4())
    with pytest.raises(HypothesisLineageContractError, match="semantic identity"):
        HypothesisLineageReceipt.from_canonical_bytes(canonical_json_bytes(value))


def test_producer_type_impostor_uninitialised_cycle_oversize_and_depth_are_total() -> (
    None
):
    from newsroom.increment6 import lineage as module

    class VersionImpostor(EventHypothesisVersion):
        pass

    class TupleImpostor(tuple):
        pass

    with pytest.raises(HypothesisLineageContractError):
        HypothesisLineageNodeBinding.from_version(object.__new__(VersionImpostor))
    with pytest.raises(HypothesisLineageContractError):
        replay_hypothesis_lineage(
            TupleImpostor(),  # type: ignore[arg-type]
            initial_heads=(),
            versions=(),
            relationship_proofs=(),
        )
    uninitialised = object.__new__(HypothesisLineageReceipt)
    with pytest.raises(HypothesisLineageContractError):
        _ = uninitialised.canonical_bytes
    receipt = _consolidation((_version(700), _version(701)), _version(702))
    cyclic: list[object] = []
    cyclic.append(cyclic)
    object.__setattr__(receipt, "inputs", cyclic)
    with pytest.raises(HypothesisLineageContractError):
        _ = receipt.canonical_bytes
    with pytest.raises(HypothesisLineageContractError):
        HypothesisLineageReceipt.from_canonical_bytes(
            b"{" + b" " * module.MAX_LINEAGE_CANONICAL_BYTES + b"}"
        )
    deep: object = None
    for _ in range(20):
        deep = [deep]
    with pytest.raises(HypothesisLineageContractError):
        HypothesisLineageReceipt.from_canonical_bytes(
            json.dumps({"x": deep}, separators=(",", ":")).encode()
        )


def test_relationship_binding_requires_exact_complete_public_receipt() -> None:
    left, right = _version(800), _version(801)
    complete, evidence = _decision(left, (right,), CanonicalOutcome.REL_SAME_STATE)
    proof = HypothesisLineageRelationshipProof.from_assessment(complete, evidence)
    binding = proof.binding
    assert binding.assessment_digest == complete.canonical_digest
    assert binding.outcome is complete.decision
    assert binding.subject.version_id == left.version_id
    assert binding.evidence[0].comparator_version_id == right.version_id
    assert binding.evidence[0].classification is CanonicalOutcome.REL_SAME_STATE
    third = _version(802)
    receipt = _consolidation((right, third), left)
    receipt_proof = _PROOFS[receipt.relationships[0].assessment_digest]
    assert (
        verify_hypothesis_lineage_receipt(
            receipt,
            versions=(right, third, left),
            relationship_proofs=(receipt_proof,),
            reversal_target=None,
        ).kind
        is HypothesisLineageKind.CONSOLIDATION
    )
    with pytest.raises(HypothesisLineageContractError, match="non-reversal"):
        verify_hypothesis_lineage_receipt(
            receipt,
            versions=(right, third, left),
            relationship_proofs=(receipt_proof,),
            reversal_target=receipt,
        )
    incomplete = RelationshipAssessment(
        AssessmentStatus.INCOMPLETE,
        HypothesisVersionBinding.from_version(left),
        ComparatorSetManifest(
            AssessmentStatus.INCOMPLETE,
            (HypothesisVersionBinding.from_version(right),),
        ),
        None,
        None,
        None,
        None,
        None,
    )
    with pytest.raises(HypothesisLineageContractError, match="complete"):
        HypothesisLineageRelationshipBinding.from_assessment(incomplete, evidence)
    with pytest.raises(HypothesisLineageContractError):
        HypothesisLineageRelationshipBinding.from_assessment(
            object(),
            evidence,  # type: ignore[arg-type]
        )
    with pytest.raises(HypothesisLineageContractError):
        HypothesisLineageRelationshipProof()
    changed = replace(evidence[0], same_state_score=79, related_distinct_score=60)
    with pytest.raises(HypothesisLineageContractError, match="policy replay"):
        HypothesisLineageRelationshipProof.from_assessment(complete, (changed,))


def test_ordinary_exceptions_normalise_and_base_exceptions_survive() -> None:
    from newsroom.increment6 import lineage as module

    for exc in (RuntimeError(), KeyError(), AttributeError()):
        with pytest.raises(HypothesisLineageContractError):
            module._normalise(lambda exc=exc: (_ for _ in ()).throw(exc), "failed")
    for exc_type in (KeyboardInterrupt, SystemExit):
        with pytest.raises(exc_type):
            module._normalise(
                lambda exc_type=exc_type: (_ for _ in ()).throw(exc_type()), "failed"
            )


def test_v22_decision_subjects_are_unique() -> None:
    receipt = _split(_version(900), (_version(901), _version(902)))
    subjects = tuple(item.subject.version_id for item in receipt.relationships)
    assert len(subjects) == len(set(subjects))


def test_replay_rejects_forged_semantic_producers() -> None:
    left, right, output = _version(910), _version(911), _version(912)
    receipt = _consolidation((left, right), output)
    forged_output = replace(receipt.outputs[0], version_digest=D2)
    forged_relationships = tuple(
        replace(item, subject=forged_output) for item in receipt.relationships
    )
    forged = replace(
        receipt, outputs=(forged_output,), relationships=forged_relationships
    )
    with pytest.raises(HypothesisLineageContractError):
        _replay((forged,), initial_heads=_heads(left, right))


def test_structural_forged_output_assessment_evidence_and_endpoint_fail_replay() -> (
    None
):
    left, right, output = _version(913), _version(914), _version(915)
    receipt = _consolidation((left, right), output)
    proof = _PROOFS[receipt.relationships[0].assessment_digest]
    base = json.loads(receipt.canonical_bytes)

    forged_values: list[dict[str, object]] = []
    forged_output = json.loads(receipt.canonical_bytes)
    forged_output["outputs"][0]["version_digest"] = D2
    forged_output["relationships"][0]["subject"]["version_digest"] = D2
    forged_values.append(forged_output)

    forged_assessment = json.loads(receipt.canonical_bytes)
    forged_assessment["relationships"][0]["assessment_digest"] = D2
    forged_values.append(forged_assessment)

    forged_evidence = json.loads(receipt.canonical_bytes)
    forged_evidence["relationships"][0]["evidence"][0]["evidence_digest"] = D2
    forged_values.append(forged_evidence)

    forged_endpoints = base
    evidence = forged_endpoints["relationships"][0]["evidence"]
    evidence[0]["comparator_version_id"], evidence[1]["comparator_version_id"] = (
        evidence[1]["comparator_version_id"],
        evidence[0]["comparator_version_id"],
    )
    evidence.sort(key=lambda item: item["comparator_version_id"])
    forged_values.append(forged_endpoints)

    for value in forged_values:
        parsed = HypothesisLineageReceipt.from_canonical_bytes(
            canonical_json_bytes(value)
        )
        with pytest.raises(HypothesisLineageContractError):
            replay_hypothesis_lineage(
                (parsed,),
                initial_heads=_heads(left, right),
                versions=(left, right, output),
                relationship_proofs=(proof,),
            )


def test_active_hypotheses_are_unique() -> None:
    version = _version(920)
    successor = _successor(version, 921)
    with pytest.raises(HypothesisLineageContractError):
        _replay((), initial_heads=_heads(version, successor))


def test_partial_continuation_is_rejected() -> None:
    with pytest.raises(HypothesisLineageContractError):
        _replay(
            (), initial_heads=(HypothesisLineageHead.from_version(_version(930), 1),)
        )


def test_uninitialised_assessment_proof_and_target_are_total() -> None:
    assessment, evidence = _decision(
        _version(940), (_version(942),), CanonicalOutcome.REL_SAME_STATE
    )
    assert assessment.status is AssessmentStatus.COMPLETE
    with pytest.raises(HypothesisLineageContractError):
        HypothesisLineageRelationshipBinding.from_assessment(
            object.__new__(RelationshipAssessment), evidence
        )
    with pytest.raises(HypothesisLineageContractError):
        _ = object.__new__(HypothesisLineageRelationshipProof).binding
    with pytest.raises(HypothesisLineageContractError):
        HypothesisLineageReceipt.reversal(
            expected_generation=1,
            target=object.__new__(HypothesisLineageReceipt),
            outputs=(_version(941),),
            relationship_proofs=(),
        )


def test_final_review_red_cross_binds_same_id_different_digest_comparators() -> None:
    left, right, merged = _version(950), _version(951), _version(952)
    changed_right = replace(right, proposed_summary="Changed comparator 951")
    consolidation_proof = _proof(
        merged, (left, changed_right), CanonicalOutcome.REL_SAME_STATE
    )
    consolidation = HypothesisLineageReceipt.consolidation(
        expected_generation=0,
        inputs=(left, right),
        output=merged,
        relationship_proofs=(consolidation_proof,),
    )
    with pytest.raises(HypothesisLineageContractError):
        verify_hypothesis_lineage_receipt(
            consolidation,
            versions=(left, right, merged),
            relationship_proofs=(consolidation_proof,),
            reversal_target=None,
        )

    restored = (_successor(left, 953), _successor(right, 954))
    changed_merged = replace(merged, proposed_summary="Changed comparator 952")
    reversal_proofs = tuple(
        _proof(
            output,
            (changed_merged,),
            CanonicalOutcome.REL_CORRECTION_REVERSAL_OF,
        )
        for output in restored
    )
    reversal = HypothesisLineageReceipt.reversal(
        expected_generation=1,
        target=consolidation,
        outputs=restored,
        relationship_proofs=reversal_proofs,
    )
    with pytest.raises(HypothesisLineageContractError):
        verify_hypothesis_lineage_receipt(
            reversal,
            versions=(merged, *restored),
            relationship_proofs=reversal_proofs,
            reversal_target=consolidation,
        )


def test_final_review_red_standalone_verifier_rejects_changed_reversal_target() -> None:
    left, right, merged = _version(960), _version(961), _version(962)
    target = _consolidation((left, right), merged)
    restored = (_successor(left, 963), _successor(right, 964))
    proofs = tuple(
        _proof(output, (merged,), CanonicalOutcome.REL_CORRECTION_REVERSAL_OF)
        for output in restored
    )
    reversal = HypothesisLineageReceipt.reversal(
        expected_generation=1,
        target=target,
        outputs=restored,
        relationship_proofs=proofs,
    )
    changed_target = HypothesisLineageTarget(target.lineage_id, D1)
    forged = HypothesisLineageReceipt._build(
        HypothesisLineageKind.REVERSAL,
        reversal.expected_generation,
        reversal.inputs,
        reversal.outputs,
        reversal.relationships,
        changed_target,
    )
    assert forged.lineage_id != reversal.lineage_id
    with pytest.raises(HypothesisLineageContractError):
        verify_hypothesis_lineage_receipt(
            forged,
            versions=(merged, *restored),
            relationship_proofs=proofs,
            reversal_target=target,
        )


def test_final_parity_red_standalone_rejects_wrong_restoration_identities() -> None:
    left, right, merged = _version(970), _version(971), _version(972)
    target = _consolidation((left, right), merged)
    wrong = _version(973)
    proof = _proof(wrong, (merged,), CanonicalOutcome.REL_CORRECTION_REVERSAL_OF)
    reversal = HypothesisLineageReceipt.reversal(
        expected_generation=1,
        target=target,
        outputs=(wrong,),
        relationship_proofs=(proof,),
    )
    with pytest.raises(HypothesisLineageContractError, match="restore"):
        verify_hypothesis_lineage_receipt(
            reversal,
            versions=(merged, wrong),
            relationship_proofs=(proof,),
            reversal_target=target,
        )
