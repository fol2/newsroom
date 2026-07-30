from __future__ import annotations

import sqlite3

from newsroom.authority._capability import _AuthorizedCommandGrant
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes, digest_canonical
from newsroom.authority.persistence import AuthorityPersistenceError
from newsroom.authority.types import EventId, UtcTimestamp
from newsroom.entities.models import (
    CanonicalEntity,
    CanonicalEntityVersion,
    EntityAlias,
    EntityMention,
    EntityMentionAdmissionRequest,
    EntityResolutionDecision,
    EntityResolutionDecisionRequest,
    EntityResolutionProposalRequest,
    EntityResolutionProposalVersion,
)
from newsroom.entities.policy import (
    ENTITY_MENTION_ADMIT_COMMAND,
    ENTITY_RESOLUTION_DECIDE_COMMAND,
    ENTITY_RESOLUTION_PROPOSE_COMMAND,
)
from newsroom.entities.types import (
    CanonicalEntityLifecycle,
    EntityDecisionConflict,
    EntityIdentifierReuse,
    EntityResolutionDecisionAction,
    EntityResolutionProposalKind,
    EntityResolutionState,
    EntitySemanticCollision,
    EntityStaleDecision,
    EntityStateError,
    classify_entity_script,
    normalize_entity_text,
)
from newsroom.extraction.types import ExtractionProposalKind
from newsroom.sources.types import (
    DiscoveryRepresentationId,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceItemId,
    SourceRevisionId,
)

from ._entity_store_common import deterministic_decision_id


