from __future__ import annotations

import json
import sqlite3
from dataclasses import replace

import pytest

from newsroom.authority.canonical import digest_bytes
from newsroom.increment9.controller import (
    CHECK_IDS,
    CONTROLLER_STAGES,
    RECOVERY_SCENARIOS,
    STAGE_MANIFEST_DIMENSIONS,
    ControllerError,
    ControllerEvidenceJournal,
    ControllerQualificationDisposition,
    ControllerQualificationPlan,
    ControllerQualificationReceipt,
    ControllerEvidenceBundle,
    LedgerKind,
    ReplayIntegrationController,
    ScenarioOutcome,
    StageFixture,
    qualify_controller,
    initialise_controller_journal,
)
from newsroom.increment9.deployment import (
    INCREMENT9_SHADOW_SCHEMA_FINGERPRINT,
    INCREMENT9_SHADOW_SCHEMA_VERSION,
    ISOLATED_DIRECTORY_INVENTORY,
    ISOLATED_FILE_INVENTORY,
    PRODUCTION_MIGRATION_HISTORY_DIGEST,
    PRODUCTION_SCHEMA_FINGERPRINT,
    PRODUCTION_SCHEMA_VERSION,
    IsolatedDeploymentReceipt,
    qualify_deployment,
)
from newsroom.increment9.epoch import RunKind, RunAttempt, ShadowRun

from .test_increment9a2_shadow_deployment import D, _bundle, _plan, _scope
from .test_increment9b1_shadow_epoch import _cohort, _epoch, _manifest


T6 = "2042-01-01T00:06:00.000000Z"
T7 = "2042-01-01T00:07:00.000000Z"
T8 = "2042-01-01T00:08:00.000000Z"


def _isolated(plan):
    return IsolatedDeploymentReceipt(
        receipt_id="isolated-9b2",
        deployment_plan_digest=plan.canonical_digest,
        root_identity_digest=D("a"),
        directory_inventory=ISOLATED_DIRECTORY_INVENTORY,
        protected_file_digests={path: D("b") for path in ISOLATED_FILE_INVENTORY},
        epoch_schema_version=INCREMENT9_SHADOW_SCHEMA_VERSION,
        epoch_schema_fingerprint=INCREMENT9_SHADOW_SCHEMA_FINGERPRINT,
        epoch_backup_restore_digest=D("c"),
        production_snapshot_digest=plan.production_snapshot_digest,
        production_snapshot_schema_version=PRODUCTION_SCHEMA_VERSION,
        production_snapshot_schema_fingerprint=PRODUCTION_SCHEMA_FINGERPRINT,
        production_snapshot_migration_history_digest=PRODUCTION_MIGRATION_HISTORY_DIGEST,
        production_snapshot_backup_restore_digest=D("d"),
        graphiti_workspace=plan.graphiti_workspace,
        neo4j_database=plan.neo4j_database,
        neo4j_namespace=plan.neo4j_namespace,
        created_at="2042-01-01T00:02:30.000000Z",
    )


def _records():
    scope = _scope()
    deployment = _plan()
    readiness = qualify_deployment(deployment, _bundle(deployment), receipt_id="ready-9b2")
    epoch = replace(
        _epoch(),
        shadow_scope_digest=deployment.scope_digest,
        opened_at="2042-01-01T00:00:00.000000Z",
        cutoff_at="2042-01-01T00:00:00.000000Z",
    )
    manifest = _manifest("a", resolved=True)
    cohort = _cohort(epoch, manifest, opened_at="2042-01-01T00:01:00.000000Z")
    run = ShadowRun(
        run_id="run-9b2-replay",
        epoch_id=epoch.epoch_id,
        epoch_digest=epoch.canonical_digest,
        cohort_id=cohort.cohort_id,
        cohort_digest=cohort.canonical_digest,
        manifest_digest=manifest.canonical_digest,
        production_snapshot_digest=deployment.production_snapshot_digest,
        production_nonmutation_before_digest=D("e"),
        run_kind=RunKind.REPLAY_QUALIFICATION,
        started_at=T6,
        prospective=False,
    )
    attempt = RunAttempt(
        attempt_id="attempt-9b2-replay",
        run_id=run.run_id,
        run_digest=run.canonical_digest,
        ordinal=1,
        previous_attempt_digest=None,
        started_at=T6,
        restart_reason=None,
    )
    return scope, deployment, readiness, _isolated(deployment), epoch, manifest, cohort, run, attempt


