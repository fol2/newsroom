from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from newsroom.authority._capability import _AuthorizedCommandGrant
from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
)
from newsroom.authority.persistence import AuthorityPersistenceError
from newsroom.authority.types import EventId, PayloadMode, TrustScope, UtcTimestamp
from newsroom.entities.types import (
    CanonicalEntityId,
    CanonicalEntityVersionId,
    EntityResolutionDependencyId,
    EntityRightsDenied,
    EntityStaleDecision,
    EntityStateError,
)
from newsroom.extraction.types import ExtractionRightsDenied
from newsroom.relations.editorial_models import (
    EDITORIAL_PREDICATE_REGISTRY_V1,
    CanonicalEntityRelationEndpoint,
    EditorialRelationEndpoint,
    EditorialRelationEvidence,
    EventHypothesisRelationEndpoint,
    ExtractionRelationEvidence,
    RelationAssertionRelationEndpoint,
    SourceRevisionRelationEndpoint,
    StoryCandidateRelationEndpoint,
    WorkflowRelationEvidence,
    endpoint_canonical_bytes,
    endpoint_canonical_value,
)
from newsroom.relations.editorial_policy import (
    EDITORIAL_RELATION_DECISION_COMMAND,
    EDITORIAL_RELATION_PROPOSAL_COMMAND,
)
from newsroom.relations.editorial_types import (
    EditorialRelationAssertionId,
    EditorialRelationAssertionLifecycle,
    EditorialRelationEndpointKind,
    EditorialRelationIdentifierReuse,
    EditorialRelationDecisionConflict,
    EditorialRelationProposalId,
    EditorialRelationProposalVersionId,
    EditorialRelationRightsDenied,
    EditorialRelationSemanticCollision,
    EditorialRelationStaleDecision,
    EditorialRelationStateError,
)


_RECORD_SPECS: dict[str, tuple[str, str, TrustScope]] = {
    EDITORIAL_RELATION_PROPOSAL_COMMAND: (
        "editorial_relation_proposal_version",
        "editorial.relation.proposed",
        TrustScope.PROPOSED,
    ),
    EDITORIAL_RELATION_DECISION_COMMAND: (
        "editorial_relation_decision",
        "editorial.relation.decided",
        TrustScope.ADMITTED,
    ),
}


def _deterministic_v4(identifier_type: type, domain: bytes, value: str):
    digest = hashlib.sha256(domain + b"\0" + value.encode("ascii")).digest()
    raw = bytearray(digest[:16])
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return identifier_type(UUID(bytes=bytes(raw)))


def deterministic_editorial_projection_event_id(
    *, source_event_id: EventId, assertion_id: EditorialRelationAssertionId
) -> EventId:
    return _deterministic_v4(
        EventId,
        b"newsroom.editorial-relation-projection-event.v1",
        f"{source_event_id}:{assertion_id}",
    )


def workflow_event_digest(row: Mapping[str, Any]) -> str:
    """Stable digest for exact retained workflow evidence.

    The digest deliberately binds the complete authority-facing event envelope,
    not local SQLite row order or transport metadata.
    """

    return digest_canonical(
        {
            "event_id": str(row["event_id"]),
            "event_type": str(row["event_type"]),
            "event_schema_version": int(row["event_schema_version"]),
            "aggregate_type": str(row["aggregate_type"]),
            "aggregate_id": str(row["aggregate_id"]),
            "aggregate_version": int(row["aggregate_version"]),
            "recorded_at": str(row["recorded_at"]),
            "command_definition_digest": str(row["command_definition_digest"]),
            "payload_digest": str(row["payload_digest"]),
            "principal_id": str(row["principal_id"]),
            "security_scope": str(row["security_scope"]),
            "retention_scope": str(row["retention_scope"]),
            "trust_scope": str(row["trust_scope"]),
        }
    )


