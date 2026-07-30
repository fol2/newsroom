from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from newsroom.authority.canonical import digest_bytes, digest_canonical
from newsroom.sources import (
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceItemId,
    SourceRevisionId,
    DiscoveryRepresentationId,
)
from newsroom.authority.types import EventId, UtcTimestamp
from newsroom.entities import (
    ENTITY_NORMALISATION_CONTRACT_DIGEST,
    CanonicalEntity,
    CanonicalEntityId,
    CanonicalEntityLifecycle,
    CanonicalEntityVersion,
    CanonicalEntityVersionId,
    EntityAdmissionGuard,
    EntityAlias,
    EntityAliasId,
    EntityAliasKind,
    EntityContractError,
    EntityCreationDecisionKind,
    EntityKind,
    EntityLineageVersion,
    EntityLineageDecisionKind,
    EntityMergeDecisionId,
    EntityMergeDecisionRequest,
    EntityMention,
    EntityMentionAdmissionRequest,
    EntityMentionId,
    EntityReadPolicy,
    EntityResolutionDecisionAction,
    EntityResolutionDecisionId,
    EntityResolutionDecisionRequest,
    EntityResolutionProposalId,
    EntityResolutionProposalKind,
    EntityResolutionProposalRequest,
    EntityResolutionProposalVersionId,
    EntityResolutionState,
    EntityReversalDecisionId,
    EntityReversalDecisionRequest,
    EntityReversalTargetKind,
    EntityScript,
    EntitySplitAllocation,
    EntitySplitDecisionId,
    EntitySplitDecisionRequest,
    classify_entity_script,
    normalize_entity_text,
)
from newsroom.extraction.types import (
    ExtractionOutputId,
    ExtractionPassageId,
    ExtractionRunId,
    ExtractionRunVersionId,
    ProposalEnvelopeId,
    ProposalSetId,
)


def _id(cls, suffix: int):
    return cls.parse(f"00000000-0000-4000-8000-{suffix:012d}")


NOW = UtcTimestamp(datetime(2026, 7, 30, 1, 30, tzinfo=UTC))
DIGEST = digest_canonical({"fixture": "entity-4b"})


def _mention_request(*, text: str = "hong kong transport department"):
    return EntityMentionAdmissionRequest(
        mention_id=_id(EntityMentionId, 4201),
        source_proposal_id=_id(ProposalEnvelopeId, 4101),
        expected_source_proposal_digest=DIGEST,
        entity_kind=EntityKind.GOVERNMENT_BODY,
        language="en-GB",
        script=EntityScript.LATIN,
        normalized_text=text,
        normalization_contract_digest=ENTITY_NORMALISATION_CONTRACT_DIGEST,
        idempotency_key="entity-mention-en-v1",
    )


def _mention(*, text: str = "Hong Kong Transport Department") -> EntityMention:
    data = text.encode("utf-8")
    return EntityMention(
        mention_id=_id(EntityMentionId, 4201),
        source_proposal_id=_id(ProposalEnvelopeId, 4101),
        proposal_set_id=_id(ProposalSetId, 4102),
        output_id=_id(ExtractionOutputId, 4103),
        run_id=_id(ExtractionRunId, 4104),
        run_version_id=_id(ExtractionRunVersionId, 4105),
        definition_id=_id(SourceDefinitionId, 3101),
        definition_version_id=_id(SourceDefinitionVersionId, 3102),
        item_id=_id(SourceItemId, 3103),
        revision_id=_id(SourceRevisionId, 3104),
        representation_id=_id(DiscoveryRepresentationId, 3105),
        passage_id=_id(ExtractionPassageId, 4106),
        start_byte=0,
        end_byte=len(data),
        evidence_text_digest=digest_bytes(data),
        mention_text=text,
        normalized_text=normalize_entity_text(text),
        normalization_contract_digest=ENTITY_NORMALISATION_CONTRACT_DIGEST,
        language="en-GB",
        script=classify_entity_script(text),
        entity_kind=EntityKind.GOVERNMENT_BODY,
        confidence_basis_points=9100,
        uncertainty_codes=("REQUIRES_EXPLICIT_RESOLUTION",),
        rationale_codes=("EXACT_FIXTURE_EVIDENCE",),
        source_proposal_digest=DIGEST,
        authority_event_id=_id(EventId, 4202),
        authority_ledger_seq=100,
        recorded_at=NOW,
    )


