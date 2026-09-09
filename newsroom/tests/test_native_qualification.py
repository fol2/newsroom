import json
import sqlite3
from types import SimpleNamespace as NS

import pytest

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
)
from newsroom.control_plane.model_usage import (
    CONSERVATIVE_DISPOSITION_SCHEMA_VERSION,
    ModelUsageService,
    WorkloadClass,
)
from newsroom.control_plane.native_progress import NativeRevisionJournal
from newsroom.control_plane.native_qualification import (
    NativeQualificationError,
    record_qualification,
    validate_qualification,
)
from newsroom.control_plane.store import append_ledger, connect
from newsroom.increment9.proving import SOURCE_IDS
from newsroom.tests.test_native_graphiti import _native

IDENTITY = "sha256:" + "a" * 64


def _open(path):
    ModelUsageService(str(path))
    return connect(str(path))


def _portfolio(journal, unit=None, *, first_reason=None, source_override=None):
    rights_holds = {
        "HK-01": "MEDIA_REUSE_PERMISSION_SCOPE_NOT_ESTABLISHED",
        "HK-04": "NON_COMMERCIAL_INTERNAL_USE_ONLY",
        "RAD-01": "AUTOMATED_REUSE_PERMISSION_NOT_RETAINED",
        "RAD-02": "COMPUTER_ANALYSIS_PERMISSION_NOT_RETAINED",
    }
    dispositions = tuple(
        NS(
            source_id=source_id, status="HOLD" if source_id in rights_holds else "READY",
            reason_code=(
                first_reason if source_id == SOURCE_IDS[0] and first_reason
                else rights_holds[source_id] if source_id in rights_holds
                else "NO_ACTIVE_WARNINGS_OBSERVED"
                if source_id in {"UK-10", "HK-02"}
                else "GOVERNED_REVISIONS_RETAINED"
            ),
            units=(unit,) if unit is not None and source_id == unit.source_id else (),
            observations=((
                f"https://terms.example/{source_id}",
                digest_canonical({"terms": source_id}),
                f"admission-{source_id}",
                f"access-{source_id}",
            ),) if source_id in rights_holds else (),
            item_holds=(),
        )
        for source_id in SOURCE_IDS
    )
    if source_override is not None:
        dispositions = (
            NS(**{**vars(dispositions[0]), **source_override}), *dispositions[1:],
        )
    journal.sources(dispositions)


def _cycle(
    connection,
    *,
    identity=IDENTITY,
    outcome="COMPLETE",
    queued=0,
    revision_state="EVIDENCE_HOLD",
    reason="SOURCE_LOCAL_EVIDENCE_HOLD",
    source_reason=None,
    source_override=None,
):
    journal = NativeRevisionJournal(connection)
    unit = _native("qualification-hold")
    journal.land((unit,))
    journal.advance(unit.revision_id, stage=revision_state, facts={"reason": reason})
    _portfolio(journal, unit, first_reason=source_reason, source_override=source_override)
    append_ledger(connection, "NATIVE_SERVICE_CYCLE_STARTED", {
        "cycle_id": "qualification-cycle", "runtime_identity_digest": identity,
    })
    connection.commit()
    append_ledger(connection, "NATIVE_SERVICE_CYCLE_TERMINAL", {
        "runtime_identity_digest": identity,
        "cycle_id": "qualification-cycle",
        "outcome": outcome,
        "failure_class": None if outcome == "COMPLETE" else "RuntimeError",
        "pipeline": {
            "sources": list(journal.portfolio),
            "revision_states": {
                revision_state: 1, **({"QUEUED": queued} if queued else {})
            },
            "unclassified_revisions": queued,
        },
    })
    connection.commit()
    return journal


