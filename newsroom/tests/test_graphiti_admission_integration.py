from __future__ import annotations

from types import SimpleNamespace

import pytest

from newsroom.authority.auth import AuthenticationProof
from newsroom.authority.canonical import digest_canonical
from newsroom.authority.types import EventId, UtcTimestamp
from newsroom.control_plane.graphiti_admission import (
    GraphitiAdmissionConsumerError,
    GraphitiAdmissionRequest,
    GraphitiGovernedDecision,
)
from newsroom.control_plane.graphiti_admission_integration import (
    ExistingGovernedGraphitiAdmissionAuthority,
    GraphitiEntityAdmissionPlan,
    GraphitiRelationAdmissionPlan,
)
from newsroom.entities.models import (
    EntityMentionAdmissionRequest,
    EntityResolutionDecision,
    EntityResolutionDecisionRequest,
    EntityResolutionProposalRequest,
)
from newsroom.entities.types import (
    ENTITY_NORMALISATION_CONTRACT_DIGEST,
    CanonicalEntityId,
    CanonicalEntityLifecycle,
    CanonicalEntityVersionId,
    EntityAliasId,
    EntityAliasKind,
    EntityKind,
    EntityMentionId,
    EntityResolutionDecisionAction,
    EntityResolutionDecisionId,
    EntityResolutionProposalId,
    EntityResolutionProposalKind,
    EntityResolutionProposalVersionId,
    EntityScript,
)
from newsroom.extraction.models import ProposalDraft
from newsroom.extraction.types import (
    EvidenceRange,
    ExtractionPassageId,
    ExtractionProposalKind,
    ProposalEnvelopeId,
    ProposalPredicateHint,
)
from newsroom.graphiti_adapter.admission import GraphitiProposalAdmissionAction
from newsroom.relations.editorial_models import (
    CanonicalEntityRelationEndpoint,
    EditorialRelationTemporalScope,
)
from newsroom.relations.editorial_types import (
    EditorialPredicateCode,
    EditorialRelationAssertionLifecycle,
    EditorialRelationDecisionAction,
)

DIGEST = "sha256:" + ("ab" * 32)


def _request() -> GraphitiAdmissionRequest:
    proposal = ProposalDraft(
        local_id="entity.0001",
        kind=ExtractionProposalKind.ENTITY_MENTION,
        subject_placeholder="Alice",
        object_placeholder=None,
        predicate_hint=None,
        confidence_basis_points=9_000,
        uncertainty_codes=(),
        rationale_codes=("EXACT_EXTRACTION_EVIDENCE",),
        evidence=(
            EvidenceRange(
                passage_id=ExtractionPassageId.parse(
                    "00000000-0000-4000-8000-000000007601"
                ),
                start_byte=0,
                end_byte=5,
                evidence_text_digest=DIGEST,
            ),
        ),
    )
    return GraphitiAdmissionRequest(
        queue_seq=1,
        proposal_key="proposal-key",
        source_receipt_digest=DIGEST,
        proposal=proposal,
        proposal_payload=proposal.canonical_value(),
        evidence_passages=({"passage_id": str(proposal.evidence[0].passage_id)},),
        proposed_endpoints=None,
        relation_statement=None,
        relation_temporal_bounds=None,
        source_lineage={"revision_id": "fixture"},
    )