def _resolution_request(
    *,
    kind: EntityResolutionProposalKind = EntityResolutionProposalKind.MENTION_TO_NEW_ENTITY,
) -> EntityResolutionProposalRequest:
    kwargs = {
        "proposal_id": _id(EntityResolutionProposalId, 4301),
        "proposal_version_id": _id(EntityResolutionProposalVersionId, 4302),
        "version_number": 1,
        "expected_previous_version_id": None,
        "source_proposal_id": _id(ProposalEnvelopeId, 4101),
        "expected_source_proposal_digest": DIGEST,
        "kind": kind,
        "subject_mention_id": _id(EntityMentionId, 4201),
        "object_mention_id": None,
        "candidate_entity_id": None,
        "candidate_entity_version_id": None,
        "confidence_basis_points": 8000,
        "uncertainty_codes": ("EDITORIAL_REVIEW_REQUIRED",),
        "basis_codes": ("EXACT_PASSAGE",),
        "idempotency_key": "entity-resolution-proposal-v1",
    }
    if kind is EntityResolutionProposalKind.MENTION_EQUIVALENCE:
        kwargs["object_mention_id"] = _id(EntityMentionId, 4203)
    elif kind in {
        EntityResolutionProposalKind.MENTION_TO_ENTITY,
        EntityResolutionProposalKind.ALIAS_TO_ENTITY,
    }:
        kwargs["candidate_entity_id"] = _id(CanonicalEntityId, 4401)
        kwargs["candidate_entity_version_id"] = _id(
            CanonicalEntityVersionId, 4402
        )
    return EntityResolutionProposalRequest(**kwargs)


def test_fixed_bilingual_normalisation_is_explicit_and_non_fuzzy() -> None:
    assert normalize_entity_text("Hong   Kong Transport Department") == (
        "hong kong transport department"
    )
    assert normalize_entity_text("Cafe\u0301") == "café"
    assert normalize_entity_text("香港運輸署") == "香港運輸署"
    assert classify_entity_script("Hong Kong") is EntityScript.LATIN
    assert classify_entity_script("香港運輸署") is EntityScript.TRADITIONAL_HAN
    assert classify_entity_script("香港 Transport") is EntityScript.MIXED


def test_mention_request_requires_exact_normalisation_contract() -> None:
    request = _mention_request()
    assert request.digest == digest_canonical(request.canonical_value())

    with pytest.raises(EntityContractError, match="normalisation"):
        _mention_request(text="Hong Kong Transport Department")

    with pytest.raises(EntityContractError, match="unapproved normalisation"):
        replace(request, normalization_contract_digest=DIGEST)


def test_retained_mention_is_proposed_exact_evidence() -> None:
    mention = _mention()
    assert mention.trust_scope.value == "PROPOSED"
    assert mention.canonical_digest == digest_bytes(mention.canonical_bytes)
    assert mention.semantic_digest.startswith("sha256:")

    with pytest.raises(EntityContractError, match="script differs"):
        replace(mention, script=EntityScript.MIXED)


def test_resolution_proposal_shapes_are_closed() -> None:
    new_entity = _resolution_request()
    assert new_entity.digest.startswith("sha256:")
    assert new_entity.stable_semantic_digest.startswith("sha256:")

    equivalence = _resolution_request(
        kind=EntityResolutionProposalKind.MENTION_EQUIVALENCE
    )
    assert equivalence.object_mention_id is not None

    existing = _resolution_request(
        kind=EntityResolutionProposalKind.MENTION_TO_ENTITY
    )
    assert existing.candidate_entity_id is not None

    with pytest.raises(EntityContractError, match="cannot name an existing target"):
        replace(new_entity, candidate_entity_id=_id(CanonicalEntityId, 4401))


