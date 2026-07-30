from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from newsroom.authority.types import UtcTimestamp
from newsroom.entities.types import CanonicalEntityId, CanonicalEntityVersionId
from newsroom.extraction.types import (
    ExtractionOutputId,
    ExtractionPassageId,
    ExtractionRunId,
    ExtractionRunVersionId,
    ProposalEnvelopeId,
)
from newsroom.integrated.models import IntegratedHypothesisVersionId
from newsroom.relations.editorial_models import (
    EDITORIAL_PREDICATE_REGISTRY_V1,
    EDITORIAL_RELATION_ADMISSION_POLICY_VERSION,
    CanonicalEntityRelationEndpoint,
    EditorialPredicateEndpointPair,
    EditorialRelationDecisionRequest,
    EditorialRelationProducer,
    EditorialRelationProposalRequest,
    EditorialRelationReadPolicy,
    EditorialRelationTemporalScope,
    EventHypothesisRelationEndpoint,
    ExtractionRelationEvidence,
    SourceRevisionRelationEndpoint,
)
from newsroom.relations.editorial_types import (
    EditorialPredicateCode,
    EditorialPredicateDirectionality,
    EditorialRelationAssertionId,
    EditorialRelationContractError,
    EditorialRelationDecisionAction,
    EditorialRelationDecisionId,
    EditorialRelationEndpointKind,
    EditorialRelationProducerKind,
    EditorialRelationProposalId,
    EditorialRelationProposalVersionId,
)
from newsroom.sources.types import SourceItemId, SourceRevisionId


def _uuid(value: int) -> str:
    return f"00000000-0000-4000-8000-{value:012d}"


def _evidence(index: int, *, start: int = 0) -> ExtractionRelationEvidence:
    return ExtractionRelationEvidence(
        source_proposal_id=ProposalEnvelopeId.parse(_uuid(100 + index)),
        source_proposal_digest="sha256:" + f"{index + 1:02x}" * 32,
        run_id=ExtractionRunId.parse(_uuid(200 + index)),
        run_version_id=ExtractionRunVersionId.parse(_uuid(300 + index)),
        output_id=ExtractionOutputId.parse(_uuid(400 + index)),
        passage_id=ExtractionPassageId.parse(_uuid(500 + index)),
        source_evidence_ordinal=0,
        start_byte=start,
        end_byte=start + 10,
        evidence_text_digest="sha256:" + f"{index + 11:02x}" * 32,
    )


def _producer() -> EditorialRelationProducer:
    return EditorialRelationProducer(
        kind=EditorialRelationProducerKind.EXTRACTION_RUN,
        producer_id="fixture.editorial-relation",
        producer_version="fixture-editorial-relation-v1",
        contract_digest="sha256:" + "aa" * 32,
    )


def _proposal(
    *,
    predicate: EditorialPredicateCode = EditorialPredicateCode.ABOUT_EVENT,
) -> EditorialRelationProposalRequest:
    contract = EDITORIAL_PREDICATE_REGISTRY_V1.contract(predicate)
    return EditorialRelationProposalRequest(
        proposal_id=EditorialRelationProposalId.parse(_uuid(1)),
        proposal_version_id=EditorialRelationProposalVersionId.parse(_uuid(2)),
        version_number=1,
        expected_previous_version_id=None,
        predicate_registry_digest=EDITORIAL_PREDICATE_REGISTRY_V1.digest,
        predicate_contract_digest=contract.digest,
        predicate=predicate,
        subject=CanonicalEntityRelationEndpoint(
            entity_id=CanonicalEntityId.parse(_uuid(3)),
            entity_version_id=CanonicalEntityVersionId.parse(_uuid(4)),
        ),
        object=EventHypothesisRelationEndpoint(
            hypothesis_version_id=IntegratedHypothesisVersionId.parse(_uuid(5))
        ),
        temporal_scope=EditorialRelationTemporalScope(
            valid_from=None,
            valid_until=None,
            observed_at=UtcTimestamp.parse("2042-03-12T10:00:00.000000Z"),
        ),
        evidence=(_evidence(1),),
        resolution_dependency_ids=(),
        producer=_producer(),
        statement="The admitted entity is about the retained event hypothesis.",
        confidence_basis_points=7500,
        uncertainty_codes=("IDENTITY_REVIEWED",),
        basis_codes=("EXACT_OCCURRENCE",),
        idempotency_key="relation-proposal-one",
    )


def test_editorial_predicate_registry_is_closed_versioned_and_immutable() -> None:
    registry = EDITORIAL_PREDICATE_REGISTRY_V1
    assert registry.registry_version == "editorial-predicate-registry-v1"
    assert {item.predicate for item in registry.contracts} == set(
        EditorialPredicateCode
    )
    assert len(registry.contracts) == 9
    assert registry.digest.startswith("sha256:")
    assert all(item.digest.startswith("sha256:") for item in registry.contracts)
    assert registry.contract(EditorialPredicateCode.SAME_EVENT_AS).directionality is (
        EditorialPredicateDirectionality.SYMMETRIC
    )
    with pytest.raises(FrozenInstanceError):
        registry.registry_version = "changed"  # type: ignore[misc]


