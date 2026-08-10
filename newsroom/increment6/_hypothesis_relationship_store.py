"""Private checked v22 Event Hypothesis relationship authority."""

from __future__ import annotations

import json
import sqlite3
import stat
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Self

from newsroom.authority._capability import _CapabilityIssuer
from newsroom.authority._event_store import _EventAuthorityStore
from newsroom.authority.auth import AuthenticationProof
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.models import InlinePayload, SemanticCommand
from newsroom.authority.persistence import AuthoritySchemaError
from newsroom.authority.policy import CommandRegistry, PayloadSchemaRegistry
from newsroom.authority.service import CommandService
from newsroom.authority.types import AggregateId, UtcTimestamp
from newsroom.increment6._hypothesis_store import _HypothesisStore
from newsroom.increment6.dispositions import ProposalDispositionStore
from newsroom.increment6.relationships import (
    RELATIONSHIP_AGGREGATE_TYPE,
    RELATIONSHIP_COMMAND_TYPE,
    RELATIONSHIP_EVENT_TYPE,
    AssessmentStatus,
    ComparatorEvidence,
    RelationshipAssessment,
    RelationshipContractError,
    merge_relationship_authority_registries,
    verify_relationship_assessment_replay,
)
from newsroom.increment6.work_items import RetrievalContextAuthority

_STORE_TOKEN = object()


def _evidence_bytes(values: tuple[bytes, ...]) -> tuple[bytes, tuple[bytes, ...]]:
    if type(values) is not tuple:
        raise RelationshipContractError("evidence must be an exact tuple")
    parsed = tuple(ComparatorEvidence.from_canonical_bytes(value) for value in values)
    canonical = tuple(value.canonical_bytes for value in parsed)
    if canonical != values:
        raise RelationshipContractError("evidence bytes differ from canonical values")
    return canonical_json_bytes([value.canonical_value for value in parsed]), canonical


def _decode_evidence(raw: bytes) -> tuple[bytes, ...]:
    try:
        value = json.loads(raw)
        if type(value) is not list or canonical_json_bytes(value) != raw:
            raise ValueError
        return tuple(
            ComparatorEvidence.from_value(item).canonical_bytes for item in value
        )
    except RelationshipContractError:
        raise
    except Exception as exc:
        raise RelationshipContractError("retained evidence differs") from exc


