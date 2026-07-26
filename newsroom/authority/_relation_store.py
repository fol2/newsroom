from __future__ import annotations

from dataclasses import asdict
import json
import sqlite3
from typing import Any, Iterable

from ._capability import _AuthorizedCommandGrant
from ._event_store import _EventAuthorityStore
from .canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
    validate_sha256_digest,
)
from .persistence import AuthorityPersistenceError
from .types import EventId, ObjectAdmissionId, UtcTimestamp
from newsroom.relations.fixture_v2 import INTEGRATED_FIXTURE_V2
from newsroom.relations.models import (
    FixturePassageLifecycleLink,
    FixturePassageObject,
    IntegratedFixtureV2Binding,
    IntegratedFixtureV2BindingId,
    IntegratedFixtureV2BindingRequest,
    RelationAdmissionDecision,
    RelationAdmissionDecisionId,
    RelationAssertion,
    RelationAssertionId,
    RelationConflict,
    RelationCurrentState,
    RelationDecisionAction,
    RelationDecisionRequest,
    RelationDecisionResult,
    RelationEndpoint,
    RelationPredicate,
    RelationProducer,
    RelationProducerKind,
    RelationProjectionAction,
    RelationProjectionEvent,
    RelationProposal,
    RelationProposalId,
    RelationProposalRequest,
    RelationRecordType,
    RelationSemanticCollision,
    RelationStaleDecision,
    RelationStateError,
    RelationTemporalScope,
    governed_relation_key,
)
from newsroom.relations.policy import (
    INTEGRATED_FIXTURE_V2_BIND_COMMAND,
    RELATION_DECISION_COMMAND,
    RELATION_PROPOSAL_COMMAND,
)


_STATE_BY_ACTION = {
    RelationDecisionAction.HOLD: RelationCurrentState.HELD,
    RelationDecisionAction.REJECT: RelationCurrentState.REJECTED,
    RelationDecisionAction.ADMIT: RelationCurrentState.ADMITTED,
    RelationDecisionAction.INVALIDATE: RelationCurrentState.INVALIDATED,
    RelationDecisionAction.REVOKE: RelationCurrentState.REVOKED,
    RelationDecisionAction.SUPERSEDE: RelationCurrentState.SUPERSEDED,
}
_TERMINAL_STATES = {
    RelationCurrentState.INVALIDATED,
    RelationCurrentState.REVOKED,
    RelationCurrentState.SUPERSEDED,
}
_MAX_RELATION_CURRENT_SCAN = 10_000