def _allocation(
    connection,
    *,
    usage_status=None,
    workload=WorkloadClass.NATIVE_EVIDENCE_ASSESSOR,
    provider="fixture",
    route="fixture",
    ingest_id=None,
):
    workload_value = workload.value
    policy = digest_canonical({"policy": workload_value})
    envelope = digest_canonical({"envelope": workload_value})
    invocation = digest_canonical({"invocation": workload_value})
    policy_record = canonical_json_bytes({"policy": policy}).decode()
    envelope_value = {
        "envelope_id": envelope,
        "cycle_id": "qualification-model-cycle",
        "workload_class": workload_value,
        "candidate_id": "candidate-1",
    }
    if ingest_id is not None:
        envelope_value["ingest_id"] = ingest_id
    envelope_record = canonical_json_bytes(envelope_value).decode()
    allocation_record = canonical_json_bytes({
        "canonical_digest": invocation,
        "invocation_id": invocation,
        "envelope_id": envelope,
        "cycle_id": "qualification-model-cycle",
        "workload_class": workload_value,
        "policy_digest": policy,
        "provider": provider,
        "route": route,
    }).decode()
    connection.execute(
        "INSERT INTO model_invocation_policies VALUES(?,?,?,?,?,?,?,?,?)",
        (policy, "qualification-policy", "v1", workload_value,
         provider, route, "fixture", 1, policy_record),
    )
    connection.execute(
        "INSERT INTO model_work_envelopes VALUES(?,?,?,?,?,?)",
        (envelope, "qualification-model-cycle", workload_value,
         "2026-09-09T00:00:00.000000Z", envelope, envelope_record),
    )
    connection.execute(
        "INSERT INTO model_invocation_allocations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (invocation, envelope, "qualification-model-cycle", 1,
         workload_value, policy, provider, route,
         "fixture", digest_canonical({"request": 1}), None,
         "2026-09-09T00:00:00.000000Z", invocation, allocation_record),
    )
    if usage_status is not None:
        terminal = {
            "schema_version": "newsroom.model-usage.v3",
            "terminal_digest": "",
            "invocation_id": invocation,
            "outcome": "COMPLETE",
            "failure_class": (
                "MISSING_PROVIDER_TELEMETRY"
                if usage_status == "UNREPORTED" else None
            ),
            "usage_status": usage_status,
            "components": {"total_tokens": 1, "provenance": "PROVIDER_REPORTED"},
            "dispatch_at": "2026-09-09T00:00:01.000000Z",
            "completed_at": "2026-09-09T00:00:02.000000Z",
            "observed_at": "2026-09-09T00:00:02.000000Z",
            "provider_telemetry_digest": digest_canonical({"telemetry": 1}),
            "raw_telemetry_pointer": None,
            "estimate_policy_digest": None,
            "estimate_calculation": None,
            "pre_dispatch_zero_proved": False,
            "od_011_reference": None,
            "subscription_cli_chat_not_cash_debited": (
                workload is WorkloadClass.GRAPHITI_CHAT_PRIMARY
            ),
            "policy_breach": None,
        }
        terminal_digest = digest_canonical(terminal)
        terminal["terminal_digest"] = terminal_digest
        connection.execute(
            "INSERT INTO model_invocation_terminals VALUES(?,?,?,?,?,?,?)",
            (terminal_digest, invocation, usage_status, "COMPLETE",
             terminal["failure_class"], "2026-09-09T00:00:02.000000Z",
             canonical_json_bytes(terminal).decode()),
        )
    connection.commit()
    return invocation


