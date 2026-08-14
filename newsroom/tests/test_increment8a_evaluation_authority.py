from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from newsroom.authority.increment8_evaluation_migrations import (
    INCREMENT8_EVALUATION_MIGRATION_CHECKSUM,
    INCREMENT8_EVALUATION_MIGRATION_NAME,
    Increment8EvaluationBackupError,
    prepare_increment8_evaluation_backup,
)
from newsroom.authority.canonical import digest_bytes
from newsroom.authority.migrations import (
    EXPECTED_MIGRATION_HISTORY,
    EXPECTED_SCHEMA_FINGERPRINT,
    SCHEMA_VERSION,
    apply_pending_migrations,
    schema_fingerprint,
)
from newsroom.increment8.evaluation import (
    EvaluationAuthority,
    EvaluationAuthorityError,
    EvaluationPlan,
    ReleaseEvidenceDecision,
    ReleaseVerdict,
    ReviewRole,
    RightsStatus,
    RunKind,
    build_adjudication,
    build_case,
    build_evaluation_plan,
    build_release_decision,
    build_review_label,
    freeze_epoch,
    open_run,
)
from newsroom.increment8.readiness import (
    INCREMENT_8_READINESS_DIGEST,
    READINESS_CONTRACT_PATH,
)
from newsroom.tests.authority_migration_compatibility import build_exact_prefix

D1 = "sha256:" + "1" * 64
D2 = "sha256:" + "2" * 64
D3 = "sha256:" + "3" * 64
OWNER = "sha256:" + "a" * 64
REVIEWER_1 = "sha256:" + "b" * 64
REVIEWER_2 = "sha256:" + "c" * 64
ADJUDICATOR = "sha256:" + "d" * 64
T0 = "2026-08-14T12:00:00Z"
T1 = "2026-08-14T12:01:00Z"
T2 = "2026-08-14T12:02:00Z"
T3 = "2026-08-14T12:03:00Z"
T4 = "2026-08-14T12:04:00Z"
T5 = "2026-08-14T12:05:00Z"


def _plan_kwargs():
    return {
        "authorised_primary_reviewer_digests": (REVIEWER_1, REVIEWER_2),
        "authorised_secondary_reviewer_digests": (REVIEWER_1, REVIEWER_2),
        "authorised_adjudicator_digests": (ADJUDICATOR,),
        "authorised_release_owner_digests": (OWNER,),
    }


def _facts(
    *,
    geography: str = "GLOBAL",
    language: str = "EN_GB",
    urgency: str = "ROUTINE",
    domains: int = 2,
    failures: int = 2,
    candidate: str = "NO_CANDIDATE",
    transition: str = "UNCHANGED",
):
    return {
        "case_metadata": {
            "geography": geography,
            "language": language,
            "urgency": urgency,
        },
        "source_evidence": {"distinct_domain_count": domains},
        "fixture": {"injected_failure_count": failures},
        "expected": {
            "candidate_outcome": candidate,
            "transition_outcome": transition,
        },
    }


