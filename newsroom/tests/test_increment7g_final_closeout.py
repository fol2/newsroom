from __future__ import annotations

import importlib
import json

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.migrations import EXPECTED_MIGRATION_HISTORY
from newsroom.increment7.agenda import PLANNED_AGENDA_VERSION
from newsroom.increment7.agenda_authority import open_planned_agenda_authority
from newsroom.increment7.closeout import (
    INCREMENT7_CLOSEOUT_RECEIPT,
    INCREMENT7_FINAL_CLOSEOUT_INVENTORY_DIGEST,
    INCREMENT7_FINAL_MIGRATION_HISTORY_DIGEST,
    INCREMENT7_FINAL_NON_EFFECTS,
    INCREMENT7_FINAL_REQUIREMENTS,
    INCREMENT7_FINAL_SCHEMA_FINGERPRINT,
    INCREMENT7_FINAL_SCHEMA_VERSION,
    INCREMENT7G_FINAL_CLOSEOUT_CASES,
    Increment7CloseoutError,
    Increment7CloseoutReceipt,
    Increment7ProofRecord,
    Increment7ProofStage,
    build_increment7_closeout_receipt,
    increment7_final_migration_history,
    validate_increment7_final_closeout_inventory,
)
from newsroom.increment7.coverage import (
    COVERAGE_AUDIT,
    COVERAGE_GAP_DECISION,
)
from newsroom.increment7.coverage_authority import open_coverage_audit_authority
from newsroom.increment7.local_watch import (
    EVENT_SCOPED_LOCAL_WATCH,
    LOCAL_WATCH_CLOSURE,
)
from newsroom.increment7.local_watch_authority import (
    LOCAL_WATCH_REENTRY,
    open_local_watch_authority,
)
from newsroom.increment7.search import (
    SEARCH_ATTEMPT,
    SEARCH_OUTCOME,
    SEARCH_PURPOSE,
    SEARCH_REQUEST,
)
from newsroom.increment7.search_authority import open_bounded_search_authority
from newsroom.tests.test_increment7a2_exact_immutable_read_port import _create
from newsroom.tests.test_increment7c2_coverage_audit_authority import _command
from newsroom.tests.test_increment7d2_local_watch_authority import (
    _append_command,
    _close_command,
    _create_command,
)

_AT = "2042-01-04T00:03:00.000000Z"


def _record(
    stage: Increment7ProofStage,
    schema_id: str,
    record_id: str,
    record_digest: str,
) -> Increment7ProofRecord:
    return Increment7ProofRecord(stage, schema_id, record_id, record_digest)


def test_complete_fixture_path_replays_from_one_shared_authority_database(
    tmp_path,
) -> None:
    database = tmp_path / "increment7-closed-fixture.sqlite3"

    agenda = open_planned_agenda_authority(database, applied_at=_AT)
    item, version, agenda_command, agenda_snapshot = _create(agenda)
    assert agenda.apply(agenda_command.canonical_bytes) == agenda_snapshot
    agenda.close()

    coverage_command, searches, providers, locality = _command()
    purpose, request, attempt, outcome, results, review = searches[0]
    search = open_bounded_search_authority(database, applied_at=_AT)
    assert search.record_purpose(purpose.canonical_bytes) == purpose
    assert search.record_request(request.canonical_bytes) == request
    assert search.record_attempt(attempt.canonical_bytes) == attempt
    assert search.record_outcome(outcome.canonical_bytes) == outcome
    assert search.record_result(results[0].canonical_bytes) == results[0]
    assert search.record_review(review.canonical_bytes) == review
    search.close()

    coverage = open_coverage_audit_authority(database, applied_at=_AT)
    assert (
        coverage.record(
            coverage_command.canonical_bytes,
            search_evidence=searches,
            provider_qualifications=providers,
            locality_qualification=locality,
        )
        == coverage_command.decision
    )
    coverage.close()

    create_watch = _create_command()
    append_watch = _append_command(create_watch)
    close_watch = _close_command(append_watch)
    watch = open_local_watch_authority(database, applied_at=_AT)
    watch.record(create_watch.canonical_bytes)
    watch.record(append_watch.canonical_bytes)
    final_watch = watch.record(close_watch.canonical_bytes)
    assert final_watch.closed is True
    assert final_watch.reentry == close_watch.reentry
    watch.close()

    assert close_watch.closure is not None
    assert close_watch.reentry is not None
    records = (
        _record(
            Increment7ProofStage.AGENDA,
            PLANNED_AGENDA_VERSION,
            version.agenda_version_id,
            version.digest,
        ),
        _record(
            Increment7ProofStage.SEARCH_PURPOSE,
            SEARCH_PURPOSE,
            purpose.purpose_id,
            purpose.digest,
        ),
        _record(
            Increment7ProofStage.SEARCH_REQUEST,
            SEARCH_REQUEST,
            request.request_id,
            request.digest,
        ),
        _record(
            Increment7ProofStage.SEARCH_ATTEMPT,
            SEARCH_ATTEMPT,
            attempt.attempt_id,
            attempt.digest,
        ),
        _record(
            Increment7ProofStage.SEARCH_OUTCOME,
            SEARCH_OUTCOME,
            outcome.outcome_id,
            outcome.digest,
        ),
        _record(
            Increment7ProofStage.COVERAGE_AUDIT,
            COVERAGE_AUDIT,
            coverage_command.audit.audit_id,
            coverage_command.audit.digest,
        ),
        _record(
            Increment7ProofStage.REVIEWED_GAP,
            COVERAGE_GAP_DECISION,
            coverage_command.decision.decision_id,
            coverage_command.decision.digest,
        ),
        _record(
            Increment7ProofStage.EVENT_SCOPED_LOCAL_WATCH,
            EVENT_SCOPED_LOCAL_WATCH,
            close_watch.watch.watch_id,
            close_watch.watch.canonical_digest,
        ),
        _record(
            Increment7ProofStage.WATCH_CLOSURE,
            LOCAL_WATCH_CLOSURE,
            close_watch.closure.closure_id,
            close_watch.closure.canonical_digest,
        ),
        _record(
            Increment7ProofStage.GOVERNED_INCREMENT6_REENTRY,
            LOCAL_WATCH_REENTRY,
            close_watch.reentry.reentry_id,
            close_watch.reentry.digest,
        ),
    )
    receipt = build_increment7_closeout_receipt(
        proof_id="increment7-complete-fixture-v1",
        records=records,
        retained_authority_database=database.read_bytes(),
        recorded_at=_AT,
    )
    assert (
        Increment7CloseoutReceipt.from_canonical_bytes(receipt.canonical_bytes)
        == receipt
    )
    assert receipt.receipt_identity == digest_bytes(receipt.canonical_bytes)
    assert receipt.non_effects == INCREMENT7_FINAL_NON_EFFECTS

    agenda = open_planned_agenda_authority(database, applied_at=_AT)
    search = open_bounded_search_authority(database, applied_at=_AT)
    coverage = open_coverage_audit_authority(database, applied_at=_AT)
    watch = open_local_watch_authority(database, applied_at=_AT)
    try:
        assert agenda.read_port().load(item.agenda_item_id) == agenda_snapshot
        assert search.read_port().request(request.request_id) == request
        assert (
            coverage.read_port().decision(coverage_command.decision.decision_id)
            == coverage_command.decision
        )
        assert watch.read_port().load(close_watch.watch.watch_id) == final_watch
    finally:
        agenda.close()
        search.close()
        coverage.close()
        watch.close()


