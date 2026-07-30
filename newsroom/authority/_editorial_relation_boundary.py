from __future__ import annotations

from typing import Any, Callable

from newsroom.authority._security import _AuthorizationRequest
from newsroom.authority.auth import AuthenticationProof
from newsroom.authority.canonical import digest_canonical
from newsroom.authority.models import InlinePayload, SemanticCommand
from newsroom.authority.service import CommandService
from newsroom.authority.types import AggregateId, TrustScope, UtcTimestamp
from newsroom.relations.editorial_models import (
    EditorialRelationAssertion,
    EditorialRelationCurrentView,
    EditorialRelationDecision,
    EditorialRelationDecisionRequest,
    EditorialRelationProjectionEvent,
    EditorialRelationProposalRequest,
    EditorialRelationProposalVersion,
    EditorialRelationReadPolicy,
)
from newsroom.relations.editorial_policy import (
    EDITORIAL_RELATION_DECISION_COMMAND,
    EDITORIAL_RELATION_PROPOSAL_COMMAND,
)
from newsroom.relations.editorial_types import (
    EditorialRelationAssertionId,
    EditorialRelationProposalId,
    EditorialRelationProposalVersionId,
)

from ._editorial_relation_store import _EditorialRelationAuthorityStore


_EDITORIAL_RELATION_READ_SCHEMA_DIGEST = digest_canonical(
    {
        "contract": "editorial-relation-authority-read-no-payload-v1",
        "payload_mode": "NO_PAYLOAD",
        "surfaces": ["PROPOSAL", "ADMITTED", "PROJECTION"],
    }
)


