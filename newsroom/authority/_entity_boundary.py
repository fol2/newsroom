from __future__ import annotations

from typing import Any, Callable

from newsroom.authority._security import _AuthorizationRequest
from newsroom.authority.auth import AuthenticationProof
from newsroom.authority.canonical import digest_canonical
from newsroom.authority.models import InlinePayload, SemanticCommand
from newsroom.authority.service import CommandService
from newsroom.authority.types import AggregateId, TrustScope, UtcTimestamp
from newsroom.entities.models import (
    CanonicalEntity,
    CanonicalEntityVersion,
    EntityAdmissionGuard,
    EntityAlias,
    EntityDependentAdmissionGuard,
    EntityMention,
    EntityMentionAdmissionRequest,
    EntityMergeDecision,
    EntityMergeDecisionRequest,
    EntityPreferredIdentity,
    EntityProjectionEvent,
    EntityResolutionDecision,
    EntityResolutionDecisionRequest,
    EntityResolutionDependency,
    EntityResolutionDependencyRequest,
    EntityResolutionProposalRequest,
    EntityResolutionProposalVersion,
    EntityReversalDecision,
    EntityReversalDecisionRequest,
    EntitySplitDecision,
    EntitySplitDecisionRequest,
)
from newsroom.entities.policy import (
    ENTITY_MENTION_ADMIT_COMMAND,
    ENTITY_MERGE_DECIDE_COMMAND,
    ENTITY_RESOLUTION_DECIDE_COMMAND,
    ENTITY_RESOLUTION_DEPENDENCY_BIND_COMMAND,
    ENTITY_RESOLUTION_PROPOSE_COMMAND,
    ENTITY_REVERSAL_DECIDE_COMMAND,
    ENTITY_SPLIT_DECIDE_COMMAND,
)
from newsroom.entities.types import (
    CanonicalEntityId,
    CanonicalEntityVersionId,
    EntityMentionId,
    EntityMergeDecisionId,
    EntityReadPolicy,
    EntityResolutionDependencyId,
    EntityResolutionProposalId,
    EntityResolutionProposalVersionId,
    EntityReversalDecisionId,
    EntitySplitDecisionId,
)
from newsroom.extraction.types import ProposalEnvelopeId

from ._entity_store import _EntityAuthorityStore
from ._entity_store_common import deterministic_decision_id


_ENTITY_READ_SCHEMA_DIGEST = digest_canonical(
    {
        "contract": "entity-authority-read-no-payload-v1",
        "payload_mode": "NO_PAYLOAD",
        "surfaces": ["PROPOSAL", "ADMITTED", "PROJECTION"],
    }
)


