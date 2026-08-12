from __future__ import annotations

import json
import uuid
from dataclasses import replace

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.policy import (
    CommandRegistry,
    PayloadSchemaContract,
    PayloadSchemaRegistry,
)
from newsroom.authority.types import EventId, PayloadMode
from newsroom.discovery.record_models import DiscoverySignal, GateDecision, NewsLead
from newsroom.discovery.types import (
    DecisionTerminality,
    GateOutcome,
    NextAction,
    NextActionKind,
    TimeValidity,
)
from newsroom.increment6 import candidates as candidates_module
from newsroom.increment6.candidates import (
    CANDIDATE_ADMISSION,
    CANDIDATE_CURRENT_VERSION,
    STORY_CANDIDATE,
    STORY_CANDIDATE_VERSION,
    CandidateAdmission,
    CandidateAdmissionOutcome,
    CandidateAdmissionReason,
    CandidateAdmissionRequest,
    CandidateContractError,
    CandidateGoverningManifest,
    CandidateGoverningState,
    CandidateGoverningStateBinding,
    CandidateGoverningStateStatus,
    CandidateLeadSignalBinding,
    StoryCandidate,
    StoryCandidateVersion,
    build_candidate_distinct_scope_proof,
    build_candidate_governing_manifest,
    evaluate_candidate_admission,
    merge_candidate_authority_registries,
    validate_candidate_first_version,
    validate_candidate_version_successor,
)
from newsroom.increment6.collision import (
    CandidateUseCollisionBinding,
    CandidateUseOperation,
    CollisionEligibilityOutcome,
    CollisionEligibilityReason,
    CollisionState,
    CurrentCollisionEligibilityRequest,
)
from newsroom.increment6.hypotheses import (
    EventHypothesis,
    EventHypothesisVersion,
    HypothesisSourceBinding,
)
from newsroom.increment6.lineage import (
    HypothesisLineageHead,
    HypothesisLineageReceipt,
)
from newsroom.increment6.outcomes import CanonicalOutcome
from newsroom.increment6.proposals import CandidateManifestKind
from newsroom.increment6.relationships import (
    AssessmentStatus,
    RetainedRelationshipDecisionReceipt,
    relationship_command_definition,
    relationship_payload_contract,
)
from newsroom.tests.discovery_3d_authority_helpers import exact_admission_request
from newsroom.tests.discovery_3d_helpers import reason
from newsroom.tests.test_increment6a2_work_items import _id
from newsroom.tests.test_increment6c2_dispositions import _persisted_disposition_store
from newsroom.tests.test_increment6d3_lineage import (
    _consolidation,
    _heads,
    _proof,
    _replay,
    _split,
    _successor,
    _version,
)
from newsroom.tests.test_increment6d3_lineage import (
    _decision as _relationship_decision,
)
from newsroom.tests.test_increment6e1_collision import _decide, _occupied_evidence

D = "sha256:" + "1" * 64
HYPOTHESIS_ID = "11111111-1111-4111-8111-111111111111"
VERSION_ID = "22222222-2222-4222-8222-222222222222"


def test_candidate_registry_merge_preserves_upstream_current_versions() -> None:
    definition = relationship_command_definition()
    contract = relationship_payload_contract()
    newer_definition = replace(definition, definition_version="relationship-command-v9")
    newer_contract = replace(contract, contract_version="relationship-contract-v9")
    other_mode = PayloadSchemaContract(
        contract.schema_version,
        PayloadMode.NO_PAYLOAD,
        "other-mode-v1",
        "other-mode-canonicalizer-v1",
        lambda _: b"",
        (replace(contract.golden_vectors[0], name="other-mode", expected_bytes=b""),),
    )
    commands = CommandRegistry(
        (definition, newer_definition),
        current_versions={definition.command_type: definition.definition_version},
    )
    schemas = PayloadSchemaRegistry(
        (contract, newer_contract, other_mode),
        current_versions={
            (contract.schema_version, contract.payload_mode): contract.contract_version,
            (
                other_mode.schema_version,
                other_mode.payload_mode,
            ): other_mode.contract_version,
        },
    )

    merged_commands, merged_schemas = merge_candidate_authority_registries(
        commands, schemas
    )

    assert merged_commands.resolve(definition.command_type) == definition
    assert (
        merged_schemas.resolve(contract.schema_version, contract.payload_mode)
        == contract
    )
    assert (
        merged_schemas.resolve(other_mode.schema_version, other_mode.payload_mode)
        == other_mode
    )


def _manifest(collision, *, incomplete: bool = False) -> CandidateGoverningManifest:
    binding = collision.request.binding
    scope = digest_bytes(
        canonical_json_bytes(
            {
                "collision_namespace": binding.collision_namespace,
                "collision_key_digest": binding.collision_key_digest,
                "hypothesis_id": HYPOTHESIS_ID,
            }
        )
    )
    return CandidateGoverningManifest(
        semantic_scope_digest=scope,
        candidate_kind=CandidateManifestKind.NEW_EVENT,
        hypothesis_id=HYPOTHESIS_ID,
        hypothesis_version_id=VERSION_ID,
        hypothesis_version_digest=D,
        proposed_summary="Unverified discovery hypothesis",
        hypothesis_status="UNVERIFIED_DISCOVERY_HYPOTHESIS",
        relationship_status=AssessmentStatus.COMPLETE,
        relationship_outcome=CanonicalOutcome.REL_NO_ADEQUATE_PRIOR_MATCH,
        relationship_assessment_digest=D,
        relationship_comparator_hypothesis_id=None,
        relationship_comparator_version_id=None,
        relationship_comparator_version_digest=None,
        lineage_generation=2,
        lineage_history_digests=(D,),
        disposition_digests=(D,),
        candidate_manifest_digests=(D,),
        lead_signal_bindings=(
            CandidateLeadSignalBinding(
                "33333333-3333-4333-8333-333333333333",
                D,
                "44444444-4444-4444-8444-444444444444",
                D,
                "99999999-9999-4999-8999-999999999999",
                1,
                "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                1,
                '{"obligation_id":"news","responsibility":"PRIMARY"}',
                incomplete,
            ),
        ),
        proposed_geography="GB",
        proposed_category="UK_NEWS",
        urgency="ROUTINE",
        likely_new_information=("Material change",),
        reader_utility_bases=("Reader utility",),
        uncertainties=("Unverified",),
        evidence_objectives=("Confirm",),
        governing_versions=("candidate-policy-v1",),
        missing_context=(),
        retrieval_incompleteness=(),
        lead_incompleteness_warnings=(),
        signal_operational_finding_ids=(),
        collision_request_digest=collision.request.request_digest,
        collision_decision_digest=digest_bytes(collision.canonical_bytes),
        collision_namespace=binding.collision_namespace,
        collision_key_digest=binding.collision_key_digest,
        governing_state_binding=CandidateGoverningStateBinding(*((D,) * 9)),
        incomplete=incomplete,
    )


def _with_relationship(manifest, outcome):
    return replace(
        manifest,
        relationship_outcome=outcome,
        relationship_comparator_hypothesis_id="33333333-3333-4333-8333-333333333333",
        relationship_comparator_version_id="44444444-4444-4444-8444-444444444444",
        relationship_comparator_version_digest=D,
    )


