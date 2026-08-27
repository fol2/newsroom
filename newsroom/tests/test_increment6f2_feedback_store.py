from __future__ import annotations

import pickle
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import ClassVar

import pytest

from newsroom.authority.evaluation_feedback_system import (
    _open_unlocked_evaluation_feedback_authority_for_test,
)
from newsroom.authority.migrations import (
    apply_pending_migrations,
    prepare_pending_migration_backup,
)
from newsroom.increment6.feedback import (
    EvaluationFeedbackOutcome,
    EvaluationFeedbackReason,
    FeedbackContractError,
    ReconciliationDispositionOutcome,
    ReconciliationDispositionReason,
    append_reconciliation_disposition,
    create_evaluation_feedback,
    create_reconciliation_obligation,
)
from newsroom.increment6.handoffs import (
    Acknowledgement,
    AcknowledgementOutcome,
    EvaluationHandoffStore,
    create_handoff,
)
from newsroom.tests import test_increment6e2_candidate_store as candidate_fixture
from newsroom.tests import test_increment6f2_feedback_system as system_fixture
from newsroom.tests.authority_store_conformance import (
    _CURRENT_USE_AUTHORITIES,
    _HISTORICAL_TAMPERS,
    _REPRESENTATION_TAMPERS,
    _REQUEST_BINDING_FIELDS,
    _SCENARIOS,
    _TAMPER_REJECTION_TAMPERS,
    CASE_INVENTORY,
    Applicability,
    AuthorityValue,
    BindingConflict,
    CaseId,
    IntegrityViolation,
    LostResponse,
    StoredAuthorityState,
    TamperKind,
    WriteCommand,
    _current_use_authority,
    _exact_replay,
    _fresh_reopen_digest,
    _fresh_reopen_persistence,
    _fresh_submission,
    _historical_retained_operation,
    _historical_tamper_operation,
    _representation_retained,
    _representation_tamper,
    _request_binding_field,
    _restart_or_migrate,
    _rollback_kind,
    _rollback_sequence,
    _tamper_rejection_kind,
)


def _encoded(command: WriteCommand) -> str:
    heads = ",".join(f"{name}={head}" for name, head in command.required_upstream_heads)
    return "|".join(
        (
            "cf",
            command.record_id,
            str(command.scalar_columns["value"]),
            command.cas_predecessor,
            command.actor,
            command.request,
            command.idempotency,
            heads,
        )
    )


def _decoded(value: str) -> WriteCommand:
    if not value.startswith("cf|"):
        raise KeyError(value)
    prefix, record_id, scalar, predecessor, actor, request, idempotency, raw_heads = (
        value.split("|", 7)
    )
    if prefix != "cf":
        raise KeyError(value)
    return replace(
        candidate_fixture._generic(record_id, predecessor, scalar),
        actor=actor,
        request=request,
        idempotency=idempotency,
        required_upstream_heads=tuple(
            tuple(item.split("=", 1)) for item in raw_heads.split(",")
        ),
    )