class _EditorialRelationBoundary:
    def __init__(
        self,
        *,
        store: _EditorialRelationAuthorityStore,
        command_service: CommandService,
        authenticator: Any,
        authorizer: Any,
        read_policy: EditorialRelationReadPolicy,
        clock: Callable[[], UtcTimestamp],
    ) -> None:
        self._store = store
        self._command_service = command_service
        self._authenticator = authenticator
        self._authorizer = authorizer
        self._read_policy = read_policy
        self._clock = clock

    def propose(
        self,
        request: EditorialRelationProposalRequest,
        proof: AuthenticationProof,
    ) -> EditorialRelationProposalVersion:
        if not isinstance(request, EditorialRelationProposalRequest):
            raise TypeError("editorial relation proposal must be a typed request")
        command = SemanticCommand(
            command_type=EDITORIAL_RELATION_PROPOSAL_COMMAND,
            aggregate_id=AggregateId(request.proposal_version_id.value),
            expected_aggregate_version=0,
            payload=InlinePayload(request.canonical_value()),
            idempotency_key=request.idempotency_key,
        )
        grant = self._command_service._authorize_for_commit(command, proof=proof)
        return self._store.commit_editorial_relation_proposal(
            grant, request=request
        )

    def decide(
        self,
        request: EditorialRelationDecisionRequest,
        proof: AuthenticationProof,
    ) -> EditorialRelationDecision:
        if not isinstance(request, EditorialRelationDecisionRequest):
            raise TypeError("editorial relation decision must be a typed request")
        command = SemanticCommand(
            command_type=EDITORIAL_RELATION_DECISION_COMMAND,
            aggregate_id=AggregateId(request.decision_id.value),
            expected_aggregate_version=0,
            payload=InlinePayload(request.canonical_value()),
            idempotency_key=request.idempotency_key,
        )
        grant = self._command_service._authorize_for_commit(command, proof=proof)
        return self._store.commit_editorial_relation_decision(
            grant, request=request
        )

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
                "contract": "editorial-relation-authority-read-v1",
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
            "authentication_context_id": str(
                authentication.authentication_context_id
            ),
            "principal_id": authentication.principal_id,
            "authority_domain": authentication.authority_domain,
            "operation_type": operation,
            "required_scope": required_scope,
            "stable_semantic_request_digest": stable,
            "command_definition_digest": _EDITORIAL_RELATION_READ_SCHEMA_DIGEST,
            "aggregate_type": aggregate_type,
            "aggregate_id": aggregate_id,
            "event_type": "editorial.relation.authority.read",
            "event_schema_version": 1,
            "payload_mode": "NO_PAYLOAD",
            "payload_schema_version": "editorial_relation_authority_read_v1",
            "payload_schema_contract_version": (
                "editorial-relation-authority-read-no-payload-v1"
            ),
            "payload_schema_contract_digest": (
                _EDITORIAL_RELATION_READ_SCHEMA_DIGEST
            ),
            "payload_canonicalizer_version": (
                "editorial-relation-authority-none-v1"
            ),
            "trust_scope": trust_scope.value,
            "security_scope": "authority.relation",
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
            command_definition_digest=_EDITORIAL_RELATION_READ_SCHEMA_DIGEST,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type="editorial.relation.authority.read",
            event_schema_version=1,
            payload_mode="NO_PAYLOAD",
            payload_schema_version="editorial_relation_authority_read_v1",
            payload_schema_contract_version=(
                "editorial-relation-authority-read-no-payload-v1"
            ),
            payload_schema_contract_digest=_EDITORIAL_RELATION_READ_SCHEMA_DIGEST,
            payload_canonicalizer_version="editorial-relation-authority-none-v1",
            trust_scope=trust_scope.value,
            security_scope="authority.relation",
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
            raise PermissionError(
                "editorial relation read authorization provenance differs"
            )
        decision.require_allowed()

    def proposal(
        self,
        proposal_id: EditorialRelationProposalId,
        proof: AuthenticationProof,
    ) -> EditorialRelationProposalVersion:
        self._authorize_read(
            proof,
            operation="read:editorial_relation:proposal",
            aggregate_type="editorial_relation_proposal",
            aggregate_id=str(proposal_id),
            required_scope=self._read_policy.proposal_required_scope,
            trust_scope=TrustScope.PROPOSED,
        )
        return self._store.editorial_proposal_current(proposal_id)

    def proposal_version(
        self,
        proposal_version_id: EditorialRelationProposalVersionId,
        proof: AuthenticationProof,
    ) -> EditorialRelationProposalVersion:
        self._authorize_read(
            proof,
            operation="read:editorial_relation:proposal_version",
            aggregate_type="editorial_relation_proposal_version",
            aggregate_id=str(proposal_version_id),
            required_scope=self._read_policy.proposal_required_scope,
            trust_scope=TrustScope.PROPOSED,
        )
        return self._store.editorial_proposal_version(proposal_version_id)

    def decision(
        self,
        proposal_id: EditorialRelationProposalId,
        proof: AuthenticationProof,
    ) -> EditorialRelationDecision | None:
        self._authorize_read(
            proof,
            operation="read:editorial_relation:decision",
            aggregate_type="editorial_relation_proposal",
            aggregate_id=str(proposal_id),
            required_scope=self._read_policy.proposal_required_scope,
            trust_scope=TrustScope.PROPOSED,
        )
        return self._store.editorial_decision_current(proposal_id)

    def assertion(
        self,
        assertion_id: EditorialRelationAssertionId,
        proof: AuthenticationProof,
    ) -> EditorialRelationAssertion:
        self._authorize_read(
            proof,
            operation="read:editorial_relation:assertion",
            aggregate_type="editorial_relation_assertion",
            aggregate_id=str(assertion_id),
            required_scope=self._read_policy.admitted_required_scope,
            trust_scope=TrustScope.ADMITTED,
        )
        return self._store.editorial_assertion(assertion_id)

    def current(
        self,
        assertion_id: EditorialRelationAssertionId,
        proof: AuthenticationProof,
    ) -> EditorialRelationCurrentView:
        self._authorize_read(
            proof,
            operation="read:editorial_relation:current",
            aggregate_type="editorial_relation_assertion",
            aggregate_id=str(assertion_id),
            required_scope=self._read_policy.admitted_required_scope,
            trust_scope=TrustScope.ADMITTED,
        )
        return self._store.editorial_current(assertion_id)

    def current_relations(
        self,
        limit: int,
        proof: AuthenticationProof,
    ) -> tuple[EditorialRelationCurrentView, ...]:
        self._authorize_read(
            proof,
            operation="read:editorial_relation:current_list",
            aggregate_type="editorial_relation_current_view",
            aggregate_id=self._read_policy.policy_id,
            required_scope=self._read_policy.admitted_required_scope,
            trust_scope=TrustScope.ADMITTED,
            limit=limit,
        )
        return self._store.editorial_current_relations(limit=limit)

    def projection_events_after(
        self,
        after_ledger_seq: int,
        limit: int,
        proof: AuthenticationProof,
    ) -> tuple[EditorialRelationProjectionEvent, ...]:
        if (
            isinstance(after_ledger_seq, bool)
            or not isinstance(after_ledger_seq, int)
            or after_ledger_seq < 0
        ):
            raise ValueError(
                "editorial relation projection cutoff must be non-negative"
            )
        self._authorize_read(
            proof,
            operation="read:editorial_relation:projection_events",
            aggregate_type="editorial_relation_projection_event_stream",
            aggregate_id=self._read_policy.policy_id,
            required_scope=self._read_policy.projection_required_scope,
            trust_scope=TrustScope.ADMITTED,
            limit=limit,
        )
        return self._store.editorial_projection_events_after(
            after_ledger_seq=after_ledger_seq,
            limit=limit,
        )


__all__ = ["_EditorialRelationBoundary"]
