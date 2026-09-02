from __future__ import annotations

import os
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import newsroom.control_plane.graphiti_event_reconciliation as event_repair
from newsroom.authority.auth import (
    AuthenticationProof,
    StaticAuthenticator,
    StaticPrincipal,
)
from newsroom.authority.types import UtcTimestamp
from newsroom.control_plane.command_service import ControlPlaneCommandService
from newsroom.control_plane.corpus import CorpusIngestUnit
from newsroom.control_plane.graphiti_event_reconciliation import (
    GraphitiEventRepairDisposition,
    GraphitiEventReconciliationError,
    plan_graphiti_event_reconciliation,
)
from newsroom.control_plane.graphiti_events import GraphitiEventQueue
from newsroom.control_plane.graphiti_steady_state import (
    _event_accounting,
    build_graphiti_steady_state_packet,
)
from newsroom.control_plane.store import connect, emit_effective_revision_landed
from newsroom.effective_revision import EffectiveRevisionIdentity
from newsroom.graphiti_adapter.identity import content_digest


EVALUATED_AT = datetime(2026, 9, 1, 12, tzinfo=UTC)
PROOF = AuthenticationProof(method="STATIC_TOKEN", credential="operator-token")


def _unit(number: int) -> CorpusIngestUnit:
    headline = f"Headline {number}"
    body = f"Body {number}"
    url = f"https://example.test/{number}"
    observed_at = "2026-09-01T00:00:00.000000Z"
    identity = EffectiveRevisionIdentity(
        source_id="UK-01",
        item_key=f"item-{number}",
        revision_digest=content_digest(
            headline=headline,
            body=body,
            canonical_url=url,
        ),
        first_observed_at=observed_at,
    )
    return CorpusIngestUnit(
        source_id=identity.source_id,
        item_key=identity.item_key,
        headline=headline,
        body=body,
        canonical_url=url,
        observation_digest=f"sha256:observation-{number}",
        observed_at=observed_at,
        proving_run_id="run-1",
        effective_revision=identity,
        source_definition_url="https://example.test/feed",
        effective_pull_first_observed_at=observed_at,
    )


def _stores(tmp_path: Path) -> tuple[Path, Path]:
    proving = tmp_path / "proving.sqlite3"
    connection = sqlite3.connect(proving)
    connection.execute("CREATE TABLE fixture(value TEXT NOT NULL)")
    connection.execute("INSERT INTO fixture VALUES('exact proving identity')")
    connection.commit()
    connection.close()
    unpublished = tmp_path / "unpublished.sqlite3"
    connection = connect(str(unpublished))
    connection.close()
    return proving, unpublished


def _land(
    unpublished: Path,
    unit: CorpusIngestUnit,
    *,
    ingest_ids: tuple[str, ...] | None = None,
) -> str:
    connection = connect(str(unpublished))
    assert emit_effective_revision_landed(
        connection,
        unit.effective_revision,
        published_at=unit.published_at,
        updated_at=unit.updated_at,
        ingest_ids=(unit.ingest_id,) if ingest_ids is None else ingest_ids,
        landed_at=unit.coverage_first_observed_at,
    )
    connection.commit()
    event_id = str(
        connection.execute(
            "SELECT ledger_digest FROM unpublished_effective_revision_landed "
            "WHERE source_id=? AND item_key=? AND revision_digest=?",
            (unit.source_id, unit.item_key, unit.revision_digest),
        ).fetchone()[0]
    )
    connection.close()
    return event_id


def _service(*, principal: str = "newsroom.hermes") -> ControlPlaneCommandService:
    return ControlPlaneCommandService(
        authenticator=StaticAuthenticator(
            credentials={"operator-token": StaticPrincipal(principal_id=principal)},
            authority_domain="newsroom.control-plane",
        ),
        clock=lambda: UtcTimestamp(EVALUATED_AT),
    )


