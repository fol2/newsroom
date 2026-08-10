from __future__ import annotations

import importlib.util
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier, Event, current_thread

import pytest

from newsroom.increment6._execution_store import (
    TriageExecutionAuthorityError,
    _TriageExecutionStore,
    _open_on_connection,
)
from newsroom.authority.auth import (
    AuthenticationProof,
    StaticAuthenticator,
    StaticPrincipal,
)
from newsroom.authority.canonical import canonical_json_bytes
from newsroom.authority.types import UtcTimestamp
from newsroom.increment6.execution import (
    ExecutionBatch,
    LeaseLifecycle,
    LeaseProgress,
    WorkerAttempt,
    open_triage_execution_authority,
)
from newsroom.increment6.proposals import FixtureWorkerKind
from newsroom.increment6.scheduling import allocate_reserved_capacity
from newsroom.increment6.work_items import (
    RetrievalContextAuthority,
    RetrievalInputBinding,
    DecisionLeadBinding,
    TriageWorkItem,
    TriageWorkItemStore,
)
from newsroom.tests import test_increment5d1_hybrid_composer as composer_helpers
from newsroom.tests import test_increment5d2_retrieval_context as retrieval_helpers
from newsroom.tests.check_3c_authority_helpers import proof as authority_proof
from newsroom.tests.discovery_3d_authority_helpers import (
    exact_admission_request,
    open_discovery_system,
    seed_check_lineage,
)
from newsroom.tests.test_increment6a2_work_items import _version
from newsroom.tests.test_increment6b1_execution import _batch, _decision_for, _digest


PROOF = AuthenticationProof(method="STATIC_TOKEN", credential="worker-token")
OTHER_PROOF = AuthenticationProof(method="STATIC_TOKEN", credential="other-token")


def _fixture(tmp_path: Path):
    inputs = composer_helpers.branch_inputs.__wrapped__(tmp_path)
    (
        builder,
        _composer,
        _cas_root,
        _journal,
        _journal_path,
        request,
        receipt,
        _content,
    ) = retrieval_helpers._retained_complete_context(
        tmp_path, inputs, name="execution-v20"
    )
    retrieval = RetrievalContextAuthority(
        builder.journal.path, {request.request_digest: (request, receipt)}
    )
    database = tmp_path / "execution-authority.sqlite3"
    with open_discovery_system(database) as discovery:
        seed_check_lineage(discovery)
        admitted = discovery.discovery.admit_signal_to_lead(
            exact_admission_request(), proof=authority_proof()
        )
        assert admitted.lead is not None
        assert admitted.initial_disposition is not None
        decision = DecisionLeadBinding.from_authority(
            admitted.lead, admitted.initial_disposition
        )
    connection = sqlite3.connect(database, isolation_level=None)
    connection.execute("PRAGMA foreign_keys=ON")
    item = TriageWorkItem.create((decision,))
    version = replace(
        _version(item),
        retrieval=RetrievalInputBinding.from_receipt(request, receipt),
    )
    work_items = TriageWorkItemStore(connection, retrieval)
    work_items.create_or_replay(item, version)
    batch = _batch(version)
    attempt = WorkerAttempt.create(
        member=batch.members[0],
        ordinal=1,
        worker_kind=FixtureWorkerKind.REPLAY,
        worker_version="fixture-v20",
        input_digest=_digest(991),
    )
    authenticator = StaticAuthenticator(
        credentials={
            "worker-token": StaticPrincipal("worker:one"),
            "other-token": StaticPrincipal("worker:other"),
        },
        authority_domain="triage-execution",
    )
    now = [UtcTimestamp.parse("2042-03-12T10:00:00Z")]
    authority = _open_on_connection(
        connection,
        retrieval_authority=retrieval,
        authenticator=authenticator,
        clock=lambda: now[0],
        lease_ttl_seconds=300,
    )
    return connection, retrieval, authenticator, authority, now, version, batch, attempt


