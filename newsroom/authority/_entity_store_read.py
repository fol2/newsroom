from __future__ import annotations

import sqlite3

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.persistence import AuthorityPersistenceError
from newsroom.authority.types import EventId, UtcTimestamp
from newsroom.entities.models import (
    CanonicalEntity,
    CanonicalEntityVersion,
    EntityAdmissionGuard,
    EntityAlias,
    EntityMention,
    EntityPreferredIdentity,
    EntityResolutionDecision,
    EntityResolutionProposalVersion,
)
from newsroom.entities.policy import (
    ENTITY_MENTION_ADMIT_COMMAND,
    ENTITY_RESOLUTION_DECIDE_COMMAND,
    ENTITY_RESOLUTION_PROPOSE_COMMAND,
)
from newsroom.entities.types import (
    CanonicalEntityId,
    CanonicalEntityLifecycle,
    CanonicalEntityVersionId,
    EntityAliasId,
    EntityAliasKind,
    EntityKind,
    EntityLineageDecisionKind,
    EntityMentionId,
    EntityResolutionDecisionAction,
    EntityResolutionDecisionId,
    EntityResolutionProposalId,
    EntityResolutionProposalKind,
    EntityResolutionProposalVersionId,
    EntityResolutionState,
    EntityScript,
)
from newsroom.extraction.types import (
    ExtractionOutputId,
    ExtractionPassageId,
    ExtractionRunId,
    ExtractionRunVersionId,
    ProposalEnvelopeId,
    ProposalSetId,
)
from newsroom.sources.types import (
    DiscoveryRepresentationId,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceItemId,
    SourceRevisionId,
)

from ._entity_decoding import (
    decode_entity_decision_request,
    decode_entity_mention_request,
    decode_entity_proposal_request,
)
from ._entity_store_common import deterministic_decision_id