def _apply(
    service: ControlPlaneCommandService,
    proving: Path,
    unpublished: Path,
    plan: event_repair.GraphitiEventReconciliationPlan,
    *,
    idempotency_key: str = "repair-events-1",
) -> event_repair.GraphitiEventReconciliationReceipt:
    return service.reconcile_graphiti_events(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        dry_run_plan=plan.as_dict(),
        evaluated_at=EVALUATED_AT,
        idempotency_key=idempotency_key,
        expected_plan_digest=plan.plan_digest,
        proof=PROOF,
    )


def test_plan_projects_59_exact_revisions_and_holds_ingest_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proving, unpublished = _stores(tmp_path)
    exact = tuple(_unit(number) for number in range(1, 60))
    drift = _unit(60)
    for unit in exact:
        _land(unpublished, unit)
    drift_event_id = _land(unpublished, drift, ingest_ids=("retained-old-ingest",))
    monkeypatch.setattr(
        event_repair,
        "load_graphiti_units_from_connection",
        lambda _connection, *, evaluated_at: (*exact, drift),
    )

    plan = plan_graphiti_event_reconciliation(
        str(proving), str(unpublished), evaluated_at=EVALUATED_AT
    )

    assert plan.provider_calls == 0
    assert len(plan.decisions) == 60
    assert sum(
        item.disposition is GraphitiEventRepairDisposition.PROJECT_EVENT
        for item in plan.decisions
    ) == 59
    drift_decision = next(item for item in plan.decisions if item.event_id == drift_event_id)
    assert drift_decision.disposition is GraphitiEventRepairDisposition.HOLD
    assert drift_decision.reason == "RESOLVED_INGEST_IDS_DIFFER_FROM_LANDED"
    connection = sqlite3.connect(unpublished)
    accounting, blockers = _event_accounting(
        connection, gap_decisions=plan.decisions
    )
    connection.close()
    assert blockers == ["LANDED_REVISION_EVENT_MISSING"]
    assert len(accounting["projection_candidate_ledger_sequences"]) == 59
    assert accounting["held_missing_event_ledger_sequences"] == [
        drift_decision.ledger_seq
    ]

    receipt = _apply(_service(), proving, unpublished, plan)
    assert receipt.projected_event_count == 59
    assert receipt.hold_count == 1
    assert receipt.provider_calls == 0
    connection = connect(str(unpublished))
    rows = connection.execute(
        "SELECT state,provider_dispatched,attempt_count FROM "
        "unpublished_graphiti_revision_events ORDER BY ledger_seq"
    ).fetchall()
    connection.close()
    assert rows == [("QUEUED", 0, 0)] * 59

    remaining = plan_graphiti_event_reconciliation(
        str(proving), str(unpublished), evaluated_at=EVALUATED_AT
    )
    connection = sqlite3.connect(unpublished)
    accounting, blockers = _event_accounting(
        connection, gap_decisions=remaining.decisions
    )
    connection.close()
    assert blockers == []
    assert accounting["one_to_one"] is False
    assert accounting["eligible_one_to_one"] is True


def test_apply_refuses_store_drift_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proving, unpublished = _stores(tmp_path)
    first, later = _unit(1), _unit(2)
    _land(unpublished, first)
    units = [first]
    monkeypatch.setattr(
        event_repair,
        "load_graphiti_units_from_connection",
        lambda _connection, *, evaluated_at: tuple(units),
    )
    plan = plan_graphiti_event_reconciliation(
        str(proving), str(unpublished), evaluated_at=EVALUATED_AT
    )
    units.append(later)
    _land(unpublished, later)

    with pytest.raises(
        GraphitiEventReconciliationError,
        match="stores changed after the dry-run event-repair plan",
    ):
        _apply(_service(), proving, unpublished, plan)

    connection = connect(str(unpublished))
    assert connection.execute(
        "SELECT COUNT(*) FROM unpublished_graphiti_revision_events"
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM unpublished_reconciliation_commands "
        "WHERE command_type='RECONCILE_GRAPHITI_EVENTS'"
    ).fetchone()[0] == 0
    connection.close()


