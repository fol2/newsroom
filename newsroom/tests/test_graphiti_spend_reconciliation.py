from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from newsroom.authority.auth import (
    AuthenticationError,
    AuthenticationProof,
    StaticAuthenticator,
    StaticPrincipal,
)
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.control_plane.command_service import ControlPlaneCommandService
from newsroom.control_plane.graphiti_spend_reconciliation import (
    GraphitiSpendDisposition,
    GraphitiSpendReconciliationError,
    GraphitiSpendReconciliationPlan,
    plan_graphiti_spend_reconciliation,
)
from newsroom.control_plane.store import (
    append_ledger,
    claim_graphiti_attempt,
    connect,
    insert_graphiti_attempt_receipt,
    reconcile_graphiti_spend,
    reserve_graphiti_spend,
)
from newsroom.control_plane.usage import graphiti_usage_report
from newsroom.control_plane.veto import VetoError
from newsroom.graphiti_adapter.evaluation_packet import GRAPHITI_GENERATION_ID
from newsroom.graphiti_adapter.usage_meter import summarise_graphiti_usage
from scripts.reconcile_graphiti_spend import main as reconciliation_main


def _reserve(connection: sqlite3.Connection, *, ingest_id: str, attempt: int) -> str:
    spend_id = f"{ingest_id}:{attempt}"
    assert reserve_graphiti_spend(
        connection,
        spend_id=spend_id,
        ingest_id=ingest_id,
        attempt_number=attempt,
        proving_run_id="run-1",
        generation_id=GRAPHITI_GENERATION_ID,
        reserved_gbp_microunits=500_000,
        ceiling_gbp_microunits=5_000_000,
    )
    return spend_id


def _provider_usage(cost: int = 17) -> dict[str, object]:
    return {
        "requests": [
            {
                "provider": "openrouter",
                "model": "openai/text-embedding-3-large",
                "request_id": "request-1",
                "prompt_tokens": 11,
                "total_tokens": 11,
                "cost_usd_microunits": cost,
                "cost_reported": True,
                "outcome": "COMPLETE",
            }
        ],
        "request_count": 1,
        "embedding_tokens": 11,
        "cost_usd_microunits": cost,
        "usage_basis": "PROVIDER_REPORTED",
    }


def _no_embedding_usage() -> dict[str, object]:
    return {
        "requests": [],
        "request_count": 0,
        "embedding_tokens": 0,
        "cost_usd_microunits": 0,
        "usage_basis": "NO_EMBEDDING_CALL",
    }


def _token_usage(*, embedding_cost: int = 17) -> dict[str, object]:
    return {
        "usage_basis": "PROVIDER_REPORTED",
        "chat_request_count": 0,
        "cursor_request_count": 0,
        "grok_request_count": 0,
        "chat_input_tokens": 0,
        "chat_output_tokens": 0,
        "chat_cached_read_tokens": 0,
        "chat_cached_write_tokens": 0,
        "chat_reasoning_tokens": 0,
        "chat_total_tokens": 0,
        "embedding_request_count": 1,
        "embedding_tokens": 11,
        "embedding_cost_usd_microunits": embedding_cost,
        "observed_total_tokens": 11,
        "unreported_chat_requests": 0,
    }


def _journal(
    spend_id: str,
    *,
    ingest_id: str,
    attempt_number: int,
    **evidence: object,
) -> dict[str, object]:
    value = {
        "evidence_source": "GRAPH_JOURNAL_EXPORT_V1",
        "journal_record_id": f"journal:{spend_id}",
        "spend_id": spend_id,
        "ingest_id": ingest_id,
        "attempt_number": attempt_number,
        **evidence,
    }
    value["evidence_digest"] = digest_bytes(canonical_json_bytes(value))
    return value


def _command_service(
    *, principal_id: str = "newsroom.hermes"
) -> ControlPlaneCommandService:
    return ControlPlaneCommandService(
        authenticator=StaticAuthenticator(
            credentials={"operator-token": StaticPrincipal(principal_id=principal_id)},
            authority_domain="newsroom.control-plane",
        )
    )


def _apply_missing_reconciliation(
    path: Path, *, idempotency_key: str
) -> tuple[
    ControlPlaneCommandService,
    GraphitiSpendReconciliationPlan,
    datetime,
    AuthenticationProof,
]:
    connection = connect(str(path))
    spend_id = _reserve(connection, ingest_id=idempotency_key, attempt=1)
    accounting = reconcile_graphiti_spend(
        connection, spend_id=spend_id, embedding_usage=None
    )
    insert_graphiti_attempt_receipt(
        connection,
        ingest_id=idempotency_key,
        attempt_number=1,
        outcome="FAILED",
        receipt={
            "ingest_id": idempotency_key,
            "attempt_number": 1,
            "outcome": "FAILED",
            "provider_attempt_number": 1,
            "chat_invocations": [],
            "embedding_usage": None,
            "accounting": accounting,
        },
    )
    connection.commit()
    connection.close()
    evaluated_at = datetime(2026, 8, 24, tzinfo=UTC)
    plan = plan_graphiti_spend_reconciliation(str(path), evaluated_at=evaluated_at)
    service = _command_service()
    proof = AuthenticationProof(method="STATIC_TOKEN", credential="operator-token")
    service.reconcile_graphiti_spend(
        unpublished_store=str(path),
        dry_run_plan=plan.as_dict(),
        evaluated_at=evaluated_at,
        idempotency_key=idempotency_key,
        expected_plan_digest=plan.plan_digest,
        proof=proof,
    )
    return service, plan, evaluated_at, proof


def test_dry_run_classifies_terminal_missing_usage_without_mutation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    spend_id = _reserve(connection, ingest_id="ingest-1", attempt=1)
    accounting = reconcile_graphiti_spend(
        connection,
        spend_id=spend_id,
        embedding_usage=None,
    )
    receipt = {
        "ingest_id": "ingest-1",
        "attempt_number": 1,
        "outcome": "FAILED",
        "failure_code": "EXECUTION_TIMEOUT",
        "provider_attempt_number": 1,
        "chat_invocations": [],
        "embedding_usage": None,
        "token_usage": None,
        "accounting": accounting,
        "receipt_digest": "",
    }
    receipt_digest = insert_graphiti_attempt_receipt(
        connection,
        ingest_id="ingest-1",
        attempt_number=1,
        outcome="FAILED",
        receipt=receipt,
    )
    connection.commit()
    connection.close()

    before = path.read_bytes()
    plan = plan_graphiti_spend_reconciliation(
        str(path),
        evaluated_at=datetime(2026, 8, 24, tzinfo=UTC),
    )

    assert path.read_bytes() == before
    assert plan.provider_calls == 0
    assert len(plan.transitions) == 1
    transition = plan.transitions[0]
    assert transition.spend_id == spend_id
    assert transition.ingest_id == "ingest-1"
    assert transition.attempt_number == 1
    assert transition.disposition is (
        GraphitiSpendDisposition.UNRECONCILED_REPORTED_MISSING
    )
    assert transition.attempt_receipt_digest == receipt_digest
    assert transition.provider_leaf_count == 0
    assert transition.actual_usd_microunits is None
    assert transition.actual_gbp_microunits is None
    assert transition.source_status == "UNRECONCILED"
    assert transition.target_status == "UNRECONCILED"
    assert transition.source_usage_basis == "UNREPORTED"
    assert transition.target_usage_basis == "UNREPORTED"
    assert transition.unused_reservation_released is False
    assert transition.evidence_basis == (
        "TERMINAL_ATTEMPT_WITHOUT_PROVIDER_NATIVE_USAGE"
    )
    assert transition.graph_journal_state == "UNOBSERVED"
    assert plan.plan_digest.startswith("sha256:")

    reopened = sqlite3.connect(path)
    assert (
        reopened.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='unpublished_graphiti_spend_dispositions'"
        ).fetchone()
        is None
    )
    retained = reopened.execute(
        "SELECT receipt_json FROM unpublished_graphiti_attempt_receipts"
    ).fetchone()
    reopened.close()
    assert retained is not None
    assert json.loads(retained[0])["receipt_digest"] == receipt_digest


def test_plan_keeps_retries_separate_and_holds_only_stale_ambiguous_effects(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))

    missing = _reserve(connection, ingest_id="retry", attempt=1)
    missing_accounting = reconcile_graphiti_spend(
        connection, spend_id=missing, embedding_usage=None
    )
    insert_graphiti_attempt_receipt(
        connection,
        ingest_id="retry",
        attempt_number=1,
        outcome="FAILED",
        receipt={
            "ingest_id": "retry",
            "attempt_number": 1,
            "outcome": "FAILED",
            "provider_attempt_number": 1,
            "chat_invocations": [{"invocation_id": "chat-1"}],
            "embedding_usage": None,
            "accounting": missing_accounting,
        },
    )

    reported = _reserve(connection, ingest_id="retry", attempt=2)
    reported_usage = _provider_usage()
    reported_accounting = reconcile_graphiti_spend(
        connection, spend_id=reported, embedding_usage=reported_usage
    )
    insert_graphiti_attempt_receipt(
        connection,
        ingest_id="retry",
        attempt_number=2,
        outcome="COMPLETE",
        receipt={
            "ingest_id": "retry",
            "attempt_number": 2,
            "outcome": "COMPLETE",
            "provider_attempt_number": 2,
            "chat_invocations": [{"invocation_id": "chat-2"}],
            "embedding_usage": reported_usage,
            "accounting": reported_accounting,
        },
    )

    pre_provider = _reserve(connection, ingest_id="pre-provider", attempt=1)
    insert_graphiti_attempt_receipt(
        connection,
        ingest_id="pre-provider",
        attempt_number=1,
        outcome="REFUSED",
        receipt={
            "ingest_id": "pre-provider",
            "attempt_number": 1,
            "outcome": "REFUSED",
            "provider_attempt_number": None,
            "chat_invocations": [],
            "embedding_usage": _no_embedding_usage(),
        },
    )
    ambiguous = _reserve(connection, ingest_id="ambiguous", attempt=1)
    assert claim_graphiti_attempt(
        connection,
        spend_id=ambiguous,
        generation_id=GRAPHITI_GENERATION_ID,
        owner_id="dead-process",
        claimed_at="2026-08-23T23:00:00.000000Z",
        lease_expires_at="2026-08-23T23:15:00.000000Z",
    )
    live = _reserve(connection, ingest_id="live", attempt=1)
    assert claim_graphiti_attempt(
        connection,
        spend_id=live,
        generation_id=GRAPHITI_GENERATION_ID,
        owner_id="live-process",
        claimed_at="2026-08-24T00:00:00.000000Z",
        lease_expires_at="2026-08-24T00:15:00.000000Z",
    )
    connection.commit()
    connection.close()

    plan = plan_graphiti_spend_reconciliation(
        str(path),
        evaluated_at=datetime(2026, 8, 24, 0, 5, tzinfo=UTC),
        graph_journal_evidence={
            pre_provider: _journal(
                pre_provider,
                ingest_id="pre-provider",
                attempt_number=1,
                state="ABSENT",
                provider_dispatch_state="NOT_DISPATCHED",
            ),
            ambiguous: _journal(
                ambiguous,
                ingest_id="ambiguous",
                attempt_number=1,
                state="PENDING",
                marker_attempt_number=1,
                provider_dispatch_state="UNKNOWN",
            ),
        },
    )

    by_spend = {transition.spend_id: transition for transition in plan.transitions}
    assert set(by_spend) == {missing, reported, pre_provider, ambiguous}
    assert by_spend[missing].disposition is (
        GraphitiSpendDisposition.UNRECONCILED_REPORTED_MISSING
    )
    assert by_spend[missing].provider_leaf_count == 1
    assert by_spend[reported].disposition is GraphitiSpendDisposition.RECONCILED
    assert by_spend[reported].actual_usd_microunits == 17
    assert by_spend[reported].actual_gbp_microunits == 17
    assert by_spend[pre_provider].disposition is (
        GraphitiSpendDisposition.RELEASED_BEFORE_PROVIDER_IO
    )
    assert by_spend[ambiguous].disposition is (
        GraphitiSpendDisposition.AMBIGUOUS_EFFECT_HOLD
    )
    assert plan.live_reservation_spend_ids == (live,)