def _eligible_current(tmp_path, candidate_id: str):
    requirement, evidence = _occupied_evidence(tmp_path)
    original = requirement.binding
    binding = CandidateUseCollisionBinding(
        subject_id=HYPOTHESIS_ID,
        subject_version_id=VERSION_ID,
        subject_version_digest=D,
        operation=CandidateUseOperation.USE_CURRENT_CANDIDATE,
        expected_candidate_id=candidate_id,
        collision_namespace=original.collision_namespace,
        collision_key_digest=original.collision_key_digest,
        generation_id=original.generation_id,
        query_valid_time=original.query_valid_time,
        serving_time=original.serving_time,
        authority_watermark=original.authority_watermark,
    )
    request = CurrentCollisionEligibilityRequest(
        binding, requirement.named_request_digest
    )
    original_decision = _decide(request=requirement, evidence=evidence)
    return replace(
        original_decision, request=request, observed_candidate_id=candidate_id
    )


def _request(
    manifest: CandidateGoverningManifest, current: StoryCandidateVersion | None
) -> CandidateAdmissionRequest:
    return CandidateAdmissionRequest(
        request_id="55555555-5555-4555-8555-555555555555",
        actor_identity_digest=D,
        idempotency_key="candidate-request:001",
        expected_current_version_id=None if current is None else current.version_id,
        expected_current_version_digest=None
        if current is None
        else current.canonical_digest,
        expected_current_ordinal=0 if current is None else current.ordinal,
        semantic_scope_digest=manifest.semantic_scope_digest,
        collision_request_digest=manifest.collision_request_digest,
        expected_governing_state_digest=manifest.governing_state_binding.canonical_digest,
        distinct_scope_proof_digest=None,
    )


def _current_state(manifest: CandidateGoverningManifest) -> CandidateGoverningState:
    return CandidateGoverningState(
        CandidateGoverningStateStatus.COMPLETE, manifest.governing_state_binding
    )


def _lineage_args(version: EventHypothesisVersion) -> dict[str, object]:
    return {
        "lineage_receipts": (),
        "lineage_initial_heads": (HypothesisLineageHead.from_version(version),),
        "lineage_versions": (version,),
        "lineage_relationship_proofs": (),
    }


def test_candidate_contract_names_are_exact() -> None:
    assert STORY_CANDIDATE == "newsroom.increment6.story-candidate.v1"
    assert STORY_CANDIDATE_VERSION == "newsroom.increment6.story-candidate-version.v1"
    assert CANDIDATE_ADMISSION == "newsroom.increment6.candidate-admission.v1"
    assert CANDIDATE_CURRENT_VERSION == "EXACT_RETAINED_MAX_ORDINAL_HEAD"
    assert "proposed_summary" in CandidateGoverningManifest.__dataclass_fields__
    assert "hypothesis_status" in CandidateGoverningManifest.__dataclass_fields__


def test_only_committed_admission_can_create_candidate_identity_and_version() -> None:
    candidate = StoryCandidate(
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "66666666-6666-4666-8666-666666666666",
        "77777777-7777-4777-8777-777777777777",
        D,
    )
    assert StoryCandidate.from_canonical_bytes(candidate.canonical_bytes) == candidate
    assert not hasattr(StoryCandidate, "allocate")
    assert not hasattr(StoryCandidate, "from_committed_admission")
    assert candidate.creates_candidate is False

    class Child(StoryCandidate):
        pass

    with pytest.raises(CandidateContractError):
        Child(
            candidate.candidate_id,
            candidate.committed_admission_decision_id,
            candidate.authority_event_id,
            candidate.semantic_scope_digest,
        )


def test_version_replay_deduplicates_and_changed_manifest_is_contiguous(
    tmp_path,
) -> None:
    provisional = StoryCandidate(
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "66666666-6666-4666-8666-666666666666",
        "77777777-7777-4777-8777-777777777777",
        D,
    )
    collision = _eligible_current(tmp_path, provisional.candidate_id)
    manifest = _manifest(collision)
    candidate = replace(
        provisional, semantic_scope_digest=manifest.semantic_scope_digest
    )
    first = StoryCandidateVersion(
        "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        candidate.candidate_id,
        1,
        None,
        None,
        candidate.committed_admission_decision_id,
        manifest,
    )
    assert StoryCandidateVersion.from_canonical_bytes(first.canonical_bytes) == first
    assert validate_candidate_first_version(candidate, first) == first
    changed = replace(manifest, governing_versions=("candidate-policy-v2",))
    with pytest.raises(CandidateContractError, match="equivalent manifest"):
        validate_candidate_version_successor(
            first,
            replace(
                first,
                version_id="dddddddd-dddd-4ddd-8ddd-dddddddddddd",
                ordinal=2,
                previous_version_id=first.version_id,
                previous_version_digest=first.canonical_digest,
                committed_admission_decision_id="88888888-8888-4888-8888-888888888888",
            ),
        )
    second = StoryCandidateVersion(
        "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        candidate.candidate_id,
        2,
        first.version_id,
        first.canonical_digest,
        "88888888-8888-4888-8888-888888888888",
        changed,
    )
    assert validate_candidate_version_successor(first, second) == second
    false_scope = replace(
        changed,
        hypothesis_id="eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
        semantic_scope_digest=digest_bytes(
            canonical_json_bytes(
                {
                    "collision_namespace": changed.collision_namespace,
                    "collision_key_digest": changed.collision_key_digest,
                    "hypothesis_id": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
                }
            )
        ),
    )
    with pytest.raises(CandidateContractError, match="contiguous successor"):
        validate_candidate_version_successor(
            first, replace(second, governing_manifest=false_scope)
        )
    with pytest.raises(CandidateContractError, match="new committed"):
        validate_candidate_version_successor(
            first,
            replace(
                second,
                committed_admission_decision_id=first.committed_admission_decision_id,
            ),
        )
    with pytest.raises(CandidateContractError):
        validate_candidate_version_successor(
            first, replace(second, version_id=first.version_id)
        )
    assert second.ordinal == 2
    assert (second.previous_version_id, second.previous_version_digest) == (
        first.version_id,
        first.canonical_digest,
    )


def test_pure_duplicate_decision_has_no_new_candidate_or_version_identity(
    tmp_path,
) -> None:
    provisional = StoryCandidate(
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "66666666-6666-4666-8666-666666666666",
        "77777777-7777-4777-8777-777777777777",
        D,
    )
    collision = _eligible_current(tmp_path, provisional.candidate_id)
    manifest = _manifest(collision)
    candidate = replace(
        provisional, semantic_scope_digest=manifest.semantic_scope_digest
    )
    current = StoryCandidateVersion(
        "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        candidate.candidate_id,
        1,
        None,
        None,
        candidate.committed_admission_decision_id,
        manifest,
    )
    decision = evaluate_candidate_admission(
        request=_request(manifest, current),
        manifest=manifest,
        collision=collision,
        current_version=current,
        governing_state=_current_state(manifest),
    )
    assert decision.outcome is CandidateAdmissionOutcome.DUPLICATE_EQUIVALENT
    assert decision.reason is CandidateAdmissionReason.EXACT_MANIFEST_REPLAY
    assert CandidateAdmission.from_canonical_bytes(decision.canonical_bytes) == decision
    assert decision.authority == decision.candidate_effect == "NONE"
    assert decision.candidate_effect_performed is decision.creates_candidate is False
    document = json.loads(decision.canonical_bytes)
    assert document["current_candidate_id"] == current.candidate_id
    assert "candidate_version_id" not in document
    assert "committed_admission_decision_id" not in document