class _RelationshipEventStore(_EventAuthorityStore):
    """Existing event authority composed with the sole v22 relationship table."""

    def __init__(
        self,
        token: object,
        path: Path,
        *,
        issuer: _CapabilityIssuer,
        command_registry: CommandRegistry,
        payload_schemas: PayloadSchemaRegistry,
        retrieval_authority: RetrievalContextAuthority,
        authenticator: object,
        clock: Callable[[], UtcTimestamp],
        busy_timeout_ms: int,
    ) -> None:
        if token is not _STORE_TOKEN:
            raise RelationshipContractError(
                "relationship store construction is private"
            )
        super().__init__(
            path,
            issuer=issuer,
            command_registry=command_registry,
            payload_schemas=payload_schemas,
            command_service_version="increment6-relationship-v1",
            busy_timeout_ms=busy_timeout_ms,
            clock=clock,
        )
        with self._hypothesis_rows():
            self._hypotheses = _HypothesisStore(
                self._connection, retrieval_authority, authenticator, clock
            )
        self._command_service: CommandService | None = None
        with self._lock, self._transaction():
            self._adopt()
            try:
                self._verify_relationships()
            finally:
                self._release()

    def _acquire_writer_lock(self) -> None:
        lock_path = self.path.with_name(self.path.name + ".writer.lock")
        if lock_path.exists():
            self._validate_owned_file(lock_path)
            if stat.S_IMODE(lock_path.stat().st_mode) != 0o600:
                raise AuthoritySchemaError("writer lock mode differs")
        super()._acquire_writer_lock()

    def bind_command_service(self, service: CommandService) -> None:
        if self._command_service is not None or type(service) is not CommandService:
            raise RelationshipContractError("relationship command service differs")
        self._command_service = service

    def _service(self) -> CommandService:
        if self._command_service is None:
            raise RelationshipContractError("relationship command service is absent")
        return self._command_service

    @contextmanager
    def _hypothesis_rows(self):
        row_factory = self._connection.row_factory
        self._connection.row_factory = None
        try:
            yield
        finally:
            self._connection.row_factory = row_factory

    def _adopt(self) -> None:
        self._hypotheses.adopt_active_transaction()

    def _release(self) -> None:
        self._hypotheses.release_active_transaction()

    def _validate_relational_invariants(self, conn: sqlite3.Connection) -> None:
        super()._validate_relational_invariants(conn)
        if "event_hypothesis_relationship_decisions" not in self._table_names():
            return
        orphan = conn.execute(
            "SELECT r.decision_id FROM event_hypothesis_relationship_decisions r "
            "LEFT JOIN ledger_events e ON e.event_id=r.authority_event_id "
            "WHERE e.event_id IS NULL OR e.event_type!=? LIMIT 1",
            (RELATIONSHIP_EVENT_TYPE,),
        ).fetchone()
        uncovered = conn.execute(
            "SELECT e.event_id FROM ledger_events e LEFT JOIN "
            "event_hypothesis_relationship_decisions r "
            "ON r.authority_event_id=e.event_id WHERE e.event_type=? "
            "AND r.decision_id IS NULL LIMIT 1",
            (RELATIONSHIP_EVENT_TYPE,),
        ).fetchone()
        if orphan is not None or uncovered is not None:
            raise AuthoritySchemaError("relationship event coverage differs")

    @staticmethod
    def _actor_identity(row: sqlite3.Row) -> str:
        return digest_bytes(
            canonical_json_bytes(
                {
                    "principal_id": str(row["principal_id"]),
                    "credential_binding_digest": str(row["credential_binding_digest"]),
                }
            )
        )

    def _row(self, decision_id: str) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT r.*,e.event_type,e.event_schema_version,e.aggregate_type,"
            "e.aggregate_id,e.aggregate_version,e.recorded_at AS event_recorded_at,"
            "e.command_id,e.command_definition_version,e.command_definition_digest,"
            "c.command_type,c.expected_aggregate_version,c.idempotency_key,"
            "c.committed_at,p.payload_bytes,p.payload_digest,p.mode,p.schema_version,"
            "p.schema_contract_version,p.schema_contract_digest,"
            "p.canonicalizer_implementation_version,a.principal_id,"
            "a.credential_binding_digest FROM event_hypothesis_relationship_decisions r "
            "JOIN ledger_events e ON e.event_id=r.authority_event_id "
            "JOIN authority_commands c ON c.command_id=e.command_id "
            "JOIN authority_payloads p ON p.payload_id=e.payload_id "
            "JOIN authentication_contexts a ON a.authentication_context_id="
            "c.authentication_context_id WHERE r.decision_id=?",
            (decision_id,),
        ).fetchone()
        if row is None:
            raise RelationshipContractError("unknown relationship decision")
        return row

    def _load_row(self, decision_id: str) -> RelationshipAssessment:
        row = self._row(decision_id)
        assessment = RelationshipAssessment.from_canonical_bytes(
            bytes(row["assessment_bytes"])
        )
        evidence = _decode_evidence(bytes(row["evidence_bytes"]))
        with self._hypothesis_rows():
            subject = self._hypotheses.require_retained_version_in_transaction(
                str(row["subject_version_id"])
            )
            comparators = tuple(
                self._hypotheses.require_retained_version_in_transaction(item.version_id)
                for item in assessment.comparator_manifest.comparators
            )
        verified = verify_relationship_assessment_replay(
            assessment.canonical_bytes,
            subject_version=subject,
            comparator_versions=comparators,
            evidence=evidence,
        )
        selected = verified.comparator
        expected = {
            "decision_id": verified.canonical_digest,
            "subject_hypothesis_id": verified.subject.hypothesis_id,
            "subject_version_id": verified.subject.version_id,
            "subject_version_digest": verified.subject.version_digest,
            "comparator_manifest_bytes": verified.comparator_manifest.canonical_bytes,
            "comparator_manifest_digest": verified.comparator_manifest_digest,
            "selected_comparator_hypothesis_id": None
            if selected is None
            else selected.hypothesis_id,
            "selected_comparator_version_id": None
            if selected is None
            else selected.version_id,
            "selected_comparator_version_digest": None
            if selected is None
            else selected.version_digest,
            "decision": verified.decision.value,
            "assessment_bytes": verified.canonical_bytes,
            "assessment_digest": verified.canonical_digest,
            "evidence_digest": verified.evidence_digest,
        }
        if any(row[key] != value for key, value in expected.items()):
            raise RelationshipContractError("retained relationship decision differs")
        definition = self._command_registry.resolve(RELATIONSHIP_COMMAND_TYPE)
        contract = self._payload_schemas.resolve(
            definition.payload_schema_version, definition.payload_mode
        )
        if (
            str(row["event_type"]) != RELATIONSHIP_EVENT_TYPE
            or int(row["event_schema_version"]) != 1
            or str(row["aggregate_type"]) != RELATIONSHIP_AGGREGATE_TYPE
            or str(row["aggregate_id"]) != str(row["authority_aggregate_id"])
            or int(row["aggregate_version"]) != 1
            or str(row["command_type"]) != RELATIONSHIP_COMMAND_TYPE
            or int(row["expected_aggregate_version"]) != 0
            or str(row["idempotency_key"]) != verified.subject.version_id
            or bytes(row["payload_bytes"]) != verified.canonical_bytes
            or str(row["payload_digest"]) != verified.canonical_digest
            or str(row["command_definition_version"]) != definition.definition_version
            or str(row["command_definition_digest"]) != definition.digest
            or str(row["mode"]) != definition.payload_mode.value
            or str(row["schema_version"]) != contract.schema_version
            or str(row["schema_contract_version"]) != contract.contract_version
            or str(row["schema_contract_digest"]) != contract.contract_digest
            or str(row["canonicalizer_implementation_version"])
            != contract.canonicalizer_implementation_version
            or self._actor_identity(row) != str(row["actor_identity_digest"])
            or str(row["recorded_at"]) != str(row["event_recorded_at"])
            or str(row["recorded_at"]) != str(row["committed_at"])
            or digest_bytes(bytes(row["evidence_bytes"])) != verified.evidence_digest
        ):
            raise RelationshipContractError("relationship authority graph differs")
        UtcTimestamp.parse(str(row["recorded_at"]))
        return verified

    def _verify_relationships(self) -> None:
        with self._hypothesis_rows():
            self._hypotheses._verify()
        ids = [
            str(row[0])
            for row in self._connection.execute(
                "SELECT decision_id FROM event_hypothesis_relationship_decisions ORDER BY decision_id"
            )
        ]
        for decision_id in ids:
            self._load_row(decision_id)
        self._validate_relational_invariants(self._connection)

    @staticmethod
    def _command(
        assessment: RelationshipAssessment, aggregate_id: str
    ) -> SemanticCommand:
        return SemanticCommand(
            command_type=RELATIONSHIP_COMMAND_TYPE,
            aggregate_id=AggregateId.parse(aggregate_id),
            expected_aggregate_version=0,
            payload=InlinePayload(assessment.canonical_value),
            idempotency_key=assessment.subject.version_id,
        )

    def _retain_active(
        self,
        assessment_bytes: bytes,
        evidence: tuple[bytes, ...],
        *,
        proof: AuthenticationProof,
    ) -> RelationshipAssessment:
        assessment = RelationshipAssessment.from_canonical_bytes(assessment_bytes)
        if assessment.status is not AssessmentStatus.COMPLETE:
            raise RelationshipContractError(
                "only complete relationship assessments are authoritative"
            )
        stored_evidence, evidence_values = _evidence_bytes(evidence)
        conn = self._connection
        self._verify_relationships()
        existing = conn.execute(
            "SELECT decision_id,authority_aggregate_id,evidence_bytes,actor_identity_digest "
            "FROM event_hypothesis_relationship_decisions WHERE subject_version_id=?",
            (assessment.subject.version_id,),
        ).fetchone()
        aggregate_id = (
            str(AggregateId.new())
            if existing is None
            else str(existing["authority_aggregate_id"])
        )
        command = self._command(assessment, aggregate_id)
        grant = self._service()._authorize_for_commit(command, proof=proof)
        actor = ProposalDispositionStore._authenticated_identity(
            grant.authentication
        )
        if existing is not None:
            retained = self._load_row(str(existing["decision_id"]))
            if (
                retained.canonical_bytes != assessment_bytes
                or bytes(existing["evidence_bytes"]) != stored_evidence
                or str(existing["actor_identity_digest"]) != actor
            ):
                raise RelationshipContractError("relationship replay diverges")
            committed = self._commit_grant_in_transaction(
                conn,
                grant,
                recorded_at=str(
                    self._row(retained.canonical_digest)["recorded_at"]
                ),
            )
            if not committed.replayed or committed.event_id != str(
                self._row(retained.canonical_digest)["authority_event_id"]
            ):
                raise RelationshipContractError(
                    "relationship command replay differs"
                )
            return retained
        with self._hypothesis_rows():
            subject = self._hypotheses.require_current_version_in_transaction(
                assessment.subject.version_id, proof=proof
            )
            comparators = tuple(
                self._hypotheses.require_retained_version_in_transaction(
                    item.version_id
                )
                for item in assessment.comparator_manifest.comparators
            )
        verified = verify_relationship_assessment_replay(
            assessment_bytes,
            subject_version=subject,
            comparator_versions=comparators,
            evidence=evidence_values,
        )
        if verified.evidence_digest != digest_bytes(stored_evidence):
            raise RelationshipContractError("evidence-set identity differs")
        recorded_at = self._clock().to_text()
        committed = self._commit_grant_in_transaction(
            conn, grant, recorded_at=recorded_at
        )
        if committed.replayed:
            raise RelationshipContractError(
                "fresh relationship command replayed"
            )
        selected = verified.comparator
        conn.execute(
            "INSERT INTO event_hypothesis_relationship_decisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                verified.canonical_digest,
                aggregate_id,
                committed.event_id,
                verified.subject.hypothesis_id,
                verified.subject.version_id,
                verified.subject.version_digest,
                verified.comparator_manifest.canonical_bytes,
                verified.comparator_manifest_digest,
                None if selected is None else selected.hypothesis_id,
                None if selected is None else selected.version_id,
                None if selected is None else selected.version_digest,
                verified.decision.value,
                verified.canonical_bytes,
                verified.canonical_digest,
                stored_evidence,
                verified.evidence_digest,
                actor,
                recorded_at,
            ),
        )
        self._verify_relationships()
        return verified

    def retain(
        self,
        assessment_bytes: bytes,
        evidence: tuple[bytes, ...],
        *,
        proof: AuthenticationProof,
    ) -> RelationshipAssessment:
        with self._lock, self._transaction():
            self._adopt()
            try:
                return self._retain_active(
                    assessment_bytes, evidence, proof=proof
                )
            finally:
                self._release()

    create_or_replay = retain

    def _read(self, operation: Callable[[], object]) -> object:
        with self._lock, self._transaction():
            self._adopt()
            try:
                self._verify_relationships()
                return operation()
            finally:
                self._release()

    def load(self, decision_id: str) -> RelationshipAssessment:
        return self._read(lambda: self._load_row(decision_id))  # type: ignore[return-value]

    def history(self) -> tuple[RelationshipAssessment, ...]:
        def values() -> tuple[RelationshipAssessment, ...]:
            return tuple(
                self._load_row(str(row[0]))
                for row in self._connection.execute(
                    "SELECT decision_id FROM event_hypothesis_relationship_decisions ORDER BY recorded_at,decision_id"
                )
            )

        return self._read(values)  # type: ignore[return-value]

    def current(
        self, decision_id: str, *, proof: AuthenticationProof
    ) -> RelationshipAssessment:
        def value() -> RelationshipAssessment:
            retained = self._load_row(decision_id)
            with self._hypothesis_rows():
                self._hypotheses.require_current_version_in_transaction(
                    retained.subject.version_id, proof=proof
                )
            return retained

        return self._read(value)  # type: ignore[return-value]

    def rollback_scope(
        self, operation: Callable[[_RelationshipTransaction], None]
    ) -> None:
        try:
            with self._lock, self._transaction():
                self._adopt()
                try:
                    operation(_RelationshipTransaction(self))
                    raise _Rollback()
                finally:
                    self._release()
        except _Rollback:
            return