def test_increment7_closeout_inventory_and_contract_are_exact() -> None:
    validate_increment7_final_closeout_inventory()
    assert len(INCREMENT7G_FINAL_CLOSEOUT_CASES) == 11
    assert INCREMENT7_CLOSEOUT_RECEIPT == "newsroom.increment7.closeout-receipt.v1"
    assert INCREMENT7_FINAL_SCHEMA_VERSION == 29
    assert INCREMENT7_FINAL_SCHEMA_FINGERPRINT == (
        "sha256:68194825ecc7c429b283204dbc1332a43481e04ca2681fcbf75886a984ea6f55"
    )
    assert INCREMENT7_FINAL_MIGRATION_HISTORY_DIGEST == (
        "sha256:02e531a9279e316e7f131beabfef5b2f5d02f6b825b7312f4c6296028ffee4ff"
    )
    assert INCREMENT7_FINAL_CLOSEOUT_INVENTORY_DIGEST == (
        "sha256:0d185ed45c925d8c85f79b6e5437fc717b596956802240bfe27bd15fe9499d8c"
    )
    assert INCREMENT7_FINAL_NON_EFFECTS == tuple(sorted(INCREMENT7_FINAL_NON_EFFECTS))
    assert {case.requirement for case in INCREMENT7G_FINAL_CLOSEOUT_CASES} == (
        INCREMENT7_FINAL_REQUIREMENTS
    )
    assert increment7_final_migration_history(EXPECTED_MIGRATION_HISTORY) == tuple(
        EXPECTED_MIGRATION_HISTORY
    )
    appended = (*EXPECTED_MIGRATION_HISTORY, (30, "future_authorised", "sha256:x"))
    assert increment7_final_migration_history(appended) == tuple(
        EXPECTED_MIGRATION_HISTORY
    )
    changed = list(EXPECTED_MIGRATION_HISTORY)
    changed[28] = (29, "changed", changed[28][2])
    with pytest.raises(Increment7CloseoutError, match="migration history"):
        increment7_final_migration_history(tuple(changed))

    for case in INCREMENT7G_FINAL_CLOSEOUT_CASES:
        module_name, function_name = case.test_id.split("::", 1)
        module = importlib.import_module(module_name)
        assert callable(getattr(module, function_name))


def test_closeout_receipt_rejects_unknown_duplicate_noncanonical_and_reordered() -> (
    None
):
    records = tuple(
        _record(
            stage,
            f"newsroom.fixture.{stage.value.lower()}.v1",
            str(index),
            "sha256:" + f"{index:x}" * 64,
        )
        for index, stage in enumerate(Increment7ProofStage, start=1)
    )
    receipt = build_increment7_closeout_receipt(
        proof_id="strict-fixture",
        records=records,
        retained_authority_database=b"fixture",
        recorded_at=_AT,
    )
    value = json.loads(receipt.canonical_bytes)
    value["unknown"] = False
    with pytest.raises(Increment7CloseoutError):
        Increment7CloseoutReceipt.from_canonical_bytes(canonical_json_bytes(value))
    duplicate = receipt.canonical_bytes.replace(
        b'{"inventory_digest":',
        b'{"inventory_digest":"sha256:' + b"0" * 64 + b'","inventory_digest":',
        1,
    )
    with pytest.raises(Increment7CloseoutError, match="duplicate"):
        Increment7CloseoutReceipt.from_canonical_bytes(duplicate)
    with pytest.raises(Increment7CloseoutError, match="canonical"):
        Increment7CloseoutReceipt.from_canonical_bytes(receipt.canonical_bytes + b"\n")
    with pytest.raises(Increment7CloseoutError, match="stage order"):
        build_increment7_closeout_receipt(
            proof_id="reordered",
            records=tuple(reversed(records)),
            retained_authority_database=b"fixture",
            recorded_at=_AT,
        )