def _controller_plan() -> ControllerQualificationPlan:
    scope, deployment, readiness, isolated, epoch, manifest, cohort, run, attempt = _records()
    return ControllerQualificationPlan.build(
        qualification_id="controller-qualification-9b2",
        scope=scope,
        deployment_plan=deployment,
        readiness_receipt=readiness,
        isolated_deployment_receipt=isolated,
        epoch=epoch,
        effective_manifest=manifest,
        cohort=cohort,
        run=run,
        attempt=attempt,
        stage_interface_digests={
            stage: manifest.identity_digests[STAGE_MANIFEST_DIMENSIONS[stage]]
            for stage in CONTROLLER_STAGES
        },
        created_at=T6,
        expires_at="2042-01-02T00:00:00.000000Z",
    )


def _fixtures(plan: ControllerQualificationPlan) -> tuple[StageFixture, ...]:
    fixtures = []
    request = D("1")
    for index, stage in enumerate(CONTROLLER_STAGES):
        response = D(format((index + 2) % 16, "x"))
        fixtures.append(
            StageFixture(
                stage=stage,
                target_interface_digest=plan.stage_interface_digests[str(stage)],
                rights_receipt_digest=D("2"),
                purpose_digest=D("3"),
                credential_scope_digest=D("4"),
                egress_receipt_digest=D("5"),
                budget_reservation_digest=D("6"),
                freshness_digest=D("7"),
                request_digest=request,
                response_digest=response,
                proposal_digest=D("a") if str(stage) == "GRAPHITI_PROPOSAL" else None,
                decision_digest=D("b") if str(stage) in {
                    "DETERMINISTIC_ADMISSION", "TRIAGE", "CANDIDATE", "HANDOFF", "EVALUATION_SINK"
                } else None,
                checkpoint_digest=D("c"),
                usage_digest=D("d"),
                cost_digest=D("e"),
                watermark=f"watermark-{index:02d}",
                started_at=T7,
                completed_at=T7,
            )
        )
        request = response
    return tuple(fixtures)


def _evidence(plan: ControllerQualificationPlan):
    return _controller(plan).qualify(
        fixtures=_fixtures(plan),
        scenario_evidence_digests={item: D("7") for item in RECOVERY_SCENARIOS},
        check_evidence_digests={item: D("8") for item in CHECK_IDS},
        equivalence_evidence_digests={
            item: D("9") for item in plan.production_difference_ids
        },
        sealed_at=T8,
        production_nonmutation_after_digest=plan.production_nonmutation_before_digest,
    )


def _controller(plan: ControllerQualificationPlan) -> ReplayIntegrationController:
    return ReplayIntegrationController(
        plan, initialise_controller_journal(sqlite3.connect(":memory:"))
    )


def test_plan_binds_all_predecessor_authorities_and_no_effects() -> None:
    plan = _controller_plan()
    assert plan.owner_plan_digest
    assert plan.run_kind is RunKind.REPLAY_QUALIFICATION
    assert tuple(plan.stage_interface_digests) == tuple(str(stage) for stage in CONTROLLER_STAGES)
    assert plan.authorises_live_call is False
    assert plan.authorises_credentials is False
    assert plan.authorises_external_egress is False
    assert plan.authorises_spend is False
    assert plan.authorises_publication is False
    assert plan.authorises_evidence_intake is False
    assert plan.authorises_production_mutation is False
    assert plan.authorises_decision_bearing_campaign is False


def test_plan_strict_canonical_round_trip_and_tamper_rejection() -> None:
    plan = _controller_plan()
    assert ControllerQualificationPlan.from_bytes(plan.canonical_bytes) == plan
    with pytest.raises(ControllerError, match="canonical"):
        ControllerQualificationPlan.from_bytes(json.dumps(plan.primitive()).encode())
    duplicate = plan.canonical_bytes.replace(b'{"attempt_digest"', b'{"attempt_digest":"' + "0".encode() * 64 + b'","attempt_digest"', 1)
    with pytest.raises(ControllerError):
        ControllerQualificationPlan.from_bytes(duplicate)