class _UnlockedRelationshipEventStoreForTest(_RelationshipEventStore):
    """Exact private test composition for exercising SQLite contention."""

    def _acquire_writer_lock(self) -> None:
        self._lock_fd = None


class _Rollback(Exception):
    pass


class _RelationshipTransaction:
    def __init__(self, store: _RelationshipEventStore) -> None:
        self._store = store

    def retain(self, *args: object, **kwargs: object) -> RelationshipAssessment:
        # rollback-scope conformance uses the same active implementation through a
        # specialised adapter; normal callers never receive this private scope.
        return self._store._retain_active(*args, **kwargs)  # type: ignore[arg-type,no-any-return]

    def load(self, decision_id: str) -> RelationshipAssessment:
        return self._store._load_row(decision_id)

    def history(self) -> tuple[RelationshipAssessment, ...]:
        return tuple(
            self._store._load_row(str(row[0]))
            for row in self._store._connection.execute(
                "SELECT decision_id FROM event_hypothesis_relationship_decisions ORDER BY recorded_at,decision_id"
            )
        )


class EventHypothesisRelationshipAuthority:
    __slots__ = ("__closed", "__store")

    def __init__(self, token: object, store: _RelationshipEventStore):
        if token is not _STORE_TOKEN or not isinstance(store, _RelationshipEventStore):
            raise RelationshipContractError(
                "relationship authority construction is private"
            )
        self.__store = store
        self.__closed = False

    def retain(self, *args: object, **kwargs: object) -> RelationshipAssessment:
        return self.__store.retain(*args, **kwargs)  # type: ignore[arg-type]

    create_or_replay = retain

    def load(self, decision_id: str) -> RelationshipAssessment:
        return self.__store.load(decision_id)

    def history(self) -> tuple[RelationshipAssessment, ...]:
        return self.__store.history()

    def current(
        self, decision_id: str, *, proof: AuthenticationProof
    ) -> RelationshipAssessment:
        return self.__store.current(decision_id, proof=proof)

    require_current = current

    def close(self) -> None:
        if not self.__closed:
            self.__closed = True
            self.__store.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _compose_relationship_authority(
    database: str | Path,
    *,
    retrieval_authority: RetrievalContextAuthority,
    authenticator: object,
    authorizer: object,
    command_registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
    clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
    busy_timeout_ms: int = 5000,
    unlocked_for_test: bool = False,
) -> EventHypothesisRelationshipAuthority:
    merged_commands, merged_schemas = merge_relationship_authority_registries(
        command_registry, payload_schemas
    )
    issuer = _CapabilityIssuer(
        command_registry=merged_commands, payload_schemas=merged_schemas
    )
    store_class = (
        _UnlockedRelationshipEventStoreForTest
        if unlocked_for_test
        else _RelationshipEventStore
    )
    store = store_class(
        _STORE_TOKEN,
        Path(database),
        issuer=issuer,
        command_registry=merged_commands,
        payload_schemas=merged_schemas,
        retrieval_authority=retrieval_authority,
        authenticator=authenticator,
        clock=clock,
        busy_timeout_ms=busy_timeout_ms,
    )
    service = CommandService(
        registry=merged_commands,
        payload_schemas=merged_schemas,
        authenticator=authenticator,
        authorizer=authorizer,
        committed_lookup=store,
        clock=clock,
        _issuer=issuer,
    )
    store.bind_command_service(service)
    return EventHypothesisRelationshipAuthority(_STORE_TOKEN, store)