def _conservative_disposition(connection, invocation):
    terminal_digest = connection.execute(
        "SELECT terminal_digest FROM model_invocation_terminals WHERE invocation_id=?",
        (invocation,),
    ).fetchone()[0]
    allocation_digest, policy_digest = connection.execute(
        "SELECT canonical_digest,policy_digest FROM model_invocation_allocations "
        "WHERE invocation_id=?", (invocation,),
    ).fetchone()
    record = {
        "schema_version": CONSERVATIVE_DISPOSITION_SCHEMA_VERSION,
        "invocation_id": invocation,
        "terminal_digest": terminal_digest,
        "allocation_digest": allocation_digest,
        "policy_digest": policy_digest,
        "approved_plan_digest": digest_canonical({"plan": 1}),
        "usage_status": "ESTIMATED",
        "components": {"total_tokens": 1, "provenance": "BOUNDED_ESTIMATE"},
        "estimate_policy_digest": policy_digest,
        "estimate_calculation": (
            "QUALIFIED_POLICY_MAX_TOTAL_TOKENS_CONSERVATIVE_UPPER_BOUND"
        ),
        "exact_usage_remains_unknown": True,
        "provider_dispatch_preserved": True,
        "unknown_spend_released": False,
        "authority_digest": digest_canonical({"authority": 1}),
        "approved_by": "github:fol2",
        "approval_reference": "retained:test",
        "approved_at": "2026-09-09T00:00:03.000000Z",
        "observed_at": "2026-09-09T00:00:03.000000Z",
    }
    digest = digest_canonical(record)
    record["disposition_digest"] = digest
    connection.execute(
        "INSERT INTO model_usage_conservative_dispositions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (digest, invocation, terminal_digest, allocation_digest, policy_digest,
         record["approved_plan_digest"], record["authority_digest"],
         record["approved_by"], record["approval_reference"], record["approved_at"],
         record["observed_at"], "ESTIMATED", canonical_json_bytes(record).decode()),
    )
    connection.commit()


def test_exact_identity_cycle_with_evidenced_hold_qualifies(tmp_path):
    path = tmp_path / "private.sqlite3"
    connection = _open(path)
    try:
        _cycle(connection)
        record_qualification(connection, IDENTITY)
        retained = validate_qualification(connection, IDENTITY)
        assert retained.cycle_id == "qualification-cycle"
        assert retained.started_seq < retained.terminal_seq
        assert retained.invocation_ids == ()
        assert retained.runtime_identity_digest == IDENTITY

        _cycle(connection, outcome="FAILED")
        _allocation(connection, workload=WorkloadClass.NATIVE_RETRIEVAL_EMBEDDING)
        assert validate_qualification(connection, IDENTITY) == retained
    finally:
        connection.close()

    readonly = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        assert validate_qualification(readonly, IDENTITY) == retained
    finally:
        readonly.close()

    typed_hold = _open(tmp_path / "typed-hold.sqlite3")
    try:
        _cycle(
            typed_hold,
            revision_state="RETRIEVAL_HOLD",
            reason="CURRENT_SOURCE_REVISION_UNAVAILABLE",
        )
        record_qualification(typed_hold, IDENTITY)
    finally:
        typed_hold.close()


def test_legacy_drift_failed_and_unfinished_cycles_never_qualify(tmp_path):
    for case in (
        "legacy", "drift", "failed", "queued", "invented", "generic",
        "source_missing",
    ):
        connection = _open(tmp_path / f"{case}.sqlite3")
        try:
            if case == "legacy":
                journal = NativeRevisionJournal(connection)
                _portfolio(journal)
                append_ledger(connection, "NATIVE_SERVICE_CYCLE_STARTED", {"cycle_id": "old"})
                append_ledger(connection, "NATIVE_SERVICE_CYCLE_TERMINAL", {
                    "cycle_id": "old", "outcome": "COMPLETE", "failure_class": None,
                    "pipeline": {"sources": list(journal.portfolio), "revision_states": {},
                                 "unclassified_revisions": 0},
                })
                connection.commit()
            else:
                _cycle(
                    connection,
                    identity="sha256:" + "b" * 64 if case == "drift" else IDENTITY,
                    outcome="FAILED" if case == "failed" else "COMPLETE",
                    queued=1 if case == "queued" else 0,
                    revision_state=(
                        "INVENTED_HOLD" if case == "invented" else "EVIDENCE_HOLD"
                    ),
                    reason="RuntimeError" if case == "generic" else "RETAINED_HOLD",
                    source_reason=(
                        "SOURCE_DEFINITION_MISSING"
                        if case == "source_missing" else None
                    ),
                )
            with pytest.raises(NativeQualificationError):
                record_qualification(connection, IDENTITY)
        finally:
            connection.close()