class _EntityCommitMixin:
    def commit_entity_mention(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        request: EntityMentionAdmissionRequest,
    ) -> EntityMention:
        if not isinstance(request, EntityMentionAdmissionRequest):
            raise TypeError("entity mention commit requires a typed request")
        self._require_entity_grant(
            grant,
            command_type=ENTITY_MENTION_ADMIT_COMMAND,
            aggregate_id=str(request.mention_id),
            expected_aggregate_version=0,
            canonical_bytes=canonical_json_bytes(request.canonical_value()),
        )
        with self._lock, self._transaction() as conn:
            now = self._clock()
            grant.authentication.require_current(now)
            if grant.replay_of_command_id is not None:
                committed = self._commit_grant_in_transaction(
                    conn, grant, recorded_at=now.to_text()
                )
                row = self._row_for_event(
                    conn,
                    table="entity_mentions",
                    event_id=committed.event_id,
                    identity="entity mention",
                )
                result = self._mention_from_row(conn, row, replayed=True)
                self._require_mention_current(conn, result)
                return result

            source = self._source_proposal(conn, request.source_proposal_id)
            if source.kind is not ExtractionProposalKind.ENTITY_MENTION:
                raise EntityStateError("entity mention requires an ENTITY_MENTION proposal")
            if source.canonical_digest != request.expected_source_proposal_digest:
                raise EntityStaleDecision("source proposal digest differs")
            if len(source.evidence) != 1:
                raise EntityStateError("entity mention requires one exact evidence range")
            evidence = source.evidence[0]
            passage = conn.execute(
                "SELECT p.*,r.definition_id,r.definition_version_id,r.item_id,"
                "r.revision_id,r.representation_id "
                "FROM extraction_run_passages p "
                "JOIN extraction_runs r ON r.run_id=p.run_id "
                "WHERE p.run_id=? AND p.passage_id=?",
                (str(source.run_id), str(evidence.passage_id)),
            ).fetchone()
            if passage is None:
                raise AuthorityPersistenceError("mention evidence passage is missing")
            mention_text = source.subject_placeholder
            text_bytes = mention_text.encode("utf-8")
            if (
                len(text_bytes) != evidence.end_byte - evidence.start_byte
                or digest_bytes(text_bytes) != evidence.evidence_text_digest
            ):
                raise AuthorityPersistenceError(
                    "mention placeholder differs from exact extraction evidence"
                )
            if request.normalized_text != normalize_entity_text(mention_text):
                raise EntityStateError("mention normalized text differs from exact text")
            if request.script is not classify_entity_script(mention_text):
                raise EntityStateError("mention script differs from exact text")
            if request.language != str(passage["language"]):
                raise EntityStateError("mention language differs from governed passage")

            self._ensure_identifier_absent(
                conn,
                table="entity_mentions",
                column="mention_id",
                identifier=str(request.mention_id),
                identity="entity mention identity",
            )
            recorded_at = now.to_text()
            committed = self._commit_grant_in_transaction(
                conn, grant, recorded_at=recorded_at
            )
            if committed.replayed:
                row = self._row_for_event(
                    conn,
                    table="entity_mentions",
                    event_id=committed.event_id,
                    identity="entity mention",
                )
                return self._mention_from_row(conn, row, replayed=True)

            result = EntityMention(
                mention_id=request.mention_id,
                source_proposal_id=source.proposal_id,
                proposal_set_id=source.proposal_set_id,
                output_id=source.output_id,
                run_id=source.run_id,
                run_version_id=source.run_version_id,
                definition_id=SourceDefinitionId.parse(str(passage["definition_id"])),
                definition_version_id=SourceDefinitionVersionId.parse(str(passage["definition_version_id"])),
                item_id=SourceItemId.parse(str(passage["item_id"])),
                revision_id=SourceRevisionId.parse(str(passage["revision_id"])),
                representation_id=DiscoveryRepresentationId.parse(str(passage["representation_id"])),
                passage_id=evidence.passage_id,
                start_byte=evidence.start_byte,
                end_byte=evidence.end_byte,
                evidence_text_digest=evidence.evidence_text_digest,
                mention_text=mention_text,
                normalized_text=request.normalized_text,
                normalization_contract_digest=request.normalization_contract_digest,
                language=request.language,
                script=request.script,
                entity_kind=request.entity_kind,
                confidence_basis_points=source.confidence_basis_points,
                uncertainty_codes=source.uncertainty_codes,
                rationale_codes=source.rationale_codes,
                source_proposal_digest=source.canonical_digest,
                authority_event_id=EventId.parse(committed.event_id),
                authority_ledger_seq=committed.ledger_seq,
                recorded_at=UtcTimestamp.parse(recorded_at),
                replayed=False,
            )
            self._ensure_semantic_absent(
                conn,
                table="entity_mentions",
                column="semantic_digest",
                digest=result.semantic_digest,
                identity="entity mention semantics",
            )
            data = canonical_json_bytes(result.canonical_value())
            conn.execute(
                "INSERT INTO entity_mentions("
                "mention_id,source_proposal_id,proposal_set_id,output_id,run_id,"
                "run_version_id,definition_id,definition_version_id,item_id,"
                "revision_id,representation_id,passage_id,start_byte,end_byte,"
                "evidence_text_digest,mention_text,normalized_text,"
                "normalization_contract_digest,language,script,entity_kind,"
                "confidence_basis_points,uncertainty_codes_bytes,"
                "rationale_codes_bytes,source_proposal_digest,semantic_digest,"
                "authority_event_id,authority_aggregate_version,canonical_bytes,"
                "canonical_digest,recorded_at) "
                "VALUES(" + ",".join("?" for _ in range(31)) + ")",
                (
                    str(result.mention_id),
                    str(result.source_proposal_id),
                    str(result.proposal_set_id),
                    str(result.output_id),
                    str(result.run_id),
                    str(result.run_version_id),
                    str(result.definition_id),
                    str(result.definition_version_id),
                    str(result.item_id),
                    str(result.revision_id),
                    str(result.representation_id),
                    str(result.passage_id),
                    result.start_byte,
                    result.end_byte,
                    result.evidence_text_digest,
                    result.mention_text,
                    result.normalized_text,
                    result.normalization_contract_digest,
                    result.language,
                    result.script.value,
                    result.entity_kind.value,
                    result.confidence_basis_points,
                    self._json_bytes(result.uncertainty_codes),
                    self._json_bytes(result.rationale_codes),
                    result.source_proposal_digest,
                    result.semantic_digest,
                    committed.event_id,
                    committed.aggregate_version,
                    data,
                    digest_bytes(data),
                    recorded_at,
                ),
            )
            row = self._row_for_event(
                conn,
                table="entity_mentions",
                event_id=committed.event_id,
                identity="entity mention",
            )
            return self._mention_from_row(conn, row, replayed=False)

    def commit_entity_resolution_proposal(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        request: EntityResolutionProposalRequest,
    ) -> EntityResolutionProposalVersion:
        if not isinstance(request, EntityResolutionProposalRequest):
            raise TypeError("resolution proposal commit requires a typed request")
        self._require_entity_grant(
            grant,
            command_type=ENTITY_RESOLUTION_PROPOSE_COMMAND,
            aggregate_id=str(request.proposal_version_id),
            expected_aggregate_version=0,
            canonical_bytes=request.canonical_bytes,
        )
        with self._lock, self._transaction() as conn:
            now = self._clock()
            grant.authentication.require_current(now)
            if grant.replay_of_command_id is not None:
                committed = self._commit_grant_in_transaction(
                    conn, grant, recorded_at=now.to_text()
                )
                row = self._row_for_event(
                    conn,
                    table="entity_resolution_proposal_versions",
                    event_id=committed.event_id,
                    identity="entity resolution proposal version",
                )
                return self._proposal_version_from_row(conn, row, replayed=True)

            source = self._source_proposal(conn, request.source_proposal_id)
            if source.canonical_digest != request.expected_source_proposal_digest:
                raise EntityStaleDecision("source proposal digest differs")
            subject = self._mention_from_row(
                conn, self._mention_row(conn, request.subject_mention_id), replayed=False
            )
            self._require_mention_current(conn, subject)
            if request.kind is EntityResolutionProposalKind.MENTION_EQUIVALENCE:
                if source.kind is not ExtractionProposalKind.ENTITY_EQUIVALENCE:
                    raise EntityStateError("mention equivalence requires equivalence source")
                assert request.object_mention_id is not None
                other = self._mention_from_row(
                    conn, self._mention_row(conn, request.object_mention_id), replayed=False
                )
                self._require_mention_current(conn, other)
                if {subject.mention_text, other.mention_text} != {
                    source.subject_placeholder,
                    source.object_placeholder,
                }:
                    raise EntityStateError("equivalence source text differs from mentions")
            else:
                if (
                    source.kind is not ExtractionProposalKind.ENTITY_MENTION
                    or subject.source_proposal_id != source.proposal_id
                ):
                    raise EntityStateError("resolution source differs from subject mention")
            if request.candidate_entity_id is not None:
                assert request.candidate_entity_version_id is not None
                self._require_candidate_current(
                    conn,
                    entity_id=request.candidate_entity_id,
                    version_id=request.candidate_entity_version_id,
                )

            head = self._proposal_head_row(conn, request.proposal_id)
            if request.version_number == 1:
                if head is not None:
                    raise EntityStaleDecision("initial proposal already has a head")
                self._ensure_identifier_absent(
                    conn,
                    table="entity_resolution_proposals",
                    column="resolution_proposal_id",
                    identifier=str(request.proposal_id),
                    identity="resolution proposal identity",
                )
                self._ensure_semantic_absent(
                    conn,
                    table="entity_resolution_proposals",
                    column="stable_semantic_digest",
                    digest=request.stable_semantic_digest,
                    identity="resolution proposal semantics",
                )
            else:
                if (
                    head is None
                    or int(head["current_version_number"]) != request.version_number - 1
                    or str(head["current_proposal_version_id"])
                    != str(request.expected_previous_version_id)
                ):
                    raise EntityStaleDecision("proposal does not extend the current head")
                self._require_proposal_open(conn, request.proposal_id)
                base = conn.execute(
                    "SELECT stable_semantic_digest FROM entity_resolution_proposals "
                    "WHERE resolution_proposal_id=?",
                    (str(request.proposal_id),),
                ).fetchone()
                if base is None or str(base["stable_semantic_digest"]) != request.stable_semantic_digest:
                    raise EntitySemanticCollision("proposal version changes stable semantics")
            self._ensure_identifier_absent(
                conn,
                table="entity_resolution_proposal_versions",
                column="proposal_version_id",
                identifier=str(request.proposal_version_id),
                identity="resolution proposal version identity",
            )

            recorded_at = now.to_text()
            committed = self._commit_grant_in_transaction(
                conn, grant, recorded_at=recorded_at
            )
            if committed.replayed:
                row = self._row_for_event(
                    conn,
                    table="entity_resolution_proposal_versions",
                    event_id=committed.event_id,
                    identity="entity resolution proposal version",
                )
                return self._proposal_version_from_row(conn, row, replayed=True)

            if request.version_number == 1:
                base_value = {
                    "proposal_id": str(request.proposal_id),
                    "source_proposal_id": str(request.source_proposal_id),
                    "kind": request.kind.value,
                    "subject_mention_id": str(request.subject_mention_id),
                    "object_mention_id": (
                        None
                        if request.object_mention_id is None
                        else str(request.object_mention_id)
                    ),
                    "candidate_entity_id": (
                        None
                        if request.candidate_entity_id is None
                        else str(request.candidate_entity_id)
                    ),
                    "candidate_entity_version_id": (
                        None
                        if request.candidate_entity_version_id is None
                        else str(request.candidate_entity_version_id)
                    ),
                    "stable_semantic_digest": request.stable_semantic_digest,
                }
                base_bytes = canonical_json_bytes(base_value)
                conn.execute(
                    "INSERT INTO entity_resolution_proposals("
                    "resolution_proposal_id,source_proposal_id,proposal_kind,"
                    "subject_mention_id,object_mention_id,candidate_entity_id,"
                    "candidate_entity_version_id,stable_semantic_digest,"
                    "created_by_event_id,canonical_bytes,canonical_digest,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        str(request.proposal_id),
                        str(request.source_proposal_id),
                        request.kind.value,
                        str(request.subject_mention_id),
                        (
                            None
                            if request.object_mention_id is None
                            else str(request.object_mention_id)
                        ),
                        (
                            None
                            if request.candidate_entity_id is None
                            else str(request.candidate_entity_id)
                        ),
                        (
                            None
                            if request.candidate_entity_version_id is None
                            else str(request.candidate_entity_version_id)
                        ),
                        request.stable_semantic_digest,
                        committed.event_id,
                        base_bytes,
                        digest_bytes(base_bytes),
                        recorded_at,
                    ),
                )

            result = EntityResolutionProposalVersion(
                proposal_id=request.proposal_id,
                proposal_version_id=request.proposal_version_id,
                version_number=request.version_number,
                previous_proposal_version_id=request.expected_previous_version_id,
                source_proposal_id=request.source_proposal_id,
                source_proposal_digest=request.expected_source_proposal_digest,
                kind=request.kind,
                subject_mention_id=request.subject_mention_id,
                object_mention_id=request.object_mention_id,
                candidate_entity_id=request.candidate_entity_id,
                candidate_entity_version_id=request.candidate_entity_version_id,
                confidence_basis_points=request.confidence_basis_points,
                uncertainty_codes=request.uncertainty_codes,
                basis_codes=request.basis_codes,
                stable_semantic_digest=request.stable_semantic_digest,
                authority_event_id=EventId.parse(committed.event_id),
                authority_ledger_seq=committed.ledger_seq,
                recorded_at=UtcTimestamp.parse(recorded_at),
                replayed=False,
            )
            data = canonical_json_bytes(result.canonical_value())
            conn.execute(
                "INSERT INTO entity_resolution_proposal_versions("
                "proposal_version_id,resolution_proposal_id,version_number,"
                "previous_proposal_version_id,source_proposal_digest,"
                "confidence_basis_points,uncertainty_codes_bytes,basis_codes_bytes,"
                "request_bytes,request_digest,canonical_bytes,canonical_digest,"
                "authority_event_id,authority_aggregate_version,recorded_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(result.proposal_version_id),
                    str(result.proposal_id),
                    result.version_number,
                    (
                        None
                        if result.previous_proposal_version_id is None
                        else str(result.previous_proposal_version_id)
                    ),
                    result.source_proposal_digest,
                    result.confidence_basis_points,
                    self._json_bytes(result.uncertainty_codes),
                    self._json_bytes(result.basis_codes),
                    request.canonical_bytes,
                    request.digest,
                    data,
                    digest_bytes(data),
                    committed.event_id,
                    committed.aggregate_version,
                    recorded_at,
                ),
            )
            # Schema-v14 triggers create or advance the checked current-head
            # projection from the immutable proposal-version insert. The store
            # deliberately has no second writer for that derived projection.
            row = self._row_for_event(
                conn,
                table="entity_resolution_proposal_versions",
                event_id=committed.event_id,
                identity="entity resolution proposal version",
            )
            return self._proposal_version_from_row(conn, row, replayed=False)

    @staticmethod
    def _latest_mention_resolution(
        conn: sqlite3.Connection, mention_id: str
    ) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT r.*,e.ledger_seq FROM entity_mention_resolutions r "
            "JOIN entity_resolution_decisions d ON d.decision_id=r.decision_id "
            "JOIN ledger_events e ON e.event_id=d.authority_event_id "
            "WHERE r.mention_id=? ORDER BY e.ledger_seq DESC LIMIT 1",
            (mention_id,),
        ).fetchone()

    def commit_entity_resolution_decision(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        request: EntityResolutionDecisionRequest,
    ) -> EntityResolutionDecision:
        if not isinstance(request, EntityResolutionDecisionRequest):
            raise TypeError("resolution decision commit requires a typed request")
        decision_id = deterministic_decision_id(request)
        payload = canonical_json_bytes(request.canonical_value())
        self._require_entity_grant(
            grant,
            command_type=ENTITY_RESOLUTION_DECIDE_COMMAND,
            aggregate_id=str(decision_id),
            expected_aggregate_version=0,
            canonical_bytes=payload,
        )
        with self._lock, self._transaction() as conn:
            now = self._clock()
            grant.authentication.require_current(now)
            if grant.replay_of_command_id is not None:
                committed = self._commit_grant_in_transaction(
                    conn, grant, recorded_at=now.to_text()
                )
                row = self._row_for_event(
                    conn,
                    table="entity_resolution_decisions",
                    event_id=committed.event_id,
                    identity="entity resolution decision",
                )
                return self._decision_from_row(conn, row, replayed=True)

            proposal_head = self._proposal_head_row(conn, request.proposal_id)
            if (
                proposal_head is None
                or str(proposal_head["current_proposal_version_id"])
                != str(request.expected_proposal_version_id)
            ):
                raise EntityStaleDecision("resolution proposal version is no longer current")
            proposal_row = self._required_entity_row(
                conn,
                table="entity_resolution_proposal_versions",
                column="proposal_version_id",
                identifier=str(request.expected_proposal_version_id),
                identity="resolution proposal version",
            )
            proposal = self._proposal_version_from_row(conn, proposal_row, replayed=False)
            if proposal.canonical_digest != request.expected_proposal_digest:
                raise EntityStaleDecision("resolution proposal digest differs")
            subject = self._mention_from_row(
                conn, self._mention_row(conn, proposal.subject_mention_id), replayed=False
            )
            self._require_mention_current(conn, subject)
            decision_head = self._decision_head_row(conn, request.proposal_id)
            if request.expected_decision_version == 0:
                if decision_head is not None:
                    raise EntityStaleDecision("initial decision already exists")
            else:
                if (
                    decision_head is None
                    or int(decision_head["current_decision_version"])
                    != request.expected_decision_version
                    or str(decision_head["current_decision_id"])
                    != str(request.expected_previous_decision_id)
                    or bool(decision_head["terminal"])
                ):
                    raise EntityStaleDecision("decision does not extend the current head")
            self._ensure_identifier_absent(
                conn,
                table="entity_resolution_decisions",
                column="decision_id",
                identifier=str(decision_id),
                identity="resolution decision identity",
            )

            if request.action is EntityResolutionDecisionAction.ACCEPT:
                assert request.accepted_entity_id is not None
                assert request.accepted_entity_version_id is not None
                assert request.alias_id is not None
                assert request.alias_kind is not None
                prior_subject = self._latest_mention_resolution(
                    conn, str(subject.mention_id)
                )
                if prior_subject is not None:
                    raise EntityDecisionConflict("subject mention is already admitted")
                if proposal.kind is EntityResolutionProposalKind.MENTION_TO_NEW_ENTITY:
                    self._ensure_identifier_absent(
                        conn,
                        table="canonical_entities",
                        column="entity_id",
                        identifier=str(request.accepted_entity_id),
                        identity="canonical entity identity",
                    )
                    self._ensure_identifier_absent(
                        conn,
                        table="canonical_entity_versions",
                        column="entity_version_id",
                        identifier=str(request.accepted_entity_version_id),
                        identity="canonical entity version identity",
                    )
                elif proposal.kind in {
                    EntityResolutionProposalKind.MENTION_TO_ENTITY,
                    EntityResolutionProposalKind.ALIAS_TO_ENTITY,
                }:
                    if (
                        proposal.candidate_entity_id != request.accepted_entity_id
                        or proposal.candidate_entity_version_id
                        != request.accepted_entity_version_id
                    ):
                        raise EntityDecisionConflict(
                            "accepted entity differs from proposal candidate"
                        )
                    self._require_candidate_current(
                        conn,
                        entity_id=request.accepted_entity_id,
                        version_id=request.accepted_entity_version_id,
                    )
                elif proposal.kind is EntityResolutionProposalKind.MENTION_EQUIVALENCE:
                    assert proposal.object_mention_id is not None
                    other = self._mention_from_row(
                        conn,
                        self._mention_row(conn, proposal.object_mention_id),
                        replayed=False,
                    )
                    self._require_mention_current(conn, other)
                    resolved = self._latest_mention_resolution(
                        conn, str(other.mention_id)
                    )
                    if resolved is None:
                        raise EntityDecisionConflict(
                            "equivalence acceptance requires an admitted object mention"
                        )
                    if (
                        str(resolved["entity_id"]) != str(request.accepted_entity_id)
                        or str(resolved["entity_version_id"])
                        != str(request.accepted_entity_version_id)
                    ):
                        raise EntityDecisionConflict(
                            "equivalence acceptance differs from object identity"
                        )
                    self._require_candidate_current(
                        conn,
                        entity_id=request.accepted_entity_id,
                        version_id=request.accepted_entity_version_id,
                    )
                self._ensure_identifier_absent(
                    conn,
                    table="entity_aliases",
                    column="alias_id",
                    identifier=str(request.alias_id),
                    identity="entity alias identity",
                )

            recorded_at = now.to_text()
            committed = self._commit_grant_in_transaction(
                conn, grant, recorded_at=recorded_at
            )
            if committed.replayed:
                row = self._row_for_event(
                    conn,
                    table="entity_resolution_decisions",
                    event_id=committed.event_id,
                    identity="entity resolution decision",
                )
                return self._decision_from_row(conn, row, replayed=True)

            result = EntityResolutionDecision(
                decision_id=decision_id,
                proposal_id=request.proposal_id,
                proposal_version_id=request.expected_proposal_version_id,
                proposal_digest=request.expected_proposal_digest,
                action=request.action,
                decision_version=request.expected_decision_version + 1,
                previous_decision_id=request.expected_previous_decision_id,
                accepted_entity_id=request.accepted_entity_id,
                accepted_entity_version_id=request.accepted_entity_version_id,
                alias_id=request.alias_id,
                reason_code=request.reason_code,
                decision_policy_version=request.decision_policy_version,
                authority_event_id=EventId.parse(committed.event_id),
                authority_ledger_seq=committed.ledger_seq,
                recorded_at=UtcTimestamp.parse(recorded_at),
                replayed=False,
            )
            data = canonical_json_bytes(result.canonical_value())
            conn.execute(
                "INSERT INTO entity_resolution_decisions("
                "decision_id,resolution_proposal_id,proposal_version_id,"
                "proposal_digest,action,decision_version,previous_decision_id,"
                "accepted_entity_id,accepted_entity_version_id,alias_id,reason_code,"
                "decision_policy_version,authority_event_id,authority_aggregate_version,"
                "canonical_bytes,canonical_digest,recorded_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(result.decision_id),
                    str(result.proposal_id),
                    str(result.proposal_version_id),
                    result.proposal_digest,
                    result.action.value,
                    result.decision_version,
                    (
                        None
                        if result.previous_decision_id is None
                        else str(result.previous_decision_id)
                    ),
                    (
                        None
                        if result.accepted_entity_id is None
                        else str(result.accepted_entity_id)
                    ),
                    (
                        None
                        if result.accepted_entity_version_id is None
                        else str(result.accepted_entity_version_id)
                    ),
                    None if result.alias_id is None else str(result.alias_id),
                    result.reason_code,
                    result.decision_policy_version,
                    committed.event_id,
                    committed.aggregate_version,
                    data,
                    digest_bytes(data),
                    recorded_at,
                ),
            )
            # Schema-v14 triggers create or advance the checked decision-head
            # projection from the immutable decision insert. Keeping the head
            # trigger-owned avoids a second mutable authority path.

            if result.action is EntityResolutionDecisionAction.ACCEPT:
                assert result.accepted_entity_id is not None
                assert result.accepted_entity_version_id is not None
                assert result.alias_id is not None
                assert request.alias_kind is not None
                if proposal.kind is EntityResolutionProposalKind.MENTION_TO_NEW_ENTITY:
                    entity = CanonicalEntity(
                        entity_id=result.accepted_entity_id,
                        entity_kind=subject.entity_kind,
                        created_by_decision_id=result.decision_id,
                        initial_version_id=result.accepted_entity_version_id,
                        authority_event_id=result.authority_event_id,
                        authority_ledger_seq=result.authority_ledger_seq,
                        created_at=result.recorded_at,
                    )
                    entity_data = canonical_json_bytes(entity.canonical_value())
                    conn.execute(
                        "INSERT INTO canonical_entities("
                        "entity_id,entity_kind,created_by_decision_id,initial_version_id,"
                        "authority_event_id,authority_aggregate_version,canonical_bytes,"
                        "canonical_digest,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            str(entity.entity_id),
                            entity.entity_kind.value,
                            str(entity.created_by_decision_id),
                            str(entity.initial_version_id),
                            committed.event_id,
                            committed.aggregate_version,
                            entity_data,
                            digest_bytes(entity_data),
                            recorded_at,
                        ),
                    )
                    version = CanonicalEntityVersion(
                        entity_version_id=result.accepted_entity_version_id,
                        entity_id=result.accepted_entity_id,
                        version_number=1,
                        previous_entity_version_id=None,
                        entity_kind=subject.entity_kind,
                        lifecycle=CanonicalEntityLifecycle.ACTIVE,
                        lineage_decision_kind=None,
                        lineage_decision_id=None,
                        preferred_continuation_entity_id=result.accepted_entity_id,
                        authority_event_id=result.authority_event_id,
                        authority_ledger_seq=result.authority_ledger_seq,
                        recorded_at=result.recorded_at,
                    )
                    version_data = canonical_json_bytes(version.canonical_value())
                    conn.execute(
                        "INSERT INTO canonical_entity_versions("
                        "entity_version_id,entity_id,version_number,"
                        "previous_entity_version_id,entity_kind,lifecycle,"
                        "lineage_decision_kind,lineage_decision_id,"
                        "preferred_continuation_entity_id,authority_event_id,"
                        "authority_aggregate_version,canonical_bytes,canonical_digest,"
                        "recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            str(version.entity_version_id),
                            str(version.entity_id),
                            version.version_number,
                            None,
                            version.entity_kind.value,
                            version.lifecycle.value,
                            None,
                            None,
                            str(version.preferred_continuation_entity_id),
                            committed.event_id,
                            committed.aggregate_version,
                            version_data,
                            digest_bytes(version_data),
                            recorded_at,
                        ),
                    )
                alias = EntityAlias(
                    alias_id=result.alias_id,
                    entity_id=result.accepted_entity_id,
                    entity_version_id=result.accepted_entity_version_id,
                    alias_text=subject.mention_text,
                    normalized_text=subject.normalized_text,
                    normalization_contract_digest=subject.normalization_contract_digest,
                    language=subject.language,
                    script=subject.script,
                    alias_kind=request.alias_kind,
                    valid_from=None,
                    valid_until=None,
                    provenance_mention_id=subject.mention_id,
                    resolution_decision_id=result.decision_id,
                    uncertainty_codes=proposal.uncertainty_codes,
                    authority_event_id=result.authority_event_id,
                    authority_ledger_seq=result.authority_ledger_seq,
                    recorded_at=result.recorded_at,
                )
                alias_semantic = digest_canonical(
                    {
                        "entity_id": str(alias.entity_id),
                        "normalized_text": alias.normalized_text,
                        "normalization_contract_digest": alias.normalization_contract_digest,
                        "language": alias.language,
                        "script": alias.script.value,
                        "alias_kind": alias.alias_kind.value,
                    }
                )
                self._ensure_semantic_absent(
                    conn,
                    table="entity_aliases",
                    column="semantic_digest",
                    digest=alias_semantic,
                    identity="entity alias semantics",
                )
                alias_data = canonical_json_bytes(alias.canonical_value())
                conn.execute(
                    "INSERT INTO entity_aliases("
                    "alias_id,entity_id,entity_version_id,alias_text,normalized_text,"
                    "normalization_contract_digest,language,script,alias_kind,valid_from,"
                    "valid_until,provenance_mention_id,resolution_decision_id,"
                    "uncertainty_codes_bytes,semantic_digest,authority_event_id,"
                    "authority_aggregate_version,canonical_bytes,canonical_digest,"
                    "recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        str(alias.alias_id),
                        str(alias.entity_id),
                        str(alias.entity_version_id),
                        alias.alias_text,
                        alias.normalized_text,
                        alias.normalization_contract_digest,
                        alias.language,
                        alias.script.value,
                        alias.alias_kind.value,
                        None,
                        None,
                        str(alias.provenance_mention_id),
                        str(alias.resolution_decision_id),
                        self._json_bytes(alias.uncertainty_codes),
                        alias_semantic,
                        committed.event_id,
                        committed.aggregate_version,
                        alias_data,
                        digest_bytes(alias_data),
                        recorded_at,
                    ),
                )
                resolution_value = {
                    "mention_id": str(subject.mention_id),
                    "decision_id": str(result.decision_id),
                    "resolution_proposal_id": str(result.proposal_id),
                    "entity_id": str(result.accepted_entity_id),
                    "entity_version_id": str(result.accepted_entity_version_id),
                    "alias_id": str(result.alias_id),
                    "admitted_at": recorded_at,
                }
                resolution_bytes = canonical_json_bytes(resolution_value)
                conn.execute(
                    "INSERT INTO entity_mention_resolutions("
                    "mention_id,decision_id,resolution_proposal_id,entity_id,"
                    "entity_version_id,alias_id,admitted_at,canonical_bytes,"
                    "canonical_digest) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        str(subject.mention_id),
                        str(result.decision_id),
                        str(result.proposal_id),
                        str(result.accepted_entity_id),
                        str(result.accepted_entity_version_id),
                        str(result.alias_id),
                        recorded_at,
                        resolution_bytes,
                        digest_bytes(resolution_bytes),
                    ),
                )
                preferred_row = conn.execute(
                    "SELECT * FROM canonical_entity_heads WHERE entity_id=?",
                    (str(result.accepted_entity_id),),
                ).fetchone()
                if preferred_row is None:
                    raise AuthorityPersistenceError("accepted entity head is missing")
                existing_preferred = conn.execute(
                    "SELECT 1 FROM entity_preferred_identities WHERE entity_id=?",
                    (str(result.accepted_entity_id),),
                ).fetchone()
                if existing_preferred is None:
                    conn.execute(
                        "INSERT INTO entity_preferred_identities("
                        "entity_id,current_entity_version_id,preferred_entity_id,"
                        "lifecycle,decided_by_kind,decided_by_id,"
                        "projected_through_ledger_seq,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                        (
                            str(result.accepted_entity_id),
                            str(preferred_row["current_entity_version_id"]),
                            str(result.accepted_entity_id),
                            str(preferred_row["lifecycle"]),
                            None,
                            None,
                            committed.ledger_seq,
                            recorded_at,
                        ),
                    )
                else:
                    conn.execute(
                        "UPDATE entity_preferred_identities SET "
                        "current_entity_version_id=?,preferred_entity_id=?,lifecycle=?,"
                        "decided_by_kind=NULL,decided_by_id=NULL,"
                        "projected_through_ledger_seq=?,updated_at=? WHERE entity_id=?",
                        (
                            str(preferred_row["current_entity_version_id"]),
                            str(result.accepted_entity_id),
                            str(preferred_row["lifecycle"]),
                            committed.ledger_seq,
                            recorded_at,
                            str(result.accepted_entity_id),
                        ),
                    )
                projection_id = str(EventId.new())
                projection_value = {
                    "projection_event_id": projection_id,
                    "source_event_id": committed.event_id,
                    "source_ledger_seq": committed.ledger_seq,
                    "action": "UPSERT",
                    "entity_id": str(result.accepted_entity_id),
                    "entity_version_id": str(preferred_row["current_entity_version_id"]),
                    "preferred_entity_id": str(result.accepted_entity_id),
                    "lifecycle": str(preferred_row["lifecycle"]),
                }
                projection_bytes = canonical_json_bytes(projection_value)
                conn.execute(
                    "INSERT INTO entity_projection_events("
                    "projection_event_id,source_event_id,source_ledger_seq,action,"
                    "entity_id,entity_version_id,preferred_entity_id,lifecycle,"
                    "canonical_bytes,canonical_digest,recorded_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        projection_id,
                        committed.event_id,
                        committed.ledger_seq,
                        "UPSERT",
                        str(result.accepted_entity_id),
                        str(preferred_row["current_entity_version_id"]),
                        str(result.accepted_entity_id),
                        str(preferred_row["lifecycle"]),
                        projection_bytes,
                        digest_bytes(projection_bytes),
                        recorded_at,
                    ),
                )

            row = self._row_for_event(
                conn,
                table="entity_resolution_decisions",
                event_id=committed.event_id,
                identity="entity resolution decision",
            )
            return self._decision_from_row(conn, row, replayed=False)


__all__ = ["_EntityCommitMixin"]