def test_predicate_contract_enforces_endpoint_types_and_temporal_semantics() -> None:
    development = EDITORIAL_PREDICATE_REGISTRY_V1.contract(
        EditorialPredicateCode.DEVELOPMENT_OF
    )
    assert development.allows(
        EditorialRelationEndpointKind.SOURCE_REVISION,
        EditorialRelationEndpointKind.SOURCE_REVISION,
    )
    assert not development.allows(
        EditorialRelationEndpointKind.CANONICAL_ENTITY_VERSION,
        EditorialRelationEndpointKind.EVENT_HYPOTHESIS_VERSION,
    )
    with pytest.raises(EditorialRelationContractError, match="valid interval"):
        replace(
            _proposal(),
            predicate=EditorialPredicateCode.DEVELOPMENT_OF,
            predicate_contract_digest=development.digest,
            subject=SourceRevisionRelationEndpoint(
                source_item_id=SourceItemId.parse(_uuid(20)),
                source_revision_id=SourceRevisionId.parse(_uuid(21)),
            ),
            object=SourceRevisionRelationEndpoint(
                source_item_id=SourceItemId.parse(_uuid(22)),
                source_revision_id=SourceRevisionId.parse(_uuid(23)),
            ),
        )


def test_symmetric_relations_require_canonical_endpoint_order() -> None:
    contract = EDITORIAL_PREDICATE_REGISTRY_V1.contract(
        EditorialPredicateCode.SAME_EVENT_AS
    )
    left = EventHypothesisRelationEndpoint(
        hypothesis_version_id=IntegratedHypothesisVersionId.parse(_uuid(30))
    )
    right = EventHypothesisRelationEndpoint(
        hypothesis_version_id=IntegratedHypothesisVersionId.parse(_uuid(31))
    )
    request = EditorialRelationProposalRequest(
        proposal_id=EditorialRelationProposalId.parse(_uuid(32)),
        proposal_version_id=EditorialRelationProposalVersionId.parse(_uuid(33)),
        version_number=1,
        expected_previous_version_id=None,
        predicate_registry_digest=EDITORIAL_PREDICATE_REGISTRY_V1.digest,
        predicate_contract_digest=contract.digest,
        predicate=EditorialPredicateCode.SAME_EVENT_AS,
        subject=left,
        object=right,
        temporal_scope=EditorialRelationTemporalScope(
            valid_from=None,
            valid_until=None,
            observed_at=UtcTimestamp.parse("2042-03-12T10:00:00.000000Z"),
        ),
        evidence=(_evidence(2),),
        resolution_dependency_ids=(),
        producer=_producer(),
        statement="The two hypotheses describe the same event.",
        confidence_basis_points=None,
        uncertainty_codes=(),
        basis_codes=("EXACT_WORKFLOW_MATCH",),
        idempotency_key="same-event-canonical",
    )
    assert request.semantic_slot_digest.startswith("sha256:")
    with pytest.raises(EditorialRelationContractError, match="canonical order"):
        replace(
            request,
            proposal_id=EditorialRelationProposalId.parse(_uuid(34)),
            proposal_version_id=EditorialRelationProposalVersionId.parse(_uuid(35)),
            subject=right,
            object=left,
        )


def test_relation_evidence_is_exact_sorted_and_unique() -> None:
    first = _evidence(3)
    second = _evidence(4)
    ordered = tuple(sorted((first, second), key=lambda item: item.canonical_bytes))
    request = replace(
        _proposal(),
        proposal_id=EditorialRelationProposalId.parse(_uuid(40)),
        proposal_version_id=EditorialRelationProposalVersionId.parse(_uuid(41)),
        evidence=ordered,
        idempotency_key="ordered-evidence",
    )
    assert [item.digest for item in request.evidence] == [
        item.digest for item in ordered
    ]
    with pytest.raises(EditorialRelationContractError, match="sorted"):
        replace(
            request,
            proposal_id=EditorialRelationProposalId.parse(_uuid(42)),
            proposal_version_id=EditorialRelationProposalVersionId.parse(_uuid(43)),
            evidence=tuple(reversed(ordered)),
            idempotency_key="reversed-evidence",
        )
    with pytest.raises(EditorialRelationContractError, match="unique"):
        replace(
            request,
            proposal_id=EditorialRelationProposalId.parse(_uuid(44)),
            proposal_version_id=EditorialRelationProposalVersionId.parse(_uuid(45)),
            evidence=(first, first),
            idempotency_key="duplicate-evidence",
        )