def _plan(request: GraphitiAdmissionRequest) -> GraphitiEntityAdmissionPlan:
    mention_id = EntityMentionId.parse("00000000-0000-4000-8000-000000007602")
    source_id = ProposalEnvelopeId.parse("00000000-0000-4000-8000-000000007603")
    proposal_id = EntityResolutionProposalId.parse(
        "00000000-0000-4000-8000-000000007604"
    )
    version_id = EntityResolutionProposalVersionId.parse(
        "00000000-0000-4000-8000-000000007605"
    )
    proposal_request = EntityResolutionProposalRequest(
        proposal_id=proposal_id,
        proposal_version_id=version_id,
        version_number=1,
        expected_previous_version_id=None,
        source_proposal_id=source_id,
        expected_source_proposal_digest=DIGEST,
        kind=EntityResolutionProposalKind.MENTION_TO_NEW_ENTITY,
        subject_mention_id=mention_id,
        object_mention_id=None,
        candidate_entity_id=None,
        candidate_entity_version_id=None,
        confidence_basis_points=9_000,
        uncertainty_codes=(),
        basis_codes=("EXACT_EXTRACTION_EVIDENCE",),
        idempotency_key="entity-proposal",
    )
    retained_digest = digest_canonical(proposal_request.canonical_value())
    return GraphitiEntityAdmissionPlan(
        graphiti_proposal_digest=request.proposal.digest,
        graphiti_proposal_local_id=request.proposal.local_id,
        mention_requests=(
            EntityMentionAdmissionRequest(
                mention_id=mention_id,
                source_proposal_id=source_id,
                expected_source_proposal_digest=DIGEST,
                entity_kind=EntityKind.PERSON,
                language="en-GB",
                script=EntityScript.LATIN,
                normalized_text="alice",
                normalization_contract_digest=ENTITY_NORMALISATION_CONTRACT_DIGEST,
                idempotency_key="entity-mention",
            ),
        ),
        proposal_request=proposal_request,
        decision_request=EntityResolutionDecisionRequest(
            proposal_id=proposal_id,
            expected_proposal_version_id=version_id,
            expected_proposal_digest=retained_digest,
            action=EntityResolutionDecisionAction.ACCEPT,
            expected_decision_version=0,
            expected_previous_decision_id=None,
            accepted_entity_id=CanonicalEntityId.parse(
                "00000000-0000-4000-8000-000000007606"
            ),
            accepted_entity_version_id=CanonicalEntityVersionId.parse(
                "00000000-0000-4000-8000-000000007607"
            ),
            alias_id=EntityAliasId.parse("00000000-0000-4000-8000-000000007608"),
            alias_kind=EntityAliasKind.PRIMARY_NAME,
            reason_code="FIXTURE_ACCEPT",
            decision_policy_version="entity-resolution-policy-v1",
            idempotency_key="entity-decision",
        ),
    )


class _Entities:
    def __init__(self, plan: GraphitiEntityAdmissionPlan) -> None:
        self.plan = plan
        self.calls: list[str] = []
        self.retained_decision: EntityResolutionDecision | None = None
        self.preferred_entity_id = plan.decision_request.accepted_entity_id

    def admit_mention(self, request, *, proof):
        assert isinstance(proof, AuthenticationProof)
        self.calls.append("mention")
        return SimpleNamespace()

    def propose_resolution(self, request, *, proof):
        self.calls.append("propose")
        return SimpleNamespace(
            proposal_id=request.proposal_id,
            proposal_version_id=request.proposal_version_id,
            canonical_digest=self.plan.decision_request.expected_proposal_digest,
        )

    def decide_resolution(self, request, *, proof):
        self.calls.append("decide")
        self.retained_decision = EntityResolutionDecision(
            decision_id=EntityResolutionDecisionId.parse(
                "00000000-0000-4000-8000-000000007609"
            ),
            proposal_id=request.proposal_id,
            proposal_version_id=request.expected_proposal_version_id,
            proposal_digest=request.expected_proposal_digest,
            action=request.action,
            decision_version=1,
            previous_decision_id=None,
            accepted_entity_id=request.accepted_entity_id,
            accepted_entity_version_id=request.accepted_entity_version_id,
            alias_id=request.alias_id,
            reason_code=request.reason_code,
            decision_policy_version=request.decision_policy_version,
            authority_event_id=EventId.parse("00000000-0000-4000-8000-000000007610"),
            authority_ledger_seq=42,
            recorded_at=UtcTimestamp.parse("2026-08-24T00:00:00Z"),
        )
        return self.retained_decision

    def decision(self, proposal_id, *, proof):
        assert proposal_id == self.plan.proposal_request.proposal_id
        return self.retained_decision

    def entity_version(self, version_id, *, proof):
        assert version_id == self.plan.decision_request.accepted_entity_version_id
        return SimpleNamespace(
            entity_id=self.plan.decision_request.accepted_entity_id,
            version_number=1,
            lifecycle=CanonicalEntityLifecycle.ACTIVE,
            canonical_value=lambda: {
                "entity_id": str(self.plan.decision_request.accepted_entity_id),
                "entity_version_id": str(version_id),
                "lifecycle": "ACTIVE",
                "version_number": 1,
            },
        )

    def preferred(self, entity_id, *, proof):
        return SimpleNamespace(
            entity_id=entity_id,
            current_entity_version_id=(
                self.plan.decision_request.accepted_entity_version_id
            ),
            preferred_entity_id=self.preferred_entity_id,
            lifecycle=CanonicalEntityLifecycle.ACTIVE,
        )

    def aliases(self, entity_id, *, limit, proof):
        assert entity_id == self.plan.decision_request.accepted_entity_id
        assert limit == 16
        return ()


