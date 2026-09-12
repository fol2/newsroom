"""Native retry proof is bounded by selected immutable attempt identities."""

import json
import sqlite3
from datetime import timedelta

import pytest

from newsroom.control_plane import model_usage as usage_module
from newsroom.control_plane.cycle import _graphiti_usage_cycle_id, _queue
from newsroom.control_plane.model_usage import (
    InvocationTerminal, ModelUsageIntegrityError, ModelUsageService, UsageComponents, UsageStatus,
    WorkEnvelope, WorkloadClass,
)
from newsroom.control_plane.store import connect, record_graphiti_failure
from newsroom.tests.test_graphiti_internal_requests import T0, _bound_request, _service_fixture
from newsroom.tests.test_model_usage_receipts import _reported
from newsroom.tests.test_native_graphiti import _native


def _attempt(service, policy, shape, unit, number):
    envelope = WorkEnvelope.create(
        cycle_id=_graphiti_usage_cycle_id(unit, attempt_number=number, requested_cycle_id=None),
        workload_class=WorkloadClass.GRAPHITI_CHAT_PRIMARY, admitted_at=T0,
        admission_decision_id=None, candidate_id=None, hypothesis_digest=None,
        evidence_package_digest=None, ingest_id=unit.ingest_id,
        graphiti_attempt_id=f"{unit.ingest_id}:{number}",
    )
    service.open_envelope(envelope)
    allocation, identity = _bound_request(
        service=service, envelope=envelope, policy=policy, shape=shape,
        ordinal=1, semantic=f"{unit.ingest_id}:{number}",
    )
    service.allocate_graphiti_request(
        allocation, identity=identity,
        max_distinct_internal_requests=shape.max_distinct_internal_requests,
    )
    return envelope, allocation


def _settle(service, envelope, allocation, *, zero):
    if zero:
        terminal = service.complete(InvocationTerminal.create(
            invocation_id=allocation.invocation_id, outcome="DISPATCH_FENCE_REFUSED",
            failure_class="DISPATCH_FENCE_REFUSED", usage_status=UsageStatus.REPORTED,
            components=UsageComponents(total_tokens=0, provenance="CLI_DERIVED"),
            dispatch_at=None, completed_at=T0 + timedelta(seconds=2),
            observed_at=T0 + timedelta(seconds=2), pre_dispatch_zero_proved=True,
            subscription_cli_chat_not_cash_debited=True,
        ))
    else:
        terminal = _reported(allocation, outcome="FAILED")
        service.observe_transport(
            invocation_id=allocation.invocation_id, observed_at=terminal.dispatch_at,
            state="DISPATCH_STARTED", evidence_digest=allocation.canonical_digest,
        )
        terminal = service.complete(
            terminal, provider_telemetry={"invocation": allocation.invocation_id},
        )
    service.record_work_outcome(
        envelope_id=envelope.envelope_id, outcome="GRAPHITI_FAILED",
        outcome_record_id=f"failed:{allocation.invocation_id}", payload_digest=None,
        terminal_at=terminal.completed_at,
    )


def _failures(connection, unit, count=3):
    for _ in range(count):
        record_graphiti_failure(
            connection, ingest_id=unit.ingest_id, source_id=unit.source_id,
            item_key=unit.item_key, outcome="FAILED", failure_code="TEST_FAILURE",
        )
    connection.commit()