def test_relation_decision_shapes_separate_admission_and_lifecycle() -> None:
    proposal = _proposal()
    accepted = EditorialRelationDecisionRequest(
        decision_id=EditorialRelationDecisionId.parse(_uuid(50)),
        action=EditorialRelationDecisionAction.ACCEPT,
        proposal_id=proposal.proposal_id,
        proposal_version_id=proposal.proposal_version_id,
        expected_proposal_version_digest=proposal.canonical_digest,
        expected_previous_decision_id=None,
        expected_previous_decision_version=0,
        assertion_id=EditorialRelationAssertionId.parse(_uuid(51)),
        target_assertion_id=None,
        successor_assertion_id=None,
        supersession_id=None,
        reason_code="EXPLICIT_EDITORIAL_ACCEPT",
        decision_policy_version=EDITORIAL_RELATION_ADMISSION_POLICY_VERSION,
        idempotency_key="accept-relation",
    )
    assert accepted.action.terminal_for_proposal
    with pytest.raises(EditorialRelationContractError, match="lifecycle"):
        replace(
            accepted,
            decision_id=EditorialRelationDecisionId.parse(_uuid(52)),
            target_assertion_id=EditorialRelationAssertionId.parse(_uuid(53)),
            idempotency_key="invalid-accept-shape",
        )



def test_relation_requests_reject_changed_registry_contract_and_policy() -> None:
    proposal = _proposal()
    wrong_registry = "sha256:" + "00" * 32
    wrong_contract = EDITORIAL_PREDICATE_REGISTRY_V1.contract(
        EditorialPredicateCode.SAME_PROCESS_AS
    ).digest
    with pytest.raises(EditorialRelationContractError, match="registry digest"):
        replace(
            proposal,
            proposal_id=EditorialRelationProposalId.parse(_uuid(54)),
            proposal_version_id=EditorialRelationProposalVersionId.parse(_uuid(55)),
            predicate_registry_digest=wrong_registry,
            idempotency_key="wrong-registry",
        )
    with pytest.raises(EditorialRelationContractError, match="predicate digest"):
        replace(
            proposal,
            proposal_id=EditorialRelationProposalId.parse(_uuid(56)),
            proposal_version_id=EditorialRelationProposalVersionId.parse(_uuid(57)),
            predicate_contract_digest=wrong_contract,
            idempotency_key="wrong-predicate-contract",
        )

    accepted = EditorialRelationDecisionRequest(
        decision_id=EditorialRelationDecisionId.parse(_uuid(58)),
        action=EditorialRelationDecisionAction.ACCEPT,
        proposal_id=proposal.proposal_id,
        proposal_version_id=proposal.proposal_version_id,
        expected_proposal_version_digest=proposal.canonical_digest,
        expected_previous_decision_id=None,
        expected_previous_decision_version=0,
        assertion_id=EditorialRelationAssertionId.parse(_uuid(59)),
        target_assertion_id=None,
        successor_assertion_id=None,
        supersession_id=None,
        reason_code="EXPLICIT_EDITORIAL_ACCEPT",
        decision_policy_version=EDITORIAL_RELATION_ADMISSION_POLICY_VERSION,
        idempotency_key="accepted-policy-contract",
    )
    with pytest.raises(EditorialRelationContractError, match="policy version"):
        replace(
            accepted,
            decision_id=EditorialRelationDecisionId.parse(_uuid(60)),
            decision_policy_version="editorial-relation-admission-policy-v2",
            idempotency_key="wrong-decision-policy",
        )


def test_relation_read_policy_separates_proposal_admitted_and_projection() -> None:
    policy = EditorialRelationReadPolicy(
        policy_id="editorial-relation-reader-v1",
        purpose="editorial.relation.read",
        proposal_required_scope="authority.relation.read_proposals",
        admitted_required_scope="authority.relation.read_admitted",
        projection_required_scope="authority.relation.read_projection",
        allowed_principal_ids=frozenset({"principal.editor"}),
        max_results=64,
    )
    policy.require_principal("principal.editor")
    policy.require_limit(64)
    assert policy.digest.startswith("sha256:")
    with pytest.raises(EditorialRelationContractError, match="distinct scopes"):
        EditorialRelationReadPolicy(
            policy_id="bad-reader-v1",
            purpose="editorial.relation.read",
            proposal_required_scope="authority.relation.read",
            admitted_required_scope="authority.relation.read",
            projection_required_scope="authority.relation.read_projection",
            allowed_principal_ids=frozenset({"principal.editor"}),
        )


def test_public_relations_package_exports_general_editorial_contracts() -> None:
    import newsroom.relations as relations

    assert relations.EDITORIAL_PREDICATE_REGISTRY_V1.digest == (
        EDITORIAL_PREDICATE_REGISTRY_V1.digest
    )
    assert relations.EditorialRelationProposalId is EditorialRelationProposalId
    assert relations.EditorialRelationProposalRequest is EditorialRelationProposalRequest
    assert relations.EDITORIAL_RELATION_PROPOSAL_COMMAND == (
        "editorial.relation.proposal.record"
    )
