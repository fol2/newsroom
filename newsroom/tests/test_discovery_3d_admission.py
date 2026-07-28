from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import time
from dataclasses import replace
from pathlib import Path
import sqlite3

import pytest

from newsroom.authority import AuthorityWriterBusy
from newsroom.authority._check_store_support import _observed_item_id
from newsroom.checks import (
    BaselineDisposition,
    CheckOutcomeKind,
    OperationalFindingId,
    BaselineDecisionId,
    CandidateObservationRef,
    CheckAttemptId,
    CheckOutcomeId,
    CheckRequestId,
    ObservableTransitionId,
)

from newsroom.checks.admission_models import deterministic_uuid4

from newsroom.discovery import (
    DecisionTerminality,
    DiscoveryVersionConflict,
    GateOutcome,
    LeadDispositionDecisionId,
    LeadDispositionOutcome,
    DiscoverySignalId,
    GateDecisionId,
    NewsLeadId,
    ReasonReference,
    StructuredReason,
    NextAction,
    NextActionKind,
    SignalLeadAdmissionRequest,
    TimeValidity,
)

from .check_3c_authority_helpers import proof
from newsroom.discovery_adapters import AdapterRequestId, ObservationProposalId
from newsroom.sources import (
    DiscoveryOccurrenceId,
    DiscoveryRepresentationId,
    IdentityComponent,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceItemId,
    SourceRevisionId,
    VersionedPolicyRef,
)