def test_unchanged_native_queue_decodes_only_selected_attempts_as_history_grows(tmp_path, monkeypatch):
    service, _, policy, shape = _service_fixture(tmp_path)
    unit = _native("selected")
    for number in range(1, 4):
        _settle(service, *_attempt(service, policy, shape, unit, number), zero=False)
    connection = connect(service.path)
    _failures(connection, unit)
    decoded = []
    original_envelope = usage_module._envelope_from_record
    original_allocation = usage_module._allocation_from_record
    original_object = usage_module._object

    def decode_object(raw):
        record = original_object(raw)
        if "outcome_record_id" in record:
            decoded.append("outcome")
        if "observation_digest" in record and "state" in record:
            decoded.append("transport")
        return record

    monkeypatch.setattr(usage_module, "_object", decode_object)
    monkeypatch.setattr(usage_module, "_envelope_from_record",
                        lambda record: (decoded.append("envelope"), original_envelope(record))[1])
    monkeypatch.setattr(usage_module, "_allocation_from_record",
                        lambda record: (decoded.append("allocation"), original_allocation(record))[1])
    for tick in range(2):
        for index in range(10):
            _settle(service, *_attempt(
                service, policy, shape, _native(f"unrelated-{tick}-{index}"), 1,
            ), zero=False)
        decoded.clear()
        assert _queue(connection, (unit,), model_usage=service) == []
        assert all(decoded.count(kind) == 3 for kind in (
            "envelope", "allocation", "outcome", "transport",
        ))
    connection.close()


def _proof(service, unit, failed=1):
    return service.native_graphiti_ingest_retry_evidence_many(
        failed_attempts={unit.ingest_id: failed}, max_attempts=6,
    )[unit.ingest_id]


def test_native_retry_rechecks_pending_settlement_without_a_cache(tmp_path):
    service, _, policy, shape = _service_fixture(tmp_path)
    unit = _native("later-settlement")
    for number in (1, 2):
        _settle(service, *_attempt(service, policy, shape, unit, number), zero=True)
    envelope, allocation = _attempt(service, policy, shape, unit, 3)
    connection = connect(service.path)
    _failures(connection, unit)
    assert _proof(service, unit, 3).unresolved_attempts == (3,)
    assert _queue(connection, (unit,), model_usage=service) == []
    _settle(service, envelope, allocation, zero=True)
    assert _proof(service, unit, 3).zero_dispatch_attempts == (1, 2, 3)
    assert [entry[-1] for entry in _queue(connection, (unit,), model_usage=service)] == [unit]
    connection.close()


def test_native_retry_probes_unsettled_attempt_above_raw_failure_count(tmp_path):
    service, _, policy, shape = _service_fixture(tmp_path)
    unit = _native("pending-next")
    for number in (1, 2, 3):
        _settle(service, *_attempt(service, policy, shape, unit, number), zero=True)
    _attempt(service, policy, shape, unit, 4)
    assert _proof(service, unit, 3).unresolved_attempts == (4,)


@pytest.mark.parametrize("missing", ["envelope", "request", "allocation", "terminal", "outcome", "all-leaves"])
def test_native_zero_credit_requires_positive_complete_retained_leaf_proof(tmp_path, missing):
    service, _, policy, shape = _service_fixture(tmp_path)
    unit = _native("missing-binding")
    if missing != "envelope":
        envelope, allocation = _attempt(service, policy, shape, unit, 1)
        _settle(service, envelope, allocation, zero=True)
        assert _proof(service, unit).zero_dispatch_attempts == (1,)
        with sqlite3.connect(service.path) as connection:
            tables = {
                "request": ("graphiti_internal_requests",),
                "allocation": ("model_invocation_allocations",),
                "terminal": ("model_invocation_terminals",),
                "outcome": ("model_work_outcomes",),
                "all-leaves": ("model_invocation_allocations", "graphiti_internal_requests"),
            }[missing]
            for table in tables:
                connection.execute(f"DELETE FROM {table}")
    evidence = _proof(service, unit)
    assert evidence.attempt_numbers == evidence.unresolved_attempts == (1,)
    assert evidence.zero_dispatch_attempts == ()