def _distinct_batch(version, *, policy_version: str) -> ExecutionBatch:
    original_decision = _decision_for((version,))
    distinct_decision = allocate_reserved_capacity(
        policy=replace(original_decision.policy, policy_version=policy_version),
        snapshot=original_decision.snapshot,
    )
    return ExecutionBatch.create(
        scheduling_decision=distinct_decision,
        work_item_versions=(version,),
    )


def _insert_attempt_direct(
    connection: sqlite3.Connection, batch_id: str, attempt: WorkerAttempt
) -> None:
    actor = str(
        connection.execute(
            "SELECT actor_identity_digest FROM triage_worker_attempts "
            "WHERE attempt_id=?",
            (attempt.previous_attempt_id,),
        ).fetchone()[0]
    )
    recorded_at = "2042-03-12T10:00:00.000000Z"
    connection.execute(
        "INSERT INTO triage_worker_attempts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            attempt.attempt_id,
            batch_id,
            attempt.work_item_id,
            attempt.work_item_version_id,
            attempt.work_item_version_digest,
            attempt.retrieval_context_digest,
            attempt.priority_digest,
            attempt.ordinal,
            attempt.previous_attempt_id,
            attempt.previous_attempt_digest,
            attempt.semantic_request_key,
            attempt.canonical_bytes,
            attempt.canonical_digest,
            actor,
            _TriageExecutionStore._event_id(
                attempt.canonical_digest, actor, recorded_at
            ),
            recorded_at,
        ),
    )


def _insert_attempt_values_direct(
    connection: sqlite3.Connection,
    batch_id: str,
    values: dict[str, object],
    *,
    canonical_digest: str,
    actor: str,
) -> None:
    raw = canonical_json_bytes(values)
    recorded_at = "2042-03-12T10:00:00.000000Z"
    connection.execute(
        "INSERT INTO triage_worker_attempts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            values["attempt_id"],
            batch_id,
            values["work_item_id"],
            values["work_item_version_id"],
            values["work_item_version_digest"],
            values["retrieval_context_digest"],
            values["priority_digest"],
            values["ordinal"],
            values["previous_attempt_id"],
            values["previous_attempt_digest"],
            values["semantic_request_key"],
            raw,
            canonical_digest,
            actor,
            _TriageExecutionStore._event_id(canonical_digest, actor, recorded_at),
            recorded_at,
        ),
    )


def _with_ordinal(attempt: WorkerAttempt, ordinal: int) -> WorkerAttempt:
    identity = (
        f"{attempt.schema_identity}|{attempt.semantic_request_digest}|{ordinal}|"
        f"{attempt.previous_attempt_id}|{attempt.previous_attempt_digest}"
    )
    return replace(
        attempt,
        attempt_id=str(uuid.uuid5(uuid.NAMESPACE_URL, identity)),
        ordinal=ordinal,
    )