def test_resolution_decision_cannot_admit_identity_without_accept() -> None:
    accepted = EntityResolutionDecisionRequest(
        proposal_id=_id(EntityResolutionProposalId, 4301),
        expected_proposal_version_id=_id(EntityResolutionProposalVersionId, 4302),
        expected_proposal_digest=DIGEST,
        action=EntityResolutionDecisionAction.ACCEPT,
        expected_decision_version=0,
        expected_previous_decision_id=None,
        accepted_entity_id=_id(CanonicalEntityId, 4401),
        accepted_entity_version_id=_id(CanonicalEntityVersionId, 4402),
        alias_id=_id(EntityAliasId, 4403),
        alias_kind=EntityAliasKind.PRIMARY_NAME,
        reason_code="EDITORIAL_ACCEPT",
        decision_policy_version="entity-resolution-policy-v1",
        idempotency_key="entity-resolution-accept-v1",
    )
    assert accepted.digest.startswith("sha256:")

    with pytest.raises(EntityContractError, match="non-accept"):
        replace(accepted, action=EntityResolutionDecisionAction.HOLD)


def test_canonical_entity_and_alias_are_admitted_but_not_name_identified() -> None:
    decision_id = _id(EntityResolutionDecisionId, 4501)
    entity_id = _id(CanonicalEntityId, 4401)
    version_id = _id(CanonicalEntityVersionId, 4402)
    entity = CanonicalEntity(
        entity_id=entity_id,
        entity_kind=EntityKind.GOVERNMENT_BODY,
        created_by_kind=EntityCreationDecisionKind.RESOLUTION,
        created_by_decision_id=str(decision_id),
        initial_version_id=version_id,
        authority_event_id=_id(EventId, 4502),
        authority_ledger_seq=101,
        created_at=NOW,
    )
    assert "name" not in entity.canonical_value()

    version = CanonicalEntityVersion(
        entity_version_id=version_id,
        entity_id=entity_id,
        version_number=1,
        previous_entity_version_id=None,
        entity_kind=EntityKind.GOVERNMENT_BODY,
        lifecycle=CanonicalEntityLifecycle.ACTIVE,
        lineage_decision_kind=None,
        lineage_decision_id=None,
        preferred_continuation_entity_id=entity_id,
        authority_event_id=_id(EventId, 4503),
        authority_ledger_seq=102,
        recorded_at=NOW,
    )
    assert version.canonical_value()["trust_scope"] == "ADMITTED"

    mention = _mention()
    alias = EntityAlias(
        alias_id=_id(EntityAliasId, 4403),
        entity_id=entity_id,
        entity_version_id=version_id,
        alias_text=mention.mention_text,
        normalized_text=mention.normalized_text,
        normalization_contract_digest=ENTITY_NORMALISATION_CONTRACT_DIGEST,
        language=mention.language,
        script=mention.script,
        alias_kind=EntityAliasKind.PRIMARY_NAME,
        valid_from=None,
        valid_until=None,
        provenance_mention_id=mention.mention_id,
        resolution_decision_id=decision_id,
        uncertainty_codes=(),
        authority_event_id=_id(EventId, 4504),
        authority_ledger_seq=103,
        recorded_at=NOW,
    )
    assert alias.trust_scope.value == "ADMITTED"