def test_plan_rejects_not_ready_unresolved_wrong_run_and_cross_binding() -> None:
    scope, deployment, readiness, isolated, epoch, manifest, cohort, run, attempt = _records()
    kwargs = dict(
        qualification_id="controller-qualification-9b2",
        scope=scope,
        deployment_plan=deployment,
        readiness_receipt=readiness,
        isolated_deployment_receipt=isolated,
        epoch=epoch,
        effective_manifest=manifest,
        cohort=cohort,
        run=run,
        attempt=attempt,
        stage_interface_digests={
            stage: manifest.identity_digests[STAGE_MANIFEST_DIMENSIONS[stage]]
            for stage in CONTROLLER_STAGES
        },
        created_at=T6,
        expires_at="2042-01-02T00:00:00.000000Z",
    )
    with pytest.raises(ControllerError, match="readiness"):
        ControllerQualificationPlan.build(**{**kwargs, "readiness_receipt": replace(readiness, disposition="NOT_READY", reason="READINESS_EVIDENCE_INCOMPLETE_OR_FAILED", actual_service_probe_ids=(), actual_host_probe_ids=(), production_nonmutation_proved=False, teardown_complete=False)})
    unresolved = _manifest("a", resolved=False)
    with pytest.raises(ControllerError, match="resolved"):
        ControllerQualificationPlan.build(**{**kwargs, "effective_manifest": unresolved})
    wrong_run = replace(run, run_kind=RunKind.READINESS_PROBE)
    with pytest.raises(ControllerError, match="replay"):
        ControllerQualificationPlan.build(**{**kwargs, "run": wrong_run, "attempt": replace(attempt, run_digest=wrong_run.canonical_digest)})
    with pytest.raises(ControllerError, match="scope"):
        ControllerQualificationPlan.build(**{**kwargs, "scope": replace(scope, scope_id="other-scope")})


def test_replay_executes_exact_stage_path_and_persists_before_downstream() -> None:
    plan = _controller_plan()
    evidence = _evidence(plan)
    assert tuple(item.stage for item in evidence.stages) == CONTROLLER_STAGES
    assert tuple(item.scenario for item in evidence.scenarios) == RECOVERY_SCENARIOS
    assert tuple(item.check_id for item in evidence.checks) == CHECK_IDS
    assert [entry.ordinal for entry in evidence.ledger] == list(range(1, len(evidence.ledger) + 1))
    for previous, current in zip(evidence.ledger, evidence.ledger[1:], strict=False):
        assert current.previous_entry_digest == previous.canonical_digest
    first_by_stage = {stage: next(entry for entry in evidence.ledger if entry.stage is stage) for stage in CONTROLLER_STAGES}
    last_by_stage = {stage: [entry for entry in evidence.ledger if entry.stage is stage][-1] for stage in CONTROLLER_STAGES}
    for previous, current in zip(CONTROLLER_STAGES, CONTROLLER_STAGES[1:], strict=False):
        assert first_by_stage[current].ordinal == last_by_stage[previous].ordinal + 1
        assert first_by_stage[current].kind is LedgerKind.CONTROL_ENVELOPE
    assert evidence.external_request_count == 0
    assert evidence.provider_call_count == 0
    assert evidence.credential_use_count == 0
    assert evidence.gross_monetary_minor_units == 0
    assert evidence.decision_bearing_case_count == 0


def test_graphiti_is_proposal_only_and_deterministic_stages_are_sole_committers() -> None:
    evidence = _evidence(_controller_plan())
    proposal = next(item for item in evidence.stages if str(item.stage) == "GRAPHITI_PROPOSAL")
    admission = next(item for item in evidence.stages if str(item.stage) == "DETERMINISTIC_ADMISSION")
    assert proposal.proposal_digest is not None and proposal.decision_digest is None
    assert admission.proposal_digest is None and admission.decision_digest is not None
    assert evidence.proposal_authority_commit_count == 0
    assert evidence.deterministic_authority_commit_count == 5


