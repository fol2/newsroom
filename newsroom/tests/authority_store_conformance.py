"""Test-only authority-store conformance kernel.

Adapters create persisted locations and primitive handles. The kernel owns all
commands, concurrency, transactions, reopen sequencing and assertions.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from enum import Enum
from threading import Barrier
from typing import Any, Protocol, runtime_checkable


class CaseId(str, Enum):
    FRESH_REPLAY = "fresh_replay"
    FRESH_REOPEN = "fresh_reopen"
    REPRESENTATION_BINDING = "representation_binding"
    REQUEST_BINDING = "request_binding"
    LOST_RESPONSE_REPLAY = "lost_response_replay"
    HISTORICAL_READ = "historical_read"
    CURRENT_USE_REVALIDATION = "current_use_revalidation"
    TAMPER_REJECTION = "tamper_rejection"
    COMPETING_WRITERS = "competing_writers"
    TRANSACTION_ROLLBACK = "transaction_rollback"
    RESTART_MIGRATION = "restart_migration"


CASE_INVENTORY: tuple[CaseId, ...] = (
    CaseId.FRESH_REPLAY,
    CaseId.FRESH_REOPEN,
    CaseId.REPRESENTATION_BINDING,
    CaseId.REQUEST_BINDING,
    CaseId.LOST_RESPONSE_REPLAY,
    CaseId.HISTORICAL_READ,
    CaseId.CURRENT_USE_REVALIDATION,
    CaseId.TAMPER_REJECTION,
    CaseId.COMPETING_WRITERS,
    CaseId.TRANSACTION_ROLLBACK,
    CaseId.RESTART_MIGRATION,
)


class FailureCode(str, Enum):
    ADAPTER_PROTOCOL = "adapter_protocol"
    ADAPTER_ERROR = "adapter_error"
    REPLAY_MISMATCH = "replay_mismatch"
    REOPEN_MISMATCH = "reopen_mismatch"
    REPRESENTATION_MISMATCH = "representation_mismatch"
    REQUEST_BINDING_MISMATCH = "request_binding_mismatch"
    LOST_RESPONSE_INTEGRITY = "lost_response_integrity"
    HISTORICAL_INTEGRITY = "historical_integrity"
    CURRENT_USE_REVALIDATION = "current_use_revalidation"
    TAMPER_ACCEPTED = "tamper_accepted"
    COMPETING_WRITERS_NONDETERMINISTIC = "competing_writers_nondeterministic"
    TRANSACTION_NOT_ROLLED_BACK = "transaction_not_rolled_back"
    RESTART_MIGRATION_MISMATCH = "restart_migration_mismatch"


class OutcomeStatus(str, Enum):
    PASS = "pass"
    SKIPPED = "skipped"
    FAIL = "fail"


class TamperKind(str, Enum):
    CANONICAL = "canonical"
    SCALAR = "scalar"
    IDENTITY = "identity"
    LINKED_ROW = "linked_row"
    DIGEST = "digest"
    PROVENANCE = "provenance"
    OFFLINE_REWRITE = "offline_rewrite"


class StoreOperationError(Exception):
    """Base exception translated by a store adapter at the test seam."""


class IntegrityViolation(StoreOperationError):
    pass


class BindingConflict(StoreOperationError):
    pass


class LostResponse(StoreOperationError):
    pass


@dataclass(frozen=True)
class Applicability:
    supported: bool
    reason: str | None = None
    waiver_reference: str | None = None

    @classmethod
    def required(cls) -> Applicability:
        return cls(True)

    @classmethod
    def waived(cls, *, reason: str, waiver_reference: str) -> Applicability:
        return cls(False, reason, waiver_reference)


@dataclass(frozen=True)
class WriteCommand:
    record_id: str
    canonical_bytes: bytes
    scalar_columns: Mapping[str, Any]
    identity_columns: Mapping[str, Any]
    linked_rows: tuple[Mapping[str, Any], ...]
    actor: str
    request: str
    idempotency: str
    cas_predecessor: str
    required_upstream_heads: tuple[tuple[str, str], ...]


def _normalise(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _normalise(item) for key, item in sorted(value.items())}
    if isinstance(value, tuple):
        return [_normalise(item) for item in value]
    if isinstance(value, bytes):
        return value.hex()
    return value


def _command_digest(command: WriteCommand) -> str:
    material = json.dumps(
        _normalise(
            {
                "record_id": command.record_id,
                "canonical_bytes": command.canonical_bytes,
                "scalar_columns": command.scalar_columns,
                "identity_columns": command.identity_columns,
                "linked_rows": command.linked_rows,
                "actor": command.actor,
                "request": command.request,
                "idempotency": command.idempotency,
                "cas_predecessor": command.cas_predecessor,
                "required_upstream_heads": command.required_upstream_heads,
            }
        ),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(material).hexdigest()


@dataclass(frozen=True)
class StoredAuthorityState:
    record_id: str
    canonical_bytes: bytes
    scalar_columns: Mapping[str, Any]
    identity_columns: Mapping[str, Any]
    linked_rows: tuple[Mapping[str, Any], ...]
    actor: str
    request: str
    idempotency: str
    cas_predecessor: str
    required_upstream_heads: tuple[tuple[str, str], ...]
    digest: str
    provenance: str

    @classmethod
    def from_command(cls, command: WriteCommand) -> StoredAuthorityState:
        return cls(
            record_id=command.record_id,
            canonical_bytes=command.canonical_bytes,
            scalar_columns=command.scalar_columns,
            identity_columns=command.identity_columns,
            linked_rows=command.linked_rows,
            actor=command.actor,
            request=command.request,
            idempotency=command.idempotency,
            cas_predecessor=command.cas_predecessor,
            required_upstream_heads=command.required_upstream_heads,
            digest=_command_digest(command),
            provenance=command.request,
        )


@dataclass(frozen=True)
class AuthorityValue:
    record_id: str
    value: Any
    digest: str
    provenance: str

    @classmethod
    def from_command(cls, command: WriteCommand) -> AuthorityValue:
        return cls(
            command.record_id,
            command.scalar_columns["value"],
            _command_digest(command),
            command.request,
        )


class RollbackScope(Protocol):
    def submit(self, command: WriteCommand) -> AuthorityValue: ...
    def observe(self, record_id: str) -> StoredAuthorityState | None: ...
    def history(self) -> tuple[AuthorityValue, ...]: ...


RollbackOperation = Callable[[RollbackScope], None]


@runtime_checkable
class AuthorityStoreHandle(Protocol):
    def submit(
        self, command: WriteCommand, *, lose_response: bool = False
    ) -> AuthorityValue: ...
    def observe(self, record_id: str) -> StoredAuthorityState | None: ...
    def history(self) -> tuple[AuthorityValue, ...]: ...
    def read(self, record_id: str) -> AuthorityValue: ...
    def list_history(self) -> tuple[AuthorityValue, ...]: ...
    def set_upstream_head(self, authority: str, value: str) -> None: ...
    def current_use(self, record_id: str) -> AuthorityValue: ...
    def tamper(self, record_id: str, kind: TamperKind) -> None: ...
    def rollback_scope(self, operation: RollbackOperation) -> None: ...
    def close(self) -> None: ...


@runtime_checkable
class AuthorityStoreAdapter(Protocol):
    name: str
    applicability: Mapping[CaseId, Applicability]

    def create_location(self) -> object: ...
    def open_handle(
        self, location: object, *, migrate: bool = False
    ) -> AuthorityStoreHandle: ...


@dataclass(frozen=True)
class ConformanceFailure:
    case: CaseId | None
    code: FailureCode
    detail: str


@dataclass(frozen=True)
class CaseOutcome:
    case: CaseId
    status: OutcomeStatus
    failures: tuple[ConformanceFailure, ...] = ()
    waiver_reason: str | None = None
    waiver_reference: str | None = None


@dataclass(frozen=True)
class ConformanceReport:
    adapter_name: str
    outcomes: tuple[CaseOutcome, ...]
    protocol_failures: tuple[ConformanceFailure, ...] = ()

    @property
    def failures(self) -> tuple[ConformanceFailure, ...]:
        return self.protocol_failures + tuple(
            failure for outcome in self.outcomes for failure in outcome.failures
        )

    @property
    def passed(self) -> bool:
        return not self.failures

    def render(self) -> tuple[str, ...]:
        lines = [f"adapter={self.adapter_name}"]
        lines.extend(
            f"protocol failure code={failure.code.value} detail={failure.detail}"
            for failure in self.protocol_failures
        )
        for outcome in self.outcomes:
            line = f"case={outcome.case.value} status={outcome.status.value}"
            if outcome.failures:
                line += " codes=" + ",".join(
                    failure.code.value for failure in outcome.failures
                )
            if outcome.status is OutcomeStatus.SKIPPED and outcome.waiver_reference:
                line += (
                    f" waiver={outcome.waiver_reference} reason={outcome.waiver_reason}"
                )
            lines.append(line)
        return tuple(lines)


class AuthorityStoreConformanceError(AssertionError):
    def __init__(self, report: ConformanceReport) -> None:
        self.report = report
        super().__init__("\n".join(report.render()))


_CASE_FAILURES = {
    CaseId.FRESH_REPLAY: FailureCode.REPLAY_MISMATCH,
    CaseId.FRESH_REOPEN: FailureCode.REOPEN_MISMATCH,
    CaseId.REPRESENTATION_BINDING: FailureCode.REPRESENTATION_MISMATCH,
    CaseId.REQUEST_BINDING: FailureCode.REQUEST_BINDING_MISMATCH,
    CaseId.LOST_RESPONSE_REPLAY: FailureCode.LOST_RESPONSE_INTEGRITY,
    CaseId.HISTORICAL_READ: FailureCode.HISTORICAL_INTEGRITY,
    CaseId.CURRENT_USE_REVALIDATION: FailureCode.CURRENT_USE_REVALIDATION,
    CaseId.TAMPER_REJECTION: FailureCode.TAMPER_ACCEPTED,
    CaseId.COMPETING_WRITERS: FailureCode.COMPETING_WRITERS_NONDETERMINISTIC,
    CaseId.TRANSACTION_ROLLBACK: FailureCode.TRANSACTION_NOT_ROLLED_BACK,
    CaseId.RESTART_MIGRATION: FailureCode.RESTART_MIGRATION_MISMATCH,
}


class _CaseFailed(AssertionError):
    pass


class _RollbackInspectionAbort(Exception):
    pass


def _require(condition: bool, detail: str) -> None:
    if not condition:
        raise _CaseFailed(detail)


def _expect_exception(exception: type[Exception], operation: Any, detail: str) -> None:
    try:
        operation()
    except exception:
        return
    except Exception as exc:
        raise _CaseFailed(f"{detail}; raised {type(exc).__name__}") from exc
    raise _CaseFailed(detail)


def _command(
    record_id: str = "record-1", predecessor: str = "record-0", value: str = "alpha"
) -> WriteCommand:
    return WriteCommand(
        record_id=record_id,
        canonical_bytes=f'{{"value":"{value}"}}'.encode(),
        scalar_columns={"value": value, "version": 1},
        identity_columns={"record_id": record_id, "authority": "fixture"},
        linked_rows=(
            {"child_id": f"child-{record_id}", "record_id": record_id, "ordinal": 0},
        ),
        actor="actor-1",
        request=f"request-{record_id}",
        idempotency=f"idempotency-{record_id}",
        cas_predecessor=predecessor,
        required_upstream_heads=(
            ("authority", "authority-head-1"),
            ("policy", "policy-head-1"),
        ),
    )


def _new_handle(
    adapter: AuthorityStoreAdapter,
) -> tuple[object, AuthorityStoreHandle]:
    location = adapter.create_location()
    return location, adapter.open_handle(location)


def _snapshot(
    handle: AuthorityStoreHandle, record_id: str
) -> tuple[StoredAuthorityState | None, tuple[AuthorityValue, ...]]:
    return handle.observe(record_id), handle.history()


def _seed_heads(handle: AuthorityStoreHandle, command: WriteCommand) -> None:
    for authority, head in command.required_upstream_heads:
        handle.set_upstream_head(authority, head)


def _assert_tampers_rejected(
    adapter: AuthorityStoreAdapter,
    kinds: tuple[TamperKind, ...],
) -> None:
    command = _command()
    for kind in kinds:
        location, handle = _new_handle(adapter)
        handle.submit(command)
        handle.tamper(command.record_id, kind)
        _expect_exception(
            IntegrityViolation,
            lambda handle=handle: handle.read(command.record_id),
            f"fresh read accepted {kind.value} mutation",
        )
        handle.close()
        reopened = adapter.open_handle(location)
        _require(reopened is not handle, "reopen returned the original handle")
        _expect_exception(
            IntegrityViolation,
            lambda reopened=reopened: reopened.read(command.record_id),
            f"reopened read accepted {kind.value} mutation",
        )


def _fresh_replay(adapter: AuthorityStoreAdapter) -> None:
    command = _command()
    _, handle = _new_handle(adapter)
    before_history = handle.history()
    _require(handle.observe(command.record_id) is None, "record existed before write")
    expected = AuthorityValue.from_command(command)
    _require(handle.submit(command) == expected, "fresh submission result differs")
    after_fresh = _snapshot(handle, command.record_id)
    _require(
        len(after_fresh[1]) == len(before_history) + 1,
        "fresh submission did not append once",
    )
    _require(handle.submit(command) == expected, "exact replay result differs")
    _require(
        _snapshot(handle, command.record_id) == after_fresh,
        "exact replay changed state or append-only history",
    )


def _fresh_submission(adapter: AuthorityStoreAdapter) -> None:
    command = _command()
    _, handle = _new_handle(adapter)
    before_history = handle.history()
    _require(handle.observe(command.record_id) is None, "record existed before write")
    expected = AuthorityValue.from_command(command)
    _require(handle.submit(command) == expected, "fresh submission result differs")
    after_fresh = _snapshot(handle, command.record_id)
    _require(
        len(after_fresh[1]) == len(before_history) + 1,
        "fresh submission did not append once",
    )


def _exact_replay(adapter: AuthorityStoreAdapter) -> None:
    command = _command()
    _, handle = _new_handle(adapter)
    expected = AuthorityValue.from_command(command)
    handle.submit(command)
    after_fresh = _snapshot(handle, command.record_id)
    _require(handle.submit(command) == expected, "exact replay result differs")
    _require(
        _snapshot(handle, command.record_id) == after_fresh,
        "exact replay changed state or append-only history",
    )


def _fresh_reopen_persistence(adapter: AuthorityStoreAdapter) -> None:
    command = _command()
    location, handle = _new_handle(adapter)
    expected = AuthorityValue.from_command(command)
    handle.submit(command)
    _require(handle.read(command.record_id) == expected, "fresh-handle read differs")
    snapshot = _snapshot(handle, command.record_id)
    handle.close()
    reopened = adapter.open_handle(location)
    _require(reopened is not handle, "reopen returned the original handle")
    _require(
        reopened.read(command.record_id) == expected, "reopened-handle read differs"
    )
    _require(
        _snapshot(reopened, command.record_id) == snapshot,
        "reopen changed state or history",
    )


def _fresh_reopen_digest(adapter: AuthorityStoreAdapter) -> None:
    _assert_tampers_rejected(adapter, (TamperKind.DIGEST,))


def _fresh_reopen(adapter: AuthorityStoreAdapter) -> None:
    _fresh_reopen_persistence(adapter)
    _fresh_reopen_digest(adapter)


_REPRESENTATION_TAMPERS = (
    TamperKind.SCALAR,
    TamperKind.CANONICAL,
    TamperKind.IDENTITY,
    TamperKind.LINKED_ROW,
)
_REQUEST_BINDING_FIELDS = ("actor", "request", "idempotency", "cas_predecessor")
_HISTORICAL_TAMPERS = (
    TamperKind.IDENTITY,
    TamperKind.DIGEST,
    TamperKind.PROVENANCE,
)
_CURRENT_USE_AUTHORITIES = ("authority", "policy")
_TAMPER_REJECTION_TAMPERS = (
    TamperKind.CANONICAL,
    TamperKind.LINKED_ROW,
    TamperKind.OFFLINE_REWRITE,
)


def _representation_retained(adapter: AuthorityStoreAdapter) -> None:
    command = _command()
    _, handle = _new_handle(adapter)
    handle.submit(command)
    _require(
        handle.observe(command.record_id) == StoredAuthorityState.from_command(command),
        "persisted representation differs",
    )


def _representation_tamper(adapter: AuthorityStoreAdapter, kind: TamperKind) -> None:
    _require(kind in _REPRESENTATION_TAMPERS, "unknown representation tamper probe")
    _assert_tampers_rejected(adapter, (kind,))


def _representation(adapter: AuthorityStoreAdapter) -> None:
    _representation_retained(adapter)
    for kind in _REPRESENTATION_TAMPERS:
        _representation_tamper(adapter, kind)


def _request_binding_field(adapter: AuthorityStoreAdapter, field_name: str) -> None:
    _require(field_name in _REQUEST_BINDING_FIELDS, "unknown request binding probe")
    command = _command()
    _, handle = _new_handle(adapter)
    handle.submit(command)
    before = _snapshot(handle, command.record_id)
    divergent = replace(command, **{field_name: f"different-{field_name}"})
    _expect_exception(
        BindingConflict,
        lambda: handle.submit(divergent),
        f"divergent {field_name} binding was accepted",
    )
    _require(
        _snapshot(handle, command.record_id) == before,
        f"divergent {field_name} changed state or history",
    )


def _request_binding(adapter: AuthorityStoreAdapter) -> None:
    command = _command()
    record_id = command.record_id
    location, baseline_handle = _new_handle(adapter)
    try:
        baseline = baseline_handle.submit(command)
        initial = _snapshot(baseline_handle, record_id)
    finally:
        baseline_handle.close()
    previous_handle = baseline_handle
    for field_name in _REQUEST_BINDING_FIELDS:
        handle = adapter.open_handle(location)
        _require(handle is not previous_handle, "request binding reused prior handle")
        try:
            divergent = replace(command, **{field_name: f"different-{field_name}"})
            _expect_exception(
                BindingConflict,
                lambda h=handle, c=divergent: h.submit(c),
                f"divergent {field_name} was accepted",
            )
            _require(_snapshot(handle, record_id) == initial, "rejection mutated state")
            _require(handle.submit(command) == baseline, "exact replay changed value")
            _require(_snapshot(handle, record_id) == initial, "replay mutated state")
        finally:
            handle.close()
        previous_handle = handle
    reopened = adapter.open_handle(location)
    _require(reopened is not previous_handle, "final reopen reused prior handle")
    try:
        _require(_snapshot(reopened, record_id) == initial, "final reopen differs")
        _require(reopened.submit(command) == baseline, "final replay changed value")
        _require(_snapshot(reopened, record_id) == initial, "final replay mutated")
    finally:
        reopened.close()


def _lost_response(adapter: AuthorityStoreAdapter) -> None:
    command = _command()
    _, handle = _new_handle(adapter)
    _seed_heads(handle, command)
    _expect_exception(
        LostResponse,
        lambda: handle.submit(command, lose_response=True),
        "lost response was not raised after retention",
    )
    retained = _snapshot(handle, command.record_id)
    _require(retained[0] is not None, "lost response retained no state")
    for authority, _ in command.required_upstream_heads:
        handle.set_upstream_head(authority, "changed-after-write")
    _require(
        handle.submit(command) == AuthorityValue.from_command(command),
        "exact replay imposed use-time currentness",
    )
    _require(
        _snapshot(handle, command.record_id) == retained,
        "lost-response replay changed state or history",
    )
    handle.tamper(command.record_id, TamperKind.DIGEST)
    _expect_exception(
        IntegrityViolation,
        lambda: handle.submit(command),
        "lost-response replay accepted corrupt retained integrity",
    )


def _historical_fixture(adapter: AuthorityStoreAdapter, kind: TamperKind):
    _require(kind in _HISTORICAL_TAMPERS, "unknown historical tamper probe")
    first = _command()
    second = _command("record-2", "record-1", "beta")
    location, handle = _new_handle(adapter)
    handle.submit(first)
    handle.submit(second)
    handle.tamper(first.record_id, kind)
    return first, location, handle


def _historical_retained_operation(
    adapter: AuthorityStoreAdapter, *, listing: bool
) -> None:
    first = _command()
    second = _command("record-2", "record-1", "beta")
    expected = AuthorityValue.from_command(first)
    _, handle = _new_handle(adapter)
    handle.submit(first)
    handle.submit(second)
    if listing:
        _require(
            expected in handle.list_history(),
            "historical list omitted retained value",
        )
    else:
        _require(handle.read(first.record_id) == expected, "historical load differs")


def _historical_tamper_operation(
    adapter: AuthorityStoreAdapter,
    kind: TamperKind,
    *,
    reopened: bool,
    listing: bool,
) -> None:
    first, location, handle = _historical_fixture(adapter, kind)
    checked = handle
    if reopened:
        _expect_historical_corruption(handle, first, kind, False, listing)
        handle.close()
        checked = adapter.open_handle(location)
        _require(checked is not handle, "historical reopen returned original handle")
    _expect_historical_corruption(checked, first, kind, reopened, listing)


def _expect_historical_corruption(
    handle: AuthorityStoreHandle,
    command: WriteCommand,
    kind: TamperKind,
    reopened: bool,
    listing: bool,
) -> None:
    operation = (
        handle.list_history if listing else lambda: handle.read(command.record_id)
    )
    phase = "reopened" if reopened else "fresh"
    noun = "list" if listing else "read"
    _expect_exception(
        IntegrityViolation,
        operation,
        f"{phase} historical {noun} accepted {kind.value} mutation",
    )


def _historical_tamper(adapter: AuthorityStoreAdapter, kind: TamperKind) -> None:
    first = _command()
    second = _command("record-2", "record-1", "beta")
    expected = AuthorityValue.from_command(first)
    location, handle = _new_handle(adapter)
    handle.submit(first)
    handle.submit(second)
    _require(handle.read(first.record_id) == expected, "historical load differs")
    _require(
        expected in handle.list_history(), "historical list omitted retained value"
    )
    handle.tamper(first.record_id, kind)
    _expect_historical_corruption(handle, first, kind, False, False)
    _expect_historical_corruption(handle, first, kind, False, True)
    handle.close()
    reopened = adapter.open_handle(location)
    _require(reopened is not handle, "historical reopen returned original handle")
    _expect_historical_corruption(reopened, first, kind, True, False)
    _expect_historical_corruption(reopened, first, kind, True, True)


def _historical(adapter: AuthorityStoreAdapter) -> None:
    for kind in _HISTORICAL_TAMPERS:
        _historical_tamper(adapter, kind)


def _current_use_authority(adapter: AuthorityStoreAdapter, authority: str) -> None:
    _require(authority in _CURRENT_USE_AUTHORITIES, "unknown current-use probe")
    command = _command()
    _, handle = _new_handle(adapter)
    _seed_heads(handle, command)
    handle.submit(command)
    _require(
        handle.current_use(command.record_id) == AuthorityValue.from_command(command),
        "valid current-use read differs",
    )
    handle.set_upstream_head(authority, "changed")
    _expect_exception(
        IntegrityViolation,
        lambda: handle.current_use(command.record_id),
        f"changed {authority} head was accepted",
    )


def _current_use(adapter: AuthorityStoreAdapter) -> None:
    for authority in _CURRENT_USE_AUTHORITIES:
        _current_use_authority(adapter, authority)


def _tamper_rejection_kind(adapter: AuthorityStoreAdapter, kind: TamperKind) -> None:
    _require(kind in _TAMPER_REJECTION_TAMPERS, "unknown tamper rejection probe")
    _assert_tampers_rejected(adapter, (kind,))


def _tamper_rejection(adapter: AuthorityStoreAdapter) -> None:
    for kind in _TAMPER_REJECTION_TAMPERS:
        _tamper_rejection_kind(adapter, kind)


def _competing_writers(adapter: AuthorityStoreAdapter) -> None:
    location = adapter.create_location()
    first_handle = adapter.open_handle(location)
    second_handle = adapter.open_handle(location)
    _require(second_handle is not first_handle, "competing writers share one handle")
    first = _command("record-a", "record-0", "alpha")
    second = _command("record-b", "record-0", "beta")
    before_history = first_handle.history()
    barrier = Barrier(3)

    def submit(handle: AuthorityStoreHandle, command: WriteCommand) -> str:
        barrier.wait()
        try:
            handle.submit(command)
        except BindingConflict:
            return "conflict"
        return "success"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(submit, first_handle, first),
            executor.submit(submit, second_handle, second),
        )
        barrier.wait()
        outcomes = tuple(future.result() for future in futures)
    _require(
        sorted(outcomes) == ["conflict", "success"],
        "competing writers did not produce one winner and one conflict",
    )
    states = (
        first_handle.observe(first.record_id),
        first_handle.observe(second.record_id),
    )
    _require(
        sum(state is not None for state in states) == 1,
        "loser row retained or winner missing",
    )
    history = first_handle.history()
    _require(
        len(history) == len(before_history) + 1,
        "competing writers duplicated or omitted history",
    )
    winner = first if states[0] is not None else second
    _require(
        states[0] == StoredAuthorityState.from_command(first)
        if states[0] is not None
        else states[1] == StoredAuthorityState.from_command(second),
        "winning state differs from its submitted command",
    )
    _require(
        history[-1] == AuthorityValue.from_command(winner),
        "history retained the loser or a non-normative winner",
    )


def _rollback_sequence(adapter: AuthorityStoreAdapter) -> None:
    location, handle = _new_handle(adapter)
    before_history = handle.history()
    normal_command = _command("record-rollback-normal")
    normal_invocations = 0
    normal_complete = False

    def normal_operation(scope: RollbackScope) -> None:
        nonlocal normal_invocations, normal_complete
        normal_invocations += 1
        _require(
            normal_invocations == 1,
            "normal rollback scope invoked kernel callback more than once",
        )
        scope.submit(normal_command)
        _require(
            scope.observe(normal_command.record_id)
            == StoredAuthorityState.from_command(normal_command),
            "normal rollback scope cannot observe submitted state",
        )
        _require(
            scope.history()
            == before_history + (AuthorityValue.from_command(normal_command),),
            "normal rollback scope history did not append exactly once",
        )
        normal_complete = True

    try:
        handle.rollback_scope(normal_operation)
    except _CaseFailed:
        raise
    except Exception as exc:
        raise _CaseFailed(f"normal rollback scope raised {type(exc).__name__}") from exc
    _require(normal_invocations == 1, "normal rollback scope skipped kernel callback")
    _require(normal_complete, "normal rollback scope swallowed kernel inspection")
    _require(
        handle.observe(normal_command.record_id) is None,
        "normal rolled-back row remains visible on same handle",
    )
    _require(
        handle.history() == before_history,
        "normal rollback changed same-handle append-only history",
    )

    abort_command = _command("record-rollback-abort")
    abort_invocations = 0
    abort_complete = False
    sentinel = _RollbackInspectionAbort()

    def abort_operation(scope: RollbackScope) -> None:
        nonlocal abort_invocations, abort_complete
        abort_invocations += 1
        _require(
            abort_invocations == 1,
            "abort rollback scope invoked kernel callback more than once",
        )
        scope.submit(abort_command)
        _require(
            scope.observe(abort_command.record_id)
            == StoredAuthorityState.from_command(abort_command),
            "abort rollback scope cannot observe submitted state",
        )
        _require(
            scope.history()
            == before_history + (AuthorityValue.from_command(abort_command),),
            "abort rollback scope history did not append exactly once",
        )
        abort_complete = True
        raise sentinel

    abort_rethrown = False
    try:
        handle.rollback_scope(abort_operation)
    except Exception as exc:
        if exc is sentinel:
            abort_rethrown = True
        elif isinstance(exc, _CaseFailed):
            raise
        else:
            raise _CaseFailed(
                f"abort rollback scope raised {type(exc).__name__}"
            ) from exc
    _require(abort_invocations == 1, "abort rollback scope skipped kernel callback")
    _require(abort_complete, "abort rollback scope swallowed kernel inspection")
    _require(abort_rethrown, "abort rollback scope swallowed kernel sentinel")
    _require(
        handle.observe(abort_command.record_id) is None,
        "abort rolled-back row remains visible on same handle",
    )
    _require(
        handle.history() == before_history,
        "abort rollback changed same-handle append-only history",
    )

    handle.close()
    reopened = adapter.open_handle(location)
    _require(reopened is not handle, "post-rollback reopen returned original handle")
    for command in (normal_command, abort_command):
        _require(
            reopened.observe(command.record_id) is None,
            f"rolled-back row remains visible after reopen: {command.record_id}",
        )
    _require(
        reopened.history() == before_history,
        "rollback changed reopened append-only history",
    )


def _rollback_kind(adapter: AuthorityStoreAdapter, *, abort: bool) -> None:
    location, handle = _new_handle(adapter)
    before_history = handle.history()
    label = "abort" if abort else "normal"
    command = _command(f"record-rollback-{label}")
    invocations = 0
    inspection_complete = False
    sentinel = _RollbackInspectionAbort()

    def operation(scope: RollbackScope) -> None:
        nonlocal invocations, inspection_complete
        invocations += 1
        _require(invocations == 1, f"{label} rollback scope invoked callback twice")
        scope.submit(command)
        _require(
            scope.observe(command.record_id)
            == StoredAuthorityState.from_command(command),
            f"{label} rollback scope cannot observe submitted state",
        )
        _require(
            scope.history() == before_history + (AuthorityValue.from_command(command),),
            f"{label} rollback scope history did not append exactly once",
        )
        inspection_complete = True
        if abort:
            raise sentinel

    rethrown = False
    try:
        handle.rollback_scope(operation)
    except Exception as exc:
        if abort and exc is sentinel:
            rethrown = True
        elif isinstance(exc, _CaseFailed):
            raise
        else:
            raise _CaseFailed(
                f"{label} rollback scope raised {type(exc).__name__}"
            ) from exc
    _require(invocations == 1, f"{label} rollback scope skipped kernel callback")
    _require(inspection_complete, f"{label} rollback scope swallowed inspection")
    if abort:
        _require(rethrown, "abort rollback scope swallowed kernel sentinel")
    _require(
        handle.observe(command.record_id) is None,
        f"{label} rolled-back row remains visible on same handle",
    )
    _require(
        handle.history() == before_history,
        f"{label} rollback changed same-handle append-only history",
    )
    handle.close()
    reopened = adapter.open_handle(location)
    _require(reopened is not handle, "post-rollback reopen returned original handle")
    _require(
        reopened.observe(command.record_id) is None,
        f"rolled-back row remains visible after reopen: {command.record_id}",
    )
    _require(
        reopened.history() == before_history,
        "rollback changed reopened append-only history",
    )


def _restart_or_migrate(adapter: AuthorityStoreAdapter, *, migrate: bool) -> None:
    command = _command()
    location, original = _new_handle(adapter)
    original.submit(command)
    expected_value = AuthorityValue.from_command(command)
    expected_snapshot = _snapshot(original, command.record_id)
    original.close()
    restarted = adapter.open_handle(location)
    _require(restarted is not original, "restart returned original handle")
    _require(
        restarted.read(command.record_id) == expected_value, "restart read differs"
    )
    _require(
        _snapshot(restarted, command.record_id) == expected_snapshot,
        "restart changed state or history",
    )
    if not migrate:
        return
    restarted.close()
    migrated = adapter.open_handle(location, migrate=True)
    _require(migrated is not restarted, "migration returned prior handle")
    _require(
        migrated.read(command.record_id) == expected_value, "migration read differs"
    )
    _require(
        _snapshot(migrated, command.record_id) == expected_snapshot,
        "migration changed state or history",
    )


def _restart_migration(adapter: AuthorityStoreAdapter) -> None:
    _restart_or_migrate(adapter, migrate=True)


_SCENARIOS = {
    CaseId.FRESH_REPLAY: _fresh_replay,
    CaseId.FRESH_REOPEN: _fresh_reopen,
    CaseId.REPRESENTATION_BINDING: _representation,
    CaseId.REQUEST_BINDING: _request_binding,
    CaseId.LOST_RESPONSE_REPLAY: _lost_response,
    CaseId.HISTORICAL_READ: _historical,
    CaseId.CURRENT_USE_REVALIDATION: _current_use,
    CaseId.TAMPER_REJECTION: _tamper_rejection,
    CaseId.COMPETING_WRITERS: _competing_writers,
    CaseId.TRANSACTION_ROLLBACK: _rollback_sequence,
    CaseId.RESTART_MIGRATION: _restart_migration,
}


def _adapter_name(adapter: object) -> str:
    name = getattr(adapter, "name", None)
    return name if type(name) is str and name else type(adapter).__name__


def _manifest(
    adapter: object,
) -> tuple[dict[CaseId, Applicability], tuple[ConformanceFailure, ...]]:
    raw = getattr(adapter, "applicability", None)
    if not isinstance(raw, Mapping):
        return {}, (
            ConformanceFailure(
                None, FailureCode.ADAPTER_PROTOCOL, "applicability mapping is required"
            ),
        )
    manifest: dict[CaseId, Applicability] = {}
    failures: list[ConformanceFailure] = []
    for case in CASE_INVENTORY:
        entry = raw.get(case)
        if type(entry) is not Applicability:
            detail = (
                f"applicability missing {case.value}"
                if entry is None
                else f"invalid applicability for {case.value}"
            )
            failures.append(
                ConformanceFailure(case, FailureCode.ADAPTER_PROTOCOL, detail)
            )
            continue
        malformed = (
            type(entry.supported) is not bool
            or (entry.reason is not None and type(entry.reason) is not str)
            or (
                entry.waiver_reference is not None
                and type(entry.waiver_reference) is not str
            )
        )
        if malformed:
            failures.append(
                ConformanceFailure(
                    case,
                    FailureCode.ADAPTER_PROTOCOL,
                    f"malformed applicability fields for {case.value}",
                )
            )
            continue
        if entry.supported and (
            entry.reason is not None or entry.waiver_reference is not None
        ):
            failures.append(
                ConformanceFailure(
                    case,
                    FailureCode.ADAPTER_PROTOCOL,
                    f"supported case {case.value} must not declare waiver metadata",
                )
            )
        elif not entry.supported and (
            not entry.reason
            or not entry.reason.strip()
            or not entry.waiver_reference
            or not entry.waiver_reference.strip()
        ):
            failures.append(
                ConformanceFailure(
                    case,
                    FailureCode.ADAPTER_PROTOCOL,
                    f"waived case {case.value} requires reason and waiver reference",
                )
            )
        manifest[case] = entry
    known_count = sum(case in raw for case in CASE_INVENTORY)
    if len(raw) != known_count:
        failures.append(
            ConformanceFailure(
                None, FailureCode.ADAPTER_PROTOCOL, "unknown applicability entries"
            )
        )
    return manifest, tuple(failures)


def run_conformance(adapter: AuthorityStoreAdapter) -> ConformanceReport:
    name = _adapter_name(adapter)
    manifest, protocol_failures = _manifest(adapter)
    missing = tuple(
        method
        for method in ("create_location", "open_handle")
        if not callable(getattr(adapter, method, None))
    )
    if missing:
        protocol_failures += (
            ConformanceFailure(
                None,
                FailureCode.ADAPTER_PROTOCOL,
                "missing operations: " + ",".join(missing),
            ),
        )
    if protocol_failures:
        return ConformanceReport(
            name,
            tuple(CaseOutcome(case, OutcomeStatus.SKIPPED) for case in CASE_INVENTORY),
            protocol_failures,
        )

    outcomes: list[CaseOutcome] = []
    for case in CASE_INVENTORY:
        applicability = manifest[case]
        if not applicability.supported:
            outcomes.append(
                CaseOutcome(
                    case,
                    OutcomeStatus.SKIPPED,
                    waiver_reason=applicability.reason,
                    waiver_reference=applicability.waiver_reference,
                )
            )
            continue
        try:
            _SCENARIOS[case](adapter)
        except _CaseFailed as exc:
            failure = ConformanceFailure(case, _CASE_FAILURES[case], str(exc))
            outcomes.append(CaseOutcome(case, OutcomeStatus.FAIL, (failure,)))
        except StoreOperationError as exc:
            failure = ConformanceFailure(
                case,
                _CASE_FAILURES[case],
                f"unexpected store rejection {type(exc).__name__}",
            )
            outcomes.append(CaseOutcome(case, OutcomeStatus.FAIL, (failure,)))
        except Exception as exc:  # noqa: BLE001 - deterministic adapter classification
            failure = ConformanceFailure(
                case, FailureCode.ADAPTER_ERROR, f"scenario raised {type(exc).__name__}"
            )
            outcomes.append(CaseOutcome(case, OutcomeStatus.FAIL, (failure,)))
        else:
            outcomes.append(CaseOutcome(case, OutcomeStatus.PASS))
    return ConformanceReport(name, tuple(outcomes))


def assert_conformant(adapter: AuthorityStoreAdapter) -> ConformanceReport:
    report = run_conformance(adapter)
    if not report.passed:
        raise AuthorityStoreConformanceError(report)
    return report


__all__ = [
    "CASE_INVENTORY",
    "Applicability",
    "AuthorityStoreAdapter",
    "AuthorityStoreConformanceError",
    "AuthorityStoreHandle",
    "AuthorityValue",
    "BindingConflict",
    "CaseId",
    "CaseOutcome",
    "ConformanceFailure",
    "ConformanceReport",
    "FailureCode",
    "IntegrityViolation",
    "LostResponse",
    "OutcomeStatus",
    "RollbackOperation",
    "RollbackScope",
    "StoredAuthorityState",
    "TamperKind",
    "WriteCommand",
    "assert_conformant",
    "run_conformance",
]
