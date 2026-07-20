from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import sqlite3

import pytest

from newsroom.authority import (
    AuthenticationError,
    AuthorityPersistenceError,
    AuthorizationDenied,
    AggregateId,
    CommandDefinition,
    CommandRegistry,
    IdempotencyIdentityConflict,
    ObjectAdmissionDenied,
    ObjectAdmissionDescriptor,
    ObjectAdmissionId,
    ObjectAdmissionPayload,
    ObjectIntegrityError,
    PayloadGoldenVector,
    PayloadMode,
    PayloadSchemaContract,
    PayloadSchemaRegistry,
    PayloadSchemaValidationError,
    SemanticCommand,
    StaticAuthenticator,
    StaticPrincipal,
    TrustScope,
    UtcTimestamp,
    canonical_json_bytes,
)

from .authority_a2b_helpers import MutableClock, admit, open_object_system
from .authority_event_helpers import payload_schemas, registry_v1
from .authority_helpers import FIXED_NOW, proof


def _object_reference_bytes(value: object) -> bytes:
    if not isinstance(value, ObjectAdmissionDescriptor):
        raise PayloadSchemaValidationError(
            "object-reference payload requires an admission descriptor"
        )
    return canonical_json_bytes(
        {
            "admission_id": str(value.admission_id),
            "blob_digest": value.blob_digest,
            "object_class": value.object_class,
            "allowed_use": value.allowed_use,
            "security_scope": value.security_scope,
            "retention_scope": value.retention_scope,
        }
    )


def _object_contract() -> PayloadSchemaContract:
    vector = ObjectAdmissionDescriptor(
        admission_id=ObjectAdmissionId.parse(
            "00000000-0000-4000-8000-000000000001"
        ),
        blob_digest="sha256:" + "a" * 64,
        object_class="source_capture",
        allowed_use="project.discovery",
        security_scope="authority.protected",
        retention_scope="source.short",
        active=True,
    )
    return PayloadSchemaContract(
        schema_version="governed_object_reference_v1",
        payload_mode=PayloadMode.OBJECT_ADMISSION,
        contract_version="governed-object-contract-v1",
        canonicalizer_implementation_version="governed-object-canonicalizer-v1",
        canonicalizer=_object_reference_bytes,
        golden_vectors=(
            PayloadGoldenVector(
                name="source-capture-reference",
                input_identity="source-capture-reference-v1",
                value=vector,
                expected_bytes=_object_reference_bytes(vector),
            ),
        ),
    )


def _object_definition(contract: PayloadSchemaContract) -> CommandDefinition:
    return CommandDefinition(
        command_type="record.object_observed",
        definition_version="object-command-v1",
        aggregate_type="fixture_object_record",
        event_type="fixture.object_observed.recorded",
        event_schema_version=1,
        payload_mode=PayloadMode.OBJECT_ADMISSION,
        payload_schema_version=contract.schema_version,
        payload_schema_contract_version=contract.contract_version,
        payload_schema_contract_digest=contract.contract_digest,
        payload_canonicalizer_version=(
            contract.canonicalizer_implementation_version
        ),
        trust_scope=TrustScope.OBSERVED,
        security_scope="authority.protected",
        retention_scope="source.short",
        required_scope="authority.observed.write",
        required_object_class="source_capture",
        required_allowed_use="project.discovery",
    )


def _registries() -> tuple[CommandRegistry, PayloadSchemaRegistry]:
    contract = _object_contract()
    return (
        CommandRegistry((*registry_v1().definitions(), _object_definition(contract))),
        PayloadSchemaRegistry((*payload_schemas().contracts(), contract)),
    )


def _command(admission_id: ObjectAdmissionId, *, key: str) -> SemanticCommand:
    return SemanticCommand(
        command_type="record.object_observed",
        aggregate_id=AggregateId.new(),
        expected_aggregate_version=0,
        payload=ObjectAdmissionPayload(admission_id),
        idempotency_key=key,
    )


def _installed_path(root: Path, digest: str) -> Path:
    value = digest.split(":", 1)[1]
    return root / "objects" / value[:2] / value


