"""Generic, adapter-driven authority-store conformance checks.

This module is deliberately test-only.  A persistence implementation supplies a
small adapter and declares the invariant families it can exercise; the kernel
then compares typed observations in a fixed order and emits stable failure
codes.  Store-specific schemas, names and operations remain in the adapter.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class CaseId(str, Enum):
    """Invariant families understood by the reusable harness."""

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


# The order is part of the protocol: reports and focused CI output must not
# depend on set/dict iteration order in an adapter.
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
    """Stable machine-readable failure classifications."""

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


@dataclass(frozen=True)
class AuthorityStoreRepresentation:
    """The mutually-bound persisted forms returned by an adapter."""

    canonical_bytes: bytes
    scalar_columns: Mapping[str, Any]
    identity_columns: Mapping[str, Any]
    linked_rows: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class AuthorityStoreBinding:
    """Opaque values that must bind an accepted write to its caller/request."""

    actor: Any
    request: Any
    idempotency: Any
    cas_predecessor: Any


@dataclass(frozen=True)
class HistoricalAuthorityValue:
    """A retained value and the identity/digest/provenance that authenticates it."""

    identity: Any
    digest: Any
    provenance: Any
    value: Any


@dataclass(frozen=True)
class CurrentUseExpectation:
    """Upstream authority heads that a current-use read must revalidate."""

    upstream_heads: tuple[Any, ...]
    rejected_after_head_change: bool = True


@dataclass(frozen=True)
class TamperExpectation:
    """Named mutation probes supplied by an adapter (names are not interpreted)."""

    mutation_kinds: tuple[str, ...]


@dataclass(frozen=True)
class LifecycleExpectation:
    """Deterministic transaction and restart outcomes expected from a store."""

    competing_writers_deterministic: bool = True
    rollback_clean: bool = True
    restart_reopen: bool = True
    migration_reopen: bool = True


@dataclass(frozen=True)
class AuthorityStoreFixture:
    """Adapter-owned expected values for the cases it declares."""

    representation: AuthorityStoreRepresentation | None = None
    binding: AuthorityStoreBinding | None = None
    historical_values: tuple[HistoricalAuthorityValue, ...] | None = None
    current_use: CurrentUseExpectation | None = None
    tamper: TamperExpectation | None = None
    lifecycle: LifecycleExpectation | None = None
    # A lost response is a retained-result replay.  It must not acquire an
    # unrelated use-time currentness check merely because the response was lost.
    lost_response_use_currentness: bool = False


_UNSET = object()


@dataclass(frozen=True)
class LifecycleEvidence:
    competing_writers_deterministic: bool | None = None
    rollback_clean: bool | None = None
    restart_reopen: bool | None = None
    migration_reopen: bool | None = None


@dataclass(frozen=True)
class ConformanceEvidence:
    """One adapter exercise result, with opaque values kept out of the kernel."""

    fresh_result: Any = _UNSET
    replay_result: Any = _UNSET
    reopened_result: Any = _UNSET
    representation: AuthorityStoreRepresentation | None = None
    binding: AuthorityStoreBinding | None = None
    lost_response_result: Any = _UNSET
    lost_response_integrity_validated: bool | None = None
    lost_response_used_currentness: bool | None = None
    historical_values: tuple[HistoricalAuthorityValue, ...] | None = None
    current_use_checked_heads: tuple[Any, ...] | None = None
    current_use_rejected_after_head_change: bool | None = None
    tamper_rejected: Mapping[str, bool] | None = None
    lifecycle: LifecycleEvidence | None = None


@runtime_checkable
class AuthorityStoreAdapter(Protocol):
    """Minimal adapter protocol implemented by a store-specific test fixture."""

    name: str
    supported_cases: Collection[CaseId | str]

    def build_fixture(self) -> AuthorityStoreFixture:
        """Return expected values for the declared cases."""

    def exercise_case(
        self, case: CaseId, fixture: AuthorityStoreFixture
    ) -> ConformanceEvidence:
        """Execute one deterministic case and return typed observations."""


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


@dataclass(frozen=True)
class ConformanceReport:
    adapter_name: str
    supported_cases: tuple[CaseId, ...]
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
        """Render stable, value-independent lines suitable for CI artefacts."""

        lines = [f"adapter={self.adapter_name}"]
        lines.extend(
            f"protocol failure code={failure.code.value}"
            for failure in self.protocol_failures
        )
        lines.extend(
            f"case={outcome.case.value} status={outcome.status.value}"
            + (
                " codes=" + ",".join(failure.code.value for failure in outcome.failures)
                if outcome.failures
                else ""
            )
            for outcome in self.outcomes
        )
        return tuple(lines)


class AuthorityStoreConformanceError(AssertionError):
    """Raised by :func:`assert_conformant` with deterministic report lines."""

    def __init__(self, report: ConformanceReport) -> None:
        self.report = report
        super().__init__("\n".join(report.render()))


_CASE_FAILURES: dict[CaseId, FailureCode] = {
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


def _case_failure(case: CaseId, detail: str) -> ConformanceFailure:
    return ConformanceFailure(case=case, code=_CASE_FAILURES[case], detail=detail)


def _check_case(
    case: CaseId,
    fixture: AuthorityStoreFixture,
    evidence: ConformanceEvidence,
) -> tuple[ConformanceFailure, ...]:
    """Check one case without interpreting adapter-specific values."""

    failures: list[ConformanceFailure] = []
    if case is CaseId.FRESH_REPLAY:
        if evidence.fresh_result is _UNSET or evidence.replay_result is _UNSET:
            failures.append(
                _case_failure(case, "fresh and replay results are required")
            )
        elif evidence.fresh_result != evidence.replay_result:
            failures.append(_case_failure(case, "fresh and replay results differ"))
    elif case is CaseId.FRESH_REOPEN:
        if evidence.fresh_result is _UNSET or evidence.reopened_result is _UNSET:
            failures.append(
                _case_failure(case, "fresh and reopened results are required")
            )
        elif evidence.fresh_result != evidence.reopened_result:
            failures.append(_case_failure(case, "fresh and reopened results differ"))
    elif case is CaseId.REPRESENTATION_BINDING:
        expected = fixture.representation
        actual = evidence.representation
        if expected is None or actual is None:
            failures.append(
                _case_failure(case, "expected and observed representation are required")
            )
        elif actual != expected:
            failures.append(
                _case_failure(
                    case, "canonical, scalar, identity or linked forms differ"
                )
            )
    elif case is CaseId.REQUEST_BINDING:
        if fixture.binding is None or evidence.binding is None:
            failures.append(
                _case_failure(
                    case, "expected and observed request bindings are required"
                )
            )
        elif evidence.binding != fixture.binding:
            failures.append(
                _case_failure(case, "actor/request/idempotency/CAS binding differs")
            )
    elif case is CaseId.LOST_RESPONSE_REPLAY:
        if evidence.fresh_result is _UNSET or evidence.lost_response_result is _UNSET:
            failures.append(
                _case_failure(
                    case, "fresh and lost-response replay results are required"
                )
            )
        elif evidence.fresh_result != evidence.lost_response_result:
            failures.append(
                _case_failure(case, "lost-response replay differs from retained result")
            )
        if evidence.lost_response_integrity_validated is not True:
            failures.append(
                _case_failure(case, "retained integrity was not revalidated")
            )
        if evidence.lost_response_used_currentness is None:
            failures.append(
                _case_failure(case, "lost-response currentness observation is required")
            )
        elif (
            evidence.lost_response_used_currentness
            != fixture.lost_response_use_currentness
        ):
            failures.append(
                _case_failure(
                    case, "lost-response replay applied unrelated currentness"
                )
            )
    elif case is CaseId.HISTORICAL_READ:
        if fixture.historical_values is None or evidence.historical_values is None:
            failures.append(
                _case_failure(
                    case, "expected and observed historical values are required"
                )
            )
        elif evidence.historical_values != fixture.historical_values:
            failures.append(
                _case_failure(case, "historical identity/digest/provenance differs")
            )
    elif case is CaseId.CURRENT_USE_REVALIDATION:
        expected = fixture.current_use
        if expected is None or evidence.current_use_checked_heads is None:
            failures.append(
                _case_failure(case, "expected and observed upstream heads are required")
            )
        elif evidence.current_use_checked_heads != expected.upstream_heads:
            failures.append(
                _case_failure(case, "not every required upstream head was checked")
            )
        if (
            expected is not None
            and evidence.current_use_rejected_after_head_change
            != expected.rejected_after_head_change
        ):
            failures.append(
                _case_failure(case, "changed upstream head was not rejected")
            )
    elif case is CaseId.TAMPER_REJECTION:
        expected = fixture.tamper
        actual = evidence.tamper_rejected
        if expected is None or actual is None:
            failures.append(
                _case_failure(case, "expected and observed tamper probes are required")
            )
        elif set(actual) != set(expected.mutation_kinds) or any(
            actual.get(kind) is not True for kind in expected.mutation_kinds
        ):
            failures.append(
                _case_failure(case, "a declared tamper mutation was accepted")
            )
    elif case is CaseId.COMPETING_WRITERS:
        expected = fixture.lifecycle
        actual = evidence.lifecycle
        if (
            expected is None
            or actual is None
            or actual.competing_writers_deterministic
            != expected.competing_writers_deterministic
        ):
            failures.append(
                _case_failure(case, "competing-writer outcome is not deterministic")
            )
    elif case is CaseId.TRANSACTION_ROLLBACK:
        expected = fixture.lifecycle
        actual = evidence.lifecycle
        if (
            expected is None
            or actual is None
            or actual.rollback_clean != expected.rollback_clean
        ):
            failures.append(_case_failure(case, "rollback did not leave a clean store"))
    elif case is CaseId.RESTART_MIGRATION:
        expected = fixture.lifecycle
        actual = evidence.lifecycle
        if (
            expected is None
            or actual is None
            or actual.restart_reopen != expected.restart_reopen
            or actual.migration_reopen != expected.migration_reopen
        ):
            failures.append(_case_failure(case, "restart or migration reopen differs"))
    return tuple(failures)


def _adapter_name(adapter: object) -> str:
    value = getattr(adapter, "name", None)
    return value if isinstance(value, str) and value else type(adapter).__name__


def _normalise_supported(
    adapter: object,
) -> tuple[tuple[CaseId, ...], tuple[ConformanceFailure, ...]]:
    raw = getattr(adapter, "supported_cases", None)
    if raw is None:
        return (), (
            ConformanceFailure(
                case=None,
                code=FailureCode.ADAPTER_PROTOCOL,
                detail="supported_cases is required",
            ),
        )
    supported: set[CaseId] = set()
    failures: list[ConformanceFailure] = []
    try:
        values = tuple(raw)
    except TypeError:
        return (), (
            ConformanceFailure(
                case=None,
                code=FailureCode.ADAPTER_PROTOCOL,
                detail="supported_cases must be iterable",
            ),
        )
    for value in values:
        try:
            supported.add(value if isinstance(value, CaseId) else CaseId(value))
        except (TypeError, ValueError):
            failures.append(
                ConformanceFailure(
                    case=None,
                    code=FailureCode.ADAPTER_PROTOCOL,
                    detail=f"unknown supported case: {value!s}",
                )
            )
    ordered = tuple(case for case in CASE_INVENTORY if case in supported)
    return ordered, tuple(failures)


def run_conformance(adapter: AuthorityStoreAdapter) -> ConformanceReport:
    """Run all declared invariant families in deterministic inventory order."""

    adapter_name = _adapter_name(adapter)
    supported, protocol_failures = _normalise_supported(adapter)
    if not protocol_failures and not supported:
        protocol_failures = (
            ConformanceFailure(
                case=None,
                code=FailureCode.ADAPTER_PROTOCOL,
                detail="at least one supported case is required",
            ),
        )
    if protocol_failures:
        return ConformanceReport(
            adapter_name=adapter_name,
            supported_cases=supported,
            outcomes=tuple(
                CaseOutcome(case=case, status=OutcomeStatus.SKIPPED)
                for case in CASE_INVENTORY
            ),
            protocol_failures=protocol_failures,
        )

    build_fixture = getattr(adapter, "build_fixture", None)
    exercise_case = getattr(adapter, "exercise_case", None)
    if not callable(build_fixture) or not callable(exercise_case):
        return ConformanceReport(
            adapter_name=adapter_name,
            supported_cases=supported,
            outcomes=tuple(
                CaseOutcome(case=case, status=OutcomeStatus.SKIPPED)
                for case in CASE_INVENTORY
            ),
            protocol_failures=(
                ConformanceFailure(
                    case=None,
                    code=FailureCode.ADAPTER_PROTOCOL,
                    detail="build_fixture and exercise_case are required",
                ),
            ),
        )

    try:
        fixture = build_fixture()
    except Exception as exc:  # noqa: BLE001 - classify adapter failures deterministically
        return ConformanceReport(
            adapter_name=adapter_name,
            supported_cases=supported,
            outcomes=tuple(
                CaseOutcome(case=case, status=OutcomeStatus.SKIPPED)
                for case in CASE_INVENTORY
            ),
            protocol_failures=(
                ConformanceFailure(
                    case=None,
                    code=FailureCode.ADAPTER_ERROR,
                    detail=f"build_fixture raised {type(exc).__name__}",
                ),
            ),
        )
    if not isinstance(fixture, AuthorityStoreFixture):
        return ConformanceReport(
            adapter_name=adapter_name,
            supported_cases=supported,
            outcomes=tuple(
                CaseOutcome(case=case, status=OutcomeStatus.SKIPPED)
                for case in CASE_INVENTORY
            ),
            protocol_failures=(
                ConformanceFailure(
                    case=None,
                    code=FailureCode.ADAPTER_PROTOCOL,
                    detail="build_fixture must return AuthorityStoreFixture",
                ),
            ),
        )

    outcomes: list[CaseOutcome] = []
    for case in CASE_INVENTORY:
        if case not in supported:
            outcomes.append(CaseOutcome(case=case, status=OutcomeStatus.SKIPPED))
            continue
        try:
            evidence = exercise_case(case, fixture)
        except Exception as exc:  # noqa: BLE001 - classify adapter failures deterministically
            outcomes.append(
                CaseOutcome(
                    case=case,
                    status=OutcomeStatus.FAIL,
                    failures=(
                        ConformanceFailure(
                            case=case,
                            code=FailureCode.ADAPTER_ERROR,
                            detail=f"exercise_case raised {type(exc).__name__}",
                        ),
                    ),
                )
            )
            continue
        if not isinstance(evidence, ConformanceEvidence):
            outcomes.append(
                CaseOutcome(
                    case=case,
                    status=OutcomeStatus.FAIL,
                    failures=(
                        ConformanceFailure(
                            case=case,
                            code=FailureCode.ADAPTER_PROTOCOL,
                            detail="exercise_case must return ConformanceEvidence",
                        ),
                    ),
                )
            )
            continue
        failures = _check_case(case, fixture, evidence)
        outcomes.append(
            CaseOutcome(
                case=case,
                status=OutcomeStatus.FAIL if failures else OutcomeStatus.PASS,
                failures=failures,
            )
        )
    return ConformanceReport(
        adapter_name=adapter_name,
        supported_cases=supported,
        outcomes=tuple(outcomes),
    )


def assert_conformant(adapter: AuthorityStoreAdapter) -> ConformanceReport:
    """Run the harness and raise with the deterministic report if it fails."""

    report = run_conformance(adapter)
    if not report.passed:
        raise AuthorityStoreConformanceError(report)
    return report


__all__ = [
    "CASE_INVENTORY",
    "AuthorityStoreAdapter",
    "AuthorityStoreBinding",
    "AuthorityStoreConformanceError",
    "AuthorityStoreFixture",
    "AuthorityStoreRepresentation",
    "CaseId",
    "CaseOutcome",
    "ConformanceEvidence",
    "ConformanceFailure",
    "ConformanceReport",
    "CurrentUseExpectation",
    "FailureCode",
    "HistoricalAuthorityValue",
    "LifecycleEvidence",
    "LifecycleExpectation",
    "OutcomeStatus",
    "TamperExpectation",
    "assert_conformant",
    "run_conformance",
]
