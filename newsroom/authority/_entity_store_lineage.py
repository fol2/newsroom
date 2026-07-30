from __future__ import annotations

import sqlite3

from newsroom.authority._capability import _AuthorizedCommandGrant
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.persistence import AuthorityPersistenceError
from newsroom.authority.types import EventId, UtcTimestamp
from newsroom.entities.models import (
    CanonicalEntity,
    CanonicalEntityVersion,
    EntityLineageVersion,
    EntityMergeDecision,
    EntityMergeDecisionRequest,
    EntityMergePredecessor,
    EntityReversalDecision,
    EntityReversalDecisionRequest,
    EntitySplitDecision,
    EntitySplitDecisionRequest,
)
from newsroom.entities.policy import (
    ENTITY_MERGE_DECIDE_COMMAND,
    ENTITY_REVERSAL_DECIDE_COMMAND,
    ENTITY_SPLIT_DECIDE_COMMAND,
)
from newsroom.entities.types import (
    CanonicalEntityId,
    CanonicalEntityLifecycle,
    CanonicalEntityVersionId,
    EntityCreationDecisionKind,
    EntityDecisionConflict,
    EntityIdentifierReuse,
    EntityKind,
    EntityLineageDecisionKind,
    EntityMergeDecisionId,
    EntityMentionId,
    EntityResolutionProposalId,
    EntityResolutionState,
    EntityReversalDecisionId,
    EntityReversalTargetKind,
    EntitySemanticCollision,
    EntitySplitDecisionId,
    EntityStaleDecision,
    EntityStateError,
)

from ._entity_store_common import (
    deterministic_lineage_version_id,
    deterministic_projection_event_id,
)