def test_batch_and_attempt_exact_replay_divergence_and_stale_absent_no_write(
    tmp_path: Path,
) -> None:
    connection, retrieval, _, authority, _, version, batch, attempt = _fixture(
        tmp_path
    )
    assert authority.register_batch(batch, proof=PROOF) == batch
    assert authority.register_batch(batch, proof=PROOF) == batch
    assert authority.register_attempt(batch.batch_id, attempt, proof=PROOF) == attempt
    assert authority.register_attempt(batch.batch_id, attempt, proof=PROOF) == attempt
    lease = authority.claim(attempt.attempt_id, proof=PROOF)

    item = TriageWorkItem.create(version.decision_leads)
    successor = replace(
        _version(item, 2),
        retrieval=version.retrieval,
    )
    TriageWorkItemStore(connection, retrieval).append_version(
        version.version_id, version.canonical_digest, successor
    )
    stale_absent_batch = _distinct_batch(
        version, policy_version="stale-absent-v20"
    )
    assert stale_absent_batch.batch_id != batch.batch_id
    assert stale_absent_batch.members[0].work_item_version_digest == (
        batch.members[0].work_item_version_digest
    )
    assert stale_absent_batch.scheduling_decision_digest != (
        batch.scheduling_decision_digest
    )
    retained_batch_count = connection.execute(
        "SELECT count(*) FROM triage_execution_batches"
    ).fetchone()[0]
    with pytest.raises(TriageExecutionAuthorityError, match="not exact current"):
        authority.register_batch(stale_absent_batch, proof=PROOF)
    assert connection.execute(
        "SELECT count(*) FROM triage_execution_batches"
    ).fetchone()[0] == retained_batch_count
    assert authority.release(lease.lease_id, proof=PROOF).lifecycle is (
        LeaseLifecycle.RELEASED
    )
    assert authority.register_batch(batch, proof=PROOF) == batch
    divergent_attempt = WorkerAttempt.create(
        member=batch.members[0],
        ordinal=1,
        worker_kind=FixtureWorkerKind.REPLAY,
        worker_version="divergent-v20",
        input_digest=_digest(777),
    )
    with pytest.raises(TriageExecutionAuthorityError):
        authority.register_attempt(batch.batch_id, divergent_attempt, proof=PROOF)
    current_batch = _batch(successor)
    current_attempt = WorkerAttempt.create(
        member=current_batch.members[0],
        ordinal=1,
        worker_kind=FixtureWorkerKind.REPLAY,
        worker_version="current-v20",
        input_digest=_digest(778),
    )
    authority.register_batch(current_batch, proof=PROOF)
    authority.register_attempt(
        current_batch.batch_id, current_attempt, proof=PROOF
    )
    current_lease = authority.claim(current_attempt.attempt_id, proof=PROOF)
    third = replace(_version(item, 3), retrieval=version.retrieval)
    TriageWorkItemStore(connection, retrieval).append_version(
        successor.version_id, successor.canonical_digest, third
    )
    with pytest.raises(TriageExecutionAuthorityError):
        authority.complete(current_lease.lease_id, _digest(779), proof=PROOF)
    assert connection.execute(
        "SELECT lifecycle FROM triage_work_item_leases WHERE lease_id=?",
        (current_lease.lease_id,),
    ).fetchone() == ("CLAIMED",)
    assert connection.execute(
        "SELECT count(*) FROM triage_execution_batches"
    ).fetchone()[0] == 2
    assert version.canonical_digest == batch.members[0].work_item_version_digest


def test_attempt_replay_is_bound_to_the_exact_retained_batch(tmp_path: Path) -> None:
    _, _, _, authority, _, version, batch, attempt = _fixture(tmp_path)
    other_batch = _distinct_batch(version, policy_version="replay-other-batch-v20")
    authority.register_batch(batch, proof=PROOF)
    authority.register_batch(other_batch, proof=PROOF)
    authority.register_attempt(batch.batch_id, attempt, proof=PROOF)

    with pytest.raises(TriageExecutionAuthorityError, match="Batch"):
        authority.register_attempt(other_batch.batch_id, attempt, proof=PROOF)
    with pytest.raises(TriageExecutionAuthorityError, match="Batch"):
        authority.register_attempt(
            "00000000-0000-0000-0000-000000000000", attempt, proof=PROOF
        )


def test_execution_contract_remains_the_sole_public_execution_module() -> None:
    assert importlib.util.find_spec("newsroom.authority.triage_execution_system") is None


def test_attempt_insert_guard_requires_terminal_same_batch_predecessor(
    tmp_path: Path,
) -> None:
    connection, _, _, authority, _, version, batch, attempt = _fixture(tmp_path)
    other_batch = _distinct_batch(version, policy_version="other-batch-v20")
    authority.register_batch(batch, proof=PROOF)
    authority.register_batch(other_batch, proof=PROOF)
    authority.register_attempt(batch.batch_id, attempt, proof=PROOF)
    successor = WorkerAttempt.create(
        member=batch.members[0],
        ordinal=2,
        previous_attempt=attempt,
        worker_kind=FixtureWorkerKind.REPLAY,
        worker_version="direct-successor-v20",
        input_digest=_digest(998),
    )

    with pytest.raises(sqlite3.DatabaseError, match="Batch membership"):
        _insert_attempt_direct(connection, batch.batch_id, successor)
    predecessor_lease = authority.claim(attempt.attempt_id, proof=PROOF)
    authority.release(predecessor_lease.lease_id, proof=PROOF)
    with pytest.raises(sqlite3.DatabaseError, match="Batch membership"):
        _insert_attempt_direct(connection, other_batch.batch_id, successor)
    assert connection.execute(
        "SELECT count(*) FROM triage_worker_attempts WHERE ordinal=2"
    ).fetchone() == (0,)