def test_admissible_new_intent_contains_no_candidate_or_version_identity(
    tmp_path,
) -> None:
    candidate_id = StoryCandidate(
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "66666666-6666-4666-8666-666666666666",
        "77777777-7777-4777-8777-777777777777",
        D,
    ).candidate_id
    current = _eligible_current(tmp_path, candidate_id)
    old = current.request.binding
    binding = replace(
        old,
        operation=CandidateUseOperation.ADMIT_NEW_CANDIDATE,
        expected_candidate_id=None,
    )
    collision = replace(
        current,
        request=CurrentCollisionEligibilityRequest(
            binding, current.request.named_request_digest
        ),
        reason=CollisionEligibilityReason.CURRENT_SLOT_UNOCCUPIED,
        collision_state=CollisionState.UNOCCUPIED,
        observed_candidate_id=None,
    )
    manifest = _manifest(collision)
    decision = evaluate_candidate_admission(
        request=_request(manifest, None),
        manifest=manifest,
        collision=collision,
        current_version=None,
        governing_state=_current_state(manifest),
    )
    assert decision.outcome is CandidateAdmissionOutcome.ADMISSIBLE
    assert decision.current_candidate_id is None
    assert decision.current_candidate_version_id is None
    assert decision.current_candidate_version_digest is None
    document = json.loads(decision.canonical_bytes)
    assert "committed_admission_decision_id" not in document
    assert "candidate_version_id" not in document


def test_incomplete_and_stale_are_typed_while_mismatched_binding_fails_closed(
    tmp_path,
) -> None:
    provisional = StoryCandidate(
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "66666666-6666-4666-8666-666666666666",
        "77777777-7777-4777-8777-777777777777",
        D,
    )
    collision = _eligible_current(tmp_path, provisional.candidate_id)
    manifest = _manifest(collision, incomplete=True)
    candidate = replace(
        provisional, semantic_scope_digest=manifest.semantic_scope_digest
    )
    current = StoryCandidateVersion(
        "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        candidate.candidate_id,
        1,
        None,
        None,
        candidate.committed_admission_decision_id,
        manifest,
    )
    decision = evaluate_candidate_admission(
        request=_request(manifest, current),
        manifest=manifest,
        collision=collision,
        current_version=current,
        governing_state=_current_state(manifest),
    )
    assert decision.outcome is CandidateAdmissionOutcome.INCOMPLETE
    stale = replace(_request(manifest, current), expected_current_ordinal=2)
    stale_decision = evaluate_candidate_admission(
        request=stale,
        manifest=manifest,
        collision=collision,
        current_version=current,
        governing_state=_current_state(manifest),
    )
    assert stale_decision.outcome is CandidateAdmissionOutcome.STALE
    with pytest.raises(CandidateContractError):
        evaluate_candidate_admission(
            request=replace(_request(manifest, current), collision_request_digest=D),
            manifest=manifest,
            collision=collision,
            current_version=current,
            governing_state=_current_state(manifest),
        )
    with pytest.raises(CandidateContractError, match="incompleteness differs"):
        replace(manifest, incomplete=False)


def test_missing_expected_current_is_typed_stale_and_scope_retarget_is_distinct(
    tmp_path,
) -> None:
    candidate = StoryCandidate(
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "66666666-6666-4666-8666-666666666666",
        "77777777-7777-4777-8777-777777777777",
        D,
    )
    collision = _eligible_current(tmp_path, candidate.candidate_id)
    proposed = _manifest(collision)
    expected = CandidateAdmissionRequest(
        "55555555-5555-4555-8555-555555555555",
        D,
        "candidate-request:missing",
        "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        D,
        1,
        proposed.semantic_scope_digest,
        proposed.collision_request_digest,
        proposed.governing_state_binding.canonical_digest,
        None,
    )
    stale = evaluate_candidate_admission(
        request=expected,
        manifest=proposed,
        collision=collision,
        current_version=None,
        governing_state=_current_state(proposed),
    )
    assert stale.outcome is CandidateAdmissionOutcome.STALE
    assert stale.current_candidate_id is None

    other_scope = digest_bytes(
        canonical_json_bytes(
            {
                "collision_namespace": proposed.collision_namespace,
                "collision_key_digest": proposed.collision_key_digest,
                "hypothesis_id": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
            }
        )
    )
    current_manifest = replace(
        proposed,
        hypothesis_id="eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
        semantic_scope_digest=other_scope,
    )
    current = StoryCandidateVersion(
        "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        candidate.candidate_id,
        1,
        None,
        None,
        candidate.committed_admission_decision_id,
        current_manifest,
    )
    distinct = evaluate_candidate_admission(
        request=_request(proposed, current),
        manifest=proposed,
        collision=collision,
        current_version=current,
        governing_state=_current_state(proposed),
    )
    assert distinct.outcome is CandidateAdmissionOutcome.BLOCKED


def test_distinct_and_blocked_collision_results_remain_typed(tmp_path) -> None:
    candidate = StoryCandidate(
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "66666666-6666-4666-8666-666666666666",
        "77777777-7777-4777-8777-777777777777",
        D,
    )
    eligible = _eligible_current(tmp_path, candidate.candidate_id)
    distinct_collision = replace(
        eligible,
        outcome=CollisionEligibilityOutcome.COLLISION_CONFLICT,
        reason=CollisionEligibilityReason.CURRENT_CANDIDATE_DIFFERS,
    )
    distinct_manifest = _manifest(distinct_collision)
    distinct = evaluate_candidate_admission(
        request=_request(distinct_manifest, None),
        manifest=distinct_manifest,
        collision=distinct_collision,
        current_version=None,
        governing_state=_current_state(distinct_manifest),
    )
    assert distinct.outcome is CandidateAdmissionOutcome.BLOCKED
    related_manifest = _with_relationship(
        distinct_manifest, CanonicalOutcome.REL_RELATED_DISTINCT
    )
    related_binding = replace(
        distinct_collision.request.binding,
        operation=CandidateUseOperation.ADMIT_NEW_CANDIDATE,
        expected_candidate_id=None,
    )
    related_collision = replace(
        distinct_collision,
        request=CurrentCollisionEligibilityRequest(
            related_binding, distinct_collision.request.named_request_digest
        ),
        outcome=CollisionEligibilityOutcome.ELIGIBLE,
        reason=CollisionEligibilityReason.CURRENT_SLOT_UNOCCUPIED,
        collision_state=CollisionState.UNOCCUPIED,
        observed_candidate_id=None,
    )
    related_manifest = replace(
        related_manifest,
        collision_request_digest=related_collision.request.request_digest,
        collision_decision_digest=digest_bytes(related_collision.canonical_bytes),
    )
    related = evaluate_candidate_admission(
        request=replace(
            _request(related_manifest, None),
            collision_request_digest=related_manifest.collision_request_digest,
        ),
        manifest=related_manifest,
        collision=related_collision,
        current_version=None,
        governing_state=_current_state(related_manifest),
    )
    assert related.outcome is CandidateAdmissionOutcome.BLOCKED
    with pytest.raises(CandidateContractError, match="distinct"):
        CandidateAdmission(
            _request(related_manifest, None),
            related_manifest,
            CandidateAdmissionOutcome.DISTINCT,
            CandidateAdmissionReason.RELATED_DISTINCT_PRE_EFFECT,
            candidate.candidate_id,
            "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            D,
        )

    blocked_collision = replace(
        eligible,
        outcome=CollisionEligibilityOutcome.POLICY_BLOCKED,
        reason=CollisionEligibilityReason.AUTHORITY_POLICY_BLOCKED,
    )
    blocked_manifest = _manifest(blocked_collision)
    blocked = evaluate_candidate_admission(
        request=_request(blocked_manifest, None),
        manifest=blocked_manifest,
        collision=blocked_collision,
        current_version=None,
        governing_state=_current_state(blocked_manifest),
    )
    assert blocked.outcome is CandidateAdmissionOutcome.BLOCKED


