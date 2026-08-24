from __future__ import annotations

from types import SimpleNamespace

import pytest

from newsroom.authority.auth import AuthenticationProof
from newsroom.authority.canonical import digest_canonical
from newsroom.authority.types import EventId, UtcTimestamp
from newsroom.control_plane.graphiti_admission import (
    GraphitiAdmissionConsumerError,
    GraphitiAdmissionRequest,
)
from newsroom.control_plane.graphiti_admission_integration import (
    ExistingGovernedGraphitiAdmissionAuthority,
    GraphitiEntityAdmissionPlan,
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
)
from newsroom.graphiti_adapter.admission import GraphitiProposalAdmissionAction


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
            alias_id=EntityAliasId.parse(
                "00000000-0000-4000-8000-000000007608"
            ),
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
        return EntityResolutionDecision(
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
            authority_event_id=EventId.parse(
                "00000000-0000-4000-8000-000000007610"
            ),
            authority_ledger_seq=42,
            recorded_at=UtcTimestamp.parse("2026-08-24T00:00:00Z"),
        )


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