class _EntityBoundary:
    def __init__(
        self,
        *,
        store: _EntityAuthorityStore,
        command_service: CommandService,
        authenticator: Any,
        authorizer: Any,
        read_policy: EntityReadPolicy,
        clock: Callable[[], UtcTimestamp],
    ) -> None:
        self._store = store
        self._command_service = command_service
        self._authenticator = authenticator
        self._authorizer = authorizer
        self._read_policy = read_policy
        self._clock = clock

    def admit_mention(
        self,
        request: EntityMentionAdmissionRequest,
        proof: AuthenticationProof,
    ) -> EntityMention:
        if not isinstance(request, EntityMentionAdmissionRequest):
            raise TypeError("entity mention must be a typed request")
        command = SemanticCommand(
            command_type=ENTITY_MENTION_ADMIT_COMMAND,
            aggregate_id=AggregateId(request.mention_id.value),
            expected_aggregate_version=0,
            payload=InlinePayload(request.canonical_value()),
            idempotency_key=request.idempotency_key,
        )
        grant = self._command_service._authorize_for_commit(command, proof=proof)
        return self._store.commit_entity_mention(grant, request=request)

    def propose_resolution(
        self,
        request: EntityResolutionProposalRequest,
        proof: AuthenticationProof,
    ) -> EntityResolutionProposalVersion:
        if not isinstance(request, EntityResolutionProposalRequest):
            raise TypeError("entity resolution proposal must be typed")
        command = SemanticCommand(
            command_type=ENTITY_RESOLUTION_PROPOSE_COMMAND,
            aggregate_id=AggregateId(request.proposal_version_id.value),
            expected_aggregate_version=0,
            payload=InlinePayload(request.canonical_value()),
            idempotency_key=request.idempotency_key,
        )
        grant = self._command_service._authorize_for_commit(command, proof=proof)
        return self._store.commit_entity_resolution_proposal(grant, request=request)

    def bind_resolution_dependency(
        self,
        request: EntityResolutionDependencyRequest,
        proof: AuthenticationProof,
    ) -> EntityResolutionDependency:
        if not isinstance(request, EntityResolutionDependencyRequest):
            raise TypeError("entity resolution dependency must be typed")
        command = SemanticCommand(
            command_type=ENTITY_RESOLUTION_DEPENDENCY_BIND_COMMAND,
            aggregate_id=AggregateId(request.dependency_id.value),
            expected_aggregate_version=0,
            payload=InlinePayload(request.canonical_value()),
            idempotency_key=request.idempotency_key,
        )
        grant = self._command_service._authorize_for_commit(command, proof=proof)
        return self._store.commit_entity_resolution_dependency(
            grant, request=request
        )

    def decide_resolution(
        self,
        request: EntityResolutionDecisionRequest,
        proof: AuthenticationProof,
    ) -> EntityResolutionDecision:
        if not isinstance(request, EntityResolutionDecisionRequest):
            raise TypeError("entity resolution decision must be typed")
        decision_id = deterministic_decision_id(request)
        command = SemanticCommand(
            command_type=ENTITY_RESOLUTION_DECIDE_COMMAND,
            aggregate_id=AggregateId(decision_id.value),
            expected_aggregate_version=0,
            payload=InlinePayload(request.canonical_value()),
            idempotency_key=request.idempotency_key,
        )
        grant = self._command_service._authorize_for_commit(command, proof=proof)
        return self._store.commit_entity_resolution_decision(grant, request=request)

    def merge_entities(
        self,
        request: EntityMergeDecisionRequest,
        proof: AuthenticationProof,
    ) -> EntityMergeDecision:
        if not isinstance(request, EntityMergeDecisionRequest):
            raise TypeError("entity merge decision must be typed")
        command = SemanticCommand(
            command_type=ENTITY_MERGE_DECIDE_COMMAND,
            aggregate_id=AggregateId(request.merge_decision_id.value),
            expected_aggregate_version=0,
            payload=InlinePayload(request.canonical_value()),
            idempotency_key=request.idempotency_key,
        )
        grant = self._command_service._authorize_for_commit(command, proof=proof)
        return self._store.commit_entity_merge(grant, request=request)

    def split_entity(
        self,
        request: EntitySplitDecisionRequest,
        proof: AuthenticationProof,
    ) -> EntitySplitDecision:
        if not isinstance(request, EntitySplitDecisionRequest):
            raise TypeError("entity split decision must be typed")
        command = SemanticCommand(
            command_type=ENTITY_SPLIT_DECIDE_COMMAND,
            aggregate_id=AggregateId(request.split_decision_id.value),
            expected_aggregate_version=0,
            payload=InlinePayload(request.canonical_value()),
            idempotency_key=request.idempotency_key,
        )
        grant = self._command_service._authorize_for_commit(command, proof=proof)
        return self._store.commit_entity_split(grant, request=request)

    def reverse_lineage(
        self,
        request: EntityReversalDecisionRequest,
        proof: AuthenticationProof,
    ) -> EntityReversalDecision:
        if not isinstance(request, EntityReversalDecisionRequest):
            raise TypeError("entity reversal decision must be typed")
        command = SemanticCommand(
            command_type=ENTITY_REVERSAL_DECIDE_COMMAND,
            aggregate_id=AggregateId(request.reversal_decision_id.value),
            expected_aggregate_version=0,
            payload=InlinePayload(request.canonical_value()),
            idempotency_key=request.idempotency_key,
        )
        grant = self._command_service._authorize_for_commit(command, proof=proof)
        return self._store.commit_entity_reversal(grant, request=request)

    def _authorize_read(
        self,
        proof: AuthenticationProof,
        *,
        operation: str,
        aggregate_type: str,
        aggregate_id: str,
        required_scope: str,
        trust_scope: TrustScope,
        limit: int | None = None,
    ) -> None:
        now = self._clock()
        authentication = self._authenticator.authenticate(proof, now=now)
        authentication.require_current(now)
        self._read_policy.require_principal(authentication.principal_id)
        if limit is not None:
            self._read_policy.require_limit(limit)
        stable = digest_canonical(
            {
                "contract": "entity-authority-read-v1",
                "policy_digest": self._read_policy.digest,
                "operation": operation,
                "aggregate_type": aggregate_type,
                "aggregate_id": aggregate_id,
                "required_scope": required_scope,
                "trust_scope": trust_scope.value,
                "limit": limit,
            }
        )
        unsigned = {
            "authentication_context_id": str(authentication.authentication_context_id),
            "principal_id": authentication.principal_id,
            "authority_domain": authentication.authority_domain,
            "operation_type": operation,
            "required_scope": required_scope,
            "stable_semantic_request_digest": stable,
            "command_definition_digest": _ENTITY_READ_SCHEMA_DIGEST,
            "aggregate_type": aggregate_type,
            "aggregate_id": aggregate_id,
            "event_type": "entity.authority.read",
            "event_schema_version": 1,
            "payload_mode": "NO_PAYLOAD",
            "payload_schema_version": "entity_authority_read_v1",
            "payload_schema_contract_version": "entity-authority-read-no-payload-v1",
            "payload_schema_contract_digest": _ENTITY_READ_SCHEMA_DIGEST,
            "payload_canonicalizer_version": "entity-authority-none-v1",
            "trust_scope": trust_scope.value,
            "security_scope": "authority.entity",
            "retention_scope": "authority.audit",
            "object_class": None,
            "allowed_use": None,
        }
        request = _AuthorizationRequest(
            authentication_context_id=authentication.authentication_context_id,
            principal_id=authentication.principal_id,
            authority_domain=authentication.authority_domain,
            operation_type=operation,
            required_scope=required_scope,
            stable_semantic_request_digest=stable,
            command_definition_digest=_ENTITY_READ_SCHEMA_DIGEST,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type="entity.authority.read",
            event_schema_version=1,
            payload_mode="NO_PAYLOAD",
            payload_schema_version="entity_authority_read_v1",
            payload_schema_contract_version="entity-authority-read-no-payload-v1",
            payload_schema_contract_digest=_ENTITY_READ_SCHEMA_DIGEST,
            payload_canonicalizer_version="entity-authority-none-v1",
            trust_scope=trust_scope.value,
            security_scope="authority.entity",
            retention_scope="authority.audit",
            object_class=None,
            allowed_use=None,
            request_digest=digest_canonical(unsigned),
        )
        decision = self._authorizer.authorize(authentication, request, now=now)
        if (
            decision.authentication_context_id
            != authentication.authentication_context_id
            or decision.authorization_request_digest != request.request_digest
        ):
            raise PermissionError("entity read authorization provenance differs")
        decision.require_allowed()

    def mention(self, mention_id: EntityMentionId, proof: AuthenticationProof) -> EntityMention:
        self._authorize_read(
            proof,
            operation="read:entity:mention",
            aggregate_type="entity_mention",
            aggregate_id=str(mention_id),
            required_scope=self._read_policy.proposal_required_scope,
            trust_scope=TrustScope.PROPOSED,
        )
        return self._store.mention(mention_id)

    def proposal(
        self,
        proposal_id: EntityResolutionProposalId,
        proof: AuthenticationProof,
    ) -> EntityResolutionProposalVersion:
        self._authorize_read(
            proof,
            operation="read:entity:resolution_proposal",
            aggregate_type="entity_resolution_proposal",
            aggregate_id=str(proposal_id),
            required_scope=self._read_policy.proposal_required_scope,
            trust_scope=TrustScope.PROPOSED,
        )
        return self._store.proposal_current(proposal_id)

    def proposal_version(
        self,
        proposal_version_id: EntityResolutionProposalVersionId,
        proof: AuthenticationProof,
    ) -> EntityResolutionProposalVersion:
        self._authorize_read(
            proof,
            operation="read:entity:resolution_proposal_version",
            aggregate_type="entity_resolution_proposal_version",
            aggregate_id=str(proposal_version_id),
            required_scope=self._read_policy.proposal_required_scope,
            trust_scope=TrustScope.PROPOSED,
        )
        return self._store.proposal_version(proposal_version_id)

    def decision(
        self,
        proposal_id: EntityResolutionProposalId,
        proof: AuthenticationProof,
    ) -> EntityResolutionDecision | None:
        self._authorize_read(
            proof,
            operation="read:entity:resolution_decision",
            aggregate_type="entity_resolution_proposal",
            aggregate_id=str(proposal_id),
            required_scope=self._read_policy.proposal_required_scope,
            trust_scope=TrustScope.PROPOSED,
        )
        return self._store.decision_current(proposal_id)

    def entity(self, entity_id: CanonicalEntityId, proof: AuthenticationProof) -> CanonicalEntity:
        self._authorize_read(
            proof,
            operation="read:entity:canonical_entity",
            aggregate_type="canonical_entity",
            aggregate_id=str(entity_id),
            required_scope=self._read_policy.admitted_required_scope,
            trust_scope=TrustScope.ADMITTED,
        )
        return self._store.entity(entity_id)

    def entity_version(
        self,
        entity_version_id: CanonicalEntityVersionId,
        proof: AuthenticationProof,
    ) -> CanonicalEntityVersion:
        self._authorize_read(
            proof,
            operation="read:entity:canonical_entity_version",
            aggregate_type="canonical_entity_version",
            aggregate_id=str(entity_version_id),
            required_scope=self._read_policy.admitted_required_scope,
            trust_scope=TrustScope.ADMITTED,
        )
        return self._store.entity_version(entity_version_id)

    def aliases(
        self,
        entity_id: CanonicalEntityId,
        limit: int,
        proof: AuthenticationProof,
    ) -> tuple[EntityAlias, ...]:
        self._authorize_read(
            proof,
            operation="read:entity:aliases",
            aggregate_type="canonical_entity",
            aggregate_id=str(entity_id),
            required_scope=self._read_policy.admitted_required_scope,
            trust_scope=TrustScope.ADMITTED,
            limit=limit,
        )
        return self._store.aliases(entity_id, limit=limit)

    def preferred(
        self,
        entity_id: CanonicalEntityId,
        proof: AuthenticationProof,
    ) -> EntityPreferredIdentity:
        self._authorize_read(
            proof,
            operation="read:entity:preferred_identity",
            aggregate_type="canonical_entity",
            aggregate_id=str(entity_id),
            required_scope=self._read_policy.projection_required_scope,
            trust_scope=TrustScope.ADMITTED,
        )
        return self._store.preferred_identity(entity_id)

    def projection_events_after(
        self,
        after_ledger_seq: int,
        limit: int,
        proof: AuthenticationProof,
    ) -> tuple[EntityProjectionEvent, ...]:
        self._read_policy.require_limit(limit)
        if (
            isinstance(after_ledger_seq, bool)
            or not isinstance(after_ledger_seq, int)
            or after_ledger_seq < 0
        ):
            raise ValueError("entity projection event cutoff must be non-negative")
        self._authorize_read(
            proof,
            operation="read:entity:projection_events",
            aggregate_type="entity_projection_event_stream",
            aggregate_id=self._read_policy.policy_id,
            required_scope=self._read_policy.projection_required_scope,
            trust_scope=TrustScope.ADMITTED,
            limit=limit,
        )
        return self._store.projection_events_after(
            after_ledger_seq=after_ledger_seq, limit=limit
        )

    def merge_decision(
        self,
        decision_id: EntityMergeDecisionId,
        proof: AuthenticationProof,
    ) -> EntityMergeDecision:
        self._authorize_read(
            proof,
            operation="read:entity:merge_decision",
            aggregate_type="entity_merge_decision",
            aggregate_id=str(decision_id),
            required_scope=self._read_policy.admitted_required_scope,
            trust_scope=TrustScope.ADMITTED,
        )
        return self._store.merge_decision(decision_id)

    def split_decision(
        self,
        decision_id: EntitySplitDecisionId,
        proof: AuthenticationProof,
    ) -> EntitySplitDecision:
        self._authorize_read(
            proof,
            operation="read:entity:split_decision",
            aggregate_type="entity_split_decision",
            aggregate_id=str(decision_id),
            required_scope=self._read_policy.admitted_required_scope,
            trust_scope=TrustScope.ADMITTED,
        )
        return self._store.split_decision(decision_id)

    def reversal_decision(
        self,
        decision_id: EntityReversalDecisionId,
        proof: AuthenticationProof,
    ) -> EntityReversalDecision:
        self._authorize_read(
            proof,
            operation="read:entity:reversal_decision",
            aggregate_type="entity_reversal_decision",
            aggregate_id=str(decision_id),
            required_scope=self._read_policy.admitted_required_scope,
            trust_scope=TrustScope.ADMITTED,
        )
        return self._store.reversal_decision(decision_id)

    def dependency(
        self,
        dependency_id: EntityResolutionDependencyId,
        proof: AuthenticationProof,
    ) -> EntityResolutionDependency:
        self._authorize_read(
            proof,
            operation="read:entity:resolution_dependency",
            aggregate_type="entity_resolution_dependency",
            aggregate_id=str(dependency_id),
            required_scope=self._read_policy.proposal_required_scope,
            trust_scope=TrustScope.PROPOSED,
        )
        return self._store.dependency(dependency_id)

    def dependent_admission_guard(
        self,
        dependent_proposal_id: ProposalEnvelopeId,
        proof: AuthenticationProof,
    ) -> EntityDependentAdmissionGuard:
        self._authorize_read(
            proof,
            operation="read:entity:dependent_admission_guard",
            aggregate_type="extraction_proposal",
            aggregate_id=str(dependent_proposal_id),
            required_scope=self._read_policy.admitted_required_scope,
            trust_scope=TrustScope.ADMITTED,
        )
        return self._store.dependent_admission_guard(dependent_proposal_id)

    def admission_guard(
        self,
        proposal_id: EntityResolutionProposalId,
        proof: AuthenticationProof,
    ) -> EntityAdmissionGuard:
        self._authorize_read(
            proof,
            operation="read:entity:admission_guard",
            aggregate_type="entity_resolution_proposal",
            aggregate_id=str(proposal_id),
            required_scope=self._read_policy.admitted_required_scope,
            trust_scope=TrustScope.ADMITTED,
        )
        return self._store.admission_guard(proposal_id)


__all__ = ["_EntityBoundary"]