class _EntityLineageMixin:
    def _lineage_current(
        self,
        conn: sqlite3.Connection,
        *,
        entity_id: CanonicalEntityId,
        expected_version_id: CanonicalEntityVersionId,
        require_active: bool,
    ) -> tuple[sqlite3.Row, sqlite3.Row]:
        head = self._entity_head_row(conn, entity_id)
        if str(head["current_entity_version_id"]) != str(expected_version_id):
            raise EntityStaleDecision("entity version is no longer current")
        if require_active and str(head["lifecycle"]) != CanonicalEntityLifecycle.ACTIVE.value:
            raise EntityStateError("lineage decision requires an active entity")
        entity = conn.execute(
            "SELECT * FROM canonical_entities WHERE entity_id=?",
            (str(entity_id),),
        ).fetchone()
        if entity is None:
            raise AuthorityPersistenceError("canonical entity identity is missing")
        self._entity_from_row(conn, entity)
        version = conn.execute(
            "SELECT * FROM canonical_entity_versions WHERE entity_version_id=?",
            (str(expected_version_id),),
        ).fetchone()
        if version is None:
            raise AuthorityPersistenceError("canonical entity current version is missing")
        self._entity_version_from_row(conn, version)
        return entity, head

    def _accepted_basis_entities(
        self,
        conn: sqlite3.Connection,
        proposal_ids: tuple[EntityResolutionProposalId, ...],
    ) -> frozenset[CanonicalEntityId]:
        accepted: set[CanonicalEntityId] = set()
        for proposal_id in proposal_ids:
            proposal_row = conn.execute(
                "SELECT v.* FROM entity_resolution_proposal_heads h "
                "JOIN entity_resolution_proposal_versions v "
                "ON v.proposal_version_id=h.current_proposal_version_id "
                "WHERE h.resolution_proposal_id=?",
                (str(proposal_id),),
            ).fetchone()
            if proposal_row is None:
                raise EntityStateError("merge basis resolution proposal is missing")
            proposal = self._require_resolution_proposal_current(conn, proposal_id)
            decision_row = conn.execute(
                "SELECT d.* FROM entity_resolution_decision_heads h "
                "JOIN entity_resolution_decisions d "
                "ON d.decision_id=h.current_decision_id "
                "WHERE h.resolution_proposal_id=? AND h.current_state='ACCEPTED'",
                (str(proposal_id),),
            ).fetchone()
            if decision_row is None or decision_row["accepted_entity_id"] is None:
                raise EntityDecisionConflict(
                    "lineage basis requires a currently accepted resolution proposal"
                )
            decision = self._decision_from_row(conn, decision_row, replayed=False)
            assert decision.accepted_entity_id is not None
            accepted.add(decision.accepted_entity_id)
        return frozenset(accepted)

    @staticmethod
    def _ensure_absent_identifier(
        conn: sqlite3.Connection,
        *,
        table: str,
        column: str,
        value: str,
        identity: str,
    ) -> None:
        if conn.execute(
            f"SELECT 1 FROM {table} WHERE {column}=?", (value,)
        ).fetchone() is not None:
            raise EntityIdentifierReuse(f"{identity} already exists")

    def _insert_lineage_entity(
        self,
        conn: sqlite3.Connection,
        *,
        entity_id: CanonicalEntityId,
        entity_kind: EntityKind,
        created_by_kind: EntityCreationDecisionKind,
        created_by_decision_id: str,
        initial_version_id: CanonicalEntityVersionId,
        source_event_id: EventId,
        source_ledger_seq: int,
        recorded_at: UtcTimestamp,
        aggregate_version: int,
    ) -> None:
        entity = CanonicalEntity(
            entity_id=entity_id,
            entity_kind=entity_kind,
            created_by_kind=created_by_kind,
            created_by_decision_id=created_by_decision_id,
            initial_version_id=initial_version_id,
            authority_event_id=source_event_id,
            authority_ledger_seq=source_ledger_seq,
            created_at=recorded_at,
        )
        data = canonical_json_bytes(entity.canonical_value())
        conn.execute(
            "INSERT INTO canonical_entities("
            "entity_id,entity_kind,created_by_kind,created_by_decision_id,"
            "initial_version_id,authority_event_id,authority_aggregate_version,"
            "canonical_bytes,canonical_digest,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                str(entity.entity_id),
                entity.entity_kind.value,
                entity.created_by_kind.value,
                entity.created_by_decision_id,
                str(entity.initial_version_id),
                str(source_event_id),
                aggregate_version,
                data,
                digest_bytes(data),
                recorded_at.to_text(),
            ),
        )

    @staticmethod
    def _insert_lineage_version(
        conn: sqlite3.Connection,
        *,
        version: CanonicalEntityVersion,
        aggregate_version: int,
    ) -> None:
        data = canonical_json_bytes(version.canonical_value())
        conn.execute(
            "INSERT INTO canonical_entity_versions("
            "entity_version_id,entity_id,version_number,previous_entity_version_id,"
            "entity_kind,lifecycle,lineage_decision_kind,lineage_decision_id,"
            "preferred_continuation_entity_id,authority_event_id,"
            "authority_aggregate_version,canonical_bytes,canonical_digest,recorded_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(version.entity_version_id),
                str(version.entity_id),
                version.version_number,
                (
                    None
                    if version.previous_entity_version_id is None
                    else str(version.previous_entity_version_id)
                ),
                version.entity_kind.value,
                version.lifecycle.value,
                (
                    None
                    if version.lineage_decision_kind is None
                    else version.lineage_decision_kind.value
                ),
                version.lineage_decision_id,
                (
                    None
                    if version.preferred_continuation_entity_id is None
                    else str(version.preferred_continuation_entity_id)
                ),
                str(version.authority_event_id),
                aggregate_version,
                data,
                digest_bytes(data),
                version.recorded_at.to_text(),
            ),
        )

    @staticmethod
    def _upsert_preferred(
        conn: sqlite3.Connection,
        *,
        entity_id: CanonicalEntityId,
        version_id: CanonicalEntityVersionId,
        preferred_entity_id: CanonicalEntityId,
        lifecycle: CanonicalEntityLifecycle,
        decision_kind: EntityLineageDecisionKind,
        decision_id: str,
        ledger_seq: int,
        recorded_at: UtcTimestamp,
    ) -> None:
        existing = conn.execute(
            "SELECT 1 FROM entity_preferred_identities WHERE entity_id=?",
            (str(entity_id),),
        ).fetchone()
        values = (
            str(version_id),
            str(preferred_entity_id),
            lifecycle.value,
            decision_kind.value,
            decision_id,
            ledger_seq,
            recorded_at.to_text(),
        )
        if existing is None:
            conn.execute(
                "INSERT INTO entity_preferred_identities("
                "entity_id,current_entity_version_id,preferred_entity_id,lifecycle,"
                "decided_by_kind,decided_by_id,projected_through_ledger_seq,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (str(entity_id), *values),
            )
        else:
            conn.execute(
                "UPDATE entity_preferred_identities SET current_entity_version_id=?,"
                "preferred_entity_id=?,lifecycle=?,decided_by_kind=?,decided_by_id=?,"
                "projected_through_ledger_seq=?,updated_at=? WHERE entity_id=?",
                (*values, str(entity_id)),
            )

    @staticmethod
    def _insert_projection_event(
        conn: sqlite3.Connection,
        *,
        source_event_id: EventId,
        source_ledger_seq: int,
        entity_id: CanonicalEntityId,
        version_id: CanonicalEntityVersionId,
        preferred_entity_id: CanonicalEntityId,
        lifecycle: CanonicalEntityLifecycle,
        recorded_at: UtcTimestamp,
    ) -> None:
        projection_id = deterministic_projection_event_id(
            source_event_id=str(source_event_id), entity_id=entity_id
        )
        value = {
            "projection_event_id": str(projection_id),
            "source_event_id": str(source_event_id),
            "source_ledger_seq": source_ledger_seq,
            "action": "UPSERT",
            "entity_id": str(entity_id),
            "entity_version_id": str(version_id),
            "preferred_entity_id": str(preferred_entity_id),
            "lifecycle": lifecycle.value,
        }
        data = canonical_json_bytes(value)
        conn.execute(
            "INSERT INTO entity_projection_events("
            "projection_event_id,source_event_id,source_ledger_seq,action,entity_id,"
            "entity_version_id,preferred_entity_id,lifecycle,canonical_bytes,"
            "canonical_digest,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(projection_id),
                str(source_event_id),
                source_ledger_seq,
                "UPSERT",
                str(entity_id),
                str(version_id),
                str(preferred_entity_id),
                lifecycle.value,
                data,
                digest_bytes(data),
                recorded_at.to_text(),
            ),
        )

    def commit_entity_merge(
        self,
        grant: _AuthorizedCommandGrant,
        request: EntityMergeDecisionRequest,
    ) -> EntityMergeDecision:
        payload = canonical_json_bytes(request.canonical_value())
        self._require_entity_grant(
            grant,
            command_type=ENTITY_MERGE_DECIDE_COMMAND,
            aggregate_id=str(request.merge_decision_id),
            expected_aggregate_version=0,
            canonical_bytes=payload,
        )
        with self._lock:
            with self._transaction() as conn:
                now = self._clock()
                grant.authentication.require_current(now)
                committed = self._commit_grant_in_transaction(
                    conn, grant, recorded_at=now.to_text()
                )
                if grant.replay_of_command_id is not None:
                    row = self._row_for_event(
                        conn,
                        table="entity_merge_decisions",
                        event_id=committed.event_id,
                        identity="entity merge decision",
                    )
                    return self._merge_decision_from_row(conn, row, replayed=True)

                existing = conn.execute(
                    "SELECT request_digest FROM entity_merge_decisions "
                    "WHERE merge_decision_id=?",
                    (str(request.merge_decision_id),),
                ).fetchone()
                if existing is not None:
                    if str(existing["request_digest"]) == request.digest:
                        raise EntityDecisionConflict(
                            "exact merge replay requires the original idempotency key"
                        )
                    raise EntityIdentifierReuse("merge decision identity is already retained")
                self._ensure_absent_identifier(
                    conn,
                    table="canonical_entities",
                    column="entity_id",
                    value=str(request.successor_entity_id),
                    identity="merge successor entity",
                )
                self._ensure_absent_identifier(
                    conn,
                    table="canonical_entity_versions",
                    column="entity_version_id",
                    value=str(request.successor_entity_version_id),
                    identity="merge successor version",
                )

                entity_kind: EntityKind | None = None
                predecessors: list[EntityMergePredecessor] = []
                for item in request.predecessors:
                    entity_row, head = self._lineage_current(
                        conn,
                        entity_id=item.entity_id,
                        expected_version_id=item.entity_version_id,
                        require_active=True,
                    )
                    current_kind = EntityKind(str(entity_row["entity_kind"]))
                    if entity_kind is None:
                        entity_kind = current_kind
                    elif current_kind != entity_kind:
                        raise EntityDecisionConflict(
                            "merge predecessors must have one entity kind"
                        )
                    result_version_id = deterministic_lineage_version_id(
                        decision_kind="MERGE",
                        decision_id=str(request.merge_decision_id),
                        entity_id=item.entity_id,
                        role="PREDECESSOR",
                    )
                    self._ensure_absent_identifier(
                        conn,
                        table="canonical_entity_versions",
                        column="entity_version_id",
                        value=str(result_version_id),
                        identity="merge predecessor result version",
                    )
                    predecessors.append(
                        EntityMergePredecessor(
                            item.entity_id,
                            item.entity_version_id,
                            result_version_id,
                        )
                    )
                    if int(head["current_version_number"]) < 1:
                        raise AuthorityPersistenceError("entity head version is invalid")
                assert entity_kind is not None
                covered = self._accepted_basis_entities(
                    conn, request.basis_resolution_proposal_ids
                )
                expected_entities = frozenset(item.entity_id for item in request.predecessors)
                if covered != expected_entities:
                    raise EntityDecisionConflict(
                        "merge basis must exactly cover every predecessor identity"
                    )

                recorded_at = now
                source_event = EventId.parse(committed.event_id)
                result = EntityMergeDecision(
                    merge_decision_id=request.merge_decision_id,
                    predecessors=tuple(predecessors),
                    successor_entity_id=request.successor_entity_id,
                    successor_entity_version_id=request.successor_entity_version_id,
                    preferred_continuation_entity_id=request.preferred_continuation_entity_id,
                    basis_resolution_proposal_ids=request.basis_resolution_proposal_ids,
                    reason_code=request.reason_code,
                    decision_policy_version=request.decision_policy_version,
                    authority_event_id=source_event,
                    authority_ledger_seq=committed.ledger_seq,
                    recorded_at=recorded_at,
                )
                data = canonical_json_bytes(result.canonical_value())
                conn.execute(
                    "INSERT INTO entity_merge_decisions("
                    "merge_decision_id,successor_entity_id,successor_entity_version_id,"
                    "preferred_continuation_entity_id,predecessor_count,"
                    "basis_resolution_proposal_ids_bytes,reason_code,"
                    "decision_policy_version,request_digest,authority_event_id,"
                    "authority_aggregate_version,canonical_bytes,canonical_digest,recorded_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        str(result.merge_decision_id),
                        str(result.successor_entity_id),
                        str(result.successor_entity_version_id),
                        str(result.preferred_continuation_entity_id),
                        len(result.predecessors),
                        self._json_bytes(
                            tuple(str(value) for value in result.basis_resolution_proposal_ids)
                        ),
                        result.reason_code,
                        result.decision_policy_version,
                        request.digest,
                        committed.event_id,
                        committed.aggregate_version,
                        data,
                        digest_bytes(data),
                        recorded_at.to_text(),
                    ),
                )
                for ordinal, item in enumerate(result.predecessors, start=1):
                    child = canonical_json_bytes(item.canonical_value())
                    conn.execute(
                        "INSERT INTO entity_merge_predecessors("
                        "merge_decision_id,predecessor_ordinal,entity_id,"
                        "expected_entity_version_id,merged_entity_version_id,"
                        "canonical_bytes,canonical_digest) VALUES(?,?,?,?,?,?,?)",
                        (
                            str(result.merge_decision_id),
                            ordinal,
                            str(item.entity_id),
                            str(item.expected_entity_version_id),
                            str(item.merged_entity_version_id),
                            child,
                            digest_bytes(child),
                        ),
                    )

                self._insert_lineage_entity(
                    conn,
                    entity_id=result.successor_entity_id,
                    entity_kind=entity_kind,
                    created_by_kind=EntityCreationDecisionKind.MERGE,
                    created_by_decision_id=str(result.merge_decision_id),
                    initial_version_id=result.successor_entity_version_id,
                    source_event_id=source_event,
                    source_ledger_seq=committed.ledger_seq,
                    recorded_at=recorded_at,
                    aggregate_version=committed.aggregate_version,
                )
                successor_version = CanonicalEntityVersion(
                    entity_version_id=result.successor_entity_version_id,
                    entity_id=result.successor_entity_id,
                    version_number=1,
                    previous_entity_version_id=None,
                    entity_kind=entity_kind,
                    lifecycle=CanonicalEntityLifecycle.ACTIVE,
                    lineage_decision_kind=EntityLineageDecisionKind.MERGE,
                    lineage_decision_id=str(result.merge_decision_id),
                    preferred_continuation_entity_id=result.successor_entity_id,
                    authority_event_id=source_event,
                    authority_ledger_seq=committed.ledger_seq,
                    recorded_at=recorded_at,
                )
                self._insert_lineage_version(
                    conn,
                    version=successor_version,
                    aggregate_version=committed.aggregate_version,
                )
                for item in result.predecessors:
                    head = self._entity_head_row(conn, item.entity_id)
                    version = CanonicalEntityVersion(
                        entity_version_id=item.merged_entity_version_id,
                        entity_id=item.entity_id,
                        version_number=int(head["current_version_number"]) + 1,
                        previous_entity_version_id=item.expected_entity_version_id,
                        entity_kind=entity_kind,
                        lifecycle=CanonicalEntityLifecycle.MERGED,
                        lineage_decision_kind=EntityLineageDecisionKind.MERGE,
                        lineage_decision_id=str(result.merge_decision_id),
                        preferred_continuation_entity_id=result.successor_entity_id,
                        authority_event_id=source_event,
                        authority_ledger_seq=committed.ledger_seq,
                        recorded_at=recorded_at,
                    )
                    self._insert_lineage_version(
                        conn,
                        version=version,
                        aggregate_version=committed.aggregate_version,
                    )
                    self._upsert_preferred(
                        conn,
                        entity_id=item.entity_id,
                        version_id=item.merged_entity_version_id,
                        preferred_entity_id=result.successor_entity_id,
                        lifecycle=CanonicalEntityLifecycle.MERGED,
                        decision_kind=EntityLineageDecisionKind.MERGE,
                        decision_id=str(result.merge_decision_id),
                        ledger_seq=committed.ledger_seq,
                        recorded_at=recorded_at,
                    )
                    self._insert_projection_event(
                        conn,
                        source_event_id=source_event,
                        source_ledger_seq=committed.ledger_seq,
                        entity_id=item.entity_id,
                        version_id=item.merged_entity_version_id,
                        preferred_entity_id=result.successor_entity_id,
                        lifecycle=CanonicalEntityLifecycle.MERGED,
                        recorded_at=recorded_at,
                    )
                self._upsert_preferred(
                    conn,
                    entity_id=result.successor_entity_id,
                    version_id=result.successor_entity_version_id,
                    preferred_entity_id=result.successor_entity_id,
                    lifecycle=CanonicalEntityLifecycle.ACTIVE,
                    decision_kind=EntityLineageDecisionKind.MERGE,
                    decision_id=str(result.merge_decision_id),
                    ledger_seq=committed.ledger_seq,
                    recorded_at=recorded_at,
                )
                self._insert_projection_event(
                    conn,
                    source_event_id=source_event,
                    source_ledger_seq=committed.ledger_seq,
                    entity_id=result.successor_entity_id,
                    version_id=result.successor_entity_version_id,
                    preferred_entity_id=result.successor_entity_id,
                    lifecycle=CanonicalEntityLifecycle.ACTIVE,
                    recorded_at=recorded_at,
                )
                row = self._row_for_event(
                    conn,
                    table="entity_merge_decisions",
                    event_id=committed.event_id,
                    identity="entity merge decision",
                )
                return self._merge_decision_from_row(conn, row, replayed=False)

    def commit_entity_split(
        self,
        grant: _AuthorizedCommandGrant,
        request: EntitySplitDecisionRequest,
    ) -> EntitySplitDecision:
        payload = canonical_json_bytes(request.canonical_value())
        self._require_entity_grant(
            grant,
            command_type=ENTITY_SPLIT_DECIDE_COMMAND,
            aggregate_id=str(request.split_decision_id),
            expected_aggregate_version=0,
            canonical_bytes=payload,
        )
        with self._lock:
            with self._transaction() as conn:
                now = self._clock()
                grant.authentication.require_current(now)
                committed = self._commit_grant_in_transaction(
                    conn, grant, recorded_at=now.to_text()
                )
                if grant.replay_of_command_id is not None:
                    row = self._row_for_event(
                        conn,
                        table="entity_split_decisions",
                        event_id=committed.event_id,
                        identity="entity split decision",
                    )
                    return self._split_decision_from_row(conn, row, replayed=True)
                if conn.execute(
                    "SELECT 1 FROM entity_split_decisions WHERE split_decision_id=?",
                    (str(request.split_decision_id),),
                ).fetchone() is not None:
                    raise EntityIdentifierReuse("split decision identity is already retained")
                source_row, source_head = self._lineage_current(
                    conn,
                    entity_id=request.source_entity_id,
                    expected_version_id=request.expected_source_version_id,
                    require_active=True,
                )
                entity_kind = EntityKind(str(source_row["entity_kind"]))
                retained_mentions = tuple(
                    EntityMentionId.parse(str(row["mention_id"]))
                    for row in conn.execute(
                        "SELECT mention_id FROM entity_mention_resolutions "
                        "WHERE entity_id=? ORDER BY mention_id",
                        (str(request.source_entity_id),),
                    ).fetchall()
                )
                for mention_id in retained_mentions:
                    self._require_mention_id_current(conn, mention_id)
                allocated_mentions = tuple(item.mention_id for item in request.allocations)
                if retained_mentions != allocated_mentions:
                    raise EntityDecisionConflict(
                        "split allocations must exactly partition all admitted mentions"
                    )
                for successor in request.successors:
                    self._ensure_absent_identifier(
                        conn,
                        table="canonical_entities",
                        column="entity_id",
                        value=str(successor.entity_id),
                        identity="split successor entity",
                    )
                    self._ensure_absent_identifier(
                        conn,
                        table="canonical_entity_versions",
                        column="entity_version_id",
                        value=str(successor.entity_version_id),
                        identity="split successor version",
                    )
                source_split_version_id = deterministic_lineage_version_id(
                    decision_kind="SPLIT",
                    decision_id=str(request.split_decision_id),
                    entity_id=request.source_entity_id,
                    role="SOURCE",
                )
                self._ensure_absent_identifier(
                    conn,
                    table="canonical_entity_versions",
                    column="entity_version_id",
                    value=str(source_split_version_id),
                    identity="split source result version",
                )
                recorded_at = now
                source_event = EventId.parse(committed.event_id)
                result = EntitySplitDecision(
                    split_decision_id=request.split_decision_id,
                    source_entity_id=request.source_entity_id,
                    expected_source_version_id=request.expected_source_version_id,
                    source_split_version_id=source_split_version_id,
                    successors=request.successors,
                    allocations=request.allocations,
                    reason_code=request.reason_code,
                    decision_policy_version=request.decision_policy_version,
                    authority_event_id=source_event,
                    authority_ledger_seq=committed.ledger_seq,
                    recorded_at=recorded_at,
                )
                data = canonical_json_bytes(result.canonical_value())
                conn.execute(
                    "INSERT INTO entity_split_decisions("
                    "split_decision_id,source_entity_id,expected_source_version_id,"
                    "source_split_version_id,successor_count,reason_code,"
                    "decision_policy_version,request_digest,authority_event_id,"
                    "authority_aggregate_version,canonical_bytes,canonical_digest,recorded_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        str(result.split_decision_id),
                        str(result.source_entity_id),
                        str(result.expected_source_version_id),
                        str(result.source_split_version_id),
                        len(result.successors),
                        result.reason_code,
                        result.decision_policy_version,
                        request.digest,
                        committed.event_id,
                        committed.aggregate_version,
                        data,
                        digest_bytes(data),
                        recorded_at.to_text(),
                    ),
                )
                for ordinal, successor in enumerate(result.successors, start=1):
                    child = canonical_json_bytes(successor.canonical_value())
                    conn.execute(
                        "INSERT INTO entity_split_successors("
                        "split_decision_id,successor_ordinal,entity_id,entity_version_id,"
                        "canonical_bytes,canonical_digest) VALUES(?,?,?,?,?,?)",
                        (
                            str(result.split_decision_id),
                            ordinal,
                            str(successor.entity_id),
                            str(successor.entity_version_id),
                            child,
                            digest_bytes(child),
                        ),
                    )
                for allocation in result.allocations:
                    child = canonical_json_bytes(allocation.canonical_value())
                    conn.execute(
                        "INSERT INTO entity_split_allocations("
                        "split_decision_id,mention_id,successor_entity_id,"
                        "canonical_bytes,canonical_digest) VALUES(?,?,?,?,?)",
                        (
                            str(result.split_decision_id),
                            str(allocation.mention_id),
                            str(allocation.successor_entity_id),
                            child,
                            digest_bytes(child),
                        ),
                    )
                for successor in result.successors:
                    self._insert_lineage_entity(
                        conn,
                        entity_id=successor.entity_id,
                        entity_kind=entity_kind,
                        created_by_kind=EntityCreationDecisionKind.SPLIT,
                        created_by_decision_id=str(result.split_decision_id),
                        initial_version_id=successor.entity_version_id,
                        source_event_id=source_event,
                        source_ledger_seq=committed.ledger_seq,
                        recorded_at=recorded_at,
                        aggregate_version=committed.aggregate_version,
                    )
                    version = CanonicalEntityVersion(
                        entity_version_id=successor.entity_version_id,
                        entity_id=successor.entity_id,
                        version_number=1,
                        previous_entity_version_id=None,
                        entity_kind=entity_kind,
                        lifecycle=CanonicalEntityLifecycle.ACTIVE,
                        lineage_decision_kind=EntityLineageDecisionKind.SPLIT,
                        lineage_decision_id=str(result.split_decision_id),
                        preferred_continuation_entity_id=successor.entity_id,
                        authority_event_id=source_event,
                        authority_ledger_seq=committed.ledger_seq,
                        recorded_at=recorded_at,
                    )
                    self._insert_lineage_version(
                        conn,
                        version=version,
                        aggregate_version=committed.aggregate_version,
                    )
                source_version = CanonicalEntityVersion(
                    entity_version_id=result.source_split_version_id,
                    entity_id=result.source_entity_id,
                    version_number=int(source_head["current_version_number"]) + 1,
                    previous_entity_version_id=result.expected_source_version_id,
                    entity_kind=entity_kind,
                    lifecycle=CanonicalEntityLifecycle.SPLIT,
                    lineage_decision_kind=EntityLineageDecisionKind.SPLIT,
                    lineage_decision_id=str(result.split_decision_id),
                    preferred_continuation_entity_id=None,
                    authority_event_id=source_event,
                    authority_ledger_seq=committed.ledger_seq,
                    recorded_at=recorded_at,
                )
                self._insert_lineage_version(
                    conn,
                    version=source_version,
                    aggregate_version=committed.aggregate_version,
                )
                self._upsert_preferred(
                    conn,
                    entity_id=result.source_entity_id,
                    version_id=result.source_split_version_id,
                    preferred_entity_id=result.source_entity_id,
                    lifecycle=CanonicalEntityLifecycle.SPLIT,
                    decision_kind=EntityLineageDecisionKind.SPLIT,
                    decision_id=str(result.split_decision_id),
                    ledger_seq=committed.ledger_seq,
                    recorded_at=recorded_at,
                )
                self._insert_projection_event(
                    conn,
                    source_event_id=source_event,
                    source_ledger_seq=committed.ledger_seq,
                    entity_id=result.source_entity_id,
                    version_id=result.source_split_version_id,
                    preferred_entity_id=result.source_entity_id,
                    lifecycle=CanonicalEntityLifecycle.SPLIT,
                    recorded_at=recorded_at,
                )
                for successor in result.successors:
                    self._upsert_preferred(
                        conn,
                        entity_id=successor.entity_id,
                        version_id=successor.entity_version_id,
                        preferred_entity_id=successor.entity_id,
                        lifecycle=CanonicalEntityLifecycle.ACTIVE,
                        decision_kind=EntityLineageDecisionKind.SPLIT,
                        decision_id=str(result.split_decision_id),
                        ledger_seq=committed.ledger_seq,
                        recorded_at=recorded_at,
                    )
                    self._insert_projection_event(
                        conn,
                        source_event_id=source_event,
                        source_ledger_seq=committed.ledger_seq,
                        entity_id=successor.entity_id,
                        version_id=successor.entity_version_id,
                        preferred_entity_id=successor.entity_id,
                        lifecycle=CanonicalEntityLifecycle.ACTIVE,
                        recorded_at=recorded_at,
                    )
                row = self._row_for_event(
                    conn,
                    table="entity_split_decisions",
                    event_id=committed.event_id,
                    identity="entity split decision",
                )
                return self._split_decision_from_row(conn, row, replayed=False)

    def commit_entity_reversal(
        self,
        grant: _AuthorizedCommandGrant,
        request: EntityReversalDecisionRequest,
    ) -> EntityReversalDecision:
        payload = canonical_json_bytes(request.canonical_value())
        self._require_entity_grant(
            grant,
            command_type=ENTITY_REVERSAL_DECIDE_COMMAND,
            aggregate_id=str(request.reversal_decision_id),
            expected_aggregate_version=0,
            canonical_bytes=payload,
        )
        with self._lock:
            with self._transaction() as conn:
                now = self._clock()
                grant.authentication.require_current(now)
                committed = self._commit_grant_in_transaction(
                    conn, grant, recorded_at=now.to_text()
                )
                if grant.replay_of_command_id is not None:
                    row = self._row_for_event(
                        conn,
                        table="entity_reversal_decisions",
                        event_id=committed.event_id,
                        identity="entity reversal decision",
                    )
                    return self._reversal_decision_from_row(conn, row, replayed=True)
                if conn.execute(
                    "SELECT 1 FROM entity_reversal_decisions WHERE reversal_decision_id=?",
                    (str(request.reversal_decision_id),),
                ).fetchone() is not None:
                    raise EntityIdentifierReuse(
                        "reversal decision identity is already retained"
                    )
                if conn.execute(
                    "SELECT 1 FROM entity_reversal_decisions "
                    "WHERE target_kind=? AND target_decision_id=?",
                    (request.target_kind.value, request.target_decision_id),
                ).fetchone() is not None:
                    raise EntityDecisionConflict("lineage decision is already reversed")

                restoration_ids = tuple(item.entity_id for item in request.restorations)
                supersessions: tuple[EntityLineageVersion, ...]
                preferred: dict[CanonicalEntityId, CanonicalEntityId] = {}
                entity_kinds: dict[CanonicalEntityId, EntityKind] = {}
                current_versions: dict[CanonicalEntityId, CanonicalEntityVersionId] = {}
                current_numbers: dict[CanonicalEntityId, int] = {}
                if request.target_kind is EntityReversalTargetKind.MERGE:
                    target = conn.execute(
                        "SELECT * FROM entity_merge_decisions WHERE merge_decision_id=?",
                        (request.target_decision_id,),
                    ).fetchone()
                    if target is None:
                        raise EntityStateError("target merge decision is missing")
                    predecessor_rows = conn.execute(
                        "SELECT * FROM entity_merge_predecessors WHERE merge_decision_id=? "
                        "ORDER BY predecessor_ordinal",
                        (request.target_decision_id,),
                    ).fetchall()
                    expected_restore_ids = tuple(
                        CanonicalEntityId.parse(str(row["entity_id"]))
                        for row in predecessor_rows
                    )
                    if restoration_ids != expected_restore_ids:
                        raise EntityDecisionConflict(
                            "merge reversal must restore every predecessor identity"
                        )
                    affected_ids = (*expected_restore_ids, CanonicalEntityId.parse(str(target["successor_entity_id"])))
                    successor_id = affected_ids[-1]
                    supersessions = (
                        EntityLineageVersion(
                            successor_id,
                            deterministic_lineage_version_id(
                                decision_kind="REVERSAL",
                                decision_id=str(request.reversal_decision_id),
                                entity_id=successor_id,
                                role="SUPERSEDED",
                            ),
                        ),
                    )
                    preferred[successor_id] = CanonicalEntityId.parse(
                        str(target["preferred_continuation_entity_id"])
                    )
                    for entity_id in expected_restore_ids:
                        preferred[entity_id] = entity_id
                else:
                    target = conn.execute(
                        "SELECT * FROM entity_split_decisions WHERE split_decision_id=?",
                        (request.target_decision_id,),
                    ).fetchone()
                    if target is None:
                        raise EntityStateError("target split decision is missing")
                    source_id = CanonicalEntityId.parse(str(target["source_entity_id"]))
                    if restoration_ids != (source_id,):
                        raise EntityDecisionConflict(
                            "split reversal must restore the exact source identity"
                        )
                    successor_rows = conn.execute(
                        "SELECT * FROM entity_split_successors WHERE split_decision_id=? "
                        "ORDER BY successor_ordinal",
                        (request.target_decision_id,),
                    ).fetchall()
                    successor_ids = tuple(
                        CanonicalEntityId.parse(str(row["entity_id"]))
                        for row in successor_rows
                    )
                    affected_ids = (source_id, *successor_ids)
                    supersessions = tuple(
                        EntityLineageVersion(
                            entity_id,
                            deterministic_lineage_version_id(
                                decision_kind="REVERSAL",
                                decision_id=str(request.reversal_decision_id),
                                entity_id=entity_id,
                                role="SUPERSEDED",
                            ),
                        )
                        for entity_id in successor_ids
                    )
                    preferred[source_id] = source_id
                    for entity_id in successor_ids:
                        preferred[entity_id] = source_id

                for entity_id in affected_ids:
                    self._require_entity_current(conn, entity_id)
                    head = self._entity_head_row(conn, entity_id)
                    entity = conn.execute(
                        "SELECT entity_kind FROM canonical_entities WHERE entity_id=?",
                        (str(entity_id),),
                    ).fetchone()
                    if entity is None:
                        raise AuthorityPersistenceError("reversal entity is missing")
                    entity_kinds[entity_id] = EntityKind(str(entity["entity_kind"]))
                    current_versions[entity_id] = CanonicalEntityVersionId.parse(
                        str(head["current_entity_version_id"])
                    )
                    current_numbers[entity_id] = int(head["current_version_number"])
                actual_expected = tuple(sorted(current_versions.values(), key=str))
                if actual_expected != request.expected_current_entity_version_ids:
                    raise EntityStaleDecision(
                        "reversal expected versions do not match every current lineage head"
                    )
                for item in (*request.restorations, *supersessions):
                    self._ensure_absent_identifier(
                        conn,
                        table="canonical_entity_versions",
                        column="entity_version_id",
                        value=str(item.entity_version_id),
                        identity="reversal result version",
                    )

                recorded_at = now
                source_event = EventId.parse(committed.event_id)
                result = EntityReversalDecision(
                    reversal_decision_id=request.reversal_decision_id,
                    target_kind=request.target_kind,
                    target_decision_id=request.target_decision_id,
                    expected_current_entity_version_ids=request.expected_current_entity_version_ids,
                    restorations=request.restorations,
                    supersessions=supersessions,
                    reason_code=request.reason_code,
                    decision_policy_version=request.decision_policy_version,
                    authority_event_id=source_event,
                    authority_ledger_seq=committed.ledger_seq,
                    recorded_at=recorded_at,
                )
                data = canonical_json_bytes(result.canonical_value())
                conn.execute(
                    "INSERT INTO entity_reversal_decisions("
                    "reversal_decision_id,target_kind,target_decision_id,reason_code,"
                    "decision_policy_version,request_digest,authority_event_id,"
                    "authority_aggregate_version,canonical_bytes,canonical_digest,recorded_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        str(result.reversal_decision_id),
                        result.target_kind.value,
                        result.target_decision_id,
                        result.reason_code,
                        result.decision_policy_version,
                        request.digest,
                        committed.event_id,
                        committed.aggregate_version,
                        data,
                        digest_bytes(data),
                        recorded_at.to_text(),
                    ),
                )
                for ordinal, version_id in enumerate(
                    result.expected_current_entity_version_ids, start=1
                ):
                    conn.execute(
                        "INSERT INTO entity_reversal_expected_versions("
                        "reversal_decision_id,version_ordinal,entity_version_id) "
                        "VALUES(?,?,?)",
                        (str(result.reversal_decision_id), ordinal, str(version_id)),
                    )
                for table, values, ordinal_name in (
                    ("entity_reversal_restorations", result.restorations, "restoration_ordinal"),
                    ("entity_reversal_supersessions", result.supersessions, "supersession_ordinal"),
                ):
                    for ordinal, item in enumerate(values, start=1):
                        child = canonical_json_bytes(item.canonical_value())
                        conn.execute(
                            f"INSERT INTO {table}(reversal_decision_id,{ordinal_name},"
                            "entity_id,entity_version_id,canonical_bytes,canonical_digest) "
                            "VALUES(?,?,?,?,?,?)",
                            (
                                str(result.reversal_decision_id),
                                ordinal,
                                str(item.entity_id),
                                str(item.entity_version_id),
                                child,
                                digest_bytes(child),
                            ),
                        )

                for item in result.restorations:
                    version = CanonicalEntityVersion(
                        entity_version_id=item.entity_version_id,
                        entity_id=item.entity_id,
                        version_number=current_numbers[item.entity_id] + 1,
                        previous_entity_version_id=current_versions[item.entity_id],
                        entity_kind=entity_kinds[item.entity_id],
                        lifecycle=CanonicalEntityLifecycle.ACTIVE,
                        lineage_decision_kind=EntityLineageDecisionKind.REVERSAL,
                        lineage_decision_id=str(result.reversal_decision_id),
                        preferred_continuation_entity_id=item.entity_id,
                        authority_event_id=source_event,
                        authority_ledger_seq=committed.ledger_seq,
                        recorded_at=recorded_at,
                    )
                    self._insert_lineage_version(
                        conn,
                        version=version,
                        aggregate_version=committed.aggregate_version,
                    )
                    self._upsert_preferred(
                        conn,
                        entity_id=item.entity_id,
                        version_id=item.entity_version_id,
                        preferred_entity_id=item.entity_id,
                        lifecycle=CanonicalEntityLifecycle.ACTIVE,
                        decision_kind=EntityLineageDecisionKind.REVERSAL,
                        decision_id=str(result.reversal_decision_id),
                        ledger_seq=committed.ledger_seq,
                        recorded_at=recorded_at,
                    )
                    self._insert_projection_event(
                        conn,
                        source_event_id=source_event,
                        source_ledger_seq=committed.ledger_seq,
                        entity_id=item.entity_id,
                        version_id=item.entity_version_id,
                        preferred_entity_id=item.entity_id,
                        lifecycle=CanonicalEntityLifecycle.ACTIVE,
                        recorded_at=recorded_at,
                    )
                for item in result.supersessions:
                    version = CanonicalEntityVersion(
                        entity_version_id=item.entity_version_id,
                        entity_id=item.entity_id,
                        version_number=current_numbers[item.entity_id] + 1,
                        previous_entity_version_id=current_versions[item.entity_id],
                        entity_kind=entity_kinds[item.entity_id],
                        lifecycle=CanonicalEntityLifecycle.REVERSED,
                        lineage_decision_kind=EntityLineageDecisionKind.REVERSAL,
                        lineage_decision_id=str(result.reversal_decision_id),
                        preferred_continuation_entity_id=preferred[item.entity_id],
                        authority_event_id=source_event,
                        authority_ledger_seq=committed.ledger_seq,
                        recorded_at=recorded_at,
                    )
                    self._insert_lineage_version(
                        conn,
                        version=version,
                        aggregate_version=committed.aggregate_version,
                    )
                    self._upsert_preferred(
                        conn,
                        entity_id=item.entity_id,
                        version_id=item.entity_version_id,
                        preferred_entity_id=preferred[item.entity_id],
                        lifecycle=CanonicalEntityLifecycle.REVERSED,
                        decision_kind=EntityLineageDecisionKind.REVERSAL,
                        decision_id=str(result.reversal_decision_id),
                        ledger_seq=committed.ledger_seq,
                        recorded_at=recorded_at,
                    )
                    self._insert_projection_event(
                        conn,
                        source_event_id=source_event,
                        source_ledger_seq=committed.ledger_seq,
                        entity_id=item.entity_id,
                        version_id=item.entity_version_id,
                        preferred_entity_id=preferred[item.entity_id],
                        lifecycle=CanonicalEntityLifecycle.REVERSED,
                        recorded_at=recorded_at,
                    )
                row = self._row_for_event(
                    conn,
                    table="entity_reversal_decisions",
                    event_id=committed.event_id,
                    identity="entity reversal decision",
                )
                return self._reversal_decision_from_row(conn, row, replayed=False)


__all__ = ["_EntityLineageMixin"]
