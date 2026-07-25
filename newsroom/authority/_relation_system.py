from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ._capability import _CapabilityIssuer
from ._event_system import _ReadBoundary
from ._relation_store import _RelationAuthorityStore
from ._security import _AuthorizationRequest
from .auth import AuthenticationProof
from .canonical import digest_canonical
from .models import InlinePayload, SemanticCommand
from .persistence import AuthorityEvents, EventReadPolicy
from .policy import CommandRegistry, PayloadSchemaRegistry
from .service import CommandService
from .types import AggregateId, UtcTimestamp
from newsroom.relations.models import (
    IntegratedFixtureV2Binding,
    IntegratedFixtureV2BindingId,
    IntegratedFixtureV2BindingRequest,
    RelationAdmissionDecision,
    RelationAdmissionDecisionId,
    RelationAssertion,
    RelationDecisionRequest,
    RelationDecisionResult,
    RelationProjectionEvent,
    RelationProposal,
    RelationProposalId,
    RelationProposalRequest,
    RelationReadPolicy,
)
from newsroom.relations.policy import (
    INTEGRATED_FIXTURE_V2_BIND_COMMAND,
    RELATION_DECISION_COMMAND,
    RELATION_PROPOSAL_COMMAND,
    merge_relation_authority_registries,
)


_RELATION_READ_SCHEMA_DIGEST = digest_canonical(
    {
        "contract": "governed-relation-read-no-payload-v1",
        "payload_mode": "NO_PAYLOAD",
        "golden_vectors": [{"name": "empty", "size": 0}],
    }
)


class GovernedRelations:
    """Typed relation authority facade; private SQLite writers never escape."""

    __slots__ = (
        "__bind_fixture",
        "__propose",
        "__decide",
        "__fixture_binding",
        "__proposal",
        "__decision",
        "__admitted",
        "__projection_events_after",
    )

    def __init__(
        self,
        *,
        bind_fixture: Callable[
            [IntegratedFixtureV2BindingRequest, AuthenticationProof],
            IntegratedFixtureV2Binding,
        ],
        propose: Callable[
            [RelationProposalRequest, AuthenticationProof], RelationProposal
        ],
        decide: Callable[
            [RelationDecisionRequest, AuthenticationProof], RelationDecisionResult
        ],
        fixture_binding: Callable[
            [IntegratedFixtureV2BindingId, AuthenticationProof],
            IntegratedFixtureV2Binding,
        ],
        proposal: Callable[
            [RelationProposalId, AuthenticationProof], RelationProposal
        ],
        decision: Callable[
            [RelationAdmissionDecisionId, AuthenticationProof],
            RelationAdmissionDecision,
        ],
        admitted: Callable[
            [UtcTimestamp, int, AuthenticationProof], tuple[RelationAssertion, ...]
        ],
        projection_events_after: Callable[
            [int, UtcTimestamp, int, AuthenticationProof],
            tuple[RelationProjectionEvent, ...],
        ],
    ) -> None:
        self.__bind_fixture = bind_fixture
        self.__propose = propose
        self.__decide = decide
        self.__fixture_binding = fixture_binding
        self.__proposal = proposal
        self.__decision = decision
        self.__admitted = admitted
        self.__projection_events_after = projection_events_after

    def bind_fixture(
        self,
        request: IntegratedFixtureV2BindingRequest,
        *,
        proof: AuthenticationProof,
    ) -> IntegratedFixtureV2Binding:
        return self.__bind_fixture(request, proof)

    def propose(
        self,
        request: RelationProposalRequest,
        *,
        proof: AuthenticationProof,
    ) -> RelationProposal:
        return self.__propose(request, proof)

    def decide(
        self,
        request: RelationDecisionRequest,
        *,
        proof: AuthenticationProof,
    ) -> RelationDecisionResult:
        return self.__decide(request, proof)

    def fixture_binding(
        self,
        binding_id: IntegratedFixtureV2BindingId,
        *,
        proof: AuthenticationProof,
    ) -> IntegratedFixtureV2Binding:
        return self.__fixture_binding(binding_id, proof)

    def proposal(
        self,
        proposal_id: RelationProposalId,
        *,
        proof: AuthenticationProof,
    ) -> RelationProposal:
        return self.__proposal(proposal_id, proof)

    def decision(
        self,
        decision_id: RelationAdmissionDecisionId,
        *,
        proof: AuthenticationProof,
    ) -> RelationAdmissionDecision:
        return self.__decision(decision_id, proof)

    def admitted(
        self,
        *,
        valid_at: UtcTimestamp,
        limit: int = 100,
        proof: AuthenticationProof,
    ) -> tuple[RelationAssertion, ...]:
        return self.__admitted(valid_at, limit, proof)

    def projection_events_after(
        self,
        after_ledger_seq: int,
        *,
        valid_at: UtcTimestamp,
        limit: int = 1000,
        proof: AuthenticationProof,
    ) -> tuple[RelationProjectionEvent, ...]:
        return self.__projection_events_after(
            after_ledger_seq, valid_at, limit, proof
        )


