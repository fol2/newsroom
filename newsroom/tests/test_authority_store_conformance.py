from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field, replace
from threading import RLock

import pytest

from .authority_store_conformance import (
    CASE_INVENTORY,
    Applicability,
    AuthorityStoreAdapter,
    AuthorityStoreHandle,
    AuthorityValue,
    BindingConflict,
    CaseId,
    FailureCode,
    IntegrityViolation,
    LostResponse,
    OutcomeStatus,
    RollbackScope,
    StoredAuthorityState,
    TamperKind,
    WriteCommand,
    run_conformance,
)

ALL_REQUIRED = {case: Applicability.required() for case in CASE_INVENTORY}


@dataclass
class MemoryLocation:
    rows: dict[str, StoredAuthorityState] = field(default_factory=dict)
    commands: dict[str, WriteCommand] = field(default_factory=dict)
    trusted_digests: dict[str, str] = field(default_factory=dict)
    history_entries: list[AuthorityValue] = field(default_factory=list)
    upstream_heads: dict[str, str] = field(default_factory=dict)
    head: str = "record-0"
    open_count: int = 0
    lock: RLock = field(default_factory=RLock)


class MemoryRollbackScope:
    def __init__(self, owner: InMemoryStoreAdapter, location: MemoryLocation) -> None:
        self.owner = owner
        self.location = location

    def submit(self, command: WriteCommand) -> AuthorityValue:
        return self.owner._submit(self.location, command)

    def observe(self, record_id: str) -> StoredAuthorityState | None:
        if self.owner.defect == "rollback_wrong_state_swallow":
            return None
        return deepcopy(self.location.rows.get(record_id))

    def history(self) -> tuple[AuthorityValue, ...]:
        if self.owner.defect == "rollback_wrong_history_wrap":
            return ()
        return tuple(deepcopy(self.location.history_entries))


class MemoryHandle:
    def __init__(
        self,
        owner: InMemoryStoreAdapter,
        location: MemoryLocation,
        reopened: bool,
    ) -> None:
        self.owner = owner
        self.location = location
        self.reopened = reopened
        self.closed = False

    def _open(self) -> None:
        if self.closed:
            raise RuntimeError("closed handle")

    def submit(
        self, command: WriteCommand, *, lose_response: bool = False
    ) -> AuthorityValue:
        self._open()
        return self.owner._submit(self.location, command, lose_response=lose_response)

    def observe(self, record_id: str) -> StoredAuthorityState | None:
        self._open()
        with self.location.lock:
            return deepcopy(self.location.rows.get(record_id))

    def history(self) -> tuple[AuthorityValue, ...]:
        self._open()
        with self.location.lock:
            return tuple(deepcopy(self.location.history_entries))

    def read(self, record_id: str) -> AuthorityValue:
        self._open()
        return self.owner._read(self.location, record_id, self.reopened)

    def list_history(self) -> tuple[AuthorityValue, ...]:
        self._open()
        with self.location.lock:
            if self.owner.defect == "list_skips_validation":
                return tuple(
                    self.owner._value(self.location.rows[entry.record_id])
                    for entry in self.location.history_entries
                )
            return tuple(
                self.owner._read(self.location, entry.record_id, self.reopened)
                for entry in self.location.history_entries
            )

    def set_upstream_head(self, authority: str, value: str) -> None:
        self._open()
        with self.location.lock:
            self.location.upstream_heads[authority] = value

    def current_use(self, record_id: str) -> AuthorityValue:
        self._open()
        value = self.owner._read(self.location, record_id, self.reopened)
        row = self.location.rows[record_id]
        for index, (authority, expected) in enumerate(row.required_upstream_heads):
            if self.owner.defect == "current_heads" and index == 1:
                continue
            if (
                self.owner.defect != "current_rejection"
                and self.location.upstream_heads.get(authority) != expected
            ):
                raise IntegrityViolation(authority)
        return value

    def tamper(self, record_id: str, kind: TamperKind) -> None:
        self._open()
        self.owner._tamper(self.location, record_id, kind)

    def rollback_scope(self, operation: Callable[[RollbackScope], None]) -> None:
        self._open()
        with self.location.lock:
            snapshot = (
                deepcopy(self.location.rows),
                deepcopy(self.location.commands),
                deepcopy(self.location.trusted_digests),
                deepcopy(self.location.history_entries),
                self.location.head,
            )
            failed = False
            try:
                if self.owner.defect == "rollback_omit_callback":
                    return
                scope = MemoryRollbackScope(self.owner, self.location)
                operation(scope)
                if self.owner.defect == "rollback_duplicate_callback":
                    operation(scope)
            except Exception as exc:
                failed = True
                if self.owner.defect in {
                    "rollback_wrong_state_swallow",
                    "rollback_swallow_exception",
                }:
                    return
                if self.owner.defect == "rollback_wrong_history_wrap":
                    raise RuntimeError("wrapped scope failure") from exc
                if self.owner.defect == "rollback_wrong_rethrow":
                    raise RuntimeError("wrong rollback exception") from exc
                if self.owner.defect == "rollback_same_type_rethrow":
                    raise type(exc) from exc
                raise
            finally:
                commit = self.owner.defect == "rollback_commit_normal" and not failed
                commit = commit or (
                    self.owner.defect == "rollback_commit_on_exception" and failed
                )
                if not commit:
                    (
                        self.location.rows,
                        self.location.commands,
                        self.location.trusted_digests,
                        self.location.history_entries,
                        self.location.head,
                    ) = snapshot

    def close(self) -> None:
        self.closed = True