def _database_locked(error: BaseException) -> bool:
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, sqlite3.OperationalError) and any(
            marker in str(current).lower() for marker in ("locked", "busy")
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


@dataclass
class _Location:
    candidate: object
    args: dict[str, object]
    fixtures: dict[str, tuple[object, object]]
    proof: object
    base: tuple[object, object]
    competing: dict[str, object]


@dataclass(frozen=True)
class _LocationSnapshot:
    database_bytes: bytes
    seed_tail: tuple
    args: dict[str, object]
    fixtures: dict[str, tuple[object, ...]]
    proof: object
    base: tuple[object, object]
    competing: dict[str, object]

    def clone(self, root: Path) -> _Location:
        root.mkdir(mode=0o700)
        database = root / "feedback-authority.sqlite3"
        database.write_bytes(self.database_bytes)
        database.chmod(0o600)
        collaborators = pickle.loads(
            pickle.dumps(self.seed_tail[0], protocol=pickle.HIGHEST_PROTOCOL)
        )
        retrieval = collaborators[1]
        retrieval_path = root / "retrieval-context.sqlite3"
        retrieval_path.write_bytes(Path(retrieval._path).read_bytes())
        retrieval_path.chmod(0o600)
        retrieval._path = retrieval_path
        seed = (collaborators, database, *self.seed_tail[1:])
        candidate = candidate_fixture._Location(seed, root / "candidate-collisions")
        args = dict(self.args)
        args["database"] = database
        args["retrieval_authority"] = retrieval
        return _Location(
            candidate,
            args,
            self.fixtures,
            self.proof,
            self.base,
            self.competing,
        )


_LOCATION_SNAPSHOTS: dict[tuple[str, ...], _LocationSnapshot] = {}


def _fixture(location, version, actor, command: WriteCommand, number: int):
    store = EvaluationHandoffStore(
        sqlite3.connect(location.seed[1], isolation_level=None)
    )
    handoff = store.register(
        create_handoff(
            version.version_id,
            version.governing_manifest.canonical_digest,
            f"evaluation-sink:cf-{number}",
            max_attempts=3,
        )
    )
    handoff = store.persist_attempt(handoff.handoff_id)
    attempt = handoff.attempts[0]
    handoff = store.mark_attempt_sent(handoff.handoff_id, attempt.attempt_id)
    acknowledgement = Acknowledgement.create(
        handoff_id=handoff.handoff_id,
        attempt_id=attempt.attempt_id,
        candidate_version_id=version.version_id,
        governing_manifest_digest=version.governing_manifest.canonical_digest,
        sink_id=handoff.sink_id,
        outcome=AcknowledgementOutcome.ACKNOWLEDGED,
        response_digest="sha256:" + f"{number % 10}" * 64,
    )
    handoff = store.correlate_acknowledgement(handoff.handoff_id, acknowledgement)
    store._connection.close()
    feedback = create_evaluation_feedback(
        handoff=handoff,
        attempt=attempt,
        acknowledgement=acknowledgement,
        candidate_version=version,
        source_feedback_id=_encoded(command),
        outcome=EvaluationFeedbackOutcome.ACCEPTED,
        reason=EvaluationFeedbackReason.INTAKE_ACCEPTED,
        detail_digest="sha256:" + "2" * 64,
        request_id=str(uuid.uuid4()),
        actor_identity_digest=actor,
        idempotency_key=_encoded(command),
    )
    obligation = create_reconciliation_obligation(
        feedback,
        request_id=str(uuid.uuid4()),
        actor_identity_digest=actor,
        idempotency_key="obligation:" + command.record_id,
    )
    return feedback, obligation, handoff, attempt, acknowledgement, version


def _submission(location: _Location, command: WriteCommand):
    feedback, obligation, handoff, attempt, acknowledgement, version = (
        location.fixtures[command.record_id]
    )
    if _decoded(feedback.source_feedback_id) == command:
        return feedback, obligation
    divergent = create_evaluation_feedback(
        handoff=handoff,
        attempt=attempt,
        acknowledgement=acknowledgement,
        candidate_version=version,
        source_feedback_id=_encoded(command),
        outcome=feedback.outcome,
        reason=feedback.reason,
        detail_digest=feedback.detail_digest,
        request_id=feedback.request_id,
        actor_identity_digest=feedback.actor_identity_digest,
        idempotency_key=_encoded(command),
    )
    return divergent, create_reconciliation_obligation(
        divergent,
        request_id=obligation.request_id,
        actor_identity_digest=obligation.actor_identity_digest,
        idempotency_key=obligation.idempotency_key,
    )


def _build_location(
    tmp_path: Path,
    records: tuple[str, ...],
    *,
    candidate_seed_snapshot=None,
    system_seed=None,
    system_seed_snapshot=None,
) -> _Location:
    tmp_path.mkdir(mode=0o700, parents=True)
    if system_seed is not None:
        base, args, first_feedback, first_obligation = system_seed
    elif system_seed_snapshot is None:
        base, args, first_feedback, first_obligation = system_fixture._seed(
            tmp_path, candidate_seed_snapshot=candidate_seed_snapshot
        )
    else:
        base, args, first_feedback, first_obligation = system_seed_snapshot.clone(
            tmp_path
        )
    candidate = candidate_fixture._Handle(base)
    version = candidate._opened().load_version(str(candidate._row("record-1")[1]))
    actor = first_feedback.actor_identity_digest
    catalogue = {
        "record-1": candidate_fixture._generic("record-1"),
        "record-2": candidate_fixture._generic("record-2", "record-1", "beta"),
        "record-a": candidate_fixture._generic("record-a", "record-0", "alpha"),
        "record-b": candidate_fixture._generic("record-b", "record-0", "beta"),
        "record-rollback-normal": candidate_fixture._generic("record-rollback-normal"),
        "record-rollback-abort": candidate_fixture._generic("record-rollback-abort"),
    }
    commands = [catalogue[record_id] for record_id in records]
    fixtures = {
        command.record_id: _fixture(base, version, actor, command, i + 1)
        for i, command in enumerate(commands)
    }
    root = _open_unlocked_evaluation_feedback_authority_for_test(
        base.seed[1],
        retrieval_authority=args["retrieval_authority"],
        authenticator=args["authenticator"],
        authorizer=args["authorizer"],
        command_registry=args["command_registry"],
        payload_schemas=args["payload_schemas"],
        clock=args["clock"],
    )
    accepted = root.accept(
        first_feedback.canonical_bytes,
        first_obligation.canonical_bytes,
        candidate_proof=base.seed[0][3],
    )
    competing = {
        command.record_id: append_reconciliation_disposition(
            accepted.obligation,
            (),
            outcome=ReconciliationDispositionOutcome.UNRESOLVED,
            reason=ReconciliationDispositionReason.AWAITING_RECONCILIATION,
            resolution_digest="sha256:" + str(i + 7) * 64,
            request_id=str(uuid.uuid4()),
            actor_identity_digest=actor,
            idempotency_key=_encoded(command),
            expected_current_disposition_id=None,
            expected_current_disposition_digest=None,
            expected_current_ordinal=0,
        )
        for i, command in enumerate(
            item for item in commands if item.record_id in {"record-a", "record-b"}
        )
    }
    root.close()
    location = _Location(
        base,
        args,
        fixtures,
        base.seed[0][3],
        (first_feedback, first_obligation),
        competing,
    )
    connection = sqlite3.connect(base.seed[1], isolation_level=None)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()
    return location


def _location(tmp_path: Path, records: tuple[str, ...]) -> _Location:
    snapshot = _LOCATION_SNAPSHOTS.get(records)
    if snapshot is not None:
        return snapshot.clone(tmp_path)
    location = _build_location(tmp_path, records)
    seed = location.candidate.seed
    _LOCATION_SNAPSHOTS[records] = _LocationSnapshot(
        Path(seed[1]).read_bytes(),
        (seed[0], *seed[2:]),
        dict(location.args),
        location.fixtures,
        location.proof,
        location.base,
        location.competing,
    )
    return location


class _Handle:
    def __init__(self, location: _Location):
        self.location = location
        self.root = None
        self.open_error = None
        try:
            self.root = _open_unlocked_evaluation_feedback_authority_for_test(
                location.candidate.seed[1],
                retrieval_authority=location.args["retrieval_authority"],
                authenticator=location.args["authenticator"],
                authorizer=location.args["authorizer"],
                command_registry=location.args["command_registry"],
                payload_schemas=location.args["payload_schemas"],
                clock=location.args["clock"],
                busy_timeout_ms=100,
            )
        except Exception as exc:  # noqa: BLE001 - translate at conformance seam
            self.open_error = exc

    def _opened(self):
        if self.open_error is not None:
            raise IntegrityViolation("feedback open failed") from self.open_error
        return self.root

    def _commands(self, transaction=None):
        target = transaction or self._opened()
        values = []
        connection = (
            target._connection if transaction is None else target._root._connection
        )
        feedback_ids = tuple(
            str(row[0])
            for row in connection.execute(
                "SELECT feedback_id FROM evaluation_feedback ORDER BY feedback_id"
            )
        )
        for feedback_id in feedback_ids:
            item = target.load(feedback_id)
            try:
                values.append(_decoded(item.feedback.source_feedback_id))
            except KeyError:
                pass
            has_dispositions = connection.execute(
                "SELECT 1 FROM evaluation_reconciliation_dispositions WHERE obligation_id=?",
                (item.obligation.obligation_id,),
            ).fetchone()
            history = (
                target.dispositions(item.obligation.obligation_id)
                if has_dispositions
                else ()
            )
            for disposition in history:
                try:
                    values.append(_decoded(disposition.idempotency_key))
                except KeyError:
                    pass
        return tuple(values)

    def submit(self, command: WriteCommand, *, lose_response: bool = False):
        try:
            if command.record_id in self.location.competing:
                disposition = self.location.competing[command.record_id]
                self._opened().append_disposition(
                    disposition.canonical_bytes, candidate_proof=self.location.proof
                )
            else:
                feedback, obligation = _submission(self.location, command)
                self._opened().accept(
                    feedback.canonical_bytes,
                    obligation.canonical_bytes,
                    candidate_proof=self.location.proof,
                )
        except (KeyError, FeedbackContractError, sqlite3.OperationalError) as exc:
            if _database_locked(exc):
                raise BindingConflict(command.record_id) from exc
            try:
                retained = next(
                    (
                        item
                        for item in self._commands()
                        if item.record_id == command.record_id
                    ),
                    None,
                )
            except Exception as integrity:
                raise IntegrityViolation(command.record_id) from integrity
            if retained is not None:
                raise BindingConflict(command.record_id) from exc
            raise IntegrityViolation(command.record_id) from exc
        try:
            retained = next(
                item for item in self._commands() if item.record_id == command.record_id
            )
        except Exception as exc:
            raise IntegrityViolation(command.record_id) from exc
        if retained != command:
            raise IntegrityViolation(command.record_id)
        if lose_response:
            raise LostResponse(command.record_id)
        return AuthorityValue.from_command(command)

    def observe(self, record_id: str):
        try:
            command = next(
                (item for item in self._commands() if item.record_id == record_id), None
            )
            if command is None:
                return None
            return StoredAuthorityState.from_command(command)
        except Exception as exc:
            raise IntegrityViolation(record_id) from exc

    def history(self):
        try:
            return tuple(AuthorityValue.from_command(item) for item in self._commands())
        except Exception as exc:
            raise IntegrityViolation("history") from exc

    list_history = history

    def read(self, record_id: str):
        try:
            command = next(
                (item for item in self._commands() if item.record_id == record_id), None
            )
            if command is None:
                raise KeyError(record_id)
            return AuthorityValue.from_command(command)
        except KeyError:
            raise
        except Exception as exc:
            raise IntegrityViolation(record_id) from exc

    def set_upstream_head(self, authority: str, value: str):
        if value.endswith("head-1"):
            return
        location = self.location.candidate
        subject = location.subjects["record-1"]
        connection = sqlite3.connect(location.seed[1], isolation_level=None)
        try:
            if authority == "authority":
                fixture = (connection, *location.seed[0][1:])
                proposal, dispositions = location.seed[7]["authority"]
                upstream = candidate_fixture.d1._open(fixture)
                try:
                    upstream.retain(
                        proposal,
                        dispositions,
                        proof=location.seed[0][3],
                        expected_target_version=subject,
                    )
                finally:
                    upstream.close()
            elif authority == "policy":
                item, current = location.seed[7]["policy"]
                successor = replace(
                    candidate_fixture.d1.work_item_helpers._version(item, 2),
                    retrieval=current.retrieval,
                )
                from newsroom.increment6.work_items import TriageWorkItemStore

                TriageWorkItemStore(connection, location.seed[0][1]).append_version(
                    current.version_id, current.canonical_digest, successor
                )
        finally:
            connection.close()

    def current_use(self, record_id: str):
        feedback, obligation, *_ = self.location.fixtures[record_id]
        accepted = self._opened().load(feedback.feedback_id)
        history = self._opened().dispositions(obligation.obligation_id)
        disposition = append_reconciliation_disposition(
            accepted.obligation,
            history,
            outcome=ReconciliationDispositionOutcome.UNRESOLVED,
            reason=ReconciliationDispositionReason.AWAITING_RECONCILIATION,
            resolution_digest="sha256:" + "7" * 64,
            request_id=str(uuid.uuid4()),
            actor_identity_digest=feedback.actor_identity_digest,
            idempotency_key=f"current-use:{record_id}:{len(history)}",
            expected_current_disposition_id=history[-1].disposition_id
            if history
            else None,
            expected_current_disposition_digest=history[-1].canonical_digest
            if history
            else None,
            expected_current_ordinal=len(history),
        )
        try:
            self._opened().append_disposition(
                disposition.canonical_bytes, candidate_proof=self.location.proof
            )
        except Exception as exc:
            raise IntegrityViolation(record_id) from exc
        return AuthorityValue.from_command(_decoded(feedback.source_feedback_id))

    def tamper(self, record_id: str, kind: TamperKind):
        feedback, obligation, *_ = self.location.fixtures[record_id]
        connection = sqlite3.connect(
            self.location.candidate.seed[1], isolation_level=None
        )
        connection.execute("PRAGMA foreign_keys=OFF")
        triggers = tuple(
            connection.execute(
                "SELECT name,sql FROM sqlite_master WHERE name IN "
                "('immutable_evaluation_feedback','immutable_evaluation_obligation') ORDER BY name"
            )
        )
        for name, _ in triggers:
            connection.execute(f"DROP TRIGGER {name}")
        if kind is TamperKind.OFFLINE_REWRITE:
            rewritten = replace(feedback, detail_digest="sha256:" + "9" * 64)
            derived = create_reconciliation_obligation(
                rewritten,
                request_id=obligation.request_id,
                actor_identity_digest=obligation.actor_identity_digest,
                idempotency_key=obligation.idempotency_key,
            )
            connection.execute(
                "UPDATE evaluation_feedback SET feedback_bytes=?,feedback_digest=? WHERE feedback_id=?",
                (
                    rewritten.canonical_bytes,
                    rewritten.canonical_digest,
                    feedback.feedback_id,
                ),
            )
            connection.execute(
                "UPDATE evaluation_reconciliation_obligations SET obligation_id=?,obligation_bytes=?,"
                "obligation_digest=?,feedback_digest=? WHERE obligation_id=?",
                (
                    derived.obligation_id,
                    derived.canonical_bytes,
                    derived.canonical_digest,
                    rewritten.canonical_digest,
                    obligation.obligation_id,
                ),
            )
            for _, sql in triggers:
                connection.execute(sql)
            connection.close()
            return
        table, column, value, key, identity = {
            TamperKind.CANONICAL: (
                "evaluation_feedback",
                "feedback_bytes",
                b"{}",
                "feedback_id",
                feedback.feedback_id,
            ),
            TamperKind.SCALAR: (
                "evaluation_feedback",
                "candidate_id",
                str(uuid.uuid4()),
                "feedback_id",
                feedback.feedback_id,
            ),
            TamperKind.IDENTITY: (
                "evaluation_feedback",
                "authority_aggregate_id",
                str(uuid.uuid4()),
                "feedback_id",
                feedback.feedback_id,
            ),
            TamperKind.LINKED_ROW: (
                "evaluation_reconciliation_obligations",
                "feedback_digest",
                "sha256:" + "0" * 64,
                "obligation_id",
                obligation.obligation_id,
            ),
            TamperKind.DIGEST: (
                "evaluation_feedback",
                "feedback_digest",
                "sha256:" + "0" * 64,
                "feedback_id",
                feedback.feedback_id,
            ),
            TamperKind.PROVENANCE: (
                "evaluation_feedback",
                "actor_identity_digest",
                "sha256:" + "0" * 64,
                "feedback_id",
                feedback.feedback_id,
            ),
        }[kind]
        connection.execute(
            f"UPDATE {table} SET {column}=? WHERE {key}=?", (value, identity)
        )
        for _, sql in triggers:
            connection.execute(sql)
        connection.close()

    def rollback_scope(self, operation):
        outer = self

        class Scope:
            def submit(_, command):
                feedback, obligation, *_ = outer.location.fixtures[command.record_id]
                transaction.accept(
                    feedback.canonical_bytes,
                    obligation.canonical_bytes,
                    candidate_proof=outer.location.proof,
                )
                return AuthorityValue.from_command(command)

            def observe(_, record_id):
                command = next(
                    (
                        item
                        for item in outer._commands(transaction)
                        if item.record_id == record_id
                    ),
                    None,
                )
                return StoredAuthorityState.from_command(command) if command else None

            def history(_):
                return tuple(
                    AuthorityValue.from_command(item)
                    for item in outer._commands(transaction)
                )

        transaction = None

        def inspect(view):
            nonlocal transaction
            transaction = view
            operation(Scope())

        self._opened().rollback_scope(inspect)

    def close(self):
        if self.root is not None:
            self.root.close()


class _Adapter:
    name = "evaluation-feedback-v25-real"
    applicability: ClassVar = {
        case: Applicability.required() for case in CASE_INVENTORY
    }

    def __init__(self, root: Path, records: tuple[str, ...] = ("record-1",)):
        self.root = root
        self.records = records

    def create_location(self):
        return _location(self.root / str(uuid.uuid4()), self.records)

    def open_handle(self, location, *, migrate=False):
        if migrate:
            connection = sqlite3.connect(
                location.candidate.seed[1], isolation_level=None
            )
            prepare_pending_migration_backup(connection)
            apply_pending_migrations(
                connection, applied_at="2042-01-02T00:00:00.000000Z"
            )
            connection.close()
        return _Handle(location)


@dataclass(frozen=True)
class _ConformanceProbe:
    probe_id: str
    case: CaseId
    operation: Callable[[object], None]


_CONFORMANCE_PROBES = (
    _ConformanceProbe(
        "fresh_replay-submission", CaseId.FRESH_REPLAY, _fresh_submission
    ),
    _ConformanceProbe("fresh_replay-replay", CaseId.FRESH_REPLAY, _exact_replay),
    _ConformanceProbe(
        "fresh_reopen-persistence", CaseId.FRESH_REOPEN, _fresh_reopen_persistence
    ),
    _ConformanceProbe("fresh_reopen-digest", CaseId.FRESH_REOPEN, _fresh_reopen_digest),
    _ConformanceProbe(
        "representation_binding-retained",
        CaseId.REPRESENTATION_BINDING,
        _representation_retained,
    ),
    *(
        _ConformanceProbe(
            f"representation_binding-{kind.value}",
            CaseId.REPRESENTATION_BINDING,
            partial(_representation_tamper, kind=kind),
        )
        for kind in _REPRESENTATION_TAMPERS
    ),
    *(
        _ConformanceProbe(
            f"request_binding-{field_name}",
            CaseId.REQUEST_BINDING,
            partial(_request_binding_field, field_name=field_name),
        )
        for field_name in _REQUEST_BINDING_FIELDS
    ),
    _ConformanceProbe(
        CaseId.LOST_RESPONSE_REPLAY.value,
        CaseId.LOST_RESPONSE_REPLAY,
        _SCENARIOS[CaseId.LOST_RESPONSE_REPLAY],
    ),
    *(
        _ConformanceProbe(
            f"historical_read-{kind.value}-{phase}-{noun}",
            CaseId.HISTORICAL_READ,
            partial(
                _historical_tamper_operation,
                kind=kind,
                reopened=reopened,
                listing=listing,
            ),
        )
        for kind in _HISTORICAL_TAMPERS
        for phase, reopened in (("fresh", False), ("reopened", True))
        for noun, listing in (("read", False), ("list", True))
    ),
    *(
        _ConformanceProbe(
            f"historical_read-retained-{noun}",
            CaseId.HISTORICAL_READ,
            partial(_historical_retained_operation, listing=listing),
        )
        for noun, listing in (("read", False), ("list", True))
    ),
    *(
        _ConformanceProbe(
            f"current_use_revalidation-{authority}",
            CaseId.CURRENT_USE_REVALIDATION,
            partial(_current_use_authority, authority=authority),
        )
        for authority in _CURRENT_USE_AUTHORITIES
    ),
    *(
        _ConformanceProbe(
            f"tamper_rejection-{kind.value}",
            CaseId.TAMPER_REJECTION,
            partial(_tamper_rejection_kind, kind=kind),
        )
        for kind in _TAMPER_REJECTION_TAMPERS
    ),
    _ConformanceProbe(
        CaseId.COMPETING_WRITERS.value,
        CaseId.COMPETING_WRITERS,
        _SCENARIOS[CaseId.COMPETING_WRITERS],
    ),
    _ConformanceProbe(
        "transaction_rollback-normal",
        CaseId.TRANSACTION_ROLLBACK,
        partial(_rollback_kind, abort=False),
    ),
    _ConformanceProbe(
        "transaction_rollback-abort", CaseId.TRANSACTION_ROLLBACK, _rollback_sequence
    ),
    _ConformanceProbe(
        "restart_migration-restart",
        CaseId.RESTART_MIGRATION,
        partial(_restart_or_migrate, migrate=False),
    ),
    _ConformanceProbe(
        "restart_migration-migrate",
        CaseId.RESTART_MIGRATION,
        partial(_restart_or_migrate, migrate=True),
    ),
)

_RECORDS_BY_CASE = {
    CaseId.HISTORICAL_READ: ("record-1", "record-2"),
    CaseId.COMPETING_WRITERS: ("record-a", "record-b"),
    CaseId.TRANSACTION_ROLLBACK: (
        "record-rollback-normal",
        "record-rollback-abort",
    ),
}


def test_real_feedback_conformance_probe_inventory_is_exact_and_unique() -> None:
    probe_ids = tuple(probe.probe_id for probe in _CONFORMANCE_PROBES)
    expected = {
        "fresh_replay-submission",
        "fresh_replay-replay",
        "fresh_reopen-persistence",
        "fresh_reopen-digest",
        "representation_binding-retained",
        CaseId.LOST_RESPONSE_REPLAY.value,
        CaseId.COMPETING_WRITERS.value,
        "transaction_rollback-normal",
        "transaction_rollback-abort",
        "restart_migration-restart",
        "restart_migration-migrate",
        *(f"representation_binding-{kind.value}" for kind in _REPRESENTATION_TAMPERS),
        *(f"request_binding-{field}" for field in _REQUEST_BINDING_FIELDS),
        *(
            f"historical_read-{kind.value}-{phase}-{noun}"
            for kind in _HISTORICAL_TAMPERS
            for phase in ("fresh", "reopened")
            for noun in ("read", "list")
        ),
        "historical_read-retained-read",
        "historical_read-retained-list",
        *(f"current_use_revalidation-{item}" for item in _CURRENT_USE_AUTHORITIES),
        *(f"tamper_rejection-{kind.value}" for kind in _TAMPER_REJECTION_TAMPERS),
    }
    assert len(probe_ids) == len(set(probe_ids))
    assert set(probe_ids) == expected
    assert {probe.case for probe in _CONFORMANCE_PROBES} == set(CASE_INVENTORY)


@pytest.mark.parametrize("probe", _CONFORMANCE_PROBES, ids=lambda item: item.probe_id)
def test_real_feedback_store_passes_required_conformance_probe(
    tmp_path: Path, probe: _ConformanceProbe
):
    probe.operation(_Adapter(tmp_path, _RECORDS_BY_CASE.get(probe.case, ("record-1",))))


def test_exact_replay_calls_production_accept(tmp_path: Path, monkeypatch) -> None:
    adapter = _Adapter(tmp_path)
    location, handle = adapter.create_location(), None
    handle = adapter.open_handle(location)
    command = candidate_fixture._generic("record-1")
    handle.submit(command)
    called = False

    def reject(*args, **kwargs):
        nonlocal called
        called = True
        raise FeedbackContractError("production replay probe")

    monkeypatch.setattr(handle.root, "accept", reject)
    with pytest.raises(BindingConflict):
        handle.submit(command)
    assert called


def test_divergent_replay_calls_production_accept(tmp_path: Path, monkeypatch) -> None:
    adapter = _Adapter(tmp_path)
    location = adapter.create_location()
    handle = adapter.open_handle(location)
    command = candidate_fixture._generic("record-1")
    handle.submit(command)
    original = handle.root.accept
    calls = 0

    def observed(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(handle.root, "accept", observed)
    with pytest.raises(BindingConflict):
        handle.submit(replace(command, actor="different-actor"))
    assert calls == 1