class GovernedRelationAuthoritySystem:
    """Composed governed relation facades with no raw mutation surface."""

    __slots__ = ("events", "relations", "__close")

    def __init__(
        self,
        *,
        events: AuthorityEvents,
        relations: GovernedRelations,
        close: Callable[[], None],
    ) -> None:
        self.events = events
        self.relations = relations
        self.__close = close

    def close(self) -> None:
        self.__close()

    def __enter__(self) -> GovernedRelationAuthoritySystem:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


class _RelationBoundary:
    def __init__(
        self,
        *,
        store: _RelationAuthorityStore,
        command_service: CommandService,
        authenticator: Any,
        authorizer: Any,
        read_policy: RelationReadPolicy,
        clock: Callable[[], UtcTimestamp],
    ) -> None:
        self._store = store
        self._command_service = command_service
        self._authenticator = authenticator
        self._authorizer = authorizer
        self._read_policy = read_policy
        self._clock = clock

    def _grant(
        self,
        *,
        command_type: str,
        aggregate_id: AggregateId,
        expected_version: int,
        payload: dict[str, object],
        idempotency_key: str,
        proof: AuthenticationProof,
    ):
        command = SemanticCommand(
            command_type=command_type,
            aggregate_id=aggregate_id,
            expected_aggregate_version=expected_version,
            payload=InlinePayload(payload),
            idempotency_key=idempotency_key,
        )
        return self._command_service._authorize_for_commit(command, proof=proof)

    def bind_fixture(
        self,
        request: IntegratedFixtureV2BindingRequest,
        proof: AuthenticationProof,
    ) -> IntegratedFixtureV2Binding:
        if not isinstance(request, IntegratedFixtureV2BindingRequest):
            raise TypeError("fixture binding requires a typed request")
        grant = self._grant(
            command_type=INTEGRATED_FIXTURE_V2_BIND_COMMAND,
            aggregate_id=AggregateId(request.binding_id.value),
            expected_version=0,
            payload=request.canonical_value(),
            idempotency_key=request.idempotency_key,
            proof=proof,
        )
        return self._store.commit_fixture_binding(grant, request)

    def propose(
        self,
        request: RelationProposalRequest,
        proof: AuthenticationProof,
    ) -> RelationProposal:
        if not isinstance(request, RelationProposalRequest):
            raise TypeError("relation proposal requires a typed request")
        grant = self._grant(
            command_type=RELATION_PROPOSAL_COMMAND,
            aggregate_id=AggregateId(request.proposal_id.value),
            expected_version=0,
            payload=request.canonical_value(),
            idempotency_key=request.idempotency_key,
            proof=proof,
        )
        return self._store.commit_relation_proposal(grant, request)

    def decide(
        self,
        request: RelationDecisionRequest,
        proof: AuthenticationProof,
    ) -> RelationDecisionResult:
        if not isinstance(request, RelationDecisionRequest):
            raise TypeError("relation decision requires a typed request")
        grant = self._grant(
            command_type=RELATION_DECISION_COMMAND,
            aggregate_id=AggregateId(request.proposal_id.value),
            expected_version=request.expected_decision_version,
            payload=request.canonical_value(),
            idempotency_key=request.idempotency_key,
            proof=proof,
        )
        return self._store.commit_relation_decision(grant, request)

    def _authenticate_read(
        self, proof: AuthenticationProof
    ) -> tuple[UtcTimestamp, Any]:
        now = self._clock()
        authentication = self._authenticator.authenticate(proof, now=now)
        authentication.require_current(now)
        self._read_policy.require_principal(authentication.principal_id)
        return now, authentication

    def _authorize_read(
        self,
        *,
        operation: str,
        aggregate_id: str,
        trust_scope: str,
        semantic_value: dict[str, object],
        proof: AuthenticationProof,
    ) -> None:
        now, authentication = self._authenticate_read(proof)
        stable_digest = digest_canonical(
            {
                "relation_read_policy_digest": self._read_policy.digest,
                "operation": operation,
                "semantic_value": semantic_value,
            }
        )
        operation_type = f"read:{self._read_policy.purpose}:{operation}"
        unsigned = {
            "authentication_context_id": str(
                authentication.authentication_context_id
            ),
            "principal_id": authentication.principal_id,
            "authority_domain": authentication.authority_domain,
            "operation_type": operation_type,
            "required_scope": self._read_policy.required_scope,
            "stable_semantic_request_digest": stable_digest,
            "command_definition_digest": self._read_policy.digest,
            "aggregate_type": "governed_relation_metadata",
            "aggregate_id": aggregate_id,
            "event_type": "relation.metadata.read",
            "event_schema_version": 1,
            "payload_mode": "NO_PAYLOAD",
            "payload_schema_version": "governed_relation_read_v1",
            "payload_schema_contract_version": (
                "governed-relation-read-contract-v1"
            ),
            "payload_schema_contract_digest": _RELATION_READ_SCHEMA_DIGEST,
            "payload_canonicalizer_version": "governed-relation-read-none-v1",
            "trust_scope": trust_scope,
            "security_scope": "authority.relation",
            "retention_scope": "authority.audit",
            "object_class": None,
            "allowed_use": None,
        }
        request = _AuthorizationRequest(
            authentication_context_id=authentication.authentication_context_id,
            principal_id=authentication.principal_id,
            authority_domain=authentication.authority_domain,
            operation_type=operation_type,
            required_scope=self._read_policy.required_scope,
            stable_semantic_request_digest=stable_digest,
            command_definition_digest=self._read_policy.digest,
            aggregate_type="governed_relation_metadata",
            aggregate_id=aggregate_id,
            event_type="relation.metadata.read",
            event_schema_version=1,
            payload_mode="NO_PAYLOAD",
            payload_schema_version="governed_relation_read_v1",
            payload_schema_contract_version=(
                "governed-relation-read-contract-v1"
            ),
            payload_schema_contract_digest=_RELATION_READ_SCHEMA_DIGEST,
            payload_canonicalizer_version="governed-relation-read-none-v1",
            trust_scope=trust_scope,
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
        ):
            raise PermissionError("relation read authorization context mismatch")
        if decision.authorization_request_digest != request.request_digest:
            raise PermissionError("relation read authorization request mismatch")
        decision.require_allowed()

    def fixture_binding(
        self,
        binding_id: IntegratedFixtureV2BindingId,
        proof: AuthenticationProof,
    ) -> IntegratedFixtureV2Binding:
        if not isinstance(binding_id, IntegratedFixtureV2BindingId):
            raise TypeError("fixture binding identity must be typed")
        self._authorize_read(
            operation="fixture-binding",
            aggregate_id=str(binding_id),
            trust_scope="OBSERVED",
            semantic_value={"binding_id": str(binding_id)},
            proof=proof,
        )
        return self._store.fixture_binding(binding_id)

    def proposal(
        self,
        proposal_id: RelationProposalId,
        proof: AuthenticationProof,
    ) -> RelationProposal:
        if not isinstance(proposal_id, RelationProposalId):
            raise TypeError("relation proposal identity must be typed")
        self._authorize_read(
            operation="proposal",
            aggregate_id=str(proposal_id),
            trust_scope="PROPOSED",
            semantic_value={"proposal_id": str(proposal_id)},
            proof=proof,
        )
        return self._store.relation_proposal(proposal_id)

    def decision(
        self,
        decision_id: RelationAdmissionDecisionId,
        proof: AuthenticationProof,
    ) -> RelationAdmissionDecision:
        if not isinstance(decision_id, RelationAdmissionDecisionId):
            raise TypeError("relation decision identity must be typed")
        self._authorize_read(
            operation="decision",
            aggregate_id=str(decision_id),
            trust_scope="ADMITTED",
            semantic_value={"decision_id": str(decision_id)},
            proof=proof,
        )
        return self._store.relation_decision(decision_id)

    def admitted(
        self,
        valid_at: UtcTimestamp,
        limit: int,
        proof: AuthenticationProof,
    ) -> tuple[RelationAssertion, ...]:
        self._read_policy.require_limit(limit)
        if not isinstance(valid_at, UtcTimestamp):
            raise TypeError("admitted relation read time must be typed")
        self._authorize_read(
            operation="admitted-assertions",
            aggregate_id=self._read_policy.policy_id,
            trust_scope="ADMITTED",
            semantic_value={
                "valid_at": valid_at.to_text(),
                "limit": limit,
            },
            proof=proof,
        )
        return self._store.admitted_assertions(now=valid_at, limit=limit)

    def projection_events_after(
        self,
        after_ledger_seq: int,
        valid_at: UtcTimestamp,
        limit: int,
        proof: AuthenticationProof,
    ) -> tuple[RelationProjectionEvent, ...]:
        self._read_policy.require_limit(limit)
        if (
            isinstance(after_ledger_seq, bool)
            or not isinstance(after_ledger_seq, int)
            or after_ledger_seq < 0
        ):
            raise ValueError("projection event cutoff must be non-negative")
        if not isinstance(valid_at, UtcTimestamp):
            raise TypeError("projection event read time must be typed")
        self._authorize_read(
            operation="projection-events",
            aggregate_id=self._read_policy.policy_id,
            trust_scope="ADMITTED",
            semantic_value={
                "after_ledger_seq": after_ledger_seq,
                "valid_at": valid_at.to_text(),
                "limit": limit,
            },
            proof=proof,
        )
        return self._store.projection_events_after(
            after_ledger_seq=after_ledger_seq,
            now=valid_at,
            limit=limit,
        )