class _EntityReadMixin:
    @staticmethod
    def _required_entity_row(
        conn: sqlite3.Connection,
        *,
        table: str,
        column: str,
        identifier: str,
        identity: str,
    ) -> sqlite3.Row:
        row = conn.execute(
            f"SELECT * FROM {table} WHERE {column}=?", (identifier,)
        ).fetchone()
        if row is None:
            raise KeyError(f"{identity} is not retained")
        return row

    def _mention_from_row(
        self, conn: sqlite3.Connection, row: sqlite3.Row, *, replayed: bool
    ) -> EntityMention:
        event = self._record_context(conn, event_id=str(row["authority_event_id"]))
        payload = bytes(event["payload_bytes"])
        request_value = self._decode_json_blob(payload, identity="entity mention request")
        request = decode_entity_mention_request(
            request_value, idempotency_key=str(event["idempotency_key"])
        )
        self._validate_entity_record_envelope(
            conn,
            row,
            command_type=ENTITY_MENTION_ADMIT_COMMAND,
            aggregate_id=str(request.mention_id),
            payload_bytes=payload,
            payload_digest=request.digest,
        )
        uncertainties = self._decode_json_blob(
            bytes(row["uncertainty_codes_bytes"]), identity="mention uncertainty codes"
        )
        rationales = self._decode_json_blob(
            bytes(row["rationale_codes_bytes"]), identity="mention rationale codes"
        )
        if not isinstance(uncertainties, list) or not isinstance(rationales, list):
            raise AuthorityPersistenceError("mention code lists are invalid")
        result = EntityMention(
            mention_id=EntityMentionId.parse(str(row["mention_id"])),
            source_proposal_id=ProposalEnvelopeId.parse(str(row["source_proposal_id"])),
            proposal_set_id=ProposalSetId.parse(str(row["proposal_set_id"])),
            output_id=ExtractionOutputId.parse(str(row["output_id"])),
            run_id=ExtractionRunId.parse(str(row["run_id"])),
            run_version_id=ExtractionRunVersionId.parse(str(row["run_version_id"])),
            definition_id=SourceDefinitionId.parse(str(row["definition_id"])),
            definition_version_id=SourceDefinitionVersionId.parse(
                str(row["definition_version_id"])
            ),
            item_id=SourceItemId.parse(str(row["item_id"])),
            revision_id=SourceRevisionId.parse(str(row["revision_id"])),
            representation_id=DiscoveryRepresentationId.parse(
                str(row["representation_id"])
            ),
            passage_id=ExtractionPassageId.parse(str(row["passage_id"])),
            start_byte=int(row["start_byte"]),
            end_byte=int(row["end_byte"]),
            evidence_text_digest=str(row["evidence_text_digest"]),
            mention_text=str(row["mention_text"]),
            normalized_text=str(row["normalized_text"]),
            normalization_contract_digest=str(row["normalization_contract_digest"]),
            language=str(row["language"]),
            script=EntityScript(str(row["script"])),
            entity_kind=EntityKind(str(row["entity_kind"])),
            confidence_basis_points=(
                None
                if row["confidence_basis_points"] is None
                else int(row["confidence_basis_points"])
            ),
            uncertainty_codes=tuple(str(value) for value in uncertainties),
            rationale_codes=tuple(str(value) for value in rationales),
            source_proposal_digest=str(row["source_proposal_digest"]),
            authority_event_id=EventId.parse(str(row["authority_event_id"])),
            authority_ledger_seq=int(event["ledger_seq"]),
            recorded_at=UtcTimestamp.parse(str(row["recorded_at"])),
            replayed=replayed,
        )
        data = canonical_json_bytes(result.canonical_value())
        if (
            request.mention_id != result.mention_id
            or request.source_proposal_id != result.source_proposal_id
            or request.expected_source_proposal_digest != result.source_proposal_digest
            or request.entity_kind is not result.entity_kind
            or request.language != result.language
            or request.script is not result.script
            or request.normalized_text != result.normalized_text
            or request.normalization_contract_digest
            != result.normalization_contract_digest
            or result.semantic_digest != str(row["semantic_digest"])
            or data != bytes(row["canonical_bytes"])
            or digest_bytes(data) != str(row["canonical_digest"])
        ):
            raise AuthorityPersistenceError("entity mention normalized columns differ")
        return result

    def _proposal_version_from_row(
        self, conn: sqlite3.Connection, row: sqlite3.Row, *, replayed: bool
    ) -> EntityResolutionProposalVersion:
        request_bytes = bytes(row["request_bytes"])
        if digest_bytes(request_bytes) != str(row["request_digest"]):
            raise AuthorityPersistenceError("resolution proposal request digest mismatch")
        event = self._record_context(conn, event_id=str(row["authority_event_id"]))
        request_value = self._decode_json_blob(
            request_bytes, identity="resolution proposal request"
        )
        request = decode_entity_proposal_request(
            request_value, idempotency_key=str(event["idempotency_key"])
        )
        self._validate_entity_record_envelope(
            conn,
            row,
            command_type=ENTITY_RESOLUTION_PROPOSE_COMMAND,
            aggregate_id=str(request.proposal_version_id),
            payload_bytes=request_bytes,
            payload_digest=request.digest,
        )
        base = conn.execute(
            "SELECT * FROM entity_resolution_proposals "
            "WHERE resolution_proposal_id=?",
            (str(row["resolution_proposal_id"]),),
        ).fetchone()
        if base is None:
            raise AuthorityPersistenceError("resolution proposal base is missing")
        uncertainties = self._decode_json_blob(
            bytes(row["uncertainty_codes_bytes"]), identity="resolution uncertainty codes"
        )
        basis = self._decode_json_blob(
            bytes(row["basis_codes_bytes"]), identity="resolution basis codes"
        )
        if not isinstance(uncertainties, list) or not isinstance(basis, list):
            raise AuthorityPersistenceError("resolution proposal code lists are invalid")
        result = EntityResolutionProposalVersion(
            proposal_id=EntityResolutionProposalId.parse(
                str(row["resolution_proposal_id"])
            ),
            proposal_version_id=EntityResolutionProposalVersionId.parse(
                str(row["proposal_version_id"])
            ),
            version_number=int(row["version_number"]),
            previous_proposal_version_id=(
                None
                if row["previous_proposal_version_id"] is None
                else EntityResolutionProposalVersionId.parse(
                    str(row["previous_proposal_version_id"])
                )
            ),
            source_proposal_id=ProposalEnvelopeId.parse(
                str(base["source_proposal_id"])
            ),
            source_proposal_digest=str(row["source_proposal_digest"]),
            kind=EntityResolutionProposalKind(str(base["proposal_kind"])),
            subject_mention_id=EntityMentionId.parse(str(base["subject_mention_id"])),
            object_mention_id=(
                None
                if base["object_mention_id"] is None
                else EntityMentionId.parse(str(base["object_mention_id"]))
            ),
            candidate_entity_id=(
                None
                if base["candidate_entity_id"] is None
                else CanonicalEntityId.parse(str(base["candidate_entity_id"]))
            ),
            candidate_entity_version_id=(
                None
                if base["candidate_entity_version_id"] is None
                else CanonicalEntityVersionId.parse(
                    str(base["candidate_entity_version_id"])
                )
            ),
            confidence_basis_points=(
                None
                if row["confidence_basis_points"] is None
                else int(row["confidence_basis_points"])
            ),
            uncertainty_codes=tuple(str(value) for value in uncertainties),
            basis_codes=tuple(str(value) for value in basis),
            stable_semantic_digest=str(base["stable_semantic_digest"]),
            authority_event_id=EventId.parse(str(row["authority_event_id"])),
            authority_ledger_seq=int(event["ledger_seq"]),
            recorded_at=UtcTimestamp.parse(str(row["recorded_at"])),
            replayed=replayed,
        )
        data = canonical_json_bytes(result.canonical_value())
        base_value = {
            "proposal_id": str(result.proposal_id),
            "source_proposal_id": str(result.source_proposal_id),
            "kind": result.kind.value,
            "subject_mention_id": str(result.subject_mention_id),
            "object_mention_id": (
                None if result.object_mention_id is None else str(result.object_mention_id)
            ),
            "candidate_entity_id": (
                None
                if result.candidate_entity_id is None
                else str(result.candidate_entity_id)
            ),
            "candidate_entity_version_id": (
                None
                if result.candidate_entity_version_id is None
                else str(result.candidate_entity_version_id)
            ),
            "stable_semantic_digest": result.stable_semantic_digest,
        }
        base_bytes = canonical_json_bytes(base_value)
        if (
            request.proposal_id != result.proposal_id
            or request.proposal_version_id != result.proposal_version_id
            or request.version_number != result.version_number
            or request.expected_previous_version_id
            != result.previous_proposal_version_id
            or request.source_proposal_id != result.source_proposal_id
            or request.expected_source_proposal_digest != result.source_proposal_digest
            or request.kind is not result.kind
            or request.subject_mention_id != result.subject_mention_id
            or request.object_mention_id != result.object_mention_id
            or request.candidate_entity_id != result.candidate_entity_id
            or request.candidate_entity_version_id
            != result.candidate_entity_version_id
            or request.confidence_basis_points != result.confidence_basis_points
            or request.uncertainty_codes != result.uncertainty_codes
            or request.basis_codes != result.basis_codes
            or request.stable_semantic_digest != result.stable_semantic_digest
            or data != bytes(row["canonical_bytes"])
            or digest_bytes(data) != str(row["canonical_digest"])
            or base_bytes != bytes(base["canonical_bytes"])
            or digest_bytes(base_bytes) != str(base["canonical_digest"])
            or str(base["created_by_event_id"])
            != str(
                conn.execute(
                    "SELECT authority_event_id FROM entity_resolution_proposal_versions "
                    "WHERE resolution_proposal_id=? AND version_number=1",
                    (str(result.proposal_id),),
                ).fetchone()[0]
            )
        ):
            raise AuthorityPersistenceError(
                "entity resolution proposal normalized columns differ"
            )
        return result

    def _decision_from_row(
        self, conn: sqlite3.Connection, row: sqlite3.Row, *, replayed: bool
    ) -> EntityResolutionDecision:
        event = self._record_context(conn, event_id=str(row["authority_event_id"]))
        request_bytes = bytes(event["payload_bytes"])
        request_value = self._decode_json_blob(
            request_bytes, identity="resolution decision request"
        )
        request = decode_entity_decision_request(
            request_value, idempotency_key=str(event["idempotency_key"])
        )
        decision_id = deterministic_decision_id(request)
        self._validate_entity_record_envelope(
            conn,
            row,
            command_type=ENTITY_RESOLUTION_DECIDE_COMMAND,
            aggregate_id=str(decision_id),
            payload_bytes=request_bytes,
            payload_digest=request.digest,
        )
        result = EntityResolutionDecision(
            decision_id=EntityResolutionDecisionId.parse(str(row["decision_id"])),
            proposal_id=EntityResolutionProposalId.parse(
                str(row["resolution_proposal_id"])
            ),
            proposal_version_id=EntityResolutionProposalVersionId.parse(
                str(row["proposal_version_id"])
            ),
            proposal_digest=str(row["proposal_digest"]),
            action=EntityResolutionDecisionAction(str(row["action"])),
            decision_version=int(row["decision_version"]),
            previous_decision_id=(
                None
                if row["previous_decision_id"] is None
                else EntityResolutionDecisionId.parse(str(row["previous_decision_id"]))
            ),
            accepted_entity_id=(
                None
                if row["accepted_entity_id"] is None
                else CanonicalEntityId.parse(str(row["accepted_entity_id"]))
            ),
            accepted_entity_version_id=(
                None
                if row["accepted_entity_version_id"] is None
                else CanonicalEntityVersionId.parse(
                    str(row["accepted_entity_version_id"])
                )
            ),
            alias_id=(
                None
                if row["alias_id"] is None
                else EntityAliasId.parse(str(row["alias_id"]))
            ),
            reason_code=str(row["reason_code"]),
            decision_policy_version=str(row["decision_policy_version"]),
            authority_event_id=EventId.parse(str(row["authority_event_id"])),
            authority_ledger_seq=int(event["ledger_seq"]),
            recorded_at=UtcTimestamp.parse(str(row["recorded_at"])),
            replayed=replayed,
        )
        data = canonical_json_bytes(result.canonical_value())
        if (
            decision_id != result.decision_id
            or request.proposal_id != result.proposal_id
            or request.expected_proposal_version_id != result.proposal_version_id
            or request.expected_proposal_digest != result.proposal_digest
            or request.action is not result.action
            or request.expected_decision_version + 1 != result.decision_version
            or request.expected_previous_decision_id != result.previous_decision_id
            or request.accepted_entity_id != result.accepted_entity_id
            or request.accepted_entity_version_id
            != result.accepted_entity_version_id
            or request.alias_id != result.alias_id
            or request.reason_code != result.reason_code
            or request.decision_policy_version != result.decision_policy_version
            or data != bytes(row["canonical_bytes"])
            or digest_bytes(data) != str(row["canonical_digest"])
        ):
            raise AuthorityPersistenceError("resolution decision normalized columns differ")
        return result

    def _entity_from_row(self, conn: sqlite3.Connection, row: sqlite3.Row) -> CanonicalEntity:
        event = self._record_context(conn, event_id=str(row["authority_event_id"]))
        result = CanonicalEntity(
            entity_id=CanonicalEntityId.parse(str(row["entity_id"])),
            entity_kind=EntityKind(str(row["entity_kind"])),
            created_by_decision_id=EntityResolutionDecisionId.parse(
                str(row["created_by_decision_id"])
            ),
            initial_version_id=CanonicalEntityVersionId.parse(
                str(row["initial_version_id"])
            ),
            authority_event_id=EventId.parse(str(row["authority_event_id"])),
            authority_ledger_seq=int(event["ledger_seq"]),
            created_at=UtcTimestamp.parse(str(row["created_at"])),
        )
        data = canonical_json_bytes(result.canonical_value())
        if data != bytes(row["canonical_bytes"]) or digest_bytes(data) != str(
            row["canonical_digest"]
        ):
            raise AuthorityPersistenceError("canonical entity normalized columns differ")
        return result

    def _entity_version_from_row(
        self, conn: sqlite3.Connection, row: sqlite3.Row
    ) -> CanonicalEntityVersion:
        event = self._record_context(conn, event_id=str(row["authority_event_id"]))
        result = CanonicalEntityVersion(
            entity_version_id=CanonicalEntityVersionId.parse(
                str(row["entity_version_id"])
            ),
            entity_id=CanonicalEntityId.parse(str(row["entity_id"])),
            version_number=int(row["version_number"]),
            previous_entity_version_id=(
                None
                if row["previous_entity_version_id"] is None
                else CanonicalEntityVersionId.parse(
                    str(row["previous_entity_version_id"])
                )
            ),
            entity_kind=EntityKind(str(row["entity_kind"])),
            lifecycle=CanonicalEntityLifecycle(str(row["lifecycle"])),
            lineage_decision_kind=(
                None
                if row["lineage_decision_kind"] is None
                else EntityLineageDecisionKind(str(row["lineage_decision_kind"]))
            ),
            lineage_decision_id=(
                None
                if row["lineage_decision_id"] is None
                else str(row["lineage_decision_id"])
            ),
            preferred_continuation_entity_id=(
                None
                if row["preferred_continuation_entity_id"] is None
                else CanonicalEntityId.parse(
                    str(row["preferred_continuation_entity_id"])
                )
            ),
            authority_event_id=EventId.parse(str(row["authority_event_id"])),
            authority_ledger_seq=int(event["ledger_seq"]),
            recorded_at=UtcTimestamp.parse(str(row["recorded_at"])),
        )
        data = canonical_json_bytes(result.canonical_value())
        if data != bytes(row["canonical_bytes"]) or digest_bytes(data) != str(
            row["canonical_digest"]
        ):
            raise AuthorityPersistenceError("canonical entity version normalized columns differ")
        return result

    def _alias_from_row(self, conn: sqlite3.Connection, row: sqlite3.Row) -> EntityAlias:
        event = self._record_context(conn, event_id=str(row["authority_event_id"]))
        uncertainty = self._decode_json_blob(
            bytes(row["uncertainty_codes_bytes"]), identity="entity alias uncertainty codes"
        )
        if not isinstance(uncertainty, list):
            raise AuthorityPersistenceError("entity alias uncertainty codes are invalid")
        result = EntityAlias(
            alias_id=EntityAliasId.parse(str(row["alias_id"])),
            entity_id=CanonicalEntityId.parse(str(row["entity_id"])),
            entity_version_id=CanonicalEntityVersionId.parse(
                str(row["entity_version_id"])
            ),
            alias_text=str(row["alias_text"]),
            normalized_text=str(row["normalized_text"]),
            normalization_contract_digest=str(row["normalization_contract_digest"]),
            language=str(row["language"]),
            script=EntityScript(str(row["script"])),
            alias_kind=EntityAliasKind(str(row["alias_kind"])),
            valid_from=(
                None if row["valid_from"] is None else UtcTimestamp.parse(str(row["valid_from"]))
            ),
            valid_until=(
                None if row["valid_until"] is None else UtcTimestamp.parse(str(row["valid_until"]))
            ),
            provenance_mention_id=EntityMentionId.parse(
                str(row["provenance_mention_id"])
            ),
            resolution_decision_id=EntityResolutionDecisionId.parse(
                str(row["resolution_decision_id"])
            ),
            uncertainty_codes=tuple(str(value) for value in uncertainty),
            authority_event_id=EventId.parse(str(row["authority_event_id"])),
            authority_ledger_seq=int(event["ledger_seq"]),
            recorded_at=UtcTimestamp.parse(str(row["recorded_at"])),
        )
        data = canonical_json_bytes(result.canonical_value())
        semantic = digest_bytes(
            canonical_json_bytes(
                {
                    "entity_id": str(result.entity_id),
                    "normalized_text": result.normalized_text,
                    "normalization_contract_digest": result.normalization_contract_digest,
                    "language": result.language,
                    "script": result.script.value,
                    "alias_kind": result.alias_kind.value,
                }
            )
        )
        if (
            data != bytes(row["canonical_bytes"])
            or digest_bytes(data) != str(row["canonical_digest"])
            or semantic != str(row["semantic_digest"])
        ):
            raise AuthorityPersistenceError("entity alias normalized columns differ")
        return result

    def mention(self, mention_id: EntityMentionId) -> EntityMention:
        if not isinstance(mention_id, EntityMentionId):
            raise TypeError("entity mention identity must be typed")
        with self._lock:
            row = self._required_entity_row(
                self._connection,
                table="entity_mentions",
                column="mention_id",
                identifier=str(mention_id),
                identity="entity mention",
            )
            result = self._mention_from_row(self._connection, row, replayed=False)
            self._require_mention_current(self._connection, result)
            return result

    def proposal_version(
        self, proposal_version_id: EntityResolutionProposalVersionId
    ) -> EntityResolutionProposalVersion:
        if not isinstance(proposal_version_id, EntityResolutionProposalVersionId):
            raise TypeError("resolution proposal version identity must be typed")
        with self._lock:
            row = self._required_entity_row(
                self._connection,
                table="entity_resolution_proposal_versions",
                column="proposal_version_id",
                identifier=str(proposal_version_id),
                identity="entity resolution proposal version",
            )
            result = self._proposal_version_from_row(
                self._connection, row, replayed=False
            )
            subject = self._mention_from_row(
                self._connection,
                self._mention_row(self._connection, result.subject_mention_id),
                replayed=False,
            )
            self._require_mention_current(self._connection, subject)
            if result.object_mention_id is not None:
                other = self._mention_from_row(
                    self._connection,
                    self._mention_row(self._connection, result.object_mention_id),
                    replayed=False,
                )
                self._require_mention_current(self._connection, other)
            if result.candidate_entity_id is not None:
                assert result.candidate_entity_version_id is not None
                self._require_candidate_current(
                    self._connection,
                    entity_id=result.candidate_entity_id,
                    version_id=result.candidate_entity_version_id,
                )
            return result

    def proposal_current(
        self, proposal_id: EntityResolutionProposalId
    ) -> EntityResolutionProposalVersion:
        if not isinstance(proposal_id, EntityResolutionProposalId):
            raise TypeError("resolution proposal identity must be typed")
        with self._lock:
            head = self._proposal_head_row(self._connection, proposal_id)
            if head is None:
                raise KeyError("entity resolution proposal is not retained")
            return self.proposal_version(
                EntityResolutionProposalVersionId.parse(
                    str(head["current_proposal_version_id"])
                )
            )

    def decision_current(
        self, proposal_id: EntityResolutionProposalId
    ) -> EntityResolutionDecision | None:
        if not isinstance(proposal_id, EntityResolutionProposalId):
            raise TypeError("resolution proposal identity must be typed")
        with self._lock:
            head = self._decision_head_row(self._connection, proposal_id)
            if head is None:
                return None
            row = self._required_entity_row(
                self._connection,
                table="entity_resolution_decisions",
                column="decision_id",
                identifier=str(head["current_decision_id"]),
                identity="entity resolution decision",
            )
            result = self._decision_from_row(self._connection, row, replayed=False)
            self.proposal_version(result.proposal_version_id)
            return result

    def entity(self, entity_id: CanonicalEntityId) -> CanonicalEntity:
        if not isinstance(entity_id, CanonicalEntityId):
            raise TypeError("canonical entity identity must be typed")
        with self._lock:
            row = self._required_entity_row(
                self._connection,
                table="canonical_entities",
                column="entity_id",
                identifier=str(entity_id),
                identity="canonical entity",
            )
            result = self._entity_from_row(self._connection, row)
            aliases = self._connection.execute(
                "SELECT provenance_mention_id FROM entity_aliases WHERE entity_id=?",
                (str(entity_id),),
            ).fetchall()
            for alias in aliases:
                mention = self._mention_from_row(
                    self._connection,
                    self._mention_row(
                        self._connection,
                        EntityMentionId.parse(str(alias["provenance_mention_id"])),
                    ),
                    replayed=False,
                )
                self._require_mention_current(self._connection, mention)
            return result

    def entity_version(
        self, entity_version_id: CanonicalEntityVersionId
    ) -> CanonicalEntityVersion:
        if not isinstance(entity_version_id, CanonicalEntityVersionId):
            raise TypeError("canonical entity version identity must be typed")
        with self._lock:
            row = self._required_entity_row(
                self._connection,
                table="canonical_entity_versions",
                column="entity_version_id",
                identifier=str(entity_version_id),
                identity="canonical entity version",
            )
            result = self._entity_version_from_row(self._connection, row)
            self.entity(result.entity_id)
            return result

    def aliases(
        self, entity_id: CanonicalEntityId, *, limit: int
    ) -> tuple[EntityAlias, ...]:
        if not isinstance(entity_id, CanonicalEntityId):
            raise TypeError("canonical entity identity must be typed")
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM entity_aliases WHERE entity_id=? "
                "ORDER BY language,normalized_text,alias_id LIMIT ?",
                (str(entity_id), limit),
            ).fetchall()
            results = tuple(self._alias_from_row(self._connection, row) for row in rows)
            for result in results:
                mention = self._mention_from_row(
                    self._connection,
                    self._mention_row(self._connection, result.provenance_mention_id),
                    replayed=False,
                )
                self._require_mention_current(self._connection, mention)
            return results

    def preferred_identity(self, entity_id: CanonicalEntityId) -> EntityPreferredIdentity:
        if not isinstance(entity_id, CanonicalEntityId):
            raise TypeError("canonical entity identity must be typed")
        with self._lock:
            row = self._required_entity_row(
                self._connection,
                table="entity_preferred_identities",
                column="entity_id",
                identifier=str(entity_id),
                identity="entity preferred identity",
            )
            result = EntityPreferredIdentity(
                entity_id=CanonicalEntityId.parse(str(row["entity_id"])),
                current_entity_version_id=CanonicalEntityVersionId.parse(
                    str(row["current_entity_version_id"])
                ),
                preferred_entity_id=CanonicalEntityId.parse(
                    str(row["preferred_entity_id"])
                ),
                lifecycle=CanonicalEntityLifecycle(str(row["lifecycle"])),
                decided_by_kind=(
                    None
                    if row["decided_by_kind"] is None
                    else EntityLineageDecisionKind(str(row["decided_by_kind"]))
                ),
                decided_by_id=(
                    None if row["decided_by_id"] is None else str(row["decided_by_id"])
                ),
                projected_through_ledger_seq=int(row["projected_through_ledger_seq"]),
            )
            self.entity(result.entity_id)
            return result

    def admission_guard(
        self, proposal_id: EntityResolutionProposalId
    ) -> EntityAdmissionGuard:
        if not isinstance(proposal_id, EntityResolutionProposalId):
            raise TypeError("resolution proposal identity must be typed")
        with self._lock:
            row = self._connection.execute(
                "SELECT h.resolution_proposal_id,h.current_proposal_version_id,"
                "COALESCE(d.current_state,'PROPOSED') AS state,"
                "COALESCE((SELECT MAX(ledger_seq) FROM ledger_events),1) AS checked_seq "
                "FROM entity_resolution_proposal_heads h "
                "LEFT JOIN entity_resolution_decision_heads d "
                "ON d.resolution_proposal_id=h.resolution_proposal_id "
                "WHERE h.resolution_proposal_id=?",
                (str(proposal_id),),
            ).fetchone()
            if row is None:
                raise KeyError("entity resolution proposal is not retained")
            return EntityAdmissionGuard(
                proposal_id=EntityResolutionProposalId.parse(
                    str(row["resolution_proposal_id"])
                ),
                proposal_version_id=EntityResolutionProposalVersionId.parse(
                    str(row["current_proposal_version_id"])
                ),
                state=EntityResolutionState(str(row["state"])),
                materially_unresolved=str(row["state"])
                not in {"ACCEPTED", "REJECTED", "REVERSED"},
                checked_at_ledger_seq=int(row["checked_seq"]),
            )


__all__ = ["_EntityReadMixin"]