def test_recovery_inventory_blocks_lost_partial_ambiguous_and_kill_evidence() -> None:
    evidence = _evidence(_controller_plan())
    outcomes = {str(item.scenario): item.outcome for item in evidence.scenarios}
    assert outcomes["RESTART_REPLAY"] is ScenarioOutcome.RECONCILED
    assert outcomes["DUPLICATE_REQUEST"] is ScenarioOutcome.DEDUPLICATED
    assert outcomes["LOST_RESPONSE"] is ScenarioOutcome.BLOCKED_RECONCILED
    assert outcomes["PARTIAL_RESPONSE"] is ScenarioOutcome.BLOCKED_RECONCILED
    assert outcomes["AMBIGUOUS_EFFECT"] is ScenarioOutcome.BLOCKED_RECONCILED
    assert outcomes["KILL_SWITCH_PROPAGATION"] is ScenarioOutcome.EARLY_STOPPED
    assert outcomes["TEARDOWN_REBUILD"] is ScenarioOutcome.REBUILT
    assert all(item.resumed_decision_bearing is False for item in evidence.scenarios)
    assert all(item.original_failure_retained for item in evidence.scenarios if item.outcome in {ScenarioOutcome.BLOCKED_RECONCILED, ScenarioOutcome.EARLY_STOPPED})


def test_qualification_receipt_is_non_activating_and_exact() -> None:
    plan = _controller_plan()
    evidence = _evidence(plan)
    receipt = qualify_controller(plan, evidence, receipt_id="qualified-9b2")
    assert receipt.disposition is ControllerQualificationDisposition.READY_FOR_9B3_AUTHORISATION_GATE
    assert receipt.production_nonmutation_proved is True
    assert receipt.full_teardown_rebuild_proved is True
    assert receipt.runtime_campaign_authority_still_required is True
    assert receipt.campaign_started is False
    assert receipt.canonical_digest


@pytest.mark.parametrize(
    "change",
    (
        {"production_nonmutation_after_digest": D("f")},
        {"public_effect_count": 1},
        {"production_mutation_count": 1},
        {"evidence_intake_count": 1},
        {"decision_bearing_case_count": 1},
        {"external_request_count": 1},
        {"credential_use_count": 1},
        {"gross_monetary_minor_units": 1},
    ),
)
def test_missing_or_prohibited_evidence_never_passes(change: dict[str, object]) -> None:
    plan = _controller_plan()
    evidence = replace(_evidence(plan), **change)
    receipt = qualify_controller(plan, evidence, receipt_id="blocked-9b2")
    assert receipt.disposition is ControllerQualificationDisposition.NOT_READY
    assert receipt.reason == "CONTROLLER_EVIDENCE_INCOMPLETE_OR_FAILED"


def test_stage_reordering_interface_drift_and_chain_break_fail_closed() -> None:
    plan = _controller_plan()
    evidence_inputs = {
        "scenario_evidence_digests": {item: D("7") for item in RECOVERY_SCENARIOS},
        "check_evidence_digests": {item: D("8") for item in CHECK_IDS},
        "equivalence_evidence_digests": {
            item: D("9") for item in plan.production_difference_ids
        },
        "sealed_at": T8,
        "production_nonmutation_after_digest": plan.production_nonmutation_before_digest,
    }
    fixtures = list(_fixtures(plan))
    fixtures[0], fixtures[1] = fixtures[1], fixtures[0]
    with pytest.raises(ControllerError, match="stage"):
        _controller(plan).qualify(fixtures=tuple(fixtures), **evidence_inputs)
    fixtures = list(_fixtures(plan))
    fixtures[0] = replace(fixtures[0], target_interface_digest=D("f"))
    with pytest.raises(ControllerError, match="interface"):
        _controller(plan).qualify(fixtures=tuple(fixtures), **evidence_inputs)
    fixtures = list(_fixtures(plan))
    fixtures[1] = replace(fixtures[1], request_digest=D("f"))
    with pytest.raises(ControllerError, match="chain"):
        _controller(plan).qualify(fixtures=tuple(fixtures), **evidence_inputs)


def test_all_records_reject_type_confusion_and_unbounded_or_unknown_input() -> None:
    plan = _controller_plan()
    value = plan.primitive()
    value["unknown"] = False
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(ControllerError, match="fields"):
        ControllerQualificationPlan.from_bytes(raw)
    with pytest.raises(ControllerError):
        ControllerQualificationPlan.from_bytes(b"[]")
    with pytest.raises(ControllerError):
        ControllerQualificationPlan.from_bytes(b"{" + b" " * 4_194_304 + b"}")


def test_receipt_digest_changes_with_any_evidence_byte() -> None:
    plan = _controller_plan()
    evidence = _evidence(plan)
    original = qualify_controller(plan, evidence, receipt_id="qualified-9b2")
    changed = replace(evidence, sealed_at="2042-01-01T00:08:01.000000Z")
    revised = qualify_controller(plan, changed, receipt_id="qualified-9b2")
    assert original.controller_evidence_digest != revised.controller_evidence_digest
    assert original.canonical_digest != revised.canonical_digest