def test_attempt_insert_guard_rejects_ordinal_gap_and_cross_lineage(
    tmp_path: Path,
) -> None:
    connection, _, _, authority, _, _, batch, attempt = _fixture(tmp_path)
    authority.register_batch(batch, proof=PROOF)
    authority.register_attempt(batch.batch_id, attempt, proof=PROOF)
    lease = authority.claim(attempt.attempt_id, proof=PROOF)
    authority.release(lease.lease_id, proof=PROOF)
    actor = str(
        connection.execute(
            "SELECT actor_identity_digest FROM triage_worker_attempts WHERE attempt_id=?",
            (attempt.attempt_id,),
        ).fetchone()[0]
    )
    successor = WorkerAttempt.create(
        member=batch.members[0],
        ordinal=2,
        previous_attempt=attempt,
        worker_kind=FixtureWorkerKind.REPLAY,
        worker_version="direct-guard-v20",
        input_digest=_digest(997),
    )

    gap = _with_ordinal(successor, 3)
    with pytest.raises(sqlite3.DatabaseError, match="Batch membership"):
        _insert_attempt_values_direct(
            connection,
            batch.batch_id,
            gap.canonical_value(),
            canonical_digest=gap.canonical_digest,
            actor=actor,
        )

    connection.execute("DROP TRIGGER retained_execution_batch_update")
    batch_values = batch.canonical_value()
    divergent_member = dict(batch_values["members"][0])
    divergent_member["retrieval_context_digest"] = _digest(996)
    batch_values["members"].append(divergent_member)
    connection.execute(
        "UPDATE triage_execution_batches SET member_count=?,canonical_bytes=? WHERE batch_id=?",
        (2, canonical_json_bytes(batch_values), batch.batch_id),
    )
    cross_lineage = successor.canonical_value()
    cross_lineage["retrieval_context_digest"] = divergent_member[
        "retrieval_context_digest"
    ]
    with pytest.raises(sqlite3.DatabaseError, match="Batch membership"):
        _insert_attempt_values_direct(
            connection,
            batch.batch_id,
            cross_lineage,
            canonical_digest=_digest(995),
            actor=actor,
        )


def test_reopen_rejects_bypassed_attempt_ordinal_gap(tmp_path: Path) -> None:
    connection, retrieval, authenticator, authority, now, _, batch, attempt = _fixture(
        tmp_path
    )
    authority.register_batch(batch, proof=PROOF)
    authority.register_attempt(batch.batch_id, attempt, proof=PROOF)
    lease = authority.claim(attempt.attempt_id, proof=PROOF)
    authority.release(lease.lease_id, proof=PROOF)
    successor = WorkerAttempt.create(
        member=batch.members[0],
        ordinal=2,
        previous_attempt=attempt,
        worker_kind=FixtureWorkerKind.REPLAY,
        worker_version="reopen-gap-v20",
        input_digest=_digest(994),
    )
    gap = _with_ordinal(successor, 3)
    actor = str(
        connection.execute(
            "SELECT actor_identity_digest FROM triage_worker_attempts WHERE attempt_id=?",
            (attempt.attempt_id,),
        ).fetchone()[0]
    )
    connection.execute("DROP TRIGGER triage_worker_attempt_coherence")
    _insert_attempt_values_direct(
        connection,
        batch.batch_id,
        gap.canonical_value(),
        canonical_digest=gap.canonical_digest,
        actor=actor,
    )

    with pytest.raises(TriageExecutionAuthorityError, match="predecessor chain"):
        _open_on_connection(
            connection,
            retrieval_authority=retrieval,
            authenticator=authenticator,
            clock=lambda: now[0],
        )