def test_existing_authority_executes_typed_entity_commands() -> None:
    request = _request()
    plan = _plan(request)
    entities = _Entities(plan)
    authority = ExistingGovernedGraphitiAdmissionAuthority(
        entities=entities,  # type: ignore[arg-type]
        relations=SimpleNamespace(),  # type: ignore[arg-type]
        proof=AuthenticationProof(method="STATIC_TOKEN", credential="fixture"),
        entity_plan=lambda *_: plan,
        relation_plan=lambda *_: pytest.fail("relation planner called"),
    )

    decision = authority.decide_entity_resolution(
        request,
        required_action=GraphitiProposalAdmissionAction.ADMIT,
        idempotency_key="graphiti-admit:proposal-key",
    )

    assert entities.calls == ["mention", "propose", "decide"]
    assert decision.action is GraphitiProposalAdmissionAction.ADMIT
    assert decision.authority_ledger_seq == 42

    context = authority.current_context(request, decision)

    assert context is not None
    assert context.currentness_state == "CURRENT"
    assert tuple(item.authority_kind for item in context.bindings) == (
        "CANONICAL_ENTITY",
        "ENTITY_RESOLUTION_DECISION",
    )
    assert context.admitted_temporal_fields == (
        ("admitted_at", "2026-08-24T00:00:00.000000Z"),
    )
    assert context.admitted_structured_value["authority_kind"] == "CANONICAL_ENTITY"


def test_existing_authority_marks_merged_entity_head_stale() -> None:
    request = _request()
    plan = _plan(request)
    entities = _Entities(plan)
    entities.preferred_entity_id = CanonicalEntityId.parse(
        "00000000-0000-4000-8000-0000000076ff"
    )
    authority = ExistingGovernedGraphitiAdmissionAuthority(
        entities=entities,  # type: ignore[arg-type]
        relations=SimpleNamespace(),  # type: ignore[arg-type]
        proof=AuthenticationProof(method="STATIC_TOKEN", credential="fixture"),
        entity_plan=lambda *_: plan,
        relation_plan=lambda *_: pytest.fail("relation planner called"),
    )
    decision = authority.decide_entity_resolution(
        request,
        required_action=GraphitiProposalAdmissionAction.ADMIT,
        idempotency_key="graphiti-admit:proposal-key",
    )

    context = authority.current_context(request, decision)

    assert context is not None
    assert context.currentness_state == "STALE"


