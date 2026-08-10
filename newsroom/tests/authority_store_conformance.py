"""Test-only authority-store conformance kernel.

Adapters expose store operations and observable persisted state.  The kernel,
not the adapter, owns the commands, scenario order and normative assertions.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
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


class WriteConflict(StoreOperationError):
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
        return cls(supported=True)

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
            record_id=command.record_id,
            value=command.scalar_columns["value"],
            digest=_command_digest(command),
            provenance=command.request,
        )


@runtime_checkable
class AuthorityStoreAdapter(Protocol):
    """Primitive store operations required by the generic scenario kernel."""

    name: str
    applicability: Mapping[CaseId, Applicability]

    def reset(self) -> None: ...
    def put(
        self, command: WriteCommand, *, lose_response: bool = False
    ) -> AuthorityValue: ...
    def replay(self, command: WriteCommand) -> AuthorityValue: ...
    def observe(self, record_id: str) -> StoredAuthorityState | None: ...
    def load(self, record_id: str) -> AuthorityValue: ...
    def list_history(self) -> tuple[AuthorityValue, ...]: ...
    def set_upstream_head(self, authority: str, value: str) -> None: ...
    def current_use(self, record_id: str) -> AuthorityValue: ...
    def tamper(self, record_id: str, kind: TamperKind) -> None: ...
    def reopen(self, *, migrate: bool) -> None: ...
    def rollback(self, command: WriteCommand) -> None: ...


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
            if outcome.status is OutcomeStatus.SKIPPED:
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
        canonical_bytes=(f'{{"value":"{value}"}}').encode(),
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


def _seed_heads(adapter: AuthorityStoreAdapter, command: WriteCommand) -> None:
    for authority, head in command.required_upstream_heads:
        adapter.set_upstream_head(authority, head)


def _fresh_replay(adapter: AuthorityStoreAdapter) -> None:
    command = _command()
    adapter.reset()
    _require(adapter.observe(command.record_id) is None, "record existed before write")
    expected = AuthorityValue.from_command(command)
    _require(adapter.put(command) == expected, "fresh write result is not normative")
    _require(adapter.replay(command) == expected, "exact replay result differs")
    _require(adapter.observe(command.record_id) is not None, "write retained no state")


def _fresh_reopen(adapter: AuthorityStoreAdapter) -> None:
    command = _command()
    adapter.reset()
    adapter.put(command)
    adapter.reopen(migrate=False)
    _require(
        adapter.load(command.record_id) == AuthorityValue.from_command(command),
        "reopened load differs",
    )


def _representation(adapter: AuthorityStoreAdapter) -> None:
    command = _command()
    adapter.reset()
    adapter.put(command)
    _require(
        adapter.observe(command.record_id)
        == StoredAuthorityState.from_command(command),
        "persisted canonical/scalar/identity/linked representation differs",
    )


def _request_binding(adapter: AuthorityStoreAdapter) -> None:
    command = _command()
    adapter.reset()
    adapter.put(command)
    state = adapter.observe(command.record_id)
    _require(state is not None, "persisted state is absent")
    _require(
        (state.actor, state.request, state.idempotency, state.cas_predecessor)
        == (
            command.actor,
            command.request,
            command.idempotency,
            command.cas_predecessor,
        ),
        "actor/request/idempotency/CAS predecessor differs",
    )


def _lost_response(adapter: AuthorityStoreAdapter) -> None:
    command = _command()
    adapter.reset()
    _seed_heads(adapter, command)
    _expect_exception(
        LostResponse,
        lambda: adapter.put(command, lose_response=True),
        "lost response was not simulated after retention",
    )
    _require(
        adapter.observe(command.record_id) is not None, "lost response retained no row"
    )
    for authority, _ in command.required_upstream_heads:
        adapter.set_upstream_head(authority, "changed-after-write")
    _require(
        adapter.replay(command) == AuthorityValue.from_command(command),
        "replay imposed use-time currentness",
    )
    adapter.reset()
    _expect_exception(
        LostResponse,
        lambda: adapter.put(command, lose_response=True),
        "lost response was not simulated",
    )
    adapter.tamper(command.record_id, TamperKind.DIGEST)
    _expect_exception(
        IntegrityViolation,
        lambda: adapter.replay(command),
        "replay accepted corrupt retained integrity",
    )


def _historical(adapter: AuthorityStoreAdapter) -> None:
    first = _command()
    second = _command("record-2", "record-1", "beta")
    expected_first = AuthorityValue.from_command(first)
    for tamper in (TamperKind.IDENTITY, TamperKind.DIGEST, TamperKind.PROVENANCE):
        adapter.reset()
        adapter.put(first)
        adapter.put(second)
        _require(
            adapter.load(first.record_id) == expected_first, "historical load differs"
        )
        _require(
            expected_first in adapter.list_history(),
            "historical list omitted retained value",
        )
        adapter.tamper(first.record_id, tamper)
        _expect_exception(
            IntegrityViolation,
            lambda: adapter.load(first.record_id),
            f"historical load accepted {tamper.value} tamper",
        )
        _expect_exception(
            IntegrityViolation,
            adapter.list_history,
            f"historical list accepted {tamper.value} tamper",
        )


def _current_use(adapter: AuthorityStoreAdapter) -> None:
    command = _command()
    for changed_authority, _ in command.required_upstream_heads:
        adapter.reset()
        _seed_heads(adapter, command)
        adapter.put(command)
        _require(
            adapter.current_use(command.record_id)
            == AuthorityValue.from_command(command),
            "valid current-use read differs",
        )
        adapter.set_upstream_head(changed_authority, "changed")
        _expect_exception(
            IntegrityViolation,
            lambda: adapter.current_use(command.record_id),
            f"changed {changed_authority} head was accepted",
        )


def _tamper_rejection(adapter: AuthorityStoreAdapter) -> None:
    command = _command()
    for tamper in (
        TamperKind.CANONICAL,
        TamperKind.LINKED_ROW,
        TamperKind.OFFLINE_REWRITE,
    ):
        adapter.reset()
        adapter.put(command)
        adapter.tamper(command.record_id, tamper)
        _expect_exception(
            IntegrityViolation,
            lambda: adapter.load(command.record_id),
            f"{tamper.value} mutation was accepted",
        )


def _competing_writers(adapter: AuthorityStoreAdapter) -> None:
    first = _command("record-a", "record-0", "alpha")
    second = _command("record-b", "record-0", "beta")
    adapter.reset()
    adapter.put(first)
    _expect_exception(
        WriteConflict,
        lambda: adapter.put(second),
        "second same-predecessor writer was accepted",
    )
    _require(adapter.observe(first.record_id) is not None, "winning write disappeared")
    _require(adapter.observe(second.record_id) is None, "losing write was retained")


def _rollback(adapter: AuthorityStoreAdapter) -> None:
    command = _command()
    adapter.reset()
    adapter.rollback(command)
    _require(
        adapter.observe(command.record_id) is None, "rolled-back row remains visible"
    )
    _require(adapter.list_history() == (), "rolled-back row remains in history")


def _restart_migration(adapter: AuthorityStoreAdapter) -> None:
    command = _command()
    expected = AuthorityValue.from_command(command)
    adapter.reset()
    adapter.put(command)
    adapter.reopen(migrate=False)
    _require(
        adapter.load(command.record_id) == expected, "restart/reopen changed value"
    )
    adapter.reopen(migrate=True)
    _require(
        adapter.load(command.record_id) == expected, "migration/reopen changed value"
    )
    _require(
        adapter.observe(command.record_id)
        == StoredAuthorityState.from_command(command),
        "migration/reopen changed persisted representation",
    )


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
    CaseId.TRANSACTION_ROLLBACK: _rollback,
    CaseId.RESTART_MIGRATION: _restart_migration,
}


def _adapter_name(adapter: object) -> str:
    name = getattr(adapter, "name", None)
    return name if isinstance(name, str) and name else type(adapter).__name__


def _manifest(
    adapter: object,
) -> tuple[dict[CaseId, Applicability], tuple[ConformanceFailure, ...]]:
    raw = getattr(adapter, "applicability", None)
    failures: list[ConformanceFailure] = []
    if not isinstance(raw, Mapping):
        return {}, (
            ConformanceFailure(
                None, FailureCode.ADAPTER_PROTOCOL, "applicability mapping is required"
            ),
        )
    manifest: dict[CaseId, Applicability] = {}
    for case in CASE_INVENTORY:
        entry = raw.get(case)
        if entry is None:
            failures.append(
                ConformanceFailure(
                    case,
                    FailureCode.ADAPTER_PROTOCOL,
                    f"applicability missing {case.value}",
                )
            )
            continue
        if not isinstance(entry, Applicability):
            failures.append(
                ConformanceFailure(
                    case,
                    FailureCode.ADAPTER_PROTOCOL,
                    f"invalid applicability for {case.value}",
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
        if not entry.supported and (
            not (entry.reason or "").strip()
            or not (entry.waiver_reference or "").strip()
        ):
            failures.append(
                ConformanceFailure(
                    case,
                    FailureCode.ADAPTER_PROTOCOL,
                    f"waived case {case.value} requires reason and waiver reference",
                )
            )
        manifest[case] = entry
    unknown = sorted(str(key) for key in raw if key not in CASE_INVENTORY)
    for key in unknown:
        failures.append(
            ConformanceFailure(
                None, FailureCode.ADAPTER_PROTOCOL, f"unknown applicability case {key}"
            )
        )
    return manifest, tuple(failures)


def run_conformance(adapter: AuthorityStoreAdapter) -> ConformanceReport:
    """Execute fixed scenarios in inventory order against primitive operations."""

    name = _adapter_name(adapter)
    manifest, protocol_failures = _manifest(adapter)
    required_methods = (
        "reset",
        "put",
        "replay",
        "observe",
        "load",
        "list_history",
        "set_upstream_head",
        "current_use",
        "tamper",
        "reopen",
        "rollback",
    )
    missing = tuple(
        method
        for method in required_methods
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
        except Exception as exc:  # noqa: BLE001 - classify adapter failures
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
    "AuthorityValue",
    "CaseId",
    "CaseOutcome",
    "ConformanceFailure",
    "ConformanceReport",
    "FailureCode",
    "IntegrityViolation",
    "LostResponse",
    "OutcomeStatus",
    "StoredAuthorityState",
    "TamperKind",
    "WriteCommand",
    "WriteConflict",
    "assert_conformant",
    "run_conformance",
]