def test_same_store_concurrent_failure_cannot_steal_the_claim_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection, retrieval, authenticator, authority, now, _, batch, attempt = _fixture(
        tmp_path
    )
    authority.register_batch(batch, proof=PROOF)
    authority.register_attempt(batch.batch_id, attempt, proof=PROOF)
    authority.close()
    connection.close()
    connection = sqlite3.connect(
        tmp_path / "execution-authority.sqlite3",
        isolation_level=None,
        check_same_thread=False,
    )
    connection.execute("PRAGMA foreign_keys=ON")
    authority = _open_on_connection(
        connection,
        retrieval_authority=retrieval,
        authenticator=authenticator,
        clock=lambda: now[0],
    )
    store = authority._TriageExecutionAuthority__store
    owner_inside_transaction = Event()
    release_owner = Event()

    def blocking_recorded_at() -> str:
        if current_thread().name.startswith("claim-owner"):
            owner_inside_transaction.set()
            assert release_owner.wait(5)
        return now[0].to_text()

    store._recorded_at = blocking_recorded_at
    original_begin = _TriageExecutionStore._begin
    contender_at_begin = Event()

    def observed_begin(self: _TriageExecutionStore) -> None:
        if current_thread().name.startswith("claim-contender"):
            contender_at_begin.set()
        original_begin(self)

    monkeypatch.setattr(_TriageExecutionStore, "_begin", observed_begin)
    with (
        ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="claim-owner"
        ) as owner_executor,
        ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="claim-contender"
        ) as contender_executor,
    ):
        owner = owner_executor.submit(
            lambda: authority.claim(attempt.attempt_id, proof=PROOF)
        )
        assert owner_inside_transaction.wait(5)
        contender = contender_executor.submit(
            lambda: authority.claim(attempt.attempt_id, proof=OTHER_PROOF)
        )
        assert contender_at_begin.wait(5)
        release_owner.set()
        lease = owner.result(timeout=5)
        with pytest.raises(TriageExecutionAuthorityError, match="owner"):
            contender.result(timeout=5)

    assert connection.execute(
        "SELECT lease_id,lifecycle FROM triage_work_item_leases WHERE attempt_id=?",
        (attempt.attempt_id,),
    ).fetchall() == [(lease.lease_id, "CLAIMED")]
    connection.close()


def test_store_does_not_rollback_an_external_transaction(tmp_path: Path) -> None:
    connection, _, _, authority, _, _, batch, _ = _fixture(tmp_path)
    connection.execute("BEGIN")

    with pytest.raises(TriageExecutionAuthorityError, match="active transaction"):
        authority.register_batch(batch, proof=PROOF)

    assert connection.in_transaction
    connection.execute("ROLLBACK")