class InMemoryStoreAdapter:
    """Persisted, multi-handle store double with primitive behaviour defects."""

    name = "stateful-memory-store"
    applicability = ALL_REQUIRED

    def __init__(self, defect: str | None = None) -> None:
        self.defect = defect
        self.last_handle: MemoryHandle | None = None
        self.last_tamper: TamperKind | None = None

    def create_location(self) -> object:
        return MemoryLocation()

    def open_handle(
        self, location: object, *, migrate: bool = False
    ) -> AuthorityStoreHandle:
        assert isinstance(location, MemoryLocation)
        if (
            self.defect == "no_new_handle"
            and self.last_handle is not None
            and self.last_handle.location is location
        ):
            self.last_handle.closed = False
            return self.last_handle
        handle = MemoryHandle(self, location, reopened=location.open_count > 0)
        location.open_count += 1
        self.last_handle = handle
        if self.defect == "migration" and migrate and location.rows:
            record_id = min(location.rows)
            location.rows[record_id] = replace(
                location.rows[record_id], canonical_bytes=b"migration-corruption"
            )
        return handle

    @staticmethod
    def _value(row: StoredAuthorityState) -> AuthorityValue:
        return AuthorityValue(
            row.record_id,
            row.scalar_columns["value"],
            row.digest,
            row.provenance,
        )

    def _valid(self, location: MemoryLocation, row: StoredAuthorityState) -> bool:
        reconstructed = StoredAuthorityState.from_command(
            WriteCommand(
                record_id=row.record_id,
                canonical_bytes=row.canonical_bytes,
                scalar_columns=row.scalar_columns,
                identity_columns=row.identity_columns,
                linked_rows=row.linked_rows,
                actor=row.actor,
                request=row.request,
                idempotency=row.idempotency,
                cas_predecessor=row.cas_predecessor,
                required_upstream_heads=row.required_upstream_heads,
            )
        )
        return (
            reconstructed == row
            and location.trusted_digests.get(row.record_id) == row.digest
        )

    def _read(
        self, location: MemoryLocation, record_id: str, reopened: bool
    ) -> AuthorityValue:
        with location.lock:
            row = location.rows[record_id]
            accepted_tamper = {
                "accept_scalar_tamper": TamperKind.SCALAR,
                "accept_canonical_tamper": TamperKind.CANONICAL,
                "accept_identity_tamper": TamperKind.IDENTITY,
                "accept_linked_tamper": TamperKind.LINKED_ROW,
                "accept_digest_tamper": TamperKind.DIGEST,
                "accept_provenance_tamper": TamperKind.PROVENANCE,
                "accept_offline_rewrite": TamperKind.OFFLINE_REWRITE,
            }
            skip_validation = accepted_tamper.get(self.defect) == self.last_tamper
            if self.defect == "reopen_validation" and reopened:
                skip_validation = True
            if not skip_validation and not self._valid(location, row):
                raise IntegrityViolation(record_id)
            return self._value(row)

    def _submit(
        self,
        location: MemoryLocation,
        command: WriteCommand,
        *,
        lose_response: bool = False,
    ) -> AuthorityValue:
        with location.lock:
            if self.defect == "no_store":
                return AuthorityValue.from_command(command)
            existing = location.commands.get(command.record_id)
            if existing is not None:
                if existing != command:
                    changed = next(
                        (
                            field_name
                            for field_name in (
                                "actor",
                                "request",
                                "idempotency",
                                "cas_predecessor",
                            )
                            if getattr(existing, field_name)
                            != getattr(command, field_name)
                        ),
                        None,
                    )
                    if self.defect != f"binding_{changed}":
                        raise BindingConflict(command.record_id)
                row = location.rows[command.record_id]
                if self.defect != "lost_integrity" and not self._valid(location, row):
                    raise IntegrityViolation(command.record_id)
                if self.defect == "replay_history":
                    location.history_entries.append(self._value(row))
                if self.defect == "replay_state":
                    row = replace(row, provenance="changed-on-replay")
                    location.rows[command.record_id] = row
                if self.defect == "lost_currentness":
                    for authority, expected in row.required_upstream_heads:
                        if location.upstream_heads.get(authority) != expected:
                            raise IntegrityViolation(authority)
                return self._value(row)
            if (
                command.cas_predecessor != location.head
                and self.defect != "competing_no_cas"
            ):
                raise BindingConflict(command.record_id)
            row = StoredAuthorityState.from_command(command)
            write_defects = {
                "write_scalar": ("scalar_columns", {"value": "wrong", "version": 1}),
                "write_canonical": ("canonical_bytes", b"wrong"),
                "write_identity": ("identity_columns", {"record_id": "wrong"}),
                "write_linked": ("linked_rows", ({"child_id": "wrong"},)),
            }
            if self.defect in write_defects:
                field_name, value = write_defects[self.defect]
                row = replace(row, **{field_name: value})
            location.rows[command.record_id] = row
            location.commands[command.record_id] = command
            location.trusted_digests[command.record_id] = row.digest
            location.history_entries.append(self._value(row))
            location.head = command.record_id
            if lose_response:
                raise LostResponse(command.record_id)
            return self._value(row)

    def _tamper(
        self, location: MemoryLocation, record_id: str, kind: TamperKind
    ) -> None:
        with location.lock:
            self.last_tamper = kind
            row = location.rows[record_id]
            if kind is TamperKind.CANONICAL:
                row = replace(row, canonical_bytes=b"tampered")
            elif kind is TamperKind.SCALAR:
                row = replace(row, scalar_columns={"value": "tampered", "version": 1})
            elif kind is TamperKind.IDENTITY:
                row = replace(row, identity_columns={"record_id": "tampered"})
            elif kind is TamperKind.LINKED_ROW:
                row = replace(row, linked_rows=({"child_id": "tampered"},))
            elif kind is TamperKind.DIGEST:
                row = replace(row, digest="tampered")
            elif kind is TamperKind.PROVENANCE:
                row = replace(row, provenance="tampered")
            elif kind is TamperKind.OFFLINE_REWRITE:
                rewritten = replace(
                    location.commands[record_id],
                    canonical_bytes=b'{"value":"offline"}',
                    scalar_columns={"value": "offline", "version": 1},
                    request="offline-request",
                    idempotency="offline-idempotency",
                )
                row = StoredAuthorityState.from_command(rewritten)
            location.rows[record_id] = row


