from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable, Protocol

from newsroom.projection import (
    INTEGRATED_FIXTURE_V2_PROJECTION,
    ProjectionContractRegistry,
)
from newsroom.projection.models import ProjectionStateError
from newsroom.projection.neo4j._retrieval_adapter import (
    _open_hybrid_retrieval_neo4j_adapter,
)
from newsroom.projection.neo4j.models import (
    Neo4jIdentityConflict,
    Neo4jProjectorConfig,
    Neo4jReadError,
)
from newsroom.retrieval.fixture_v2 import (
    INTEGRATED_FIXTURE_V2_RETRIEVAL,
    IntegratedFixtureV2RetrievalContract,
    validate_fixture_branch_executions,
)
from newsroom.retrieval.fusion import fuse_fixture_candidates
from newsroom.retrieval.models import (
    FindRelatedEventCandidatesRequest,
    FindRelatedEventCandidatesResult,
    HydratedRetrievalPassage,
    RetrievalBranchExecution,
    RetrievalContextV2,
    RetrievalContractError,
    RetrievalFailure,
    RetrievalOutcome,
    RetrievalProjectionMetadata,
    RetrievalStateError,
)
from newsroom.retrieval.policy import (
    HYBRID_FIXTURE_POLICY_V1,
    HybridRetrievalPolicy,
)

from ._capability import _CapabilityIssuer
from ._object_capability import _ObjectCapabilityIssuer
from ._object_system import _ObjectBoundary
from ._retrieval_store import _HybridRetrievalAuthorityStore
from ._retrieval_security import (
    RETRIEVAL_REQUIRED_SCOPE,
    retrieval_authorization_request,
)
from .auth import AuthenticationProof
from .canonical import canonical_json_bytes, digest_bytes
from .object_policy import (
    HydrationPolicyRegistry,
    ObjectAdmissionRegistry,
    RightsPolicyRegistry,
    merge_authority_registries,
)
from .objects import (
    HydrationRequest,
    ObjectAdmissionDenied,
    ObjectHydrationDenied,
    ObjectLimits,
)
from .persistence import (
    AuthorityPersistenceError,
    IdempotencyConflict,
)
from .policy import CommandRegistry, PayloadSchemaRegistry
from .service import CommandService
from .types import TrustScope, UtcTimestamp
from newsroom.projection.policy import merge_projection_authority_registries
from newsroom.relations.policy import merge_relation_authority_registries
from newsroom.relations import INTEGRATED_FIXTURE_V2



class _HybridBranchAdapter(Protocol):
    def run_bounded_hybrid_branches(
        self,
        *,
        identity: Any,
        fixture: Any,
        retrieval_contract: IntegratedFixtureV2RetrievalContract,
        policy: HybridRetrievalPolicy,
        query_digest: str,
    ) -> tuple[RetrievalBranchExecution, ...]: ...

    def close(self) -> None: ...


class RelatedEventCandidateRetrieval:
    """Typed public read facade for the one Increment 2C named tool."""

    __slots__ = ("__find",)

    def __init__(
        self,
        find: Callable[
            [FindRelatedEventCandidatesRequest, AuthenticationProof],
            FindRelatedEventCandidatesResult,
        ],
    ) -> None:
        self.__find = find

    def find_related_event_candidates(
        self,
        request: FindRelatedEventCandidatesRequest,
        *,
        proof: AuthenticationProof,
    ) -> FindRelatedEventCandidatesResult:
        return self.__find(request, proof)


class HybridRetrievalAuthoritySystem:
    """Single-writer authority plus one bounded non-authoritative read tool."""

    __slots__ = ("retrieval", "__close")

    def __init__(
        self,
        *,
        retrieval: RelatedEventCandidateRetrieval,
        close: Callable[[], None],
    ) -> None:
        self.retrieval = retrieval
        self.__close = close

    def close(self) -> None:
        self.__close()

    def __enter__(self) -> "HybridRetrievalAuthoritySystem":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


