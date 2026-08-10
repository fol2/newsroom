from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from .authority_store_conformance import (
    CASE_INVENTORY,
    Applicability,
    AuthorityStoreAdapter,
    AuthorityValue,
    CaseId,
    FailureCode,
    IntegrityViolation,
    LostResponse,
    OutcomeStatus,
    StoredAuthorityState,
    TamperKind,
    WriteCommand,
    WriteConflict,
    run_conformance,
)

ALL_REQUIRED = {case: Applicability.required() for case in CASE_INVENTORY}


class InMemoryStoreAdapter:
    """Stateful store double; defects change operations, never expected evidence."""

    name = "stateful-memory-store"
    applicability = ALL_REQUIRED

    def __init__(self, defect: str | None = None) -> None:
        self.defect = defect
        self.reset()

    def reset(self) -> None:
        self.rows: dict[str, StoredAuthorityState] = {}
        self.trusted_digests: dict[str, str] = {}
        self.head: str | None = "record-0"
        self.upstream_heads: dict[str, str] = {}
        self.closed_rows: dict[str, StoredAuthorityState] | None = None

    @staticmethod
    def _value(row: StoredAuthorityState) -> AuthorityValue:
        return AuthorityValue(
            record_id=row.record_id,
            value=row.scalar_columns["value"],
            digest=row.digest,
            provenance=row.provenance,
        )

    def _valid(self, row: StoredAuthorityState) -> bool:
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
            row == reconstructed
            and self.trusted_digests.get(row.record_id) == row.digest
        )

    def _validated_row(
        self, record_id: str, *, replay: bool = False
    ) -> StoredAuthorityState:
        row = self.rows[record_id]
        if not (replay and self.defect == "lost_integrity") and not self._valid(row):
            raise IntegrityViolation(record_id)
        return row

    def put(
        self, command: WriteCommand, *, lose_response: bool = False
    ) -> AuthorityValue:
        if command.cas_predecessor != self.head and self.defect != "competing":
            raise WriteConflict(command.record_id)
        row = StoredAuthorityState.from_command(command)
        if self.defect == "canonical":
            row = replace(row, canonical_bytes=b'{"value":"beta"}')
        elif self.defect == "scalar":
            row = replace(row, scalar_columns={"value": "beta", "version": 1})
        elif self.defect == "linked":
            row = replace(
                row, linked_rows=({"child_id": "child-1", "record_id": "wrong"},)
            )
        elif self.defect in {"actor", "request", "idempotency", "cas"}:
            field = "cas_predecessor" if self.defect == "cas" else self.defect
            row = replace(row, **{field: "wrong"})
        self.rows[command.record_id] = row
        self.trusted_digests[command.record_id] = row.digest
        self.head = command.record_id
        value = self._value(row)
        if lose_response:
            raise LostResponse(command.record_id)
        return value

    def replay(self, command: WriteCommand) -> AuthorityValue:
        row = self._validated_row(command.record_id, replay=True)
        if self.defect == "lost_currentness":
            self._validate_current_heads(row)
        value = self._value(row)
        if self.defect == "replay":
            return replace(value, value="beta")
        return value

    def observe(self, record_id: str) -> StoredAuthorityState | None:
        return self.rows.get(record_id)

    def load(self, record_id: str) -> AuthorityValue:
        row = self.rows[record_id]
        if self.defect != "historical" and not self._valid(row):
            raise IntegrityViolation(record_id)
        return self._value(row)

    def list_history(self) -> tuple[AuthorityValue, ...]:
        values = []
        for record_id in sorted(self.rows):
            values.append(self.load(record_id))
        return tuple(values)

    def set_upstream_head(self, authority: str, value: str) -> None:
        self.upstream_heads[authority] = value

    def _validate_current_heads(self, row: StoredAuthorityState) -> None:
        required = row.required_upstream_heads
        for index, (authority, expected) in enumerate(required):
            if self.defect == "current_heads" and index == len(required) - 1:
                continue
            if self.upstream_heads.get(authority) != expected:
                raise IntegrityViolation(authority)

    def current_use(self, record_id: str) -> AuthorityValue:
        row = self._validated_row(record_id)
        if self.defect != "current_rejection":
            self._validate_current_heads(row)
        return self._value(row)

    def tamper(self, record_id: str, kind: TamperKind) -> None:
        ignored = {
            "tamper_direct": TamperKind.CANONICAL,
            "tamper_linked": TamperKind.LINKED_ROW,
            "tamper_self_consistent": TamperKind.OFFLINE_REWRITE,
        }
        if ignored.get(self.defect) is kind:
            return
        row = self.rows[record_id]
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
            rewritten = WriteCommand(
                record_id=row.record_id,
                canonical_bytes=b'{"value":"offline"}',
                scalar_columns={"value": "offline", "version": 1},
                identity_columns=row.identity_columns,
                linked_rows=row.linked_rows,
                actor=row.actor,
                request="offline-request",
                idempotency="offline-idempotency",
                cas_predecessor=row.cas_predecessor,
                required_upstream_heads=row.required_upstream_heads,
            )
            row = StoredAuthorityState.from_command(rewritten)
        self.rows[record_id] = row

    def reopen(self, *, migrate: bool) -> None:
        self.closed_rows = deepcopy(self.rows)
        self.rows = deepcopy(self.closed_rows)
        if (
            (self.defect == "reopen" and not migrate)
            or (self.defect == "migration" and migrate)
            or (self.defect == "restart" and not migrate)
        ):
            record_id = min(self.rows)
            self.rows[record_id] = replace(
                self.rows[record_id], canonical_bytes=b"corrupt-after-reopen"
            )

    def rollback(self, command: WriteCommand) -> None:
        snapshot = deepcopy(self.rows)
        trusted_snapshot = deepcopy(self.trusted_digests)
        head = self.head
        self.put(command)
        if self.defect != "rollback":
            self.rows = snapshot
            self.trusted_digests = trusted_snapshot
            self.head = head