@pytest.mark.parametrize(
    (
        "collision_outcome",
        "collision_reason",
        "expected_outcome",
        "expected_admission_reason",
    ),
    [
        (
            CollisionEligibilityOutcome.UNAVAILABLE,
            CollisionEligibilityReason.AUTHORITY_UNAVAILABLE,
            CandidateAdmissionOutcome.INCOMPLETE,
            CandidateAdmissionReason.COLLISION_AUTHORITY_UNAVAILABLE,
        ),
        (
            CollisionEligibilityOutcome.BINDING_MISMATCH,
            CollisionEligibilityReason.NAMED_REQUEST_BINDING_DIFFERS,
            CandidateAdmissionOutcome.BLOCKED,
            CandidateAdmissionReason.COLLISION_AUTHORITY_BLOCKED,
        ),
    ],
)
def test_unavailable_and_binding_mismatch_keep_typed_fail_closed_meaning(
    tmp_path,
    collision_outcome,
    collision_reason,
    expected_outcome,
    expected_admission_reason,
) -> None:
    collision = replace(
        _eligible_current(tmp_path, "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        outcome=collision_outcome,
        reason=collision_reason,
    )
    manifest = _manifest(collision)
    decision = evaluate_candidate_admission(
        request=_request(manifest, None),
        manifest=manifest,
        collision=collision,
        current_version=None,
        governing_state=_current_state(manifest),
    )
    assert decision.outcome is expected_outcome
    assert decision.reason is expected_admission_reason


@pytest.mark.parametrize(
    "outcome",
    [CanonicalOutcome.REL_SAME_STATE, CanonicalOutcome.REL_UNCERTAIN],
)
def test_same_state_and_uncertain_are_typed_blocked(tmp_path, outcome) -> None:
    collision = _eligible_current(tmp_path, "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    manifest = _with_relationship(_manifest(collision), outcome)
    decision = evaluate_candidate_admission(
        request=_request(manifest, None),
        manifest=manifest,
        collision=collision,
        current_version=None,
        governing_state=_current_state(manifest),
    )
    assert decision.outcome is CandidateAdmissionOutcome.BLOCKED


def test_lineage_history_order_is_preserved_not_sorted(tmp_path) -> None:
    manifest = _manifest(
        _eligible_current(tmp_path, "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    )
    ordered = replace(
        manifest,
        lineage_history_digests=("sha256:" + "2" * 64, "sha256:" + "1" * 64),
    )
    assert (
        CandidateGoverningManifest.from_value(
            ordered.canonical_value()
        ).lineage_history_digests
        == ordered.lineage_history_digests
    )


def test_semantic_scope_separates_split_subjects_and_preserves_restored_subject(
    tmp_path,
) -> None:
    collision = _eligible_current(tmp_path, "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    original = _manifest(collision)
    split_hypothesis = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
    split_scope = digest_bytes(
        canonical_json_bytes(
            {
                "collision_namespace": original.collision_namespace,
                "collision_key_digest": original.collision_key_digest,
                "hypothesis_id": split_hypothesis,
            }
        )
    )
    split = replace(
        original, hypothesis_id=split_hypothesis, semantic_scope_digest=split_scope
    )
    assert split.semantic_scope_digest != original.semantic_scope_digest
    restored = replace(original, lineage_generation=original.lineage_generation + 2)
    assert restored.semantic_scope_digest == original.semantic_scope_digest


def test_real_producers_build_exact_governing_manifest(tmp_path) -> None:
    _, _, _, _, _, _, disposition = _persisted_disposition_store(
        tmp_path, name="candidate-producer-integration"
    )
    base = exact_admission_request()
    lead_request = replace(
        base.lead,
        lead_id=type(base.lead.lead_id).parse(disposition.lead_head.decision_lead_id),
        promoting_gate_decision_id=type(base.lead.promoting_gate_decision_id).parse(
            _id(101)
        ),
        definition_id=type(base.lead.definition_id).parse(_id(201)),
        definition_version_id=type(base.lead.definition_version_id).parse(_id(301)),
    )
    assert lead_request.digest == disposition.lead_head.decision_lead_digest
    signal_request = replace(
        base.signal,
        signal_id=lead_request.signal_id,
        definition_id=lead_request.definition_id,
        definition_version_id=lead_request.definition_version_id,
        item_id=lead_request.item_id,
        revision_id=lead_request.revision_id,
        representation_id=lead_request.representation_id,
        occurrence_id=lead_request.occurrence_id,
        transition_id=lead_request.transition_id,
    )
    lead = NewsLead(
        lead_request, EventId.new(), 1, lead_request.created_at, lead_request.digest
    )
    signal = DiscoverySignal(
        signal_request,
        EventId.new(),
        1,
        signal_request.admitted_at,
        signal_request.digest,
    )
    gate_request = replace(
        base.gate,
        decision_id=lead_request.promoting_gate_decision_id,
        signal_id=lead_request.signal_id,
        evaluated_definition_version_id=lead_request.definition_version_id,
        coverage=lead_request.coverage,
    )
    gate = GateDecision(
        gate_request, EventId.new(), 1, gate_request.decided_at, gate_request.digest
    )
    proposed = disposition.route_binding.hypothesis
    assert proposed is not None
    hypothesis = EventHypothesis.allocate(
        disposition.proposal_id, proposed.proposal_local_id
    )
    source = HypothesisSourceBinding(
        disposition.disposition_id,
        digest_bytes(disposition.canonical_bytes),
        disposition.finding_set_digest,
        disposition.route_binding_digest,
        disposition.lead_head.decision_lead_id,
        disposition.lead_head.decision_lead_digest,
        disposition.lead_head.current_disposition_head_id,
        disposition.lead_head.current_disposition_head_digest,
    )
    version = EventHypothesisVersion(
        str(uuid.uuid5(uuid.UUID(hypothesis.hypothesis_id), "version:1")),
        hypothesis.hypothesis_id,
        1,
        None,
        None,
        proposed.summary,
        proposed.relationship_kind,
        proposed.target_hypothesis_id,
        None,
        None,
        disposition.proposal_id,
        disposition.proposal_content_identity,
        disposition.proposal_canonical_digest,
        proposed.proposal_local_id,
        disposition.work_item_id,
        disposition.work_item_version_id,
        disposition.work_item_version_digest,
        disposition.retrieval_context_id,
        disposition.retrieval_context_digest,
        (source,),
        disposition.validator_input.authenticated_context_identity,
        str(EventId.new()),
        "2042-01-01T00:00:00.000000Z",
    )
    collision_path = tmp_path / "collision"
    collision_path.mkdir()
    occupied = _eligible_current(collision_path, "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    binding = replace(
        occupied.request.binding,
        subject_id=version.hypothesis_id,
        subject_version_id=version.version_id,
        subject_version_digest=version.canonical_digest,
        operation=CandidateUseOperation.ADMIT_NEW_CANDIDATE,
        expected_candidate_id=None,
    )
    collision = replace(
        occupied,
        request=CurrentCollisionEligibilityRequest(
            binding, occupied.request.named_request_digest
        ),
        reason=CollisionEligibilityReason.CURRENT_SLOT_UNOCCUPIED,
        collision_state=CollisionState.UNOCCUPIED,
        observed_candidate_id=None,
    )
    assessment, evidence = _relationship_decision(
        version, (), CanonicalOutcome.REL_NO_ADEQUATE_PRIOR_MATCH
    )
    relationship = RetainedRelationshipDecisionReceipt(assessment, evidence)
    manifest = build_candidate_governing_manifest(
        hypothesis_version=version,
        **_lineage_args(version),
        dispositions=(disposition,),
        leads=(lead,),
        signals=(signal,),
        gates=(gate,),
        relationship=relationship,
        collision=collision,
    )
    assert manifest.candidate_kind is CandidateManifestKind.NEW_EVENT
    assert manifest.lead_signal_bindings[0].coverage_basis
    assert manifest.lineage_history_digests == ()
    assert manifest.missing_context == disposition.route_binding.missing_context
    assert (
        manifest.retrieval_incompleteness
        == disposition.route_binding.retrieval_incompleteness
    )
    assert manifest.lead_incompleteness_warnings == lead.request.incompleteness_warnings
    assert manifest.signal_operational_finding_ids == tuple(
        str(value) for value in signal.request.operational_finding_ids
    )
    comparator_hypothesis = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
    comparator_hypothesis_version = "ffffffff-ffff-4fff-8fff-ffffffffffff"
    comparator_key = "sha256:" + "2" * 64
    comparator_scope = digest_bytes(
        canonical_json_bytes(
            {
                "collision_namespace": binding.collision_namespace,
                "collision_key_digest": comparator_key,
                "hypothesis_id": comparator_hypothesis,
            }
        )
    )
    comparator_candidate_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    comparator_binding = replace(
        binding,
        subject_id=comparator_hypothesis,
        subject_version_id=comparator_hypothesis_version,
        subject_version_digest=D,
        operation=CandidateUseOperation.USE_CURRENT_CANDIDATE,
        expected_candidate_id=comparator_candidate_id,
        collision_key_digest=comparator_key,
    )
    comparator_collision = replace(
        collision,
        request=CurrentCollisionEligibilityRequest(
            comparator_binding, collision.request.named_request_digest
        ),
        reason=CollisionEligibilityReason.CURRENT_CANDIDATE_MATCH,
        collision_state=CollisionState.OCCUPIED,
        observed_candidate_id=comparator_candidate_id,
    )
    comparator_admit_binding = replace(
        comparator_binding,
        operation=CandidateUseOperation.ADMIT_NEW_CANDIDATE,
        expected_candidate_id=None,
    )
    comparator_admission = replace(
        collision,
        request=CurrentCollisionEligibilityRequest(
            comparator_admit_binding, collision.request.named_request_digest
        ),
    )
    comparator_manifest = replace(
        manifest,
        hypothesis_id=comparator_hypothesis,
        hypothesis_version_id=comparator_hypothesis_version,
        hypothesis_version_digest=D,
        collision_request_digest=comparator_admission.request.request_digest,
        collision_decision_digest=digest_bytes(comparator_admission.canonical_bytes),
        collision_key_digest=comparator_key,
        semantic_scope_digest=comparator_scope,
    )
    comparator_version = StoryCandidateVersion(
        "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        comparator_candidate_id,
        1,
        None,
        None,
        "66666666-6666-4666-8666-666666666666",
        comparator_manifest,
    )
    proof = build_candidate_distinct_scope_proof(
        proposed_manifest=manifest,
        proposed_collision=collision,
        comparator_collision=comparator_collision,
        comparator_version=comparator_version,
    )
    assert (
        comparator_version.governing_manifest.collision_request_digest
        == comparator_admission.request.request_digest
        != comparator_collision.request.request_digest
    )
    with pytest.raises(CandidateContractError):
        build_candidate_distinct_scope_proof(
            proposed_manifest=manifest,
            proposed_collision=collision,
            comparator_collision=replace(
                comparator_collision,
                trusted_context=replace(
                    comparator_collision.trusted_context,
                    authority_scope_id="different-trusted-scope",
                ),
            ),
            comparator_version=comparator_version,
        )
    with pytest.raises(CandidateContractError):
        build_candidate_distinct_scope_proof(
            proposed_manifest=manifest,
            proposed_collision=collision,
            comparator_collision=replace(
                comparator_collision,
                request=replace(
                    comparator_collision.request,
                    binding=replace(comparator_binding, collision_key_digest=D),
                ),
            ),
            comparator_version=comparator_version,
        )
    distinct_request = replace(
        _request(manifest, None), distinct_scope_proof_digest=proof.canonical_digest
    )
    distinct = evaluate_candidate_admission(
        request=distinct_request,
        manifest=manifest,
        collision=collision,
        current_version=None,
        governing_state=_current_state(manifest),
        comparator_collision=comparator_collision,
        comparator_version=comparator_version,
    )
    assert distinct.outcome is CandidateAdmissionOutcome.DISTINCT
    assert distinct.distinct_scope_proof == proof
    lineage_args = _lineage_args(version)
    lineage = candidates_module.replay_hypothesis_lineage(
        lineage_args["lineage_receipts"],
        initial_heads=lineage_args["lineage_initial_heads"],
        versions=lineage_args["lineage_versions"],
        relationship_proofs=lineage_args["lineage_relationship_proofs"],
    )
    assert (
        candidates_module._derive_governing_state(
            (gate,),
            (lead,),
            (signal,),
            (disposition,),
            version,
            assessment,
            lineage,
        )
        == manifest.governing_state_binding
    )
    second_gate_request = replace(
        gate.request,
        decision_id=type(gate.request.decision_id).parse(_id(102)),
        idempotency_key="candidate-gate:permutation",
    )
    second_gate = GateDecision(
        second_gate_request,
        EventId.new(),
        1,
        second_gate_request.decided_at,
        second_gate_request.digest,
    )
    derive = candidates_module._derive_governing_state
    args = ((lead,), (signal,), (disposition,), version, assessment, lineage)
    assert derive((gate, second_gate), *args) == derive((second_gate, gate), *args)
    with pytest.raises(CandidateContractError):
        build_candidate_governing_manifest(
            hypothesis_version=version,
            **_lineage_args(version),
            dispositions=(disposition,),
            leads=(lead,),
            signals=(signal,),
            gates=(gate, gate),
            relationship=relationship,
            collision=collision,
        )
    hold_basis = replace(
        gate.request.basis,
        operationally_executable=False,
        policy_current=False,
        time_validity=TimeValidity.CURRENT,
    )
    wrong_outcome = replace(
        gate.request,
        basis=hold_basis,
        outcome=GateOutcome.OPERATIONAL_HOLD,
        terminality=DecisionTerminality.PENDING_CONDITION,
        primary_reason=reason("OPS.REQUIRED_CONTEXT_UNAVAILABLE"),
        next_action=NextAction(
            NextActionKind.WAIT_DEPENDENCY,
            "WAIT_FOR_REQUIRED_CONTEXT",
            dependency="fixture-context-authority",
            instructions="Retain the Signal without creating a Lead.",
        ),
        idempotency_key="candidate-gate:wrong-outcome",
    )
    for wrong_gate_request in (
        wrong_outcome,
        replace(
            gate.request,
            evaluated_definition_version_id=type(
                gate.request.evaluated_definition_version_id
            ).parse(_id(302)),
        ),
    ):
        wrong_gate = GateDecision(
            wrong_gate_request,
            EventId.new(),
            1,
            wrong_gate_request.decided_at,
            wrong_gate_request.digest,
        )
        with pytest.raises(CandidateContractError):
            build_candidate_governing_manifest(
                hypothesis_version=version,
                **_lineage_args(version),
                dispositions=(disposition,),
                leads=(lead,),
                signals=(signal,),
                gates=(wrong_gate,),
                relationship=relationship,
                collision=collision,
            )
    candidate_manifest = disposition.route_binding.candidate_manifest
    assert candidate_manifest is not None
    assert (
        len(
            {
                digest_bytes(canonical_json_bytes(candidate_manifest.canonical_value()))
                for _ in range(2)
            }
        )
        == 1
    )
    with pytest.raises(CandidateContractError, match="one exact disposition"):
        candidates_module._validate_contributing_dispositions(
            {
                disposition.lead_head.decision_lead_id,
                "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            },
            (disposition,),
        )

    tampered_lead_request = replace(
        lead.request, incompleteness_warnings=("Missing corroboration",)
    )
    tampered_lead = NewsLead(
        tampered_lead_request,
        EventId.new(),
        1,
        tampered_lead_request.created_at,
        tampered_lead_request.digest,
    )
    with pytest.raises(CandidateContractError, match="supplied News Lead"):
        build_candidate_governing_manifest(
            hypothesis_version=version,
            **_lineage_args(version),
            dispositions=(disposition,),
            leads=(tampered_lead,),
            signals=(signal,),
            gates=(gate,),
            relationship=relationship,
            collision=collision,
        )

    for field in (
        "finding_set_digest",
        "route_binding_digest",
        "decision_lead_digest",
        "decision_lead_head_digest",
    ):
        tampered_source = replace(source, **{field: "sha256:" + "9" * 64})
        with pytest.raises(CandidateContractError):
            tampered_version = replace(version, source_bindings=(tampered_source,))
            build_candidate_governing_manifest(
                hypothesis_version=tampered_version,
                **_lineage_args(tampered_version),
                dispositions=(disposition,),
                leads=(lead,),
                signals=(signal,),
                gates=(gate,),
                relationship=relationship,
                collision=collision,
            )

    extra_request = replace(
        signal.request, signal_id=type(signal.request.signal_id).new()
    )
    extra_signal = DiscoverySignal(
        extra_request, EventId.new(), 1, extra_request.admitted_at, extra_request.digest
    )
    with pytest.raises(CandidateContractError, match="Signals differ"):
        build_candidate_governing_manifest(
            hypothesis_version=version,
            **_lineage_args(version),
            dispositions=(disposition,),
            leads=(lead,),
            signals=(signal, extra_signal),
            gates=(gate,),
            relationship=relationship,
            collision=collision,
        )
    with pytest.raises(CandidateContractError):
        build_candidate_governing_manifest(
            hypothesis_version=version,
            lineage_receipts=(),
            lineage_initial_heads=(),
            lineage_versions=(version,),
            lineage_relationship_proofs=(),
            dispositions=(disposition,),
            leads=(lead,),
            signals=(signal,),
            gates=(gate,),
            relationship=relationship,
            collision=collision,
        )
    split_source, split_left, split_right = _version(950), _version(951), _version(952)
    split_proofs = tuple(
        _proof(
            output,
            (
                split_source,
                *(item for item in (split_left, split_right) if item != output),
            ),
            CanonicalOutcome.REL_RELATED_DISTINCT,
        )
        for output in (split_left, split_right)
    )
    split_receipt = HypothesisLineageReceipt.split(
        expected_generation=0,
        source=split_source,
        outputs=(split_left, split_right),
        relationship_proofs=split_proofs,
    )
    split_assessment, split_evidence = _relationship_decision(
        split_source, (), CanonicalOutcome.REL_NO_ADEQUATE_PRIOR_MATCH
    )
    with pytest.raises(CandidateContractError, match="current lineage head"):
        build_candidate_governing_manifest(
            hypothesis_version=split_source,
            lineage_receipts=(split_receipt,),
            lineage_initial_heads=(HypothesisLineageHead.from_version(split_source),),
            lineage_versions=(split_source, split_left, split_right),
            lineage_relationship_proofs=split_proofs,
            dispositions=(disposition,),
            leads=(lead,),
            signals=(signal,),
            gates=(gate,),
            relationship=RetainedRelationshipDecisionReceipt(
                split_assessment, split_evidence
            ),
            collision=collision,
        )
    with pytest.raises(CandidateContractError):
        build_candidate_governing_manifest(
            hypothesis_version=version,
            lineage_receipts=(),
            lineage_initial_heads=(HypothesisLineageHead.from_version(version, 1),),
            lineage_versions=(version,),
            lineage_relationship_proofs=(),
            dispositions=(disposition,),
            leads=(lead,),
            signals=(signal,),
            gates=(gate,),
            relationship=relationship,
            collision=collision,
        )


def test_incomplete_d2_is_retained_and_blocks_admission(tmp_path) -> None:
    collision = _eligible_current(tmp_path, "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    manifest = _manifest(collision)
    incomplete = replace(
        manifest,
        relationship_status=AssessmentStatus.INCOMPLETE,
        relationship_outcome=None,
        incomplete=True,
    )
    decision = evaluate_candidate_admission(
        request=_request(incomplete, None),
        manifest=incomplete,
        collision=collision,
        current_version=None,
        governing_state=_current_state(incomplete),
    )
    assert decision.outcome is CandidateAdmissionOutcome.INCOMPLETE


def test_candidate_kind_is_version_state_not_candidate_identity(tmp_path) -> None:
    original = _manifest(
        _eligible_current(tmp_path, "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    )
    correction_scope = digest_bytes(
        canonical_json_bytes(
            {
                "collision_namespace": original.collision_namespace,
                "collision_key_digest": original.collision_key_digest,
                "hypothesis_id": original.hypothesis_id,
            }
        )
    )
    correction = _with_relationship(
        replace(
            original,
            candidate_kind=CandidateManifestKind.CORRECTION,
            semantic_scope_digest=correction_scope,
        ),
        CanonicalOutcome.REL_CORRECTION_REVERSAL_OF,
    )
    assert correction.semantic_scope_digest == original.semantic_scope_digest


def test_actual_d3_split_consolidation_and_reversal_preserve_scope_rules() -> None:
    def scope(hypothesis_id: str, kind: CandidateManifestKind) -> str:
        return digest_bytes(
            canonical_json_bytes(
                {
                    "collision_namespace": "candidate-development",
                    "collision_key_digest": D,
                    "hypothesis_id": hypothesis_id,
                }
            )
        )

    source, left, right = _version(900), _version(901), _version(902)
    split = _split(source, (left, right))
    split_replay = _replay((split,), _heads(source))
    split_ids = [head.node.hypothesis_id for head in split_replay.active_heads]
    assert (
        len({scope(item, CandidateManifestKind.NEW_EVENT) for item in split_ids}) == 2
    )

    merged = _version(903)
    consolidation = _consolidation((left, right), merged)
    consolidated = _replay((consolidation,), _heads(left, right))
    assert len(consolidated.active_heads) == 1
    merged_scope = scope(merged.hypothesis_id, CandidateManifestKind.NEW_EVENT)
    assert merged_scope not in {
        scope(left.hypothesis_id, CandidateManifestKind.NEW_EVENT),
        scope(right.hypothesis_id, CandidateManifestKind.NEW_EVENT),
    }

    restored = (_successor(left, 904), _successor(right, 905))
    reversal = HypothesisLineageReceipt.reversal(
        expected_generation=1,
        target=consolidation,
        outputs=restored,
        relationship_proofs=tuple(
            _proof(output, (merged,), CanonicalOutcome.REL_CORRECTION_REVERSAL_OF)
            for output in restored
        ),
    )
    reversed_replay = _replay((consolidation, reversal), _heads(left, right))
    assert {
        scope(head.node.hypothesis_id, CandidateManifestKind.NEW_EVENT)
        for head in reversed_replay.active_heads
    } == {
        scope(left.hypothesis_id, CandidateManifestKind.NEW_EVENT),
        scope(right.hypothesis_id, CandidateManifestKind.NEW_EVENT),
    }
    assert scope(left.hypothesis_id, CandidateManifestKind.CORRECTION) == scope(
        left.hypothesis_id, CandidateManifestKind.NEW_EVENT
    )


def test_first_version_and_admission_reason_invariants_fail_closed(tmp_path) -> None:
    collision = _eligible_current(tmp_path, "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    manifest = _manifest(collision)
    candidate = StoryCandidate(
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "66666666-6666-4666-8666-666666666666",
        "77777777-7777-4777-8777-777777777777",
        manifest.semantic_scope_digest,
    )
    version = StoryCandidateVersion(
        "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        candidate.candidate_id,
        1,
        None,
        None,
        candidate.committed_admission_decision_id,
        manifest,
    )
    with pytest.raises(CandidateContractError, match="committed Candidate"):
        validate_candidate_first_version(
            replace(
                candidate,
                committed_admission_decision_id="88888888-8888-4888-8888-888888888888",
            ),
            version,
        )
    request = _request(manifest, version)
    with pytest.raises(CandidateContractError, match="outcome and reason"):
        CandidateAdmission(
            request,
            manifest,
            CandidateAdmissionOutcome.DUPLICATE_EQUIVALENT,
            CandidateAdmissionReason.COLLISION_AUTHORITY_BLOCKED,
            version.candidate_id,
            version.version_id,
            version.canonical_digest,
        )
    with pytest.raises(CandidateContractError, match="requires an exact current"):
        CandidateAdmission(
            replace(
                request,
                expected_current_version_id=None,
                expected_current_version_digest=None,
                expected_current_ordinal=0,
            ),
            manifest,
            CandidateAdmissionOutcome.DUPLICATE_EQUIVALENT,
            CandidateAdmissionReason.EXACT_MANIFEST_REPLAY,
            None,
            None,
            None,
        )
    assert request.canonical_digest == digest_bytes(request.canonical_bytes)


@pytest.mark.parametrize(
    "raw",
    [
        b"[]",
        b"true",
        b"1.0",
        b'{"schema_version":"x","schema_version":"x"}',
        b'{ "schema_version":"newsroom.increment6.story-candidate.v1"}',
    ],
)
def test_canonical_parsers_reject_malformed_duplicate_and_noncanonical_json(
    raw: bytes,
) -> None:
    with pytest.raises(CandidateContractError):
        StoryCandidate.from_canonical_bytes(raw)


def test_parser_rejects_unknown_deep_large_bool_int_and_builtin_subclasses() -> None:
    deep = b'{"a":' * 25 + b"null" + b"}" * 25
    large = b"{" + b'"x":"' + b"x" * 1_048_576 + b'"}'
    over_envelope = b"{" + b'"x":"' + b"x" * 16_777_216 + b'"}'
    for raw in (deep, large, over_envelope):
        with pytest.raises(CandidateContractError):
            StoryCandidate.from_canonical_bytes(raw)
    with pytest.raises(CandidateContractError):
        CandidateAdmissionRequest(
            "55555555-5555-4555-8555-555555555555",
            D,
            "request:1",
            None,
            None,
            True,
            D,
            D,
            D,
            None,
        )

    class Raw(bytes):
        pass

    with pytest.raises(CandidateContractError):
        StoryCandidate.from_canonical_bytes(Raw(b"{}"))
    with pytest.raises(CandidateContractError):
        _ = object.__new__(StoryCandidate).canonical_bytes

    binding = CandidateLeadSignalBinding(
        "33333333-3333-4333-8333-333333333333",
        D,
        "44444444-4444-4444-8444-444444444444",
        D,
        "99999999-9999-4999-8999-999999999999",
        1,
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        1,
        '{"obligation_id":"news"}',
        False,
    )
    with pytest.raises(CandidateContractError):
        replace(binding, coverage_basis='{"value":"\ud800"}')


def test_constructed_values_cannot_exceed_the_parser_structural_envelope(
    tmp_path,
) -> None:
    manifest = _manifest(
        _eligible_current(tmp_path, "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    )
    with pytest.raises(CandidateContractError, match="structural bounds"):
        replace(
            manifest,
            uncertainties=tuple(f"uncertainty-{index:05d}" for index in range(40_000)),
        )
    with pytest.raises(CandidateContractError, match="canonical UUID"):
        replace(manifest, signal_operational_finding_ids=("not-a-finding-id",))
    with pytest.raises(CandidateContractError):
        replace(
            manifest,
            lead_signal_bindings=(object.__new__(CandidateLeadSignalBinding),),
        )

    class Status(str):
        pass

    with pytest.raises(CandidateContractError):
        replace(manifest, hypothesis_status=Status(manifest.hypothesis_status))
    with pytest.raises(CandidateContractError):
        CandidateAdmission(
            object.__new__(CandidateAdmissionRequest),
            manifest,
            CandidateAdmissionOutcome.BLOCKED,
            CandidateAdmissionReason.COLLISION_AUTHORITY_BLOCKED,
            None,
            None,
            None,
        )


def test_governing_currentness_statuses_and_exact_binding(tmp_path) -> None:
    collision = _eligible_current(tmp_path, "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    manifest = _manifest(collision)
    request = _request(manifest, None)
    for status, outcome in (
        (
            CandidateGoverningStateStatus.UNAVAILABLE,
            CandidateAdmissionOutcome.INCOMPLETE,
        ),
        (
            CandidateGoverningStateStatus.INCOMPLETE,
            CandidateAdmissionOutcome.INCOMPLETE,
        ),
        (CandidateGoverningStateStatus.BLOCKED, CandidateAdmissionOutcome.BLOCKED),
    ):
        decision = evaluate_candidate_admission(
            request=request,
            manifest=manifest,
            collision=collision,
            current_version=None,
            governing_state=CandidateGoverningState(status, None),
        )
        assert decision.outcome is outcome
    changed = replace(manifest.governing_state_binding, coverage="sha256:" + "2" * 64)
    stale = evaluate_candidate_admission(
        request=request,
        manifest=manifest,
        collision=collision,
        current_version=None,
        governing_state=CandidateGoverningState(
            CandidateGoverningStateStatus.COMPLETE, changed
        ),
    )
    assert stale.outcome is CandidateAdmissionOutcome.STALE


def test_partial_predecessor_and_request_cas_fail_closed(tmp_path) -> None:
    manifest = _manifest(
        _eligible_current(tmp_path, "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    )
    with pytest.raises(CandidateContractError, match="partial"):
        replace(
            _request(manifest, None),
            expected_current_version_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        )
    candidate = StoryCandidate(
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "66666666-6666-4666-8666-666666666666",
        "77777777-7777-4777-8777-777777777777",
        manifest.semantic_scope_digest,
    )
    with pytest.raises(CandidateContractError, match="partial"):
        StoryCandidateVersion(
            "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            candidate.candidate_id,
            2,
            "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
            None,
            "88888888-8888-4888-8888-888888888888",
            manifest,
        )


def test_collision_receipt_refresh_is_material_duplicate(tmp_path) -> None:
    candidate_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    use_collision = _eligible_current(tmp_path, candidate_id)
    use_binding = use_collision.request.binding
    admit_binding = replace(
        use_binding,
        operation=CandidateUseOperation.ADMIT_NEW_CANDIDATE,
        expected_candidate_id=None,
    )
    admit_collision = replace(
        use_collision,
        request=CurrentCollisionEligibilityRequest(
            admit_binding, use_collision.request.named_request_digest
        ),
        reason=CollisionEligibilityReason.CURRENT_SLOT_UNOCCUPIED,
        collision_state=CollisionState.UNOCCUPIED,
        observed_candidate_id=None,
    )
    admitted_manifest, current_manifest = (
        _manifest(admit_collision),
        _manifest(use_collision),
    )
    current = StoryCandidateVersion(
        "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        candidate_id,
        1,
        None,
        None,
        "66666666-6666-4666-8666-666666666666",
        admitted_manifest,
    )
    assert admitted_manifest.canonical_digest != current_manifest.canonical_digest
    assert (
        admitted_manifest.version_material_digest
        == current_manifest.version_material_digest
    )
    assert admitted_manifest.version_material_digest != digest_bytes(
        canonical_json_bytes(admitted_manifest.version_material_value())
    )
    duplicate = evaluate_candidate_admission(
        request=_request(current_manifest, current),
        manifest=current_manifest,
        collision=use_collision,
        current_version=current,
        governing_state=_current_state(current_manifest),
    )
    assert duplicate.outcome is CandidateAdmissionOutcome.DUPLICATE_EQUIVALENT
    changed = replace(current_manifest, uncertainties=("Materially changed",))
    successor = evaluate_candidate_admission(
        request=_request(changed, current),
        manifest=changed,
        collision=use_collision,
        current_version=current,
        governing_state=_current_state(changed),
    )
    assert successor.reason is CandidateAdmissionReason.SUCCESSOR_VERSION_PRE_EFFECT


def test_d2_comparator_must_match_exact_d1_target_version() -> None:
    base = _version(980)
    successor = _successor(base, 981)
    assessment, _ = _relationship_decision(
        successor, (base,), CanonicalOutcome.REL_CORRECTION_REVERSAL_OF
    )
    candidates_module._validate_relationship_route(successor, assessment)
    wrong = replace(
        assessment.comparator,
        version_id="eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
    )
    tampered = replace(
        assessment,
        comparator=wrong,
        comparator_manifest=replace(
            assessment.comparator_manifest, comparators=(wrong,)
        ),
    )
    with pytest.raises(CandidateContractError):
        candidates_module._validate_relationship_route(successor, tampered)


def test_evaluator_rejects_collision_namespace_and_key_mismatch(tmp_path) -> None:
    collision = _eligible_current(tmp_path, "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    manifest = _manifest(collision)
    for field, value in (
        ("collision_namespace", "different-candidate-namespace"),
        ("collision_key_digest", "sha256:" + "9" * 64),
    ):
        changed_binding = replace(collision.request.binding, **{field: value})
        changed = replace(
            collision,
            request=CurrentCollisionEligibilityRequest(
                changed_binding, collision.request.named_request_digest
            ),
        )
        receipt_bound = replace(
            manifest,
            collision_request_digest=changed.request.request_digest,
            collision_decision_digest=digest_bytes(changed.canonical_bytes),
        )
        with pytest.raises(CandidateContractError):
            evaluate_candidate_admission(
                request=_request(receipt_bound, None),
                manifest=receipt_bound,
                collision=changed,
                current_version=None,
                governing_state=_current_state(receipt_bound),
            )


def test_relationship_comparator_presence_matrix_and_nested_totality(tmp_path) -> None:
    manifest = _manifest(
        _eligible_current(tmp_path, "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    )
    comparator = (
        "33333333-3333-4333-8333-333333333333",
        "44444444-4444-4444-8444-444444444444",
        D,
    )
    invalid = (
        (AssessmentStatus.INCOMPLETE, None, comparator),
        (
            AssessmentStatus.COMPLETE,
            CanonicalOutcome.REL_NO_ADEQUATE_PRIOR_MATCH,
            comparator,
        ),
        (
            AssessmentStatus.COMPLETE,
            CanonicalOutcome.REL_DEVELOPMENT_OF,
            (None, None, None),
        ),
    )
    for status, outcome, values in invalid:
        with pytest.raises(CandidateContractError):
            replace(
                manifest,
                relationship_status=status,
                relationship_outcome=outcome,
                incomplete=status is AssessmentStatus.INCOMPLETE,
                relationship_comparator_hypothesis_id=values[0],
                relationship_comparator_version_id=values[1],
                relationship_comparator_version_digest=values[2],
            )
    assert (
        replace(
            manifest,
            relationship_status=AssessmentStatus.INCOMPLETE,
            relationship_outcome=None,
            incomplete=True,
        ).relationship_comparator_hypothesis_id
        is None
    )
    assert (
        _with_relationship(
            manifest, CanonicalOutcome.REL_DEVELOPMENT_OF
        ).relationship_comparator_version_digest
        == D
    )
    value = manifest.canonical_value()
    for malformed in ({"bad": "element"}, ["bad"]):
        changed = dict(value)
        changed["uncertainties"] = [malformed]
        with pytest.raises(CandidateContractError):
            CandidateGoverningManifest.from_value(changed)
        changed["uncertainties"] = value["uncertainties"]
        changed["lead_signal_bindings"] = [malformed]
        with pytest.raises(CandidateContractError):
            CandidateGoverningManifest.from_value(changed)


def test_story_candidate_digest_includes_schema_envelope() -> None:
    candidate = StoryCandidate(
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "66666666-6666-4666-8666-666666666666",
        "77777777-7777-4777-8777-777777777777",
        D,
    )
    assert candidate.canonical_digest == digest_bytes(candidate.canonical_bytes)
    replayed = StoryCandidate.from_canonical_bytes(candidate.canonical_bytes)
    assert replayed.canonical_bytes == candidate.canonical_bytes
    assert replayed.canonical_digest == candidate.canonical_digest