@dataclass(frozen=True, slots=True)
class _RetrievalSecurityGrant:
    authentication: Any
    authorization_request: Any
    authorization: Any
    checked_at: UtcTimestamp


class _HybridRetrievalBoundary:
    def __init__(
        self,
        *,
        store: _HybridRetrievalAuthorityStore,
        object_boundary: _ObjectBoundary,
        adapter: _HybridBranchAdapter,
        policy: HybridRetrievalPolicy,
        retrieval_contract: IntegratedFixtureV2RetrievalContract,
        authenticator: Any,
        authorizer: Any,
        clock: Callable[[], UtcTimestamp],
    ) -> None:
        self._store = store
        self._object_boundary = object_boundary
        self._adapter = adapter
        self._policy = policy
        self._retrieval_contract = retrieval_contract
        self._authenticator = authenticator
        self._authorizer = authorizer
        self._clock = clock

    def _authenticate_and_authorize(
        self,
        request: FindRelatedEventCandidatesRequest,
        proof: AuthenticationProof,
    ) -> _RetrievalSecurityGrant:
        now = self._clock()
        authentication = self._authenticator.authenticate(proof, now=now)
        authentication.require_current(now)
        authorization_request = retrieval_authorization_request(
            authentication=authentication,
            request=request,
            policy=self._policy,
            retrieval_contract=self._retrieval_contract,
        )
        authorization = self._authorizer.authorize(
            authentication,
            authorization_request,
            now=now,
        )
        if (
            authorization.authentication_context_id
            != authentication.authentication_context_id
            or authorization.authorization_request_digest
            != authorization_request.request_digest
        ):
            raise PermissionError(
                "retrieval authorizer returned mismatched provenance"
            )
        authorization.require_allowed()
        return _RetrievalSecurityGrant(
            authentication=authentication,
            authorization_request=authorization_request,
            authorization=authorization,
            checked_at=now,
        )

    def find_related_event_candidates(
        self,
        request: FindRelatedEventCandidatesRequest,
        proof: AuthenticationProof,
    ) -> FindRelatedEventCandidatesResult:
        if not isinstance(request, FindRelatedEventCandidatesRequest):
            raise TypeError(
                "find_related_event_candidates requires a typed request"
            )
        security = self._authenticate_and_authorize(request, proof)

        try:
            replay = self._store.replay_request(
                request,
                authentication=security.authentication,
            )
        except (RetrievalStateError, ProjectionStateError) as exc:
            outcome, reason_code = self._classify_failure(exc)
            return FindRelatedEventCandidatesResult(
                request=request,
                context=None,
                failure=RetrievalFailure(
                    request_id=request.request_id,
                    context_id=request.context_id,
                    outcome=outcome,
                    reason_code=reason_code,
                    policy_digest=self._policy.contract_digest,
                    recorded_at=self._clock(),
                ),
                replayed=True,
            )
        if replay is not None:
            return replay

        policy_failure = self._request_policy_failure(request, security.checked_at)
        if policy_failure is not None:
            return self._persist_failure(
                request=request,
                outcome=RetrievalOutcome.POLICY_BLOCKED,
                reason_code=policy_failure,
                security=security,
            )

        projection: RetrievalProjectionMetadata | None = None
        try:
            projection = self._store.active_retrieval_projection(
                query_valid_time=request.query_valid_time
            )
            query_digest = self._retrieval_contract.query_digest(
                generation_identity_digest=(
                    projection.identity.identity_digest
                ),
                query_valid_time=request.query_valid_time.to_text(),
                watermark=projection.contiguous_ledger_seq,
            )
            branches = self._adapter.run_bounded_hybrid_branches(
                identity=projection.identity,
                fixture=INTEGRATED_FIXTURE_V2_PROJECTION,
                retrieval_contract=self._retrieval_contract,
                policy=self._policy,
                query_digest=query_digest,
            )
            validate_fixture_branch_executions(
                executions=branches,
                policy=self._policy,
                contract=self._retrieval_contract,
                query_digest=query_digest,
            )
            retained, exclusions = fuse_fixture_candidates(
                executions=branches,
                policy=self._policy,
                fixture=self._retrieval_contract,
            )
            if not retained:
                raise RetrievalStateError(
                    "required fixture prior candidate was not retained"
                )
            hydrated = self._hydrate_candidates(retained, proof=proof)
            total_context_bytes = sum(
                len(item.text.encode("utf-8")) for item in hydrated
            )
            serving_time = self._clock()
            projection = RetrievalProjectionMetadata(
                identity=projection.identity,
                generation_state=projection.generation_state,
                contiguous_ledger_seq=projection.contiguous_ledger_seq,
                open_gap_count=projection.open_gap_count,
                dead_letter_count=projection.dead_letter_count,
                query_valid_time=projection.query_valid_time,
                serving_time=serving_time,
            )
            context = RetrievalContextV2(
                context_id=request.context_id,
                request_id=request.request_id,
                tool_name=self._policy.tool_name,
                tool_version=self._policy.tool_version,
                policy_digest=self._policy.contract_digest,
                query_digest=query_digest,
                outcome=RetrievalOutcome.COMPLETE,
                projection=projection,
                branches=branches,
                retained_candidates=retained,
                exclusions=exclusions,
                hydrated_passages=hydrated,
                total_context_bytes=total_context_bytes,
                truncated=False,
                recorded_at=serving_time,
            )
            if (
                len(canonical_json_bytes(context.canonical_value()))
                > self._policy.response_byte_limit
            ):
                raise RetrievalStateError(
                    "retrieval context exceeds the server-owned response bound"
                )
            return self._store.persist_complete_result(
                request=request,
                context=context,
                retrieval_contract_digest=(
                    self._retrieval_contract.contract_digest
                ),
                authentication=security.authentication,
                authorization_request=security.authorization_request,
                authorization=security.authorization,
            )
        except Exception as exc:
            outcome, reason_code = self._classify_failure(exc)
            return self._persist_failure(
                request=request,
                outcome=outcome,
                reason_code=reason_code,
                security=security,
                projection=projection,
            )

    def _request_policy_failure(
        self,
        request: FindRelatedEventCandidatesRequest,
        checked_at: UtcTimestamp,
    ) -> str | None:
        contract = self._retrieval_contract
        if request.fixture_id != contract.fixture_id:
            return "FIXTURE_ID_NOT_ALLOWED"
        if request.query_revision_id != contract.query_revision_id:
            return "QUERY_REVISION_NOT_ALLOWED"
        if (
            request.query_hypothesis_version_id
            != contract.query_hypothesis_version_id
        ):
            return "QUERY_HYPOTHESIS_NOT_ALLOWED"
        if request.query_valid_time.value > checked_at.value:
            return "QUERY_VALID_TIME_IN_FUTURE"
        return None

    def _hydrate_candidates(
        self,
        retained: tuple[Any, ...],
        *,
        proof: AuthenticationProof,
    ) -> tuple[HydratedRetrievalPassage, ...]:
        passage_ids = tuple(
            sorted(
                {
                    passage_id
                    for candidate in retained
                    for passage_id in self._retrieval_contract.root_by_id[
                        candidate.dependency_root_id
                    ].passage_ids
                }
            )
        )
        hydrated_passages: list[HydratedRetrievalPassage] = []
        for passage_id in passage_ids:
            admission_id, blob_digest, language = (
                self._store.fixture_passage_binding(passage_id)
            )
            hydrated = self._object_boundary.hydrate(
                HydrationRequest(
                    admission_id=admission_id,
                    purpose="project.discovery",
                    offset=0,
                    length=None,
                ),
                proof,
            )
            expected = self._retrieval_contract.root_by_passage_id.get(passage_id)
            fixture_passage = (
                None
                if expected is None
                else INTEGRATED_FIXTURE_V2.passage_by_id.get(passage_id)
            )
            if (
                fixture_passage is None
                or hydrated.data != fixture_passage.canonical_bytes
                or fixture_passage.blob_digest != blob_digest
                or fixture_passage.language != language
            ):
                raise RetrievalStateError(
                    "hydrated bytes differ from checked fixture authority"
                )
            try:
                text = hydrated.data.decode("utf-8", errors="strict")
                state_cutoff = json.loads(
                    hydrated.decision.state_cutoff_bytes.decode(
                        "utf-8", errors="strict"
                    )
                )
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise RetrievalStateError(
                    "hydrated authority evidence is malformed"
                ) from exc
            if not isinstance(state_cutoff, dict):
                raise RetrievalStateError(
                    "hydrated authority state cutoff is malformed"
                )
            hydrated_passages.append(
                HydratedRetrievalPassage(
                    passage_id=passage_id,
                    admission_id=admission_id,
                    blob_digest=blob_digest,
                    language=language,
                    text=text,
                    text_digest=digest_bytes(text.encode("utf-8")),
                    hydration_policy_contract_digest=(
                        hydrated.decision.policy_contract_digest
                    ),
                    access_decision_id=(
                        hydrated.decision.access_decision_id
                    ),
                    byte_start=hydrated.decision.offset,
                    byte_end=(
                        hydrated.decision.offset
                        + hydrated.decision.allowed_bytes
                    ),
                    rights_state="PERMITTED",
                    lifecycle_state=str(
                        state_cutoff.get("admission_state", "UNKNOWN")
                    ),
                    trust_scope=TrustScope.OBSERVED,
                )
            )
        return tuple(hydrated_passages)

    def _persist_failure(
        self,
        *,
        request: FindRelatedEventCandidatesRequest,
        outcome: RetrievalOutcome,
        reason_code: str,
        security: _RetrievalSecurityGrant,
        projection: RetrievalProjectionMetadata | None = None,
    ) -> FindRelatedEventCandidatesResult:
        failure = RetrievalFailure(
            request_id=request.request_id,
            context_id=request.context_id,
            outcome=outcome,
            reason_code=reason_code,
            policy_digest=self._policy.contract_digest,
            recorded_at=self._clock(),
        )
        try:
            return self._store.persist_failure_result(
                request=request,
                failure=failure,
                retrieval_contract_digest=(
                    self._retrieval_contract.contract_digest
                ),
                authentication=security.authentication,
                authorization_request=security.authorization_request,
                authorization=security.authorization,
                projection=projection,
            )
        except (RetrievalStateError, ProjectionStateError) as exc:
            final_outcome, final_reason_code = self._classify_failure(exc)
            final_failure = RetrievalFailure(
                request_id=request.request_id,
                context_id=request.context_id,
                outcome=final_outcome,
                reason_code=final_reason_code,
                policy_digest=self._policy.contract_digest,
                recorded_at=self._clock(),
            )
            return self._store.persist_failure_result(
                request=request,
                failure=final_failure,
                retrieval_contract_digest=(
                    self._retrieval_contract.contract_digest
                ),
                authentication=security.authentication,
                authorization_request=security.authorization_request,
                authorization=security.authorization,
                projection=None,
            )

    @staticmethod
    def _classify_failure(exc: Exception) -> tuple[RetrievalOutcome, str]:
        if isinstance(exc, IdempotencyConflict):
            raise exc
        if isinstance(exc, (ObjectHydrationDenied, ObjectAdmissionDenied)):
            return RetrievalOutcome.INCOMPLETE, "HYDRATION_AUTHORITY_DENIED"
        if isinstance(exc, Neo4jReadError):
            return RetrievalOutcome.UNAVAILABLE, "NEO4J_RETRIEVAL_UNAVAILABLE"
        if isinstance(exc, Neo4jIdentityConflict):
            return RetrievalOutcome.INCOMPLETE, "NEO4J_RETRIEVAL_IDENTITY_MISMATCH"
        if isinstance(exc, ProjectionStateError):
            return RetrievalOutcome.UNAVAILABLE, "ACTIVE_PROJECTION_UNAVAILABLE"
        if isinstance(exc, RetrievalStateError):
            message = str(exc).lower()
            if (
                "stale" in message
                or "source" in message
                or "changed before" in message
            ):
                return RetrievalOutcome.STALE, "RETRIEVAL_SOURCE_STALE"
            if "dead letter" in message:
                return (
                    RetrievalOutcome.INCOMPLETE,
                    "RETRIEVAL_DEAD_LETTER_BLOCKED",
                )
            if "gap" in message:
                return RetrievalOutcome.INCOMPLETE, "RETRIEVAL_GAP_BLOCKED"
            if "generation" in message or "active" in message:
                return (
                    RetrievalOutcome.UNAVAILABLE,
                    "ACTIVE_PROJECTION_UNAVAILABLE",
                )
            if "response bound" in message:
                return (
                    RetrievalOutcome.POLICY_BLOCKED,
                    "RESPONSE_BOUND_EXCEEDED",
                )
            return RetrievalOutcome.INCOMPLETE, "RETRIEVAL_INCOMPLETE"
        if isinstance(exc, RetrievalContractError):
            return RetrievalOutcome.INCOMPLETE, "RETRIEVAL_CONTRACT_MISMATCH"
        if isinstance(exc, AuthorityPersistenceError):
            return RetrievalOutcome.INCOMPLETE, "RETRIEVAL_AUTHORITY_MISMATCH"
        raise exc


