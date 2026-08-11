"""Private checked v23 Event Hypothesis lineage authority."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from newsroom.authority.auth import AuthenticationProof
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.models import InlinePayload, SemanticCommand
from newsroom.authority.persistence import AuthoritySchemaError
from newsroom.authority.policy import CommandRegistry, PayloadSchemaRegistry
from newsroom.authority.service import CommandService
from newsroom.authority.types import AggregateId, UtcTimestamp
from newsroom.increment6.lineage import (
    LINEAGE_AGGREGATE_TYPE,
    LINEAGE_COMMAND_TYPE,
    LINEAGE_EVENT_TYPE,
    EventHypothesisLineageAuthority,
    HypothesisLineageContractError,
    HypothesisLineageHead,
    HypothesisLineageReceipt,
    HypothesisLineageRelationshipProof,
    _compose_event_hypothesis_lineage_authority,
    lineage_command_definition,
    merge_lineage_authority_registries,
    replay_hypothesis_lineage,
)
from newsroom.increment6.relationships import (
    EventHypothesisRelationshipReadPort,
    merge_relationship_authority_registries,
)
from newsroom.increment6.work_items import RetrievalContextAuthority

from ._capability import _CapabilityIssuer
from ._event_hypothesis_relationship_system import (
    _create_event_hypothesis_relationship_read_port,
)
from ._event_store import _EventAuthorityStore

_TOKEN = object()
_LINEAGE_AGGREGATE_DOMAIN = b"newsroom.event-hypothesis-lineage.aggregate.v1"
_VERIFY_RETAINED_RELATIONSHIP_INTEGRITY = (
    EventHypothesisRelationshipReadPort.verify_retained_integrity_in_transaction
)


def _lineage_aggregate_id(lineage_id: str) -> AggregateId:
    digest = hashlib.sha256(
        _LINEAGE_AGGREGATE_DOMAIN + b"\0" + lineage_id.encode("ascii")
    ).digest()
    raw = bytearray(digest[:16])
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return AggregateId(UUID(bytes=bytes(raw)))


def _actor(authentication: object) -> str:
    try:
        principal_id = authentication.principal_id  # type: ignore[attr-defined]
        credential_binding_digest = authentication.credential_binding_digest  # type: ignore[attr-defined]
        if type(principal_id) is not str or type(credential_binding_digest) is not str:
            raise HypothesisLineageContractError(
                "lineage authenticated context differs"
            )
        return digest_bytes(
            canonical_json_bytes(
                {
                    "principal_id": principal_id,
                    "credential_binding_digest": credential_binding_digest,
                }
            )
        )
    except HypothesisLineageContractError:
        raise
    except Exception as exc:
        raise HypothesisLineageContractError(
            "lineage authenticated context differs"
        ) from exc


def _row_actor(row: sqlite3.Row) -> str:
    return digest_bytes(
        canonical_json_bytes(
            {
                "principal_id": str(row["principal_id"]),
                "credential_binding_digest": str(row["credential_binding_digest"]),
            }
        )
    )


def _exact_version(version: object, node: object) -> None:
    from newsroom.increment6.hypotheses import EventHypothesisVersion
    from newsroom.increment6.lineage import HypothesisLineageNodeBinding

    if (
        type(version) is not EventHypothesisVersion
        or type(node) is not HypothesisLineageNodeBinding
    ):
        raise HypothesisLineageContractError("lineage Version binding type differs")
    if (
        version.hypothesis_id != node.hypothesis_id
        or version.version_id != node.version_id
        or digest_bytes(version.canonical_bytes) != node.version_digest
    ):
        raise HypothesisLineageContractError("lineage Version binding differs")


class _LineageStore(_EventAuthorityStore):
    def __init__(
        self,
        token: object,
        path: Path,
        *,
        retrieval_authority: RetrievalContextAuthority,
        authenticator: object,
        authorizer: object,
        command_registry: CommandRegistry,
        payload_schemas: PayloadSchemaRegistry,
        clock: Callable[[], UtcTimestamp],
        busy_timeout_ms: int,
    ) -> None:
        if token is not _TOKEN:
            raise HypothesisLineageContractError(
                "lineage store construction is private"
            )
        relationship_commands, relationship_schemas = (
            merge_relationship_authority_registries(command_registry, payload_schemas)
        )
        merged_commands, merged_schemas = merge_lineage_authority_registries(
            relationship_commands, relationship_schemas
        )
        issuer = _CapabilityIssuer(
            command_registry=merged_commands, payload_schemas=merged_schemas
        )
        super().__init__(
            path,
            issuer=issuer,
            command_registry=merged_commands,
            payload_schemas=merged_schemas,
            command_service_version="increment6-lineage-v1",
            busy_timeout_ms=busy_timeout_ms,
            clock=clock,
        )
        try:
            self._port = _create_event_hypothesis_relationship_read_port(
                self._connection,
                retrieval_authority=retrieval_authority,
                authenticator=authenticator,
                command_registry=merged_commands,
                payload_schemas=merged_schemas,
                clock=clock,
            )
            if type(self._port) is not EventHypothesisRelationshipReadPort:
                raise HypothesisLineageContractError(
                    "lineage relationship port differs"
                )
            self._service = CommandService(
                registry=merged_commands,
                payload_schemas=merged_schemas,
                authenticator=authenticator,
                authorizer=authorizer,
                committed_lookup=self,
                clock=clock,
                _issuer=issuer,
            )
            with self._lock, self._transaction():
                self._verify()
        except BaseException:
            try:
                self.close()
            except BaseException:  # noqa: BLE001, S110 - preserve opening failure
                pass
            raise

    @staticmethod
    def _command(
        receipt: HypothesisLineageReceipt, aggregate_id: str
    ) -> SemanticCommand:
        return SemanticCommand(
            command_type=LINEAGE_COMMAND_TYPE,
            aggregate_id=AggregateId.parse(aggregate_id),
            expected_aggregate_version=0,
            payload=InlinePayload(receipt.canonical_value),
            idempotency_key=receipt.lineage_id,
        )

    def _row(self, lineage_id: str) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT l.*,e.event_type,e.event_schema_version,e.aggregate_type,"
            "e.aggregate_id,e.aggregate_version,e.recorded_at AS event_recorded_at,"
            "e.command_id,e.command_definition_version,e.command_definition_digest,"
            "c.command_type,c.aggregate_type AS command_aggregate_type,"
            "c.aggregate_id AS command_aggregate_id,c.expected_aggregate_version,"
            "c.idempotency_key,c.result_digest,c.result_bytes,c.committed_at,"
            "v.aggregate_type AS version_aggregate_type,"
            "v.aggregate_id AS version_aggregate_id,"
            "v.aggregate_version AS retained_aggregate_version,"
            "g.aggregate_type AS head_aggregate_type,"
            "g.aggregate_id AS head_aggregate_id,g.current_version,"
            "r.canonical_bytes AS request_bytes,p.payload_bytes,p.payload_digest,"
            "p.mode,p.schema_version,p.schema_contract_version,"
            "p.schema_contract_digest,p.canonicalizer_implementation_version,"
            "a.principal_id,a.credential_binding_digest "
            "FROM event_hypothesis_lineage l "
            "JOIN ledger_events e ON e.event_id=l.authority_event_id "
            "JOIN authority_commands c ON c.command_id=e.command_id "
            "JOIN authority_aggregate_versions v ON v.command_id=c.command_id "
            "JOIN authority_aggregates g ON g.aggregate_type=v.aggregate_type "
            "AND g.aggregate_id=v.aggregate_id "
            "JOIN authorization_requests r "
            "ON r.request_digest=c.authorization_request_digest "
            "JOIN authority_payloads p ON p.payload_id=e.payload_id "
            "JOIN authentication_contexts a ON a.authentication_context_id="
            "c.authentication_context_id WHERE l.lineage_id=?",
            (lineage_id,),
        ).fetchone()
        if row is None or type(row) is not sqlite3.Row:
            raise HypothesisLineageContractError("unknown lineage receipt")
        return row

    def _load_row(self, lineage_id: str) -> HypothesisLineageReceipt:
        row = self._row(lineage_id)
        receipt = HypothesisLineageReceipt.from_canonical_bytes(
            bytes(row["receipt_bytes"])
        )
        definition = lineage_command_definition()
        contract = self._payload_schemas.resolve(
            definition.payload_schema_version, definition.payload_mode
        )
        aggregate_id = str(_lineage_aggregate_id(receipt.lineage_id))
        result = self._decode_result(
            bytes(row["result_bytes"]), str(row["result_digest"]), replayed=False
        )
        request = self._decode_canonical(bytes(row["request_bytes"]))
        target = receipt.reversal_target
        expected = {
            "lineage_id": receipt.lineage_id,
            "kind": receipt.kind.value,
            "expected_generation": receipt.expected_generation,
            "receipt_digest": receipt.canonical_digest,
            "reversal_target_lineage_id": None if target is None else target.lineage_id,
            "reversal_target_lineage_digest": None
            if target is None
            else target.lineage_digest,
        }
        if any(row[key] != value for key, value in expected.items()):
            raise HypothesisLineageContractError("retained lineage scalars differ")
        if (
            str(row["event_type"]) != LINEAGE_EVENT_TYPE
            or int(row["event_schema_version"]) != 1
            or str(row["aggregate_type"]) != LINEAGE_AGGREGATE_TYPE
            or any(
                str(row[key]) != aggregate_id
                for key in (
                    "authority_aggregate_id",
                    "aggregate_id",
                    "command_aggregate_id",
                    "version_aggregate_id",
                    "head_aggregate_id",
                )
            )
            or any(
                str(row[key]) != LINEAGE_AGGREGATE_TYPE
                for key in (
                    "command_aggregate_type",
                    "version_aggregate_type",
                    "head_aggregate_type",
                )
            )
            or int(row["aggregate_version"]) != 1
            or int(row["retained_aggregate_version"]) != 1
            or int(row["current_version"]) != 1
            or result.aggregate_id != aggregate_id
            or not isinstance(request, dict)
            or request.get("aggregate_id") != aggregate_id
            or str(row["command_type"]) != LINEAGE_COMMAND_TYPE
            or int(row["expected_aggregate_version"]) != 0
            or str(row["idempotency_key"]) != receipt.lineage_id
            or bytes(row["payload_bytes"]) != receipt.canonical_bytes
            or str(row["payload_digest"]) != receipt.canonical_digest
            or str(row["command_definition_version"]) != definition.definition_version
            or str(row["command_definition_digest"]) != definition.digest
            or str(row["mode"]) != definition.payload_mode.value
            or str(row["schema_version"]) != contract.schema_version
            or str(row["schema_contract_version"]) != contract.contract_version
            or str(row["schema_contract_digest"]) != contract.contract_digest
            or str(row["canonicalizer_implementation_version"])
            != contract.canonicalizer_implementation_version
            or _row_actor(row) != str(row["actor_identity_digest"])
            or str(row["recorded_at"]) != str(row["event_recorded_at"])
            or str(row["recorded_at"]) != str(row["committed_at"])
        ):
            raise HypothesisLineageContractError("lineage authority graph differs")
        UtcTimestamp.parse(str(row["recorded_at"]))
        return receipt

    def _full_replay(self, receipts: tuple[HypothesisLineageReceipt, ...]):
        nodes = {
            node.version_id: node
            for receipt in receipts
            for node in (*receipt.inputs, *receipt.outputs)
        }
        versions = []
        for version_id in sorted(nodes):
            version = self._port.require_retained_version_in_transaction(version_id)
            _exact_version(version, nodes[version_id])
            versions.append(version)
        proofs = []
        for digest in sorted(
            {
                binding.assessment_digest
                for receipt in receipts
                for binding in receipt.relationships
            }
        ):
            retained = self._port.require_retained_receipt_in_transaction(digest)
            proofs.append(
                HypothesisLineageRelationshipProof.from_assessment(
                    retained.assessment, retained.evidence
                )
            )
        output_ids = {
            node.version_id for receipt in receipts for node in receipt.outputs
        }
        roots = tuple(
            HypothesisLineageHead(nodes[version_id], 0)
            for version_id in sorted(
                {node.version_id for receipt in receipts for node in receipt.inputs}
                - output_ids
            )
        )
        return replay_hypothesis_lineage(
            receipts,
            initial_heads=roots,
            versions=tuple(versions),
            relationship_proofs=tuple(proofs),
        )

    def _history_rows(self) -> tuple[HypothesisLineageReceipt, ...]:
        return tuple(
            self._load_row(str(row[0]))
            for row in self._connection.execute(
                "SELECT lineage_id FROM event_hypothesis_lineage ORDER BY expected_generation,lineage_id"
            )
        )

    def _verify(self) -> None:
        _VERIFY_RETAINED_RELATIONSHIP_INTEGRITY(self._port)
        self._validate_relational_invariants(self._connection)
        self._validate_immutable_records(self._connection)
        self._validate_registry_coverage(self._connection)
        orphan = self._connection.execute(
            "SELECT l.lineage_id FROM event_hypothesis_lineage l LEFT JOIN ledger_events e ON e.event_id=l.authority_event_id WHERE e.event_id IS NULL OR e.event_type!=? UNION ALL SELECT e.event_id FROM ledger_events e LEFT JOIN event_hypothesis_lineage l ON l.authority_event_id=e.event_id WHERE e.event_type=? AND l.lineage_id IS NULL LIMIT 1",
            (LINEAGE_EVENT_TYPE, LINEAGE_EVENT_TYPE),
        ).fetchone()
        if orphan is not None:
            raise AuthoritySchemaError("lineage event coverage differs")
        history = self._history_rows()
        replay = self._full_replay(history)
        verified = replay.history
        actual = tuple(
            (
                str(row["hypothesis_id"]),
                str(row["version_id"]),
                str(row["version_digest"]),
                int(row["generation"]),
                str(row["producing_lineage_id"]),
                str(row["updated_at"]),
            )
            for row in self._connection.execute(
                "SELECT * FROM event_hypothesis_lineage_heads ORDER BY hypothesis_id"
            )
        )
        producer = {
            node.version_id: (
                receipt.lineage_id,
                str(self._row(receipt.lineage_id)["recorded_at"]),
            )
            for receipt in verified
            for node in receipt.outputs
        }
        expected = tuple(
            sorted(
                (
                    head.node.hypothesis_id,
                    head.node.version_id,
                    head.node.version_digest,
                    head.generation,
                    producer[head.node.version_id][0],
                    producer[head.node.version_id][1],
                )
                for head in replay.active_heads
            )
        )
        if actual != expected:
            raise AuthoritySchemaError("lineage materialised heads differ")

    def _rebuild_heads(self, replay: object) -> None:
        from newsroom.increment6.lineage import HypothesisLineageReplay

        if type(replay) is not HypothesisLineageReplay:
            raise HypothesisLineageContractError("lineage replay type differs")
        producers = {
            node.version_id: (
                receipt.lineage_id,
                str(self._row(receipt.lineage_id)["recorded_at"]),
            )
            for receipt in replay.history
            for node in receipt.outputs
        }
        self._connection.execute("DELETE FROM event_hypothesis_lineage_heads")
        self._connection.executemany(
            "INSERT INTO event_hypothesis_lineage_heads VALUES(?,?,?,?,?,?)",
            [
                (
                    head.node.hypothesis_id,
                    head.node.version_id,
                    head.node.version_digest,
                    head.generation,
                    producers[head.node.version_id][0],
                    producers[head.node.version_id][1],
                )
                for head in replay.active_heads
            ],
        )

    def _retain_active(
        self, receipt_bytes: bytes, *, proof: AuthenticationProof
    ) -> HypothesisLineageReceipt:
        receipt = HypothesisLineageReceipt.from_canonical_bytes(receipt_bytes)
        self._verify()
        existing = self._connection.execute(
            "SELECT * FROM event_hypothesis_lineage WHERE lineage_id=?",
            (receipt.lineage_id,),
        ).fetchone()
        aggregate_id = str(_lineage_aggregate_id(receipt.lineage_id))
        command = self._command(receipt, aggregate_id)
        grant = self._service._authorize_for_commit(command, proof=proof)
        actor = _actor(grant.authentication)
        if existing is not None:
            retained = self._load_row(receipt.lineage_id)
            if retained.canonical_bytes != receipt_bytes or actor != str(
                existing["actor_identity_digest"]
            ):
                raise HypothesisLineageContractError("lineage replay diverges")
            committed = self._commit_grant_in_transaction(
                self._connection, grant, recorded_at=str(existing["recorded_at"])
            )
            if not committed.replayed or committed.event_id != str(
                existing["authority_event_id"]
            ):
                raise HypothesisLineageContractError("lineage command replay differs")
            return retained
        for node in (*receipt.inputs, *receipt.outputs):
            current = self._port.require_current_version_in_transaction(
                node.version_id, proof=proof
            )
            _exact_version(current, node)
        history = self._history_rows()
        replay = self._full_replay((*history, receipt))
        verified = replay.history[-1]
        recorded_at = self._clock().to_text()
        committed = self._commit_grant_in_transaction(
            self._connection, grant, recorded_at=recorded_at
        )
        if committed.replayed:
            raise HypothesisLineageContractError("fresh lineage command replayed")
        target = verified.reversal_target
        self._connection.execute(
            "INSERT INTO event_hypothesis_lineage VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                verified.lineage_id,
                aggregate_id,
                committed.event_id,
                verified.kind.value,
                verified.expected_generation,
                verified.canonical_bytes,
                verified.canonical_digest,
                None if target is None else target.lineage_id,
                None if target is None else target.lineage_digest,
                actor,
                recorded_at,
            ),
        )
        self._rebuild_heads(replay)
        self._verify()
        return verified

    def retain(
        self, receipt_bytes: bytes, *, proof: AuthenticationProof
    ) -> HypothesisLineageReceipt:
        with self._lock, self._transaction():
            return self._retain_active(receipt_bytes, proof=proof)

    create_or_replay = retain

    def load(self, lineage_id: str) -> HypothesisLineageReceipt:
        with self._lock, self._transaction():
            self._verify()
            retained = self._load_row(lineage_id)
            return next(
                item
                for item in self._full_replay(self._history_rows()).history
                if item.lineage_id == retained.lineage_id
            )

    def history(self) -> tuple[HypothesisLineageReceipt, ...]:
        with self._lock, self._transaction():
            self._verify()
            return self._history_rows()

    def current_heads(
        self, *, proof: AuthenticationProof
    ) -> tuple[HypothesisLineageHead, ...]:
        with self._lock, self._transaction():
            self._verify()
            replay = self._full_replay(self._history_rows())
            for head in replay.active_heads:
                current = self._port.require_current_version_in_transaction(
                    head.node.version_id, proof=proof
                )
                _exact_version(current, head.node)
            return replay.active_heads

    def rollback_scope(self, operation: Callable[[object], None]) -> None:
        try:
            with self._lock, self._transaction():
                self._verify()
                operation(_LineageTransaction(self))
                raise _Rollback()
        except _Rollback:
            return


class _Rollback(Exception):
    pass


class _LineageTransaction:
    def __init__(self, store: _LineageStore) -> None:
        self._store = store

    def retain(
        self, receipt_bytes: bytes, *, proof: AuthenticationProof
    ) -> HypothesisLineageReceipt:
        return self._store._retain_active(receipt_bytes, proof=proof)

    def load(self, lineage_id: str) -> HypothesisLineageReceipt:
        return self._store._load_row(lineage_id)

    def history(self) -> tuple[HypothesisLineageReceipt, ...]:
        return self._store._history_rows()


class _UnlockedLineageStore(_LineageStore):
    def _acquire_writer_lock(self) -> None:
        self._lock_fd = None


class _LineageAuthority:
    def __init__(self, token: object, store: _LineageStore) -> None:
        if token is not _TOKEN or not isinstance(store, _LineageStore):
            raise HypothesisLineageContractError(
                "lineage authority construction is private"
            )
        self._store = store

    def retain(self, *args: object, **kwargs: object) -> HypothesisLineageReceipt:
        return self._store.retain(*args, **kwargs)  # type: ignore[arg-type,no-any-return]

    create_or_replay = retain

    def load(self, lineage_id: str) -> HypothesisLineageReceipt:
        return self._store.load(lineage_id)

    def history(self) -> tuple[HypothesisLineageReceipt, ...]:
        return self._store.history()

    def current_heads(
        self, *, proof: AuthenticationProof
    ) -> tuple[HypothesisLineageHead, ...]:
        return self._store.current_heads(proof=proof)

    def close(self) -> None:
        self._store.close()

    def rollback_scope(self, operation: Callable[[object], None]) -> None:
        self._store.rollback_scope(operation)


def _open(
    database: str | Path,
    *,
    retrieval_authority: RetrievalContextAuthority,
    authenticator: object,
    authorizer: object,
    command_registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
    clock: Callable[[], UtcTimestamp],
    busy_timeout_ms: int,
    unlocked: bool,
) -> _LineageAuthority:
    store_type = _UnlockedLineageStore if unlocked else _LineageStore
    store = store_type(
        _TOKEN,
        Path(database),
        retrieval_authority=retrieval_authority,
        authenticator=authenticator,
        authorizer=authorizer,
        command_registry=command_registry,
        payload_schemas=payload_schemas,
        clock=clock,
        busy_timeout_ms=busy_timeout_ms,
    )
    return _LineageAuthority(_TOKEN, store)


def open_lineage_authority(
    database: str | Path,
    *,
    retrieval_authority: RetrievalContextAuthority,
    authenticator: object,
    authorizer: object,
    command_registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
    clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
    busy_timeout_ms: int = 5000,
) -> EventHypothesisLineageAuthority:
    raw = _open(
        database,
        retrieval_authority=retrieval_authority,
        authenticator=authenticator,
        authorizer=authorizer,
        command_registry=command_registry,
        payload_schemas=payload_schemas,
        clock=clock,
        busy_timeout_ms=busy_timeout_ms,
        unlocked=False,
    )
    try:
        return _compose_event_hypothesis_lineage_authority(raw)
    except BaseException:
        raw.close()
        raise


def _open_unlocked_lineage_authority_for_test(
    database: str | Path,
    *,
    retrieval_authority: RetrievalContextAuthority,
    authenticator: object,
    authorizer: object,
    command_registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
    clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
    busy_timeout_ms: int = 5000,
) -> _LineageAuthority:
    return _open(
        database,
        retrieval_authority=retrieval_authority,
        authenticator=authenticator,
        authorizer=authorizer,
        command_registry=command_registry,
        payload_schemas=payload_schemas,
        clock=clock,
        busy_timeout_ms=busy_timeout_ms,
        unlocked=True,
    )


__all__: list[str] = []