def test_bundle_and_receipt_strict_canonical_round_trip() -> None:
    plan = _controller_plan()
    evidence = _evidence(plan)
    receipt = qualify_controller(plan, evidence, receipt_id="qualified-9b2")
    assert ControllerEvidenceBundle.from_bytes(evidence.canonical_bytes) == evidence
    assert ControllerQualificationReceipt.from_bytes(receipt.canonical_bytes) == receipt


def test_missing_recovery_check_or_equivalence_evidence_fails_closed() -> None:
    plan = _controller_plan()
    controller = _controller(plan)
    common = {
        "fixtures": _fixtures(plan),
        "scenario_evidence_digests": {item: D("7") for item in RECOVERY_SCENARIOS},
        "check_evidence_digests": {item: D("8") for item in CHECK_IDS},
        "equivalence_evidence_digests": {
            item: D("9") for item in plan.production_difference_ids
        },
        "sealed_at": T8,
        "production_nonmutation_after_digest": plan.production_nonmutation_before_digest,
    }
    for field in (
        "scenario_evidence_digests",
        "check_evidence_digests",
        "equivalence_evidence_digests",
    ):
        changed = {**common, field: dict(common[field])}
        changed[field].pop(next(iter(changed[field])))
        with pytest.raises(ControllerError, match="evidence inventory"):
            controller.qualify(**changed)


def test_forged_ledger_payload_and_stage_chronology_do_not_qualify() -> None:
    plan = _controller_plan()
    evidence = _evidence(plan)
    ledger = list(evidence.ledger)
    ledger[1] = replace(ledger[1], payload_digest=D("f"))
    forged = replace(evidence, ledger=tuple(ledger))
    assert qualify_controller(plan, forged, receipt_id="forged").disposition is ControllerQualificationDisposition.NOT_READY

    fixtures = list(_fixtures(plan))
    fixtures[1] = replace(
        fixtures[1],
        started_at="2042-01-01T00:06:59.000000Z",
        completed_at="2042-01-01T00:07:00.000000Z",
    )
    with pytest.raises(ControllerError, match="downstream"):
        _controller(plan).qualify(
            fixtures=tuple(fixtures),
            scenario_evidence_digests={item: D("7") for item in RECOVERY_SCENARIOS},
            check_evidence_digests={item: D("8") for item in CHECK_IDS},
            equivalence_evidence_digests={item: D("9") for item in plan.production_difference_ids},
            sealed_at=T8,
            production_nonmutation_after_digest=plan.production_nonmutation_before_digest,
        )


def test_plan_rejects_stage_interface_not_bound_to_effective_manifest() -> None:
    plan = _controller_plan()
    interfaces = dict(plan.stage_interface_digests)
    interfaces["SOURCE"] = D("f")
    with pytest.raises(ControllerError, match="Effective Manifest"):
        replace(plan, stage_interface_digests=interfaces)


def test_append_only_journal_survives_restart_and_rejects_mutation(tmp_path) -> None:
    path = tmp_path / "controller-journal.sqlite3"
    connection = sqlite3.connect(path)
    plan = _controller_plan()
    controller = ReplayIntegrationController(
        plan, initialise_controller_journal(connection)
    )
    evidence = controller.qualify(
        fixtures=_fixtures(plan),
        scenario_evidence_digests={item: D("7") for item in RECOVERY_SCENARIOS},
        check_evidence_digests={item: D("8") for item in CHECK_IDS},
        equivalence_evidence_digests={
            item: D("9") for item in plan.production_difference_ids
        },
        sealed_at=T8,
        production_nonmutation_after_digest=plan.production_nonmutation_before_digest,
    )
    connection.close()

    reopened = sqlite3.connect(path)
    journal = ControllerEvidenceJournal(reopened)
    assert journal.inventory() == evidence.ledger
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        reopened.execute("UPDATE controller_ledger SET entry_bytes=entry_bytes")
    reopened.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        reopened.execute("DELETE FROM controller_ledger")
    reopened.rollback()
    with pytest.raises(ControllerError, match="empty journal"):
        ReplayIntegrationController(plan, journal)
