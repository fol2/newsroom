from __future__ import annotations

from newsroom.authority._capability import _AuthorizedCommandGrant
from newsroom.sources.item_models import (
    LocatorContinuityDecisionRequest,
    SourceItemRequest,
)
from newsroom.sources.observation_models import (
    DiscoveryOccurrenceRequest,
    DiscoveryRepresentationRequest,
    SourceRevisionRequest,
)
from newsroom.sources.policy import (
    DISCOVERY_OCCURRENCE_RECORD_COMMAND,
    DISCOVERY_REPRESENTATION_RECORD_COMMAND,
    SOURCE_ITEM_REGISTER_COMMAND,
    SOURCE_LOCATOR_CONTINUITY_DECIDE_COMMAND,
    SOURCE_REVISION_RECORD_COMMAND,
)
from newsroom.sources.record_models import (
    DiscoveryOccurrence,
    DiscoveryRepresentation,
    LocatorContinuityDecision,
    SourceItem,
    SourceRevision,
)
from newsroom.sources.types import (
    LocatorContinuityOutcome,
    SourceDefinitionId,
    SourceSemanticCollision,
    SourceStateError,
    SourceVersionConflict,
)


class _SourceRegistryLineageCommitMixin:
    def commit_source_item(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        request: SourceItemRequest,
    ) -> SourceItem:
        if not isinstance(request, SourceItemRequest):
            raise TypeError("source item commit requires a typed request")
        self._require_source_grant(
            grant,
            command_type=SOURCE_ITEM_REGISTER_COMMAND,
            aggregate_id=str(request.item_id),
            canonical_bytes=request.canonical_bytes,
        )
        with self._lock, self._transaction() as conn:
            if grant.replay_of_command_id is not None:
                committed = self._commit_grant_in_transaction(
                    conn, grant, recorded_at=self._clock().to_text()
                )
                return self._source_item_for_event(
                    conn, committed.event_id, replayed=True
                )
            version = self._require_current_version(
                conn,
                definition_id=request.definition_id,
                version_id=request.definition_version_id,
            )
            if (
                request.identity_policy.policy_id
                != str(version["item_identity_policy_id"])
                or request.identity_policy.policy_version
                != str(version["item_identity_policy_version"])
            ):
                raise SourceVersionConflict(
                    "source item identity policy differs from its source version"
                )
            self._ensure_identifier_absent(
                conn,
                table="source_items",
                column="item_id",
                identifier=str(request.item_id),
                identity="source item identity",
            )
            self._ensure_semantic_absent(
                conn,
                table="source_items",
                predicate="definition_id=? AND identity_digest=?",
                parameters=(
                    str(request.definition_id),
                    request.identity_digest,
                ),
                identity="source item semantics",
            )
            if request.source_native_id is not None:
                self._ensure_semantic_absent(
                    conn,
                    table="source_items",
                    predicate="definition_id=? AND source_native_id=?",
                    parameters=(
                        str(request.definition_id),
                        request.source_native_id,
                    ),
                    identity="source-native item identity",
                )
            recorded_at = self._clock().to_text()
            committed = self._commit_grant_in_transaction(
                conn, grant, recorded_at=recorded_at
            )
            if committed.replayed:
                return self._source_item_for_event(
                    conn, committed.event_id, replayed=True
                )
            conn.execute(
                "INSERT INTO source_items("
                "item_id,definition_id,definition_version_id,identity_kind,"
                "identity_policy_id,identity_policy_version,source_native_id,"
                "identity_components_bytes,uncertainties_bytes,identity_digest,"
                "authority_event_id,authority_aggregate_version,canonical_bytes,"
                "canonical_digest,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(request.item_id),
                    str(request.definition_id),
                    str(request.definition_version_id),
                    request.identity_kind.value,
                    request.identity_policy.policy_id,
                    request.identity_policy.policy_version,
                    request.source_native_id,
                    self._json_blob(
                        [item.canonical_value() for item in request.identity_components]
                    ),
                    self._json_blob(list(request.uncertainties)),
                    request.identity_digest,
                    committed.event_id,
                    committed.aggregate_version,
                    request.canonical_bytes,
                    request.digest,
                    recorded_at,
                ),
            )
            return self._source_item_for_event(
                conn, committed.event_id, replayed=False
            )

    def commit_locator_continuity_decision(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        request: LocatorContinuityDecisionRequest,
    ) -> LocatorContinuityDecision:
        if not isinstance(request, LocatorContinuityDecisionRequest):
            raise TypeError("locator continuity commit requires a typed request")
        self._require_source_grant(
            grant,
            command_type=SOURCE_LOCATOR_CONTINUITY_DECIDE_COMMAND,
            aggregate_id=str(request.decision_id),
            canonical_bytes=request.canonical_bytes,
        )
        with self._lock, self._transaction() as conn:
            if grant.replay_of_command_id is not None:
                committed = self._commit_grant_in_transaction(
                    conn, grant, recorded_at=self._clock().to_text()
                )
                return self._locator_decision_for_event(
                    conn, committed.event_id, replayed=True
                )
            version = self._require_current_version(
                conn,
                definition_id=request.definition_id,
                version_id=request.definition_version_id,
            )
            prior = self._item_row(conn, str(request.prior_item_id))
            related = self._item_row(conn, str(request.related_item_id))
            if (
                str(prior["definition_id"]) != str(request.definition_id)
                or str(related["definition_id"]) != str(request.definition_id)
            ):
                raise SourceStateError(
                    "locator continuity items must share the source definition"
                )
            if str(version["locator"]) != request.observed_locator:
                raise SourceVersionConflict(
                    "observed locator differs from the exact current source version"
                )
            prior_digest = self._digest_value(
                {
                    "definition_id": str(request.definition_id),
                    "locator": request.prior_locator,
                }
            )
            prior_locator = conn.execute(
                "SELECT 1 FROM source_definition_versions "
                "WHERE definition_id=? AND locator_digest=?",
                (str(request.definition_id), prior_digest),
            ).fetchone()
            if prior_locator is None:
                raise SourceStateError(
                    "prior locator has no retained source-version provenance"
                )
            self._ensure_identifier_absent(
                conn,
                table="source_locator_continuity_decisions",
                column="decision_id",
                identifier=str(request.decision_id),
                identity="locator continuity decision identity",
            )
            self._ensure_semantic_absent(
                conn,
                table="source_locator_continuity_decisions",
                predicate="definition_id=? AND semantic_digest=?",
                parameters=(
                    str(request.definition_id),
                    request.semantic_digest,
                ),
                identity="locator continuity semantics",
            )
            if (
                request.outcome is LocatorContinuityOutcome.SAME_ITEM
                and request.related_item_id != request.prior_item_id
            ):
                raise SourceStateError(
                    "same-item locator decision changed stable identity"
                )
            recorded_at = self._clock().to_text()
            committed = self._commit_grant_in_transaction(
                conn, grant, recorded_at=recorded_at
            )
            if committed.replayed:
                return self._locator_decision_for_event(
                    conn, committed.event_id, replayed=True
                )
            conn.execute(
                "INSERT INTO source_locator_continuity_decisions("
                "decision_id,definition_id,definition_version_id,prior_item_id,"
                "prior_locator,prior_locator_digest,observed_locator,"
                "observed_locator_digest,outcome,related_item_id,rationale,"
                "decision_policy_id,decision_policy_version,observed_at,"
                "semantic_digest,authority_event_id,authority_aggregate_version,"
                "canonical_bytes,canonical_digest,recorded_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(request.decision_id),
                    str(request.definition_id),
                    str(request.definition_version_id),
                    str(request.prior_item_id),
                    request.prior_locator,
                    prior_digest,
                    request.observed_locator,
                    str(version["locator_digest"]),
                    request.outcome.value,
                    str(request.related_item_id),
                    request.rationale,
                    request.decision_policy.policy_id,
                    request.decision_policy.policy_version,
                    request.observed_at.to_text(),
                    request.semantic_digest,
                    committed.event_id,
                    committed.aggregate_version,
                    request.canonical_bytes,
                    request.digest,
                    recorded_at,
                ),
            )
            return self._locator_decision_for_event(
                conn, committed.event_id, replayed=False
            )

    def commit_source_revision(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        request: SourceRevisionRequest,
    ) -> SourceRevision:
        if not isinstance(request, SourceRevisionRequest):
            raise TypeError("source revision commit requires a typed request")
        self._require_source_grant(
            grant,
            command_type=SOURCE_REVISION_RECORD_COMMAND,
            aggregate_id=str(request.revision_id),
            canonical_bytes=request.canonical_bytes,
        )
        with self._lock, self._transaction() as conn:
            if grant.replay_of_command_id is not None:
                committed = self._commit_grant_in_transaction(
                    conn, grant, recorded_at=self._clock().to_text()
                )
                return self._source_revision_for_event(
                    conn, committed.event_id, replayed=True
                )
            item = self._item_row(conn, str(request.item_id))
            definition_id = str(item["definition_id"])
            version = self._require_current_version(
                conn,
                definition_id=SourceDefinitionId.parse(definition_id),
                version_id=request.definition_version_id,
            )
            if (
                request.revision_policy.policy_id
                != str(version["revision_policy_id"])
                or request.revision_policy.policy_version
                != str(version["revision_policy_version"])
            ):
                raise SourceVersionConflict(
                    "source revision policy differs from its source version"
                )
            self._ensure_identifier_absent(
                conn,
                table="source_revisions",
                column="revision_id",
                identifier=str(request.revision_id),
                identity="source revision identity",
            )
            self._ensure_semantic_absent(
                conn,
                table="source_revisions",
                predicate="item_id=? AND revision_identity_digest=?",
                parameters=(
                    str(request.item_id),
                    request.revision_identity_digest,
                ),
                identity="source revision semantics",
            )
            if request.source_native_revision_token is not None:
                self._ensure_semantic_absent(
                    conn,
                    table="source_revisions",
                    predicate=(
                        "item_id=? AND source_native_revision_token=?"
                    ),
                    parameters=(
                        str(request.item_id),
                        request.source_native_revision_token,
                    ),
                    identity="source-native revision token",
                )
            latest = conn.execute(
                "SELECT r.revision_id FROM source_revisions r "
                "JOIN ledger_events e ON e.event_id=r.authority_event_id "
                "WHERE r.item_id=? ORDER BY e.ledger_seq DESC LIMIT 1",
                (str(request.item_id),),
            ).fetchone()
            expected_prior = None if latest is None else str(latest["revision_id"])
            actual_prior = (
                None
                if request.prior_revision_id is None
                else str(request.prior_revision_id)
            )
            if actual_prior != expected_prior:
                raise SourceVersionConflict(
                    "source revision does not extend the exact retained revision head"
                )
            recorded_at = self._clock().to_text()
            committed = self._commit_grant_in_transaction(
                conn, grant, recorded_at=recorded_at
            )
            if committed.replayed:
                return self._source_revision_for_event(
                    conn, committed.event_id, replayed=True
                )
            conn.execute(
                "INSERT INTO source_revisions("
                "revision_id,item_id,definition_id,definition_version_id,"
                "prior_revision_id,source_native_revision_token,"
                "permitted_state_digest,revision_policy_id,revision_policy_version,"
                "canonicalizer_version,source_published_time_bytes,"
                "source_updated_time_bytes,observed_at,revision_identity_digest,"
                "authority_event_id,authority_aggregate_version,canonical_bytes,"
                "canonical_digest,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(request.revision_id),
                    str(request.item_id),
                    definition_id,
                    str(request.definition_version_id),
                    actual_prior,
                    request.source_native_revision_token,
                    request.permitted_state_digest,
                    request.revision_policy.policy_id,
                    request.revision_policy.policy_version,
                    request.canonicalizer_version,
                    self._json_blob(request.source_published_time.canonical_value()),
                    self._json_blob(request.source_updated_time.canonical_value()),
                    request.observed_at.to_text(),
                    request.revision_identity_digest,
                    committed.event_id,
                    committed.aggregate_version,
                    request.canonical_bytes,
                    request.digest,
                    recorded_at,
                ),
            )
            return self._source_revision_for_event(
                conn, committed.event_id, replayed=False
            )

    def commit_discovery_representation(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        request: DiscoveryRepresentationRequest,
    ) -> DiscoveryRepresentation:
        if not isinstance(request, DiscoveryRepresentationRequest):
            raise TypeError("representation commit requires a typed request")
        self._require_source_grant(
            grant,
            command_type=DISCOVERY_REPRESENTATION_RECORD_COMMAND,
            aggregate_id=str(request.representation_id),
            canonical_bytes=request.canonical_bytes,
        )
        with self._lock, self._transaction() as conn:
            if grant.replay_of_command_id is not None:
                committed = self._commit_grant_in_transaction(
                    conn, grant, recorded_at=self._clock().to_text()
                )
                return self._representation_for_event(
                    conn, committed.event_id, replayed=True
                )
            revision = self._revision_row(conn, str(request.revision_id))
            if (
                str(revision["definition_version_id"])
                != str(request.definition_version_id)
            ):
                raise SourceVersionConflict(
                    "representation source version differs from its revision"
                )
            self._ensure_identifier_absent(
                conn,
                table="discovery_representations",
                column="representation_id",
                identifier=str(request.representation_id),
                identity="discovery representation identity",
            )
            slot = conn.execute(
                "SELECT representation_identity_digest "
                "FROM discovery_representations "
                "WHERE revision_id=? AND producer_slot_digest=?",
                (str(request.revision_id), request.producer_slot_digest),
            ).fetchone()
            if slot is not None:
                raise SourceSemanticCollision(
                    "one producer-version slot cannot emit conflicting representation bytes"
                )
            self._ensure_semantic_absent(
                conn,
                table="discovery_representations",
                predicate="revision_id=? AND representation_identity_digest=?",
                parameters=(
                    str(request.revision_id),
                    request.representation_identity_digest,
                ),
                identity="discovery representation semantics",
            )
            recorded_at = self._clock().to_text()
            committed = self._commit_grant_in_transaction(
                conn, grant, recorded_at=recorded_at
            )
            if committed.replayed:
                return self._representation_for_event(
                    conn, committed.event_id, replayed=True
                )
            conn.execute(
                "INSERT INTO discovery_representations("
                "representation_id,revision_id,definition_id,definition_version_id,"
                "adapter_version,parser_version,normalizer_version,"
                "extraction_scope_version,permitted_fields_digest,"
                "representation_digest,producer_slot_digest,"
                "representation_identity_digest,produced_at,authority_event_id,"
                "authority_aggregate_version,canonical_bytes,canonical_digest,"
                "recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(request.representation_id),
                    str(request.revision_id),
                    str(revision["definition_id"]),
                    str(request.definition_version_id),
                    request.adapter_version,
                    request.parser_version,
                    request.normalizer_version,
                    request.extraction_scope_version,
                    request.permitted_fields_digest,
                    request.representation_digest,
                    request.producer_slot_digest,
                    request.representation_identity_digest,
                    request.produced_at.to_text(),
                    committed.event_id,
                    committed.aggregate_version,
                    request.canonical_bytes,
                    request.digest,
                    recorded_at,
                ),
            )
            return self._representation_for_event(
                conn, committed.event_id, replayed=False
            )

    def commit_discovery_occurrence(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        request: DiscoveryOccurrenceRequest,
    ) -> DiscoveryOccurrence:
        if not isinstance(request, DiscoveryOccurrenceRequest):
            raise TypeError("occurrence commit requires a typed request")
        self._require_source_grant(
            grant,
            command_type=DISCOVERY_OCCURRENCE_RECORD_COMMAND,
            aggregate_id=str(request.occurrence_id),
            canonical_bytes=request.canonical_bytes,
        )
        with self._lock, self._transaction() as conn:
            if grant.replay_of_command_id is not None:
                committed = self._commit_grant_in_transaction(
                    conn, grant, recorded_at=self._clock().to_text()
                )
                return self._occurrence_for_event(
                    conn, committed.event_id, replayed=True
                )
            revision = self._revision_row(conn, str(request.revision_id))
            if (
                str(revision["definition_version_id"])
                != str(request.definition_version_id)
            ):
                raise SourceVersionConflict(
                    "occurrence source version differs from its revision"
                )
            if request.representation_id is not None:
                representation = self._representation_row(
                    conn, str(request.representation_id)
                )
                if str(representation["revision_id"]) != str(request.revision_id):
                    raise SourceStateError(
                        "occurrence representation belongs to another revision"
                    )
            self._ensure_identifier_absent(
                conn,
                table="discovery_occurrences",
                column="occurrence_id",
                identifier=str(request.occurrence_id),
                identity="discovery occurrence identity",
            )
            self._ensure_semantic_absent(
                conn,
                table="discovery_occurrences",
                predicate="semantic_digest=?",
                parameters=(request.semantic_digest,),
                identity="discovery occurrence semantics",
            )
            recorded_at = self._clock().to_text()
            committed = self._commit_grant_in_transaction(
                conn, grant, recorded_at=recorded_at
            )
            if committed.replayed:
                return self._occurrence_for_event(
                    conn, committed.event_id, replayed=True
                )
            conn.execute(
                "INSERT INTO discovery_occurrences("
                "occurrence_id,check_outcome_id,revision_id,representation_id,"
                "definition_id,definition_version_id,occurrence_kind,observed_at,"
                "receipt_digest,source_asserted_time_bytes,semantic_digest,"
                "authority_event_id,authority_aggregate_version,canonical_bytes,"
                "canonical_digest,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(request.occurrence_id),
                    str(request.check_outcome_id),
                    str(request.revision_id),
                    (
                        None
                        if request.representation_id is None
                        else str(request.representation_id)
                    ),
                    str(revision["definition_id"]),
                    str(request.definition_version_id),
                    request.kind.value,
                    request.observed_at.to_text(),
                    request.receipt_digest,
                    self._json_blob(request.source_asserted_time.canonical_value()),
                    request.semantic_digest,
                    committed.event_id,
                    committed.aggregate_version,
                    request.canonical_bytes,
                    request.digest,
                    recorded_at,
                ),
            )
            return self._occurrence_for_event(
                conn, committed.event_id, replayed=False
            )


__all__ = ["_SourceRegistryLineageCommitMixin"]