def focused_adapter(defect: str, case: CaseId) -> InMemoryStoreAdapter:
    adapter = InMemoryStoreAdapter(defect)
    adapter.applicability = {
        inventory_case: (
            Applicability.required()
            if inventory_case is case
            else Applicability.waived(
                reason="focused primitive defect fixture",
                waiver_reference="test:focused-primitive-defect",
            )
        )
        for inventory_case in CASE_INVENTORY
    }
    return adapter


def test_case_inventory_is_stable_and_complete() -> None:
    assert tuple(case.value for case in CASE_INVENTORY) == (
        "fresh_replay",
        "fresh_reopen",
        "representation_binding",
        "request_binding",
        "lost_response_replay",
        "historical_read",
        "current_use_revalidation",
        "tamper_rejection",
        "competing_writers",
        "transaction_rollback",
        "restart_migration",
    )


def test_stateful_all_required_store_passes_every_kernel_owned_scenario() -> None:
    adapter: AuthorityStoreAdapter = InMemoryStoreAdapter()
    report = run_conformance(adapter)
    assert report.passed
    assert all(outcome.status is OutcomeStatus.PASS for outcome in report.outcomes)


@pytest.mark.parametrize(
    ("defect", "case", "code"),
    (
        ("replay_history", CaseId.FRESH_REPLAY, FailureCode.REPLAY_MISMATCH),
        ("replay_state", CaseId.FRESH_REPLAY, FailureCode.REPLAY_MISMATCH),
        ("no_store", CaseId.FRESH_REPLAY, FailureCode.REPLAY_MISMATCH),
        ("no_new_handle", CaseId.FRESH_REOPEN, FailureCode.REOPEN_MISMATCH),
        ("reopen_validation", CaseId.FRESH_REOPEN, FailureCode.REOPEN_MISMATCH),
        (
            "write_scalar",
            CaseId.REPRESENTATION_BINDING,
            FailureCode.REPRESENTATION_MISMATCH,
        ),
        (
            "write_canonical",
            CaseId.REPRESENTATION_BINDING,
            FailureCode.REPRESENTATION_MISMATCH,
        ),
        (
            "write_identity",
            CaseId.REPRESENTATION_BINDING,
            FailureCode.REPRESENTATION_MISMATCH,
        ),
        (
            "write_linked",
            CaseId.REPRESENTATION_BINDING,
            FailureCode.REPRESENTATION_MISMATCH,
        ),
        ("binding_actor", CaseId.REQUEST_BINDING, FailureCode.REQUEST_BINDING_MISMATCH),
        (
            "binding_request",
            CaseId.REQUEST_BINDING,
            FailureCode.REQUEST_BINDING_MISMATCH,
        ),
        (
            "binding_idempotency",
            CaseId.REQUEST_BINDING,
            FailureCode.REQUEST_BINDING_MISMATCH,
        ),
        (
            "binding_cas_predecessor",
            CaseId.REQUEST_BINDING,
            FailureCode.REQUEST_BINDING_MISMATCH,
        ),
        (
            "lost_integrity",
            CaseId.LOST_RESPONSE_REPLAY,
            FailureCode.LOST_RESPONSE_INTEGRITY,
        ),
        (
            "lost_currentness",
            CaseId.LOST_RESPONSE_REPLAY,
            FailureCode.LOST_RESPONSE_INTEGRITY,
        ),
        (
            "accept_digest_tamper",
            CaseId.HISTORICAL_READ,
            FailureCode.HISTORICAL_INTEGRITY,
        ),
        (
            "accept_provenance_tamper",
            CaseId.HISTORICAL_READ,
            FailureCode.HISTORICAL_INTEGRITY,
        ),
        (
            "list_skips_validation",
            CaseId.HISTORICAL_READ,
            FailureCode.HISTORICAL_INTEGRITY,
        ),
        (
            "current_heads",
            CaseId.CURRENT_USE_REVALIDATION,
            FailureCode.CURRENT_USE_REVALIDATION,
        ),
        (
            "current_rejection",
            CaseId.CURRENT_USE_REVALIDATION,
            FailureCode.CURRENT_USE_REVALIDATION,
        ),
        (
            "accept_scalar_tamper",
            CaseId.REPRESENTATION_BINDING,
            FailureCode.REPRESENTATION_MISMATCH,
        ),
        (
            "accept_canonical_tamper",
            CaseId.REPRESENTATION_BINDING,
            FailureCode.REPRESENTATION_MISMATCH,
        ),
        (
            "accept_canonical_tamper",
            CaseId.TAMPER_REJECTION,
            FailureCode.TAMPER_ACCEPTED,
        ),
        (
            "accept_identity_tamper",
            CaseId.REPRESENTATION_BINDING,
            FailureCode.REPRESENTATION_MISMATCH,
        ),
        (
            "accept_linked_tamper",
            CaseId.REPRESENTATION_BINDING,
            FailureCode.REPRESENTATION_MISMATCH,
        ),
        ("accept_linked_tamper", CaseId.TAMPER_REJECTION, FailureCode.TAMPER_ACCEPTED),
        (
            "accept_offline_rewrite",
            CaseId.TAMPER_REJECTION,
            FailureCode.TAMPER_ACCEPTED,
        ),
        (
            "reopen_validation",
            CaseId.TAMPER_REJECTION,
            FailureCode.TAMPER_ACCEPTED,
        ),
        (
            "competing_no_cas",
            CaseId.COMPETING_WRITERS,
            FailureCode.COMPETING_WRITERS_NONDETERMINISTIC,
        ),
        (
            "rollback_commit_normal",
            CaseId.TRANSACTION_ROLLBACK,
            FailureCode.TRANSACTION_NOT_ROLLED_BACK,
        ),
        (
            "rollback_commit_on_exception",
            CaseId.TRANSACTION_ROLLBACK,
            FailureCode.TRANSACTION_NOT_ROLLED_BACK,
        ),
        (
            "rollback_omit_callback",
            CaseId.TRANSACTION_ROLLBACK,
            FailureCode.TRANSACTION_NOT_ROLLED_BACK,
        ),
        (
            "rollback_duplicate_callback",
            CaseId.TRANSACTION_ROLLBACK,
            FailureCode.TRANSACTION_NOT_ROLLED_BACK,
        ),
        (
            "rollback_wrong_state_swallow",
            CaseId.TRANSACTION_ROLLBACK,
            FailureCode.TRANSACTION_NOT_ROLLED_BACK,
        ),
        (
            "rollback_wrong_history_wrap",
            CaseId.TRANSACTION_ROLLBACK,
            FailureCode.TRANSACTION_NOT_ROLLED_BACK,
        ),
        (
            "rollback_swallow_exception",
            CaseId.TRANSACTION_ROLLBACK,
            FailureCode.TRANSACTION_NOT_ROLLED_BACK,
        ),
        (
            "rollback_wrong_rethrow",
            CaseId.TRANSACTION_ROLLBACK,
            FailureCode.TRANSACTION_NOT_ROLLED_BACK,
        ),
        (
            "rollback_same_type_rethrow",
            CaseId.TRANSACTION_ROLLBACK,
            FailureCode.TRANSACTION_NOT_ROLLED_BACK,
        ),
        ("migration", CaseId.RESTART_MIGRATION, FailureCode.RESTART_MIGRATION_MISMATCH),
    ),
)
def test_primitive_store_defects_have_exact_family_classification(
    defect: str, case: CaseId, code: FailureCode
) -> None:
    report = run_conformance(focused_adapter(defect, case))
    assert [(failure.case, failure.code) for failure in report.failures] == [
        (case, code)
    ]