def test_existing_authority_hydrates_current_relation_facts() -> None:
    entity_request = _request()
    proposal = ProposalDraft(
        local_id="relation.0001",
        kind=ExtractionProposalKind.RELATION,
        subject_placeholder="Alice",
        object_placeholder="Bob",
        predicate_hint=ProposalPredicateHint.SUPPORTS,
        confidence_basis_points=9_000,
        uncertainty_codes=(),
        rationale_codes=("EXACT_EXTRACTION_EVIDENCE",),
        evidence=entity_request.proposal.evidence,
    )
    request = GraphitiAdmissionRequest(
        queue_seq=1,
        proposal_key="relation-proposal-key",
        source_receipt_digest=DIGEST,
        proposal=proposal,
        proposal_payload=proposal.canonical_value(),
        evidence_passages=entity_request.evidence_passages,
        proposed_endpoints=("Alice", "Bob"),
        relation_statement="Alice supports Bob",
        relation_temporal_bounds={
            "valid_at": "2026-08-24T00:00:00Z",
            "invalid_at": None,
            "expired_at": None,
        },
        source_lineage=entity_request.source_lineage,
    )
    decision = GraphitiGovernedDecision(
        proposal_key=request.proposal_key,
        proposal_digest=proposal.digest,
        proposal_kind=proposal.kind,
        proposal_local_id=proposal.local_id,
        action=GraphitiProposalAdmissionAction.ADMIT,
        decision_id="00000000-0000-4000-8000-0000000076a1",
        authority_ledger_seq=43,
        reason_code="FIXTURE_ACCEPT",
        authority_receipt_digest=DIGEST,
        endpoint_resolution_decision_ids=(
            "00000000-0000-4000-8000-0000000076b1",
            "00000000-0000-4000-8000-0000000076b2",
        ),
        resolved_endpoint_names=("Alice", "Bob"),
    )
    subject = CanonicalEntityRelationEndpoint(
        entity_id=CanonicalEntityId.parse("00000000-0000-4000-8000-0000000076a2"),
        entity_version_id=CanonicalEntityVersionId.parse(
            "00000000-0000-4000-8000-0000000076a3"
        ),
    )
    object_ = CanonicalEntityRelationEndpoint(
        entity_id=CanonicalEntityId.parse("00000000-0000-4000-8000-0000000076a4"),
        entity_version_id=CanonicalEntityVersionId.parse(
            "00000000-0000-4000-8000-0000000076a5"
        ),
    )
    temporal = EditorialRelationTemporalScope(
        valid_from=UtcTimestamp.parse("2026-08-24T00:00:00Z"),
        valid_until=None,
        observed_at=UtcTimestamp.parse("2026-08-24T00:00:00Z"),
    )
    assertion = SimpleNamespace(
        assertion_id="00000000-0000-4000-8000-0000000076a6",
        proposal_version_id="00000000-0000-4000-8000-0000000076a7",
        predicate=EditorialPredicateCode.SUPPORTS,
        subject=subject,
        object=object_,
        statement="Alice supports Bob",
        temporal_scope=temporal,
        uncertainty_codes=(),
        admitted_at=UtcTimestamp.parse("2026-08-24T00:00:00Z"),
    )
    retained = SimpleNamespace(
        action=EditorialRelationDecisionAction.ACCEPT,
        decision_id=decision.decision_id,
        decision_version=1,
        authority_ledger_seq=43,
        assertion_id=assertion.assertion_id,
    )
    relations = SimpleNamespace(
        decision=lambda *_args, **_kwargs: retained,
        current=lambda *_args, **_kwargs: SimpleNamespace(
            assertion=assertion,
            lifecycle=EditorialRelationAssertionLifecycle.ACTIVE,
            current_decision_id=decision.decision_id,
            current_decision_version=1,
        ),
        proposal_version=lambda *_args, **_kwargs: SimpleNamespace(version_number=1),
    )
    plan = GraphitiRelationAdmissionPlan(
        graphiti_proposal_digest=proposal.digest,
        graphiti_proposal_local_id=proposal.local_id,
        proposal_request=SimpleNamespace(proposal_id="relation-proposal"),  # type: ignore[arg-type]
        decision_request=SimpleNamespace(),  # type: ignore[arg-type]
        endpoint_resolution_proposal_ids=(),
        resolved_endpoint_names=("Alice", "Bob"),
    )
    authority = ExistingGovernedGraphitiAdmissionAuthority(
        entities=SimpleNamespace(),  # type: ignore[arg-type]
        relations=relations,  # type: ignore[arg-type]
        proof=AuthenticationProof(method="STATIC_TOKEN", credential="fixture"),
        entity_plan=lambda *_: pytest.fail("entity planner called"),
        relation_plan=lambda *_: plan,
    )

    context = authority.current_context(request, decision)

    assert context is not None
    assert context.currentness_state == "CURRENT"
    structured = context.admitted_structured_value
    assert structured["authority_kind"] == "EDITORIAL_RELATION_ASSERTION"
    assert structured["assertion"]["predicate"] == "SUPPORTS"  # type: ignore[index]
    assert structured["assertion"]["statement"] == "Alice supports Bob"  # type: ignore[index]


def test_existing_authority_rejects_unbound_graphiti_plan() -> None:
    request = _request()
    plan = _plan(request)
    unbound = GraphitiEntityAdmissionPlan(
        graphiti_proposal_digest=DIGEST,
        graphiti_proposal_local_id=plan.graphiti_proposal_local_id,
        mention_requests=plan.mention_requests,
        proposal_request=plan.proposal_request,
        decision_request=plan.decision_request,
    )
    authority = ExistingGovernedGraphitiAdmissionAuthority(
        entities=_Entities(plan),  # type: ignore[arg-type]
        relations=SimpleNamespace(),  # type: ignore[arg-type]
        proof=AuthenticationProof(method="STATIC_TOKEN", credential="fixture"),
        entity_plan=lambda *_: unbound,
        relation_plan=lambda *_: pytest.fail("relation planner called"),
    )

    with pytest.raises(GraphitiAdmissionConsumerError, match="exact Graphiti"):
        authority.decide_entity_resolution(
            request,
            required_action=None,
            idempotency_key="graphiti-admit:proposal-key",
        )


def test_required_rights_rejection_is_checked_before_authority_mutation() -> None:
    request = _request()
    plan = _plan(request)
    entities = _Entities(plan)
    authority = ExistingGovernedGraphitiAdmissionAuthority(
        entities=entities,  # type: ignore[arg-type]
        relations=SimpleNamespace(),  # type: ignore[arg-type]
        proof=AuthenticationProof(method="STATIC_TOKEN", credential="fixture"),
        entity_plan=lambda *_: plan,
        relation_plan=lambda *_: pytest.fail("relation planner called"),
    )

    with pytest.raises(GraphitiAdmissionConsumerError, match="required admission"):
        authority.decide_entity_resolution(
            request,
            required_action=GraphitiProposalAdmissionAction.REJECT,
            idempotency_key="graphiti-admit:proposal-key",
        )

    assert entities.calls == []