def _content_hold(reason="SOURCE_ITEM_NOT_YET_PUBLISHED"):
    return {
        "status": "HOLD", "reason_code": "SOURCE_ITEMS_HELD",
        "item_holds": (("https://www.gov.uk/held-item", reason),),
        "observations": ((
            "https://www.gov.uk/api/content/held-item",
            digest_canonical({"retained": "source content"}),
            "00000000-0000-4000-8000-000000000101",
            "00000000-0000-4000-8000-000000000102",
        ),),
    }


@pytest.mark.parametrize("reason", [
    "SOURCE_ITEM_NOT_YET_PUBLISHED",
    "SOURCE_ITEM_CHILD_COVERAGE_INCOMPLETE",
    "SOURCE_ITEM_ATTACHMENT_COVERAGE_INCOMPLETE",
])
def test_observation_bound_content_hold_qualifies_without_hiding_sibling(tmp_path, reason):
    path = tmp_path / "content-hold.sqlite3"
    connection = _open(path)
    try:
        journal = _cycle(connection, source_override=_content_hold(reason))
        retained = record_qualification(connection, IDENTITY)
        source = journal.portfolio[0]
        assert source["status"] == "HOLD"
        assert source["item_holds"] == [["https://www.gov.uk/held-item", reason]]
        assert source["revision_ids"] == sorted(journal.units)
        assert validate_qualification(connection, IDENTITY) == retained
    finally:
        connection.close()
    readonly = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        assert validate_qualification(readonly, IDENTITY) == retained
    finally:
        readonly.close()


@pytest.mark.parametrize("case", [
    "metadata", "transport", "invented", "missing_observation", "wrong_url",
    "duplicate_observation", "bad_digest", "bad_admission", "bad_access",
    "no_items", "duplicate_items", "ready", "rights_reason", "other_route",
])
def test_unclassified_or_unbound_content_hold_does_not_qualify(tmp_path, case):
    value = _content_hold()
    if case in {"metadata", "transport", "invented"}:
        reason = {
            "metadata": "SOURCE_ITEM_METADATA_HOLD",
            "transport": "SOURCE_ITEM_FETCH_INCOMPLETE",
            "invented": "INVENTED_HOLD",
        }[case]
        value = _content_hold(reason)
    elif case == "missing_observation":
        value["observations"] = ()
    elif case in {"wrong_url", "bad_digest", "bad_admission", "bad_access"}:
        parts = list(value["observations"][0])
        index = {"wrong_url": 0, "bad_digest": 1, "bad_admission": 2, "bad_access": 3}[case]
        parts[index] = "https://www.gov.uk/api/content/unrelated" if index == 0 else "invalid"
        value["observations"] = (tuple(parts),)
    elif case == "duplicate_observation":
        value["observations"] *= 2
    elif case == "no_items":
        value["item_holds"] = ()
    elif case == "duplicate_items":
        value["item_holds"] *= 2
    elif case == "ready":
        value.update(status="READY", reason_code="GOVERNED_REVISIONS_RETAINED")
    elif case == "rights_reason":
        value["reason_code"] = "MEDIA_REUSE_PERMISSION_SCOPE_NOT_ESTABLISHED"
    elif case == "other_route":
        value["item_holds"] = (("https://example.org/held-item", value["item_holds"][0][1]),)
    connection = _open(tmp_path / f"{case}.sqlite3")
    try:
        _cycle(connection, source_override=value)
        with pytest.raises(NativeQualificationError):
            record_qualification(connection, IDENTITY)
    finally:
        connection.close()


def test_only_referenced_native_ledger_rows_enter_qualification(tmp_path):
    connection = _open(tmp_path / "bounded-ledger.sqlite3")
    try:
        append_ledger(connection, "UNRELATED_HISTORICAL_EVENT", {"value": "before"})
        connection.commit()
        _cycle(connection)
        record_qualification(connection, IDENTITY)

        connection.execute(
            "UPDATE ledger SET payload_json='{}' "
            "WHERE kind='UNRELATED_HISTORICAL_EVENT'"
        )
        connection.commit()
        assert validate_qualification(connection, IDENTITY).cycle_id == (
            "qualification-cycle"
        )

        connection.execute(
            "UPDATE ledger SET payload_json='{}' "
            "WHERE kind='NATIVE_REVISION_PROGRESS'"
        )
        connection.commit()
        with pytest.raises(NativeQualificationError, match="native ledger payload"):
            validate_qualification(connection, IDENTITY)
    finally:
        connection.close()