def test_plan_and_apply_refuse_pre_existing_ledger_chain_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proving, unpublished = _stores(tmp_path)
    unit = _unit(1)
    _land(unpublished, unit)
    monkeypatch.setattr(
        event_repair,
        "load_graphiti_units_from_connection",
        lambda _connection, *, evaluated_at: (unit,),
    )
    valid_plan = plan_graphiti_event_reconciliation(
        str(proving), str(unpublished), evaluated_at=EVALUATED_AT
    )
    connection = connect(str(unpublished))
    connection.execute(
        "UPDATE ledger SET prev_digest=? WHERE seq=1",
        ("sha256:" + "f" * 64,),
    )
    connection.commit()
    connection.close()

    with pytest.raises(GraphitiEventReconciliationError, match="ledger chain differs"):
        plan_graphiti_event_reconciliation(
            str(proving), str(unpublished), evaluated_at=EVALUATED_AT
        )
    with pytest.raises(GraphitiEventReconciliationError, match="ledger chain differs"):
        _apply(_service(), proving, unpublished, valid_plan)

    connection = connect(str(unpublished))
    assert connection.execute(
        "SELECT COUNT(*) FROM unpublished_graphiti_revision_events"
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM unpublished_reconciliation_commands "
        "WHERE command_type='RECONCILE_GRAPHITI_EVENTS'"
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM ledger "
        "WHERE kind='GRAPHITI_EVENT_RECONCILIATION_APPLIED'"
    ).fetchone()[0] == 0
    connection.close()


@pytest.mark.parametrize("alias_kind", ["same-path", "hard-link"])
def test_plan_and_apply_refuse_aliased_authority_and_writable_stores(
    tmp_path: Path,
    alias_kind: str,
) -> None:
    _proving, unpublished = _stores(tmp_path)
    proving_alias = unpublished
    if alias_kind == "hard-link":
        proving_alias = tmp_path / "proving-alias.sqlite3"
        os.link(unpublished, proving_alias)

    with pytest.raises(GraphitiEventReconciliationError, match="must be distinct"):
        plan_graphiti_event_reconciliation(
            str(proving_alias),
            str(unpublished),
            evaluated_at=EVALUATED_AT,
        )
    with pytest.raises(GraphitiEventReconciliationError, match="must be distinct"):
        _service().reconcile_graphiti_events(
            proving_store=str(proving_alias),
            unpublished_store=str(unpublished),
            dry_run_plan={},
            evaluated_at=EVALUATED_AT,
            idempotency_key="aliased-stores",
            expected_plan_digest="sha256:" + "0" * 64,
            proof=PROOF,
        )

    connection = connect(str(unpublished))
    assert connection.execute(
        "SELECT COUNT(*) FROM unpublished_graphiti_revision_events"
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM unpublished_reconciliation_commands "
        "WHERE command_type='RECONCILE_GRAPHITI_EVENTS'"
    ).fetchone()[0] == 0
    connection.close()


def test_apply_requires_hermes_authentication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proving, unpublished = _stores(tmp_path)
    unit = _unit(1)
    _land(unpublished, unit)
    monkeypatch.setattr(
        event_repair,
        "load_graphiti_units_from_connection",
        lambda _connection, *, evaluated_at: (unit,),
    )
    plan = plan_graphiti_event_reconciliation(
        str(proving), str(unpublished), evaluated_at=EVALUATED_AT
    )

    with pytest.raises(PermissionError, match="requires the Hermes principal"):
        _apply(_service(principal="other.principal"), proving, unpublished, plan)

    connection = connect(str(unpublished))
    assert connection.execute(
        "SELECT COUNT(*) FROM unpublished_graphiti_revision_events"
    ).fetchone()[0] == 0
    connection.close()


