from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from newsroom.increment2.models import (
    DevelopmentCandidateAdmissionRequest,
    DevelopmentCandidateAdmissionView,
    INTEGRATED_FIXTURE_V2_DEVELOPMENT_CANDIDATE,
)
from newsroom.increment2.policy import (
    DEVELOPMENT_CANDIDATE_ADMISSION_COMMAND,
    merge_development_candidate_authority_registries,
)
from newsroom.integrated.models import CandidateAdmissionDecisionId
from newsroom.projection import ProjectionContractRegistry
from newsroom.projection.neo4j._retrieval_adapter import (
    _open_hybrid_retrieval_neo4j_adapter,
)
from newsroom.projection.neo4j.models import Neo4jProjectorConfig
from newsroom.retrieval import (
    INTEGRATED_FIXTURE_V2_RETRIEVAL,
    RetrievalContextV2,
)
from newsroom.retrieval.policy import HYBRID_FIXTURE_POLICY_V1

from ._capability import _CapabilityIssuer
from ._development_candidate_store import _DevelopmentCandidateAuthorityStore
from ._object_capability import _ObjectCapabilityIssuer
from ._object_system import _ObjectBoundary
from ._retrieval_system import (
    RelatedEventCandidateRetrieval,
    _HybridBranchAdapter,
    _HybridRetrievalBoundary,
)
from ._security import _AuthorizationRequest
from .auth import AuthenticationProof
from .canonical import digest_canonical
from .models import InlinePayload, SemanticCommand
from .object_policy import (
    HydrationPolicyRegistry,
    ObjectAdmissionRegistry,
    RightsPolicyRegistry,
    merge_authority_registries,
)
from .objects import ObjectLimits
from .policy import CommandRegistry, PayloadSchemaRegistry
from .service import CommandService
from .types import UtcTimestamp
from newsroom.projection.policy import merge_projection_authority_registries
from newsroom.relations.policy import merge_relation_authority_registries


_CANDIDATE_READ_SCHEMA_DIGEST = digest_canonical(
    {
        "contract": "development-candidate-read-no-payload-v1",
        "payload_mode": "NO_PAYLOAD",
    }
)


class DevelopmentCandidates:
    """Typed public Candidate facade; SQLite writers never escape."""

    __slots__ = ("__admit", "__decision")

    def __init__(
        self,
        *,
        admit: Callable[
            [DevelopmentCandidateAdmissionRequest, AuthenticationProof],
            DevelopmentCandidateAdmissionView,
        ],
        decision: Callable[
            [CandidateAdmissionDecisionId, AuthenticationProof],
            DevelopmentCandidateAdmissionView,
        ],
    ) -> None:
        self.__admit = admit
        self.__decision = decision

    def admit(
        self,
        request: DevelopmentCandidateAdmissionRequest,
        *,
        proof: AuthenticationProof,
    ) -> DevelopmentCandidateAdmissionView:
        return self.__admit(request, proof)

    def decision(
        self,
        decision_id: CandidateAdmissionDecisionId,
        *,
        proof: AuthenticationProof,
    ) -> DevelopmentCandidateAdmissionView:
        return self.__decision(decision_id, proof)


class CompleteFixtureCandidateAuthoritySystem:
    """One SQLite writer with bounded retrieval and Candidate authority."""

    __slots__ = ("retrieval", "candidates", "__close")

    def __init__(
        self,
        *,
        retrieval: RelatedEventCandidateRetrieval,
        candidates: DevelopmentCandidates,
        close: Callable[[], None],
    ) -> None:
        self.retrieval = retrieval
        self.candidates = candidates
        self.__close = close

    def close(self) -> None:
        self.__close()

    def __enter__(self) -> "CompleteFixtureCandidateAuthoritySystem":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