class ConstantNoStoreAdapter(InMemoryStoreAdapter):
    """Regression double for the old self-consistent, no-store loophole."""

    def reset(self) -> None:
        self.rows = {}
        self.trusted_digests = {}
        self.head = "record-0"
        self.upstream_heads = {}
        self.closed_rows = None

    def put(
        self, command: WriteCommand, *, lose_response: bool = False
    ) -> AuthorityValue:
        return AuthorityValue(command.record_id, "alpha", "constant", "constant")

    def replay(self, command: WriteCommand) -> AuthorityValue:
        return AuthorityValue(command.record_id, "alpha", "constant", "constant")

    def observe(self, record_id: str) -> StoredAuthorityState | None:
        return None


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


def test_stateful_all_required_store_passes_every_family() -> None:
    adapter: AuthorityStoreAdapter = InMemoryStoreAdapter()
    report = run_conformance(adapter)
    assert report.passed
    assert report.failures == ()
    assert all(outcome.status is OutcomeStatus.PASS for outcome in report.outcomes)


def test_self_consistent_constant_no_store_adapter_fails() -> None:
    report = run_conformance(ConstantNoStoreAdapter())
    assert not report.passed
    assert report.failures[0].code is FailureCode.REPLAY_MISMATCH


@pytest.mark.parametrize(
    ("defect", "case", "code"),
    (
        ("replay", CaseId.FRESH_REPLAY, FailureCode.REPLAY_MISMATCH),
        ("reopen", CaseId.FRESH_REOPEN, FailureCode.REOPEN_MISMATCH),
        ("scalar", CaseId.REPRESENTATION_BINDING, FailureCode.REPRESENTATION_MISMATCH),
        (
            "canonical",
            CaseId.REPRESENTATION_BINDING,
            FailureCode.REPRESENTATION_MISMATCH,
        ),
        ("linked", CaseId.REPRESENTATION_BINDING, FailureCode.REPRESENTATION_MISMATCH),
        ("actor", CaseId.REQUEST_BINDING, FailureCode.REQUEST_BINDING_MISMATCH),
        ("request", CaseId.REQUEST_BINDING, FailureCode.REQUEST_BINDING_MISMATCH),
        ("idempotency", CaseId.REQUEST_BINDING, FailureCode.REQUEST_BINDING_MISMATCH),
        ("cas", CaseId.REQUEST_BINDING, FailureCode.REQUEST_BINDING_MISMATCH),
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
        ("historical", CaseId.HISTORICAL_READ, FailureCode.HISTORICAL_INTEGRITY),
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
        ("tamper_direct", CaseId.TAMPER_REJECTION, FailureCode.TAMPER_ACCEPTED),
        ("tamper_linked", CaseId.TAMPER_REJECTION, FailureCode.TAMPER_ACCEPTED),
        (
            "tamper_self_consistent",
            CaseId.TAMPER_REJECTION,
            FailureCode.TAMPER_ACCEPTED,
        ),
        (
            "competing",
            CaseId.COMPETING_WRITERS,
            FailureCode.COMPETING_WRITERS_NONDETERMINISTIC,
        ),
        (
            "rollback",
            CaseId.TRANSACTION_ROLLBACK,
            FailureCode.TRANSACTION_NOT_ROLLED_BACK,
        ),
        ("restart", CaseId.RESTART_MIGRATION, FailureCode.RESTART_MIGRATION_MISMATCH),
        ("migration", CaseId.RESTART_MIGRATION, FailureCode.RESTART_MIGRATION_MISMATCH),
    ),
)
def test_store_behaviour_defects_have_exact_family_classification(
    defect: str, case: CaseId, code: FailureCode
) -> None:
    adapter = InMemoryStoreAdapter(defect)
    adapter.applicability = {
        inventory_case: (
            Applicability.required()
            if inventory_case is case
            else Applicability.waived(
                reason="focused defect-classification fixture",
                waiver_reference="test:focused-defect-classification",
            )
        )
        for inventory_case in CASE_INVENTORY
    }
    report = run_conformance(adapter)
    assert [(failure.case, failure.code) for failure in report.failures] == [
        (case, code)
    ]