def test_object_backed_command_commits_admission_reference_without_copying_bytes(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    commands, schemas = _registries()
    system = open_object_system(
        database,
        object_root=object_root,
        command_registry=commands,
        payload_schema_registry=schemas,
    )
    command: SemanticCommand
    try:
        admission = admit(system, data=b"authoritative object payload").admission
        command = _command(admission.admission_id, key="object-command")
        committed = system.commands.execute(command, proof=proof())
        assert committed.replayed is False
    finally:
        system.close()

    reopened = open_object_system(
        database,
        object_root=object_root,
        command_registry=commands,
        payload_schema_registry=schemas,
    )
    try:
        replayed = reopened.commands.execute(command, proof=proof())
        assert replayed.replayed is True
        assert replayed.command_id == committed.command_id
        assert replayed.event_id == committed.event_id
        reopened.objects.revoke(
            admission.admission_id,
            reason_code="REVOKED_AFTER_COMMAND",
            idempotency_key="object-command-revoke",
            proof=proof(),
        )
        deletion = reopened.objects.request_deletion(
            admission.blob.blob_digest,
            reason_code="DELETE_AFTER_COMMAND",
            idempotency_key="object-command-delete",
            proof=proof(),
        )
        reopened.objects.tombstone(
            deletion.deletion_id,
            reason_code="TOMBSTONE_AFTER_COMMAND",
            idempotency_key="object-command-tombstone",
            proof=proof(),
        )
        reopened.objects.complete_deletion(
            deletion.deletion_id,
            idempotency_key="object-command-remove",
            proof=proof(),
        )
        replayed_after_delete = reopened.commands.execute(
            command, proof=proof()
        )
        assert replayed_after_delete.replayed is True
        assert replayed_after_delete.command_id == committed.command_id
        assert replayed_after_delete.event_id == committed.event_id
    finally:
        reopened.close()

    # Startup integrity must accept the immutable object reference after lawful
    # byte deletion, while the command's exact result remains replayable.
    reopened_after_delete = open_object_system(
        database,
        object_root=object_root,
        command_registry=commands,
        payload_schema_registry=schemas,
    )
    try:
        final_replay = reopened_after_delete.commands.execute(
            command, proof=proof()
        )
        assert final_replay.replayed is True
        assert final_replay.command_id == committed.command_id
    finally:
        reopened_after_delete.close()

    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    try:
        payload = conn.execute(
            "SELECT mode,payload_digest,payload_bytes,object_admission_id "
            "FROM authority_payloads WHERE object_admission_id=?",
            (str(admission.admission_id),),
        ).fetchone()
        assert payload is not None
        assert payload["mode"] == PayloadMode.OBJECT_ADMISSION.value
        assert payload["payload_digest"] == admission.blob.blob_digest
        assert payload["payload_bytes"] is None
        assert payload["object_admission_id"] == str(admission.admission_id)
        event = conn.execute(
            "SELECT payload_mode,payload_digest,object_admission_id "
            "FROM ledger_events WHERE event_id=?",
            (committed.event_id,),
        ).fetchone()
        assert event is not None
        assert event["payload_mode"] == PayloadMode.OBJECT_ADMISSION.value
        assert event["payload_digest"] == admission.blob.blob_digest
        assert event["object_admission_id"] == str(admission.admission_id)
    finally:
        conn.close()


def test_object_backed_command_rechecks_pinned_bytes_before_commit(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    commands, schemas = _registries()
    armed = False
    rehashes = 0

    def fault(checkpoint: str) -> None:
        nonlocal rehashes
        if not armed or checkpoint != "before_pinned_rehash":
            return
        rehashes += 1
        if rehashes != 2:
            return
        paths = [path for path in (object_root / "objects").rglob("*") if path.is_file()]
        assert len(paths) == 1
        path = paths[0]
        original = path.read_bytes()
        path.chmod(0o600)
        path.write_bytes(b"X" * len(original))

    system = open_object_system(
        database,
        object_root=object_root,
        command_registry=commands,
        payload_schema_registry=schemas,
        fault_hook=fault,
    )
    try:
        admission = admit(system, data=b"transaction recheck bytes").admission
        armed = True
        with pytest.raises(ObjectIntegrityError):
            system.commands.execute(
                _command(admission.admission_id, key="object-command-corrupt"),
                proof=proof(),
            )
        assert rehashes >= 2
        assert all(
            item.event_type != "fixture.object_observed.recorded"
            for item in system.events.after(0, limit=1000, proof=proof())
        )
    finally:
        system.close()


def test_revoked_admission_cannot_authorize_a_new_object_backed_command(
    tmp_path: Path,
) -> None:
    commands, schemas = _registries()
    system = open_object_system(
        tmp_path / "authority.sqlite3",
        command_registry=commands,
        payload_schema_registry=schemas,
    )
    try:
        admission = admit(system).admission
        system.objects.revoke(
            admission.admission_id,
            reason_code="REVOKED",
            idempotency_key="revoke-object-command",
            proof=proof(),
        )
        with pytest.raises(ObjectAdmissionDenied):
            system.commands.execute(
                _command(admission.admission_id, key="object-command-revoked"),
                proof=proof(),
            )
    finally:
        system.close()



def test_committed_object_command_replays_after_admission_revocation(
    tmp_path: Path,
) -> None:
    commands, schemas = _registries()
    system = open_object_system(
        tmp_path / "authority.sqlite3",
        command_registry=commands,
        payload_schema_registry=schemas,
    )
    try:
        admission = admit(system, data=b"replay after revoke").admission
        command = _command(admission.admission_id, key="object-replay-revoked")
        first = system.commands.execute(command, proof=proof())
        system.objects.revoke(
            admission.admission_id,
            reason_code="REVOKED_AFTER_COMMAND",
            idempotency_key="revoke-after-command",
            proof=proof(),
        )
        before = system.events.after(0, limit=1000, proof=proof())
        replay = system.commands.execute(command, proof=proof())
        after = system.events.after(0, limit=1000, proof=proof())
        assert replay.replayed is True
        assert replay.command_id == first.command_id
        assert replay.event_id == first.event_id
        assert len(after) == len(before)
    finally:
        system.close()


def test_committed_object_command_replays_after_lawful_deletion(
    tmp_path: Path,
) -> None:
    commands, schemas = _registries()
    system = open_object_system(
        tmp_path / "authority.sqlite3",
        command_registry=commands,
        payload_schema_registry=schemas,
    )
    try:
        admission = admit(system, data=b"replay after deletion").admission
        command = _command(admission.admission_id, key="object-replay-deleted")
        first = system.commands.execute(command, proof=proof())
        system.objects.revoke(
            admission.admission_id,
            reason_code="DELETE",
            idempotency_key="delete-revoke",
            proof=proof(),
        )
        deletion = system.objects.request_deletion(
            admission.blob.blob_digest,
            reason_code="DELETE",
            idempotency_key="delete-request",
            proof=proof(),
        )
        system.objects.tombstone(
            deletion.deletion_id,
            reason_code="DELETE",
            idempotency_key="delete-tombstone",
            proof=proof(),
        )
        system.objects.complete_deletion(
            deletion.deletion_id,
            idempotency_key="delete-complete",
            proof=proof(),
        )
        before = system.events.after(0, limit=1000, proof=proof())
        replay = system.commands.execute(command, proof=proof())
        after = system.events.after(0, limit=1000, proof=proof())
        assert replay.replayed is True
        assert replay.command_id == first.command_id
        assert replay.event_id == first.event_id
        assert len(after) == len(before)
    finally:
        system.close()


def test_object_command_idempotency_rejects_another_admission(
    tmp_path: Path,
) -> None:
    commands, schemas = _registries()
    system = open_object_system(
        tmp_path / "authority.sqlite3",
        command_registry=commands,
        payload_schema_registry=schemas,
    )
    try:
        first_admission = admit(system, data=b"first object", key="first-admit").admission
        second_admission = admit(system, data=b"second object", key="second-admit").admission
        original = _command(first_admission.admission_id, key="object-key-conflict")
        system.commands.execute(original, proof=proof())
        conflicting = SemanticCommand(
            command_type=original.command_type,
            aggregate_id=original.aggregate_id,
            expected_aggregate_version=original.expected_aggregate_version,
            payload=ObjectAdmissionPayload(second_admission.admission_id),
            idempotency_key=original.idempotency_key,
        )
        with pytest.raises(IdempotencyIdentityConflict):
            system.commands.execute(conflicting, proof=proof())
    finally:
        system.close()


def test_object_command_rechecks_rights_time_inside_commit(
    tmp_path: Path,
) -> None:
    commands, schemas = _registries()
    clock = MutableClock(FIXED_NOW)
    armed = False
    rehashes = 0

    def fault(checkpoint: str) -> None:
        nonlocal rehashes
        if not armed or checkpoint != "after_pinned_rehash":
            return
        rehashes += 1
        if rehashes == 2:
            clock.current = UtcTimestamp(
                FIXED_NOW.value + timedelta(seconds=30)
            )

    system = open_object_system(
        tmp_path / "authority.sqlite3",
        command_registry=commands,
        payload_schema_registry=schemas,
        clock=clock,
        fault_hook=fault,
    )
    try:
        admission = admit(
            system,
            data=b"short command rights",
            key="short-command-admit",
            admission_type="source.short",
        ).admission
        armed = True
        with pytest.raises(ObjectAdmissionDenied, match="expired|RIGHTS"):
            system.commands.execute(
                _command(admission.admission_id, key="short-object-command"),
                proof=proof(),
            )
        assert all(
            item.event_type != "fixture.object_observed.recorded"
            for item in system.events.after(0, limit=1000, proof=proof())
        )
    finally:
        system.close()



def test_denied_object_command_does_not_hash_governed_bytes_before_authorization(
    tmp_path: Path,
) -> None:
    commands, schemas = _registries()
    armed = False
    rehashes = 0

    def fault(checkpoint: str) -> None:
        nonlocal rehashes
        if armed and checkpoint == "before_pinned_rehash":
            rehashes += 1

    system = open_object_system(
        tmp_path / "authority.sqlite3",
        command_registry=commands,
        payload_schema_registry=schemas,
        scopes=frozenset(
            {
                "authority.objects.admit",
                "authority.objects.lifecycle.write",
            }
        ),
        fault_hook=fault,
    )
    try:
        admission = admit(system, data=b"do not hash before authorization").admission
        armed = True
        with pytest.raises(AuthorizationDenied):
            system.commands.execute(
                _command(admission.admission_id, key="denied-object-command"),
                proof=proof(),
            )
        assert rehashes == 0
    finally:
        system.close()

def test_object_command_rechecks_authentication_after_final_byte_hash(
    tmp_path: Path,
) -> None:
    commands, schemas = _registries()
    clock = MutableClock(FIXED_NOW)
    armed = False
    rehashes = 0

    def fault(checkpoint: str) -> None:
        nonlocal rehashes
        if not armed or checkpoint != "after_pinned_rehash":
            return
        rehashes += 1
        if rehashes == 2:
            clock.current = UtcTimestamp(
                FIXED_NOW.value + timedelta(seconds=2)
            )

    system = open_object_system(
        tmp_path / "authority.sqlite3",
        command_registry=commands,
        payload_schema_registry=schemas,
        authenticator=StaticAuthenticator(
            credentials={"token-1": StaticPrincipal("principal.alpha")},
            authority_domain="newsroom.authority",
            ttl_seconds=1,
        ),
        clock=clock,
        fault_hook=fault,
    )
    try:
        admission = admit(
            system,
            data=b"authentication expires during final hash",
            key="auth-expiry-admit",
        ).admission
        armed = True
        with pytest.raises(AuthenticationError, match="expired"):
            system.commands.execute(
                _command(admission.admission_id, key="auth-expiry-command"),
                proof=proof(),
            )
        assert rehashes >= 2
        assert all(
            item.event_type != "fixture.object_observed.recorded"
            for item in system.events.after(0, limit=1000, proof=proof())
        )
    finally:
        system.close()


def test_object_payload_schema_metadata_tamper_fails_reopen(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    commands, schemas = _registries()
    system = open_object_system(
        database,
        command_registry=commands,
        payload_schema_registry=schemas,
    )
    try:
        admission = admit(system, data=b"schema metadata").admission
        system.commands.execute(
            _command(admission.admission_id, key="object-schema-tamper"),
            proof=proof(),
        )
    finally:
        system.close()

    conn = sqlite3.connect(database)
    try:
        conn.execute("DROP TRIGGER immutable_authority_payloads_update")
        conn.execute("DROP TRIGGER immutable_ledger_events_update")
        conn.execute(
            "UPDATE authority_payloads SET schema_version='tampered-v1' "
            "WHERE mode='OBJECT_ADMISSION'"
        )
        conn.execute(
            "UPDATE ledger_events SET payload_schema_version='tampered-v1' "
            "WHERE payload_mode='OBJECT_ADMISSION'"
        )
        conn.execute(
            "CREATE TRIGGER immutable_authority_payloads_update "
            "BEFORE UPDATE ON authority_payloads BEGIN "
            "SELECT RAISE(ABORT,'immutable authority payload'); END"
        )
        conn.execute(
            "CREATE TRIGGER immutable_ledger_events_update "
            "BEFORE UPDATE ON ledger_events BEGIN "
            "SELECT RAISE(ABORT,'immutable ledger event'); END"
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(AuthorityPersistenceError, match="schema contract"):
        open_object_system(
            database,
            command_registry=commands,
            payload_schema_registry=schemas,
        )