def open_governed_relation_authority_system(
    *,
    path: Path,
    registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
    authenticator: Any,
    authorizer: Any,
    event_read_policy: EventReadPolicy,
    relation_read_policy: RelationReadPolicy,
    command_service_version: str = "authority-command-v1",
    busy_timeout_ms: int = 5_000,
    clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
) -> GovernedRelationAuthoritySystem:
    """Open authenticated SQLite relation authority for Increment 2A only."""

    merged_registry, merged_schemas = merge_relation_authority_registries(
        command_registry=registry,
        payload_schemas=payload_schemas,
    )
    issuer = _CapabilityIssuer(
        command_registry=merged_registry,
        payload_schemas=merged_schemas,
    )
    store: _RelationAuthorityStore | None = None
    try:
        store = _RelationAuthorityStore(
            path,
            issuer=issuer,
            command_registry=merged_registry,
            payload_schemas=merged_schemas,
            command_service_version=command_service_version,
            busy_timeout_ms=busy_timeout_ms,
            clock=clock,
        )
        command_service = CommandService(
            registry=merged_registry,
            payload_schemas=merged_schemas,
            authenticator=authenticator,
            authorizer=authorizer,
            committed_lookup=store,
            clock=clock,
            _issuer=issuer,
        )
        event_boundary = _ReadBoundary(
            store=store,
            policy=event_read_policy,
            authenticator=authenticator,
            authorizer=authorizer,
            clock=clock,
        )
        relation_boundary = _RelationBoundary(
            store=store,
            command_service=command_service,
            authenticator=authenticator,
            authorizer=authorizer,
            read_policy=relation_read_policy,
            clock=clock,
        )
        return GovernedRelationAuthoritySystem(
            events=AuthorityEvents(
                policy_id=event_read_policy.policy_id,
                read=event_boundary.events_after,
                provenance=event_boundary.provenance,
                result=event_boundary.command_result,
            ),
            relations=GovernedRelations(
                bind_fixture=relation_boundary.bind_fixture,
                propose=relation_boundary.propose,
                decide=relation_boundary.decide,
                fixture_binding=relation_boundary.fixture_binding,
                proposal=relation_boundary.proposal,
                decision=relation_boundary.decision,
                admitted=relation_boundary.admitted,
                projection_events_after=(
                    relation_boundary.projection_events_after
                ),
            ),
            close=store.close,
        )
    except Exception:
        if store is not None:
            store.close()
        raise


__all__ = [
    "GovernedRelationAuthoritySystem",
    "GovernedRelations",
    "open_governed_relation_authority_system",
]