def _open_hybrid_retrieval_with_adapter(
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
    policy: HybridRetrievalPolicy = HYBRID_FIXTURE_POLICY_V1,
    retrieval_contract: IntegratedFixtureV2RetrievalContract = (
        INTEGRATED_FIXTURE_V2_RETRIEVAL
    ),
    command_service_version: str = "authority-command-v1",
    busy_timeout_ms: int = 5_000,
    clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
) -> HybridRetrievalAuthoritySystem:
    object_registry, object_schemas = merge_authority_registries(
        command_registry=registry,
        payload_schemas=payload_schemas,
    )
    relation_registry, relation_schemas = merge_relation_authority_registries(
        command_registry=object_registry,
        payload_schemas=object_schemas,
    )
    merged_registry, merged_schemas = merge_projection_authority_registries(
        command_registry=relation_registry,
        payload_schemas=relation_schemas,
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
    store: _HybridRetrievalAuthorityStore | None = None
    try:
        store = _HybridRetrievalAuthorityStore(
            path,
            object_root=object_root,
            object_limits=object_limits,
            object_issuer=object_issuer,
            admission_registry=admission_registry,
            rights_policies=rights_policies,
            hydration_policies=hydration_policies,
            retrieval_policy=policy,
            retrieval_contract=retrieval_contract,
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
            store=store,  # type: ignore[arg-type]
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
            policy=policy,
            retrieval_contract=retrieval_contract,
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

        return HybridRetrievalAuthoritySystem(
            retrieval=RelatedEventCandidateRetrieval(
                retrieval_boundary.find_related_event_candidates
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


def open_hybrid_retrieval_authority_system(
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
    policy: HybridRetrievalPolicy = HYBRID_FIXTURE_POLICY_V1,
    retrieval_contract: IntegratedFixtureV2RetrievalContract = (
        INTEGRATED_FIXTURE_V2_RETRIEVAL
    ),
    command_service_version: str = "authority-command-v1",
    busy_timeout_ms: int = 5_000,
    clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
) -> HybridRetrievalAuthoritySystem:
    adapter = _open_hybrid_retrieval_neo4j_adapter(neo4j_config)
    return _open_hybrid_retrieval_with_adapter(
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
        policy=policy,
        retrieval_contract=retrieval_contract,
        command_service_version=command_service_version,
        busy_timeout_ms=busy_timeout_ms,
        clock=clock,
    )


__all__ = [
    "HybridRetrievalAuthoritySystem",
    "RelatedEventCandidateRetrieval",
    "_open_hybrid_retrieval_with_adapter",
    "open_hybrid_retrieval_authority_system",
]