def _report_bytes(
    run,
    *,
    status: str = "PASS",
    zero_failures: tuple[str, ...] = (),
    evidence_manifest_digest: str = D2,
    case_outcomes=None,
) -> bytes:
    from newsroom.increment8.metrics import build_metric_report
    from newsroom.tests.test_increment8b_metrics import (
        _ablations,
        _case_outcomes,
        _contributions,
        _performance,
    )

    plan, epoch, expected_run = _records(RunKind(str(run.payload["run_kind"])))
    assert expected_run == run
    context = (plan, epoch, run)
    outcomes = case_outcomes or _case_outcomes(
        context=context,
        metric_fail="candidate_precision" if status == "FAIL" else None,
        zero_finding=zero_failures[0] if zero_failures else None,
    )
    if len(zero_failures) > 1:
        from newsroom.increment8.metrics import (
            ReviewedCaseOutcome,
            reviewed_case_assessment_label,
        )

        target_index = next(
            index
            for index, outcome in enumerate(outcomes)
            if outcome.zero_tolerance_findings
        )
        target = outcomes[target_index]
        case_document = json.loads(target.canonical_bytes)["payload"]
        from newsroom.increment8.evaluation import EvaluationCase, ReviewLabel
        from newsroom.authority.canonical import canonical_json_bytes

        case = EvaluationCase.from_canonical_bytes(
            canonical_json_bytes(case_document["case"])
        )
        previous_label = ReviewLabel.from_canonical_bytes(
            canonical_json_bytes(case_document["review_label"])
        )
        previous_secondary = (
            None
            if case_document["secondary_review_label"] is None
            else ReviewLabel.from_canonical_bytes(
                canonical_json_bytes(case_document["secondary_review_label"])
            )
        )
        findings = tuple(sorted(zero_failures))
        replacement_label = build_review_label(
            case=case,
            reviewer_identity_digest=previous_label.payload["reviewer_identity_digest"],
            role=ReviewRole.PRIMARY,
            label=reviewed_case_assessment_label(
                case=case,
                metric_eligible=target.metric_eligible,
                metric_success=target.metric_success,
                triage_eligible=target.triage_eligible,
                triage_error=target.triage_error,
                slice_success=target.slice_success,
                zero_tolerance_findings=findings,
            ),
            blinded=previous_label.payload["blinded"],
            recorded_at=previous_label.payload["recorded_at"],
        )
        replacement = ReviewedCaseOutcome.build(
            case=case,
            review_label=replacement_label,
            secondary_review_label=previous_secondary,
            metric_eligible=target.metric_eligible,
            metric_success=target.metric_success,
            triage_eligible=target.triage_eligible,
            triage_error=target.triage_error,
            slice_success=target.slice_success,
            zero_tolerance_findings=findings,
        )
        outcomes = (
            *outcomes[:target_index],
            replacement,
            *outcomes[target_index + 1 :],
        )
        outcomes = tuple(sorted(outcomes, key=lambda item: item.case_id))
    report = build_metric_report(
        plan=plan,
        epoch=epoch,
        run=run,
        case_outcomes=outcomes,
        performance=_performance(),
        contributions=_contributions(),
        ablations=_ablations(),
        metric_code_digest="sha256:" + "9" * 64,
        environment_digest="sha256:" + "a" * 64,
        sampling_manifest_digest=evidence_manifest_digest,
        label_manifest_digest=evidence_manifest_digest,
    )
    return report.canonical_bytes


def _database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, isolation_level=None)
    connection.execute("PRAGMA foreign_keys=ON")
    apply_pending_migrations(connection, applied_at=T0)
    return connection


def _records(kind: RunKind = RunKind.QUALIFICATION):
    plan = build_evaluation_plan(
        approved_by_digest=OWNER,
        approved_at=T0,
        component_manifest_digest=D1,
        **_plan_kwargs(),
    )
    epoch = freeze_epoch(
        plan=plan,
        target_manifest_digest=D1,
        universe_manifest_digest=D2,
        sampling_method_digest=D3,
        cutoff_at=T0,
        opened_at=T0,
    )
    run = open_run(epoch=epoch, kind=kind, started_at=T1)
    return plan, epoch, run


def test_v30_is_checked_additive_schema_and_exact_v29_backup(tmp_path: Path) -> None:
    assert SCHEMA_VERSION >= 30
    assert EXPECTED_MIGRATION_HISTORY[29] == (
        30,
        INCREMENT8_EVALUATION_MIGRATION_NAME,
        INCREMENT8_EVALUATION_MIGRATION_CHECKSUM,
    )
    old = tmp_path / "authority-v29.sqlite3"
    build_exact_prefix(old, 29)
    connection = sqlite3.connect(old, isolation_level=None)
    try:
        backup = tmp_path / "authority-v29.backup.sqlite3"
        receipt = prepare_increment8_evaluation_backup(connection, backup)
        assert receipt.backup_path == backup
        apply_pending_migrations(connection, applied_at=T1)
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert schema_fingerprint(connection) == EXPECTED_SCHEMA_FINGERPRINT
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        retained = sqlite3.connect(f"file:{backup}?mode=ro", uri=True)
        try:
            assert retained.execute("PRAGMA user_version").fetchone()[0] == 29
        finally:
            retained.close()
    finally:
        connection.close()


def test_v29_upgrade_fails_without_prepared_backup(tmp_path: Path) -> None:
    path = tmp_path / "authority-v29.sqlite3"
    build_exact_prefix(path, 29)
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        with pytest.raises(Increment8EvaluationBackupError, match="prepared backup"):
            apply_pending_migrations(connection, applied_at=T1)
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 29
    finally:
        connection.close()