from .check_3c_helpers import (
    FINDING_ID,
    baseline_decision,
    baseline_entry,
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


def test_incomplete_signal_cannot_add_unrelated_finding_lineage(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    with open_discovery_system(database) as system:
        system.sources.register_definition(definition_request(), proof=proof())
        system.sources.record_definition_version(version_request(), proof=proof())
        system.checks.register_request(check_request(), proof=proof())
        system.checks.start_attempt(check_attempt(), proof=proof())
        system.checks.record_outcome(
            changed_outcome(
                kind=CheckOutcomeKind.SUCCESS_PARTIAL,
                incomplete=True,
            ),
            proof=proof(),
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
                idempotency_key="incomplete-baseline-extra-finding",
            ),
            proof=proof(),
        )
        system.checks.record_transition(first_transition(), proof=proof())
        system.checks.open_finding(operational_finding(), proof=proof())
        system.checks.record_finding_occurrence(
            finding_occurrence(),
            proof=proof(),
        )

        extra = OperationalFindingId.parse(
            "00000000-0000-4000-8000-000000006015"
        )
        signal = replace(
            exact_signal_request(),
            incomplete=True,
            operational_finding_ids=(FINDING_ID, extra),
            idempotency_key="incomplete-signal-extra-finding",
        )
        with pytest.raises(
            DiscoveryVersionConflict,
            match="exact Outcome findings",
        ):
            system.discovery.admit_signal(signal, proof=proof())


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


_SECOND_DEFINITION_ID = SourceDefinitionId.parse(
    "00000000-0000-4000-8000-000000008004"
)
_SECOND_VERSION_ID = SourceDefinitionVersionId.parse(
    "00000000-0000-4000-8000-000000008005"
)
_SECOND_ITEM_KEY = "sha256:" + "1" * 64
_SECOND_ITEM_ID = deterministic_uuid4(
    SourceItemId,
    namespace="increment-3c-source-item-v1",
    semantic_value={
        "definition_id": str(_SECOND_DEFINITION_ID),
        "item_key": _SECOND_ITEM_KEY,
    },
)
_SECOND_REVISION_ID = SourceRevisionId.parse(
    "00000000-0000-4000-8000-000000008008"
)
_SECOND_REPRESENTATION_ID = DiscoveryRepresentationId.parse(
    "00000000-0000-4000-8000-000000008009"
)
_SECOND_REQUEST_ID = CheckRequestId.parse(
    "00000000-0000-4000-8000-000000008001"
)
_SECOND_ATTEMPT_ID = CheckAttemptId.parse(
    "00000000-0000-4000-8000-000000008002"
)
_SECOND_OUTCOME_ID = CheckOutcomeId.parse(
    "00000000-0000-4000-8000-000000008003"
)
_SECOND_OCCURRENCE_ID = DiscoveryOccurrenceId.parse(
    "00000000-0000-4000-8000-000000008016"
)
_SECOND_BASELINE_ID = BaselineDecisionId.parse(
    "00000000-0000-4000-8000-000000008012"
)
_SECOND_TRANSITION_ID = ObservableTransitionId.parse(
    "00000000-0000-4000-8000-000000008013"
)
_SECOND_ADAPTER_REQUEST_ID = AdapterRequestId.parse(
    "00000000-0000-4000-8000-000000008010"
)
_SECOND_PROPOSAL_ID = ObservationProposalId.parse(
    "00000000-0000-4000-8000-000000008011"
)
_SECOND_SIGNAL_ID = DiscoverySignalId.parse(
    "00000000-0000-4000-8000-000000008020"
)
_SECOND_GATE_ID = GateDecisionId.parse(
    "00000000-0000-4000-8000-000000008021"
)
_SECOND_LEAD_ID = NewsLeadId.parse(
    "00000000-0000-4000-8000-000000008022"
)
_SECOND_DISPOSITION_ID = LeadDispositionDecisionId.parse(
    "00000000-0000-4000-8000-000000008023"
)


def _second_source_plan(system) -> SignalLeadAdmissionRequest:
    item_key = _SECOND_ITEM_KEY
    state_digest = "sha256:" + "2" * 64
    adapter_digest = "sha256:" + "3" * 64
    body_digest = "sha256:" + "4" * 64
    receipt_digest = "sha256:" + "5" * 64
    capture_digest = "sha256:" + "6" * 64
    rights_id = "00000000-0000-4000-8000-000000008099"

    definition = replace(
        definition_request(),
        definition_id=_SECOND_DEFINITION_ID,
        name="Second fixture originating authority",
        idempotency_key="second-source-definition",
    )
    version = replace(
        version_request(),
        version_id=_SECOND_VERSION_ID,
        definition_id=_SECOND_DEFINITION_ID,
        locator="fixture://increment-3d/second-originating-authority",
        rights=replace(
            version_request().rights,
            rights_decision_id=rights_id,
        ),
        change_reason="Second source proves cross-source lineage separation.",
        idempotency_key="second-source-version",
    )
    check = replace(
        check_request(),
        request_id=_SECOND_REQUEST_ID,
        definition_id=_SECOND_DEFINITION_ID,
        definition_version_id=_SECOND_VERSION_ID,
        rights_decision_id=rights_id,
        adapter_request_digest=adapter_digest,
        producer_slot_digest=item_key,
        idempotency_key="second-check-request",
    )
    attempt = replace(
        check_attempt(),
        attempt_id=_SECOND_ATTEMPT_ID,
        request_id=_SECOND_REQUEST_ID,
        adapter_request_id=_SECOND_ADAPTER_REQUEST_ID,
        adapter_request_digest=adapter_digest,
        idempotency_key="second-check-attempt",
    )
    candidate = CandidateObservationRef(item_key, state_digest)
    outcome = replace(
        changed_outcome(),
        outcome_id=_SECOND_OUTCOME_ID,
        request_id=_SECOND_REQUEST_ID,
        attempt_id=_SECOND_ATTEMPT_ID,
        proposal_id=_SECOND_PROPOSAL_ID,
        definition_id=_SECOND_DEFINITION_ID,
        definition_version_id=_SECOND_VERSION_ID,
        receipt_digest=receipt_digest,
        capture_digest=capture_digest,
        parser_result_digest=adapter_digest,
        source_body_digest=body_digest,
        producer_slot_digest=item_key,
        representation_digest=state_digest,
        candidate_observations=(candidate,),
        observed_items=(candidate,),
        idempotency_key="second-check-outcome",
    )
    item = replace(
        item_request(),
        item_id=_SECOND_ITEM_ID,
        definition_id=_SECOND_DEFINITION_ID,
        definition_version_id=_SECOND_VERSION_ID,
        identity_components=(
            IdentityComponent("document_class", "guidance"),
            IdentityComponent("publisher_key", "second-fixture-authority"),
        ),
        idempotency_key="second-source-item",
    )
    revision = replace(
        revision_request(),
        revision_id=_SECOND_REVISION_ID,
        item_id=_SECOND_ITEM_ID,
        definition_version_id=_SECOND_VERSION_ID,
        source_native_revision_token="second-source-revision-1",
        permitted_state_digest=state_digest,
        idempotency_key="second-source-revision",
    )
    representation = replace(
        representation_request(),
        representation_id=_SECOND_REPRESENTATION_ID,
        revision_id=_SECOND_REVISION_ID,
        definition_version_id=_SECOND_VERSION_ID,
        permitted_fields_digest=capture_digest,
        representation_digest=state_digest,
        idempotency_key="second-source-representation",
    )
    occurrence = replace(
        occurrence_request(),
        occurrence_id=_SECOND_OCCURRENCE_ID,
        check_outcome_id=_SECOND_OUTCOME_ID,
        revision_id=_SECOND_REVISION_ID,
        representation_id=_SECOND_REPRESENTATION_ID,
        definition_version_id=_SECOND_VERSION_ID,
        receipt_digest=receipt_digest,
        idempotency_key="second-source-occurrence",
    )
    entry = replace(
        baseline_entry(),
        item_key=item_key,
        item_id=_SECOND_ITEM_ID,
        revision_id=_SECOND_REVISION_ID,
    )
    baseline = replace(
        baseline_decision(),
        decision_id=_SECOND_BASELINE_ID,
        definition_id=_SECOND_DEFINITION_ID,
        definition_version_id=_SECOND_VERSION_ID,
        check_request_id=_SECOND_REQUEST_ID,
        check_outcome_id=_SECOND_OUTCOME_ID,
        entries=(entry,),
        source_body_digest=body_digest,
        producer_slot_digest=item_key,
        representation_digest=state_digest,
        idempotency_key="second-baseline-decision",
    )
    transition = replace(
        first_transition(),
        transition_id=_SECOND_TRANSITION_ID,
        definition_id=_SECOND_DEFINITION_ID,
        definition_version_id=_SECOND_VERSION_ID,
        check_outcome_id=_SECOND_OUTCOME_ID,
        item_id=_SECOND_ITEM_ID,
        current_revision_id=_SECOND_REVISION_ID,
        representation_id=_SECOND_REPRESENTATION_ID,
        idempotency_key="second-source-transition",
    )

    system.sources.register_definition(definition, proof=proof())
    system.sources.record_definition_version(version, proof=proof())
    system.checks.register_request(check, proof=proof())
    system.checks.start_attempt(attempt, proof=proof())
    system.checks.record_outcome(outcome, proof=proof())
    system.sources.register_item(item, proof=proof())
    system.sources.record_revision(revision, proof=proof())
    system.sources.record_representation(representation, proof=proof())
    system.sources.record_occurrence(occurrence, proof=proof())
    system.checks.decide_baseline(baseline, proof=proof())
    system.checks.record_transition(transition, proof=proof())

    signal = replace(
        exact_signal_request(),
        signal_id=_SECOND_SIGNAL_ID,
        definition_id=_SECOND_DEFINITION_ID,
        definition_version_id=_SECOND_VERSION_ID,
        item_id=_SECOND_ITEM_ID,
        revision_id=_SECOND_REVISION_ID,
        representation_id=_SECOND_REPRESENTATION_ID,
        check_outcome_id=_SECOND_OUTCOME_ID,
        occurrence_id=_SECOND_OCCURRENCE_ID,
        transition_id=_SECOND_TRANSITION_ID,
        idempotency_key="second-discovery-signal",
    )
    gate = replace(
        exact_gate_request(),
        decision_id=_SECOND_GATE_ID,
        signal_id=_SECOND_SIGNAL_ID,
        evaluated_definition_version_id=_SECOND_VERSION_ID,
        coverage=check.coverage,
        rights_decision_id=rights_id,
        idempotency_key="second-gate-decision",
    )
    lead = replace(
        exact_lead_request(),
        lead_id=_SECOND_LEAD_ID,
        signal_id=_SECOND_SIGNAL_ID,
        promoting_gate_decision_id=_SECOND_GATE_ID,
        definition_id=_SECOND_DEFINITION_ID,
        definition_version_id=_SECOND_VERSION_ID,
        item_id=_SECOND_ITEM_ID,
        revision_id=_SECOND_REVISION_ID,
        representation_id=_SECOND_REPRESENTATION_ID,
        occurrence_id=_SECOND_OCCURRENCE_ID,
        transition_id=_SECOND_TRANSITION_ID,
        coverage=check.coverage,
        source_roles=version.roles,
        portfolio_functions=version.portfolio_functions,
        source_dependencies=version.dependencies,
        idempotency_key="second-news-lead",
    )
    disposition = replace(
        exact_initial_disposition(),
        decision_id=_SECOND_DISPOSITION_ID,
        lead_id=_SECOND_LEAD_ID,
        gate_decision_id=_SECOND_GATE_ID,
        urgency_route=lead.urgency,
        idempotency_key="second-initial-disposition",
    )
    return SignalLeadAdmissionRequest(signal, gate, lead, disposition)


def test_cross_source_reports_remain_separate_signals_and_leads(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    with open_discovery_system(database) as system:
        seed_check_lineage(system)
        first = system.discovery.admit_signal_to_lead(
            exact_admission_request(),
            proof=proof(),
        )
        second_plan = _second_source_plan(system)
        second = system.discovery.admit_signal_to_lead(
            second_plan,
            proof=proof(),
        )
        assert first.signal.request.definition_id != second.signal.request.definition_id
        assert first.lead is not None and second.lead is not None
        assert first.lead.request.lead_id != second.lead.request.lead_id

        duplicate_basis = replace(
            second_plan.gate.basis,
            duplicate_signal_id=SIGNAL_ID,
            duplicate_rule=VersionedPolicyRef("fixture-duplicate", "v1"),
        )
        duplicate_reason = StructuredReason(
            code="NOVELTY.EXACT_DUPLICATE",
            basis=second_plan.gate.primary_reason.basis,
            references=(
                ReasonReference(
                    "DISCOVERY_SIGNAL",
                    str(SIGNAL_ID),
                ),
            ),
            explanation="Attempted cross-source suppression must fail closed.",
        )
        duplicate_gate = replace(
            second_plan.gate,
            decision_id=GateDecisionId.parse(
                "00000000-0000-4000-8000-000000008024"
            ),
            decision_ordinal=2,
            previous_decision_id=_SECOND_GATE_ID,
            basis=duplicate_basis,
            outcome=GateOutcome.SUPPRESSED_DUPLICATE,
            primary_reason=duplicate_reason,
            next_action=NextAction(
                NextActionKind.CLOSE,
                "CLOSE_EXACT_DUPLICATE",
                instructions="Do not collapse cross-source authority.",
            ),
            idempotency_key="cross-source-duplicate-attempt",
        )
        with pytest.raises(DiscoveryVersionConflict, match="cross-source"):
            system.discovery.decide_gate(duplicate_gate, proof=proof())

    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM discovery_signals").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM news_leads").fetchone()[0] == 2


def test_gate_rejects_false_current_rights_and_signal_policy(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    with open_discovery_system(database) as system:
        seed_check_lineage(system)
        system.discovery.admit_signal(exact_signal_request(), proof=proof())
        wrong_rights = replace(
            exact_gate_request(),
            rights_decision_id="00000000-0000-4000-8000-000000009099",
            idempotency_key="gate-wrong-current-rights",
        )
        with pytest.raises(DiscoveryVersionConflict, match="rights basis"):
            system.discovery.decide_gate(wrong_rights, proof=proof())

        wrong_signal_policy = replace(
            exact_gate_request(),
            signal_admission_policy=VersionedPolicyRef(
                "different-signal-admission-policy",
                "v2",
            ),
            idempotency_key="gate-wrong-signal-policy",
        )
        with pytest.raises(DiscoveryVersionConflict, match="exact Signal"):
            system.discovery.decide_gate(wrong_signal_policy, proof=proof())