class _DevelopmentCandidateBoundary:
    def __init__(
        self,
        *,
        store: _DevelopmentCandidateAuthorityStore,
        command_service: CommandService,
        authenticator: Any,
        authorizer: Any,
        clock: Callable[[], UtcTimestamp],
    ) -> None:
        self._store = store
        self._command_service = command_service
        self._authenticator = authenticator
        self._authorizer = authorizer
        self._clock = clock

    def admit(
        self,
        request: DevelopmentCandidateAdmissionRequest,
        proof: AuthenticationProof,
    ) -> DevelopmentCandidateAdmissionView:
        if not isinstance(request, DevelopmentCandidateAdmissionRequest):
            raise TypeError("development Candidate admission requires a typed request")
        manifest = INTEGRATED_FIXTURE_V2_DEVELOPMENT_CANDIDATE
        payload = {
            "proposal_id": str(request.proposal_id),
            "retrieval_context_id": str(request.retrieval_context_id),
            "expected_context_digest": request.expected_context_digest,
            "candidate_manifest_digest": manifest.manifest_digest,
            "semantic_collision_digest": manifest.semantic_collision_digest,
        }
        command = SemanticCommand(
            command_type=DEVELOPMENT_CANDIDATE_ADMISSION_COMMAND,
            aggregate_id=request.proposal_id.as_aggregate_id(),
            expected_aggregate_version=0,
            payload=InlinePayload(payload),
            idempotency_key=request.idempotency_key,
        )
        # Authenticate and authorize before the context lookup so the public
        # Candidate facade cannot become a context-existence oracle.
        grant = self._command_service._authorize_for_commit(command, proof=proof)
        context = self._store.retrieval_context(request.retrieval_context_id)
        return self._store.commit_development_candidate_admission(
            grant,
            request=request,
            context=context,
        )

    def decision(
        self,
        decision_id: CandidateAdmissionDecisionId,
        proof: AuthenticationProof,
    ) -> DevelopmentCandidateAdmissionView:
        if not isinstance(decision_id, CandidateAdmissionDecisionId):
            raise TypeError("development Candidate decision identity must be typed")
        now = self._clock()
        authentication = self._authenticator.authenticate(proof, now=now)
        authentication.require_current(now)
        stable = digest_canonical(
            {
                "contract": "development-candidate-decision-read-v1",
                "decision_id": str(decision_id),
            }
        )
        unsigned = {
            "authentication_context_id": str(
                authentication.authentication_context_id
            ),
            "principal_id": authentication.principal_id,
            "authority_domain": authentication.authority_domain,
            "operation_type": "read:development_candidate:decision",
            "required_scope": "authority.candidate.read",
            "stable_semantic_request_digest": stable,
            "command_definition_digest": _CANDIDATE_READ_SCHEMA_DIGEST,
            "aggregate_type": "development_candidate_admission_decision",
            "aggregate_id": str(decision_id),
            "event_type": "candidate.development.read",
            "event_schema_version": 1,
            "payload_mode": "NO_PAYLOAD",
            "payload_schema_version": "development_candidate_read_v1",
            "payload_schema_contract_version": (
                "development-candidate-read-no-payload-v1"
            ),
            "payload_schema_contract_digest": _CANDIDATE_READ_SCHEMA_DIGEST,
            "payload_canonicalizer_version": "development-candidate-none-v1",
            "trust_scope": "ADMITTED",
            "security_scope": "authority.candidate",
            "retention_scope": "authority.audit",
            "object_class": None,
            "allowed_use": None,
        }
        request = _AuthorizationRequest(
            authentication_context_id=authentication.authentication_context_id,
            principal_id=authentication.principal_id,
            authority_domain=authentication.authority_domain,
            operation_type="read:development_candidate:decision",
            required_scope="authority.candidate.read",
            stable_semantic_request_digest=stable,
            command_definition_digest=_CANDIDATE_READ_SCHEMA_DIGEST,
            aggregate_type="development_candidate_admission_decision",
            aggregate_id=str(decision_id),
            event_type="candidate.development.read",
            event_schema_version=1,
            payload_mode="NO_PAYLOAD",
            payload_schema_version="development_candidate_read_v1",
            payload_schema_contract_version=(
                "development-candidate-read-no-payload-v1"
            ),
            payload_schema_contract_digest=_CANDIDATE_READ_SCHEMA_DIGEST,
            payload_canonicalizer_version="development-candidate-none-v1",
            trust_scope="ADMITTED",
            security_scope="authority.candidate",
            retention_scope="authority.audit",
            object_class=None,
            allowed_use=None,
            request_digest=digest_canonical(unsigned),
        )
        decision = self._authorizer.authorize(
            authentication,
            request,
            now=now,
        )
        if (
            decision.authentication_context_id
            != authentication.authentication_context_id
            or decision.authorization_request_digest != request.request_digest
        ):
            raise PermissionError(
                "development Candidate read authorization provenance differs"
            )
        decision.require_allowed()
        return self._store.development_candidate_decision(decision_id)


