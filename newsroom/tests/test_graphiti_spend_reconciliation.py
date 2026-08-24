from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.auth import (
    AuthenticationError,
    AuthenticationProof,
    StaticAuthenticator,
    StaticPrincipal,
)
from newsroom.control_plane.command_service import ControlPlaneCommandService
from newsroom.control_plane.graphiti_spend_reconciliation import (
    GraphitiSpendDisposition,
    GraphitiSpendReconciliationError,
    plan_graphiti_spend_reconciliation,
)
from newsroom.control_plane.store import (
    claim_graphiti_attempt,
    connect,
    insert_graphiti_attempt_receipt,
    reconcile_graphiti_spend,
    reserve_graphiti_spend,
)
from newsroom.control_plane.usage import graphiti_usage_report
from newsroom.control_plane.veto import VetoError
from newsroom.graphiti_adapter.evaluation_packet import GRAPHITI_GENERATION_ID
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
            "embedding_usage": None,
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
    service = ControlPlaneCommandService(
        authenticator=StaticAuthenticator(
            credentials={
                "operator-token": StaticPrincipal(principal_id="newsroom.hermes")
            },
            authority_domain="newsroom.control-plane",
        )
    )

    with pytest.raises(AuthenticationError, match="invalid authentication"):
        service.reconcile_graphiti_spend(
            unpublished_store=str(path),
            dry_run_plan=dry_run.as_dict(),
            evaluated_at=evaluated_at,
            idempotency_key="reconcile-1",
            expected_plan_digest=dry_run.plan_digest,
            proof=AuthenticationProof(method="STATIC_TOKEN", credential="wrong"),
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
        "SELECT COUNT(*) FROM ledger "
        "WHERE kind='GRAPHITI_SPEND_RECONCILIATION_APPLIED'"
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
    connection.commit()
    connection.close()
    usage = _provider_usage(23)
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

    service = ControlPlaneCommandService(
        authenticator=StaticAuthenticator(
            credentials={
                "operator-token": StaticPrincipal(principal_id="newsroom.hermes")
            },
            authority_domain="newsroom.control-plane",
        )
    )
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
    service = ControlPlaneCommandService(
        authenticator=StaticAuthenticator(
            credentials={
                "operator-token": StaticPrincipal(principal_id="newsroom.hermes")
            },
            authority_domain="newsroom.control-plane",
        )
    )
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
            "embedding_usage": None,
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
    service = ControlPlaneCommandService(
        authenticator=StaticAuthenticator(
            credentials={
                "operator-token": StaticPrincipal(principal_id="newsroom.hermes")
            },
            authority_domain="newsroom.control-plane",
        )
    )

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
            "usage": {"usage_basis": "UNREPORTED"},
        }
    ]
    for attempt in (1, 2):
        spend_id = _reserve(connection, ingest_id="recovered-retry", attempt=attempt)
        accounting = reconcile_graphiti_spend(
            connection, spend_id=spend_id, embedding_usage=None
        )
        insert_graphiti_attempt_receipt(
            connection,
            ingest_id="recovered-retry",
            attempt_number=attempt,
            outcome="FAILED",
            receipt={
                "ingest_id": "recovered-retry",
                "attempt_number": attempt,
                "outcome": "FAILED",
                "provider_attempt_number": 1 if attempt == 1 else None,
                "chat_invocations": provider_leaves if attempt == 1 else [],
                "embedding_usage": None,
                "accounting": accounting,
            },
        )
    connection.commit()
    connection.close()
    first, retry = "recovered-retry:1", "recovered-retry:2"
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
            ),
        },
    )

    by_spend = {item.spend_id: item for item in plan.transitions}
    assert by_spend[first].disposition is (
        GraphitiSpendDisposition.UNRECONCILED_REPORTED_MISSING
    )
    assert by_spend[first].provider_leaf_count == 1
    assert by_spend[retry].disposition is (
        GraphitiSpendDisposition.RELEASED_BEFORE_PROVIDER_IO
    )
    assert by_spend[retry].evidence_basis == (
        "RECOVERED_COMPLETE_WITHOUT_SECOND_PROVIDER_DISPATCH"
    )
    assert plan.provider_calls == 0


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
            "chat_invocations": [{"invocation_id": "retained"}],
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
                    provider_leaves=[{"invocation_id": "substituted"}],
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
    service = ControlPlaneCommandService(
        authenticator=StaticAuthenticator(
            credentials={
                "operator-token": StaticPrincipal(principal_id="newsroom.hermes")
            },
            authority_domain="newsroom.control-plane",
        )
    )

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