def test_claim_lost_response_completion_terminal_replay_and_restart(
    tmp_path: Path,
) -> None:
    _, _, _, authority, now, _, batch, attempt = _fixture(tmp_path)
    authority.register_batch(batch, proof=PROOF)
    authority.register_attempt(batch.batch_id, attempt, proof=PROOF)
    lease = authority.claim(attempt.attempt_id, proof=PROOF)
    assert authority.claim(attempt.attempt_id, proof=PROOF) == lease
    with pytest.raises(TriageExecutionAuthorityError, match="owner"):
        authority.claim(attempt.attempt_id, proof=OTHER_PROOF)
    with pytest.raises(TriageExecutionAuthorityError, match="owner"):
        authority.release(lease.lease_id, proof=OTHER_PROOF)
    evidence = _digest(808)
    now[0] = UtcTimestamp.parse("2042-03-12T10:01:00Z")
    completed = authority.complete(lease.lease_id, evidence, proof=PROOF)
    assert completed.lifecycle is LeaseLifecycle.RELEASED
    assert completed.transition.progress[-1].progress is LeaseProgress.COMPLETED
    assert authority.complete(lease.lease_id, evidence, proof=PROOF) == completed
    with pytest.raises(TriageExecutionAuthorityError, match="diverges"):
        authority.complete(lease.lease_id, _digest(809), proof=PROOF)

    successor = authority.restart(
        attempt.attempt_id,
        worker_kind=FixtureWorkerKind.REPLAY,
        worker_version="fixture-v20-restart",
        input_digest=_digest(992),
        proof=PROOF,
    )
    assert successor.ordinal == 2
    assert authority.restart(
        attempt.attempt_id,
        worker_kind=FixtureWorkerKind.REPLAY,
        worker_version="fixture-v20-restart",
        input_digest=_digest(992),
        proof=PROOF,
    ) == successor
    successor_lease = authority.claim(successor.attempt_id, proof=PROOF)
    assert successor_lease.fence == lease.fence + 1
    now[0] = UtcTimestamp.parse(successor_lease.expires_at)
    expired = authority.expire(successor_lease.lease_id, proof=PROOF)
    assert expired.lifecycle is LeaseLifecycle.EXPIRED
    assert authority.expire(successor_lease.lease_id, proof=PROOF) == expired


def test_completed_predecessor_and_claimed_successor_reopen_cleanly(
    tmp_path: Path,
) -> None:
    connection, retrieval, authenticator, authority, now, _, batch, attempt = _fixture(
        tmp_path
    )
    authority.register_batch(batch, proof=PROOF)
    authority.register_attempt(batch.batch_id, attempt, proof=PROOF)
    predecessor_lease = authority.claim(attempt.attempt_id, proof=PROOF)
    authority.complete(predecessor_lease.lease_id, _digest(810), proof=PROOF)
    successor = authority.restart(
        attempt.attempt_id,
        worker_kind=FixtureWorkerKind.REPLAY,
        worker_version="fixture-v20-reopen",
        input_digest=_digest(993),
        proof=PROOF,
    )
    successor_lease = authority.claim(successor.attempt_id, proof=PROOF)

    authority.close()
    reopened = _open_on_connection(
        connection,
        retrieval_authority=retrieval,
        authenticator=authenticator,
        clock=lambda: now[0],
    )
    assert reopened.claim(successor.attempt_id, proof=PROOF) == successor_lease


def test_expired_crash_can_be_reclaimed_by_a_different_authenticated_worker(
    tmp_path: Path,
) -> None:
    _, _, _, authority, now, _, batch, attempt = _fixture(tmp_path)
    authority.register_batch(batch, proof=PROOF)
    authority.register_attempt(batch.batch_id, attempt, proof=PROOF)
    predecessor_lease = authority.claim(attempt.attempt_id, proof=PROOF)
    restart = dict(
        worker_kind=FixtureWorkerKind.REPLAY,
        worker_version="fixture-v20-crash-reclaim",
        input_digest=_digest(994),
        proof=OTHER_PROOF,
    )

    now[0] = UtcTimestamp.parse("2042-03-12T10:04:59Z")
    with pytest.raises(TriageExecutionAuthorityError, match="still current"):
        authority.restart(attempt.attempt_id, **restart)

    now[0] = UtcTimestamp.parse(predecessor_lease.expires_at)
    successor = authority.restart(attempt.attempt_id, **restart)
    assert successor.ordinal == 2
    assert authority.restart(attempt.attempt_id, **restart) == successor
    successor_lease = authority.claim(successor.attempt_id, proof=OTHER_PROOF)
    assert successor_lease.fence == predecessor_lease.fence + 1
    with pytest.raises(TriageExecutionAuthorityError, match="owner"):
        authority.release(successor_lease.lease_id, proof=PROOF)
    with pytest.raises(TriageExecutionAuthorityError, match="owner"):
        authority.complete(successor_lease.lease_id, _digest(995), proof=PROOF)