def test_exhaustive_manifest_accepts_a_narrow_structural_waiver() -> None:
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
    skipped = report.outcomes[-1]
    assert skipped.status is OutcomeStatus.SKIPPED
    assert skipped.waiver_reference == "issue:384#ephemeral-fixture"
    assert report.render()[-1].endswith(
        "waiver=issue:384#ephemeral-fixture reason=store is ephemeral and has no reopen boundary"
    )


@pytest.mark.parametrize("invalid", ["missing", "empty_reason", "empty_reference"])
def test_manifest_rejects_silent_or_unreviewable_skips(invalid: str) -> None:
    adapter = InMemoryStoreAdapter()
    manifest = dict(ALL_REQUIRED)
    if invalid == "missing":
        del manifest[CaseId.HISTORICAL_READ]
    elif invalid == "empty_reason":
        manifest[CaseId.HISTORICAL_READ] = Applicability(False, "", "issue:384")
    else:
        manifest[CaseId.HISTORICAL_READ] = Applicability(False, "structural", "")
    adapter.applicability = manifest
    report = run_conformance(adapter)
    assert not report.passed
    assert report.failures[0].code is FailureCode.ADAPTER_PROTOCOL


def test_report_rendering_is_deterministic() -> None:
    first = run_conformance(InMemoryStoreAdapter("linked"))
    second = run_conformance(InMemoryStoreAdapter("linked"))
    assert first.render() == second.render()
    assert first.render()[0] == "adapter=stateful-memory-store"
