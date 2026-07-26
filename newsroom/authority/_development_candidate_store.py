from __future__ import annotations

import json
import sqlite3
from typing import Any

from newsroom.increment2.models import (
    DevelopmentCandidateAdmissionRequest,
    DevelopmentCandidateAdmissionView,
    DevelopmentCandidateManifest,
    INTEGRATED_FIXTURE_V2_DEVELOPMENT_CANDIDATE,
)
from newsroom.increment2.policy import DEVELOPMENT_CANDIDATE_ADMISSION_COMMAND
from newsroom.integrated.models import (
    CandidateAdmissionDecisionId,
    CandidateAdmissionOutcome,
    CandidateRoute,
    IntegratedContractError,
    IntegratedFixtureId,
    IntegratedTriageProposalId,
    StoryCandidateId,
    StoryCandidateVersionId,
)
from newsroom.relations import RelationCurrentState, RelationPredicate
from newsroom.retrieval import (
    INTEGRATED_FIXTURE_V2_RETRIEVAL,
    RetrievalBranch,
    RetrievalContextV2,
    RetrievalContextV2Id,
    RetrievalOutcome,
)
from newsroom.retrieval.fixture_v2 import validate_fixture_branch_executions
from newsroom.retrieval.fusion import fuse_fixture_candidates

from ._capability import _AuthorizedCommandGrant
from ._retrieval_store import _HybridRetrievalAuthorityStore
from .canonical import canonical_json_bytes, digest_bytes, validate_sha256_digest
from .persistence import AuthorityPersistenceError, IdempotencyConflict
from .types import EventId, UtcTimestamp