def test_rollback_seam_is_store_owned_not_an_externally_held_transaction() -> None:
    assert not hasattr(MemoryHandle, "begin")
    assert not hasattr(AuthorityStoreHandle, "begin")
    assert hasattr(AuthorityStoreHandle, "rollback_scope")


def test_rollback_inspection_runs_against_staged_state_and_history() -> None:
    adapter = InMemoryStoreAdapter()
    location = adapter.create_location()
    handle = adapter.open_handle(location)
    command = WriteCommand(
        record_id="record-inspection",
        canonical_bytes=b'{"value":"visible"}',
        scalar_columns={"value": "visible", "version": 1},
        identity_columns={"record_id": "record-inspection", "authority": "fixture"},
        linked_rows=(),
        actor="actor",
        request="request",
        idempotency="idempotency",
        cas_predecessor="record-0",
        required_upstream_heads=(),
    )
    seen: list[tuple[StoredAuthorityState | None, tuple[AuthorityValue, ...]]] = []

    def operate(scope: RollbackScope) -> None:
        scope.submit(command)
        state = scope.observe(command.record_id)
        history = scope.history()
        assert handle.observe(command.record_id) == state
        assert handle.history() == history
        seen.append((state, history))

    handle.rollback_scope(operate)

    assert seen == [
        (
            StoredAuthorityState.from_command(command),
            (AuthorityValue.from_command(command),),
        )
    ]
    assert handle.observe(command.record_id) is None
    assert handle.history() == ()