def test_plan_binds_exact_pre_measurement_values_and_round_trips() -> None:
    plan, epoch, run = _records()
    assert plan.payload["readiness_digest"] == INCREMENT_8_READINESS_DIGEST
    assert (
        plan.payload["plan_definition"]
        == json.loads(READINESS_CONTRACT_PATH.read_bytes())["payload"][
            "evaluation_plan"
        ]
    )
    assert plan.payload["calibration_may_qualify_selected_values"] is False
    assert epoch.payload["frozen"] is True
    assert run.payload["run_kind"] == "QUALIFICATION"
    assert EvaluationPlan.from_canonical_bytes(plan.canonical_bytes) == plan


def test_qualification_cases_are_prospective_and_unreviewable_is_explicit() -> None:
    _, _, run = _records()
    with pytest.raises(EvaluationAuthorityError, match="prospective"):
        build_case(
            run=run,
            input_manifest_digest=D1,
            cutoff_at=T2,
            membership_facts=_facts(),
            rights_status=RightsStatus.REVIEWABLE,
            prospective=False,
        )
    case = build_case(
        run=run,
        input_manifest_digest=D1,
        cutoff_at=T2,
        membership_facts=_facts(),
        rights_status=RightsStatus.UNREVIEWABLE,
        prospective=True,
    )
    with pytest.raises(EvaluationAuthorityError, match="unreviewable"):
        build_review_label(
            case=case,
            reviewer_identity_digest=REVIEWER_1,
            role=ReviewRole.PRIMARY,
            label="expected-route",
            blinded=True,
            recorded_at=T1,
        )


def test_independent_review_and_adjudication_are_enforced() -> None:
    _, _, run = _records()
    case = build_case(
        run=run,
        input_manifest_digest=D1,
        cutoff_at=T2,
        membership_facts=_facts(urgency="URGENT"),
        rights_status=RightsStatus.REVIEWABLE,
        prospective=True,
        launch_blocker=True,
        urgent=True,
    )
    primary = build_review_label(
        case=case,
        reviewer_identity_digest=REVIEWER_1,
        role=ReviewRole.PRIMARY,
        label="route-a",
        blinded=True,
        recorded_at=T3,
    )
    same_reviewer = build_review_label(
        case=case,
        reviewer_identity_digest=REVIEWER_1,
        role=ReviewRole.SECONDARY,
        label="route-b",
        blinded=True,
        recorded_at=T3,
    )
    with pytest.raises(EvaluationAuthorityError, match="independent"):
        build_adjudication(
            case=case,
            primary=primary,
            secondary=same_reviewer,
            adjudicator_identity_digest=ADJUDICATOR,
            final_label="route-a",
            decided_at=T4,
        )
    secondary = build_review_label(
        case=case,
        reviewer_identity_digest=REVIEWER_2,
        role=ReviewRole.SECONDARY,
        label="route-b",
        blinded=True,
        recorded_at=T3,
    )
    adjudication = build_adjudication(
        case=case,
        primary=primary,
        secondary=secondary,
        adjudicator_identity_digest=ADJUDICATOR,
        final_label="route-a",
        decided_at=T4,
    )
    assert adjudication.payload["primary_label_digest"] == primary.digest


def test_calibration_and_early_stop_never_pass() -> None:
    _, _, calibration = _records(RunKind.CALIBRATION)
    with pytest.raises(EvaluationAuthorityError, match="release rule"):
        build_release_decision(
            run=calibration,
            report_canonical_bytes=b"not used for a calibration PASS",
            evidence_manifest_digest=D2,
            verdict=ReleaseVerdict.PASS,
            owner_identity_digest=OWNER,
            decided_at=T1,
        )
    _, _, qualification = _records()
    with pytest.raises(EvaluationAuthorityError, match="retained Metric Report"):
        build_release_decision(
            run=qualification,
            report_canonical_bytes=_report_bytes(qualification),
            evidence_manifest_digest=D2,
            verdict=ReleaseVerdict.PASS,
            owner_identity_digest=OWNER,
            decided_at=T1,
            early_stopped=True,
        )