def test_apply_is_authenticated_idempotent_and_emits_canonical_receipt(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    spend_id = _reserve(connection, ingest_id="ingest-1", attempt=1)
    accounting = reconcile_graphiti_spend(
        connection, spend_id=spend_id, embedding_usage=None
    )
    connection.execute(
        "UPDATE unpublished_graphiti_spend SET status='RECONCILED' WHERE spend_id=?",
        (spend_id,),
    )
    insert_graphiti_attempt_receipt(
        connection,
        ingest_id="ingest-1",
        attempt_number=1,
        outcome="TIMEOUT",
        receipt={
            "ingest_id": "ingest-1",
            "attempt_number": 1,
            "outcome": "TIMEOUT",
            "provider_attempt_number": 1,
            "chat_invocations": [],
            "embedding_usage": None,
            "accounting": accounting,
        },
    )
    connection.commit()
    connection.close()

    evaluated_at = datetime(2026, 8, 24, tzinfo=UTC)
    dry_run = plan_graphiti_spend_reconciliation(str(path), evaluated_at=evaluated_at)
    assert dry_run.transitions[0].disposition is (
        GraphitiSpendDisposition.UNRECONCILED_REPORTED_MISSING
    )
    assert dry_run.transitions[0].source_status == "RECONCILED"
    assert dry_run.transitions[0].target_status == "UNRECONCILED"
    service = _command_service()

    with pytest.raises(AuthenticationError, match="invalid authentication"):
        service.reconcile_graphiti_spend(
            unpublished_store=str(path),
            dry_run_plan=dry_run.as_dict(),
            evaluated_at=evaluated_at,
            idempotency_key="reconcile-1",
            expected_plan_digest=dry_run.plan_digest,
            proof=AuthenticationProof(method="STATIC_TOKEN", credential="wrong"),
        )

    with pytest.raises(PermissionError, match="requires the Hermes principal"):
        _command_service(principal_id="newsroom.other").reconcile_graphiti_spend(
            unpublished_store=str(path),
            dry_run_plan=dry_run.as_dict(),
            evaluated_at=evaluated_at,
            idempotency_key="wrong-principal",
            expected_plan_digest=dry_run.plan_digest,
            proof=AuthenticationProof(
                method="STATIC_TOKEN", credential="operator-token"
            ),
        )

    first = service.reconcile_graphiti_spend(
        unpublished_store=str(path),
        dry_run_plan=dry_run.as_dict(),
        evaluated_at=evaluated_at,
        idempotency_key="reconcile-1",
        expected_plan_digest=dry_run.plan_digest,
        proof=AuthenticationProof(method="STATIC_TOKEN", credential="operator-token"),
    )
    replay = service.reconcile_graphiti_spend(
        unpublished_store=str(path),
        dry_run_plan=dry_run.as_dict(),
        evaluated_at=evaluated_at,
        idempotency_key="reconcile-1",
        expected_plan_digest=dry_run.plan_digest,
        proof=AuthenticationProof(method="STATIC_TOKEN", credential="operator-token"),
    )
    with pytest.raises(GraphitiSpendReconciliationError, match="plan bytes differ"):
        service.reconcile_graphiti_spend(
            unpublished_store=str(path),
            dry_run_plan={},
            evaluated_at=evaluated_at,
            idempotency_key="reconcile-1",
            expected_plan_digest=dry_run.plan_digest,
            proof=AuthenticationProof(
                method="STATIC_TOKEN", credential="operator-token"
            ),
        )
    with pytest.raises(
        GraphitiSpendReconciliationError,
        match="idempotency key was reused for a different plan",
    ):
        service.reconcile_graphiti_spend(
            unpublished_store=str(path),
            dry_run_plan=dry_run.as_dict(),
            evaluated_at=evaluated_at,
            idempotency_key="reconcile-1",
            expected_plan_digest="sha256:" + ("0" * 64),
            proof=AuthenticationProof(
                method="STATIC_TOKEN", credential="operator-token"
            ),
        )

    assert replay.receipt_digest == first.receipt_digest
    assert first.plan_digest == dry_run.plan_digest
    assert first.provider_calls == 0
    assert first.applied_transition_count == 1
    assert first.terminal_attempt_count == 1
    assert first.terminal_spend_disposition_count == 1
    assert first.disposition_counts == {
        GraphitiSpendDisposition.UNRECONCILED_REPORTED_MISSING.value: 1
    }
    assert first.authenticated_principal == "newsroom.hermes"
    assert first.receipt_digest.startswith("sha256:")

    reopened = sqlite3.connect(path)
    disposition = reopened.execute(
        """
        SELECT disposition, attempt_receipt_digest, command_id, evidence_json
        FROM unpublished_graphiti_spend_dispositions WHERE spend_id=?
        """,
        (spend_id,),
    ).fetchone()
    command_count = reopened.execute(
        "SELECT COUNT(*) FROM unpublished_graphiti_spend_reconciliation_receipts"
    ).fetchone()[0]
    ledger_count = reopened.execute(
        "SELECT COUNT(*) FROM ledger WHERE kind='GRAPHITI_SPEND_RECONCILIATION_APPLIED'"
    ).fetchone()[0]
    reopened.close()

    assert disposition is not None
    assert disposition[:3] == (
        GraphitiSpendDisposition.UNRECONCILED_REPORTED_MISSING.value,
        dry_run.transitions[0].attempt_receipt_digest,
        "reconcile-1",
    )
    assert json.loads(disposition[3])["spend_id"] == spend_id
    assert command_count == 1
    assert ledger_count == 1


def test_plan_fails_closed_when_attempt_receipt_join_or_digest_is_tampered(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    spend_id = _reserve(connection, ingest_id="ingest-1", attempt=1)
    accounting = reconcile_graphiti_spend(
        connection, spend_id=spend_id, embedding_usage=None
    )
    insert_graphiti_attempt_receipt(
        connection,
        ingest_id="ingest-1",
        attempt_number=1,
        outcome="FAILED",
        receipt={
            "ingest_id": "ingest-1",
            "attempt_number": 1,
            "outcome": "FAILED",
            "provider_attempt_number": 1,
            "chat_invocations": [],
            "embedding_usage": None,
            "accounting": accounting,
        },
    )
    retained = json.loads(
        connection.execute(
            "SELECT receipt_json FROM unpublished_graphiti_attempt_receipts"
        ).fetchone()[0]
    )
    retained["attempt_number"] = 2
    connection.execute(
        "UPDATE unpublished_graphiti_attempt_receipts SET receipt_json=?",
        (json.dumps(retained, sort_keys=True),),
    )
    connection.commit()
    connection.close()

    with pytest.raises(
        GraphitiSpendReconciliationError,
        match="receipt (identity|digest)",
    ):
        plan_graphiti_spend_reconciliation(
            str(path), evaluated_at=datetime(2026, 8, 24, tzinfo=UTC)
        )


def test_attempt_coordinates_reject_boolean_aliases_and_unproven_retry_joins(
    tmp_path: Path,
) -> None:
    boolean_path = tmp_path / "boolean-unpublished.sqlite3"
    connection = connect(str(boolean_path))
    spend_id = _reserve(connection, ingest_id="boolean-attempt", attempt=1)
    accounting = reconcile_graphiti_spend(
        connection, spend_id=spend_id, embedding_usage=_provider_usage()
    )
    insert_graphiti_attempt_receipt(
        connection,
        ingest_id="boolean-attempt",
        attempt_number=1,
        outcome="COMPLETE",
        receipt={
            "ingest_id": "boolean-attempt",
            "attempt_number": 1,
            "outcome": "COMPLETE",
            "provider_attempt_number": 1,
            "chat_invocations": [],
            "embedding_usage": _provider_usage(),
            "accounting": accounting,
        },
    )
    retained = json.loads(
        connection.execute(
            "SELECT receipt_json FROM unpublished_graphiti_attempt_receipts"
        ).fetchone()[0]
    )
    retained["attempt_number"] = True
    retained["provider_attempt_number"] = True
    unsigned = dict(retained)
    unsigned.pop("receipt_digest")
    retained["receipt_digest"] = digest_bytes(canonical_json_bytes(unsigned))
    connection.execute(
        "UPDATE unpublished_graphiti_attempt_receipts "
        "SET receipt_json=?, receipt_digest=?",
        (
            canonical_json_bytes(retained).decode("utf-8"),
            retained["receipt_digest"],
        ),
    )
    connection.commit()
    connection.close()
    with pytest.raises(GraphitiSpendReconciliationError, match="receipt identity"):
        plan_graphiti_spend_reconciliation(
            str(boolean_path), evaluated_at=datetime(2026, 8, 24, tzinfo=UTC)
        )

    retry_path = tmp_path / "retry-unpublished.sqlite3"
    connection = connect(str(retry_path))
    for attempt in (1, 2):
        spend_id = _reserve(connection, ingest_id="unproven-retry", attempt=attempt)
        accounting = reconcile_graphiti_spend(
            connection, spend_id=spend_id, embedding_usage=None
        )
        insert_graphiti_attempt_receipt(
            connection,
            ingest_id="unproven-retry",
            attempt_number=attempt,
            outcome="FAILED" if attempt == 1 else "COMPLETE",
            receipt={
                "ingest_id": "unproven-retry",
                "attempt_number": attempt,
                "outcome": "FAILED" if attempt == 1 else "COMPLETE",
                "provider_attempt_number": 1,
                "chat_invocations": [],
                "embedding_usage": None if attempt == 1 else _provider_usage(),
                "accounting": accounting,
            },
        )
    connection.commit()
    connection.close()
    with pytest.raises(
        GraphitiSpendReconciliationError, match="provider attempt differs"
    ):
        plan_graphiti_spend_reconciliation(
            str(retry_path), evaluated_at=datetime(2026, 8, 24, tzinfo=UTC)
        )

    attributed_path = tmp_path / "attributed-retry-unpublished.sqlite3"
    connection = connect(str(attributed_path))
    for attempt in (1, 2):
        spend_id = _reserve(connection, ingest_id="attributed-retry", attempt=attempt)
        usage = None if attempt == 1 else _provider_usage()
        accounting = reconcile_graphiti_spend(
            connection, spend_id=spend_id, embedding_usage=usage
        )
        if attempt == 2:
            accounting["reported_provider_attempt_number"] = 1
            accounting["reconciled_to_current_attempt"] = True
        insert_graphiti_attempt_receipt(
            connection,
            ingest_id="attributed-retry",
            attempt_number=attempt,
            outcome="FAILED" if attempt == 1 else "COMPLETE",
            receipt={
                "ingest_id": "attributed-retry",
                "attempt_number": attempt,
                "outcome": "FAILED" if attempt == 1 else "COMPLETE",
                "provider_attempt_number": 1,
                "chat_invocations": [],
                "embedding_usage": usage,
                "accounting": accounting,
            },
        )
    connection.commit()
    connection.close()
    attributed = plan_graphiti_spend_reconciliation(
        str(attributed_path), evaluated_at=datetime(2026, 8, 24, tzinfo=UTC)
    )
    by_attempt = {item.attempt_number: item for item in attributed.transitions}
    assert by_attempt[1].disposition is (
        GraphitiSpendDisposition.UNRECONCILED_REPORTED_MISSING
    )
    assert by_attempt[2].disposition is GraphitiSpendDisposition.RECONCILED
    assert by_attempt[2].actual_usd_microunits == 17
    with sqlite3.connect(attributed_path) as reopened:
        retained = json.loads(
            reopened.execute(
                "SELECT receipt_json FROM unpublished_graphiti_attempt_receipts "
                "WHERE ingest_id=? AND attempt_number=2",
                ("attributed-retry",),
            ).fetchone()[0]
        )
        retained["accounting"]["reported_provider_attempt_number"] = True
        retained.pop("receipt_digest")
        retained_digest = digest_bytes(canonical_json_bytes(retained))
        retained["receipt_digest"] = retained_digest
        reopened.execute(
            "UPDATE unpublished_graphiti_attempt_receipts "
            "SET receipt_digest=?, receipt_json=? "
            "WHERE ingest_id=? AND attempt_number=2",
            (
                retained_digest,
                canonical_json_bytes(retained).decode("utf-8"),
                "attributed-retry",
            ),
        )
    with pytest.raises(
        GraphitiSpendReconciliationError, match="provider attempt differs"
    ):
        plan_graphiti_spend_reconciliation(
            str(attributed_path), evaluated_at=datetime(2026, 8, 24, tzinfo=UTC)
        )

    duplicate_path = tmp_path / "duplicate-attribution-unpublished.sqlite3"
    connection = connect(str(duplicate_path))
    for attempt in (1, 2):
        spend_id = _reserve(
            connection, ingest_id="duplicate-attribution", attempt=attempt
        )
        usage = _provider_usage()
        accounting = reconcile_graphiti_spend(
            connection, spend_id=spend_id, embedding_usage=usage
        )
        if attempt == 2:
            accounting["reported_provider_attempt_number"] = 1
            accounting["reconciled_to_current_attempt"] = True
        insert_graphiti_attempt_receipt(
            connection,
            ingest_id="duplicate-attribution",
            attempt_number=attempt,
            outcome="COMPLETE",
            receipt={
                "ingest_id": "duplicate-attribution",
                "attempt_number": attempt,
                "outcome": "COMPLETE",
                "provider_attempt_number": 1,
                "chat_invocations": [],
                "embedding_usage": usage,
                "accounting": accounting,
            },
        )
    connection.commit()
    connection.close()
    duplicate = plan_graphiti_spend_reconciliation(
        str(duplicate_path), evaluated_at=datetime(2026, 8, 24, tzinfo=UTC)
    )
    duplicate_by_attempt = {item.attempt_number: item for item in duplicate.transitions}
    assert duplicate_by_attempt[1].disposition is GraphitiSpendDisposition.RECONCILED
    assert duplicate_by_attempt[2].disposition is (
        GraphitiSpendDisposition.AMBIGUOUS_EFFECT_HOLD
    )
    assert duplicate_by_attempt[2].evidence_basis == (
        "DUPLICATE_CROSS_ATTEMPT_PROVIDER_ATTRIBUTION"
    )

    planned_duplicate_path = tmp_path / "planned-duplicate-unpublished.sqlite3"
    connection = connect(str(planned_duplicate_path))
    usage = _provider_usage()
    first = _reserve(connection, ingest_id="planned-duplicate", attempt=1)
    first_accounting = {
        "spend_id": first,
        "status": "RESERVED",
        "usage_basis": "PENDING_PROVIDER_REPORT",
    }
    insert_graphiti_attempt_receipt(
        connection,
        ingest_id="planned-duplicate",
        attempt_number=1,
        outcome="FAILED",
        receipt={
            "ingest_id": "planned-duplicate",
            "attempt_number": 1,
            "outcome": "FAILED",
            "provider_attempt_number": 1,
            "chat_invocations": [],
            "embedding_usage": usage,
            "token_usage": _token_usage(),
            "accounting": first_accounting,
        },
    )
    second = _reserve(connection, ingest_id="planned-duplicate", attempt=2)
    second_accounting = reconcile_graphiti_spend(
        connection, spend_id=second, embedding_usage=usage
    )
    second_accounting["reported_provider_attempt_number"] = 1
    second_accounting["reconciled_to_current_attempt"] = True
    retry_chat = [
        {
            "provider": "cursor-agent-cli",
            "model": "composer-2.5",
            "outcome": "COMPLETE",
            "usage": {
                "usage_basis": "PROVIDER_REPORTED",
                "input_tokens": 2,
                "output_tokens": 3,
                "cached_read_tokens": 0,
                "cached_write_tokens": 0,
                "reasoning_tokens": 0,
                "total_tokens": 5,
            },
        }
    ]
    insert_graphiti_attempt_receipt(
        connection,
        ingest_id="planned-duplicate",
        attempt_number=2,
        outcome="COMPLETE",
        receipt={
            "ingest_id": "planned-duplicate",
            "attempt_number": 2,
            "outcome": "COMPLETE",
            "provider_attempt_number": 1,
            "chat_invocations": retry_chat,
            "embedding_usage": usage,
            "token_usage": summarise_graphiti_usage(
                chat_invocations=retry_chat,
                embedding_usage=usage,
            ),
            "accounting": second_accounting,
        },
    )
    connection.commit()
    connection.close()

    planned_duplicate = plan_graphiti_spend_reconciliation(
        str(planned_duplicate_path),
        evaluated_at=datetime(2026, 8, 24, tzinfo=UTC),
    )
    planned_by_attempt = {
        item.attempt_number: item for item in planned_duplicate.transitions
    }
    assert planned_by_attempt[1].disposition is GraphitiSpendDisposition.RECONCILED
    assert planned_by_attempt[2].disposition is (
        GraphitiSpendDisposition.AMBIGUOUS_EFFECT_HOLD
    )
    assert (
        sum(item.actual_usd_microunits or 0 for item in planned_duplicate.transitions)
        == 17
    )
    evaluated_at = datetime(2026, 8, 24, tzinfo=UTC)
    _command_service().reconcile_graphiti_spend(
        unpublished_store=str(planned_duplicate_path),
        dry_run_plan=planned_duplicate.as_dict(),
        evaluated_at=evaluated_at,
        idempotency_key="planned-duplicate",
        expected_plan_digest=planned_duplicate.plan_digest,
        proof=AuthenticationProof(method="STATIC_TOKEN", credential="operator-token"),
    )
    duplicate_report = graphiti_usage_report(str(planned_duplicate_path))
    assert duplicate_report["embedding_request_count"] == 1
    assert duplicate_report["embedding_cost_usd_microunits"] == 17
    assert duplicate_report["chat_request_count"] == 1
    assert duplicate_report["cursor_request_count"] == 1
    assert duplicate_report["chat_total_tokens"] == 5
    assert duplicate_report["observed_total_tokens"] == 16
    assert duplicate_report["cost_complete"] is False


def test_recovered_provider_native_usage_is_retained_and_releases_reservation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    spend_id = _reserve(connection, ingest_id="recovered", attempt=1)
    assert claim_graphiti_attempt(
        connection,
        spend_id=spend_id,
        generation_id=GRAPHITI_GENERATION_ID,
        owner_id="dead-process",
        claimed_at="2026-08-23T23:00:00.000000Z",
        lease_expires_at="2026-08-23T23:15:00.000000Z",
    )
    usage = _provider_usage(23)
    insert_graphiti_attempt_receipt(
        connection,
        ingest_id="recovered",
        attempt_number=1,
        outcome="COMPLETE",
        receipt={
            "ingest_id": "recovered",
            "attempt_number": 1,
            "outcome": "COMPLETE",
            "provider_attempt_number": 1,
            "chat_invocations": [],
            "embedding_usage": usage,
        },
    )
    connection.commit()
    connection.close()
    journal = {
        spend_id: _journal(
            spend_id,
            ingest_id="recovered",
            attempt_number=1,
            state="COMPLETE",
            provider_dispatch_state="DISPATCHED",
            provider_usage=usage,
            marker_attempt_number=1,
        )
    }
    evaluated_at = datetime(2026, 8, 24, tzinfo=UTC)
    dry_run = plan_graphiti_spend_reconciliation(
        str(path),
        evaluated_at=evaluated_at,
        graph_journal_evidence=journal,
    )
    assert dry_run.transitions[0].disposition is GraphitiSpendDisposition.RECONCILED
    assert dry_run.transitions[0].actual_gbp_microunits == 23
    assert dry_run.transitions[0].fx_policy == "USD_GBP_CONSERVATIVE_PARITY_V1"
    assert dry_run.transitions[0].graph_journal_evidence["provider_usage"] == usage

    service = _command_service()
    service.reconcile_graphiti_spend(
        unpublished_store=str(path),
        dry_run_plan=dry_run.as_dict(),
        evaluated_at=evaluated_at,
        graph_journal_evidence=journal,
        idempotency_key="recover-provider-usage",
        expected_plan_digest=dry_run.plan_digest,
        proof=AuthenticationProof(method="STATIC_TOKEN", credential="operator-token"),
    )

    reopened = sqlite3.connect(path)
    spend = reopened.execute(
        """
        SELECT status, actual_usd_microunits, actual_gbp_microunits,
               provider_usage_json, dispatch_owner
        FROM unpublished_graphiti_spend WHERE spend_id=?
        """,
        (spend_id,),
    ).fetchone()
    evidence_json = reopened.execute(
        "SELECT evidence_json FROM unpublished_graphiti_spend_dispositions "
        "WHERE spend_id=?",
        (spend_id,),
    ).fetchone()[0]
    reopened.close()

    assert spend[:3] == ("RECONCILED", 23, 23)
    assert json.loads(spend[3]) == usage
    assert spend[4] is None
    retained_journal = dict(journal[spend_id])
    retained_journal.pop("evidence_digest")
    assert json.loads(evidence_json)["graph_journal_evidence"] == retained_journal


def test_usage_report_keeps_missing_cost_explicit_after_reconciliation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    spend_id = _reserve(connection, ingest_id="missing-cost", attempt=1)
    accounting = reconcile_graphiti_spend(
        connection, spend_id=spend_id, embedding_usage=None
    )
    insert_graphiti_attempt_receipt(
        connection,
        ingest_id="missing-cost",
        attempt_number=1,
        outcome="FAILED",
        receipt={
            "ingest_id": "missing-cost",
            "attempt_number": 1,
            "outcome": "FAILED",
            "provider_attempt_number": 1,
            "chat_invocations": [],
            "embedding_usage": None,
            "token_usage": None,
            "accounting": accounting,
        },
    )
    connection.commit()
    connection.close()
    evaluated_at = datetime(2026, 8, 24, tzinfo=UTC)
    dry_run = plan_graphiti_spend_reconciliation(str(path), evaluated_at=evaluated_at)
    service = _command_service()
    service.reconcile_graphiti_spend(
        unpublished_store=str(path),
        dry_run_plan=dry_run.as_dict(),
        evaluated_at=evaluated_at,
        idempotency_key="missing-cost",
        expected_plan_digest=dry_run.plan_digest,
        proof=AuthenticationProof(method="STATIC_TOKEN", credential="operator-token"),
    )

    report = graphiti_usage_report(str(path))

    reopened = sqlite3.connect(path)
    applied_state = reopened.execute(
        "SELECT status, usage_basis, actual_usd_microunits "
        "FROM unpublished_graphiti_spend WHERE spend_id=?",
        (spend_id,),
    ).fetchone()
    reopened.close()

    assert applied_state == ("UNRECONCILED", "UNREPORTED", None)
    assert report["cost_complete"] is False
    assert report["missing_usage_is_zero"] is False
    assert report["terminal_spend_disposition_count"] == 1
    assert report["spend_disposition_counts"] == {
        "RECONCILED": 0,
        "UNRECONCILED_REPORTED_MISSING": 1,
        "RELEASED_BEFORE_PROVIDER_IO": 0,
        "AMBIGUOUS_EFFECT_HOLD": 0,
    }
    assert report["unresolved_spend_attempt_count"] == 1
    assert report["unresolved_reserved_gbp_microunits"] == 500_000
    assert report["unexplained_reserved_spend_count"] == 0


def test_usage_report_is_incomplete_for_provider_spend_without_receipt_or_disposition(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    spend_id = _reserve(connection, ingest_id="unreported-provider-spend", attempt=1)
    reconcile_graphiti_spend(
        connection,
        spend_id=spend_id,
        embedding_usage=_provider_usage(),
    )
    connection.commit()
    connection.close()

    report = graphiti_usage_report(str(path))

    assert report["attempt_count"] == 0
    assert report["terminal_spend_disposition_count"] == 0
    assert report["embedding_cost_usd_microunits"] == 0
    assert report["undispositioned_spend_count"] == 1
    assert report["cost_complete"] is False


def test_late_terminal_attempt_requires_a_new_retained_disposition(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    first_spend = _reserve(connection, ingest_id="late-terminal", attempt=1)
    first_usage = _provider_usage()
    first_accounting = reconcile_graphiti_spend(
        connection, spend_id=first_spend, embedding_usage=first_usage
    )
    insert_graphiti_attempt_receipt(
        connection,
        ingest_id="late-terminal",
        attempt_number=1,
        outcome="COMPLETE",
        receipt={
            "ingest_id": "late-terminal",
            "attempt_number": 1,
            "outcome": "COMPLETE",
            "provider_attempt_number": 1,
            "chat_invocations": [],
            "embedding_usage": first_usage,
            "token_usage": _token_usage(),
            "accounting": first_accounting,
        },
    )
    connection.commit()
    connection.close()

    evaluated_at = datetime(2026, 8, 24, tzinfo=UTC)
    plan = plan_graphiti_spend_reconciliation(str(path), evaluated_at=evaluated_at)
    _command_service().reconcile_graphiti_spend(
        unpublished_store=str(path),
        dry_run_plan=plan.as_dict(),
        evaluated_at=evaluated_at,
        idempotency_key="late-terminal-first",
        expected_plan_digest=plan.plan_digest,
        proof=AuthenticationProof(method="STATIC_TOKEN", credential="operator-token"),
    )

    connection = connect(str(path))
    second_spend = _reserve(connection, ingest_id="late-terminal", attempt=2)
    second_usage = _provider_usage(23)
    second_accounting = reconcile_graphiti_spend(
        connection, spend_id=second_spend, embedding_usage=second_usage
    )
    insert_graphiti_attempt_receipt(
        connection,
        ingest_id="late-terminal",
        attempt_number=2,
        outcome="COMPLETE",
        receipt={
            "ingest_id": "late-terminal",
            "attempt_number": 2,
            "outcome": "COMPLETE",
            "provider_attempt_number": 2,
            "chat_invocations": [],
            "embedding_usage": second_usage,
            "token_usage": _token_usage(embedding_cost=23),
            "accounting": second_accounting,
        },
    )
    connection.commit()
    connection.close()

    report = graphiti_usage_report(str(path))
    assert report["attempt_count"] == 2
    assert report["terminal_spend_disposition_count"] == 1
    assert report["unreported_attempt_count"] == 0
    assert report["cost_complete"] is False


def test_usage_report_holds_one_read_snapshot_across_concurrent_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import newsroom.control_plane.usage as usage_module

    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    connection.commit()
    connection.close()
    evaluated_at = datetime(2026, 8, 24, tzinfo=UTC)
    service = _command_service()
    proof = AuthenticationProof(method="STATIC_TOKEN", credential="operator-token")
    empty_plan = plan_graphiti_spend_reconciliation(
        str(path), evaluated_at=evaluated_at
    )
    service.reconcile_graphiti_spend(
        unpublished_store=str(path),
        dry_run_plan=empty_plan.as_dict(),
        evaluated_at=evaluated_at,
        idempotency_key="snapshot-schema",
        expected_plan_digest=empty_plan.plan_digest,
        proof=proof,
    )

    connection = connect(str(path))
    spend_id = _reserve(connection, ingest_id="snapshot-race", attempt=1)
    provider_usage = _provider_usage()
    accounting = reconcile_graphiti_spend(
        connection, spend_id=spend_id, embedding_usage=provider_usage
    )
    insert_graphiti_attempt_receipt(
        connection,
        ingest_id="snapshot-race",
        attempt_number=1,
        outcome="COMPLETE",
        receipt={
            "ingest_id": "snapshot-race",
            "attempt_number": 1,
            "outcome": "COMPLETE",
            "provider_attempt_number": 1,
            "chat_invocations": [],
            "embedding_usage": provider_usage,
            "token_usage": _token_usage(),
            "accounting": accounting,
        },
    )
    connection.commit()
    connection.close()
    plan = plan_graphiti_spend_reconciliation(str(path), evaluated_at=evaluated_at)
    apply_arguments = {
        "unpublished_store": str(path),
        "dry_run_plan": plan.as_dict(),
        "evaluated_at": evaluated_at,
        "idempotency_key": "snapshot-race",
        "expected_plan_digest": plan.plan_digest,
        "proof": proof,
    }

    original_connect = sqlite3.connect
    applied = False

    class _BarrierConnection:
        def __init__(self, delegate: sqlite3.Connection) -> None:
            object.__setattr__(self, "_delegate", delegate)

        def __getattr__(self, name: str) -> object:
            return getattr(self._delegate, name)

        def __setattr__(self, name: str, value: object) -> None:
            setattr(self._delegate, name, value)

        def execute(
            self, sql: str, parameters: tuple[object, ...] = ()
        ) -> sqlite3.Cursor:
            nonlocal applied
            cursor = self._delegate.execute(sql, parameters)
            if "SELECT r.outcome, r.receipt_json" in sql and not applied:
                applied = True
                service.reconcile_graphiti_spend(**apply_arguments)
            return cursor

    monkeypatch.setattr(
        usage_module,
        "sqlite3",
        SimpleNamespace(
            connect=lambda target: _BarrierConnection(original_connect(target))
        ),
    )
    concurrent_report = graphiti_usage_report(str(path))
    stable_report = graphiti_usage_report(str(path))

    assert applied is True
    assert concurrent_report["terminal_spend_disposition_count"] == 0
    assert concurrent_report["embedding_cost_usd_microunits"] == 17
    assert concurrent_report["cost_complete"] is False
    assert stable_report["terminal_spend_disposition_count"] == 1
    assert stable_report["embedding_cost_usd_microunits"] == 17
    assert stable_report["cost_complete"] is True


def test_exact_shape_token_usage_must_match_provider_evidence(tmp_path: Path) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    spend_id = _reserve(connection, ingest_id="contradictory-token-usage", attempt=1)
    usage = _provider_usage()
    accounting = reconcile_graphiti_spend(
        connection, spend_id=spend_id, embedding_usage=usage
    )
    contradictory = _token_usage(embedding_cost=0)
    contradictory.update(
        embedding_request_count=0,
        embedding_tokens=0,
        observed_total_tokens=0,
    )
    insert_graphiti_attempt_receipt(
        connection,
        ingest_id="contradictory-token-usage",
        attempt_number=1,
        outcome="COMPLETE",
        receipt={
            "ingest_id": "contradictory-token-usage",
            "attempt_number": 1,
            "outcome": "COMPLETE",
            "provider_attempt_number": 1,
            "chat_invocations": [],
            "embedding_usage": usage,
            "token_usage": contradictory,
            "accounting": accounting,
        },
    )
    connection.commit()
    connection.close()

    evaluated_at = datetime(2026, 8, 24, tzinfo=UTC)
    plan = plan_graphiti_spend_reconciliation(str(path), evaluated_at=evaluated_at)
    _command_service().reconcile_graphiti_spend(
        unpublished_store=str(path),
        dry_run_plan=plan.as_dict(),
        evaluated_at=evaluated_at,
        idempotency_key="contradictory-token-usage",
        expected_plan_digest=plan.plan_digest,
        proof=AuthenticationProof(method="STATIC_TOKEN", credential="operator-token"),
    )

    report = graphiti_usage_report(str(path))
    assert report["unreported_attempt_count"] == 1
    assert report["measured_attempt_count"] == 0
    assert report["embedding_cost_usd_microunits"] == 0
    assert report["cost_complete"] is False


def test_future_evaluation_time_cannot_clear_an_active_dispatch_lease(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    spend_id = _reserve(connection, ingest_id="future-clock", attempt=1)
    assert claim_graphiti_attempt(
        connection,
        spend_id=spend_id,
        generation_id=GRAPHITI_GENERATION_ID,
        owner_id="active-owner",
        claimed_at="2026-08-24T03:00:00.000000Z",
        lease_expires_at="2099-01-01T00:00:00.000000Z",
    )
    connection.commit()
    connection.close()

    evaluated_at = datetime(2100, 1, 1, tzinfo=UTC)
    plan = plan_graphiti_spend_reconciliation(str(path), evaluated_at=evaluated_at)
    with pytest.raises(GraphitiSpendReconciliationError, match="active dispatch lease"):
        _command_service().reconcile_graphiti_spend(
            unpublished_store=str(path),
            dry_run_plan=plan.as_dict(),
            evaluated_at=evaluated_at,
            idempotency_key="future-clock",
            expected_plan_digest=plan.plan_digest,
            proof=AuthenticationProof(
                method="STATIC_TOKEN", credential="operator-token"
            ),
        )

    with sqlite3.connect(path) as reopened:
        retained = reopened.execute(
            "SELECT status, dispatch_owner, dispatch_lease_expires_at "
            "FROM unpublished_graphiti_spend WHERE spend_id=?",
            (spend_id,),
        ).fetchone()
    assert retained == (
        "RESERVED",
        "active-owner",
        "2099-01-01T00:00:00.000000Z",
    )


def test_live_reservation_snapshot_is_bound_and_must_still_be_live_at_apply(
    tmp_path: Path,
) -> None:
    drift_path = tmp_path / "live-drift-unpublished.sqlite3"
    connection = connect(str(drift_path))
    drift_spend = _reserve(connection, ingest_id="live-drift", attempt=1)
    assert claim_graphiti_attempt(
        connection,
        spend_id=drift_spend,
        generation_id=GRAPHITI_GENERATION_ID,
        owner_id="live-owner",
        claimed_at="2026-08-24T00:00:00.000000Z",
        lease_expires_at="2099-01-01T00:00:00.000000Z",
    )
    connection.commit()
    connection.close()
    evaluated_at = datetime(2026, 8, 24, tzinfo=UTC)
    plan = plan_graphiti_spend_reconciliation(
        str(drift_path), evaluated_at=evaluated_at
    )
    assert plan.transitions == ()
    assert plan.live_reservation_spend_ids == (drift_spend,)
    assert plan.live_reservations[0].dispatch_owner == "live-owner"
    assert plan.live_reservations[0].reserved_gbp_microunits == 500_000
    with sqlite3.connect(drift_path) as reopened:
        reopened.execute(
            "UPDATE unpublished_graphiti_spend "
            "SET reserved_gbp_microunits=reserved_gbp_microunits+1 "
            "WHERE spend_id=?",
            (drift_spend,),
        )
    with pytest.raises(GraphitiSpendReconciliationError, match="store changed"):
        _command_service().reconcile_graphiti_spend(
            unpublished_store=str(drift_path),
            dry_run_plan=plan.as_dict(),
            evaluated_at=evaluated_at,
            idempotency_key="live-drift",
            expected_plan_digest=plan.plan_digest,
            proof=AuthenticationProof(
                method="STATIC_TOKEN", credential="operator-token"
            ),
        )

    expired_path = tmp_path / "live-expired-unpublished.sqlite3"
    connection = connect(str(expired_path))
    expired_spend = _reserve(connection, ingest_id="live-expired", attempt=1)
    assert claim_graphiti_attempt(
        connection,
        spend_id=expired_spend,
        generation_id=GRAPHITI_GENERATION_ID,
        owner_id="expired-owner",
        claimed_at="1999-01-01T00:00:00.000000Z",
        lease_expires_at="2001-01-01T00:00:00.000000Z",
    )
    connection.commit()
    connection.close()
    old_evaluated_at = datetime(2000, 1, 1, tzinfo=UTC)
    expired_plan = plan_graphiti_spend_reconciliation(
        str(expired_path), evaluated_at=old_evaluated_at
    )
    assert expired_plan.live_reservation_spend_ids == (expired_spend,)
    with pytest.raises(
        GraphitiSpendReconciliationError,
        match="planned live dispatch lease is no longer active",
    ):
        _command_service().reconcile_graphiti_spend(
            unpublished_store=str(expired_path),
            dry_run_plan=expired_plan.as_dict(),
            evaluated_at=old_evaluated_at,
            idempotency_key="live-expired",
            expected_plan_digest=expired_plan.plan_digest,
            proof=AuthenticationProof(
                method="STATIC_TOKEN", credential="operator-token"
            ),
        )


def test_future_expiry_without_dispatch_owner_is_not_a_live_lease(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ownerless-lease-unpublished.sqlite3"
    connection = connect(str(path))
    spend_id = _reserve(connection, ingest_id="ownerless-lease", attempt=1)
    connection.execute(
        "UPDATE unpublished_graphiti_spend "
        "SET dispatch_lease_expires_at=? WHERE spend_id=?",
        ("2099-01-01T00:00:00.000000Z", spend_id),
    )
    connection.commit()
    connection.close()

    plan = plan_graphiti_spend_reconciliation(
        str(path), evaluated_at=datetime(2026, 8, 24, tzinfo=UTC)
    )
    report = graphiti_usage_report(str(path))

    assert plan.live_reservation_spend_ids == ()
    assert plan.transitions[0].disposition is (
        GraphitiSpendDisposition.AMBIGUOUS_EFFECT_HOLD
    )
    assert report["undispositioned_spend_count"] == 1
    assert report["unexplained_reserved_spend_count"] == 1
    assert report["cost_complete"] is False


@pytest.mark.parametrize(
    "usage",
    [_provider_usage(), _no_embedding_usage()],
    ids=["provider-reported", "no-embedding-call"],
)
def test_cost_closing_usage_without_durable_attempt_receipt_stays_incomplete(
    tmp_path: Path, usage: dict[str, object]
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    spend_id = _reserve(connection, ingest_id="receipt-missing", attempt=1)
    reconcile_graphiti_spend(connection, spend_id=spend_id, embedding_usage=usage)
    connection.commit()
    connection.close()

    evaluated_at = datetime(2026, 8, 24, tzinfo=UTC)
    plan = plan_graphiti_spend_reconciliation(str(path), evaluated_at=evaluated_at)
    assert plan.terminal_attempt_count == 0
    assert plan.planned_terminal_disposition_count == 0
    assert plan.transitions[0].disposition is (
        GraphitiSpendDisposition.AMBIGUOUS_EFFECT_HOLD
    )
    assert plan.transitions[0].evidence_basis == (
        "PROVIDER_USAGE_WITHOUT_DURABLE_ATTEMPT_RECEIPT"
    )
    _command_service().reconcile_graphiti_spend(
        unpublished_store=str(path),
        dry_run_plan=plan.as_dict(),
        evaluated_at=evaluated_at,
        idempotency_key="receipt-missing",
        expected_plan_digest=plan.plan_digest,
        proof=AuthenticationProof(method="STATIC_TOKEN", credential="operator-token"),
    )

    report = graphiti_usage_report(str(path))
    assert report["attempt_count"] == 0
    assert report["embedding_cost_usd_microunits"] == 0
    assert report["unresolved_spend_attempt_count"] == 1
    assert report["cost_complete"] is False
    assert report["missing_usage_is_zero"] is False


def test_self_digest_cannot_make_graph_journal_usage_authoritative(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    spend_id = _reserve(connection, ingest_id="untrusted-journal", attempt=1)
    connection.commit()
    connection.close()
    usage = _provider_usage(987_654)

    with pytest.raises(
        GraphitiSpendReconciliationError, match="not independently retained"
    ):
        plan_graphiti_spend_reconciliation(
            str(path),
            evaluated_at=datetime(2026, 8, 24, tzinfo=UTC),
            graph_journal_evidence={
                spend_id: _journal(
                    spend_id,
                    ingest_id="untrusted-journal",
                    attempt_number=1,
                    state="COMPLETE",
                    provider_dispatch_state="DISPATCHED",
                    provider_usage=usage,
                    marker_attempt_number=1,
                )
            },
        )
    with pytest.raises(
        GraphitiSpendReconciliationError, match="not exact provider-native usage"
    ):
        plan_graphiti_spend_reconciliation(
            str(path),
            evaluated_at=datetime(2026, 8, 24, tzinfo=UTC),
            graph_journal_evidence={
                spend_id: _journal(
                    spend_id,
                    ingest_id="untrusted-journal",
                    attempt_number=1,
                    state="COMPLETE",
                    provider_dispatch_state="DISPATCHED",
                    provider_usage="invented",
                    marker_attempt_number=1,
                )
            },
        )


def test_operator_dry_run_writes_provider_free_plan_receipt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    spend_id = _reserve(connection, ingest_id="stale", attempt=1)
    insert_graphiti_attempt_receipt(
        connection,
        ingest_id="stale",
        attempt_number=1,
        outcome="REFUSED",
        receipt={
            "ingest_id": "stale",
            "attempt_number": 1,
            "outcome": "REFUSED",
            "provider_attempt_number": None,
            "chat_invocations": [],
            "embedding_usage": _no_embedding_usage(),
        },
    )
    connection.commit()
    connection.close()
    journal_path = tmp_path / "journal.json"
    journal_path.write_text(
        json.dumps(
            {
                spend_id: _journal(
                    spend_id,
                    ingest_id="stale",
                    attempt_number=1,
                    state="ABSENT",
                    provider_dispatch_state="NOT_DISPATCHED",
                )
            }
        ),
        encoding="utf-8",
    )
    receipt_path = tmp_path / "plan.json"

    assert (
        reconciliation_main(
            [
                "dry-run",
                "--unpublished",
                str(path),
                "--evaluated-at",
                "2026-08-24T00:00:00Z",
                "--journal-evidence",
                str(journal_path),
                "--receipt",
                str(receipt_path),
            ]
        )
        == 0
    )

    stdout = json.loads(capsys.readouterr().out)
    retained = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert stdout == retained
    assert retained["provider_calls"] == 0
    assert retained["transitions"][0]["disposition"] == (
        GraphitiSpendDisposition.RELEASED_BEFORE_PROVIDER_IO.value
    )


def test_concurrent_reconcilers_converge_or_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    spend_id = _reserve(connection, ingest_id="concurrent", attempt=1)
    accounting = reconcile_graphiti_spend(
        connection, spend_id=spend_id, embedding_usage=None
    )
    insert_graphiti_attempt_receipt(
        connection,
        ingest_id="concurrent",
        attempt_number=1,
        outcome="FAILED",
        receipt={
            "ingest_id": "concurrent",
            "attempt_number": 1,
            "outcome": "FAILED",
            "provider_attempt_number": 1,
            "chat_invocations": [],
            "embedding_usage": None,
            "accounting": accounting,
        },
    )
    connection.commit()
    connection.close()
    evaluated_at = datetime(2026, 8, 24, tzinfo=UTC)
    plan = plan_graphiti_spend_reconciliation(str(path), evaluated_at=evaluated_at)
    service = _command_service()

    def apply(key: str) -> object:
        try:
            return service.reconcile_graphiti_spend(
                unpublished_store=str(path),
                dry_run_plan=plan.as_dict(),
                evaluated_at=evaluated_at,
                idempotency_key=key,
                expected_plan_digest=plan.plan_digest,
                proof=AuthenticationProof(
                    method="STATIC_TOKEN", credential="operator-token"
                ),
            )
        except GraphitiSpendReconciliationError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(apply, ("concurrent-a", "concurrent-b")))

    assert sum(not isinstance(item, Exception) for item in results) == 1
    failures = [item for item in results if isinstance(item, Exception)]
    assert len(failures) == 1
    assert "store changed" in str(failures[0])
    reopened = sqlite3.connect(path)
    assert (
        reopened.execute(
            "SELECT COUNT(*) FROM unpublished_graphiti_spend_dispositions"
        ).fetchone()[0]
        == 1
    )
    reopened.close()


def test_graph_journal_evidence_must_bind_the_exact_attempt(tmp_path: Path) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    spend_id = _reserve(connection, ingest_id="journal-bound", attempt=1)
    connection.commit()
    connection.close()

    with pytest.raises(
        GraphitiSpendReconciliationError,
        match="graph journal attempt",
    ):
        plan_graphiti_spend_reconciliation(
            str(path),
            evaluated_at=datetime(2026, 8, 24, tzinfo=UTC),
            graph_journal_evidence={
                spend_id: _journal(
                    spend_id,
                    ingest_id="journal-bound",
                    attempt_number=1,
                    state="PENDING",
                    marker_attempt_number=2,
                    provider_dispatch_state="UNKNOWN",
                )
            },
        )


def test_complete_marker_recovery_releases_retry_without_second_provider_call(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    provider_leaves = [
        {
            "provider": "grok-build-cli",
            "outcome": "FAILED",
            "usage": {
                "usage_basis": "PROVIDER_REPORTED",
                "input_tokens": 2,
                "output_tokens": 3,
                "cached_read_tokens": 0,
                "cached_write_tokens": 0,
                "reasoning_tokens": 0,
                "total_tokens": 5,
            },
        }
    ]
    prior_provider_usage = _provider_usage()
    for attempt in (1, 2):
        spend_id = _reserve(connection, ingest_id="recovered-retry", attempt=attempt)
        accounting = reconcile_graphiti_spend(
            connection,
            spend_id=spend_id,
            embedding_usage=_no_embedding_usage() if attempt == 2 else None,
        )
        if attempt == 2:
            accounting = {
                "provider_attempt": {
                    "spend_id": "recovered-retry:1",
                    "status": "UNRECONCILED",
                    "retained_attempt_receipt": True,
                    "reconciled_again": True,
                    "accounting": None,
                },
                "current_attempt": accounting,
                "recovery_classification": "RECOVERED_IMMUTABLE_COMPLETE",
            }
        insert_graphiti_attempt_receipt(
            connection,
            ingest_id="recovered-retry",
            attempt_number=attempt,
            outcome="FAILED",
            receipt={
                "ingest_id": "recovered-retry",
                "attempt_number": attempt,
                "outcome": "FAILED",
                "provider_attempt_number": 1,
                # Snapshot recovery restores the prior telemetry into the retry
                # receipt; it is not a second provider dispatch.
                "chat_invocations": provider_leaves,
                "embedding_usage": (None if attempt == 1 else prior_provider_usage),
                "token_usage": summarise_graphiti_usage(
                    chat_invocations=provider_leaves,
                    embedding_usage=prior_provider_usage,
                ),
                "accounting": accounting,
            },
        )
    connection.commit()
    connection.close()
    first, retry = "recovered-retry:1", "recovered-retry:2"
    with sqlite3.connect(path) as reopened:
        original_retry = json.loads(
            reopened.execute(
                "SELECT receipt_json FROM unpublished_graphiti_attempt_receipts "
                "WHERE ingest_id=? AND attempt_number=2",
                ("recovered-retry",),
            ).fetchone()[0]
        )
        false_zero_retry = json.loads(json.dumps(original_retry))
        false_zero_retry["accounting"]["current_attempt"]["actual_usd_microunits"] = (
            False
        )
        false_zero_retry.pop("receipt_digest")
        false_zero_digest = digest_bytes(canonical_json_bytes(false_zero_retry))
        false_zero_retry["receipt_digest"] = false_zero_digest
        reopened.execute(
            "UPDATE unpublished_graphiti_attempt_receipts "
            "SET receipt_digest=?, receipt_json=? "
            "WHERE ingest_id=? AND attempt_number=2",
            (
                false_zero_digest,
                canonical_json_bytes(false_zero_retry).decode("utf-8"),
                "recovered-retry",
            ),
        )
    with pytest.raises(
        GraphitiSpendReconciliationError, match="graph journal attempt differs"
    ):
        plan_graphiti_spend_reconciliation(
            str(path),
            evaluated_at=datetime(2026, 8, 24, tzinfo=UTC),
            graph_journal_evidence={
                first: _journal(
                    first,
                    ingest_id="recovered-retry",
                    attempt_number=1,
                    state="COMPLETE",
                    marker_attempt_number=1,
                    provider_attempt_number=1,
                    provider_dispatch_state="DISPATCHED",
                    provider_leaves=provider_leaves,
                ),
                retry: _journal(
                    retry,
                    ingest_id="recovered-retry",
                    attempt_number=2,
                    state="COMPLETE",
                    marker_attempt_number=1,
                    provider_attempt_number=1,
                    reconciliation_attempt_number=2,
                    recovery_classification="RECOVERED_IMMUTABLE_COMPLETE",
                    provider_dispatch_state="NOT_DISPATCHED",
                    provider_leaves=provider_leaves,
                    provider_usage=prior_provider_usage,
                ),
            },
        )
    with sqlite3.connect(path) as reopened:
        reopened.execute(
            "UPDATE unpublished_graphiti_attempt_receipts "
            "SET receipt_digest=?, receipt_json=? "
            "WHERE ingest_id=? AND attempt_number=2",
            (
                original_retry["receipt_digest"],
                canonical_json_bytes(original_retry).decode("utf-8"),
                "recovered-retry",
            ),
        )
    aliased_provider_leaves = json.loads(json.dumps(provider_leaves))
    aliased_provider_leaves[0]["usage"]["cached_read_tokens"] = False
    with pytest.raises(
        GraphitiSpendReconciliationError, match="recovered provider leaves differ"
    ):
        plan_graphiti_spend_reconciliation(
            str(path),
            evaluated_at=datetime(2026, 8, 24, tzinfo=UTC),
            graph_journal_evidence={
                first: _journal(
                    first,
                    ingest_id="recovered-retry",
                    attempt_number=1,
                    state="COMPLETE",
                    marker_attempt_number=1,
                    provider_attempt_number=1,
                    provider_dispatch_state="DISPATCHED",
                    provider_leaves=provider_leaves,
                ),
                retry: _journal(
                    retry,
                    ingest_id="recovered-retry",
                    attempt_number=2,
                    state="COMPLETE",
                    marker_attempt_number=1,
                    provider_attempt_number=1,
                    reconciliation_attempt_number=2,
                    recovery_classification="RECOVERED_IMMUTABLE_COMPLETE",
                    provider_dispatch_state="NOT_DISPATCHED",
                    provider_leaves=aliased_provider_leaves,
                    provider_usage=prior_provider_usage,
                ),
            },
        )
    with pytest.raises(
        GraphitiSpendReconciliationError, match="recovered provider leaves differ"
    ):
        plan_graphiti_spend_reconciliation(
            str(path),
            evaluated_at=datetime(2026, 8, 24, tzinfo=UTC),
            graph_journal_evidence={
                first: _journal(
                    first,
                    ingest_id="recovered-retry",
                    attempt_number=1,
                    state="COMPLETE",
                    marker_attempt_number=1,
                    provider_attempt_number=1,
                    provider_dispatch_state="DISPATCHED",
                    provider_leaves=provider_leaves,
                ),
                retry: _journal(
                    retry,
                    ingest_id="recovered-retry",
                    attempt_number=2,
                    state="COMPLETE",
                    marker_attempt_number=1,
                    provider_attempt_number=1,
                    reconciliation_attempt_number=2,
                    recovery_classification="RECOVERED_IMMUTABLE_COMPLETE",
                    provider_dispatch_state="NOT_DISPATCHED",
                    provider_usage=prior_provider_usage,
                ),
            },
        )
    with pytest.raises(
        GraphitiSpendReconciliationError, match="recovered provider usage"
    ):
        plan_graphiti_spend_reconciliation(
            str(path),
            evaluated_at=datetime(2026, 8, 24, tzinfo=UTC),
            graph_journal_evidence={
                first: _journal(
                    first,
                    ingest_id="recovered-retry",
                    attempt_number=1,
                    state="COMPLETE",
                    marker_attempt_number=1,
                    provider_attempt_number=1,
                    provider_dispatch_state="DISPATCHED",
                    provider_leaves=provider_leaves,
                ),
                retry: _journal(
                    retry,
                    ingest_id="recovered-retry",
                    attempt_number=2,
                    state="COMPLETE",
                    marker_attempt_number=1,
                    provider_attempt_number=1,
                    reconciliation_attempt_number=2,
                    recovery_classification="RECOVERED_IMMUTABLE_COMPLETE",
                    provider_dispatch_state="NOT_DISPATCHED",
                    provider_leaves=provider_leaves,
                ),
            },
        )
    with sqlite3.connect(path) as reopened:
        original_retry = json.loads(
            reopened.execute(
                "SELECT receipt_json FROM unpublished_graphiti_attempt_receipts "
                "WHERE ingest_id=? AND attempt_number=2",
                ("recovered-retry",),
            ).fetchone()[0]
        )
        conflicting_retry = json.loads(json.dumps(original_retry))
        # Python treats False and 0 as equal; canonical JSON evidence does not.
        conflicting_retry["chat_invocations"][0]["usage"]["cached_read_tokens"] = False
        conflicting_retry["token_usage"] = summarise_graphiti_usage(
            chat_invocations=conflicting_retry["chat_invocations"],
            embedding_usage=prior_provider_usage,
        )
        conflicting_retry.pop("receipt_digest")
        conflicting_digest = digest_bytes(canonical_json_bytes(conflicting_retry))
        conflicting_retry["receipt_digest"] = conflicting_digest
        reopened.execute(
            "UPDATE unpublished_graphiti_attempt_receipts "
            "SET receipt_digest=?, receipt_json=? "
            "WHERE ingest_id=? AND attempt_number=2",
            (
                conflicting_digest,
                json.dumps(conflicting_retry, ensure_ascii=False, sort_keys=True),
                "recovered-retry",
            ),
        )

    with pytest.raises(
        GraphitiSpendReconciliationError,
        match="recovered current receipt leaves differ",
    ):
        plan_graphiti_spend_reconciliation(
            str(path),
            evaluated_at=datetime(2026, 8, 24, tzinfo=UTC),
            graph_journal_evidence={
                first: _journal(
                    first,
                    ingest_id="recovered-retry",
                    attempt_number=1,
                    state="COMPLETE",
                    marker_attempt_number=1,
                    provider_attempt_number=1,
                    provider_dispatch_state="DISPATCHED",
                    provider_leaves=provider_leaves,
                ),
                retry: _journal(
                    retry,
                    ingest_id="recovered-retry",
                    attempt_number=2,
                    state="COMPLETE",
                    marker_attempt_number=1,
                    provider_attempt_number=1,
                    reconciliation_attempt_number=2,
                    recovery_classification="RECOVERED_IMMUTABLE_COMPLETE",
                    provider_dispatch_state="NOT_DISPATCHED",
                    provider_leaves=provider_leaves,
                    provider_usage=prior_provider_usage,
                ),
            },
        )

    with sqlite3.connect(path) as reopened:
        reopened.execute(
            "UPDATE unpublished_graphiti_attempt_receipts "
            "SET receipt_digest=?, receipt_json=? "
            "WHERE ingest_id=? AND attempt_number=2",
            (
                original_retry["receipt_digest"],
                json.dumps(original_retry, ensure_ascii=False, sort_keys=True),
                "recovered-retry",
            ),
        )
    plan = plan_graphiti_spend_reconciliation(
        str(path),
        evaluated_at=datetime(2026, 8, 24, tzinfo=UTC),
        graph_journal_evidence={
            first: _journal(
                first,
                ingest_id="recovered-retry",
                attempt_number=1,
                state="COMPLETE",
                marker_attempt_number=1,
                provider_attempt_number=1,
                provider_dispatch_state="DISPATCHED",
                provider_leaves=provider_leaves,
            ),
            retry: _journal(
                retry,
                ingest_id="recovered-retry",
                attempt_number=2,
                state="COMPLETE",
                marker_attempt_number=1,
                provider_attempt_number=1,
                reconciliation_attempt_number=2,
                recovery_classification="RECOVERED_IMMUTABLE_COMPLETE",
                provider_dispatch_state="NOT_DISPATCHED",
                provider_leaves=provider_leaves,
                provider_usage=prior_provider_usage,
            ),
        },
    )

    by_spend = {item.spend_id: item for item in plan.transitions}
    assert by_spend[first].disposition is GraphitiSpendDisposition.RECONCILED
    assert by_spend[first].actual_usd_microunits == 17
    assert by_spend[first].provider_usage == prior_provider_usage
    assert by_spend[first].provider_leaf_count == 1
    assert by_spend[retry].disposition is (
        GraphitiSpendDisposition.RELEASED_BEFORE_PROVIDER_IO
    )
    assert by_spend[retry].evidence_basis == (
        "RECOVERED_COMPLETE_WITHOUT_SECOND_PROVIDER_DISPATCH"
    )
    assert by_spend[retry].provider_usage == _no_embedding_usage()
    assert plan.provider_calls == 0

    _command_service().reconcile_graphiti_spend(
        unpublished_store=str(path),
        dry_run_plan=plan.as_dict(),
        evaluated_at=datetime(2026, 8, 24, tzinfo=UTC),
        graph_journal_evidence={
            first: _journal(
                first,
                ingest_id="recovered-retry",
                attempt_number=1,
                state="COMPLETE",
                marker_attempt_number=1,
                provider_attempt_number=1,
                provider_dispatch_state="DISPATCHED",
                provider_leaves=provider_leaves,
            ),
            retry: _journal(
                retry,
                ingest_id="recovered-retry",
                attempt_number=2,
                state="COMPLETE",
                marker_attempt_number=1,
                provider_attempt_number=1,
                reconciliation_attempt_number=2,
                recovery_classification="RECOVERED_IMMUTABLE_COMPLETE",
                provider_dispatch_state="NOT_DISPATCHED",
                provider_leaves=provider_leaves,
                provider_usage=prior_provider_usage,
            ),
        },
        idempotency_key="recovered-retry",
        expected_plan_digest=plan.plan_digest,
        proof=AuthenticationProof(method="STATIC_TOKEN", credential="operator-token"),
    )
    with sqlite3.connect(path) as reopened:
        states = reopened.execute(
            "SELECT spend_id, actual_usd_microunits, usage_basis, provider_usage_json "
            "FROM unpublished_graphiti_spend ORDER BY attempt_number"
        ).fetchall()
    assert states[0][:3] == (first, 17, "PROVIDER_REPORTED")
    assert json.loads(states[0][3]) == prior_provider_usage
    assert states[1][:3] == (retry, 0, "NO_EMBEDDING_CALL")
    assert json.loads(states[1][3]) == _no_embedding_usage()
    report = graphiti_usage_report(str(path))
    assert report["embedding_request_count"] == 1
    assert report["embedding_cost_usd_microunits"] == 17
    assert report["chat_request_count"] == 1
    assert report["grok_request_count"] == 1
    assert report["chat_total_tokens"] == 5
    assert report["observed_total_tokens"] == 16
    assert report["cost_complete"] is True


def test_later_recovery_can_join_a_previously_dispositioned_provider_attempt(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    usage = _provider_usage()
    connection = connect(str(path))
    first = _reserve(connection, ingest_id="sequential-recovery", attempt=1)
    first_accounting = reconcile_graphiti_spend(
        connection, spend_id=first, embedding_usage=usage
    )
    insert_graphiti_attempt_receipt(
        connection,
        ingest_id="sequential-recovery",
        attempt_number=1,
        outcome="COMPLETE",
        receipt={
            "ingest_id": "sequential-recovery",
            "attempt_number": 1,
            "outcome": "COMPLETE",
            "provider_attempt_number": 1,
            "chat_invocations": [],
            "embedding_usage": usage,
            "token_usage": _token_usage(),
            "accounting": first_accounting,
        },
    )
    connection.commit()
    connection.close()

    evaluated_at = datetime(2026, 8, 24, tzinfo=UTC)
    first_plan = plan_graphiti_spend_reconciliation(
        str(path), evaluated_at=evaluated_at
    )
    _command_service().reconcile_graphiti_spend(
        unpublished_store=str(path),
        dry_run_plan=first_plan.as_dict(),
        evaluated_at=evaluated_at,
        idempotency_key="sequential-recovery-first",
        expected_plan_digest=first_plan.plan_digest,
        proof=AuthenticationProof(method="STATIC_TOKEN", credential="operator-token"),
    )

    connection = connect(str(path))
    retry = _reserve(connection, ingest_id="sequential-recovery", attempt=2)
    current_accounting = reconcile_graphiti_spend(
        connection, spend_id=retry, embedding_usage=_no_embedding_usage()
    )
    recovery_accounting = {
        "provider_attempt": {
            "spend_id": first,
            "status": "RECONCILED",
            "retained_attempt_receipt": True,
            "reconciled_again": False,
            "accounting": None,
        },
        "current_attempt": current_accounting,
        "recovery_classification": "RECOVERED_IMMUTABLE_COMPLETE",
    }
    insert_graphiti_attempt_receipt(
        connection,
        ingest_id="sequential-recovery",
        attempt_number=2,
        outcome="FAILED",
        receipt={
            "ingest_id": "sequential-recovery",
            "attempt_number": 2,
            "outcome": "FAILED",
            "provider_attempt_number": 1,
            "chat_invocations": [],
            "embedding_usage": usage,
            "token_usage": _token_usage(),
            "accounting": recovery_accounting,
        },
    )
    connection.commit()
    connection.close()
    journal = {
        retry: _journal(
            retry,
            ingest_id="sequential-recovery",
            attempt_number=2,
            state="COMPLETE",
            marker_attempt_number=1,
            provider_attempt_number=1,
            reconciliation_attempt_number=2,
            recovery_classification="RECOVERED_IMMUTABLE_COMPLETE",
            provider_dispatch_state="NOT_DISPATCHED",
            provider_leaves=[],
            provider_usage=usage,
        )
    }

    retry_plan = plan_graphiti_spend_reconciliation(
        str(path),
        evaluated_at=evaluated_at,
        graph_journal_evidence=journal,
    )
    assert [item.spend_id for item in retry_plan.transitions] == [retry]
    assert retry_plan.transitions[0].disposition is (
        GraphitiSpendDisposition.RELEASED_BEFORE_PROVIDER_IO
    )
    assert retry_plan.terminal_attempt_count == 2
    assert retry_plan.planned_terminal_disposition_count == 2

    conflicting_usage = _provider_usage(23)
    with sqlite3.connect(path) as connection:
        retained_receipt = json.loads(
            connection.execute(
                "SELECT receipt_json FROM unpublished_graphiti_attempt_receipts "
                "WHERE ingest_id=? AND attempt_number=2",
                ("sequential-recovery",),
            ).fetchone()[0]
        )
        retained_receipt["embedding_usage"] = conflicting_usage
        retained_receipt["token_usage"] = _token_usage(embedding_cost=23)
        retained_receipt.pop("receipt_digest")
        receipt_digest = digest_bytes(canonical_json_bytes(retained_receipt))
        retained_receipt["receipt_digest"] = receipt_digest
        connection.execute(
            "UPDATE unpublished_graphiti_attempt_receipts "
            "SET receipt_digest=?, receipt_json=? "
            "WHERE ingest_id=? AND attempt_number=2",
            (
                receipt_digest,
                canonical_json_bytes(retained_receipt).decode("utf-8"),
                "sequential-recovery",
            ),
        )
    conflicting_journal = {
        retry: _journal(
            retry,
            ingest_id="sequential-recovery",
            attempt_number=2,
            state="COMPLETE",
            marker_attempt_number=1,
            provider_attempt_number=1,
            reconciliation_attempt_number=2,
            recovery_classification="RECOVERED_IMMUTABLE_COMPLETE",
            provider_dispatch_state="NOT_DISPATCHED",
            provider_leaves=[],
            provider_usage=conflicting_usage,
        )
    }
    with pytest.raises(
        GraphitiSpendReconciliationError, match="retained provider attempt"
    ):
        plan_graphiti_spend_reconciliation(
            str(path),
            evaluated_at=evaluated_at,
            graph_journal_evidence=conflicting_journal,
        )


def test_claimed_absent_assertion_without_terminal_receipt_stays_ambiguous(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    spend_id = _reserve(connection, ingest_id="unproven-release", attempt=1)
    connection.commit()
    connection.close()

    plan = plan_graphiti_spend_reconciliation(
        str(path),
        evaluated_at=datetime(2026, 8, 24, tzinfo=UTC),
        graph_journal_evidence={
            spend_id: _journal(
                spend_id,
                ingest_id="unproven-release",
                attempt_number=1,
                state="ABSENT",
                provider_dispatch_state="NOT_DISPATCHED",
            )
        },
    )

    transition = plan.transitions[0]
    assert transition.disposition is GraphitiSpendDisposition.AMBIGUOUS_EFFECT_HOLD
    assert transition.actual_usd_microunits is None
    assert transition.target_status == "UNRECONCILED"
    assert transition.target_usage_basis == "AMBIGUOUS_EFFECT_HOLD"


def test_graph_journal_provider_leaves_must_match_terminal_receipt(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    spend_id = _reserve(connection, ingest_id="leaf-join", attempt=1)
    accounting = reconcile_graphiti_spend(
        connection, spend_id=spend_id, embedding_usage=None
    )
    insert_graphiti_attempt_receipt(
        connection,
        ingest_id="leaf-join",
        attempt_number=1,
        outcome="FAILED",
        receipt={
            "ingest_id": "leaf-join",
            "attempt_number": 1,
            "outcome": "FAILED",
            "provider_attempt_number": 1,
            "chat_invocations": [
                {"invocation_id": "retained", "cached_read_tokens": 0}
            ],
            "embedding_usage": None,
            "accounting": accounting,
        },
    )
    connection.commit()
    connection.close()

    with pytest.raises(GraphitiSpendReconciliationError, match="provider leaves"):
        plan_graphiti_spend_reconciliation(
            str(path),
            evaluated_at=datetime(2026, 8, 24, tzinfo=UTC),
            graph_journal_evidence={
                spend_id: _journal(
                    spend_id,
                    ingest_id="leaf-join",
                    attempt_number=1,
                    state="COMPLETE",
                    marker_attempt_number=1,
                    provider_attempt_number=1,
                    provider_dispatch_state="DISPATCHED",
                    provider_leaves=[
                        {"invocation_id": "retained", "cached_read_tokens": False}
                    ],
                )
            },
        )


def test_graph_journal_provider_usage_must_match_retained_usage(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    spend_id = _reserve(connection, ingest_id="usage-join", attempt=1)
    retained_usage = _provider_usage(17)
    accounting = reconcile_graphiti_spend(
        connection, spend_id=spend_id, embedding_usage=retained_usage
    )
    insert_graphiti_attempt_receipt(
        connection,
        ingest_id="usage-join",
        attempt_number=1,
        outcome="COMPLETE",
        receipt={
            "ingest_id": "usage-join",
            "attempt_number": 1,
            "outcome": "COMPLETE",
            "provider_attempt_number": 1,
            "chat_invocations": [],
            "embedding_usage": retained_usage,
            "accounting": accounting,
        },
    )
    connection.commit()
    connection.close()

    with pytest.raises(GraphitiSpendReconciliationError, match="provider usage"):
        plan_graphiti_spend_reconciliation(
            str(path),
            evaluated_at=datetime(2026, 8, 24, tzinfo=UTC),
            graph_journal_evidence={
                spend_id: _journal(
                    spend_id,
                    ingest_id="usage-join",
                    attempt_number=1,
                    state="COMPLETE",
                    marker_attempt_number=1,
                    provider_attempt_number=1,
                    provider_dispatch_state="DISPATCHED",
                    provider_leaves=[],
                    provider_usage=_provider_usage(23),
                )
            },
        )


def test_retained_spend_usage_must_match_receipt_without_journal(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    spend_id = _reserve(connection, ingest_id="direct-usage-join", attempt=1)
    retained_usage = _provider_usage(17)
    accounting = reconcile_graphiti_spend(
        connection, spend_id=spend_id, embedding_usage=retained_usage
    )
    insert_graphiti_attempt_receipt(
        connection,
        ingest_id="direct-usage-join",
        attempt_number=1,
        outcome="COMPLETE",
        receipt={
            "ingest_id": "direct-usage-join",
            "attempt_number": 1,
            "outcome": "COMPLETE",
            "provider_attempt_number": 1,
            "chat_invocations": [],
            "embedding_usage": _provider_usage(23),
            "accounting": accounting,
        },
    )
    connection.commit()
    connection.close()

    with pytest.raises(GraphitiSpendReconciliationError, match="provider usage"):
        plan_graphiti_spend_reconciliation(
            str(path), evaluated_at=datetime(2026, 8, 24, tzinfo=UTC)
        )


def test_apply_refuses_a_production_named_store_before_opening_it(
    tmp_path: Path,
) -> None:
    service = _command_service()

    with pytest.raises(VetoError, match="store must not alias production"):
        service.reconcile_graphiti_spend(
            unpublished_store=str(tmp_path / "production.sqlite3"),
            dry_run_plan={},
            evaluated_at=datetime(2026, 8, 24, tzinfo=UTC),
            idempotency_key="production-refused",
            expected_plan_digest="sha256:" + ("0" * 64),
            proof=AuthenticationProof(
                method="STATIC_TOKEN", credential="operator-token"
            ),
        )


def test_unreconciled_provider_reported_attempt_recovers_actual_cost(
    tmp_path: Path,
) -> None:
    path = tmp_path / "store.sqlite3"
    connection = connect(str(path))
    spend_id = _reserve(connection, ingest_id="reported-after-gap", attempt=1)
    usage = _provider_usage(23)
    accounting = reconcile_graphiti_spend(
        connection, spend_id=spend_id, embedding_usage=usage
    )
    connection.execute(
        "UPDATE unpublished_graphiti_spend "
        "SET status='UNRECONCILED', actual_usd_microunits=NULL, "
        "actual_gbp_microunits=NULL WHERE spend_id=?",
        (spend_id,),
    )
    insert_graphiti_attempt_receipt(
        connection,
        ingest_id="reported-after-gap",
        attempt_number=1,
        outcome="COMPLETE",
        receipt={
            "ingest_id": "reported-after-gap",
            "attempt_number": 1,
            "outcome": "COMPLETE",
            "provider_attempt_number": 1,
            "chat_invocations": [],
            "embedding_usage": usage,
            "accounting": accounting,
        },
    )
    connection.commit()
    connection.close()

    transition = plan_graphiti_spend_reconciliation(
        str(path), evaluated_at=datetime(2026, 8, 24, tzinfo=UTC)
    ).transitions[0]

    assert transition.disposition is GraphitiSpendDisposition.RECONCILED
    assert transition.actual_usd_microunits == 23
    assert transition.actual_gbp_microunits == 23
    assert transition.target_usage_basis == "PROVIDER_REPORTED"
    assert transition.unused_reservation_released is True


def test_pre_provider_journal_conflicts_with_dispatched_attempt(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    spend_id = _reserve(connection, ingest_id="dispatch-conflict", attempt=1)
    accounting = reconcile_graphiti_spend(
        connection, spend_id=spend_id, embedding_usage=None
    )
    insert_graphiti_attempt_receipt(
        connection,
        ingest_id="dispatch-conflict",
        attempt_number=1,
        outcome="FAILED",
        receipt={
            "ingest_id": "dispatch-conflict",
            "attempt_number": 1,
            "outcome": "FAILED",
            "provider_attempt_number": 1,
            "chat_invocations": [],
            "embedding_usage": None,
            "accounting": accounting,
        },
    )
    connection.commit()
    connection.close()

    with pytest.raises(GraphitiSpendReconciliationError, match="dispatch differs"):
        plan_graphiti_spend_reconciliation(
            str(path),
            evaluated_at=datetime(2026, 8, 24, tzinfo=UTC),
            graph_journal_evidence={
                spend_id: _journal(
                    spend_id,
                    ingest_id="dispatch-conflict",
                    attempt_number=1,
                    state="ABSENT",
                    provider_dispatch_state="NOT_DISPATCHED",
                )
            },
        )


def test_journal_evidence_requires_digest_and_exact_spend_join(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    spend_id = _reserve(connection, ingest_id="journal-integrity", attempt=1)
    connection.commit()
    connection.close()
    evidence = _journal(
        spend_id,
        ingest_id="journal-integrity",
        attempt_number=1,
        state="PENDING",
        marker_attempt_number=1,
        provider_dispatch_state="UNKNOWN",
    )
    evidence.pop("evidence_digest")

    with pytest.raises(GraphitiSpendReconciliationError, match="evidence digest"):
        plan_graphiti_spend_reconciliation(
            str(path),
            evaluated_at=datetime(2026, 8, 24, tzinfo=UTC),
            graph_journal_evidence={spend_id: evidence},
        )

    unknown = "unknown-spend:1"
    with pytest.raises(GraphitiSpendReconciliationError, match="does not join"):
        plan_graphiti_spend_reconciliation(
            str(path),
            evaluated_at=datetime(2026, 8, 24, tzinfo=UTC),
            graph_journal_evidence={
                unknown: _journal(
                    unknown,
                    ingest_id="unknown-spend",
                    attempt_number=1,
                    state="PENDING",
                    marker_attempt_number=1,
                    provider_dispatch_state="UNKNOWN",
                )
            },
        )


def test_apply_compares_canonical_plan_bytes_not_python_scalar_equality(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    spend_id = _reserve(connection, ingest_id="canonical-plan", attempt=1)
    accounting = reconcile_graphiti_spend(
        connection, spend_id=spend_id, embedding_usage=None
    )
    insert_graphiti_attempt_receipt(
        connection,
        ingest_id="canonical-plan",
        attempt_number=1,
        outcome="FAILED",
        receipt={
            "ingest_id": "canonical-plan",
            "attempt_number": 1,
            "outcome": "FAILED",
            "provider_attempt_number": 1,
            "chat_invocations": [],
            "embedding_usage": None,
            "accounting": accounting,
        },
    )
    connection.commit()
    connection.close()
    evaluated_at = datetime(2026, 8, 24, tzinfo=UTC)
    plan = plan_graphiti_spend_reconciliation(str(path), evaluated_at=evaluated_at)
    tampered = plan.as_dict()
    tampered["provider_calls"] = False

    with pytest.raises(GraphitiSpendReconciliationError, match="plan bytes differ"):
        _command_service().reconcile_graphiti_spend(
            unpublished_store=str(path),
            dry_run_plan=tampered,
            evaluated_at=evaluated_at,
            idempotency_key="canonical-plan",
            expected_plan_digest=plan.plan_digest,
            proof=AuthenticationProof(
                method="STATIC_TOKEN", credential="operator-token"
            ),
        )


def test_empty_store_rejects_unjoined_graph_journal_evidence(tmp_path: Path) -> None:
    path = tmp_path / "unpublished.sqlite3"
    sqlite3.connect(path).close()
    ghost = "ghost:1"

    with pytest.raises(GraphitiSpendReconciliationError, match="does not join"):
        plan_graphiti_spend_reconciliation(
            str(path),
            evaluated_at=datetime(2026, 8, 24, tzinfo=UTC),
            graph_journal_evidence={
                ghost: _journal(
                    ghost,
                    ingest_id="ghost",
                    attempt_number=1,
                    state="ABSENT",
                    provider_dispatch_state="NOT_DISPATCHED",
                )
            },
        )


def test_empty_plan_replays_and_backfills_legacy_retained_plan(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    connection.close()
    evaluated_at = datetime(2026, 8, 24, tzinfo=UTC)
    plan = plan_graphiti_spend_reconciliation(str(path), evaluated_at=evaluated_at)
    service = _command_service()
    proof = AuthenticationProof(method="STATIC_TOKEN", credential="operator-token")
    first = service.reconcile_graphiti_spend(
        unpublished_store=str(path),
        dry_run_plan=plan.as_dict(),
        evaluated_at=evaluated_at,
        idempotency_key="empty-plan",
        expected_plan_digest=plan.plan_digest,
        proof=proof,
    )
    replay = service.reconcile_graphiti_spend(
        unpublished_store=str(path),
        dry_run_plan=plan.as_dict(),
        evaluated_at=evaluated_at,
        idempotency_key="empty-plan",
        expected_plan_digest=plan.plan_digest,
        proof=proof,
    )
    assert replay.receipt_digest == first.receipt_digest
    assert replay.applied_transition_count == 0

    connection = sqlite3.connect(path)
    connection.execute(
        "ALTER TABLE unpublished_graphiti_spend_reconciliation_receipts "
        "RENAME TO reconciliation_receipts_with_plan"
    )
    connection.execute(
        """
        CREATE TABLE unpublished_graphiti_spend_reconciliation_receipts(
            idempotency_key TEXT PRIMARY KEY,
            plan_digest TEXT NOT NULL,
            receipt_digest TEXT NOT NULL,
            receipt_json TEXT NOT NULL,
            at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        INSERT INTO unpublished_graphiti_spend_reconciliation_receipts
        SELECT idempotency_key, plan_digest, receipt_digest, receipt_json, at
        FROM reconciliation_receipts_with_plan
        """
    )
    connection.execute("DROP TABLE reconciliation_receipts_with_plan")
    connection.commit()
    connection.close()

    migrated = service.reconcile_graphiti_spend(
        unpublished_store=str(path),
        dry_run_plan=plan.as_dict(),
        evaluated_at=evaluated_at,
        idempotency_key="empty-plan",
        expected_plan_digest=plan.plan_digest,
        proof=proof,
    )
    assert migrated.receipt_digest == first.receipt_digest
    with sqlite3.connect(path) as reopened:
        retained_plan, original_receipt = reopened.execute(
            "SELECT plan_json, receipt_json "
            "FROM unpublished_graphiti_spend_reconciliation_receipts"
        ).fetchone()
    assert json.loads(retained_plan) == plan.as_dict()

    forged = json.loads(original_receipt)
    forged["terminal_attempt_count"] = 999
    forged["terminal_spend_disposition_count"] = 999
    forged["live_reservation_count"] = 999
    unsigned = dict(forged)
    unsigned.pop("receipt_digest")
    forged["receipt_digest"] = digest_bytes(canonical_json_bytes(unsigned))
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE unpublished_graphiti_spend_reconciliation_receipts "
            "SET receipt_json=?, receipt_digest=?",
            (
                canonical_json_bytes(forged).decode("utf-8"),
                forged["receipt_digest"],
            ),
        )
    with pytest.raises(GraphitiSpendReconciliationError, match="ledger event"):
        service.reconcile_graphiti_spend(
            unpublished_store=str(path),
            dry_run_plan=plan.as_dict(),
            evaluated_at=evaluated_at,
            idempotency_key="empty-plan",
            expected_plan_digest=plan.plan_digest,
            proof=proof,
        )

    forged = json.loads(original_receipt)
    forged["applied_at"] = "2099-01-01T00:00:00.000000Z"
    unsigned = dict(forged)
    unsigned.pop("receipt_digest")
    forged["receipt_digest"] = digest_bytes(canonical_json_bytes(unsigned))
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE unpublished_graphiti_spend_reconciliation_receipts "
            "SET receipt_json=?, receipt_digest=?, at=?",
            (
                canonical_json_bytes(forged).decode("utf-8"),
                forged["receipt_digest"],
                forged["applied_at"],
            ),
        )
    with pytest.raises(GraphitiSpendReconciliationError, match="ledger event"):
        service.reconcile_graphiti_spend(
            unpublished_store=str(path),
            dry_run_plan=plan.as_dict(),
            evaluated_at=evaluated_at,
            idempotency_key="empty-plan",
            expected_plan_digest=plan.plan_digest,
            proof=proof,
        )


def test_replay_rejects_a_relinked_ledger_sequence_gap(tmp_path: Path) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    append_ledger(connection, "PREVIOUS_AUDIT", {"sequence": 1})
    connection.commit()
    connection.close()
    service, plan, evaluated_at, proof = _apply_missing_reconciliation(
        path, idempotency_key="ledger-gap"
    )

    connection = sqlite3.connect(path)
    row = connection.execute(
        "SELECT seq, at, kind, payload_digest FROM ledger "
        "WHERE kind='GRAPHITI_SPEND_RECONCILIATION_APPLIED'"
    ).fetchone()
    assert row[0] == 2
    genesis = "sha256:" + ("0" * 64)
    relinked_digest = digest_bytes(
        canonical_json_bytes(
            {
                "at": row[1],
                "kind": row[2],
                "payload_digest": row[3],
                "prev": genesis,
            }
        )
    )
    connection.execute("DELETE FROM ledger WHERE seq=1")
    connection.execute(
        "UPDATE ledger SET prev_digest=?, digest=? WHERE seq=2",
        (genesis, relinked_digest),
    )
    receipt = json.loads(
        connection.execute(
            "SELECT receipt_json "
            "FROM unpublished_graphiti_spend_reconciliation_receipts"
        ).fetchone()[0]
    )
    receipt["ledger_digest"] = relinked_digest
    unsigned_receipt = dict(receipt)
    unsigned_receipt.pop("receipt_digest")
    receipt["receipt_digest"] = digest_bytes(canonical_json_bytes(unsigned_receipt))
    connection.execute(
        "UPDATE unpublished_graphiti_spend_reconciliation_receipts "
        "SET receipt_json=?, receipt_digest=?",
        (
            canonical_json_bytes(receipt).decode("utf-8"),
            receipt["receipt_digest"],
        ),
    )
    connection.commit()
    connection.close()

    with pytest.raises(GraphitiSpendReconciliationError, match="ledger chain differs"):
        service.reconcile_graphiti_spend(
            unpublished_store=str(path),
            dry_run_plan=plan.as_dict(),
            evaluated_at=evaluated_at,
            idempotency_key="ledger-gap",
            expected_plan_digest=plan.plan_digest,
            proof=proof,
        )


def test_plan_and_report_reject_wholesale_reconciliation_evidence_deletion(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    _apply_missing_reconciliation(path, idempotency_key="deleted-outcome")
    connection = sqlite3.connect(path)
    connection.execute("DELETE FROM unpublished_graphiti_spend_dispositions")
    connection.execute("DELETE FROM unpublished_graphiti_spend_reconciliation_receipts")
    connection.commit()
    connection.close()

    with pytest.raises(GraphitiSpendReconciliationError, match="ledger events differ"):
        graphiti_usage_report(str(path))
    with pytest.raises(GraphitiSpendReconciliationError, match="ledger events differ"):
        plan_graphiti_spend_reconciliation(
            str(path), evaluated_at=datetime(2026, 8, 24, tzinfo=UTC)
        )


def test_retained_receipt_requires_exact_json_and_table_digests(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    spend_id = _reserve(connection, ingest_id="receipt-integrity", attempt=1)
    accounting = reconcile_graphiti_spend(
        connection, spend_id=spend_id, embedding_usage=None
    )
    insert_graphiti_attempt_receipt(
        connection,
        ingest_id="receipt-integrity",
        attempt_number=1,
        outcome="FAILED",
        receipt={
            "ingest_id": "receipt-integrity",
            "attempt_number": 1,
            "outcome": "FAILED",
            "provider_attempt_number": 1,
            "chat_invocations": [],
            "embedding_usage": None,
            "accounting": accounting,
        },
    )
    connection.commit()
    connection.close()
    evaluated_at = datetime(2026, 8, 24, tzinfo=UTC)
    plan = plan_graphiti_spend_reconciliation(str(path), evaluated_at=evaluated_at)
    service = _command_service()
    proof = AuthenticationProof(method="STATIC_TOKEN", credential="operator-token")
    service.reconcile_graphiti_spend(
        unpublished_store=str(path),
        dry_run_plan=plan.as_dict(),
        evaluated_at=evaluated_at,
        idempotency_key="receipt-integrity",
        expected_plan_digest=plan.plan_digest,
        proof=proof,
    )

    connection = sqlite3.connect(path)
    original_evidence = connection.execute(
        "SELECT evidence_json FROM unpublished_graphiti_spend_dispositions"
    ).fetchone()[0]
    changed_evidence = json.loads(original_evidence)
    changed_evidence["provider_leaf_count"] = 1
    changed_evidence["provider_leaves_digest"] = digest_bytes(
        canonical_json_bytes([{"provider": "invented"}])
    )
    changed_evidence_json = canonical_json_bytes(changed_evidence).decode("utf-8")
    connection.execute(
        "UPDATE unpublished_graphiti_spend_dispositions "
        "SET evidence_json=?, evidence_digest=?",
        (
            changed_evidence_json,
            digest_bytes(changed_evidence_json.encode("utf-8")),
        ),
    )
    connection.commit()
    connection.close()
    with pytest.raises(
        GraphitiSpendReconciliationError, match="provider leaves differ"
    ):
        graphiti_usage_report(str(path))

    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE unpublished_graphiti_spend_dispositions "
        "SET evidence_json=?, evidence_digest=?",
        (original_evidence, digest_bytes(original_evidence.encode("utf-8"))),
    )
    changed_evidence = json.loads(original_evidence)
    changed_evidence["evidence_basis"] = "TAMPERED"
    connection.execute(
        "UPDATE unpublished_graphiti_spend_dispositions SET evidence_json=?",
        (json.dumps(changed_evidence, sort_keys=True),),
    )
    connection.commit()
    connection.close()
    with pytest.raises(
        GraphitiSpendReconciliationError, match="differs from its digest"
    ):
        graphiti_usage_report(str(path))

    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE unpublished_graphiti_spend_dispositions SET evidence_json=?",
        (original_evidence,),
    )
    original_json = connection.execute(
        "SELECT receipt_json FROM unpublished_graphiti_spend_reconciliation_receipts"
    ).fetchone()[0]
    connection.execute(
        "UPDATE unpublished_graphiti_spend_reconciliation_receipts SET receipt_json=?",
        (json.dumps(json.loads(original_json), indent=2, sort_keys=True),),
    )
    connection.commit()
    connection.close()
    with pytest.raises(GraphitiSpendReconciliationError, match="canonical record"):
        service.reconcile_graphiti_spend(
            unpublished_store=str(path),
            dry_run_plan=plan.as_dict(),
            evaluated_at=evaluated_at,
            idempotency_key="receipt-integrity",
            expected_plan_digest=plan.plan_digest,
            proof=proof,
        )

    connection = sqlite3.connect(path)
    changed = json.loads(original_json)
    changed["public_dispatch"] = True
    connection.execute(
        "UPDATE unpublished_graphiti_spend_reconciliation_receipts SET receipt_json=?",
        (canonical_json_bytes(changed).decode("utf-8"),),
    )
    connection.commit()
    connection.close()
    with pytest.raises(GraphitiSpendReconciliationError, match="canonical record"):
        service.reconcile_graphiti_spend(
            unpublished_store=str(path),
            dry_run_plan=plan.as_dict(),
            evaluated_at=evaluated_at,
            idempotency_key="receipt-integrity",
            expected_plan_digest=plan.plan_digest,
            proof=proof,
        )

    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE unpublished_graphiti_spend_reconciliation_receipts "
        "SET receipt_json=?, receipt_digest=?",
        (original_json, "sha256:" + ("0" * 64)),
    )
    connection.commit()
    connection.close()
    with pytest.raises(GraphitiSpendReconciliationError, match="columns differ"):
        service.reconcile_graphiti_spend(
            unpublished_store=str(path),
            dry_run_plan=plan.as_dict(),
            evaluated_at=evaluated_at,
            idempotency_key="receipt-integrity",
            expected_plan_digest=plan.plan_digest,
            proof=proof,
        )

    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE unpublished_graphiti_spend_reconciliation_receipts "
        "SET receipt_digest=?",
        (json.loads(original_json)["receipt_digest"],),
    )
    forged = json.loads(original_json)
    forged["idempotency_key"] = "forged-command"
    forged["applied_at"] = "2030-01-01T00:00:00.000000Z"
    unsigned_forged = dict(forged)
    unsigned_forged.pop("receipt_digest")
    forged["receipt_digest"] = digest_bytes(canonical_json_bytes(unsigned_forged))
    connection.execute(
        "UPDATE unpublished_graphiti_spend_reconciliation_receipts "
        "SET receipt_json=?, receipt_digest=?",
        (canonical_json_bytes(forged).decode("utf-8"), forged["receipt_digest"]),
    )
    connection.commit()
    connection.close()
    with pytest.raises(GraphitiSpendReconciliationError, match="columns differ"):
        service.reconcile_graphiti_spend(
            unpublished_store=str(path),
            dry_run_plan=plan.as_dict(),
            evaluated_at=evaluated_at,
            idempotency_key="receipt-integrity",
            expected_plan_digest=plan.plan_digest,
            proof=proof,
        )

    connection = sqlite3.connect(path)
    forged = json.loads(original_json)
    forged["ledger_digest"] = "sha256:" + ("f" * 64)
    unsigned_forged = dict(forged)
    unsigned_forged.pop("receipt_digest")
    forged["receipt_digest"] = digest_bytes(canonical_json_bytes(unsigned_forged))
    connection.execute(
        "UPDATE unpublished_graphiti_spend_reconciliation_receipts "
        "SET receipt_json=?, receipt_digest=?",
        (canonical_json_bytes(forged).decode("utf-8"), forged["receipt_digest"]),
    )
    connection.commit()
    connection.close()
    with pytest.raises(GraphitiSpendReconciliationError, match="ledger event"):
        service.reconcile_graphiti_spend(
            unpublished_store=str(path),
            dry_run_plan=plan.as_dict(),
            evaluated_at=evaluated_at,
            idempotency_key="receipt-integrity",
            expected_plan_digest=plan.plan_digest,
            proof=proof,
        )

    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE unpublished_graphiti_spend_reconciliation_receipts "
        "SET receipt_json=?, receipt_digest=?",
        (original_json, json.loads(original_json)["receipt_digest"]),
    )
    connection.execute("DELETE FROM unpublished_graphiti_spend_dispositions")
    connection.commit()
    connection.close()
    with pytest.raises(
        GraphitiSpendReconciliationError, match="differs from its receipt"
    ):
        graphiti_usage_report(str(path))


def test_apply_checks_resolved_symlink_target_before_opening(tmp_path: Path) -> None:
    target = tmp_path / "production.sqlite3"
    sqlite3.connect(target).close()
    alias = tmp_path / "unpublished.sqlite3"
    alias.symlink_to(target)

    with pytest.raises(VetoError, match="store must not alias production"):
        _command_service().reconcile_graphiti_spend(
            unpublished_store=str(alias),
            dry_run_plan={},
            evaluated_at=datetime(2026, 8, 24, tzinfo=UTC),
            idempotency_key="symlink-refused",
            expected_plan_digest="sha256:" + ("0" * 64),
            proof=AuthenticationProof(
                method="STATIC_TOKEN", credential="operator-token"
            ),
        )


def test_apply_rejects_dispatch_snapshot_drift_after_dry_run(tmp_path: Path) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    spend_id = _reserve(connection, ingest_id="dispatch-drift", attempt=1)
    assert claim_graphiti_attempt(
        connection,
        spend_id=spend_id,
        generation_id=GRAPHITI_GENERATION_ID,
        owner_id="owner-before",
        claimed_at="2026-08-23T23:00:00.000000Z",
        lease_expires_at="2026-08-23T23:15:00.000000Z",
    )
    connection.commit()
    connection.close()

    evaluated_at = datetime(2026, 8, 24, tzinfo=UTC)
    plan = plan_graphiti_spend_reconciliation(str(path), evaluated_at=evaluated_at)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE unpublished_graphiti_spend "
            "SET dispatch_owner=?, dispatch_lease_expires_at=? WHERE spend_id=?",
            ("owner-after", "2026-08-23T23:30:00.000000Z", spend_id),
        )

    with pytest.raises(GraphitiSpendReconciliationError, match="store changed"):
        _command_service().reconcile_graphiti_spend(
            unpublished_store=str(path),
            dry_run_plan=plan.as_dict(),
            evaluated_at=evaluated_at,
            idempotency_key="dispatch-drift",
            expected_plan_digest=plan.plan_digest,
            proof=AuthenticationProof(
                method="STATIC_TOKEN", credential="operator-token"
            ),
        )


def test_null_legacy_generation_is_retained_through_apply_and_replay(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    spend_id = _reserve(connection, ingest_id="legacy-generation", attempt=1)
    connection.execute(
        "UPDATE unpublished_graphiti_spend SET generation_id=NULL WHERE spend_id=?",
        (spend_id,),
    )
    accounting = reconcile_graphiti_spend(
        connection, spend_id=spend_id, embedding_usage=None
    )
    insert_graphiti_attempt_receipt(
        connection,
        ingest_id="legacy-generation",
        attempt_number=1,
        outcome="FAILED",
        receipt={
            "ingest_id": "legacy-generation",
            "attempt_number": 1,
            "outcome": "FAILED",
            "provider_attempt_number": 1,
            "chat_invocations": [],
            "embedding_usage": None,
            "accounting": accounting,
        },
    )
    connection.commit()
    connection.close()

    evaluated_at = datetime(2026, 8, 24, tzinfo=UTC)
    plan = plan_graphiti_spend_reconciliation(str(path), evaluated_at=evaluated_at)
    assert plan.transitions[0].source_generation_id is None
    service = _command_service()
    arguments = {
        "unpublished_store": str(path),
        "dry_run_plan": plan.as_dict(),
        "evaluated_at": evaluated_at,
        "idempotency_key": "legacy-generation",
        "expected_plan_digest": plan.plan_digest,
        "proof": AuthenticationProof(
            method="STATIC_TOKEN", credential="operator-token"
        ),
    }
    first = service.reconcile_graphiti_spend(**arguments)
    replay = service.reconcile_graphiti_spend(**arguments)
    assert replay.receipt_digest == first.receipt_digest
    assert graphiti_usage_report(str(path))["terminal_spend_disposition_count"] == 1


def test_unknown_provider_dispatch_is_not_released_by_journal_assertion(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    spend_id = _reserve(connection, ingest_id="unknown-dispatch", attempt=1)
    insert_graphiti_attempt_receipt(
        connection,
        ingest_id="unknown-dispatch",
        attempt_number=1,
        outcome="FAILED",
        receipt={
            "ingest_id": "unknown-dispatch",
            "attempt_number": 1,
            "outcome": "FAILED",
            "provider_attempt_number": None,
            "chat_invocations": [],
            "embedding_usage": None,
        },
    )
    connection.commit()
    connection.close()

    plan = plan_graphiti_spend_reconciliation(
        str(path),
        evaluated_at=datetime(2026, 8, 24, tzinfo=UTC),
        graph_journal_evidence={
            spend_id: _journal(
                spend_id,
                ingest_id="unknown-dispatch",
                attempt_number=1,
                state="ABSENT",
                provider_dispatch_state="NOT_DISPATCHED",
            )
        },
    )
    assert (
        plan.transitions[0].disposition
        is GraphitiSpendDisposition.AMBIGUOUS_EFFECT_HOLD
    )


def test_usage_does_not_dedupe_unreconciled_fabricated_recovery_receipt(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    insert_graphiti_attempt_receipt(
        connection,
        ingest_id="fabricated-recovery",
        attempt_number=2,
        outcome="FAILED",
        receipt={
            "ingest_id": "fabricated-recovery",
            "attempt_number": 2,
            "outcome": "FAILED",
            "provider_attempt_number": 1,
            "chat_invocations": [],
            "embedding_usage": _provider_usage(),
            "token_usage": _token_usage(),
            "accounting": {
                "recovery_classification": "RECOVERED_IMMUTABLE_COMPLETE",
                "provider_attempt": {"retained_attempt_receipt": True},
                "current_attempt": {"usage_basis": "NO_PROVIDER_IO"},
            },
        },
    )
    connection.commit()
    connection.close()

    report = graphiti_usage_report(str(path))
    assert report["embedding_request_count"] == 1
    assert report["embedding_cost_usd_microunits"] == 17


def test_partial_token_usage_cannot_make_provider_spend_complete(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unpublished.sqlite3"
    connection = connect(str(path))
    spend_id = _reserve(connection, ingest_id="partial-token-usage", attempt=1)
    usage = _provider_usage()
    accounting = reconcile_graphiti_spend(
        connection, spend_id=spend_id, embedding_usage=usage
    )
    insert_graphiti_attempt_receipt(
        connection,
        ingest_id="partial-token-usage",
        attempt_number=1,
        outcome="COMPLETE",
        receipt={
            "ingest_id": "partial-token-usage",
            "attempt_number": 1,
            "outcome": "COMPLETE",
            "provider_attempt_number": 1,
            "chat_invocations": [],
            "embedding_usage": usage,
            "token_usage": {},
            "accounting": accounting,
        },
    )
    connection.commit()
    connection.close()

    evaluated_at = datetime(2026, 8, 24, tzinfo=UTC)
    plan = plan_graphiti_spend_reconciliation(str(path), evaluated_at=evaluated_at)
    _command_service().reconcile_graphiti_spend(
        unpublished_store=str(path),
        dry_run_plan=plan.as_dict(),
        evaluated_at=evaluated_at,
        idempotency_key="partial-token-usage",
        expected_plan_digest=plan.plan_digest,
        proof=AuthenticationProof(method="STATIC_TOKEN", credential="operator-token"),
    )

    report = graphiti_usage_report(str(path))
    assert report["unreported_attempt_count"] == 1
    assert report["measured_attempt_count"] == 0
    assert report["cost_complete"] is False
    assert report["missing_usage_is_zero"] is False