class _DevelopmentCandidateAuthorityStore(_HybridRetrievalAuthorityStore):
    """SQLite authority for one deterministic Increment 2D Candidate admission."""

    def __init__(
        self,
        *args: Any,
        candidate_manifest: DevelopmentCandidateManifest = (
            INTEGRATED_FIXTURE_V2_DEVELOPMENT_CANDIDATE
        ),
        **kwargs: Any,
    ) -> None:
        if not isinstance(candidate_manifest, DevelopmentCandidateManifest):
            raise TypeError("development Candidate manifest must be typed")
        self._candidate_manifest = candidate_manifest
        super().__init__(*args, **kwargs)

    def _migrate_or_validate(self) -> None:
        super()._migrate_or_validate()
        self._validate_development_candidate_integrity()

    @staticmethod
    def _decode_candidate_canonical(data: bytes, *, identity: str) -> dict[str, Any]:
        try:
            value = json.loads(data.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise AuthorityPersistenceError(
                f"{identity} canonical JSON is invalid"
            ) from exc
        if not isinstance(value, dict) or canonical_json_bytes(value) != data:
            raise AuthorityPersistenceError(
                f"{identity} is not an exact canonical object"
            )
        return value

    @classmethod
    def _canonical_row_value(
        cls,
        row: sqlite3.Row,
        *,
        identity: str,
    ) -> dict[str, Any]:
        canonical = bytes(row["canonical_bytes"])
        if digest_bytes(canonical) != str(row["canonical_digest"]):
            raise AuthorityPersistenceError(
                f"{identity} canonical digest is inconsistent"
            )
        return cls._decode_candidate_canonical(canonical, identity=identity)

    def development_candidate_decision(
        self,
        decision_id: CandidateAdmissionDecisionId,
    ) -> DevelopmentCandidateAdmissionView:
        if not isinstance(decision_id, CandidateAdmissionDecisionId):
            raise TypeError("development Candidate decision identity must be typed")
        with self._lock:
            row = self._decision_row_by_id(self._connection, str(decision_id))
            self._validate_decision_row(self._connection, row)
            return self._view_from_row(row)

    def development_candidate_decision_for_proposal(
        self,
        proposal_id: IntegratedTriageProposalId,
    ) -> DevelopmentCandidateAdmissionView:
        if not isinstance(proposal_id, IntegratedTriageProposalId):
            raise TypeError("development Candidate proposal identity must be typed")
        with self._lock:
            row = self._connection.execute(
                "SELECT d.*,v.version_number "
                "FROM development_candidate_admission_decisions_v2 d "
                "JOIN development_candidate_versions_v2 v "
                "ON v.candidate_version_id=d.candidate_version_id "
                "WHERE d.proposal_id=?",
                (str(proposal_id),),
            ).fetchone()
            if row is None:
                raise KeyError(str(proposal_id))
            self._validate_decision_row(self._connection, row)
            return self._view_from_row(row)

    def _require_exact_context_locked(
        self,
        conn: sqlite3.Connection,
        *,
        request: DevelopmentCandidateAdmissionRequest,
        context: RetrievalContextV2,
        principal_id: str,
        authority_domain: str,
    ) -> None:
        manifest = self._candidate_manifest
        if context.context_id != request.retrieval_context_id:
            raise IntegratedContractError(
                "development Candidate request and context identity differ"
            )
        if context.context_digest != request.expected_context_digest:
            raise IdempotencyConflict(
                "development Candidate expected context digest differs"
            )
        if context.outcome is not RetrievalOutcome.COMPLETE:
            raise IntegratedContractError(
                "development Candidate admission requires COMPLETE retrieval"
            )
        row = conn.execute(
            "SELECT c.canonical_bytes,c.canonical_digest,a.fixture_id,"
            "a.retrieval_contract_digest "
            "FROM hybrid_retrieval_contexts_v2 c "
            "JOIN hybrid_retrieval_attempts a ON a.context_id=c.context_id "
            "WHERE c.context_id=?",
            (str(context.context_id),),
        ).fetchone()
        if row is None:
            raise AuthorityPersistenceError(
                "development Candidate context is not retained"
            )
        retained = self._context_from_bytes(
            bytes(row["canonical_bytes"]),
            expected_digest=str(row["canonical_digest"]),
        )
        if retained != context:
            raise AuthorityPersistenceError(
                "development Candidate context differs from retained authority"
            )
        if (
            str(row["fixture_id"]) != str(manifest.fixture_id)
            or str(row["retrieval_contract_digest"])
            != manifest.retrieval_contract_digest
        ):
            raise AuthorityPersistenceError(
                "development Candidate context contract differs from fixture authority"
            )
        self._require_current_projection_locked(conn, context.projection)
        self._validate_hydrations_locked(
            conn,
            context,
            principal_id=principal_id,
            authority_domain=authority_domain,
        )
        validate_fixture_branch_executions(
            executions=context.branches,
            policy=self._retrieval_policy,
            contract=self._retrieval_contract,
            query_digest=context.query_digest,
        )
        candidates, exclusions = fuse_fixture_candidates(
            executions=context.branches,
            fixture=self._retrieval_contract,
            policy=self._retrieval_policy,
        )
        if (
            candidates != context.retained_candidates
            or exclusions != context.exclusions
        ):
            raise AuthorityPersistenceError(
                "development Candidate context differs from deterministic fusion"
            )
        if not context.retained_candidates:
            raise AuthorityPersistenceError(
                "development Candidate context lacks a retained prior Candidate"
            )
        first = context.retained_candidates[0]
        if (
            first.candidate_version_id
            != str(manifest.prior_candidate_version_id)
            or first.dependency_root_id
            != f"candidate:{manifest.prior_candidate_version_id}"
            or set(first.contributing_branches) != set(RetrievalBranch)
        ):
            raise AuthorityPersistenceError(
                "development Candidate context lacks exact prior-Candidate authority"
            )
        graph = next(
            item
            for item in context.branches
            if item.branch is RetrievalBranch.ADMITTED_GRAPH
        )
        if len(graph.hits) != 1:
            raise AuthorityPersistenceError(
                "development Candidate context requires one admitted relation"
            )
        graph_hit = graph.hits[0]
        if (
            graph_hit.source_kind != "RELATION_ASSERTION"
            or graph_hit.source_identity != manifest.relation_key
            or graph_hit.dependency_root_id != first.dependency_root_id
        ):
            raise AuthorityPersistenceError(
                "development Candidate graph evidence differs from relation authority"
            )
        hydrated_ids = tuple(
            item.passage_id for item in context.hydrated_passages
        )
        if hydrated_ids != ("ifv2-prior-en", "ifv2-prior-zh-hk"):
            raise AuthorityPersistenceError(
                "development Candidate requires exact bilingual prior passages"
            )
        relation = conn.execute(
            "SELECT a.relation_key,a.predicate,h.current_state "
            "FROM relation_assertions a "
            "JOIN relation_decision_heads h ON h.proposal_id=a.proposal_id "
            "WHERE a.relation_key=?",
            (manifest.relation_key,),
        ).fetchone()
        if (
            relation is None
            or str(relation["predicate"])
            != RelationPredicate.DEVELOPMENT_OF.value
            or str(relation["current_state"])
            != RelationCurrentState.ADMITTED.value
        ):
            raise AuthorityPersistenceError(
                "development Candidate relation is not currently admitted"
            )
        distractor_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM relation_assertions "
                "WHERE predicate=? AND subject_id=? AND object_id=?",
                (
                    RelationPredicate.SAME_EVENT_AS.value,
                    str(manifest.hypothesis_version_id),
                    str(manifest.prior_hypothesis_version_id),
                ),
            ).fetchone()[0]
        )
        if distractor_count:
            raise AuthorityPersistenceError(
                "unadmitted SAME_EVENT_AS proposal entered admitted authority"
            )

    def commit_development_candidate_admission(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        request: DevelopmentCandidateAdmissionRequest,
        context: RetrievalContextV2,
    ) -> DevelopmentCandidateAdmissionView:
        if not isinstance(request, DevelopmentCandidateAdmissionRequest):
            raise TypeError("development Candidate admission requires a typed request")
        if not isinstance(context, RetrievalContextV2):
            raise TypeError("development Candidate admission requires typed context")
        manifest = self._candidate_manifest
        if (
            grant.command_type != DEVELOPMENT_CANDIDATE_ADMISSION_COMMAND
            or grant.aggregate_id != str(request.proposal_id)
            or grant.expected_aggregate_version != 0
        ):
            raise PermissionError(
                "development Candidate grant is not bound to the exact proposal"
            )

        with self._lock, self._transaction() as conn:
            checked_at = self._clock()
            grant.authentication.require_current(checked_at)
            self._require_exact_context_locked(
                conn,
                request=request,
                context=context,
                principal_id=grant.authentication.principal_id,
                authority_domain=grant.authentication.authority_domain,
            )
            recorded_at = checked_at.to_text()
            committed = self._commit_grant_in_transaction(
                conn,
                grant,
                recorded_at=recorded_at,
            )
            if committed.replayed:
                return self._decision_for_event(conn, committed.event_id)

            collision = manifest.semantic_collision_digest
            identity = conn.execute(
                "SELECT candidate_id FROM development_candidates_v2 "
                "WHERE semantic_collision_digest=?",
                (collision,),
            ).fetchone()
            if identity is None:
                outcome = CandidateAdmissionOutcome.ADMITTED
                candidate_id = StoryCandidateId.new()
                candidate_version_id = StoryCandidateVersionId.new()
                conn.execute(
                    "INSERT INTO development_candidates_v2("
                    "candidate_id,semantic_collision_digest,manifest_digest,created_at"
                    ") VALUES(?,?,?,?)",
                    (
                        str(candidate_id),
                        collision,
                        manifest.manifest_digest,
                        recorded_at,
                    ),
                )
                version_value = self._candidate_version_value(
                    candidate_id=candidate_id,
                    candidate_version_id=candidate_version_id,
                    context=context,
                )
                version_bytes = canonical_json_bytes(version_value)
                conn.execute(
                    "INSERT INTO development_candidate_versions_v2("
                    "candidate_version_id,candidate_id,version_number,fixture_id,"
                    "signal_id,lead_id,hypothesis_version_id,"
                    "prior_hypothesis_version_id,prior_candidate_version_id,"
                    "current_revision_id,prior_revision_id,canonical_process_id,"
                    "relation_key,route,hypothesis_trust_scope,"
                    "initial_retrieval_context_id,initial_retrieval_context_digest,"
                    "manifest_digest,canonical_bytes,canonical_digest,recorded_at"
                    ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        str(candidate_version_id),
                        str(candidate_id),
                        1,
                        str(manifest.fixture_id),
                        str(manifest.signal_id),
                        str(manifest.lead_id),
                        str(manifest.hypothesis_version_id),
                        str(manifest.prior_hypothesis_version_id),
                        str(manifest.prior_candidate_version_id),
                        manifest.current_revision_id,
                        manifest.prior_revision_id,
                        manifest.canonical_process_id,
                        manifest.relation_key,
                        manifest.route.value,
                        manifest.hypothesis_trust_scope.value,
                        str(context.context_id),
                        context.context_digest,
                        manifest.manifest_digest,
                        version_bytes,
                        digest_bytes(version_bytes),
                        recorded_at,
                    ),
                )
            else:
                outcome = CandidateAdmissionOutcome.DEDUPLICATED
                candidate_id = StoryCandidateId.parse(str(identity["candidate_id"]))
                version = conn.execute(
                    "SELECT candidate_version_id FROM "
                    "development_candidate_versions_v2 WHERE candidate_id=?",
                    (str(candidate_id),),
                ).fetchone()
                if version is None:
                    raise AuthorityPersistenceError(
                        "development Candidate identity lacks its immutable version"
                    )
                candidate_version_id = StoryCandidateVersionId.parse(
                    str(version["candidate_version_id"])
                )

            decision_id = CandidateAdmissionDecisionId.new()
            authority_event_id = EventId.parse(committed.event_id)
            decision_value = self._decision_value(
                decision_id=decision_id,
                outcome=outcome,
                candidate_id=candidate_id,
                candidate_version_id=candidate_version_id,
                request=request,
                context=context,
                authority_event_id=authority_event_id,
                authority_aggregate_version=committed.aggregate_version,
            )
            decision_bytes = canonical_json_bytes(decision_value)
            conn.execute(
                "INSERT INTO development_candidate_admission_decisions_v2("
                "decision_id,proposal_aggregate_type,proposal_id,outcome,"
                "candidate_id,candidate_version_id,route,fixture_id,"
                "retrieval_context_id,retrieval_context_digest,manifest_digest,"
                "semantic_collision_digest,relation_key,prior_candidate_version_id,"
                "authority_event_id,authority_aggregate_version,canonical_bytes,"
                "canonical_digest,recorded_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(decision_id),
                    "development_candidate_admission_proposal",
                    str(request.proposal_id),
                    outcome.value,
                    str(candidate_id),
                    str(candidate_version_id),
                    manifest.route.value,
                    str(manifest.fixture_id),
                    str(context.context_id),
                    context.context_digest,
                    manifest.manifest_digest,
                    collision,
                    manifest.relation_key,
                    str(manifest.prior_candidate_version_id),
                    committed.event_id,
                    committed.aggregate_version,
                    decision_bytes,
                    digest_bytes(decision_bytes),
                    recorded_at,
                ),
            )
            return self._decision_for_event(conn, committed.event_id)

    def _candidate_version_value(
        self,
        *,
        candidate_id: StoryCandidateId,
        candidate_version_id: StoryCandidateVersionId,
        context: RetrievalContextV2,
    ) -> dict[str, object]:
        manifest = self._candidate_manifest
        return {
            "contract": "newsroom-development-candidate-version-v2",
            "candidate_id": str(candidate_id),
            "candidate_version_id": str(candidate_version_id),
            "version_number": 1,
            "manifest": manifest.canonical_value(),
            "initial_retrieval_context_id": str(context.context_id),
            "initial_retrieval_context_digest": context.context_digest,
        }

    def _decision_value(
        self,
        *,
        decision_id: CandidateAdmissionDecisionId,
        outcome: CandidateAdmissionOutcome,
        candidate_id: StoryCandidateId,
        candidate_version_id: StoryCandidateVersionId,
        request: DevelopmentCandidateAdmissionRequest,
        context: RetrievalContextV2,
        authority_event_id: EventId,
        authority_aggregate_version: int,
    ) -> dict[str, object]:
        manifest = self._candidate_manifest
        return {
            "contract": "newsroom-development-candidate-admission-decision-v2",
            "decision_id": str(decision_id),
            "outcome": outcome.value,
            "proposal_id": str(request.proposal_id),
            "candidate_id": str(candidate_id),
            "candidate_version_id": str(candidate_version_id),
            "candidate_version": 1,
            "route": manifest.route.value,
            "fixture_id": str(manifest.fixture_id),
            "retrieval_context_id": str(context.context_id),
            "retrieval_context_digest": context.context_digest,
            "manifest_digest": manifest.manifest_digest,
            "semantic_collision_digest": manifest.semantic_collision_digest,
            "relation_key": manifest.relation_key,
            "prior_candidate_version_id": str(
                manifest.prior_candidate_version_id
            ),
            "authority_event_id": str(authority_event_id),
            "authority_aggregate_version": authority_aggregate_version,
        }

    def _decision_row_by_id(
        self,
        conn: sqlite3.Connection,
        decision_id: str,
    ) -> sqlite3.Row:
        row = conn.execute(
            "SELECT d.*,v.version_number FROM "
            "development_candidate_admission_decisions_v2 d "
            "JOIN development_candidate_versions_v2 v "
            "ON v.candidate_version_id=d.candidate_version_id "
            "WHERE d.decision_id=?",
            (decision_id,),
        ).fetchone()
        if row is None:
            raise KeyError(decision_id)
        return row

    def _decision_for_event(
        self,
        conn: sqlite3.Connection,
        event_id: str,
    ) -> DevelopmentCandidateAdmissionView:
        row = conn.execute(
            "SELECT d.*,v.version_number FROM "
            "development_candidate_admission_decisions_v2 d "
            "JOIN development_candidate_versions_v2 v "
            "ON v.candidate_version_id=d.candidate_version_id "
            "WHERE d.authority_event_id=?",
            (event_id,),
        ).fetchone()
        if row is None:
            raise AuthorityPersistenceError(
                "development Candidate command lacks its exact decision"
            )
        return self._view_from_row(row)

    @staticmethod
    def _view_from_row(row: sqlite3.Row) -> DevelopmentCandidateAdmissionView:
        return DevelopmentCandidateAdmissionView(
            decision_id=CandidateAdmissionDecisionId.parse(str(row["decision_id"])),
            outcome=CandidateAdmissionOutcome(str(row["outcome"])),
            proposal_id=IntegratedTriageProposalId.parse(str(row["proposal_id"])),
            candidate_id=StoryCandidateId.parse(str(row["candidate_id"])),
            candidate_version_id=StoryCandidateVersionId.parse(
                str(row["candidate_version_id"])
            ),
            candidate_version=int(row["version_number"]),
            route=CandidateRoute(str(row["route"])),
            fixture_id=IntegratedFixtureId.parse(str(row["fixture_id"])),
            retrieval_context_id=RetrievalContextV2Id.parse(
                str(row["retrieval_context_id"])
            ),
            retrieval_context_digest=str(row["retrieval_context_digest"]),
            manifest_digest=str(row["manifest_digest"]),
            semantic_collision_digest=str(row["semantic_collision_digest"]),
            relation_key=str(row["relation_key"]),
            prior_candidate_version_id=StoryCandidateVersionId.parse(
                str(row["prior_candidate_version_id"])
            ),
            authority_event_id=EventId.parse(str(row["authority_event_id"])),
            authority_aggregate_version=int(row["authority_aggregate_version"]),
            recorded_at=UtcTimestamp.parse(str(row["recorded_at"])),
        )

    def _validate_development_candidate_integrity(self) -> None:
        with self._lock:
            conn = self._connection
            for row in conn.execute(
                "SELECT * FROM development_candidate_versions_v2"
            ).fetchall():
                self._validate_version_row(conn, row)
            for row in conn.execute(
                "SELECT d.*,v.version_number FROM "
                "development_candidate_admission_decisions_v2 d "
                "JOIN development_candidate_versions_v2 v "
                "ON v.candidate_version_id=d.candidate_version_id"
            ).fetchall():
                self._validate_decision_row(conn, row)
            for row in conn.execute(
                "SELECT * FROM development_candidates_v2"
            ).fetchall():
                collision = str(row["semantic_collision_digest"])
                validate_sha256_digest(
                    collision,
                    field="development_candidate_semantic_collision_digest",
                )
                if (
                    collision != self._candidate_manifest.semantic_collision_digest
                    or str(row["manifest_digest"])
                    != self._candidate_manifest.manifest_digest
                ):
                    raise AuthorityPersistenceError(
                        "development Candidate identity differs from fixture authority"
                    )
                count = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM development_candidate_versions_v2 "
                        "WHERE candidate_id=?",
                        (str(row["candidate_id"]),),
                    ).fetchone()[0]
                )
                if count != 1:
                    raise AuthorityPersistenceError(
                        "development Candidate identity requires one exact version"
                    )

    def _validate_version_row(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> None:
        manifest = self._candidate_manifest
        value = self._canonical_row_value(
            row,
            identity="development Candidate version",
        )
        candidate_id = StoryCandidateId.parse(str(row["candidate_id"]))
        version_id = StoryCandidateVersionId.parse(
            str(row["candidate_version_id"])
        )
        context = self.retrieval_context(
            RetrievalContextV2Id.parse(str(row["initial_retrieval_context_id"]))
        )
        expected = self._candidate_version_value(
            candidate_id=candidate_id,
            candidate_version_id=version_id,
            context=context,
        )
        if value != expected:
            raise AuthorityPersistenceError(
                "development Candidate version canonical value differs"
            )
        normalized = (
            str(row["fixture_id"]),
            str(row["signal_id"]),
            str(row["lead_id"]),
            str(row["hypothesis_version_id"]),
            str(row["prior_hypothesis_version_id"]),
            str(row["prior_candidate_version_id"]),
            str(row["current_revision_id"]),
            str(row["prior_revision_id"]),
            str(row["canonical_process_id"]),
            str(row["relation_key"]),
            str(row["route"]),
            str(row["hypothesis_trust_scope"]),
            str(row["initial_retrieval_context_digest"]),
            str(row["manifest_digest"]),
        )
        expected_normalized = (
            str(manifest.fixture_id),
            str(manifest.signal_id),
            str(manifest.lead_id),
            str(manifest.hypothesis_version_id),
            str(manifest.prior_hypothesis_version_id),
            str(manifest.prior_candidate_version_id),
            manifest.current_revision_id,
            manifest.prior_revision_id,
            manifest.canonical_process_id,
            manifest.relation_key,
            manifest.route.value,
            manifest.hypothesis_trust_scope.value,
            context.context_digest,
            manifest.manifest_digest,
        )
        if int(row["version_number"]) != 1 or normalized != expected_normalized:
            raise AuthorityPersistenceError(
                "development Candidate version normalized columns differ"
            )

    def _validate_decision_row(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> None:
        value = self._canonical_row_value(
            row,
            identity="development Candidate decision",
        )
        context = self.retrieval_context(
            RetrievalContextV2Id.parse(str(row["retrieval_context_id"]))
        )
        expected = self._decision_value(
            decision_id=CandidateAdmissionDecisionId.parse(
                str(row["decision_id"])
            ),
            outcome=CandidateAdmissionOutcome(str(row["outcome"])),
            candidate_id=StoryCandidateId.parse(str(row["candidate_id"])),
            candidate_version_id=StoryCandidateVersionId.parse(
                str(row["candidate_version_id"])
            ),
            request=DevelopmentCandidateAdmissionRequest(
                proposal_id=IntegratedTriageProposalId.parse(
                    str(row["proposal_id"])
                ),
                retrieval_context_id=context.context_id,
                expected_context_digest=context.context_digest,
                idempotency_key="retained-decision-validation",
            ),
            context=context,
            authority_event_id=EventId.parse(str(row["authority_event_id"])),
            authority_aggregate_version=int(row["authority_aggregate_version"]),
        )
        if value != expected:
            raise AuthorityPersistenceError(
                "development Candidate decision canonical value differs"
            )
        event = conn.execute(
            "SELECT * FROM ledger_events WHERE event_id=?",
            (str(row["authority_event_id"]),),
        ).fetchone()
        if event is None:
            raise AuthorityPersistenceError(
                "development Candidate decision event is missing"
            )
        if (
            str(event["event_type"])
            != "candidate.development.admission.decided"
            or str(event["aggregate_type"])
            != "development_candidate_admission_proposal"
            or str(event["aggregate_id"]) != str(row["proposal_id"])
            or int(event["aggregate_version"])
            != int(row["authority_aggregate_version"])
            or str(event["security_scope"]) != "authority.candidate"
            or str(event["retention_scope"]) != "authority.audit"
            or str(event["recorded_at"]) != str(row["recorded_at"])
        ):
            raise AuthorityPersistenceError(
                "development Candidate decision event differs from authority"
            )


__all__ = ["_DevelopmentCandidateAuthorityStore"]