def test_apply_replays_retained_receipt_idempotently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proving, unpublished = _stores(tmp_path)
    unit = _unit(1)
    _land(unpublished, unit)
    monkeypatch.setattr(
        event_repair,
        "load_graphiti_units_from_connection",
        lambda _connection, *, evaluated_at: (unit,),
    )
    plan = plan_graphiti_event_reconciliation(
        str(proving), str(unpublished), evaluated_at=EVALUATED_AT
    )
    service = _service()

    first = _apply(service, proving, unpublished, plan)
    second = _apply(service, proving, unpublished, plan)

    assert second == first
    connection = connect(str(unpublished))
    assert connection.execute(
        "SELECT COUNT(*) FROM unpublished_graphiti_revision_events"
    ).fetchone()[0] == 1
    assert connection.execute(
        "SELECT COUNT(*) FROM ledger "
        "WHERE kind='GRAPHITI_EVENT_RECONCILIATION_APPLIED'"
    ).fetchone()[0] == 1
    assert connection.execute(
        "SELECT COUNT(*) FROM unpublished_reconciliation_commands "
        "WHERE command_type='RECONCILE_GRAPHITI_EVENTS'"
    ).fetchone()[0] == 1
    connection.close()


def test_apply_binds_every_projected_unit_ref_field(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proving, unpublished = _stores(tmp_path)
    unit = _unit(1)
    _land(unpublished, unit)
    selected = [unit]
    monkeypatch.setattr(
        event_repair,
        "load_graphiti_units_from_connection",
        lambda _connection, *, evaluated_at: tuple(selected),
    )
    plan = plan_graphiti_event_reconciliation(
        str(proving), str(unpublished), evaluated_at=EVALUATED_AT
    )
    changed = replace(unit, proving_run_id="run-changed-after-plan")
    assert changed.ingest_id == unit.ingest_id
    selected[:] = [changed]

    with pytest.raises(
        GraphitiEventReconciliationError,
        match="stores changed after the dry-run event-repair plan",
    ):
        _apply(_service(), proving, unpublished, plan)

    connection = connect(str(unpublished))
    assert connection.execute(
        "SELECT COUNT(*) FROM unpublished_graphiti_revision_events"
    ).fetchone()[0] == 0
    connection.close()


def test_retained_hold_is_durably_excluded_from_generic_projection_and_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proving, unpublished = _stores(tmp_path)
    unit = _unit(1)
    event_id = _land(
        unpublished,
        unit,
        ingest_ids=("retained-different-ingest",),
    )
    monkeypatch.setattr(
        event_repair,
        "load_graphiti_units_from_connection",
        lambda _connection, *, evaluated_at: (unit,),
    )
    plan = plan_graphiti_event_reconciliation(
        str(proving), str(unpublished), evaluated_at=EVALUATED_AT
    )
    receipt = _apply(_service(), proving, unpublished, plan)

    assert [item.event_id for item in receipt.held_events] == [event_id]
    queue = GraphitiEventQueue(str(unpublished), clock=lambda: EVALUATED_AT)
    health = queue.health()
    assert health.eligible_revision_count == 0
    assert health.queue_depth == 0
    assert queue.claim(owner_id="generic", lease_for=timedelta(minutes=1)) is None
    with pytest.raises(ValueError, match="durably retry-excluded"):
        queue.claim(
            owner_id="exact-retry",
            lease_for=timedelta(minutes=1),
            event_id=event_id,
        )
    connection = connect(str(unpublished))
    assert connection.execute(
        "SELECT COUNT(*) FROM unpublished_graphiti_revision_events"
    ).fetchone()[0] == 0
    connection.execute(
        "UPDATE unpublished_effective_revision_landed SET payload_digest='tampered'"
    )
    connection.commit()
    connection.close()

    corrupt = plan_graphiti_event_reconciliation(
        str(proving), str(unpublished), evaluated_at=EVALUATED_AT
    )
    assert (
        corrupt.decisions[0].disposition
        is GraphitiEventRepairDisposition.UNCLASSIFIED
    )
    assert corrupt.decisions[0].reason == "LANDED_PAYLOAD_IDENTITY_DIFFERS"
    with pytest.raises(
        GraphitiEventReconciliationError,
        match="landing identity differs",
    ):
        queue.health()


@pytest.mark.parametrize("tamper", ["ledger-chain", "command-deletion"])
def test_retained_hold_authority_drift_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    proving, unpublished = _stores(tmp_path)
    unit = _unit(1)
    _land(unpublished, unit, ingest_ids=("retained-different-ingest",))
    monkeypatch.setattr(
        event_repair,
        "load_graphiti_units_from_connection",
        lambda _connection, *, evaluated_at: (unit,),
    )
    plan = plan_graphiti_event_reconciliation(
        str(proving), str(unpublished), evaluated_at=EVALUATED_AT
    )
    _apply(_service(), proving, unpublished, plan)
    connection = connect(str(unpublished))
    if tamper == "ledger-chain":
        connection.execute(
            "UPDATE ledger SET prev_digest=? "
            "WHERE kind='GRAPHITI_EVENT_RECONCILIATION_APPLIED'",
            ("sha256:" + "f" * 64,),
        )
    else:
        connection.execute(
            "DELETE FROM unpublished_reconciliation_commands "
            "WHERE command_type='RECONCILE_GRAPHITI_EVENTS'"
        )
    connection.commit()
    connection.close()

    queue = GraphitiEventQueue(str(unpublished), clock=lambda: EVALUATED_AT)
    with pytest.raises(GraphitiEventReconciliationError):
        queue.health()

    packet = build_graphiti_steady_state_packet(
        proving_store=proving,
        unpublished_store=unpublished,
        head_sha="head",
        tree_sha="tree",
        observed_at=EVALUATED_AT,
    )
    assert packet["verdict"] == "NO_GO"
    assert "EVENT_REPAIR_EVIDENCE_INTEGRITY_FAILURE" in packet["blockers"]


def test_retained_replay_refuses_missing_projected_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proving, unpublished = _stores(tmp_path)
    unit = _unit(1)
    _land(unpublished, unit)
    monkeypatch.setattr(
        event_repair,
        "load_graphiti_units_from_connection",
        lambda _connection, *, evaluated_at: (unit,),
    )
    plan = plan_graphiti_event_reconciliation(
        str(proving), str(unpublished), evaluated_at=EVALUATED_AT
    )
    service = _service()
    _apply(service, proving, unpublished, plan)
    connection = connect(str(unpublished))
    connection.execute("DELETE FROM unpublished_graphiti_revision_events")
    connection.commit()
    connection.close()

    with pytest.raises(
        GraphitiEventReconciliationError,
        match="projection is missing",
    ):
        _apply(service, proving, unpublished, plan)


def test_retained_replay_refuses_projected_routing_identity_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proving, unpublished = _stores(tmp_path)
    unit = _unit(1)
    _land(unpublished, unit)
    monkeypatch.setattr(
        event_repair,
        "load_graphiti_units_from_connection",
        lambda _connection, *, evaluated_at: (unit,),
    )
    plan = plan_graphiti_event_reconciliation(
        str(proving), str(unpublished), evaluated_at=EVALUATED_AT
    )
    service = _service()
    _apply(service, proving, unpublished, plan)
    connection = connect(str(unpublished))
    connection.execute(
        "UPDATE unpublished_graphiti_revision_events SET source_id='tampered'"
    )
    connection.commit()
    connection.close()

    with pytest.raises(
        GraphitiEventReconciliationError,
        match="projection identity differs",
    ):
        _apply(service, proving, unpublished, plan)

    packet = build_graphiti_steady_state_packet(
        proving_store=proving,
        unpublished_store=unpublished,
        head_sha="head",
        tree_sha="tree",
        observed_at=EVALUATED_AT,
    )
    assert packet["verdict"] == "NO_GO"
    assert "EVENT_REPAIR_EVIDENCE_INTEGRITY_FAILURE" in packet["blockers"]
