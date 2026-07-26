from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

from newsroom.projection import INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID
from newsroom.projection.models import (
    ProjectionGenerationId,
    ProjectionGenerationState,
    ProjectionStateError,
)
from newsroom.projection.neo4j.complete_models import CompleteProjectionIdentity
from newsroom.relations import INTEGRATED_FIXTURE_V2
from newsroom.retrieval.models import (
    FindRelatedEventCandidatesRequest,
    FindRelatedEventCandidatesResult,
    FusedRetrievalCandidate,
    HydratedRetrievalPassage,
    ReciprocalRankScore,
    RetrievalBranch,
    RetrievalBranchExecution,
    RetrievalBranchHit,
    RetrievalContextV2,
    RetrievalContextV2Id,
    RetrievalContractError,
    RetrievalExclusion,
    RetrievalExclusionReason,
    RetrievalFailure,
    RetrievalOutcome,
    RetrievalProjectionMetadata,
    RetrievalRequestId,
    RetrievalStateError,
)
from newsroom.retrieval.fixture_v2 import (
    IntegratedFixtureV2RetrievalContract,
    validate_fixture_branch_executions,
)
from newsroom.retrieval.fusion import fuse_fixture_candidates
from newsroom.retrieval.policy import HybridRetrievalPolicy

from ._complete_projection_store import _CompleteProjectionAuthorityStore
from ._object_capability import _ObjectCapabilityIssuer
from ._object_store_base import _ObjectStoreBase
from ._object_store_hydration import _ObjectHydrationStoreMixin
from ._retrieval_security import (
    RETRIEVAL_REQUIRED_SCOPE,
    require_exact_retrieval_authorization_value,
)
from .canonical import canonical_json_bytes, digest_bytes, digest_canonical
from .object_policy import (
    HydrationPolicyRegistry,
    ObjectAdmissionRegistry,
    RightsPolicyRegistry,
)
from .objects import (
    AdmissionState,
    BlobLifecycleState,
    ObjectAccessDecisionId,
    ObjectLimits,
)
from .persistence import (
    AuthorityPersistenceError,
    IdempotencyConflict,
)
from .types import ObjectAdmissionId, TrustScope, UtcTimestamp


_ATTEMPT_CONTRACT = "newsroom-hybrid-retrieval-attempt-v1"
_TOOL_NAME = "find_related_event_candidates"
_TOOL_VERSION = "find-related-event-candidates-v1"
_ATTEMPT_KEYS = frozenset(
    {
        "contract",
        "request",
        "tool_name",
        "tool_version",
        "policy_digest",
        "retrieval_contract_digest",
        "projection",
        "result",
        "authentication_context_id",
        "authorization_request_digest",
        "authorization_decision_id",
        "recorded_at",
    }
)