class _EditorialRelationStoreSupport:
    def _require_editorial_relation_grant(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        command_type: str,
        aggregate_id: str,
        canonical_bytes: bytes,
    ) -> None:
        self._issuer.verify(grant)
        spec = _RECORD_SPECS.get(command_type)
        if spec is None:
            raise AuthorityPersistenceError("unknown editorial relation command")
        aggregate_type, event_type, trust_scope = spec
        definition = grant.definition
        if (
            grant.command_type != command_type
            or grant.aggregate_id != aggregate_id
            or grant.expected_aggregate_version != 0
            or definition.command_type != command_type
            or definition.aggregate_type != aggregate_type
            or definition.event_type != event_type
            or definition.trust_scope is not trust_scope
            or definition.security_scope != "authority.relation"
            or definition.retention_scope != "authority.audit"
            or definition.payload_mode is not PayloadMode.INLINE
            or grant.payload.kind != PayloadMode.INLINE.value
            or grant.payload.inline_bytes != canonical_bytes
            or grant.payload.digest != digest_bytes(canonical_bytes)
        ):
            raise AuthorityPersistenceError(
                "editorial relation grant differs from the typed record"
            )

    @staticmethod
    def _editorial_ensure_identifier_absent(
        conn: sqlite3.Connection,
        *,
        table: str,
        column: str,
        identifier: str,
        identity: str,
    ) -> None:
        if conn.execute(
            f"SELECT 1 FROM {table} WHERE {column}=?", (identifier,)
        ).fetchone() is not None:
            raise EditorialRelationIdentifierReuse(
                f"{identity} is already retained under different command identity"
            )

    @staticmethod
    def _editorial_ensure_semantic_absent(
        conn: sqlite3.Connection,
        *,
        table: str,
        column: str,
        digest: str,
        identity: str,
    ) -> None:
        if conn.execute(
            f"SELECT 1 FROM {table} WHERE {column}=?", (digest,)
        ).fetchone() is not None:
            raise EditorialRelationSemanticCollision(
                f"{identity} already exists under another stable identity"
            )

    @staticmethod
    def _editorial_decode_json_blob(
        value: bytes | memoryview, *, identity: str
    ) -> Any:
        data = bytes(value)
        try:
            decoded = json.loads(data.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise AuthorityPersistenceError(
                f"{identity} retained JSON is invalid"
            ) from exc
        if canonical_json_bytes(decoded) != data:
            raise AuthorityPersistenceError(
                f"{identity} retained JSON is not canonical"
            )
        return decoded

    @classmethod
    def _editorial_canonical_row_value(
        cls, row: Mapping[str, Any], *, identity: str
    ) -> dict[str, Any]:
        data = bytes(row["canonical_bytes"])
        if digest_bytes(data) != str(row["canonical_digest"]):
            raise AuthorityPersistenceError(f"{identity} canonical digest mismatch")
        value = cls._editorial_decode_json_blob(data, identity=identity)
        if not isinstance(value, dict):
            raise AuthorityPersistenceError(f"{identity} must be a canonical object")
        return value

    @staticmethod
    def _editorial_record_context(
        conn: sqlite3.Connection, *, event_id: str
    ) -> sqlite3.Row:
        row = conn.execute(
            "SELECT e.*,c.idempotency_key,p.payload_bytes "
            "FROM ledger_events e "
            "JOIN authority_commands c ON c.command_id=e.command_id "
            "JOIN authority_payloads p ON p.payload_id=e.payload_id "
            "WHERE e.event_id=?",
            (event_id,),
        ).fetchone()
        if row is None:
            raise AuthorityPersistenceError(
                "editorial relation record has no exact authority event"
            )
        return row

    @classmethod
    def _validate_editorial_relation_record_envelope(
        cls,
        conn: sqlite3.Connection,
        row: Mapping[str, Any],
        *,
        command_type: str,
        aggregate_id: str,
        payload_bytes: bytes,
        payload_digest: str,
    ) -> sqlite3.Row:
        event = cls._editorial_record_context(
            conn, event_id=str(row["authority_event_id"])
        )
        aggregate_type, event_type, trust_scope = _RECORD_SPECS[command_type]
        if (
            str(event["event_type"]) != event_type
            or int(event["event_schema_version"]) != 1
            or str(event["aggregate_type"]) != aggregate_type
            or str(event["aggregate_id"]) != aggregate_id
            or int(event["aggregate_version"])
            != int(row["authority_aggregate_version"])
            or int(row["authority_aggregate_version"]) != 1
            or str(event["recorded_at"]) != str(row["recorded_at"])
            or str(event["security_scope"]) != "authority.relation"
            or str(event["retention_scope"]) != "authority.audit"
            or str(event["trust_scope"]) != trust_scope.value
            or str(event["payload_mode"]) != PayloadMode.INLINE.value
            or str(event["payload_digest"]) != payload_digest
            or event["payload_bytes"] is None
            or bytes(event["payload_bytes"]) != payload_bytes
            or digest_bytes(payload_bytes) != payload_digest
        ):
            raise AuthorityPersistenceError(
                "editorial relation authority envelope is inconsistent"
            )
        return event

    @staticmethod
    def _editorial_row_for_event(
        conn: sqlite3.Connection,
        *,
        table: str,
        event_id: str,
        identity: str,
    ) -> sqlite3.Row:
        row = conn.execute(
            f"SELECT * FROM {table} WHERE authority_event_id=?", (event_id,)
        ).fetchone()
        if row is None:
            raise AuthorityPersistenceError(f"{identity} event record is missing")
        return row

    @staticmethod
    def _editorial_proposal_head_row(
        conn: sqlite3.Connection, proposal_id: EditorialRelationProposalId
    ) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM editorial_relation_proposal_heads WHERE proposal_id=?",
            (str(proposal_id),),
        ).fetchone()

    @staticmethod
    def _editorial_decision_head_row(
        conn: sqlite3.Connection, proposal_id: EditorialRelationProposalId
    ) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM editorial_relation_decision_heads WHERE proposal_id=?",
            (str(proposal_id),),
        ).fetchone()

    @staticmethod
    def _editorial_assertion_head_row(
        conn: sqlite3.Connection, assertion_id: EditorialRelationAssertionId
    ) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM editorial_relation_assertion_heads WHERE assertion_id=?",
            (str(assertion_id),),
        ).fetchone()

    @staticmethod
    def _editorial_endpoint_columns(
        endpoint: EditorialRelationEndpoint,
    ) -> tuple[object, ...]:
        values: dict[str, object | None] = {
            "entity_id": None,
            "entity_version_id": None,
            "source_item_id": None,
            "source_revision_id": None,
            "hypothesis_version_id": None,
            "candidate_id": None,
            "candidate_version_id": None,
            "assertion_id": None,
        }
        if isinstance(endpoint, CanonicalEntityRelationEndpoint):
            values["entity_id"] = str(endpoint.entity_id)
            values["entity_version_id"] = str(endpoint.entity_version_id)
        elif isinstance(endpoint, SourceRevisionRelationEndpoint):
            values["source_item_id"] = str(endpoint.source_item_id)
            values["source_revision_id"] = str(endpoint.source_revision_id)
        elif isinstance(endpoint, EventHypothesisRelationEndpoint):
            values["hypothesis_version_id"] = str(endpoint.hypothesis_version_id)
        elif isinstance(endpoint, StoryCandidateRelationEndpoint):
            values["candidate_id"] = str(endpoint.candidate_id)
            values["candidate_version_id"] = str(endpoint.candidate_version_id)
        elif isinstance(endpoint, RelationAssertionRelationEndpoint):
            values["assertion_id"] = str(endpoint.assertion_id)
        else:  # pragma: no cover - protected by the typed contract
            raise TypeError("unsupported editorial relation endpoint")
        return tuple(values[name] for name in values)

    def _retain_editorial_endpoint(
        self, conn: sqlite3.Connection, endpoint: EditorialRelationEndpoint
    ) -> str:
        data = endpoint_canonical_bytes(endpoint)
        digest = digest_bytes(data)
        existing = conn.execute(
            "SELECT * FROM editorial_relation_endpoints WHERE endpoint_digest=?",
            (digest,),
        ).fetchone()
        if existing is not None:
            decoded = self._editorial_endpoint_from_row(existing)
            if endpoint_canonical_bytes(decoded) != data:
                raise AuthorityPersistenceError(
                    "editorial endpoint digest collides with different semantics"
                )
            return digest
        columns = self._editorial_endpoint_columns(endpoint)
        conn.execute(
            "INSERT INTO editorial_relation_endpoints("
            "endpoint_digest,kind,entity_id,entity_version_id,source_item_id,"
            "source_revision_id,hypothesis_version_id,candidate_id,"
            "candidate_version_id,assertion_id,canonical_bytes,canonical_digest) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                digest,
                endpoint.kind.value,
                *columns,
                data,
                digest,
            ),
        )
        return digest

    @staticmethod
    def _editorial_endpoint_from_row(row: Mapping[str, Any]) -> EditorialRelationEndpoint:
        kind = EditorialRelationEndpointKind(str(row["kind"]))
        if kind is EditorialRelationEndpointKind.CANONICAL_ENTITY_VERSION:
            endpoint: EditorialRelationEndpoint = CanonicalEntityRelationEndpoint(
                entity_id=CanonicalEntityId.parse(str(row["entity_id"])),
                entity_version_id=CanonicalEntityVersionId.parse(
                    str(row["entity_version_id"])
                ),
            )
        elif kind is EditorialRelationEndpointKind.SOURCE_REVISION:
            from newsroom.sources.types import SourceItemId, SourceRevisionId

            endpoint = SourceRevisionRelationEndpoint(
                source_item_id=SourceItemId.parse(str(row["source_item_id"])),
                source_revision_id=SourceRevisionId.parse(
                    str(row["source_revision_id"])
                ),
            )
        elif kind is EditorialRelationEndpointKind.EVENT_HYPOTHESIS_VERSION:
            from newsroom.integrated.models import IntegratedHypothesisVersionId

            endpoint = EventHypothesisRelationEndpoint(
                hypothesis_version_id=IntegratedHypothesisVersionId.parse(
                    str(row["hypothesis_version_id"])
                )
            )
        elif kind is EditorialRelationEndpointKind.STORY_CANDIDATE_VERSION:
            from newsroom.integrated.models import StoryCandidateId, StoryCandidateVersionId

            endpoint = StoryCandidateRelationEndpoint(
                candidate_id=StoryCandidateId.parse(str(row["candidate_id"])),
                candidate_version_id=StoryCandidateVersionId.parse(
                    str(row["candidate_version_id"])
                ),
            )
        else:
            endpoint = RelationAssertionRelationEndpoint(
                assertion_id=EditorialRelationAssertionId.parse(
                    str(row["assertion_id"])
                )
            )
        data = endpoint_canonical_bytes(endpoint)
        if (
            str(row["endpoint_digest"]) != digest_bytes(data)
            or str(row["canonical_digest"]) != digest_bytes(data)
            or bytes(row["canonical_bytes"]) != data
        ):
            raise AuthorityPersistenceError(
                "editorial relation endpoint differs from canonical columns"
            )
        return endpoint

    def _require_editorial_endpoint_current(
        self,
        conn: sqlite3.Connection,
        endpoint: EditorialRelationEndpoint,
        *,
        visited_assertions: set[str] | None = None,
    ) -> None:
        if isinstance(endpoint, CanonicalEntityRelationEndpoint):
            try:
                self._require_candidate_current(
                    conn,
                    entity_id=endpoint.entity_id,
                    version_id=endpoint.entity_version_id,
                )
                self._require_entity_current(conn, endpoint.entity_id)
            except EntityStaleDecision as exc:
                raise EditorialRelationStaleDecision(str(exc)) from exc
            except EntityStateError as exc:
                raise EditorialRelationStateError(str(exc)) from exc
            except EntityRightsDenied as exc:
                raise EditorialRelationRightsDenied(str(exc)) from exc
            return
        if isinstance(endpoint, SourceRevisionRelationEndpoint):
            row = conn.execute(
                "SELECT r.definition_version_id,v.lifecycle_stage,h.current_version_id "
                "FROM source_revisions r "
                "JOIN source_definition_versions v ON v.version_id=r.definition_version_id "
                "JOIN source_definition_version_heads h ON h.definition_id=r.definition_id "
                "WHERE r.revision_id=? AND r.item_id=?",
                (str(endpoint.source_revision_id), str(endpoint.source_item_id)),
            ).fetchone()
            if row is None:
                raise EditorialRelationStateError(
                    "source revision endpoint is not retained"
                )
            if str(row["current_version_id"]) != str(row["definition_version_id"]):
                raise EditorialRelationRightsDenied(
                    "source revision definition version is no longer current"
                )
            if str(row["lifecycle_stage"]) in {"RETIRED", "REJECTED"}:
                raise EditorialRelationRightsDenied(
                    "source revision lifecycle blocks relation use"
                )
            return
        if isinstance(endpoint, StoryCandidateRelationEndpoint):
            row = conn.execute(
                "SELECT version_number FROM story_candidate_versions "
                "WHERE candidate_id=? AND candidate_version_id=?",
                (str(endpoint.candidate_id), str(endpoint.candidate_version_id)),
            ).fetchone()
            if row is None:
                raise EditorialRelationStateError(
                    "story candidate endpoint is not retained"
                )
            latest = conn.execute(
                "SELECT MAX(version_number) FROM story_candidate_versions "
                "WHERE candidate_id=?",
                (str(endpoint.candidate_id),),
            ).fetchone()[0]
            if int(row["version_number"]) != int(latest):
                raise EditorialRelationStaleDecision(
                    "story candidate endpoint version is no longer current"
                )
            return
        if isinstance(endpoint, EventHypothesisRelationEndpoint):
            rows = conn.execute(
                "SELECT candidate_id,version_number FROM story_candidate_versions "
                "WHERE hypothesis_version_id=?",
                (str(endpoint.hypothesis_version_id),),
            ).fetchall()
            if not rows:
                raise EditorialRelationStateError(
                    "event hypothesis endpoint has no retained workflow authority"
                )
            for row in rows:
                latest = conn.execute(
                    "SELECT MAX(version_number) FROM story_candidate_versions "
                    "WHERE candidate_id=?",
                    (str(row["candidate_id"]),),
                ).fetchone()[0]
                if int(row["version_number"]) == int(latest):
                    return
            raise EditorialRelationStaleDecision(
                "event hypothesis endpoint has no current workflow version"
            )
        if isinstance(endpoint, RelationAssertionRelationEndpoint):
            visited = (
                visited_assertions if visited_assertions is not None else set()
            )
            key = str(endpoint.assertion_id)
            if key in visited:
                raise AuthorityPersistenceError(
                    "editorial relation assertion endpoint cycle is retained"
                )
            visited.add(key)
            self._require_editorial_assertion_current(
                conn, endpoint.assertion_id, visited_assertions=visited
            )
            visited.remove(key)
            return

    def _validate_editorial_extraction_evidence(
        self, conn: sqlite3.Connection, evidence: ExtractionRelationEvidence
    ) -> None:
        try:
            proposal = self._source_proposal(conn, evidence.source_proposal_id)
        except ExtractionRightsDenied as exc:
            raise EditorialRelationRightsDenied(str(exc)) from exc
        if (
            proposal.canonical_digest != evidence.source_proposal_digest
            or proposal.run_id != evidence.run_id
            or proposal.run_version_id != evidence.run_version_id
            or proposal.output_id != evidence.output_id
        ):
            raise EditorialRelationStaleDecision(
                "relation extraction evidence differs from retained proposal"
            )
        if evidence.source_evidence_ordinal >= len(proposal.evidence):
            raise EditorialRelationStateError(
                "relation extraction evidence ordinal is outside the proposal"
            )
        retained = proposal.evidence[evidence.source_evidence_ordinal]
        if (
            retained.passage_id != evidence.passage_id
            or retained.start_byte != evidence.start_byte
            or retained.end_byte != evidence.end_byte
            or retained.evidence_text_digest != evidence.evidence_text_digest
        ):
            raise EditorialRelationStaleDecision(
                "relation extraction evidence range differs from retained proposal"
            )

    @staticmethod
    def _validate_editorial_workflow_evidence(
        conn: sqlite3.Connection, evidence: WorkflowRelationEvidence
    ) -> None:
        row = conn.execute(
            "SELECT * FROM ledger_events WHERE event_id=?",
            (str(evidence.authority_event_id),),
        ).fetchone()
        if row is None:
            raise EditorialRelationStateError(
                "relation workflow evidence event is not retained"
            )
        if (
            str(row["aggregate_type"]) != evidence.aggregate_type
            or str(row["aggregate_id"]) != evidence.aggregate_id
            or int(row["aggregate_version"]) != evidence.aggregate_version
            or workflow_event_digest(row) != evidence.event_digest
        ):
            raise EditorialRelationStaleDecision(
                "relation workflow evidence differs from retained authority event"
            )

    def _validate_editorial_evidence_current(
        self,
        conn: sqlite3.Connection,
        evidence: tuple[EditorialRelationEvidence, ...],
    ) -> None:
        for item in evidence:
            if isinstance(item, ExtractionRelationEvidence):
                self._validate_editorial_extraction_evidence(conn, item)
            else:
                self._validate_editorial_workflow_evidence(conn, item)

    def _editorial_dependencies_from_ids(
        self,
        conn: sqlite3.Connection,
        dependency_ids: tuple[EntityResolutionDependencyId, ...],
        *,
        require_accepted: bool,
        source_proposal_ids: frozenset[str],
    ):
        dependencies = []
        for dependency_id in dependency_ids:
            row = conn.execute(
                "SELECT * FROM entity_resolution_dependencies WHERE dependency_id=?",
                (str(dependency_id),),
            ).fetchone()
            if row is None:
                raise EditorialRelationStateError(
                    "entity resolution dependency is not retained"
                )
            dependency = self._dependency_from_row(conn, row, replayed=False)
            try:
                self._require_dependency_current(conn, dependency)
            except (EntityRightsDenied, ExtractionRightsDenied) as exc:
                raise EditorialRelationRightsDenied(str(exc)) from exc
            if str(dependency.dependent_proposal_id) not in source_proposal_ids:
                raise EditorialRelationStateError(
                    "relation dependency does not bind supplied extraction evidence"
                )
            if require_accepted and dependency.material:
                head = conn.execute(
                    "SELECT current_state FROM entity_resolution_decision_heads "
                    "WHERE resolution_proposal_id=?",
                    (str(dependency.resolution_proposal_id),),
                ).fetchone()
                if head is None or str(head["current_state"]) != "ACCEPTED":
                    raise EditorialRelationDecisionConflict(
                        "material entity identity is unresolved for relation admission"
                    )
            dependencies.append(dependency)
        return tuple(dependencies)

    def _require_editorial_proposal_version_current(
        self,
        conn: sqlite3.Connection,
        proposal_version_id: EditorialRelationProposalVersionId,
        *,
        require_dependencies_accepted: bool,
    ):
        row = conn.execute(
            "SELECT v.* FROM editorial_relation_proposal_versions v "
            "JOIN editorial_relation_proposal_heads h "
            "ON h.current_proposal_version_id=v.proposal_version_id "
            "WHERE v.proposal_version_id=?",
            (str(proposal_version_id),),
        ).fetchone()
        if row is None:
            raise EditorialRelationStaleDecision(
                "relation proposal version is no longer current"
            )
        result = self._editorial_proposal_version_from_row(conn, row, replayed=False)
        proposal_row = conn.execute(
            "SELECT p.*,s.kind AS subject_kind,o.kind AS object_kind "
            "FROM editorial_relation_proposals p "
            "JOIN editorial_relation_endpoints s "
            "ON s.endpoint_digest=p.subject_endpoint_digest "
            "JOIN editorial_relation_endpoints o "
            "ON o.endpoint_digest=p.object_endpoint_digest "
            "WHERE p.proposal_id=?",
            (str(result.proposal_id),),
        ).fetchone()
        if proposal_row is None:
            raise AuthorityPersistenceError("relation proposal base is missing")
        subject_row = conn.execute(
            "SELECT * FROM editorial_relation_endpoints WHERE endpoint_digest=?",
            (str(proposal_row["subject_endpoint_digest"]),),
        ).fetchone()
        object_row = conn.execute(
            "SELECT * FROM editorial_relation_endpoints WHERE endpoint_digest=?",
            (str(proposal_row["object_endpoint_digest"]),),
        ).fetchone()
        assert subject_row is not None and object_row is not None
        subject = self._editorial_endpoint_from_row(subject_row)
        object_ = self._editorial_endpoint_from_row(object_row)
        self._require_editorial_endpoint_current(conn, subject)
        self._require_editorial_endpoint_current(conn, object_)
        self._validate_editorial_evidence_current(conn, result.evidence)
        source_ids = frozenset(
            str(item.source_proposal_id)
            for item in result.evidence
            if isinstance(item, ExtractionRelationEvidence)
        )
        self._editorial_dependencies_from_ids(
            conn,
            result.resolution_dependency_ids,
            require_accepted=require_dependencies_accepted,
            source_proposal_ids=source_ids,
        )
        return result

    def _require_editorial_assertion_rights_current(
        self,
        conn: sqlite3.Connection,
        assertion_id: EditorialRelationAssertionId,
        *,
        visited_assertions: set[str] | None = None,
    ):
        visited = visited_assertions if visited_assertions is not None else set()
        root_key = str(assertion_id)
        owns_root = root_key not in visited
        if owns_root:
            visited.add(root_key)
        row = conn.execute(
            "SELECT * FROM editorial_relation_assertions WHERE assertion_id=?",
            (str(assertion_id),),
        ).fetchone()
        if row is None:
            raise EditorialRelationStateError("relation assertion is not retained")
        assertion = self._editorial_assertion_from_row(conn, row)
        self._require_editorial_endpoint_current(
            conn, assertion.subject, visited_assertions=visited
        )
        self._require_editorial_endpoint_current(
            conn, assertion.object, visited_assertions=visited
        )
        self._validate_editorial_evidence_current(conn, assertion.evidence)
        source_ids = frozenset(
            str(item.source_proposal_id)
            for item in assertion.evidence
            if isinstance(item, ExtractionRelationEvidence)
        )
        self._editorial_dependencies_from_ids(
            conn,
            assertion.resolution_dependency_ids,
            require_accepted=True,
            source_proposal_ids=source_ids,
        )
        if owns_root:
            visited.remove(root_key)
        return assertion

    def _require_editorial_assertion_current(
        self,
        conn: sqlite3.Connection,
        assertion_id: EditorialRelationAssertionId,
        *,
        visited_assertions: set[str] | None = None,
    ):
        head = self._editorial_assertion_head_row(conn, assertion_id)
        if head is None:
            raise EditorialRelationStateError("relation assertion is not retained")
        if str(head["lifecycle"]) != EditorialRelationAssertionLifecycle.ACTIVE.value:
            raise EditorialRelationRightsDenied(
                "relation assertion is not active current authority"
            )
        return self._require_editorial_assertion_rights_current(
            conn,
            assertion_id,
            visited_assertions=visited_assertions,
        )


__all__ = [
    "_EditorialRelationStoreSupport",
    "deterministic_editorial_projection_event_id",
    "workflow_event_digest",
]