def test_different_worker_can_expire_a_stale_work_item_at_the_boundary(
    tmp_path: Path,
) -> None:
    connection, retrieval, _, authority, now, version, batch, attempt = _fixture(
        tmp_path
    )
    authority.register_batch(batch, proof=PROOF)
    authority.register_attempt(batch.batch_id, attempt, proof=PROOF)
    lease = authority.claim(attempt.attempt_id, proof=PROOF)
    item = TriageWorkItem.create(version.decision_leads)
    successor_version = replace(_version(item, 2), retrieval=version.retrieval)
    TriageWorkItemStore(connection, retrieval).append_version(
        version.version_id, version.canonical_digest, successor_version
    )

    now[0] = UtcTimestamp.parse("2042-03-12T10:04:59Z")
    with pytest.raises(TriageExecutionAuthorityError, match="expiry boundary"):
        authority.expire(lease.lease_id, proof=OTHER_PROOF)
    now[0] = UtcTimestamp.parse(lease.expires_at)
    expired = authority.expire(lease.lease_id, proof=OTHER_PROOF)
    assert expired.lifecycle is LeaseLifecycle.EXPIRED
    assert authority.expire(lease.lease_id, proof=OTHER_PROOF) == expired
    assert connection.execute(
        "SELECT actor_identity_digest FROM triage_work_item_leases WHERE lease_id=?",
        (lease.lease_id,),
    ).fetchone() == (expired.transitions[-1].actor_identity_digest,)
    assert connection.execute(
        "SELECT count(*) FROM triage_worker_attempts WHERE previous_attempt_id=?",
        (attempt.attempt_id,),
    ).fetchone() == (0,)


def test_reopen_rejects_lease_side_provenance_divergent_from_transition(
    tmp_path: Path,
) -> None:
    connection, retrieval, authenticator, authority, now, _, batch, attempt = _fixture(
        tmp_path
    )
    authority.register_batch(batch, proof=PROOF)
    authority.register_attempt(batch.batch_id, attempt, proof=PROOF)
    lease = authority.claim(attempt.attempt_id, proof=PROOF)
    terminal = authority.release(lease.lease_id, proof=PROOF)
    row = connection.execute(
        "SELECT canonical_digest,updated_at FROM triage_work_item_leases WHERE lease_id=?",
        (lease.lease_id,),
    ).fetchone()
    assert row is not None
    divergent_actor = _digest(997)
    divergent_event = _TriageExecutionStore._event_id(
        str(row[0]), divergent_actor, str(row[1])
    )
    with pytest.raises(sqlite3.DatabaseError, match="illegal Lease CAS update"):
        connection.execute(
            "UPDATE triage_work_item_leases SET actor_identity_digest=?,authority_event_id=? "
            "WHERE lease_id=?",
            (divergent_actor, divergent_event, terminal.lease_id),
        )
    connection.execute("DROP TRIGGER triage_lease_update_guard")
    connection.execute(
        "UPDATE triage_work_item_leases SET actor_identity_digest=?,authority_event_id=? "
        "WHERE lease_id=?",
        (divergent_actor, divergent_event, terminal.lease_id),
    )

    with pytest.raises(TriageExecutionAuthorityError, match="provenance"):
        _open_on_connection(
            connection,
            retrieval_authority=retrieval,
            authenticator=authenticator,
            clock=lambda: now[0],
        )