class _HybridRetrievalAuthorityStore(
    _ObjectHydrationStoreMixin,
    _ObjectStoreBase,
    _CompleteProjectionAuthorityStore,
):
    """Single SQLite/CAS authority writer for bounded retrieval evidence."""

    def __init__(
        self,
        path: Path,
        *,
        object_root: Path,
        object_limits: ObjectLimits,
        object_issuer: _ObjectCapabilityIssuer,
        admission_registry: ObjectAdmissionRegistry,
        rights_policies: RightsPolicyRegistry,
        hydration_policies: HydrationPolicyRegistry,
        retrieval_policy: HybridRetrievalPolicy,
        retrieval_contract: IntegratedFixtureV2RetrievalContract,
        **kwargs: Any,
    ) -> None:
        # These registries are required while EventStoreBase invokes the virtual
        # migration/integrity hook from inside CompleteProjectionStore.__init__.
        self._object_issuer = object_issuer
        self._admission_registry = admission_registry
        self._rights_policies = rights_policies
        self._hydration_policies = hydration_policies
        self._retrieval_policy = retrieval_policy
        self._retrieval_contract = retrieval_contract
        super().__init__(
            path,
            object_root=object_root,
            object_limits=object_limits,
            **kwargs,
        )
        self._cas = self._complete_cas
        self._configure_object_store(
            object_issuer=object_issuer,
            admission_registry=admission_registry,
            rights_policies=rights_policies,
            hydration_policies=hydration_policies,
            cas=self._complete_cas,
        )

    def _migrate_or_validate(self) -> None:
        _ObjectStoreBase._migrate_or_validate(self)
        self._validate_complete_fixture_cas()
        self._validate_retrieval_integrity()

    def active_retrieval_projection(
        self,
        *,
        query_valid_time: UtcTimestamp,
        family_id: str = INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID,
    ) -> RetrievalProjectionMetadata:
        metadata = self.projection_active_generation_metadata(family_id)
        if metadata.generation.state is not ProjectionGenerationState.ACTIVE:
            raise RetrievalStateError("retrieval generation is not ACTIVE")
        if metadata.dead_letter_count:
            raise RetrievalStateError(
                "retrieval generation has an unresolved dead letter"
            )
        if metadata.open_gap_count:
            raise RetrievalStateError(
                "retrieval generation has an unresolved required gap"
            )
        if metadata.contiguous_ledger_seq <= 0:
            raise RetrievalStateError("retrieval generation has no positive checkpoint")
        validation = self.projection_generation_validation(
            metadata.generation.generation_id
        )
        serving_time = self._clock()
        date_window_start = self._retrieval_policy.date_window_start(
            query_valid_time
        )
        freshness_deadline = (
            self._retrieval_policy.projection_freshness_deadline(
                validation.recorded_at
            )
        )
        if serving_time.value < max(
            query_valid_time.value,
            validation.recorded_at.value,
        ):
            raise RetrievalStateError(
                "retrieval authority clock moved backwards"
            )
        if serving_time.value > freshness_deadline.value:
            raise RetrievalStateError(
                "retrieval projection freshness is stale"
            )
        latest = self.latest_complete_source_ledger_seq()
        if (
            validation.checkpoint_ledger_seq != metadata.contiguous_ledger_seq
            or metadata.contiguous_ledger_seq != latest
        ):
            raise RetrievalStateError(
                "retrieval generation is stale against source authority"
            )
        identity, _complete, _fulltext, _vector, _fixture = (
            self.complete_projection_contracts(metadata.generation.generation_id)
        )
        return RetrievalProjectionMetadata(
            identity=identity,
            generation_state=metadata.generation.state,
            contiguous_ledger_seq=metadata.contiguous_ledger_seq,
            open_gap_count=metadata.open_gap_count,
            dead_letter_count=metadata.dead_letter_count,
            validation_recorded_at=validation.recorded_at,
            date_window_start=date_window_start,
            query_valid_time=query_valid_time,
            freshness_deadline=freshness_deadline,
            serving_time=serving_time,
        )

    def fixture_passage_binding(
        self,
        passage_id: str,
    ) -> tuple[ObjectAdmissionId, str, str]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT p.admission_id,p.blob_digest,p.language "
                "FROM integrated_fixture_v2_passage_objects p "
                "JOIN integrated_fixture_v2_bindings b "
                "ON b.binding_id=p.binding_id "
                "WHERE b.fixture_id=? AND p.passage_id=? "
                "ORDER BY b.recorded_at",
                (INTEGRATED_FIXTURE_V2.fixture_id, passage_id),
            ).fetchall()
            if len(rows) != 1:
                raise RetrievalStateError(
                    "retrieval passage lacks one exact fixture authority binding"
                )
            row = rows[0]
            return (
                ObjectAdmissionId.parse(str(row["admission_id"])),
                str(row["blob_digest"]),
                str(row["language"]),
            )

    def _existing_attempt_locked(
        self,
        conn: sqlite3.Connection,
        request: FindRelatedEventCandidatesRequest,
    ) -> sqlite3.Row | None:
        rows = conn.execute(
            "SELECT * FROM hybrid_retrieval_attempts "
            "WHERE idempotency_key=? OR request_id=? OR context_id=? "
            "ORDER BY recorded_at,request_id",
            (
                request.idempotency_key,
                str(request.request_id),
                str(request.context_id),
            ),
        ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise IdempotencyConflict(
                "retrieval request identities resolve to different attempts"
            )
        row = rows[0]
        retained = self._request_from_bytes(bytes(row["request_bytes"]))
        if (
            retained.canonical_value() != request.canonical_value()
            or str(row["request_id"]) != str(request.request_id)
            or str(row["context_id"]) != str(request.context_id)
            or str(row["idempotency_key"]) != request.idempotency_key
        ):
            raise IdempotencyConflict(
                "retrieval identity conflicts with retained request"
            )
        return row

    def _replay_result_locked(
        self,
        conn: sqlite3.Connection,
        *,
        row: sqlite3.Row,
        request: FindRelatedEventCandidatesRequest,
        authentication: Any,
        authorization_request: Any,
        authorization: Any,
    ) -> FindRelatedEventCandidatesResult:
        self._require_current_security_locked(
            request=request,
            authentication=authentication,
            authorization_request=authorization_request,
            authorization=authorization,
        )
        original_authentication = conn.execute(
            "SELECT principal_id,authority_domain "
            "FROM authentication_contexts "
            "WHERE authentication_context_id=?",
            (str(row["authentication_context_id"]),),
        ).fetchone()
        if (
            original_authentication is None
            or str(original_authentication["principal_id"])
            != authentication.principal_id
            or str(original_authentication["authority_domain"])
            != authentication.authority_domain
        ):
            raise PermissionError(
                "retrieval replay is bound to its original principal"
            )
        result = self._result_from_attempt_row(row, replayed=True)
        if result.request.canonical_value() != request.canonical_value():
            raise IdempotencyConflict(
                "retrieval replay differs from retained request"
            )
        if result.context is not None:
            self._require_current_projection_locked(
                conn,
                result.context.projection,
            )
            self._validate_hydrations_locked(
                conn,
                result.context,
                principal_id=authentication.principal_id,
                authority_domain=authentication.authority_domain,
            )
        return result

    def replay_request(
        self,
        request: FindRelatedEventCandidatesRequest,
        *,
        authentication: Any,
        authorization_request: Any,
        authorization: Any,
    ) -> FindRelatedEventCandidatesResult | None:
        with self._lock:
            row = self._existing_attempt_locked(
                self._connection,
                request,
            )
            if row is None:
                return None
            return self._replay_result_locked(
                self._connection,
                row=row,
                request=request,
                authentication=authentication,
                authorization_request=authorization_request,
                authorization=authorization,
            )

    def retrieval_context(
        self,
        context_id: RetrievalContextV2Id,
    ) -> RetrievalContextV2:
        with self._lock:
            row = self._connection.execute(
                "SELECT canonical_bytes,canonical_digest "
                "FROM hybrid_retrieval_contexts_v2 WHERE context_id=?",
                (str(context_id),),
            ).fetchone()
            if row is None:
                raise KeyError(str(context_id))
            return self._context_from_bytes(
                bytes(row["canonical_bytes"]),
                expected_digest=str(row["canonical_digest"]),
            )

    def persist_complete_result(
        self,
        *,
        request: FindRelatedEventCandidatesRequest,
        context: RetrievalContextV2,
        retrieval_contract_digest: str,
        authentication: Any,
        authorization_request: Any,
        authorization: Any,
    ) -> FindRelatedEventCandidatesResult:
        if context.outcome is not RetrievalOutcome.COMPLETE:
            raise RetrievalContractError("complete persistence requires COMPLETE context")
        if (
            context.request_id != request.request_id
            or context.context_id != request.context_id
        ):
            raise RetrievalContractError("retrieval context differs from request")
        if context.projection.query_valid_time != request.query_valid_time:
            raise RetrievalContractError(
                "retrieval context query-valid time differs from request"
            )
        if context.tool_name != _TOOL_NAME or context.tool_version != _TOOL_VERSION:
            raise RetrievalContractError("retrieval context tool identity differs")
        if context.policy_digest != self._retrieval_policy.contract_digest:
            raise RetrievalContractError("retrieval context policy differs")
        if retrieval_contract_digest != self._retrieval_contract.contract_digest:
            raise RetrievalContractError("retrieval contract digest differs")
        with self._lock, self._transaction() as conn:
            existing = self._existing_attempt_locked(conn, request)
            if existing is not None:
                return self._replay_result_locked(
                    conn,
                    row=existing,
                    request=request,
                    authentication=authentication,
                    authorization_request=authorization_request,
                    authorization=authorization,
                )

            security_checked_at = self._require_current_security_locked(
                request=request,
                authentication=authentication,
                authorization_request=authorization_request,
                authorization=authorization,
            )
            if (
                context.recorded_at.value < authorization.decided_at.value
                or context.recorded_at.value > security_checked_at.value
                or context.recorded_at.value >= authentication.expires_at.value
            ):
                raise PermissionError(
                    "retrieval context time is outside current security authority"
                )
            self._require_current_projection_locked(conn, context.projection)
            self._validate_hydrations_locked(
                conn,
                context,
                principal_id=authentication.principal_id,
                authority_domain=authentication.authority_domain,
            )
            recorded_at = context.recorded_at.to_text()
            self._persist_security_records(
                conn,
                authentication=authentication,
                request=authorization_request,
                decision=authorization,
                recorded_at=recorded_at,
            )
            request_bytes = canonical_json_bytes(request.canonical_value())
            request_digest = digest_bytes(request_bytes)
            attempt_value = self._attempt_value(
                request=request,
                context=context,
                failure=None,
                projection=context.projection,
                retrieval_contract_digest=retrieval_contract_digest,
                authentication=authentication,
                authorization_request=authorization_request,
                authorization=authorization,
            )
            attempt_bytes = canonical_json_bytes(attempt_value)
            attempt_digest = digest_bytes(attempt_bytes)
            try:
                conn.execute(
                    "INSERT INTO hybrid_retrieval_attempts("
                    "request_id,context_id,idempotency_key,request_digest,request_bytes,"
                    "fixture_id,query_revision_id,query_hypothesis_version_id,"
                    "query_valid_time,tool_name,tool_version,policy_digest,"
                    "retrieval_contract_digest,outcome,failure_code,generation_id,"
                    "projection_identity_digest,authority_watermark,context_digest,"
                    "authentication_context_id,authorization_request_digest,"
                    "authorization_decision_id,canonical_bytes,canonical_digest,recorded_at"
                    ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        str(request.request_id),
                        str(request.context_id),
                        request.idempotency_key,
                        request_digest,
                        request_bytes,
                        request.fixture_id,
                        request.query_revision_id,
                        request.query_hypothesis_version_id,
                        request.query_valid_time.to_text(),
                        context.tool_name,
                        context.tool_version,
                        context.policy_digest,
                        retrieval_contract_digest,
                        context.outcome.value,
                        None,
                        str(context.projection.identity.generation_id),
                        context.projection.identity.identity_digest,
                        context.projection.contiguous_ledger_seq,
                        context.context_digest,
                        str(authentication.authentication_context_id),
                        authorization_request.request_digest,
                        str(authorization.authorization_decision_id),
                        attempt_bytes,
                        attempt_digest,
                        recorded_at,
                    ),
                )
                context_bytes = canonical_json_bytes(context.canonical_value())
                conn.execute(
                    "INSERT INTO hybrid_retrieval_contexts_v2("
                    "context_id,request_id,context_digest,generation_id,family_id,"
                    "projection_identity_digest,contiguous_ledger_seq,open_gap_count,"
                    "dead_letter_count,policy_digest,query_digest,total_context_bytes,"
                    "truncated,canonical_bytes,canonical_digest,recorded_at"
                    ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        str(context.context_id),
                        str(context.request_id),
                        context.context_digest,
                        str(context.projection.identity.generation_id),
                        context.projection.identity.family_id,
                        context.projection.identity.identity_digest,
                        context.projection.contiguous_ledger_seq,
                        context.projection.open_gap_count,
                        context.projection.dead_letter_count,
                        context.policy_digest,
                        context.query_digest,
                        context.total_context_bytes,
                        int(context.truncated),
                        context_bytes,
                        context.context_digest,
                        recorded_at,
                    ),
                )
                for passage in context.hydrated_passages:
                    canonical = canonical_json_bytes(passage.canonical_value())
                    conn.execute(
                        "INSERT INTO hybrid_retrieval_context_hydrations("
                        "context_id,passage_id,admission_id,access_decision_id,"
                        "blob_digest,text_digest,hydration_policy_contract_digest,"
                        "byte_start,byte_end,rights_state,lifecycle_state,trust_scope,"
                        "canonical_bytes,canonical_digest"
                        ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            str(context.context_id),
                            passage.passage_id,
                            str(passage.admission_id),
                            str(passage.access_decision_id),
                            passage.blob_digest,
                            passage.text_digest,
                            passage.hydration_policy_contract_digest,
                            passage.byte_start,
                            passage.byte_end,
                            passage.rights_state,
                            passage.lifecycle_state,
                            passage.trust_scope.value,
                            canonical,
                            digest_bytes(canonical),
                        ),
                    )
            except sqlite3.IntegrityError as exc:
                raise IdempotencyConflict(
                    "retrieval identity collides with retained authority"
                ) from exc
        return FindRelatedEventCandidatesResult(
            request=request,
            context=context,
            failure=None,
            replayed=False,
        )

    def persist_failure_result(
        self,
        *,
        request: FindRelatedEventCandidatesRequest,
        failure: RetrievalFailure,
        retrieval_contract_digest: str,
        authentication: Any,
        authorization_request: Any,
        authorization: Any,
        projection: RetrievalProjectionMetadata | None = None,
    ) -> FindRelatedEventCandidatesResult:
        if (
            failure.request_id != request.request_id
            or failure.context_id != request.context_id
        ):
            raise RetrievalContractError("retrieval failure differs from request")
        if failure.policy_digest != self._retrieval_policy.contract_digest:
            raise RetrievalContractError("retrieval failure policy differs")
        if retrieval_contract_digest != self._retrieval_contract.contract_digest:
            raise RetrievalContractError("retrieval contract digest differs")
        if (
            projection is not None
            and projection.query_valid_time != request.query_valid_time
        ):
            raise RetrievalContractError(
                "retrieval failure projection time differs from request"
            )
        with self._lock, self._transaction() as conn:
            existing = self._existing_attempt_locked(conn, request)
            if existing is not None:
                return self._replay_result_locked(
                    conn,
                    row=existing,
                    request=request,
                    authentication=authentication,
                    authorization_request=authorization_request,
                    authorization=authorization,
                )
            security_checked_at = self._require_current_security_locked(
                request=request,
                authentication=authentication,
                authorization_request=authorization_request,
                authorization=authorization,
            )
            if (
                failure.recorded_at.value < authorization.decided_at.value
                or failure.recorded_at.value > security_checked_at.value
                or failure.recorded_at.value >= authentication.expires_at.value
            ):
                raise PermissionError(
                    "retrieval failure time is outside current security authority"
                )
            if projection is not None:
                self._require_current_projection_locked(conn, projection)
            recorded_at = failure.recorded_at.to_text()
            self._persist_security_records(
                conn,
                authentication=authentication,
                request=authorization_request,
                decision=authorization,
                recorded_at=recorded_at,
            )
            request_bytes = canonical_json_bytes(request.canonical_value())
            attempt_value = self._attempt_value(
                request=request,
                context=None,
                failure=failure,
                projection=projection,
                retrieval_contract_digest=retrieval_contract_digest,
                authentication=authentication,
                authorization_request=authorization_request,
                authorization=authorization,
            )
            attempt_bytes = canonical_json_bytes(attempt_value)
            try:
                conn.execute(
                    "INSERT INTO hybrid_retrieval_attempts("
                    "request_id,context_id,idempotency_key,request_digest,request_bytes,"
                    "fixture_id,query_revision_id,query_hypothesis_version_id,"
                    "query_valid_time,tool_name,tool_version,policy_digest,"
                    "retrieval_contract_digest,outcome,failure_code,generation_id,"
                    "projection_identity_digest,authority_watermark,context_digest,"
                    "authentication_context_id,authorization_request_digest,"
                    "authorization_decision_id,canonical_bytes,canonical_digest,recorded_at"
                    ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        str(request.request_id),
                        str(request.context_id),
                        request.idempotency_key,
                        digest_bytes(request_bytes),
                        request_bytes,
                        request.fixture_id,
                        request.query_revision_id,
                        request.query_hypothesis_version_id,
                        request.query_valid_time.to_text(),
                        "find_related_event_candidates",
                        "find-related-event-candidates-v1",
                        failure.policy_digest,
                        retrieval_contract_digest,
                        failure.outcome.value,
                        failure.reason_code,
                        None if projection is None else str(projection.identity.generation_id),
                        None if projection is None else projection.identity.identity_digest,
                        None if projection is None else projection.contiguous_ledger_seq,
                        None,
                        str(authentication.authentication_context_id),
                        authorization_request.request_digest,
                        str(authorization.authorization_decision_id),
                        attempt_bytes,
                        digest_bytes(attempt_bytes),
                        recorded_at,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise IdempotencyConflict(
                    "retrieval failure identity collides with retained authority"
                ) from exc
        return FindRelatedEventCandidatesResult(
            request=request,
            context=None,
            failure=failure,
            replayed=False,
        )

    def _require_current_security_locked(
        self,
        *,
        request: FindRelatedEventCandidatesRequest,
        authentication: Any,
        authorization_request: Any,
        authorization: Any,
    ) -> UtcTimestamp:
        now = self._clock()
        authentication.require_current(now)
        authorization.require_allowed()
        if (
            authorization_request.authentication_context_id
            != authentication.authentication_context_id
            or authorization_request.principal_id != authentication.principal_id
            or authorization_request.authority_domain
            != authentication.authority_domain
            or authorization.authentication_context_id
            != authentication.authentication_context_id
            or authorization.authorization_request_digest
            != authorization_request.request_digest
            or authorization.decided_at.value < authentication.authenticated_at.value
            or authorization.decided_at.value > now.value
        ):
            raise PermissionError(
                "retrieval security provenance is not current and exact"
            )
        require_exact_retrieval_authorization_value(
            value=authorization_request.canonical_value(),
            authentication_context_id=str(
                authentication.authentication_context_id
            ),
            principal_id=authentication.principal_id,
            authority_domain=authentication.authority_domain,
            request=request,
            policy=self._retrieval_policy,
            retrieval_contract=self._retrieval_contract,
        )
        expected_scope_digest = digest_canonical(
            {
                "authentication_context_digest": authentication.digest,
                "effective_scopes": list(authorization.effective_scopes),
            }
        )
        if (
            RETRIEVAL_REQUIRED_SCOPE not in authorization.effective_scopes
            or authorization.effective_scope_digest != expected_scope_digest
        ):
            raise PermissionError(
                "retrieval authorization no longer contains exact scope evidence"
            )
        return now

    def _require_current_projection_locked(
        self,
        conn: sqlite3.Connection,
        projection: RetrievalProjectionMetadata,
    ) -> None:
        generation_id = str(projection.identity.generation_id)
        row = conn.execute(
            "SELECT family_id,state FROM projection_generations WHERE generation_id=?",
            (generation_id,),
        ).fetchone()
        if (
            row is None
            or str(row["family_id"]) != projection.identity.family_id
            or str(row["state"]) != ProjectionGenerationState.ACTIVE.value
        ):
            raise RetrievalStateError("retrieval generation authority changed")
        active_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM projection_generations "
                "WHERE family_id=? AND state='ACTIVE'",
                (projection.identity.family_id,),
            ).fetchone()[0]
        )
        if active_count != 1:
            raise RetrievalStateError("retrieval family ACTIVE authority changed")
        checkpoint = self._checkpoint_seq(conn, generation_id)
        open_gaps = int(
            conn.execute(
                "SELECT COUNT(*) FROM projection_gaps "
                "WHERE generation_id=? AND state='OPEN'",
                (generation_id,),
            ).fetchone()[0]
        )
        dead_letters = int(
            conn.execute(
                "SELECT COUNT(*) FROM projection_dead_letters WHERE generation_id=?",
                (generation_id,),
            ).fetchone()[0]
        )
        latest = int(
            conn.execute(
                "SELECT COALESCE(MAX(ledger_seq),0) FROM ledger_events "
                "WHERE security_scope NOT IN ('authority.projection','authority.candidate')"
            ).fetchone()[0]
        )
        validation = conn.execute(
            "SELECT checkpoint_ledger_seq,recorded_at "
            "FROM projection_generation_validations "
            "WHERE generation_id=?",
            (generation_id,),
        ).fetchone()
        if dead_letters != 0:
            raise RetrievalStateError(
                "retrieval projection has an unresolved dead letter"
            )
        if open_gaps != 0:
            raise RetrievalStateError(
                "retrieval projection has an unresolved required gap"
            )
        if latest != projection.contiguous_ledger_seq:
            raise RetrievalStateError(
                "retrieval source watermark is stale"
            )
        if (
            checkpoint != projection.contiguous_ledger_seq
            or validation is None
            or int(validation["checkpoint_ledger_seq"])
            != projection.contiguous_ledger_seq
        ):
            raise RetrievalStateError(
                "retrieval projection changed before context authority commit"
            )
        validation_recorded_at = UtcTimestamp.parse(
            str(validation["recorded_at"])
        )
        expected_window_start = self._retrieval_policy.date_window_start(
            projection.query_valid_time
        )
        expected_freshness_deadline = (
            self._retrieval_policy.projection_freshness_deadline(
                validation_recorded_at
            )
        )
        if (
            projection.validation_recorded_at != validation_recorded_at
            or projection.date_window_start != expected_window_start
            or projection.freshness_deadline != expected_freshness_deadline
        ):
            raise RetrievalStateError(
                "retrieval projection temporal authority changed"
            )
        now = self._clock()
        if now.value < max(
            projection.serving_time.value,
            projection.query_valid_time.value,
            validation_recorded_at.value,
        ):
            raise RetrievalStateError(
                "retrieval authority clock moved backwards"
            )
        if now.value > expected_freshness_deadline.value:
            raise RetrievalStateError(
                "retrieval projection freshness is stale"
            )
        identity, _complete, _fulltext, _vector, _fixture = (
            self.complete_projection_contracts(projection.identity.generation_id)
        )
        if identity != projection.identity:
            raise RetrievalStateError("retrieval projection identity changed")

    def _validate_hydrations_locked(
        self,
        conn: sqlite3.Connection,
        context: RetrievalContextV2,
        *,
        principal_id: str,
        authority_domain: str,
    ) -> None:
        now = self._clock()
        for passage in context.hydrated_passages:
            admission = self._current_admission_row(
                conn,
                str(passage.admission_id),
                now=now,
                require_active=True,
                require_bytes=True,
            )
            if (
                str(admission["blob_digest"]) != passage.blob_digest
                or str(admission["state"]) != AdmissionState.ACTIVE.value
            ):
                raise RetrievalStateError(
                    "hydrated passage authority changed before context commit"
                )
            access = conn.execute(
                "SELECT * FROM object_access_decisions WHERE access_decision_id=?",
                (str(passage.access_decision_id),),
            ).fetchone()
            if access is None:
                raise RetrievalStateError("hydrated passage access decision is missing")
            if (
                str(access["admission_id"]) != str(passage.admission_id)
                or str(access["hydration_policy_contract_digest"])
                != passage.hydration_policy_contract_digest
                or int(access["byte_offset"]) != passage.byte_start
                or int(access["allowed_bytes"])
                != passage.byte_end - passage.byte_start
                or str(access["principal_id"]) != principal_id
                or str(access["authority_domain"]) != authority_domain
                or str(access["purpose"]) != "project.discovery"
            ):
                raise RetrievalStateError(
                    "hydrated passage differs from its access decision"
                )
            blob = self._blob_lifecycle_row(passage.blob_digest, conn=conn)
            blob_state = str(blob["state"])
            if blob_state not in {
                BlobLifecycleState.INSTALLED.value,
                BlobLifecycleState.ACTIVE.value,
            }:
                raise RetrievalStateError("hydrated passage blob is not current")
            cutoff = self._decode_retrieval_canonical(
                bytes(access["state_cutoff_bytes"]),
                identity="retrieval hydration state cutoff",
            )
            if (
                cutoff.get("admission_state")
                != AdmissionState.ACTIVE.value
                or cutoff.get("blob_state") != blob_state
                or passage.rights_state != "PERMITTED"
                or passage.lifecycle_state != blob_state
                or passage.trust_scope is not TrustScope.OBSERVED
            ):
                raise RetrievalStateError(
                    "hydrated passage retained an invalid authority state"
                )
            expected = INTEGRATED_FIXTURE_V2.passage_by_id.get(passage.passage_id)
            if (
                expected is None
                or expected.blob_digest != passage.blob_digest
                or expected.text != passage.text
                or expected.language != passage.language
            ):
                raise RetrievalStateError(
                    "hydrated passage differs from checked fixture authority"
                )

    def _attempt_value(
        self,
        *,
        request: FindRelatedEventCandidatesRequest,
        context: RetrievalContextV2 | None,
        failure: RetrievalFailure | None,
        projection: RetrievalProjectionMetadata | None,
        retrieval_contract_digest: str,
        authentication: Any,
        authorization_request: Any,
        authorization: Any,
    ) -> dict[str, object]:
        if (context is None) == (failure is None):
            raise RetrievalContractError(
                "retrieval attempt requires exactly one context or failure"
            )
        selected_projection = context.projection if context is not None else projection
        result_value = (
            context.canonical_value()
            if context is not None
            else failure.canonical_value()  # type: ignore[union-attr]
        )
        return {
            "contract": _ATTEMPT_CONTRACT,
            "request": request.canonical_value(),
            "tool_name": (
                context.tool_name if context is not None else _TOOL_NAME
            ),
            "tool_version": (
                context.tool_version if context is not None else _TOOL_VERSION
            ),
            "policy_digest": (
                context.policy_digest
                if context is not None
                else failure.policy_digest  # type: ignore[union-attr]
            ),
            "retrieval_contract_digest": retrieval_contract_digest,
            "projection": (
                None
                if selected_projection is None
                else selected_projection.canonical_value()
            ),
            "result": result_value,
            "authentication_context_id": str(
                authentication.authentication_context_id
            ),
            "authorization_request_digest": authorization_request.request_digest,
            "authorization_decision_id": str(
                authorization.authorization_decision_id
            ),
            "recorded_at": (
                context.recorded_at.to_text()
                if context is not None
                else failure.recorded_at.to_text()  # type: ignore[union-attr]
            ),
        }

    def _result_from_attempt_row(
        self,
        row: sqlite3.Row,
        *,
        replayed: bool,
    ) -> FindRelatedEventCandidatesResult:
        attempt = self._canonical_row(row, identity="hybrid retrieval attempt")
        if frozenset(attempt) != _ATTEMPT_KEYS:
            raise AuthorityPersistenceError("retrieval attempt inventory differs")
        if attempt.get("contract") != _ATTEMPT_CONTRACT:
            raise AuthorityPersistenceError("retrieval attempt contract differs")

        request = self._request_from_value(attempt.get("request"))
        request_bytes = canonical_json_bytes(request.canonical_value())
        request_digest = digest_bytes(request_bytes)
        tool_name = str(attempt.get("tool_name"))
        tool_version = str(attempt.get("tool_version"))
        policy_digest = str(attempt.get("policy_digest"))
        retrieval_contract_digest = str(
            attempt.get("retrieval_contract_digest")
        )
        if tool_name != _TOOL_NAME or tool_version != _TOOL_VERSION:
            raise AuthorityPersistenceError("retrieval attempt tool identity differs")
        if policy_digest != self._retrieval_policy.contract_digest:
            raise AuthorityPersistenceError("retrieval attempt policy differs")
        if (
            retrieval_contract_digest
            != self._retrieval_contract.contract_digest
        ):
            raise AuthorityPersistenceError(
                "retrieval attempt contract digest differs"
            )

        projection_value = attempt.get("projection")
        projection = (
            None
            if projection_value is None
            else self._projection_from_value(projection_value)
        )
        recorded_at = UtcTimestamp.parse(str(attempt.get("recorded_at")))
        authentication_context_id = str(
            attempt.get("authentication_context_id")
        )
        authorization_request_digest = str(
            attempt.get("authorization_request_digest")
        )
        authorization_decision_id = str(
            attempt.get("authorization_decision_id")
        )
        self._validate_attempt_security_locked(
            self._connection,
            request=request,
            authentication_context_id=authentication_context_id,
            authorization_request_digest=authorization_request_digest,
            authorization_decision_id=authorization_decision_id,
            recorded_at=recorded_at,
        )

        outcome = RetrievalOutcome(str(row["outcome"]))
        context_row = self._connection.execute(
            "SELECT * FROM hybrid_retrieval_contexts_v2 WHERE request_id=?",
            (str(request.request_id),),
        ).fetchone()
        if outcome is RetrievalOutcome.COMPLETE:
            if context_row is None:
                raise AuthorityPersistenceError(
                    "complete retrieval context is missing"
                )
            context = self._context_from_bytes(
                bytes(context_row["canonical_bytes"]),
                expected_digest=str(context_row["canonical_digest"]),
            )
            if attempt.get("result") != context.canonical_value():
                raise AuthorityPersistenceError(
                    "retrieval attempt context differs"
                )
            if projection != context.projection:
                raise AuthorityPersistenceError(
                    "retrieval attempt projection differs from context"
                )
            if context.recorded_at != recorded_at:
                raise AuthorityPersistenceError(
                    "retrieval attempt context time differs"
                )
            if (
                context.request_id != request.request_id
                or context.context_id != request.context_id
                or context.projection.query_valid_time
                != request.query_valid_time
            ):
                raise AuthorityPersistenceError(
                    "retrieval context request linkage differs"
                )
            failure = None
            failure_code: str | None = None
            context_digest: str | None = context.context_digest
        else:
            if context_row is not None:
                raise AuthorityPersistenceError(
                    "failed retrieval unexpectedly retained a context"
                )
            context = None
            failure = self._failure_from_value(attempt.get("result"))
            if attempt.get("result") != failure.canonical_value():
                raise AuthorityPersistenceError(
                    "retrieval attempt failure differs"
                )
            if (
                failure.outcome is not outcome
                or failure.request_id != request.request_id
                or failure.context_id != request.context_id
                or failure.policy_digest != policy_digest
                or failure.recorded_at != recorded_at
            ):
                raise AuthorityPersistenceError(
                    "retrieval failure linkage differs"
                )
            failure_code = failure.reason_code
            context_digest = None

        expected_projection = projection
        expected = {
            "request_id": str(request.request_id),
            "context_id": str(request.context_id),
            "idempotency_key": request.idempotency_key,
            "request_digest": request_digest,
            "request_bytes": request_bytes,
            "fixture_id": request.fixture_id,
            "query_revision_id": request.query_revision_id,
            "query_hypothesis_version_id": (
                request.query_hypothesis_version_id
            ),
            "query_valid_time": request.query_valid_time.to_text(),
            "tool_name": tool_name,
            "tool_version": tool_version,
            "policy_digest": policy_digest,
            "retrieval_contract_digest": retrieval_contract_digest,
            "outcome": outcome.value,
            "failure_code": failure_code,
            "generation_id": (
                None
                if expected_projection is None
                else str(expected_projection.identity.generation_id)
            ),
            "projection_identity_digest": (
                None
                if expected_projection is None
                else expected_projection.identity.identity_digest
            ),
            "authority_watermark": (
                None
                if expected_projection is None
                else expected_projection.contiguous_ledger_seq
            ),
            "context_digest": context_digest,
            "authentication_context_id": authentication_context_id,
            "authorization_request_digest": authorization_request_digest,
            "authorization_decision_id": authorization_decision_id,
            "recorded_at": recorded_at.to_text(),
        }
        for key, expected_value in expected.items():
            actual = row[key]
            if key in {"request_bytes"}:
                actual = bytes(actual)
            if actual != expected_value:
                raise AuthorityPersistenceError(
                    f"retrieval attempt normalized {key} differs"
                )

        return FindRelatedEventCandidatesResult(
            request=request,
            context=context,
            failure=failure,
            replayed=replayed,
        )

    def _validate_attempt_security_locked(
        self,
        conn: sqlite3.Connection,
        *,
        request: FindRelatedEventCandidatesRequest,
        authentication_context_id: str,
        authorization_request_digest: str,
        authorization_decision_id: str,
        recorded_at: UtcTimestamp,
    ) -> None:
        authentication_row = conn.execute(
            "SELECT * FROM authentication_contexts "
            "WHERE authentication_context_id=?",
            (authentication_context_id,),
        ).fetchone()
        request_row = conn.execute(
            "SELECT * FROM authorization_requests WHERE request_digest=?",
            (authorization_request_digest,),
        ).fetchone()
        decision_row = conn.execute(
            "SELECT * FROM authorization_decisions "
            "WHERE authorization_decision_id=?",
            (authorization_decision_id,),
        ).fetchone()
        if (
            authentication_row is None
            or request_row is None
            or decision_row is None
        ):
            raise AuthorityPersistenceError(
                "retrieval security provenance is incomplete"
            )

        authentication = self._authentication_record_from_row(
            authentication_row
        )
        authorization_request = self._request_record_from_row(request_row)
        authorization_decision = self._decision_record_from_row(decision_row)
        request_value = self._decode_retrieval_canonical(
            authorization_request.canonical_bytes,
            identity="retrieval authorization request",
        )
        try:
            require_exact_retrieval_authorization_value(
                value=request_value,
                authentication_context_id=(
                    authentication.authentication_context_id
                ),
                principal_id=authentication.principal_id,
                authority_domain=authentication.authority_domain,
                request=request,
                policy=self._retrieval_policy,
                retrieval_contract=self._retrieval_contract,
            )
        except ValueError as exc:
            raise AuthorityPersistenceError(str(exc)) from exc

        authenticated_at = UtcTimestamp.parse(authentication.authenticated_at)
        expires_at = UtcTimestamp.parse(authentication.expires_at)
        decided_at = UtcTimestamp.parse(authorization_decision.decided_at)
        expected_scope_digest = digest_canonical(
            {
                "authentication_context_digest": (
                    authentication.canonical_digest
                ),
                "effective_scopes": list(
                    authorization_decision.effective_scopes
                ),
            }
        )
        if (
            authorization_request.authentication_context_id
            != authentication.authentication_context_id
            or authorization_request.principal_id
            != authentication.principal_id
            or authorization_request.authority_domain
            != authentication.authority_domain
            or authorization_request.request_digest
            != authorization_request_digest
            or authorization_decision.authentication_context_id
            != authentication.authentication_context_id
            or authorization_decision.authorization_request_digest
            != authorization_request_digest
            or authorization_decision.authorization_decision_id
            != authorization_decision_id
            or not authorization_decision.allowed
            or RETRIEVAL_REQUIRED_SCOPE
            not in authorization_decision.effective_scopes
            or authorization_decision.effective_scope_digest
            != expected_scope_digest
            or decided_at.value < authenticated_at.value
            or decided_at.value >= expires_at.value
            or recorded_at.value < decided_at.value
            or recorded_at.value >= expires_at.value
        ):
            raise AuthorityPersistenceError(
                "retrieval security provenance is not bound to the exact read"
            )

    def _validate_retrieval_integrity(self) -> None:
        with self._lock:
            conn = self._connection
            complete_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM hybrid_retrieval_attempts "
                    "WHERE outcome='COMPLETE'"
                ).fetchone()[0]
            )
            context_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM hybrid_retrieval_contexts_v2"
                ).fetchone()[0]
            )
            if complete_count != context_count:
                raise AuthorityPersistenceError(
                    "complete retrieval attempts and contexts differ"
                )
            for row in conn.execute(
                "SELECT * FROM hybrid_retrieval_attempts "
                "ORDER BY recorded_at,request_id"
            ).fetchall():
                result = self._result_from_attempt_row(row, replayed=False)
                if result.context is not None:
                    self._validate_context_row(
                        conn,
                        result.context,
                        attempt_row=row,
                    )
            dangling = conn.execute(
                "SELECT h.context_id FROM hybrid_retrieval_context_hydrations h "
                "LEFT JOIN hybrid_retrieval_contexts_v2 c "
                "ON c.context_id=h.context_id WHERE c.context_id IS NULL LIMIT 1"
            ).fetchone()
            if dangling is not None:
                raise AuthorityPersistenceError("retrieval hydration is orphaned")

    def _validate_context_row(
        self,
        conn: sqlite3.Connection,
        context: RetrievalContextV2,
        *,
        attempt_row: sqlite3.Row,
    ) -> None:
        row = conn.execute(
            "SELECT * FROM hybrid_retrieval_contexts_v2 WHERE context_id=?",
            (str(context.context_id),),
        ).fetchone()
        if row is None:
            raise AuthorityPersistenceError("retrieval context row is missing")
        if context.outcome is not RetrievalOutcome.COMPLETE:
            raise AuthorityPersistenceError(
                "retained retrieval context is not COMPLETE"
            )
        if (
            context.tool_name != self._retrieval_policy.tool_name
            or context.tool_version != self._retrieval_policy.tool_version
            or context.policy_digest != self._retrieval_policy.contract_digest
        ):
            raise AuthorityPersistenceError(
                "retrieval context retained policy identity differs"
            )

        identity, _complete, _fulltext, _vector, _fixture = (
            self.complete_projection_contracts(
                context.projection.identity.generation_id
            )
        )
        if identity != context.projection.identity:
            raise AuthorityPersistenceError(
                "retrieval context projection contracts differ"
            )
        expected_query_digest = self._retrieval_contract.query_digest(
            generation_identity_digest=identity.identity_digest,
            query_valid_time=context.projection.query_valid_time.to_text(),
            watermark=context.projection.contiguous_ledger_seq,
        )
        if context.query_digest != expected_query_digest:
            raise AuthorityPersistenceError(
                "retrieval context query identity differs"
            )
        validate_fixture_branch_executions(
            executions=context.branches,
            policy=self._retrieval_policy,
            contract=self._retrieval_contract,
            query_digest=context.query_digest,
        )
        retained, exclusions = fuse_fixture_candidates(
            executions=context.branches,
            policy=self._retrieval_policy,
            fixture=self._retrieval_contract,
        )
        if (
            retained != context.retained_candidates
            or exclusions != context.exclusions
        ):
            raise AuthorityPersistenceError(
                "retrieval context fusion evidence differs"
            )
        expected_passage_ids = tuple(
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
        if tuple(
            passage.passage_id for passage in context.hydrated_passages
        ) != expected_passage_ids:
            raise AuthorityPersistenceError(
                "retrieval context hydration coverage differs"
            )
        if context.total_context_bytes != sum(
            len(passage.text.encode("utf-8"))
            for passage in context.hydrated_passages
        ):
            raise AuthorityPersistenceError(
                "retrieval context factual byte accounting differs"
            )
        if (
            len(canonical_json_bytes(context.canonical_value()))
            > self._retrieval_policy.response_byte_limit
        ):
            raise AuthorityPersistenceError(
                "retrieval context exceeds retained response bound"
            )

        expected = {
            "request_id": str(context.request_id),
            "context_digest": context.context_digest,
            "generation_id": str(context.projection.identity.generation_id),
            "family_id": context.projection.identity.family_id,
            "projection_identity_digest": (
                context.projection.identity.identity_digest
            ),
            "contiguous_ledger_seq": (
                context.projection.contiguous_ledger_seq
            ),
            "open_gap_count": context.projection.open_gap_count,
            "dead_letter_count": context.projection.dead_letter_count,
            "policy_digest": context.policy_digest,
            "query_digest": context.query_digest,
            "total_context_bytes": context.total_context_bytes,
            "truncated": int(context.truncated),
            "canonical_bytes": canonical_json_bytes(
                context.canonical_value()
            ),
            "canonical_digest": context.context_digest,
            "recorded_at": context.recorded_at.to_text(),
        }
        for key, value in expected.items():
            actual = row[key]
            if key == "canonical_bytes":
                actual = bytes(actual)
            if actual != value:
                raise AuthorityPersistenceError(
                    f"retrieval context normalized {key} differs"
                )

        authentication = conn.execute(
            "SELECT principal_id,authority_domain "
            "FROM authentication_contexts "
            "WHERE authentication_context_id=?",
            (str(attempt_row["authentication_context_id"]),),
        ).fetchone()
        if authentication is None:
            raise AuthorityPersistenceError(
                "retrieval authentication context is missing"
            )
        principal_id = str(authentication["principal_id"])
        authority_domain = str(authentication["authority_domain"])

        hydration_rows = conn.execute(
            "SELECT * FROM hybrid_retrieval_context_hydrations "
            "WHERE context_id=? ORDER BY passage_id",
            (str(context.context_id),),
        ).fetchall()
        if len(hydration_rows) != len(context.hydrated_passages):
            raise AuthorityPersistenceError(
                "retrieval hydration inventory differs"
            )
        for hydration_row, passage in zip(
            hydration_rows,
            context.hydrated_passages,
            strict=True,
        ):
            canonical = canonical_json_bytes(passage.canonical_value())
            expected_hydration = {
                "passage_id": passage.passage_id,
                "admission_id": str(passage.admission_id),
                "access_decision_id": str(passage.access_decision_id),
                "blob_digest": passage.blob_digest,
                "text_digest": passage.text_digest,
                "hydration_policy_contract_digest": (
                    passage.hydration_policy_contract_digest
                ),
                "byte_start": passage.byte_start,
                "byte_end": passage.byte_end,
                "rights_state": passage.rights_state,
                "lifecycle_state": passage.lifecycle_state,
                "trust_scope": passage.trust_scope.value,
                "canonical_bytes": canonical,
                "canonical_digest": digest_bytes(canonical),
            }
            for key, value in expected_hydration.items():
                actual = hydration_row[key]
                if key == "canonical_bytes":
                    actual = bytes(actual)
                if actual != value:
                    raise AuthorityPersistenceError(
                        f"retrieval hydration normalized {key} differs"
                    )

            fixture_passage = INTEGRATED_FIXTURE_V2.passage_by_id.get(
                passage.passage_id
            )
            if (
                fixture_passage is None
                or fixture_passage.blob_digest != passage.blob_digest
                or fixture_passage.language != passage.language
                or fixture_passage.text != passage.text
                or fixture_passage.canonical_bytes
                != passage.text.encode("utf-8")
            ):
                raise AuthorityPersistenceError(
                    "retrieval hydration differs from fixture authority"
                )
            decision = self.access_decision_view(passage.access_decision_id)
            if (
                decision.admission_id != passage.admission_id
                or decision.policy_contract_digest
                != passage.hydration_policy_contract_digest
                or decision.offset != passage.byte_start
                or decision.allowed_bytes
                != passage.byte_end - passage.byte_start
                or decision.principal_id != principal_id
                or decision.authority_domain != authority_domain
                or decision.purpose != "project.discovery"
                or decision.decided_at.value > context.recorded_at.value
            ):
                raise AuthorityPersistenceError(
                    "retrieval hydration access decision differs"
                )
            cutoff = self._decode_retrieval_canonical(
                decision.state_cutoff_bytes,
                identity="retrieval hydration state cutoff",
            )
            if (
                cutoff.get("admission_id") != str(passage.admission_id)
                or cutoff.get("admission_state")
                != AdmissionState.ACTIVE.value
                or cutoff.get("blob_digest") != passage.blob_digest
                or cutoff.get("blob_state")
                not in {
                    BlobLifecycleState.INSTALLED.value,
                    BlobLifecycleState.ACTIVE.value,
                }
                or cutoff.get("offset") != passage.byte_start
                or cutoff.get("length")
                != passage.byte_end - passage.byte_start
                or passage.rights_state != "PERMITTED"
                or passage.lifecycle_state != cutoff.get("blob_state")
                or passage.trust_scope is not TrustScope.OBSERVED
            ):
                raise AuthorityPersistenceError(
                    "retrieval hydration state cutoff differs"
                )

    @staticmethod
    def _decode_retrieval_canonical(data: bytes, *, identity: str) -> dict[str, Any]:
        try:
            value = json.loads(data.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise AuthorityPersistenceError(f"{identity} is invalid JSON") from exc
        if not isinstance(value, dict) or canonical_json_bytes(value) != data:
            raise AuthorityPersistenceError(f"{identity} is not canonical")
        return value

    @classmethod
    def _canonical_row(cls, row: sqlite3.Row, *, identity: str) -> dict[str, Any]:
        data = bytes(row["canonical_bytes"])
        if digest_bytes(data) != str(row["canonical_digest"]):
            raise AuthorityPersistenceError(f"{identity} digest differs")
        return cls._decode_retrieval_canonical(data, identity=identity)

    @classmethod
    def _request_from_bytes(cls, data: bytes) -> FindRelatedEventCandidatesRequest:
        return cls._request_from_value(cls._decode_retrieval_canonical(data, identity="retrieval request"))

    @staticmethod
    def _request_from_value(value: object) -> FindRelatedEventCandidatesRequest:
        if not isinstance(value, dict):
            raise AuthorityPersistenceError("retrieval request is not an object")
        return FindRelatedEventCandidatesRequest(
            request_id=RetrievalRequestId.parse(str(value["request_id"])),
            context_id=RetrievalContextV2Id.parse(str(value["context_id"])),
            fixture_id=str(value["fixture_id"]),
            query_revision_id=str(value["query_revision_id"]),
            query_hypothesis_version_id=str(value["query_hypothesis_version_id"]),
            query_valid_time=UtcTimestamp.parse(str(value["query_valid_time"])),
            idempotency_key=str(value["idempotency_key"]),
        )

    @classmethod
    def _context_from_bytes(
        cls,
        data: bytes,
        *,
        expected_digest: str,
    ) -> RetrievalContextV2:
        if digest_bytes(data) != expected_digest:
            raise AuthorityPersistenceError("retrieval context digest differs")
        value = cls._decode_retrieval_canonical(data, identity="retrieval context")
        if value.get("contract") != "newsroom-retrieval-context-v2":
            raise AuthorityPersistenceError("retrieval context contract differs")
        projection = cls._projection_from_value(value.get("projection"))
        branches = tuple(
            cls._execution_from_value(item)
            for item in cls._list(value.get("branches"), "branches")
        )
        candidates = tuple(
            cls._candidate_from_value(item)
            for item in cls._list(value.get("retained_candidates"), "candidates")
        )
        exclusions = tuple(
            cls._exclusion_from_value(item)
            for item in cls._list(value.get("exclusions"), "exclusions")
        )
        hydrated = tuple(
            cls._hydrated_from_value(item)
            for item in cls._list(value.get("hydrated_passages"), "hydrations")
        )
        context = RetrievalContextV2(
            context_id=RetrievalContextV2Id.parse(str(value["context_id"])),
            request_id=RetrievalRequestId.parse(str(value["request_id"])),
            tool_name=str(value["tool_name"]),
            tool_version=str(value["tool_version"]),
            policy_digest=str(value["policy_digest"]),
            query_digest=str(value["query_digest"]),
            outcome=RetrievalOutcome(str(value["outcome"])),
            projection=projection,
            branches=branches,
            retained_candidates=candidates,
            exclusions=exclusions,
            hydrated_passages=hydrated,
            total_context_bytes=int(value["total_context_bytes"]),
            truncated=bool(value["truncated"]),
            recorded_at=UtcTimestamp.parse(str(value["recorded_at"])),
        )
        if context.context_digest != expected_digest:
            raise AuthorityPersistenceError("retrieval context canonical identity differs")
        return context

    @classmethod
    def _projection_from_value(
        cls,
        value: object,
    ) -> RetrievalProjectionMetadata:
        projection_value = cls._mapping(value, "projection")
        identity_value = cls._mapping(projection_value.get("identity"), "identity")
        identity = CompleteProjectionIdentity(
            generation_id=ProjectionGenerationId.parse(
                str(identity_value["generation_id"])
            ),
            family_id=str(identity_value["family_id"]),
            family_definition_version=str(identity_value["family_definition_version"]),
            projector_version=str(identity_value["projector_version"]),
            ontology_contract_digest=str(identity_value["ontology_contract_digest"]),
            mapping_contract_digest=str(identity_value["mapping_contract_digest"]),
            complete_contract_digest=str(identity_value["complete_contract_digest"]),
            fulltext_contract_digest=str(identity_value["fulltext_contract_digest"]),
            vector_contract_digest=str(identity_value["vector_contract_digest"]),
            fixture_vector_manifest_digest=str(
                identity_value["fixture_vector_manifest_digest"]
            ),
        )
        return RetrievalProjectionMetadata(
            identity=identity,
            generation_state=ProjectionGenerationState(
                str(projection_value["generation_state"])
            ),
            contiguous_ledger_seq=int(projection_value["contiguous_ledger_seq"]),
            open_gap_count=int(projection_value["open_gap_count"]),
            dead_letter_count=int(projection_value["dead_letter_count"]),
            validation_recorded_at=UtcTimestamp.parse(
                str(projection_value["validation_recorded_at"])
            ),
            date_window_start=UtcTimestamp.parse(
                str(projection_value["date_window_start"])
            ),
            query_valid_time=UtcTimestamp.parse(
                str(projection_value["query_valid_time"])
            ),
            freshness_deadline=UtcTimestamp.parse(
                str(projection_value["freshness_deadline"])
            ),
            serving_time=UtcTimestamp.parse(str(projection_value["serving_time"])),
            authoritative_system=str(projection_value["authoritative_system"]),
            projection_role=str(projection_value["projection_role"]),
        )

    @classmethod
    def _hit_from_value(cls, value: object) -> RetrievalBranchHit:
        item = cls._mapping(value, "branch hit")
        return RetrievalBranchHit(
            branch=RetrievalBranch(str(item["branch"])),
            query_id=str(item["query_id"]),
            query_digest=str(item["query_digest"]),
            rank=int(item["rank"]),
            raw_score=str(item["raw_score"]),
            result_key=str(item["result_key"]),
            dependency_root_id=str(item["dependency_root_id"]),
            passage_id=(None if item.get("passage_id") is None else str(item["passage_id"])),
            trust_scope=TrustScope(str(item["trust_scope"])),
            source_kind=str(item["source_kind"]),
            source_identity=str(item["source_identity"]),
        )

    @classmethod
    def _execution_from_value(cls, value: object) -> RetrievalBranchExecution:
        item = cls._mapping(value, "branch execution")
        return RetrievalBranchExecution(
            branch=RetrievalBranch(str(item["branch"])),
            query_id=str(item["query_id"]),
            query_digest=str(item["query_digest"]),
            result_limit=int(item["result_limit"]),
            elapsed_ms=int(item["elapsed_ms"]),
            hits=tuple(cls._hit_from_value(hit) for hit in cls._list(item.get("hits"), "hits")),
        )

    @classmethod
    def _candidate_from_value(cls, value: object) -> FusedRetrievalCandidate:
        item = cls._mapping(value, "candidate")
        score = cls._mapping(item.get("score"), "candidate score")
        return FusedRetrievalCandidate(
            dependency_root_id=str(item["dependency_root_id"]),
            candidate_version_id=(
                None if item.get("candidate_version_id") is None else str(item["candidate_version_id"])
            ),
            contributing_branches=tuple(
                RetrievalBranch(str(branch))
                for branch in cls._list(item.get("contributing_branches"), "candidate branches")
            ),
            branch_hits=tuple(
                cls._hit_from_value(hit)
                for hit in cls._list(item.get("branch_hits"), "candidate hits")
            ),
            dependency_ids=tuple(str(value) for value in cls._list(item.get("dependency_ids"), "dependencies")),
            score=ReciprocalRankScore(
                numerator=int(score["numerator"]),
                denominator=int(score["denominator"]),
            ),
            final_rank=int(item["final_rank"]),
        )

    @classmethod
    def _exclusion_from_value(cls, value: object) -> RetrievalExclusion:
        item = cls._mapping(value, "exclusion")
        return RetrievalExclusion(
            dependency_root_id=str(item["dependency_root_id"]),
            reason=RetrievalExclusionReason(str(item["reason"])),
            branch_hits=tuple(
                cls._hit_from_value(hit)
                for hit in cls._list(item.get("branch_hits"), "exclusion hits")
            ),
            detail=str(item["detail"]),
        )

    @classmethod
    def _hydrated_from_value(cls, value: object) -> HydratedRetrievalPassage:
        item = cls._mapping(value, "hydrated passage")
        return HydratedRetrievalPassage(
            passage_id=str(item["passage_id"]),
            admission_id=ObjectAdmissionId.parse(str(item["admission_id"])),
            blob_digest=str(item["blob_digest"]),
            language=str(item["language"]),
            text=str(item["text"]),
            text_digest=str(item["text_digest"]),
            hydration_policy_contract_digest=str(item["hydration_policy_contract_digest"]),
            access_decision_id=ObjectAccessDecisionId.parse(str(item["access_decision_id"])),
            byte_start=int(item["byte_start"]),
            byte_end=int(item["byte_end"]),
            rights_state=str(item["rights_state"]),
            lifecycle_state=str(item["lifecycle_state"]),
            trust_scope=TrustScope(str(item["trust_scope"])),
        )

    @staticmethod
    def _failure_from_value(value: object) -> RetrievalFailure:
        if not isinstance(value, dict):
            raise AuthorityPersistenceError("retrieval failure is not an object")
        return RetrievalFailure(
            request_id=RetrievalRequestId.parse(str(value["request_id"])),
            context_id=RetrievalContextV2Id.parse(str(value["context_id"])),
            outcome=RetrievalOutcome(str(value["outcome"])),
            reason_code=str(value["reason_code"]),
            policy_digest=str(value["policy_digest"]),
            recorded_at=UtcTimestamp.parse(str(value["recorded_at"])),
        )

    @staticmethod
    def _mapping(value: object, identity: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise AuthorityPersistenceError(f"{identity} is not an object")
        return value

    @staticmethod
    def _list(value: object, identity: str) -> list[Any]:
        if not isinstance(value, list):
            raise AuthorityPersistenceError(f"{identity} is not an array")
        return value


__all__ = ["_HybridRetrievalAuthorityStore"]