def _open_complete_fixture_candidate_with_adapter(
    *,
    path: Path,
    object_root: Path,
    object_limits: ObjectLimits,
    registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
    contracts: ProjectionContractRegistry,
    admission_registry: ObjectAdmissionRegistry,
    rights_policies: RightsPolicyRegistry,
    hydration_policies: HydrationPolicyRegistry,
    authenticator: Any,
    authorizer: Any,
    adapter: _HybridBranchAdapter,
    command_service_version: str = "authority-command-v1",
    busy_timeout_ms: int = 5_000,
    clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
) -> CompleteFixtureCandidateAuthoritySystem:
    object_registry, object_schemas = merge_authority_registries(
        command_registry=registry,
        payload_schemas=payload_schemas,
    )
    relation_registry, relation_schemas = merge_relation_authority_registries(
        command_registry=object_registry,
        payload_schemas=object_schemas,
    )
    projection_registry, projection_schemas = merge_projection_authority_registries(
        command_registry=relation_registry,
        payload_schemas=relation_schemas,
    )
    merged_registry, merged_schemas = (
        merge_development_candidate_authority_registries(
            command_registry=projection_registry,
            payload_schemas=projection_schemas,
        )
    )
    issuer = _CapabilityIssuer(
        command_registry=merged_registry,
        payload_schemas=merged_schemas,
    )
    object_issuer = _ObjectCapabilityIssuer(
        admission_registry=admission_registry,
        rights_policies=rights_policies,
        hydration_policies=hydration_policies,
        command_registry=merged_registry,
    )
    store: _DevelopmentCandidateAuthorityStore | None = None
    try:
        store = _DevelopmentCandidateAuthorityStore(
            path,
            object_root=object_root,
            object_limits=object_limits,
            object_issuer=object_issuer,
            admission_registry=admission_registry,
            rights_policies=rights_policies,
            hydration_policies=hydration_policies,
            retrieval_policy=HYBRID_FIXTURE_POLICY_V1,
            retrieval_contract=INTEGRATED_FIXTURE_V2_RETRIEVAL,
            candidate_manifest=INTEGRATED_FIXTURE_V2_DEVELOPMENT_CANDIDATE,
            issuer=issuer,
            command_registry=merged_registry,
            payload_schemas=merged_schemas,
            command_service_version=command_service_version,
            busy_timeout_ms=busy_timeout_ms,
            clock=clock,
            contracts=contracts,
        )
        command_service = CommandService(
            registry=merged_registry,
            payload_schemas=merged_schemas,
            authenticator=authenticator,
            authorizer=authorizer,
            admission_lookup=store,
            committed_lookup=store,
            clock=clock,
            _issuer=issuer,
        )
        object_boundary = _ObjectBoundary(
            store=store,
            cas=store._complete_cas,
            object_issuer=object_issuer,
            admission_registry=admission_registry,
            rights_policies=rights_policies,
            hydration_policies=hydration_policies,
            authenticator=authenticator,
            authorizer=authorizer,
            command_service=command_service,
            command_registry=merged_registry,
            clock=clock,
        )
        retrieval_boundary = _HybridRetrievalBoundary(
            store=store,
            object_boundary=object_boundary,
            adapter=adapter,
            policy=HYBRID_FIXTURE_POLICY_V1,
            retrieval_contract=INTEGRATED_FIXTURE_V2_RETRIEVAL,
            authenticator=authenticator,
            authorizer=authorizer,
            clock=clock,
        )
        candidate_boundary = _DevelopmentCandidateBoundary(
            store=store,
            command_service=command_service,
            authenticator=authenticator,
            authorizer=authorizer,
            clock=clock,
        )
        closed = False

        def close() -> None:
            nonlocal closed
            if closed:
                return
            closed = True
            try:
                adapter.close()
            finally:
                assert store is not None
                store.close()

        return CompleteFixtureCandidateAuthoritySystem(
            retrieval=RelatedEventCandidateRetrieval(
                retrieval_boundary.find_related_event_candidates
            ),
            candidates=DevelopmentCandidates(
                admit=candidate_boundary.admit,
                decision=candidate_boundary.decision,
            ),
            close=close,
        )
    except Exception:
        try:
            adapter.close()
        finally:
            if store is not None:
                store.close()
        raise


def open_complete_fixture_candidate_authority_system(
    *,
    path: Path,
    object_root: Path,
    object_limits: ObjectLimits,
    registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
    contracts: ProjectionContractRegistry,
    admission_registry: ObjectAdmissionRegistry,
    rights_policies: RightsPolicyRegistry,
    hydration_policies: HydrationPolicyRegistry,
    authenticator: Any,
    authorizer: Any,
    neo4j_config: Neo4jProjectorConfig,
    command_service_version: str = "authority-command-v1",
    busy_timeout_ms: int = 5_000,
    clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
) -> CompleteFixtureCandidateAuthoritySystem:
    adapter = _open_hybrid_retrieval_neo4j_adapter(neo4j_config)
    return _open_complete_fixture_candidate_with_adapter(
        path=path,
        object_root=object_root,
        object_limits=object_limits,
        registry=registry,
        payload_schemas=payload_schemas,
        contracts=contracts,
        admission_registry=admission_registry,
        rights_policies=rights_policies,
        hydration_policies=hydration_policies,
        authenticator=authenticator,
        authorizer=authorizer,
        adapter=adapter,
        command_service_version=command_service_version,
        busy_timeout_ms=busy_timeout_ms,
        clock=clock,
    )


__all__ = [
    "CompleteFixtureCandidateAuthoritySystem",
    "DevelopmentCandidates",
    "_open_complete_fixture_candidate_with_adapter",
    "open_complete_fixture_candidate_authority_system",
]