@pytest.mark.parametrize("table,field,raw", [
    ("model_work_envelopes", "ingest_id", True),
    ("model_work_envelopes", "graphiti_attempt_id", True),
    ("model_work_envelopes", "both-identities", True),
    ("model_invocation_allocations", "envelope_id", False),
    ("model_invocation_allocations", "envelope_id", True),
    ("graphiti_internal_requests", "graphiti_attempt_id", False),
    ("graphiti_internal_requests", "envelope_id", False),
    ("graphiti_internal_requests", "ingest_obligation_id", True),
    ("graphiti_internal_requests", "canonical_digest", True),
    ("model_work_outcomes", "envelope_id", True),
])
def test_native_retry_rejects_selected_identity_retarget(tmp_path, table, field, raw):
    service, unrelated, policy, shape = _service_fixture(tmp_path)
    unit = _native("retargeted")
    envelope, allocation = _attempt(service, policy, shape, unit, 1)
    _settle(service, envelope, allocation, zero=True)
    key = "envelope_id" if table != "graphiti_internal_requests" else "invocation_id"
    value = envelope.envelope_id if key == "envelope_id" else allocation.invocation_id
    with sqlite3.connect(service.path) as connection:
        if raw:
            record = json.loads(connection.execute(
                f"SELECT record_json FROM {table} WHERE {key}=?", (value,),
            ).fetchone()[0])
            fields = ("ingest_id", "graphiti_attempt_id") if field == "both-identities" else (field,)
            for name in fields:
                record[name] = unrelated.as_record().get(name, "changed")
            connection.execute(f"UPDATE {table} SET record_json=? WHERE {key}=?",
                               (json.dumps(record), value))
        else:
            changed = unrelated.envelope_id if field == "envelope_id" else unrelated.graphiti_attempt_id
            connection.execute(f"UPDATE {table} SET {field}=? WHERE {key}=?", (changed, value))
    with pytest.raises(ModelUsageIntegrityError):
        _proof(service, unit)


def test_native_outcome_index_retarget_is_unresolved_not_zero_credit(tmp_path):
    service, unrelated, policy, shape = _service_fixture(tmp_path)
    unit = _native("retargeted-outcome")
    envelope, allocation = _attempt(service, policy, shape, unit, 1)
    _settle(service, envelope, allocation, zero=True)
    with sqlite3.connect(service.path) as connection:
        connection.execute("UPDATE model_work_outcomes SET envelope_id=? WHERE envelope_id=?",
                           (unrelated.envelope_id, envelope.envelope_id))
    evidence = _proof(service, unit)
    assert evidence.unresolved_attempts == (1,)
    assert evidence.zero_dispatch_attempts == ()


def test_native_retry_queries_use_existing_selected_identity_indexes(tmp_path, monkeypatch):
    service, _, policy, shape = _service_fixture(tmp_path)
    unit = _native("indexed-proof")
    _settle(service, *_attempt(service, policy, shape, unit, 1), zero=False)
    statements = []
    original_connection = service._connection

    def traced_connection():
        connection = original_connection()
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(service, "_connection", traced_connection)
    _proof(service, unit)
    selected = [statement for statement in statements if statement.startswith((
        "SELECT envelope_id,", "SELECT outcome_digest,", "SELECT a.invocation_id,",
        "SELECT canonical_digest,invocation_id,",
        "SELECT observation_digest,observed_at,state,evidence_digest,record_json ",
    ))]
    assert len(selected) == 5
    with sqlite3.connect(service.path) as connection:
        for statement in selected:
            plan = tuple(row[3] for row in connection.execute("EXPLAIN QUERY PLAN " + statement))
            assert not any(detail.startswith("SCAN ") for detail in plan), plan
            assert not any("TEMP B-TREE" in detail for detail in plan
                           if "model_transport_observations" in statement), plan


def test_transport_index_installs_on_existing_store_without_changing_evidence(tmp_path):
    service, _, policy, shape = _service_fixture(tmp_path)
    unit = _native("existing-store-index")
    _settle(service, *_attempt(service, policy, shape, unit, 1), zero=False)
    before = _proof(service, unit)
    with sqlite3.connect(service.path) as connection:
        connection.execute("DROP INDEX model_usage_transport_invocation")
        observations = tuple(connection.execute("SELECT * FROM model_transport_observations"))
    reopened = ModelUsageService(service.path)
    assert _proof(reopened, unit) == before
    with sqlite3.connect(service.path) as connection:
        assert tuple(connection.execute("SELECT * FROM model_transport_observations")) == observations
        assert tuple(row[2] for row in connection.execute(
            "PRAGMA index_info(model_usage_transport_invocation)"
        )) == ("invocation_id", "observed_at", "observation_digest")