def test_two_connections_converge_on_one_claim_and_reopen_detects_tamper(
    tmp_path: Path,
) -> None:
    connection, retrieval, authenticator, authority, now, _, batch, attempt = _fixture(
        tmp_path
    )
    authority.register_batch(batch, proof=PROOF)
    authority.register_attempt(batch.batch_id, attempt, proof=PROOF)
    authority.close()
    connection.close()
    database = tmp_path / "execution-authority.sqlite3"
    connection = sqlite3.connect(
        database, isolation_level=None, check_same_thread=False
    )
    connection.execute("PRAGMA foreign_keys=ON")
    first = _open_on_connection(
        connection,
        retrieval_authority=retrieval,
        authenticator=authenticator,
        clock=lambda: now[0],
    )
    second_connection = sqlite3.connect(
        database, isolation_level=None, check_same_thread=False
    )
    second_connection.execute("PRAGMA foreign_keys=ON")
    second = _open_on_connection(
        second_connection,
        retrieval_authority=retrieval,
        authenticator=authenticator,
        clock=lambda: now[0],
    )
    same_principal_barrier = Barrier(2)

    def same_principal_claim(authority):
        same_principal_barrier.wait()
        return authority.claim(attempt.attempt_id, proof=PROOF)

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = tuple(
            future.result()
            for future in (
                executor.submit(same_principal_claim, first),
                executor.submit(same_principal_claim, second),
            )
        )
    first_lease = claims[0]
    assert claims == (first_lease, first_lease)
    assert connection.execute(
        "SELECT count(*) FROM triage_work_item_leases WHERE attempt_id=?",
        (attempt.attempt_id,),
    ).fetchone() == (1,)

    first.release(first_lease.lease_id, proof=PROOF)
    successor = first.restart(
        attempt.attempt_id,
        worker_kind=FixtureWorkerKind.REPLAY,
        worker_version="fixture-v20-competing-race",
        input_digest=_digest(996),
        proof=PROOF,
    )
    competing_barrier = Barrier(2)

    def competing_claim(authority, proof):
        competing_barrier.wait()
        try:
            return authority.claim(successor.attempt_id, proof=proof)
        except TriageExecutionAuthorityError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        competing = tuple(
            future.result()
            for future in (
                executor.submit(competing_claim, first, PROOF),
                executor.submit(competing_claim, second, OTHER_PROOF),
            )
        )
    assert sum(not isinstance(result, Exception) for result in competing) == 1
    assert sum(isinstance(result, TriageExecutionAuthorityError) for result in competing) == 1
    rejection = next(result for result in competing if isinstance(result, Exception))
    assert str(rejection) == "Lease replay owner differs"
    assert connection.execute(
        "SELECT count(*) FROM triage_work_item_leases "
        "WHERE attempt_id=? AND lifecycle='CLAIMED'",
        (successor.attempt_id,),
    ).fetchone() == (1,)

    with pytest.raises(sqlite3.DatabaseError):
        connection.execute(
            "UPDATE triage_worker_attempts SET ordinal=2 WHERE attempt_id=?",
            (attempt.attempt_id,),
        )
    with pytest.raises(sqlite3.DatabaseError):
        connection.execute(
            "UPDATE triage_work_item_leases SET canonical_digest=? WHERE lease_id=?",
            (_digest(999), first_lease.lease_id),
        )
    connection.execute("DROP TRIGGER triage_lease_update_guard")
    connection.execute(
        "UPDATE triage_work_item_leases SET canonical_digest=? WHERE lease_id=?",
        (_digest(999), first_lease.lease_id),
    )
    with pytest.raises(TriageExecutionAuthorityError, match="retained"):
        _open_on_connection(
            connection,
            retrieval_authority=retrieval,
            authenticator=authenticator,
            clock=lambda: now[0],
        )
    second_connection.close()
    connection.close()


def test_public_open_uses_secure_checked_lifecycle_lock_and_idempotent_close(
    tmp_path: Path,
) -> None:
    connection, retrieval, authenticator, authority, now, _, _, _ = _fixture(
        tmp_path
    )
    authority.close()
    connection.close()
    database = tmp_path / "execution-authority.sqlite3"
    opened = open_triage_execution_authority(
        database,
        retrieval_authority=retrieval,
        authenticator=authenticator,
        clock=lambda: now[0],
    )
    with pytest.raises(TriageExecutionAuthorityError, match="writer"):
        open_triage_execution_authority(
            database,
            retrieval_authority=retrieval,
            authenticator=authenticator,
            clock=lambda: now[0],
        )
    opened.close()
    opened.close()

    database.chmod(0o644)
    with pytest.raises(TriageExecutionAuthorityError, match="database file"):
        open_triage_execution_authority(
            database,
            retrieval_authority=retrieval,
            authenticator=authenticator,
            clock=lambda: now[0],
        )