def test_append_only_authority_retains_failed_run_and_rejects_mutation(
    tmp_path: Path,
) -> None:
    connection = _database(tmp_path / "authority.sqlite3")
    try:
        authority = EvaluationAuthority(connection)
        plan, epoch, run = _records()
        authority.register_plan(plan)
        authority.register_epoch(epoch)
        authority.register_run(run)
        case = build_case(
            run=run,
            input_manifest_digest=D1,
            cutoff_at=T2,
            membership_facts=_facts(),
            rights_status=RightsStatus.REVIEWABLE,
            prospective=True,
        )
        authority.register_case(case)
        from newsroom.increment8.metrics import (
            ReviewedCaseOutcome,
            reviewed_case_assessment_label,
        )
        from newsroom.tests.test_increment8b_metrics import (
            _CASE_RATE_NAMES,
            _TRIAGE_NAMES,
        )

        metric_eligible = {name: True for name in _CASE_RATE_NAMES}
        metric_success = {name: True for name in _CASE_RATE_NAMES}
        metric_success["candidate_precision"] = False
        triage_error = {name: False for name in _TRIAGE_NAMES}
        triage_eligible = {name: True for name in _TRIAGE_NAMES}
        label = build_review_label(
            case=case,
            reviewer_identity_digest=REVIEWER_1,
            role=ReviewRole.PRIMARY,
            label=reviewed_case_assessment_label(
                case=case,
                metric_eligible=metric_eligible,
                metric_success=metric_success,
                triage_eligible=triage_eligible,
                triage_error=triage_error,
                slice_success=True,
            ),
            blinded=True,
            recorded_at=T3,
        )
        authority.record_label(label)
        case_outcome = ReviewedCaseOutcome.build(
            case=case,
            review_label=label,
            metric_eligible=metric_eligible,
            metric_success=metric_success,
            triage_eligible=triage_eligible,
            triage_error=triage_error,
            slice_success=True,
        )
        manifest = authority.evidence_manifest_digest(run.run_id)
        decision = build_release_decision(
            run=run,
            report_canonical_bytes=_report_bytes(
                run,
                status="FAIL",
                evidence_manifest_digest=manifest,
                case_outcomes=(case_outcome,),
            ),
            evidence_manifest_digest=manifest,
            verdict=ReleaseVerdict.INCONCLUSIVE,
            owner_identity_digest=OWNER,
            decided_at=T5,
            early_stopped=True,
        )
        authority.decide_release(decision)
        assert (
            authority.read_record(
                "evaluation_release_decisions", "decision_id", decision.decision_id
            )
            == decision.canonical_bytes
        )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE evaluation_release_decisions SET verdict='PASS' WHERE decision_id=?",
                (decision.decision_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="retained"):
            connection.execute(
                "DELETE FROM evaluation_release_decisions WHERE decision_id=?",
                (decision.decision_id,),
            )
    finally:
        connection.close()


def test_pass_requires_full_exposure_primary_labels_and_second_review_sample(
    tmp_path: Path,
) -> None:
    connection = _database(tmp_path / "authority.sqlite3")
    try:
        authority = EvaluationAuthority(connection)
        plan, epoch, run = _records()
        authority.register_plan(plan)
        authority.register_epoch(epoch)
        authority.register_run(run)
        manifest = authority.evidence_manifest_digest(run.run_id)
        candidate = build_release_decision(
            run=run,
            report_canonical_bytes=_report_bytes(
                run, evidence_manifest_digest=manifest
            ),
            evidence_manifest_digest=manifest,
            verdict=ReleaseVerdict.PASS,
            owner_identity_digest=OWNER,
            decided_at=T5,
        )
        with pytest.raises(EvaluationAuthorityError, match="outcomes differ"):
            authority.decide_release(candidate)

        # The authority gate also rejects a caller that bypasses the public
        # builder and assembles canonical PASS-shaped bytes directly.
        report_raw = _report_bytes(run, evidence_manifest_digest=manifest)
        report = json.loads(report_raw)
        direct = ReleaseEvidenceDecision.build(
            {
                "run_id": run.run_id,
                "run_digest": run.digest,
                "report_digest": digest_bytes(report_raw),
                "metric_report": report,
                "evidence_manifest_digest": manifest,
                "verdict": ReleaseVerdict.PASS.value,
                "owner_identity_digest": OWNER,
                "decided_at": T5,
                "metrics_passed": True,
                "required_slices_passed": True,
                "zero_tolerance_failure_count": 0,
                "early_stopped": False,
                "production_activation_authorised": False,
            }
        )
        with pytest.raises(EvaluationAuthorityError, match="outcomes differ"):
            authority.decide_release(direct)
        assert connection.execute(
            "SELECT COUNT(*) FROM evaluation_release_decisions"
        ).fetchone() == (0,)
    finally:
        connection.close()
