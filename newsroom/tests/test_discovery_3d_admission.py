from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import time
from dataclasses import replace
from pathlib import Path
import sqlite3

import pytest

from newsroom.authority import AuthorityWriterBusy
from newsroom.checks import BaselineDisposition, CheckOutcomeKind

from newsroom.discovery import (
    DecisionTerminality,
    GateOutcome,
    LeadDispositionDecisionId,
    LeadDispositionOutcome,
    NextAction,
    NextActionKind,
    SignalLeadAdmissionRequest,
    TimeValidity,
)

from .check_3c_authority_helpers import proof
from .check_3c_helpers import (
    FINDING_ID,
    baseline_decision,
    changed_outcome,
    check_attempt,
    check_request,
    finding_occurrence,
    first_transition,
    operational_finding,
)
from .check_3c_authority_helpers import (
    definition_request,
    item_request,
    occurrence_request,
    representation_request,
    revision_request,
    version_request,
)
from .discovery_3d_authority_helpers import (
    DISPOSITION_ID,
    GATE_ID,
    LEAD_ID,
    SIGNAL_ID,
    exact_admission_request,
    exact_gate_request,
    exact_initial_disposition,
    exact_lead_request,
    exact_signal_request,
    open_discovery_system,
    scopes,
    seed_check_lineage,
)
from .discovery_3d_helpers import disposition_request, reason, watch_request


def _hold_gate():
    basis = replace(
        exact_gate_request().basis,
        operationally_executable=False,
        policy_current=False,
        time_validity=TimeValidity.CURRENT,
    )
    return replace(
        exact_gate_request(),
        basis=basis,
        outcome=GateOutcome.OPERATIONAL_HOLD,
        terminality=DecisionTerminality.PENDING_CONDITION,
        primary_reason=reason("OPS.REQUIRED_CONTEXT_UNAVAILABLE"),
        next_action=NextAction(
            NextActionKind.WAIT_DEPENDENCY,
            "WAIT_FOR_REQUIRED_CONTEXT",
            dependency="fixture-context-authority",
            instructions="Retain the Signal without creating a Lead.",
        ),
        idempotency_key="fixture-operational-hold-gate",
    )


def test_pre_authorization_failure_leaves_no_partial_discovery_state(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    with open_discovery_system(
        database,
        granted_scopes=scopes()
        - {"authority.discovery.leads.disposition"},
    ) as system:
        seed_check_lineage(system)
        with pytest.raises(PermissionError):
            system.discovery.admit_signal_to_lead(
                exact_admission_request(), proof=proof()
            )

    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM discovery_signals").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM discovery_gate_decisions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM news_leads").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM lead_disposition_decisions").fetchone()[0] == 0


def test_operational_hold_admits_signal_and_gate_without_lead(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    plan = SignalLeadAdmissionRequest(
        signal=exact_signal_request(),
        gate=_hold_gate(),
        lead=None,
        initial_disposition=None,
    )
    with open_discovery_system(database) as system:
        seed_check_lineage(system)
        result = system.discovery.admit_signal_to_lead(plan, proof=proof())
        assert result.lead is None
        assert result.initial_disposition is None
        status = system.discovery.current_status(SIGNAL_ID, proof=proof())
        assert status.current_gate.request.outcome is GateOutcome.OPERATIONAL_HOLD
        assert status.lead is None
        assert status.next_action == plan.gate.next_action


def test_lead_watch_and_later_disposition_are_append_only(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    with open_discovery_system(database) as system:
        seed_check_lineage(system)
        created = system.discovery.admit_signal_to_lead(
            exact_admission_request(), proof=proof()
        )
        assert created.initial_disposition is not None
        watch = system.discovery.record_watch_condition(
            watch_request(), proof=proof()
        )
        later = replace(
            disposition_request(outcome=LeadDispositionOutcome.WATCH_DEFER),
            decision_id=LeadDispositionDecisionId.parse(
                "00000000-0000-4000-8000-000000007094"
            ),
            lead_id=LEAD_ID,
            decision_ordinal=2,
            previous_decision_id=DISPOSITION_ID,
            urgency_route=exact_lead_request().urgency,
            idempotency_key="fixture-watch-disposition-v2",
        )
        retained = system.discovery.record_lead_disposition(later, proof=proof())
        status = system.discovery.current_status(SIGNAL_ID, proof=proof())
        assert status.watch_condition == watch
        assert status.current_disposition == retained
        assert system.discovery.dispositions(
            LEAD_ID, limit=10, proof=proof()
        ) == (created.initial_disposition, retained)


def test_incomplete_signal_requires_exact_finding_and_visible_lead_warning(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    with open_discovery_system(database) as system:
        system.sources.register_definition(definition_request(), proof=proof())
        system.sources.record_definition_version(version_request(), proof=proof())
        system.checks.register_request(check_request(), proof=proof())
        system.checks.start_attempt(check_attempt(), proof=proof())
        system.checks.record_outcome(
            changed_outcome(kind=CheckOutcomeKind.SUCCESS_PARTIAL, incomplete=True), proof=proof()
        )
        system.sources.register_item(item_request(), proof=proof())
        system.sources.record_revision(revision_request(), proof=proof())
        system.sources.record_representation(representation_request(), proof=proof())
        system.sources.record_occurrence(occurrence_request(), proof=proof())
        system.checks.decide_baseline(
            replace(
                baseline_decision(),
                disposition=BaselineDisposition.MANUAL_HOLD,
                reason_codes=("INCOMPLETE_OUTCOME_MANUAL_HOLD",),
                idempotency_key="incomplete-baseline-hold",
            ),
            proof=proof(),
        )
        system.checks.record_transition(first_transition(), proof=proof())
        system.checks.open_finding(operational_finding(), proof=proof())
        system.checks.record_finding_occurrence(finding_occurrence(), proof=proof())

        signal = replace(
            exact_signal_request(),
            incomplete=True,
            operational_finding_ids=(FINDING_ID,),
            idempotency_key="incomplete-signal",
        )
        lead = replace(
            exact_lead_request(),
            incompleteness_warnings=("CHECK_RESULT_INCOMPLETE",),
            idempotency_key="incomplete-signal-lead",
        )
        result = system.discovery.admit_signal_to_lead(
            SignalLeadAdmissionRequest(
                signal=signal,
                gate=exact_gate_request(),
                lead=lead,
                initial_disposition=exact_initial_disposition(),
            ),
            proof=proof(),
        )
        assert result.signal.request.operational_finding_ids == (FINDING_ID,)
        assert result.lead is not None
        assert result.lead.request.incompleteness_warnings == (
            "CHECK_RESULT_INCOMPLETE",
        )


def test_competing_workers_converge_on_one_signal_gate_and_lead(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    with open_discovery_system(database) as system:
        seed_check_lineage(system)

    def worker():
        for _ in range(100):
            try:
                with open_discovery_system(database) as system:
                    return system.discovery.admit_signal_to_lead(
                        exact_admission_request(), proof=proof()
                    )
            except AuthorityWriterBusy:
                time.sleep(0.01)
        raise AssertionError("competing authority writer did not converge")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _: worker(), range(2)))

    assert {result.signal.event_id for result in results}
    assert len({result.signal.event_id for result in results}) == 1
    assert len({result.gate.event_id for result in results}) == 1
    assert len({result.lead.event_id for result in results if result.lead}) == 1
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM discovery_signals").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM discovery_gate_decisions").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM news_leads").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM lead_disposition_decisions").fetchone()[0] == 1