def test_same_count_revision_fact_mutation_does_not_match_reference(tmp_path):
    connection = _open(tmp_path / "revision-mutation.sqlite3")
    try:
        _cycle(connection)
        retained = record_qualification(connection, IDENTITY)
        seq, at, kind, previous = connection.execute(
            "SELECT seq,at,kind,prev_digest FROM ledger "
            "WHERE kind='NATIVE_REVISION_PROGRESS'"
        ).fetchone()
        payload = {
            "revision_id": next(iter(NativeRevisionJournal(connection).units)),
            "ordinal": 1,
            "stage": "EVIDENCE_HOLD",
            "facts": {"reason": "DIFFERENT_RETAINED_HOLD"},
        }
        raw = canonical_json_bytes(payload)
        payload_digest = digest_bytes(raw)
        ledger_digest = digest_bytes(canonical_json_bytes({
            "at": at, "kind": kind, "payload_digest": payload_digest,
            "prev": previous,
        }))
        connection.execute(
            "UPDATE ledger SET payload_json=?,payload_digest=?,digest=? WHERE seq=?",
            (raw.decode(), payload_digest, ledger_digest, seq),
        )
        connection.commit()
        with pytest.raises(NativeQualificationError):
            validate_qualification(connection, IDENTITY)
        assert retained.revision_inventory_digest != digest_canonical(
            {"EVIDENCE_HOLD": 1}
        )
    finally:
        connection.close()


def test_native_invocation_must_have_resolved_retained_usage(tmp_path):
    unfinished = _open(tmp_path / "unfinished.sqlite3")
    try:
        _cycle(unfinished)
        _allocation(unfinished)
        with pytest.raises(NativeQualificationError, match="in flight"):
            record_qualification(unfinished, IDENTITY)
    finally:
        unfinished.close()

    resolved = _open(tmp_path / "resolved.sqlite3")
    try:
        _cycle(resolved)
        invocation = _allocation(resolved, usage_status="REPORTED")
        record_qualification(resolved, IDENTITY)
        assert validate_qualification(resolved, IDENTITY).invocation_ids == (invocation,)
    finally:
        resolved.close()

    unknown = _open(tmp_path / "unknown.sqlite3")
    try:
        _cycle(unknown)
        _allocation(unknown, usage_status="UNREPORTED")
        with pytest.raises(NativeQualificationError, match="unresolved"):
            record_qualification(unknown, IDENTITY)
    finally:
        unknown.close()

    reconciled = _open(tmp_path / "reconciled.sqlite3")
    try:
        journal = _cycle(reconciled)
        ingest_id = next(iter(journal.units.values()))[0].ingest_id
        invocation = _allocation(
            reconciled,
            usage_status="UNREPORTED",
            workload=WorkloadClass.GRAPHITI_CHAT_PRIMARY,
            provider="cursor-agent-cli",
            route=WorkloadClass.GRAPHITI_CHAT_PRIMARY.value,
            ingest_id=ingest_id,
        )
        observation = digest_canonical({"dispatch": invocation})
        reconciled.execute(
            "INSERT INTO model_transport_observations VALUES(?,?,?,?,?,?)",
            (
                observation,
                invocation,
                "2026-09-09T00:00:01.000000Z",
                "DISPATCH_STARTED",
                observation,
                canonical_json_bytes({"dispatch": invocation}).decode(),
            ),
        )
        reconciled.commit()
        _conservative_disposition(reconciled, invocation)
        record_qualification(reconciled, IDENTITY)
        assert validate_qualification(reconciled, IDENTITY).invocation_ids == (
            invocation,
        )
    finally:
        reconciled.close()