class _RelationAuthorityStore(_EventAuthorityStore):
    """SQLite-authoritative fixture, proposal, decision, and assertion state."""

    def _migrate_or_validate(self) -> None:
        super()._migrate_or_validate()
        self._validate_relation_integrity()

    @staticmethod
    def _decode_relation_canonical(data: bytes, *, identity: str) -> dict[str, Any]:
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
        digest = str(row["canonical_digest"])
        if digest_bytes(canonical) != digest:
            raise AuthorityPersistenceError(
                f"{identity} canonical digest is inconsistent"
            )
        return cls._decode_relation_canonical(canonical, identity=identity)

    @staticmethod
    def _require_positive(value: object, *, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise AuthorityPersistenceError(f"{field} must be positive")
        return value

    @staticmethod
    def _event_row(conn: sqlite3.Connection, event_id: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM ledger_events WHERE event_id=?", (event_id,)
        ).fetchone()
        if row is None:
            raise AuthorityPersistenceError("relation authority event is missing")
        return row

    @staticmethod
    def _event_ledger_seq(conn: sqlite3.Connection, event_id: str) -> int:
        row = conn.execute(
            "SELECT ledger_seq FROM ledger_events WHERE event_id=?", (event_id,)
        ).fetchone()
        if row is None:
            raise AuthorityPersistenceError("object lifecycle event is missing")
        return int(row["ledger_seq"])

    @classmethod
    def _validate_event(
        cls,
        conn: sqlite3.Connection,
        *,
        event_id: str,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        aggregate_version: int,
        payload_digest: str,
        trust_scope: str,
        recorded_at: str,
    ) -> sqlite3.Row:
        event = cls._event_row(conn, event_id)
        if (
            str(event["event_type"]) != event_type
            or str(event["aggregate_type"]) != aggregate_type
            or str(event["aggregate_id"]) != aggregate_id
            or int(event["aggregate_version"]) != aggregate_version
            or str(event["payload_digest"]) != payload_digest
            or event["object_admission_id"] is not None
            or str(event["trust_scope"]) != trust_scope
            or str(event["security_scope"]) != "authority.relation"
            or str(event["retention_scope"]) != "authority.audit"
            or str(event["recorded_at"]) != recorded_at
        ):
            raise AuthorityPersistenceError(
                "relation authority event differs from immutable record"
            )
        return event

    @classmethod
    def _immutable_object_reference(
        cls,
        conn: sqlite3.Connection,
        admission_id: str,
        expected_blob_digest: str,
    ) -> sqlite3.Row:
        validate_sha256_digest(expected_blob_digest, field="object_blob_digest")
        row = conn.execute(
            "SELECT a.*,b.size_bytes AS blob_size_bytes,"
            "r.authentication_context_id AS rights_authentication_context_id,"
            "r.authorization_request_digest AS rights_authorization_request_digest,"
            "r.authorization_decision_id AS rights_authorization_decision_id,"
            "r.rights_request_digest,r.policy_contract_digest,"
            "r.admission_definition_digest,"
            "r.allowed AS rights_allowed,r.reason_code AS rights_reason_code,"
            "r.decided_at AS rights_decided_at,r.valid_from AS rights_valid_from,"
            "r.valid_until AS rights_valid_until,r.canonical_bytes AS rights_canonical_bytes,"
            "r.canonical_digest AS rights_canonical_digest "
            "FROM object_admissions a "
            "JOIN blob_identities b ON b.blob_digest=a.blob_digest "
            "JOIN object_rights_decisions r "
            "ON r.rights_decision_id=a.rights_decision_id "
            "WHERE a.admission_id=?",
            (admission_id,),
        ).fetchone()
        if row is None or str(row["blob_digest"]) != expected_blob_digest:
            raise AuthorityPersistenceError(
                "governed object reference differs from immutable admission"
            )
        rights_bytes = bytes(row["rights_canonical_bytes"])
        rights_digest = str(row["rights_canonical_digest"])
        if digest_bytes(rights_bytes) != rights_digest:
            raise AuthorityPersistenceError(
                "governed object rights digest is inconsistent"
            )
        rights = cls._decode_relation_canonical(
            rights_bytes, identity="governed object rights decision"
        )
        expected = {
            "rights_decision_id": str(row["rights_decision_id"]),
            "authentication_context_id": str(
                row["rights_authentication_context_id"]
            ),
            "authorization_request_digest": str(
                row["rights_authorization_request_digest"]
            ),
            "authorization_decision_id": str(
                row["rights_authorization_decision_id"]
            ),
            "rights_request_digest": str(row["rights_request_digest"]),
            "policy_contract_digest": str(row["policy_contract_digest"]),
            "admission_definition_digest": str(
                row["admission_definition_digest"]
            ),
            "object_class": str(row["object_class"]),
            "allowed_use": str(row["allowed_use"]),
            "security_scope": str(row["security_scope"]),
            "retention_scope": str(row["retention_scope"]),
            "allowed": bool(row["rights_allowed"]),
            "reason_code": str(row["rights_reason_code"]),
            "decided_at": str(row["rights_decided_at"]),
            "valid_from": str(row["rights_valid_from"]),
            "valid_until": (
                None
                if row["rights_valid_until"] is None
                else str(row["rights_valid_until"])
            ),
        }
        if any(rights.get(key) != value for key, value in expected.items()):
            raise AuthorityPersistenceError(
                "governed object rights canonical evidence differs from columns"
            )
        blob = rights.get("blob")
        if (
            not isinstance(blob, dict)
            or blob.get("blob_digest") != expected_blob_digest
            or blob.get("size_bytes") != int(row["blob_size_bytes"])
        ):
            raise AuthorityPersistenceError(
                "governed object rights blob evidence differs from authority"
            )
        return row

    @classmethod
    def _object_current_state(
        cls,
        conn: sqlite3.Connection,
        admission_id: str,
        expected_blob_digest: str,
        *,
        now: UtcTimestamp,
    ) -> tuple[bool, str, tuple[int, EventId] | None]:
        admission = cls._immutable_object_reference(
            conn, admission_id, expected_blob_digest
        )
        lifecycle = conn.execute(
            "SELECT av.state AS admission_state,av.event_id AS admission_event_id,"
            "av.recorded_at AS admission_recorded_at,bv.state AS blob_state,"
            "bv.integrity_state AS blob_integrity_state,bv.event_id AS blob_event_id,"
            "bv.recorded_at AS blob_recorded_at "
            "FROM object_admission_heads ah "
            "JOIN object_admission_versions av "
            "ON av.admission_id=ah.admission_id "
            "AND av.lifecycle_version=ah.current_version "
            "JOIN object_admissions a ON a.admission_id=ah.admission_id "
            "JOIN blob_lifecycle_heads bh ON bh.blob_digest=a.blob_digest "
            "JOIN blob_lifecycle_versions bv "
            "ON bv.blob_digest=bh.blob_digest "
            "AND bv.lifecycle_version=bh.current_version "
            "WHERE ah.admission_id=?",
            (admission_id,),
        ).fetchone()
        if lifecycle is None:
            raise AuthorityPersistenceError(
                "governed object lifecycle authority is missing"
            )
        deletion = conn.execute(
            "SELECT dv.state,dv.event_id,dv.recorded_at "
            "FROM object_deletions d "
            "JOIN object_deletion_heads dh ON dh.deletion_id=d.deletion_id "
            "JOIN object_deletion_versions dv "
            "ON dv.deletion_id=dh.deletion_id "
            "AND dv.lifecycle_version=dh.current_version "
            "WHERE d.blob_digest=? ORDER BY d.created_at DESC LIMIT 1",
            (expected_blob_digest,),
        ).fetchone()

        invalid_events: list[tuple[int, int, EventId, str]] = []

        def add_event(event_value: object, reason: str, *, priority: int) -> None:
            if event_value is None:
                return
            event_id = EventId.parse(str(event_value))
            invalid_events.append(
                (
                    cls._event_ledger_seq(conn, str(event_id)),
                    priority,
                    event_id,
                    reason,
                )
            )

        admission_state = str(lifecycle["admission_state"])
        blob_state = str(lifecycle["blob_state"])
        integrity_state = str(lifecycle["blob_integrity_state"])
        if admission_state != "ACTIVE":
            add_event(
                lifecycle["admission_event_id"],
                f"OBJECT_ADMISSION_{admission_state}",
                priority=1,
            )
        if blob_state != "ACTIVE" or integrity_state != "VERIFIED":
            add_event(
                lifecycle["blob_event_id"],
                f"OBJECT_BLOB_{blob_state}_{integrity_state}",
                priority=2,
            )
        if deletion is not None and str(deletion["state"]) != "FAILED":
            add_event(
                deletion["event_id"],
                f"OBJECT_DELETION_{str(deletion['state'])}",
                priority=3,
            )
        if invalid_events:
            ledger_seq, _priority, event_id, reason = max(
                invalid_events, key=lambda item: (item[0], item[1])
            )
            return False, reason, (ledger_seq, event_id)
        if not bool(admission["rights_allowed"]):
            return False, "OBJECT_RIGHTS_DENIED", None
        for start_field, end_field, prefix in (
            ("valid_from", "valid_until", "OBJECT_ADMISSION"),
            ("rights_valid_from", "rights_valid_until", "OBJECT_RIGHTS"),
        ):
            start = UtcTimestamp.parse(str(admission[start_field]))
            end = (
                None
                if admission[end_field] is None
                else UtcTimestamp.parse(str(admission[end_field]))
            )
            if now.value < start.value:
                return False, f"{prefix}_NOT_YET_VALID", None
            if end is not None and now.value >= end.value:
                return False, f"{prefix}_EXPIRED", None
        if str(admission["allowed_use"]) != "project.discovery":
            return False, "OBJECT_USE_NOT_DISCOVERY", None
        if str(admission["security_scope"]) != "authority.protected":
            return False, "OBJECT_SECURITY_SCOPE_MISMATCH", None
        if str(admission["retention_scope"]) != "source.short":
            return False, "OBJECT_RETENTION_SCOPE_MISMATCH", None
        return True, "OBJECT_CURRENT", None

    @classmethod
    def _require_current_object(
        cls,
        conn: sqlite3.Connection,
        admission_id: str,
        expected_blob_digest: str,
        *,
        now: UtcTimestamp,
    ) -> None:
        current, reason, _event = cls._object_current_state(
            conn,
            admission_id,
            expected_blob_digest,
            now=now,
        )
        if not current:
            raise RelationStateError(
                f"governed relation object is not current: {reason}"
            )

    @classmethod
    def _require_retained_fixture_object(
        cls,
        conn: sqlite3.Connection,
        admission_id: str,
        expected_blob_digest: str,
        *,
        now: UtcTimestamp,
    ) -> None:
        """Require the fixture's explicit retained repository-permitted rights.

        Increment 2A has no scheduler that can emit an ordered projection removal
        exactly when a wall-clock expiry occurs.  The repository fixture therefore
        rejects expiring admission or rights windows instead of creating a silent
        time-based projection divergence.  Explicit revocation and deletion remain
        ordered lifecycle events and are handled by the projection seam.
        """

        row = cls._immutable_object_reference(
            conn, admission_id, expected_blob_digest
        )
        if row["valid_until"] is not None or row["rights_valid_until"] is not None:
            raise RelationStateError(
                "integrated_fixture_v2 requires non-expiring retained rights"
            )
        cls._require_current_object(
            conn,
            admission_id,
            expected_blob_digest,
            now=now,
        )

    @classmethod
    def _fixture_passage_lifecycle_link(
        cls,
        conn: sqlite3.Connection,
        *,
        passage_id: str,
        expected_lifecycle: str,
        admission_id: str,
        expected_blob_digest: str,
        now: UtcTimestamp,
    ) -> FixturePassageLifecycleLink:
        row = cls._immutable_object_reference(
            conn, admission_id, expected_blob_digest
        )
        if row["valid_until"] is not None or row["rights_valid_until"] is not None:
            raise RelationStateError(
                "integrated_fixture_v2 requires non-expiring retained rights"
            )

        if expected_lifecycle == "ACTIVE":
            cls._require_current_object(
                conn,
                admission_id,
                expected_blob_digest,
                now=now,
            )
            lifecycle = conn.execute(
                "SELECT v.event_id,v.recorded_at FROM object_admission_heads h "
                "JOIN object_admission_versions v "
                "ON v.admission_id=h.admission_id "
                "AND v.lifecycle_version=h.current_version "
                "WHERE h.admission_id=? AND v.state='ACTIVE'",
                (admission_id,),
            ).fetchone()
            if lifecycle is None or lifecycle["event_id"] is None:
                raise AuthorityPersistenceError(
                    "active fixture passage lacks lifecycle authority event"
                )
            event_id = EventId.parse(str(lifecycle["event_id"]))
            recorded_at = UtcTimestamp.parse(str(lifecycle["recorded_at"]))
        elif expected_lifecycle == "TOMBSTONED":
            current, reason, lifecycle_event = cls._object_current_state(
                conn,
                admission_id,
                expected_blob_digest,
                now=now,
            )
            if (
                current
                or reason != "OBJECT_DELETION_TOMBSTONED"
                or lifecycle_event is None
            ):
                raise RelationStateError(
                    "fixture tombstone-negative passage must be governed TOMBSTONED"
                )
            _ledger_seq, event_id = lifecycle_event
            event = cls._event_row(conn, str(event_id))
            recorded_at = UtcTimestamp.parse(str(event["recorded_at"]))
        else:
            raise AuthorityPersistenceError(
                "repository fixture passage lifecycle is unsupported"
            )

        return FixturePassageLifecycleLink(
            passage_id=passage_id,
            expected_lifecycle=expected_lifecycle,
            authority_event_id=event_id,
            authority_ledger_seq=cls._event_ledger_seq(conn, str(event_id)),
            recorded_at=recorded_at,
        )

    @classmethod
    def _validate_fixture_passage_lifecycle_link(
        cls,
        conn: sqlite3.Connection,
        *,
        admission_id: str,
        blob_digest: str,
        link: FixturePassageLifecycleLink,
        binding_ledger_seq: int,
    ) -> None:
        event = cls._event_row(conn, str(link.authority_event_id))
        if (
            int(event["ledger_seq"]) != link.authority_ledger_seq
            or str(event["recorded_at"]) != link.recorded_at.to_text()
            or link.authority_ledger_seq >= binding_ledger_seq
        ):
            raise AuthorityPersistenceError(
                "fixture passage lifecycle link is not ordered before binding"
            )
        if link.expected_lifecycle == "ACTIVE":
            admission = conn.execute(
                "SELECT v.state FROM object_admission_versions v "
                "WHERE v.admission_id=? AND v.event_id=?",
                (admission_id, str(link.authority_event_id)),
            ).fetchone()
            blob = conn.execute(
                "SELECT v.state,v.integrity_state FROM blob_lifecycle_versions v "
                "WHERE v.blob_digest=? AND v.event_id=?",
                (blob_digest, str(link.authority_event_id)),
            ).fetchone()
            if (
                admission is None
                or str(admission["state"]) != "ACTIVE"
                or blob is None
                or str(blob["state"]) != "ACTIVE"
                or str(blob["integrity_state"]) != "VERIFIED"
                or str(event["event_type"])
                != "governed_object.admission.activated"
            ):
                raise AuthorityPersistenceError(
                    "fixture active passage lifecycle link is inconsistent"
                )
            return

        deletion = conn.execute(
            "SELECT dv.state FROM object_deletions d "
            "JOIN object_deletion_versions dv ON dv.deletion_id=d.deletion_id "
            "WHERE d.blob_digest=? AND dv.event_id=?",
            (blob_digest, str(link.authority_event_id)),
        ).fetchone()
        if (
            link.expected_lifecycle != "TOMBSTONED"
            or deletion is None
            or str(deletion["state"]) != "TOMBSTONED"
            or str(event["event_type"])
            != "governed_blob.deletion.tombstoned"
        ):
            raise AuthorityPersistenceError(
                "fixture tombstoned passage lifecycle link is inconsistent"
            )

    @staticmethod
    def _validate_exact_fixture_binding_request(
        request: IntegratedFixtureV2BindingRequest,
    ) -> None:
        fixture = INTEGRATED_FIXTURE_V2
        if (
            request.fixture_id != fixture.fixture_id
            or request.schema_version != fixture.schema_version
            or request.fixture_digest != fixture.manifest_digest
            or request.manifest_blob_digest != fixture.manifest_digest
        ):
            raise RelationStateError(
                "fixture binding differs from repository integrated_fixture_v2"
            )
        expected = fixture.expected_passage_digests
        actual = {item.passage_id: item.blob_digest for item in request.passage_objects}
        if actual != expected:
            raise RelationStateError(
                "fixture passage objects differ from repository integrated_fixture_v2"
            )

    def commit_fixture_binding(
        self,
        grant: _AuthorizedCommandGrant,
        request: IntegratedFixtureV2BindingRequest,
    ) -> IntegratedFixtureV2Binding:
        if not isinstance(request, IntegratedFixtureV2BindingRequest):
            raise TypeError("fixture binding requires a typed request")
        self._validate_exact_fixture_binding_request(request)
        if (
            grant.command_type != INTEGRATED_FIXTURE_V2_BIND_COMMAND
            or grant.aggregate_id != str(request.binding_id)
            or grant.expected_aggregate_version != 0
            or grant.payload.inline_bytes != request.canonical_bytes
        ):
            raise PermissionError(
                "fixture binding grant is not bound to the exact request"
            )
        with self._lock, self._transaction() as conn:
            recorded_at = self._clock().to_text()
            if grant.replay_of_command_id is not None:
                committed = self._commit_grant_in_transaction(
                    conn, grant, recorded_at=recorded_at
                )
                return self._binding_for_event(
                    conn, committed.event_id, replayed=True
                )
            duplicate = conn.execute(
                "SELECT binding_id FROM integrated_fixture_v2_bindings "
                "WHERE fixture_id=? AND fixture_digest=? AND binding_id!=?",
                (
                    request.fixture_id,
                    request.fixture_digest,
                    str(request.binding_id),
                ),
            ).fetchone()
            if duplicate is not None:
                raise RelationSemanticCollision(
                    "repository fixture already has a different binding identity"
                )
            checked_at = self._clock()
            self._require_retained_fixture_object(
                conn,
                str(request.manifest_admission_id),
                request.manifest_blob_digest,
                now=checked_at,
            )
            fixture_passages = INTEGRATED_FIXTURE_V2.passage_by_id
            lifecycle_links: dict[str, FixturePassageLifecycleLink] = {}
            for passage_object in request.passage_objects:
                passage = fixture_passages[passage_object.passage_id]
                lifecycle_links[passage.passage_id] = (
                    self._fixture_passage_lifecycle_link(
                        conn,
                        passage_id=passage.passage_id,
                        expected_lifecycle=passage.expected_lifecycle,
                        admission_id=str(passage_object.admission_id),
                        expected_blob_digest=passage_object.blob_digest,
                        now=checked_at,
                    )
                )
            committed = self._commit_grant_in_transaction(
                conn, grant, recorded_at=recorded_at
            )
            canonical = request.canonical_bytes
            conn.execute(
                "INSERT INTO integrated_fixture_v2_bindings("
                "binding_id,fixture_id,schema_version,fixture_digest,"
                "manifest_admission_id,manifest_blob_digest,authority_event_id,"
                "authority_aggregate_version,canonical_bytes,canonical_digest,"
                "recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(request.binding_id),
                    request.fixture_id,
                    request.schema_version,
                    request.fixture_digest,
                    str(request.manifest_admission_id),
                    request.manifest_blob_digest,
                    committed.event_id,
                    committed.aggregate_version,
                    canonical,
                    digest_bytes(canonical),
                    recorded_at,
                ),
            )
            for passage_object in request.passage_objects:
                passage = fixture_passages[passage_object.passage_id]
                lifecycle_link = lifecycle_links[passage.passage_id]
                value = {
                    **passage_object.canonical_value(),
                    "revision_id": passage.revision_id,
                    "language": passage.language,
                    "expected_lifecycle": passage.expected_lifecycle,
                    "eligible_for_relation_evidence": (
                        passage.eligible_for_relation_evidence
                    ),
                    "bound_lifecycle": lifecycle_link.canonical_value(),
                }
                passage_canonical = canonical_json_bytes(value)
                conn.execute(
                    "INSERT INTO integrated_fixture_v2_passage_objects("
                    "binding_id,passage_id,revision_id,language,expected_lifecycle,"
                    "eligible_for_relation_evidence,admission_id,blob_digest,"
                    "canonical_bytes,canonical_digest) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        str(request.binding_id),
                        passage.passage_id,
                        passage.revision_id,
                        passage.language,
                        passage.expected_lifecycle,
                        int(passage.eligible_for_relation_evidence),
                        str(passage_object.admission_id),
                        passage_object.blob_digest,
                        passage_canonical,
                        digest_bytes(passage_canonical),
                    ),
                )
            return self._binding_for_event(conn, committed.event_id, replayed=False)

    @classmethod
    def _binding_from_row(
        cls,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        replayed: bool,
    ) -> IntegratedFixtureV2Binding:
        passages = conn.execute(
            "SELECT passage_id,admission_id,blob_digest,canonical_bytes,"
            "canonical_digest "
            "FROM integrated_fixture_v2_passage_objects "
            "WHERE binding_id=? ORDER BY passage_id",
            (str(row["binding_id"]),),
        ).fetchall()
        event = cls._event_row(conn, str(row["authority_event_id"]))
        lifecycle_links: list[FixturePassageLifecycleLink] = []
        for item in passages:
            value = cls._canonical_row_value(
                item, identity="integrated fixture v2 passage"
            )
            lifecycle = value.get("bound_lifecycle")
            if not isinstance(lifecycle, dict):
                raise AuthorityPersistenceError(
                    "fixture passage lacks bound lifecycle evidence"
                )
            lifecycle_links.append(
                FixturePassageLifecycleLink(
                    passage_id=str(lifecycle["passage_id"]),
                    expected_lifecycle=str(lifecycle["expected_lifecycle"]),
                    authority_event_id=EventId.parse(
                        str(lifecycle["authority_event_id"])
                    ),
                    authority_ledger_seq=int(
                        lifecycle["authority_ledger_seq"]
                    ),
                    recorded_at=UtcTimestamp.parse(
                        str(lifecycle["recorded_at"])
                    ),
                )
            )
        return IntegratedFixtureV2Binding(
            binding_id=IntegratedFixtureV2BindingId.parse(str(row["binding_id"])),
            fixture_id=str(row["fixture_id"]),
            schema_version=str(row["schema_version"]),
            fixture_digest=str(row["fixture_digest"]),
            manifest_admission_id=ObjectAdmissionId.parse(
                str(row["manifest_admission_id"])
            ),
            manifest_blob_digest=str(row["manifest_blob_digest"]),
            passage_objects=tuple(
                FixturePassageObject(
                    passage_id=str(item["passage_id"]),
                    admission_id=ObjectAdmissionId.parse(str(item["admission_id"])),
                    blob_digest=str(item["blob_digest"]),
                )
                for item in passages
            ),
            passage_lifecycle_links=tuple(lifecycle_links),
            authority_event_id=EventId.parse(str(row["authority_event_id"])),
            authority_ledger_seq=int(event["ledger_seq"]),
            authority_aggregate_version=int(row["authority_aggregate_version"]),
            recorded_at=UtcTimestamp.parse(str(row["recorded_at"])),
            replayed=replayed,
        )

    @classmethod
    def _binding_for_event(
        cls,
        conn: sqlite3.Connection,
        event_id: str,
        *,
        replayed: bool,
    ) -> IntegratedFixtureV2Binding:
        row = conn.execute(
            "SELECT * FROM integrated_fixture_v2_bindings WHERE authority_event_id=?",
            (event_id,),
        ).fetchone()
        if row is None:
            raise AuthorityPersistenceError(
                "fixture binding command lacks exact retained binding"
            )
        return cls._binding_from_row(conn, row, replayed=replayed)

    def fixture_binding(
        self, binding_id: IntegratedFixtureV2BindingId
    ) -> IntegratedFixtureV2Binding:
        if not isinstance(binding_id, IntegratedFixtureV2BindingId):
            raise TypeError("fixture binding identity must be typed")
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM integrated_fixture_v2_bindings WHERE binding_id=?",
                (str(binding_id),),
            ).fetchone()
            if row is None:
                raise KeyError(str(binding_id))
            return self._binding_from_row(self._connection, row, replayed=False)

    def commit_relation_proposal(
        self,
        grant: _AuthorizedCommandGrant,
        request: RelationProposalRequest,
    ) -> RelationProposal:
        if not isinstance(request, RelationProposalRequest):
            raise TypeError("relation proposal requires a typed request")
        if (
            grant.command_type != RELATION_PROPOSAL_COMMAND
            or grant.aggregate_id != str(request.proposal_id)
            or grant.expected_aggregate_version != 0
            or grant.payload.inline_bytes != request.canonical_bytes
        ):
            raise PermissionError(
                "relation proposal grant is not bound to the exact proposal"
            )
        with self._lock, self._transaction() as conn:
            recorded_at = self._clock().to_text()
            if grant.replay_of_command_id is not None:
                committed = self._commit_grant_in_transaction(
                    conn, grant, recorded_at=recorded_at
                )
                return self._proposal_for_event(
                    conn, committed.event_id, replayed=True
                )
            binding = conn.execute(
                "SELECT * FROM integrated_fixture_v2_bindings WHERE binding_id=?",
                (str(request.fixture_binding_id),),
            ).fetchone()
            if binding is None:
                raise RelationStateError("relation proposal lacks fixture binding")
            duplicate = conn.execute(
                "SELECT proposal_id FROM relation_proposals "
                "WHERE semantic_identity_digest=? AND proposal_id!=?",
                (request.semantic_identity_digest, str(request.proposal_id)),
            ).fetchone()
            if duplicate is not None:
                raise RelationSemanticCollision(
                    "exact relation semantics already belong to another proposal"
                )
            evidence_rows = self._proposal_evidence_rows(conn, request)
            checked_at = self._clock()
            self._require_current_object(
                conn,
                str(binding["manifest_admission_id"]),
                str(binding["manifest_blob_digest"]),
                now=checked_at,
            )
            for row in evidence_rows:
                self._require_current_object(
                    conn,
                    str(row["admission_id"]),
                    str(row["blob_digest"]),
                    now=checked_at,
                )
            committed = self._commit_grant_in_transaction(
                conn, grant, recorded_at=recorded_at
            )
            canonical = request.canonical_bytes
            conn.execute(
                "INSERT INTO relation_proposals("
                "proposal_id,fixture_binding_id,subject_type,subject_id,predicate,"
                "object_type,object_id,valid_from,valid_until,temporal_precision,"
                "producer_kind,producer_id,producer_version,rule_version,statement,"
                "uncertainties_bytes,trust_scope,proposal_digest,"
                "semantic_slot_digest,semantic_identity_digest,authority_event_id,"
                "authority_ledger_seq,authority_aggregate_version,canonical_bytes,"
                "canonical_digest,recorded_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(request.proposal_id),
                    str(request.fixture_binding_id),
                    request.subject.record_type.value,
                    request.subject.record_id,
                    request.predicate.value,
                    request.object.record_type.value,
                    request.object.record_id,
                    request.temporal_scope.valid_from.to_text(),
                    (
                        None
                        if request.temporal_scope.valid_until is None
                        else request.temporal_scope.valid_until.to_text()
                    ),
                    request.temporal_scope.precision,
                    request.producer.kind.value,
                    request.producer.producer_id,
                    request.producer.producer_version,
                    request.producer.rule_version,
                    request.statement,
                    canonical_json_bytes(list(request.uncertainties)),
                    "PROPOSED",
                    request.proposal_digest,
                    request.semantic_slot_digest,
                    request.semantic_identity_digest,
                    committed.event_id,
                    committed.ledger_seq,
                    committed.aggregate_version,
                    canonical,
                    digest_bytes(canonical),
                    recorded_at,
                ),
            )
            for row in evidence_rows:
                value = {
                    "proposal_id": str(request.proposal_id),
                    "fixture_binding_id": str(request.fixture_binding_id),
                    "passage_id": str(row["passage_id"]),
                    "admission_id": str(row["admission_id"]),
                    "blob_digest": str(row["blob_digest"]),
                }
                evidence_canonical = canonical_json_bytes(value)
                conn.execute(
                    "INSERT INTO relation_proposal_evidence("
                    "proposal_id,fixture_binding_id,passage_id,admission_id,"
                    "blob_digest,canonical_bytes,canonical_digest) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (
                        str(request.proposal_id),
                        str(request.fixture_binding_id),
                        str(row["passage_id"]),
                        str(row["admission_id"]),
                        str(row["blob_digest"]),
                        evidence_canonical,
                        digest_bytes(evidence_canonical),
                    ),
                )
            return self._proposal_for_event(conn, committed.event_id, replayed=False)

    @staticmethod
    def _proposal_evidence_rows(
        conn: sqlite3.Connection,
        request: RelationProposalRequest,
    ) -> tuple[sqlite3.Row, ...]:
        rows: list[sqlite3.Row] = []
        for passage_id in request.evidence_passage_ids:
            row = conn.execute(
                "SELECT * FROM integrated_fixture_v2_passage_objects "
                "WHERE binding_id=? AND passage_id=?",
                (str(request.fixture_binding_id), passage_id),
            ).fetchone()
            if row is None:
                raise RelationStateError(
                    "relation proposal references unknown fixture passage"
                )
            if not bool(row["eligible_for_relation_evidence"]):
                raise RelationStateError(
                    "relation proposal references ineligible fixture passage"
                )
            if str(row["expected_lifecycle"]) != "ACTIVE":
                raise RelationStateError(
                    "relation proposal cannot use tombstone-negative passage"
                )
            rows.append(row)
        return tuple(rows)

    @classmethod
    def _proposal_from_row(
        cls,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        replayed: bool,
    ) -> RelationProposal:
        value = cls._canonical_row_value(row, identity="relation proposal")
        temporal = value["temporal_scope"]
        producer = value["producer"]
        evidence = value["evidence_passage_ids"]
        uncertainties = value["uncertainties"]
        if (
            not isinstance(temporal, dict)
            or not isinstance(producer, dict)
            or not isinstance(evidence, list)
            or not isinstance(uncertainties, list)
        ):
            raise AuthorityPersistenceError("relation proposal canonical shape is invalid")
        event = cls._event_row(conn, str(row["authority_event_id"]))
        evidence_rows = conn.execute(
            "SELECT passage_id,admission_id,blob_digest "
            "FROM relation_proposal_evidence WHERE proposal_id=? "
            "ORDER BY passage_id",
            (str(row["proposal_id"]),),
        ).fetchall()
        proposal = RelationProposal(
            proposal_id=RelationProposalId.parse(str(row["proposal_id"])),
            fixture_binding_id=IntegratedFixtureV2BindingId.parse(
                str(row["fixture_binding_id"])
            ),
            subject=RelationEndpoint(
                RelationRecordType(str(row["subject_type"])),
                str(row["subject_id"]),
            ),
            predicate=RelationPredicate(str(row["predicate"])),
            object=RelationEndpoint(
                RelationRecordType(str(row["object_type"])),
                str(row["object_id"]),
            ),
            temporal_scope=RelationTemporalScope(
                UtcTimestamp.parse(str(row["valid_from"])),
                (
                    None
                    if row["valid_until"] is None
                    else UtcTimestamp.parse(str(row["valid_until"]))
                ),
                str(row["temporal_precision"]),
            ),
            evidence_passage_ids=tuple(str(item) for item in evidence),
            evidence_objects=tuple(
                FixturePassageObject(
                    passage_id=str(item["passage_id"]),
                    admission_id=ObjectAdmissionId.parse(
                        str(item["admission_id"])
                    ),
                    blob_digest=str(item["blob_digest"]),
                )
                for item in evidence_rows
            ),
            producer=RelationProducer(
                RelationProducerKind(str(row["producer_kind"])),
                str(row["producer_id"]),
                str(row["producer_version"]),
                str(row["rule_version"]),
            ),
            statement=str(row["statement"]),
            uncertainties=tuple(str(item) for item in uncertainties),
            proposal_digest=str(row["proposal_digest"]),
            semantic_slot_digest=str(row["semantic_slot_digest"]),
            semantic_identity_digest=str(row["semantic_identity_digest"]),
            authority_event_id=EventId.parse(str(row["authority_event_id"])),
            authority_ledger_seq=int(event["ledger_seq"]),
            recorded_at=UtcTimestamp.parse(str(row["recorded_at"])),
            replayed=replayed,
        )
        return proposal

    @classmethod
    def _proposal_for_event(
        cls,
        conn: sqlite3.Connection,
        event_id: str,
        *,
        replayed: bool,
    ) -> RelationProposal:
        row = conn.execute(
            "SELECT * FROM relation_proposals WHERE authority_event_id=?",
            (event_id,),
        ).fetchone()
        if row is None:
            raise AuthorityPersistenceError(
                "relation proposal command lacks exact retained proposal"
            )
        return cls._proposal_from_row(conn, row, replayed=replayed)

    def relation_proposal(self, proposal_id: RelationProposalId) -> RelationProposal:
        if not isinstance(proposal_id, RelationProposalId):
            raise TypeError("relation proposal identity must be typed")
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM relation_proposals WHERE proposal_id=?",
                (str(proposal_id),),
            ).fetchone()
            if row is None:
                raise KeyError(str(proposal_id))
            return self._proposal_from_row(self._connection, row, replayed=False)

    @classmethod
    def _proposal_matches_fixture_rule(
        cls,
        conn: sqlite3.Connection,
        proposal: RelationProposal,
    ) -> bool:
        fixture = INTEGRATED_FIXTURE_V2
        template = fixture.relation
        if (
            proposal.fixture_binding_id is None
            or proposal.subject != template.subject
            or proposal.predicate is not template.predicate
            or proposal.object != template.object
            or proposal.temporal_scope != template.temporal_scope
            or proposal.producer != template.producer
            or proposal.statement != template.statement
            or proposal.uncertainties != template.uncertainties
            or proposal.evidence_passage_ids != template.evidence_passage_ids
        ):
            return False
        binding = conn.execute(
            "SELECT fixture_id,fixture_digest FROM integrated_fixture_v2_bindings "
            "WHERE binding_id=?",
            (str(proposal.fixture_binding_id),),
        ).fetchone()
        return bool(
            binding is not None
            and str(binding["fixture_id"]) == fixture.fixture_id
            and str(binding["fixture_digest"]) == fixture.manifest_digest
        )

    @classmethod
    def _current_decision_head(
        cls,
        conn: sqlite3.Connection,
        proposal_id: str,
    ) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT h.current_version,h.decision_id,h.current_state,d.* "
            "FROM relation_decision_heads h "
            "JOIN relation_admission_decisions d ON d.decision_id=h.decision_id "
            "WHERE h.proposal_id=?",
            (proposal_id,),
        ).fetchone()

    @staticmethod
    def _require_transition(
        current: RelationCurrentState | None,
        action: RelationDecisionAction,
    ) -> None:
        allowed: dict[RelationCurrentState | None, set[RelationDecisionAction]] = {
            None: {
                RelationDecisionAction.ADMIT,
                RelationDecisionAction.REJECT,
                RelationDecisionAction.HOLD,
                RelationDecisionAction.INVALIDATE,
            },
            RelationCurrentState.HELD: {
                RelationDecisionAction.ADMIT,
                RelationDecisionAction.REJECT,
                RelationDecisionAction.HOLD,
                RelationDecisionAction.INVALIDATE,
                RelationDecisionAction.SUPERSEDE,
            },
            RelationCurrentState.ADMITTED: {
                RelationDecisionAction.REVOKE,
                RelationDecisionAction.INVALIDATE,
                RelationDecisionAction.SUPERSEDE,
            },
            RelationCurrentState.REJECTED: {
                RelationDecisionAction.INVALIDATE,
                RelationDecisionAction.SUPERSEDE,
            },
            RelationCurrentState.INVALIDATED: set(),
            RelationCurrentState.REVOKED: set(),
            RelationCurrentState.SUPERSEDED: set(),
            RelationCurrentState.PROPOSED: set(),
        }
        if action not in allowed[current]:
            label = "PROPOSED" if current is None else current.value
            raise RelationStateError(
                f"relation decision {action.value} is invalid from {label}"
            )

    @classmethod
    def _assert_fixture_objects_current(
        cls,
        conn: sqlite3.Connection,
        proposal: RelationProposal,
        *,
        now: UtcTimestamp,
    ) -> None:
        binding = conn.execute(
            "SELECT * FROM integrated_fixture_v2_bindings WHERE binding_id=?",
            (str(proposal.fixture_binding_id),),
        ).fetchone()
        if binding is None:
            raise RelationStateError("proposal fixture binding is missing")
        cls._require_current_object(
            conn,
            str(binding["manifest_admission_id"]),
            str(binding["manifest_blob_digest"]),
            now=now,
        )
        evidence = conn.execute(
            "SELECT admission_id,blob_digest FROM relation_proposal_evidence "
            "WHERE proposal_id=? ORDER BY passage_id",
            (str(proposal.proposal_id),),
        ).fetchall()
        if len(evidence) != len(proposal.evidence_passage_ids):
            raise RelationStateError(
                "relation proposal lacks complete governed evidence linkage"
            )
        for row in evidence:
            cls._require_current_object(
                conn,
                str(row["admission_id"]),
                str(row["blob_digest"]),
                now=now,
            )

    @classmethod
    def _require_successor(
        cls,
        conn: sqlite3.Connection,
        proposal: RelationProposal,
        successor_id: RelationProposalId,
    ) -> RelationProposal:
        row = conn.execute(
            "SELECT * FROM relation_proposals WHERE proposal_id=?",
            (str(successor_id),),
        ).fetchone()
        if row is None:
            raise RelationStateError("supersession successor proposal is missing")
        successor = cls._proposal_from_row(conn, row, replayed=False)
        if (
            successor.fixture_binding_id != proposal.fixture_binding_id
            or successor.subject != proposal.subject
            or successor.predicate is not proposal.predicate
            or successor.object != proposal.object
        ):
            raise RelationStateError(
                "supersession successor must preserve exact relation axis"
            )
        if successor.authority_ledger_seq <= proposal.authority_ledger_seq:
            raise RelationStateError(
                "supersession successor must be recorded later than its predecessor"
            )
        return successor

    def commit_relation_decision(
        self,
        grant: _AuthorizedCommandGrant,
        request: RelationDecisionRequest,
    ) -> RelationDecisionResult:
        if not isinstance(request, RelationDecisionRequest):
            raise TypeError("relation decision requires a typed request")
        payload_bytes = canonical_json_bytes(request.canonical_value())
        if (
            grant.command_type != RELATION_DECISION_COMMAND
            or grant.aggregate_id != str(request.proposal_id)
            or grant.expected_aggregate_version != request.expected_decision_version
            or grant.payload.inline_bytes != payload_bytes
        ):
            raise PermissionError(
                "relation decision grant is not bound to the exact request"
            )
        with self._lock, self._transaction() as conn:
            recorded_at = self._clock().to_text()
            if grant.replay_of_command_id is not None:
                committed = self._commit_grant_in_transaction(
                    conn, grant, recorded_at=recorded_at
                )
                return self._decision_for_event(
                    conn, committed.event_id, replayed=True
                )
            proposal_row = conn.execute(
                "SELECT * FROM relation_proposals WHERE proposal_id=?",
                (str(request.proposal_id),),
            ).fetchone()
            if proposal_row is None:
                raise RelationStateError("relation decision proposal is missing")
            proposal = self._proposal_from_row(conn, proposal_row, replayed=False)
            if proposal.proposal_digest != request.expected_proposal_digest:
                raise RelationStaleDecision(
                    "relation decision expected proposal digest is stale"
                )
            head = self._current_decision_head(conn, str(request.proposal_id))
            if head is None:
                if (
                    request.expected_decision_version != 0
                    or request.expected_previous_decision_id is not None
                ):
                    raise RelationStaleDecision(
                        "relation decision expected head is stale"
                    )
                current_state = None
                previous_decision_id = None
            else:
                current_version = int(head["current_version"])
                current_decision_id = RelationAdmissionDecisionId.parse(
                    str(head["decision_id"])
                )
                if (
                    request.expected_decision_version != current_version
                    or request.expected_previous_decision_id != current_decision_id
                ):
                    raise RelationStaleDecision(
                        "relation decision is not pinned to exact current head"
                    )
                current_state = RelationCurrentState(str(head["current_state"]))
                previous_decision_id = current_decision_id
            self._require_transition(current_state, request.action)
            if request.action is RelationDecisionAction.ADMIT:
                if not self._proposal_matches_fixture_rule(conn, proposal):
                    raise RelationStateError(
                        "Increment 2A admits only the exact governed fixture rule"
                    )
                self._assert_fixture_objects_current(
                    conn, proposal, now=self._clock()
                )
            if request.action is RelationDecisionAction.SUPERSEDE:
                assert request.successor_proposal_id is not None
                self._require_successor(
                    conn, proposal, request.successor_proposal_id
                )
            committed = self._commit_grant_in_transaction(
                conn, grant, recorded_at=recorded_at
            )
            decision_id = RelationAdmissionDecisionId.new()
            assertion_id = (
                RelationAssertionId.new()
                if request.action is RelationDecisionAction.ADMIT
                else None
            )
            decision_version = committed.aggregate_version
            decision_value = {
                "decision_id": str(decision_id),
                **request.canonical_value(),
                "decision_version": decision_version,
                "previous_decision_id": (
                    None
                    if previous_decision_id is None
                    else str(previous_decision_id)
                ),
                "assertion_id": (
                    None if assertion_id is None else str(assertion_id)
                ),
                "authority_event_id": committed.event_id,
                "authority_ledger_seq": committed.ledger_seq,
                "recorded_at": recorded_at,
            }
            decision_canonical = canonical_json_bytes(decision_value)
            conn.execute(
                "INSERT INTO relation_admission_decisions("
                "decision_id,proposal_id,decision_version,previous_decision_id,"
                "action,proposal_digest,reason_code,decision_policy_version,"
                "successor_proposal_id,assertion_id,authority_event_id,"
                "authority_ledger_seq,authority_aggregate_version,canonical_bytes,"
                "canonical_digest,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(decision_id),
                    str(request.proposal_id),
                    decision_version,
                    (
                        None
                        if previous_decision_id is None
                        else str(previous_decision_id)
                    ),
                    request.action.value,
                    request.expected_proposal_digest,
                    request.reason_code,
                    request.decision_policy_version,
                    (
                        None
                        if request.successor_proposal_id is None
                        else str(request.successor_proposal_id)
                    ),
                    None if assertion_id is None else str(assertion_id),
                    committed.event_id,
                    committed.ledger_seq,
                    committed.aggregate_version,
                    decision_canonical,
                    digest_bytes(decision_canonical),
                    recorded_at,
                ),
            )
            new_state = _STATE_BY_ACTION[request.action]
            if head is None:
                conn.execute(
                    "INSERT INTO relation_decision_heads("
                    "proposal_id,current_version,decision_id,current_state,updated_at) "
                    "VALUES(?,?,?,?,?)",
                    (
                        str(request.proposal_id),
                        decision_version,
                        str(decision_id),
                        new_state.value,
                        recorded_at,
                    ),
                )
            else:
                conn.execute(
                    "UPDATE relation_decision_heads SET current_version=?,"
                    "decision_id=?,current_state=?,updated_at=? WHERE proposal_id=?",
                    (
                        decision_version,
                        str(decision_id),
                        new_state.value,
                        recorded_at,
                        str(request.proposal_id),
                    ),
                )
            if assertion_id is not None:
                self._persist_assertion(
                    conn,
                    assertion_id=assertion_id,
                    decision_id=decision_id,
                    proposal=proposal,
                    admitted_at=recorded_at,
                )
            return self._decision_for_event(
                conn, committed.event_id, replayed=False
            )

    @classmethod
    def _relation_key(cls, proposal: RelationProposal) -> str:
        return governed_relation_key(
            fixture_binding_id=proposal.fixture_binding_id,
            subject=proposal.subject,
            predicate=proposal.predicate,
            object=proposal.object,
            temporal_scope=proposal.temporal_scope,
        )

    @classmethod
    def _persist_assertion(
        cls,
        conn: sqlite3.Connection,
        *,
        assertion_id: RelationAssertionId,
        decision_id: RelationAdmissionDecisionId,
        proposal: RelationProposal,
        admitted_at: str,
    ) -> None:
        evidence = conn.execute(
            "SELECT * FROM relation_proposal_evidence WHERE proposal_id=? "
            "ORDER BY passage_id",
            (str(proposal.proposal_id),),
        ).fetchall()
        evidence_objects = tuple(
            FixturePassageObject(
                passage_id=str(row["passage_id"]),
                admission_id=ObjectAdmissionId.parse(str(row["admission_id"])),
                blob_digest=str(row["blob_digest"]),
            )
            for row in evidence
        )
        assertion = RelationAssertion(
            assertion_id=assertion_id,
            proposal_id=proposal.proposal_id,
            admission_decision_id=decision_id,
            subject=proposal.subject,
            predicate=proposal.predicate,
            object=proposal.object,
            temporal_scope=proposal.temporal_scope,
            evidence_objects=evidence_objects,
            producer=proposal.producer,
            statement=proposal.statement,
            uncertainties=proposal.uncertainties,
            proposal_digest=proposal.proposal_digest,
            relation_key=cls._relation_key(proposal),
            admitted_at=UtcTimestamp.parse(admitted_at),
        )
        canonical = canonical_json_bytes(assertion.canonical_value())
        conn.execute(
            "INSERT INTO relation_assertions("
            "assertion_id,proposal_id,admission_decision_id,relation_key,"
            "subject_type,subject_id,predicate,object_type,object_id,valid_from,"
            "valid_until,temporal_precision,producer_kind,producer_id,"
            "producer_version,rule_version,statement,uncertainties_bytes,"
            "trust_scope,proposal_digest,canonical_bytes,canonical_digest,admitted_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(assertion.assertion_id),
                str(assertion.proposal_id),
                str(assertion.admission_decision_id),
                assertion.relation_key,
                assertion.subject.record_type.value,
                assertion.subject.record_id,
                assertion.predicate.value,
                assertion.object.record_type.value,
                assertion.object.record_id,
                assertion.temporal_scope.valid_from.to_text(),
                (
                    None
                    if assertion.temporal_scope.valid_until is None
                    else assertion.temporal_scope.valid_until.to_text()
                ),
                assertion.temporal_scope.precision,
                assertion.producer.kind.value,
                assertion.producer.producer_id,
                assertion.producer.producer_version,
                assertion.producer.rule_version,
                assertion.statement,
                canonical_json_bytes(list(assertion.uncertainties)),
                "ADMITTED",
                assertion.proposal_digest,
                canonical,
                digest_bytes(canonical),
                admitted_at,
            ),
        )
        for row in evidence:
            value = {
                "assertion_id": str(assertion.assertion_id),
                "proposal_id": str(assertion.proposal_id),
                "fixture_binding_id": str(row["fixture_binding_id"]),
                "passage_id": str(row["passage_id"]),
                "admission_id": str(row["admission_id"]),
                "blob_digest": str(row["blob_digest"]),
            }
            evidence_canonical = canonical_json_bytes(value)
            conn.execute(
                "INSERT INTO relation_assertion_evidence("
                "assertion_id,proposal_id,fixture_binding_id,passage_id,"
                "admission_id,blob_digest,canonical_bytes,canonical_digest) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    str(assertion.assertion_id),
                    str(assertion.proposal_id),
                    str(row["fixture_binding_id"]),
                    str(row["passage_id"]),
                    str(row["admission_id"]),
                    str(row["blob_digest"]),
                    evidence_canonical,
                    digest_bytes(evidence_canonical),
                ),
            )

    @classmethod
    def _assertion_from_row(
        cls,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> RelationAssertion:
        value = cls._canonical_row_value(row, identity="relation assertion")
        evidence = conn.execute(
            "SELECT passage_id,admission_id,blob_digest "
            "FROM relation_assertion_evidence "
            "WHERE assertion_id=? ORDER BY passage_id",
            (str(row["assertion_id"]),),
        ).fetchall()
        temporal = value.get("temporal_scope")
        producer = value.get("producer")
        uncertainties = value.get("uncertainties")
        if not isinstance(temporal, dict) or not isinstance(producer, dict) or not isinstance(uncertainties, list):
            raise AuthorityPersistenceError("relation assertion canonical shape is invalid")
        return RelationAssertion(
            assertion_id=RelationAssertionId.parse(str(row["assertion_id"])),
            proposal_id=RelationProposalId.parse(str(row["proposal_id"])),
            admission_decision_id=RelationAdmissionDecisionId.parse(
                str(row["admission_decision_id"])
            ),
            subject=RelationEndpoint(
                RelationRecordType(str(row["subject_type"])),
                str(row["subject_id"]),
            ),
            predicate=RelationPredicate(str(row["predicate"])),
            object=RelationEndpoint(
                RelationRecordType(str(row["object_type"])),
                str(row["object_id"]),
            ),
            temporal_scope=RelationTemporalScope(
                UtcTimestamp.parse(str(row["valid_from"])),
                (
                    None
                    if row["valid_until"] is None
                    else UtcTimestamp.parse(str(row["valid_until"]))
                ),
                str(row["temporal_precision"]),
            ),
            evidence_objects=tuple(
                FixturePassageObject(
                    passage_id=str(item["passage_id"]),
                    admission_id=ObjectAdmissionId.parse(
                        str(item["admission_id"])
                    ),
                    blob_digest=str(item["blob_digest"]),
                )
                for item in evidence
            ),
            producer=RelationProducer(
                RelationProducerKind(str(row["producer_kind"])),
                str(row["producer_id"]),
                str(row["producer_version"]),
                str(row["rule_version"]),
            ),
            statement=str(row["statement"]),
            uncertainties=tuple(str(item) for item in uncertainties),
            proposal_digest=str(row["proposal_digest"]),
            relation_key=str(row["relation_key"]),
            admitted_at=UtcTimestamp.parse(str(row["admitted_at"])),
        )

    @classmethod
    def _decision_from_row(
        cls,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        replayed: bool,
    ) -> RelationAdmissionDecision:
        cls._canonical_row_value(row, identity="relation admission decision")
        return RelationAdmissionDecision(
            decision_id=RelationAdmissionDecisionId.parse(str(row["decision_id"])),
            proposal_id=RelationProposalId.parse(str(row["proposal_id"])),
            action=RelationDecisionAction(str(row["action"])),
            decision_version=int(row["decision_version"]),
            previous_decision_id=(
                None
                if row["previous_decision_id"] is None
                else RelationAdmissionDecisionId.parse(
                    str(row["previous_decision_id"])
                )
            ),
            proposal_digest=str(row["proposal_digest"]),
            reason_code=str(row["reason_code"]),
            decision_policy_version=str(row["decision_policy_version"]),
            successor_proposal_id=(
                None
                if row["successor_proposal_id"] is None
                else RelationProposalId.parse(str(row["successor_proposal_id"]))
            ),
            assertion_id=(
                None
                if row["assertion_id"] is None
                else RelationAssertionId.parse(str(row["assertion_id"]))
            ),
            authority_event_id=EventId.parse(str(row["authority_event_id"])),
            authority_ledger_seq=int(row["authority_ledger_seq"]),
            recorded_at=UtcTimestamp.parse(str(row["recorded_at"])),
            replayed=replayed,
        )

    @classmethod
    def _decision_for_event(
        cls,
        conn: sqlite3.Connection,
        event_id: str,
        *,
        replayed: bool,
    ) -> RelationDecisionResult:
        row = conn.execute(
            "SELECT d.*,h.current_state FROM relation_admission_decisions d "
            "JOIN relation_decision_heads h ON h.proposal_id=d.proposal_id "
            "WHERE d.authority_event_id=?",
            (event_id,),
        ).fetchone()
        if row is None:
            raise AuthorityPersistenceError(
                "relation decision command lacks exact retained decision"
            )
        decision = cls._decision_from_row(conn, row, replayed=replayed)
        assertion = None
        if decision.assertion_id is not None:
            assertion_row = conn.execute(
                "SELECT * FROM relation_assertions WHERE assertion_id=?",
                (str(decision.assertion_id),),
            ).fetchone()
            if assertion_row is None:
                raise AuthorityPersistenceError(
                    "admission decision lacks immutable relation assertion"
                )
            assertion = cls._assertion_from_row(conn, assertion_row)
        return RelationDecisionResult(
            decision=decision,
            assertion=assertion,
            current_state=RelationCurrentState(str(row["current_state"])),
        )

    def relation_decision(
        self, decision_id: RelationAdmissionDecisionId
    ) -> RelationAdmissionDecision:
        if not isinstance(decision_id, RelationAdmissionDecisionId):
            raise TypeError("relation decision identity must be typed")
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM relation_admission_decisions WHERE decision_id=?",
                (str(decision_id),),
            ).fetchone()
            if row is None:
                raise KeyError(str(decision_id))
            return self._decision_from_row(
                self._connection, row, replayed=False
            )

    @classmethod
    def _assertion_object_state(
        cls,
        conn: sqlite3.Connection,
        assertion: RelationAssertion,
        *,
        now: UtcTimestamp,
    ) -> tuple[bool, str, tuple[int, EventId] | None, tuple[ObjectAdmissionId, ...]]:
        proposal = conn.execute(
            "SELECT fixture_binding_id FROM relation_proposals WHERE proposal_id=?",
            (str(assertion.proposal_id),),
        ).fetchone()
        if proposal is None:
            raise AuthorityPersistenceError("relation assertion proposal is missing")
        binding = conn.execute(
            "SELECT manifest_admission_id,manifest_blob_digest "
            "FROM integrated_fixture_v2_bindings WHERE binding_id=?",
            (str(proposal["fixture_binding_id"]),),
        ).fetchone()
        if binding is None:
            raise AuthorityPersistenceError("relation assertion binding is missing")
        references: list[tuple[ObjectAdmissionId, str]] = [
            (
                ObjectAdmissionId.parse(str(binding["manifest_admission_id"])),
                str(binding["manifest_blob_digest"]),
            )
        ]
        evidence = conn.execute(
            "SELECT admission_id,blob_digest FROM relation_assertion_evidence "
            "WHERE assertion_id=? ORDER BY passage_id",
            (str(assertion.assertion_id),),
        ).fetchall()
        references.extend(
            (
                ObjectAdmissionId.parse(str(row["admission_id"])),
                str(row["blob_digest"]),
            )
            for row in evidence
        )
        latest: tuple[int, EventId] | None = None
        latest_reason = "OBJECT_CURRENT"
        invalid_ids: list[ObjectAdmissionId] = []
        for admission_id, blob_digest in references:
            current, item_reason, event = cls._object_current_state(
                conn,
                str(admission_id),
                blob_digest,
                now=now,
            )
            if not current:
                invalid_ids.append(admission_id)
                if event is not None and (latest is None or event[0] > latest[0]):
                    latest = event
                    latest_reason = item_reason
        return (
            not invalid_ids,
            latest_reason,
            latest,
            tuple(sorted(invalid_ids, key=str)),
        )

    @staticmethod
    def _assertion_is_valid_at(
        assertion: RelationAssertion, valid_at: UtcTimestamp
    ) -> bool:
        if valid_at.value < assertion.temporal_scope.valid_from.value:
            return False
        valid_until = assertion.temporal_scope.valid_until
        return valid_until is None or valid_at.value < valid_until.value

    def admitted_assertions(
        self,
        *,
        now: UtcTimestamp,
        limit: int,
    ) -> tuple[RelationAssertion, ...]:
        if not isinstance(now, UtcTimestamp):
            raise TypeError("admitted relation read time must be typed")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0 or limit > 1000:
            raise ValueError("admitted relation read limit is invalid")
        with self._lock:
            retained: list[RelationAssertion] = []
            after_relation_key: str | None = None
            batch_size = min(max(limit * 2, 64), 1000)
            max_scan = min(
                max(limit * 16, 256),
                _MAX_RELATION_CURRENT_SCAN,
            )
            scanned = 0
            while len(retained) < limit:
                remaining_scan = max_scan - scanned
                page_limit = min(batch_size, remaining_scan + 1)
                if after_relation_key is None:
                    rows = self._connection.execute(
                        "SELECT a.* FROM relation_assertions a "
                        "JOIN relation_decision_heads h "
                        "ON h.proposal_id=a.proposal_id "
                        "WHERE h.current_state='ADMITTED' "
                        "ORDER BY a.relation_key LIMIT ?",
                        (page_limit,),
                    ).fetchall()
                else:
                    rows = self._connection.execute(
                        "SELECT a.* FROM relation_assertions a "
                        "JOIN relation_decision_heads h "
                        "ON h.proposal_id=a.proposal_id "
                        "WHERE h.current_state='ADMITTED' "
                        "AND a.relation_key>? "
                        "ORDER BY a.relation_key LIMIT ?",
                        (after_relation_key, page_limit),
                    ).fetchall()
                if not rows:
                    break
                if len(rows) > remaining_scan:
                    raise RelationStateError(
                        "admitted relation current-state scan exceeds its bound"
                    )
                scanned += len(rows)
                for row in rows:
                    after_relation_key = str(row["relation_key"])
                    assertion = self._assertion_from_row(
                        self._connection, row
                    )
                    current, _reason, _event, _ids = (
                        self._assertion_object_state(
                            self._connection,
                            assertion,
                            now=now,
                        )
                    )
                    if current and self._assertion_is_valid_at(assertion, now):
                        retained.append(assertion)
                        if len(retained) == limit:
                            break
                if len(rows) < page_limit:
                    break
            return tuple(retained)

    def projection_events_after(
        self,
        *,
        after_ledger_seq: int,
        now: UtcTimestamp,
        limit: int,
    ) -> tuple[RelationProjectionEvent, ...]:
        if (
            isinstance(after_ledger_seq, bool)
            or not isinstance(after_ledger_seq, int)
            or after_ledger_seq < 0
        ):
            raise ValueError("projection event cutoff must be non-negative")
        if not isinstance(now, UtcTimestamp):
            raise TypeError("projection event read time must be typed")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0 or limit > 2000:
            raise ValueError("projection event limit is invalid")
        with self._lock:
            max_scan = min(
                max(limit * 16, 256),
                _MAX_RELATION_CURRENT_SCAN,
            )
            assertions = self._connection.execute(
                "SELECT * FROM relation_assertions "
                "ORDER BY admitted_at,assertion_id LIMIT ?",
                (max_scan + 1,),
            ).fetchall()
            if len(assertions) > max_scan:
                raise RelationStateError(
                    "relation projection current-state scan exceeds its bound"
                )
            events: list[RelationProjectionEvent] = []
            for row in assertions:
                assertion = self._assertion_from_row(self._connection, row)
                admit_decision = self._connection.execute(
                    "SELECT * FROM relation_admission_decisions "
                    "WHERE decision_id=?",
                    (str(assertion.admission_decision_id),),
                ).fetchone()
                if admit_decision is None:
                    raise AuthorityPersistenceError(
                        "relation assertion admission decision is missing"
                    )
                admit_seq = int(admit_decision["authority_ledger_seq"])
                head = self._current_decision_head(
                    self._connection, str(assertion.proposal_id)
                )
                if head is None:
                    raise AuthorityPersistenceError(
                        "relation assertion lacks current decision head"
                    )
                current_state = RelationCurrentState(str(head["current_state"]))
                if current_state is not RelationCurrentState.ADMITTED:
                    remove_seq = int(head["authority_ledger_seq"])
                    if remove_seq > after_ledger_seq:
                        events.append(
                            RelationProjectionEvent(
                                action=RelationProjectionAction.REMOVE,
                                assertion_id=assertion.assertion_id,
                                relation_key=assertion.relation_key,
                                source_event_id=EventId.parse(
                                    str(head["authority_event_id"])
                                ),
                                source_ledger_seq=remove_seq,
                                reason_code=f"RELATION_{current_state.value}",
                                assertion=None,
                            )
                        )
                    continue
                current, reason, lifecycle_event, invalid_ids = self._assertion_object_state(
                    self._connection, assertion, now=now
                )
                if not current:
                    if lifecycle_event is None:
                        raise RelationStateError(
                            "invalid admitted relation lacks an ordered lifecycle event"
                        )
                    remove_seq, remove_event_id = lifecycle_event
                    if remove_seq > after_ledger_seq:
                        events.append(
                            RelationProjectionEvent(
                                action=RelationProjectionAction.REMOVE,
                                assertion_id=assertion.assertion_id,
                                relation_key=assertion.relation_key,
                                source_event_id=remove_event_id,
                                source_ledger_seq=remove_seq,
                                reason_code=reason,
                                assertion=None,
                                tombstone_object_admission_ids=invalid_ids,
                            )
                        )
                    # Historical admission remains immutable SQLite authority,
                    # but a current-state rebuild seam must never re-expose an
                    # assertion whose governed evidence is now unavailable.
                    continue
                if admit_seq > after_ledger_seq:
                    events.append(
                        RelationProjectionEvent(
                            action=RelationProjectionAction.UPSERT,
                            assertion_id=assertion.assertion_id,
                            relation_key=assertion.relation_key,
                            source_event_id=EventId.parse(
                                str(admit_decision["authority_event_id"])
                            ),
                            source_ledger_seq=admit_seq,
                            reason_code="RELATION_ADMITTED",
                            assertion=assertion,
                        )
                    )
            events.sort(
                key=lambda item: (
                    item.source_ledger_seq,
                    item.relation_key,
                    item.action.value,
                )
            )
            page: list[RelationProjectionEvent] = []
            index = 0
            while index < len(events):
                source_ledger_seq = events[index].source_ledger_seq
                end = index + 1
                while (
                    end < len(events)
                    and events[end].source_ledger_seq == source_ledger_seq
                ):
                    end += 1
                group = events[index:end]
                if len(group) > limit and not page:
                    raise RelationStateError(
                        "projection event limit would split one ledger sequence"
                    )
                if len(page) + len(group) > limit:
                    break
                page.extend(group)
                index = end
            return tuple(page)

    def _validate_relation_integrity(self) -> None:
        with self._lock:
            conn = self._connection
            for row in conn.execute(
                "SELECT * FROM integrated_fixture_v2_bindings"
            ).fetchall():
                self._validate_binding_row(conn, row)
            for row in conn.execute(
                "SELECT * FROM relation_proposals"
            ).fetchall():
                self._validate_proposal_row(conn, row)
            for row in conn.execute(
                "SELECT * FROM relation_admission_decisions "
                "ORDER BY proposal_id,decision_version"
            ).fetchall():
                self._validate_decision_row(conn, row)
            for row in conn.execute(
                "SELECT * FROM relation_assertions"
            ).fetchall():
                self._validate_assertion_row(conn, row)
            self._validate_decision_heads(conn)

    @classmethod
    def _validate_binding_row(
        cls, conn: sqlite3.Connection, row: sqlite3.Row
    ) -> None:
        value = cls._canonical_row_value(row, identity="integrated fixture v2 binding")
        binding_event = cls._event_row(conn, str(row["authority_event_id"]))
        binding_ledger_seq = int(binding_event["ledger_seq"])
        passages = conn.execute(
            "SELECT * FROM integrated_fixture_v2_passage_objects "
            "WHERE binding_id=? ORDER BY passage_id",
            (str(row["binding_id"]),),
        ).fetchall()
        expected_passages = INTEGRATED_FIXTURE_V2.passage_by_id
        if len(passages) != len(expected_passages):
            raise AuthorityPersistenceError(
                "fixture binding does not retain every repository passage"
            )
        passage_values: list[dict[str, str]] = []
        for passage_row in passages:
            passage_value = cls._canonical_row_value(
                passage_row, identity="integrated fixture v2 passage"
            )
            passage_id = str(passage_row["passage_id"])
            expected = expected_passages.get(passage_id)
            if expected is None:
                raise AuthorityPersistenceError(
                    "fixture binding contains unknown passage"
                )
            immutable = cls._immutable_object_reference(
                conn,
                str(passage_row["admission_id"]),
                str(passage_row["blob_digest"]),
            )
            lifecycle_value = passage_value.get("bound_lifecycle")
            if not isinstance(lifecycle_value, dict):
                raise AuthorityPersistenceError(
                    "fixture passage lacks lifecycle linkage"
                )
            try:
                lifecycle_link = FixturePassageLifecycleLink(
                    passage_id=str(lifecycle_value["passage_id"]),
                    expected_lifecycle=str(
                        lifecycle_value["expected_lifecycle"]
                    ),
                    authority_event_id=EventId.parse(
                        str(lifecycle_value["authority_event_id"])
                    ),
                    authority_ledger_seq=int(
                        lifecycle_value["authority_ledger_seq"]
                    ),
                    recorded_at=UtcTimestamp.parse(
                        str(lifecycle_value["recorded_at"])
                    ),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise AuthorityPersistenceError(
                    "fixture passage lifecycle linkage is malformed"
                ) from exc
            cls._validate_fixture_passage_lifecycle_link(
                conn,
                admission_id=str(passage_row["admission_id"]),
                blob_digest=str(passage_row["blob_digest"]),
                link=lifecycle_link,
                binding_ledger_seq=binding_ledger_seq,
            )
            stored_revision_id = (
                None
                if passage_row["revision_id"] is None
                else str(passage_row["revision_id"])
            )
            if (
                str(passage_row["blob_digest"]) != expected.blob_digest
                or str(immutable["blob_digest"]) != expected.blob_digest
                or immutable["valid_until"] is not None
                or immutable["rights_valid_until"] is not None
                or stored_revision_id != expected.revision_id
                or str(passage_row["language"]) != expected.language
                or str(passage_row["expected_lifecycle"])
                != expected.expected_lifecycle
                or bool(passage_row["eligible_for_relation_evidence"])
                != expected.eligible_for_relation_evidence
                or passage_value.get("passage_id") != passage_id
                or passage_value.get("admission_id")
                != str(passage_row["admission_id"])
                or passage_value.get("blob_digest")
                != str(passage_row["blob_digest"])
                or passage_value.get("revision_id") != expected.revision_id
                or passage_value.get("language") != expected.language
                or passage_value.get("expected_lifecycle")
                != expected.expected_lifecycle
                or passage_value.get("eligible_for_relation_evidence")
                != expected.eligible_for_relation_evidence
                or lifecycle_link.passage_id != passage_id
                or lifecycle_link.expected_lifecycle
                != expected.expected_lifecycle
            ):
                raise AuthorityPersistenceError(
                    "fixture passage differs from repository authority"
                )
            passage_values.append(
                {
                    "passage_id": passage_id,
                    "admission_id": str(passage_row["admission_id"]),
                    "blob_digest": str(passage_row["blob_digest"]),
                }
            )
        fixture = INTEGRATED_FIXTURE_V2
        expected_value = {
            "binding_id": str(row["binding_id"]),
            "fixture_id": fixture.fixture_id,
            "schema_version": fixture.schema_version,
            "fixture_digest": fixture.manifest_digest,
            "manifest_admission_id": str(row["manifest_admission_id"]),
            "manifest_blob_digest": fixture.manifest_digest,
            "passage_objects": passage_values,
        }
        manifest = cls._immutable_object_reference(
            conn,
            str(row["manifest_admission_id"]),
            str(row["manifest_blob_digest"]),
        )
        if (
            value != expected_value
            or str(row["fixture_id"]) != fixture.fixture_id
            or str(row["schema_version"]) != fixture.schema_version
            or str(row["fixture_digest"]) != fixture.manifest_digest
            or str(row["manifest_blob_digest"]) != fixture.manifest_digest
            or manifest["valid_until"] is not None
            or manifest["rights_valid_until"] is not None
        ):
            raise AuthorityPersistenceError(
                "fixture binding differs from repository integrated_fixture_v2"
            )
        cls._validate_event(
            conn,
            event_id=str(row["authority_event_id"]),
            event_type="integrated.fixture.v2.bound",
            aggregate_type="integrated_fixture_v2_binding",
            aggregate_id=str(row["binding_id"]),
            aggregate_version=int(row["authority_aggregate_version"]),
            payload_digest=str(row["canonical_digest"]),
            trust_scope="OBSERVED",
            recorded_at=str(row["recorded_at"]),
        )
        if binding_ledger_seq != cls._event_ledger_seq(
            conn, str(row["authority_event_id"])
        ):
            raise AuthorityPersistenceError(
                "fixture binding ledger sequence is inconsistent"
            )

    @classmethod
    def _validate_proposal_row(
        cls, conn: sqlite3.Connection, row: sqlite3.Row
    ) -> None:
        proposal = cls._proposal_from_row(conn, row, replayed=False)
        value = cls._canonical_row_value(row, identity="relation proposal")
        evidence_rows = conn.execute(
            "SELECT * FROM relation_proposal_evidence WHERE proposal_id=? "
            "ORDER BY passage_id",
            (str(proposal.proposal_id),),
        ).fetchall()
        if tuple(str(item["passage_id"]) for item in evidence_rows) != proposal.evidence_passage_ids:
            raise AuthorityPersistenceError(
                "relation proposal evidence differs from canonical proposal"
            )
        for item in evidence_rows:
            evidence_value = cls._canonical_row_value(
                item, identity="relation proposal evidence"
            )
            expected = {
                "proposal_id": str(proposal.proposal_id),
                "fixture_binding_id": str(proposal.fixture_binding_id),
                "passage_id": str(item["passage_id"]),
                "admission_id": str(item["admission_id"]),
                "blob_digest": str(item["blob_digest"]),
            }
            binding = conn.execute(
                "SELECT admission_id,blob_digest FROM "
                "integrated_fixture_v2_passage_objects "
                "WHERE binding_id=? AND passage_id=?",
                (str(proposal.fixture_binding_id), str(item["passage_id"])),
            ).fetchone()
            if (
                evidence_value != expected
                or binding is None
                or str(binding["admission_id"]) != str(item["admission_id"])
                or str(binding["blob_digest"]) != str(item["blob_digest"])
            ):
                raise AuthorityPersistenceError(
                    "relation proposal evidence cross-record identity is inconsistent"
                )
        request_value = value.copy()
        if (
            value != proposal.canonical_value()
            or
            proposal.proposal_digest != digest_canonical(request_value)
            or proposal.proposal_digest != str(row["canonical_digest"])
        ):
            raise AuthorityPersistenceError(
                "relation proposal digest differs from canonical bytes"
            )
        identity_value = value.copy()
        identity_value.pop("proposal_id")
        expected_slot = digest_canonical(
            {
                "subject": value["subject"],
                "predicate": value["predicate"],
                "object": value["object"],
                "temporal_scope": value["temporal_scope"],
            }
        )
        if (
            digest_canonical(identity_value) != str(row["semantic_identity_digest"])
            or expected_slot != str(row["semantic_slot_digest"])
            or str(row["trust_scope"]) != "PROPOSED"
        ):
            raise AuthorityPersistenceError(
                "relation proposal semantic identity is inconsistent"
            )
        cls._validate_event(
            conn,
            event_id=str(row["authority_event_id"]),
            event_type="relation.proposal.recorded",
            aggregate_type="relation_proposal",
            aggregate_id=str(row["proposal_id"]),
            aggregate_version=int(row["authority_aggregate_version"]),
            payload_digest=str(row["canonical_digest"]),
            trust_scope="PROPOSED",
            recorded_at=str(row["recorded_at"]),
        )
        event = cls._event_row(conn, str(row["authority_event_id"]))
        binding = conn.execute(
            "SELECT authority_event_id FROM integrated_fixture_v2_bindings "
            "WHERE binding_id=?",
            (str(proposal.fixture_binding_id),),
        ).fetchone()
        if (
            int(event["ledger_seq"]) != int(row["authority_ledger_seq"])
            or binding is None
            or cls._event_ledger_seq(
                conn, str(binding["authority_event_id"])
            ) >= int(event["ledger_seq"])
        ):
            raise AuthorityPersistenceError(
                "relation proposal ledger sequence or binding order is inconsistent"
            )

    @classmethod
    def _validate_decision_row(
        cls, conn: sqlite3.Connection, row: sqlite3.Row
    ) -> None:
        decision = cls._decision_from_row(conn, row, replayed=False)
        value = cls._canonical_row_value(row, identity="relation admission decision")
        proposal_row = conn.execute(
            "SELECT * FROM relation_proposals WHERE proposal_id=?",
            (str(decision.proposal_id),),
        ).fetchone()
        if proposal_row is None:
            raise AuthorityPersistenceError(
                "relation decision proposal is missing"
            )
        proposal = cls._proposal_from_row(conn, proposal_row, replayed=False)
        if proposal.proposal_digest != decision.proposal_digest:
            raise AuthorityPersistenceError(
                "relation decision proposal digest is inconsistent"
            )
        successor: RelationProposal | None = None
        if decision.action is RelationDecisionAction.SUPERSEDE:
            assert decision.successor_proposal_id is not None
            try:
                successor = cls._require_successor(
                    conn,
                    proposal,
                    decision.successor_proposal_id,
                )
            except RelationStateError as exc:
                raise AuthorityPersistenceError(
                    "relation supersession successor is inconsistent"
                ) from exc
        expected = {
            "decision_id": str(decision.decision_id),
            "proposal_id": str(decision.proposal_id),
            "action": decision.action.value,
            "expected_proposal_digest": decision.proposal_digest,
            "expected_decision_version": decision.decision_version - 1,
            "expected_previous_decision_id": (
                None
                if decision.previous_decision_id is None
                else str(decision.previous_decision_id)
            ),
            "reason_code": decision.reason_code,
            "decision_policy_version": decision.decision_policy_version,
            "successor_proposal_id": (
                None
                if decision.successor_proposal_id is None
                else str(decision.successor_proposal_id)
            ),
            "decision_version": decision.decision_version,
            "previous_decision_id": (
                None
                if decision.previous_decision_id is None
                else str(decision.previous_decision_id)
            ),
            "assertion_id": (
                None if decision.assertion_id is None else str(decision.assertion_id)
            ),
            "authority_event_id": str(decision.authority_event_id),
            "authority_ledger_seq": decision.authority_ledger_seq,
            "recorded_at": decision.recorded_at.to_text(),
        }
        if value != expected:
            raise AuthorityPersistenceError(
                "relation decision canonical evidence differs from columns"
            )
        previous = None
        prior_state: RelationCurrentState | None = None
        if decision.decision_version > 1:
            previous = conn.execute(
                "SELECT proposal_id,decision_version,authority_ledger_seq,action "
                "FROM relation_admission_decisions WHERE decision_id=?",
                (str(decision.previous_decision_id),),
            ).fetchone()
            if (
                previous is None
                or str(previous["proposal_id"]) != str(decision.proposal_id)
                or int(previous["decision_version"]) != decision.decision_version - 1
            ):
                raise AuthorityPersistenceError(
                    "relation decision predecessor chain is inconsistent"
                )
            prior_state = _STATE_BY_ACTION[
                RelationDecisionAction(str(previous["action"]))
            ]
        try:
            cls._require_transition(prior_state, decision.action)
        except RelationStateError as exc:
            raise AuthorityPersistenceError(
                "relation decision transition history is inconsistent"
            ) from exc
        event = cls._validate_event(
            conn,
            event_id=str(row["authority_event_id"]),
            event_type="relation.admission.decided",
            aggregate_type="relation_admission",
            aggregate_id=str(row["proposal_id"]),
            aggregate_version=int(row["authority_aggregate_version"]),
            payload_digest=digest_canonical(
                {
                    "proposal_id": str(decision.proposal_id),
                    "action": decision.action.value,
                    "expected_proposal_digest": decision.proposal_digest,
                    "expected_decision_version": decision.decision_version - 1,
                    "expected_previous_decision_id": (
                        None
                        if decision.previous_decision_id is None
                        else str(decision.previous_decision_id)
                    ),
                    "reason_code": decision.reason_code,
                    "decision_policy_version": decision.decision_policy_version,
                    "successor_proposal_id": (
                        None
                        if decision.successor_proposal_id is None
                        else str(decision.successor_proposal_id)
                    ),
                }
            ),
            trust_scope="ADMITTED",
            recorded_at=str(row["recorded_at"]),
        )
        event_ledger_seq = int(event["ledger_seq"])
        if (
            event_ledger_seq != decision.authority_ledger_seq
            or proposal.authority_ledger_seq >= event_ledger_seq
            or (
                previous is not None
                and int(previous["authority_ledger_seq"]) >= event_ledger_seq
            )
            or (
                successor is not None
                and successor.authority_ledger_seq >= event_ledger_seq
            )
        ):
            raise AuthorityPersistenceError(
                "relation decision ledger sequence or causal ordering is inconsistent"
            )
        if int(row["authority_aggregate_version"]) != decision.decision_version:
            raise AuthorityPersistenceError(
                "relation decision aggregate version is inconsistent"
            )

    @classmethod
    def _validate_assertion_row(
        cls, conn: sqlite3.Connection, row: sqlite3.Row
    ) -> None:
        assertion = cls._assertion_from_row(conn, row)
        value = cls._canonical_row_value(row, identity="relation assertion")
        proposal_row = conn.execute(
            "SELECT * FROM relation_proposals WHERE proposal_id=?",
            (str(assertion.proposal_id),),
        ).fetchone()
        decision = conn.execute(
            "SELECT action,assertion_id,proposal_id,recorded_at "
            "FROM relation_admission_decisions WHERE decision_id=?",
            (str(assertion.admission_decision_id),),
        ).fetchone()
        if proposal_row is None or decision is None:
            raise AuthorityPersistenceError(
                "relation assertion lacks proposal or decision authority"
            )
        proposal = cls._proposal_from_row(conn, proposal_row, replayed=False)
        if str(decision["recorded_at"]) != assertion.admitted_at.to_text():
            raise AuthorityPersistenceError(
                "relation assertion admission time differs from its decision"
            )
        if (
            value != assertion.canonical_value()
            or str(decision["action"]) != "ADMIT"
            or str(decision["assertion_id"]) != str(assertion.assertion_id)
            or str(decision["proposal_id"]) != str(assertion.proposal_id)
            or assertion.subject != proposal.subject
            or assertion.predicate is not proposal.predicate
            or assertion.object != proposal.object
            or assertion.temporal_scope != proposal.temporal_scope
            or assertion.producer != proposal.producer
            or assertion.statement != proposal.statement
            or assertion.uncertainties != proposal.uncertainties
            or assertion.proposal_digest != proposal.proposal_digest
            or assertion.relation_key != cls._relation_key(proposal)
        ):
            raise AuthorityPersistenceError(
                "relation assertion differs from admitted proposal authority"
            )
        evidence = conn.execute(
            "SELECT * FROM relation_assertion_evidence WHERE assertion_id=? "
            "ORDER BY passage_id",
            (str(assertion.assertion_id),),
        ).fetchall()
        if tuple(str(item["passage_id"]) for item in evidence) != assertion.evidence_passage_ids:
            raise AuthorityPersistenceError(
                "relation assertion evidence differs from canonical assertion"
            )
        for item in evidence:
            value = cls._canonical_row_value(
                item, identity="relation assertion evidence"
            )
            expected = {
                "assertion_id": str(assertion.assertion_id),
                "proposal_id": str(assertion.proposal_id),
                "fixture_binding_id": str(item["fixture_binding_id"]),
                "passage_id": str(item["passage_id"]),
                "admission_id": str(item["admission_id"]),
                "blob_digest": str(item["blob_digest"]),
            }
            proposal_evidence = conn.execute(
                "SELECT admission_id,blob_digest,fixture_binding_id "
                "FROM relation_proposal_evidence "
                "WHERE proposal_id=? AND passage_id=?",
                (str(assertion.proposal_id), str(item["passage_id"])),
            ).fetchone()
            if (
                value != expected
                or proposal_evidence is None
                or str(proposal_evidence["admission_id"])
                != str(item["admission_id"])
                or str(proposal_evidence["blob_digest"])
                != str(item["blob_digest"])
                or str(proposal_evidence["fixture_binding_id"])
                != str(item["fixture_binding_id"])
            ):
                raise AuthorityPersistenceError(
                    "relation assertion evidence cross-record identity is inconsistent"
                )

    @classmethod
    def _validate_decision_heads(cls, conn: sqlite3.Connection) -> None:
        proposals = conn.execute(
            "SELECT proposal_id FROM relation_proposals"
        ).fetchall()
        for proposal in proposals:
            proposal_id = str(proposal["proposal_id"])
            decisions = conn.execute(
                "SELECT * FROM relation_admission_decisions WHERE proposal_id=? "
                "ORDER BY decision_version",
                (proposal_id,),
            ).fetchall()
            head = conn.execute(
                "SELECT * FROM relation_decision_heads WHERE proposal_id=?",
                (proposal_id,),
            ).fetchone()
            if not decisions:
                if head is not None:
                    raise AuthorityPersistenceError(
                        "undecided relation proposal has a decision head"
                    )
                continue
            latest = decisions[-1]
            if (
                head is None
                or int(head["current_version"]) != int(latest["decision_version"])
                or str(head["decision_id"]) != str(latest["decision_id"])
                or str(head["current_state"])
                != _STATE_BY_ACTION[
                    RelationDecisionAction(str(latest["action"]))
                ].value
                or str(head["updated_at"]) != str(latest["recorded_at"])
            ):
                raise AuthorityPersistenceError(
                    "relation decision head is inconsistent with immutable history"
                )


__all__ = ["_RelationAuthorityStore"]