def test_merge_split_and_reversal_requests_preserve_explicit_lineage() -> None:
    entity_ids = tuple(
        sorted(
            (_id(CanonicalEntityId, 4601), _id(CanonicalEntityId, 4602)),
            key=str,
        )
    )
    version_ids = (
        _id(CanonicalEntityVersionId, 4611),
        _id(CanonicalEntityVersionId, 4612),
    )
    predecessors = tuple(
        EntityLineageVersion(entity_id, version_id)
        for entity_id, version_id in zip(entity_ids, version_ids, strict=True)
    )
    basis = (_id(EntityResolutionProposalId, 4301),)
    merge = EntityMergeDecisionRequest(
        merge_decision_id=_id(EntityMergeDecisionId, 4620),
        predecessors=predecessors,
        successor_entity_id=_id(CanonicalEntityId, 4603),
        successor_entity_version_id=_id(CanonicalEntityVersionId, 4613),
        preferred_continuation_entity_id=entity_ids[0],
        basis_resolution_proposal_ids=basis,
        reason_code="EDITORIAL_MERGE",
        decision_policy_version="entity-resolution-policy-v1",
        idempotency_key="entity-merge-v1",
    )
    assert merge.digest.startswith("sha256:")

    successor_ids = tuple(
        sorted(
            (_id(CanonicalEntityId, 4702), _id(CanonicalEntityId, 4703)),
            key=str,
        )
    )
    successor_versions = (
        _id(CanonicalEntityVersionId, 4712),
        _id(CanonicalEntityVersionId, 4713),
    )
    successors = tuple(
        EntityLineageVersion(entity_id, version_id)
        for entity_id, version_id in zip(
            successor_ids, successor_versions, strict=True
        )
    )
    allocations = tuple(
        sorted(
            (
                EntitySplitAllocation(_id(EntityMentionId, 4201), successor_ids[0]),
                EntitySplitAllocation(_id(EntityMentionId, 4203), successor_ids[1]),
            ),
            key=lambda item: (str(item.mention_id), str(item.successor_entity_id)),
        )
    )
    split = EntitySplitDecisionRequest(
        split_decision_id=_id(EntitySplitDecisionId, 4720),
        source_entity_id=_id(CanonicalEntityId, 4701),
        expected_source_version_id=_id(CanonicalEntityVersionId, 4711),
        successors=successors,
        allocations=allocations,
        reason_code="EDITORIAL_SPLIT",
        decision_policy_version="entity-resolution-policy-v1",
        idempotency_key="entity-split-v1",
    )
    assert split.digest.startswith("sha256:")

    reversal = EntityReversalDecisionRequest(
        reversal_decision_id=_id(EntityReversalDecisionId, 4730),
        target_kind=EntityReversalTargetKind.SPLIT,
        target_decision_id=str(split.split_decision_id),
        expected_current_entity_version_ids=tuple(sorted(successor_versions, key=str)),
        restorations=(
            EntityLineageVersion(
                _id(CanonicalEntityId, 4701),
                _id(CanonicalEntityVersionId, 4714),
            ),
        ),
        reason_code="EDITORIAL_REVERSAL",
        decision_policy_version="entity-resolution-policy-v1",
        idempotency_key="entity-reversal-v1",
    )
    assert reversal.digest.startswith("sha256:")


def test_dependent_admission_guard_fails_closed_until_identity_is_resolved() -> None:
    unresolved = EntityAdmissionGuard(
        proposal_id=_id(EntityResolutionProposalId, 4301),
        proposal_version_id=_id(EntityResolutionProposalVersionId, 4302),
        state=EntityResolutionState.UNRESOLVED,
        materially_unresolved=True,
        checked_at_ledger_seq=200,
    )
    with pytest.raises(EntityContractError, match="blocks dependent admission"):
        unresolved.require_resolved()

    accepted = EntityAdmissionGuard(
        proposal_id=unresolved.proposal_id,
        proposal_version_id=unresolved.proposal_version_id,
        state=EntityResolutionState.ACCEPTED,
        materially_unresolved=False,
        checked_at_ledger_seq=201,
    )
    accepted.require_resolved()


def test_entity_read_policy_requires_three_distinct_scopes() -> None:
    policy = EntityReadPolicy(
        policy_id="increment-4b-entity-read-v1",
        purpose="entity.authority.audit",
        proposal_required_scope="authority.entity.read_proposals",
        admitted_required_scope="authority.entity.read_admitted",
        projection_required_scope="authority.entity.read_projection",
        allowed_principal_ids=frozenset({"principal.alpha"}),
        max_results=100,
    )
    assert policy.digest.startswith("sha256:")
    policy.require_principal("principal.alpha")
    policy.require_limit(100)

    with pytest.raises(EntityContractError, match="distinct scopes"):
        EntityReadPolicy(
            policy_id=policy.policy_id,
            purpose=policy.purpose,
            proposal_required_scope=policy.proposal_required_scope,
            admitted_required_scope=policy.proposal_required_scope,
            projection_required_scope=policy.projection_required_scope,
            allowed_principal_ids=policy.allowed_principal_ids,
        )