def test_rollback_scope_rolls_back_when_inspection_raises() -> None:
    adapter = InMemoryStoreAdapter()
    location = adapter.create_location()
    handle = adapter.open_handle(location)
    command = WriteCommand(
        record_id="record-inspection-error",
        canonical_bytes=b'{"value":"visible"}',
        scalar_columns={"value": "visible", "version": 1},
        identity_columns={
            "record_id": "record-inspection-error",
            "authority": "fixture",
        },
        linked_rows=(),
        actor="actor",
        request="request",
        idempotency="idempotency",
        cas_predecessor="record-0",
        required_upstream_heads=(),
    )

    def fail_inspection(scope: RollbackScope) -> None:
        scope.submit(command)
        assert scope.observe(command.record_id) == StoredAuthorityState.from_command(
            command
        )
        assert scope.history() == (AuthorityValue.from_command(command),)
        raise RuntimeError("inspection failed")

    with pytest.raises(RuntimeError, match="inspection failed"):
        handle.rollback_scope(fail_inspection)

    assert handle.observe(command.record_id) is None
    assert handle.history() == ()
    handle.close()
    reopened = adapter.open_handle(location)
    assert reopened is not handle
    assert reopened.observe(command.record_id) is None
    assert reopened.history() == ()


@pytest.mark.parametrize(
    ("field_name", "malformed"),
    (
        ("supported", 1),
        ("supported", "yes"),
        ("reason", 7),
        ("reason", object()),
        ("waiver_reference", 9),
        ("waiver_reference", ["issue:384"]),
    ),
)
def test_manifest_malformed_field_types_are_ordered_protocol_failures(
    field_name: str, malformed: object
) -> None:
    adapter = InMemoryStoreAdapter()
    manifest = dict(ALL_REQUIRED)
    manifest[CaseId.FRESH_REOPEN] = replace(
        Applicability.waived(reason="structural", waiver_reference="issue:384"),
        **{field_name: malformed},
    )
    manifest[CaseId.HISTORICAL_READ] = Applicability(False, 7, "issue:384")
    adapter.applicability = manifest
    report = run_conformance(adapter)
    assert not report.passed
    assert [failure.case for failure in report.protocol_failures] == [
        CaseId.FRESH_REOPEN,
        CaseId.HISTORICAL_READ,
    ]
    assert all(
        failure.code is FailureCode.ADAPTER_PROTOCOL
        for failure in report.protocol_failures
    )


def test_narrow_waiver_renders_deterministically() -> None:
    adapter = InMemoryStoreAdapter()
    adapter.applicability = {
        **ALL_REQUIRED,
        CaseId.RESTART_MIGRATION: Applicability.waived(
            reason="store is ephemeral and has no reopen boundary",
            waiver_reference="issue:384#ephemeral-fixture",
        ),
    }
    report = run_conformance(adapter)
    assert report.passed
    assert report.render()[-1].endswith(
        "waiver=issue:384#ephemeral-fixture reason=store is ephemeral and has no reopen boundary"
    )