def open_relationship_authority(
    database: str | Path,
    *,
    retrieval_authority: RetrievalContextAuthority,
    authenticator: object,
    authorizer: object,
    command_registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
    clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
    busy_timeout_ms: int = 5000,
) -> EventHypothesisRelationshipAuthority:
    """Construct the exact production relationship authority."""
    return _compose_relationship_authority(
        database,
        retrieval_authority=retrieval_authority,
        authenticator=authenticator,
        authorizer=authorizer,
        command_registry=command_registry,
        payload_schemas=payload_schemas,
        clock=clock,
        busy_timeout_ms=busy_timeout_ms,
    )


def _open_unlocked_relationship_authority_for_test(
    database: str | Path,
    *,
    retrieval_authority: RetrievalContextAuthority,
    authenticator: object,
    authorizer: object,
    command_registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
    clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
    busy_timeout_ms: int = 5000,
) -> EventHypothesisRelationshipAuthority:
    """Construct the exact private unlocked test store without a class hook."""
    return _compose_relationship_authority(
        database,
        retrieval_authority=retrieval_authority,
        authenticator=authenticator,
        authorizer=authorizer,
        command_registry=command_registry,
        payload_schemas=payload_schemas,
        clock=clock,
        busy_timeout_ms=busy_timeout_ms,
        unlocked_for_test=True,
    )


__all__: list[str] = []
